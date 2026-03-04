"""KOSHA GUIDE 파싱, 인덱싱, 매핑, 검색 서비스

PDF 파싱 → SQLite 저장 → ChromaDB 임베딩 → 산안법 조문 자동 매핑
BM25 하이브리드 검색 지원 (v2.2)
"""
import os
import re
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict

import fitz  # PyMuPDF
import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI
from sqlalchemy.orm import Session

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False

from app.config import settings
from app.utils.text_utils import tokenize_korean
from app.db.models import KoshaGuide, GuideSection as GuideSectionModel, RegGuideMapping

logger = logging.getLogger(__name__)


# ── 분류 사전 라우팅 키워드 사전 ───────────────────────────────
CLASSIFICATION_KEYWORDS = {
    "G": ["일반안전", "사다리", "작업장", "고령", "야간", "교대", "동물원", "공연", "행사",
          "화약", "드럼", "탱크 화기", "화기작업", "폐유", "세척 용접", "무대", "트러스",
          "사육사", "맹수", "굴착 매설물", "교통 안전", "운반차량"],
    "M": ["기계", "선반", "CNC", "밀링", "프레스", "사출", "절삭", "연삭", "소음",
          "셰이퍼", "인간공학", "작업대", "공작기계", "목재가공", "가구 제작", "식음료",
          "유리병", "현미경", "반복작업", "롤러", "컨베이어", "포장기계"],
    "C": ["건설", "철골", "콘크리트", "굴착", "크레인 건설", "비계", "거푸집", "아스팔트",
          "도로포장", "터널", "용접용단", "철골 절단", "가스 절단", "건설현장 용접"],
    "E": ["전기", "감전", "가공전선", "전선로", "배선", "누전", "방폭", "정전기",
          "이온화", "환기설비", "국소배기", "진동", "직무스트레스", "밀폐공간",
          "제어반", "접지", "과전류", "가스감지기", "교정주기", "도장부스", "배기장치",
          "브레이커", "백색증상", "의료기관", "글루타르알데히드", "소독"],
    "P": ["공정안전", "반응기", "화학공장", "혼합", "가연성", "가스 누출", "분진폭발",
          "시약", "시료채취", "화학물질 보관", "공압 이송", "집진기 폭발", "방산구",
          "산알칼리", "혼합 반응", "시약 창고"],
    "H": ["보건", "건강진단", "건강검진", "피부질환", "피부염", "폐질환", "COPD",
          "심폐소생", "CPR", "AED", "구강", "치아", "제련", "중금속", "크롬",
          "심정지", "응급처치", "용융금속", "납 카드뮴", "비철금속", "치아 부식",
          "도금 공장", "산 증기", "정밀검사", "사후관리", "검진 소견", "청력 이상",
          "접촉성피부염", "파마약", "염색약", "만성기침", "호흡곤란", "벤조피렌",
          "아스팔트 포장"],
    "B": ["조선", "선박", "도크", "지게차", "안전대", "끼임", "절단재해",
          "포크리프트", "크레인", "와이어로프", "방폭전기", "방폭등급", "회전기계"],
    "W": ["MSDS", "물질안전보건자료", "한랭", "냉동", "저온", "작업환경", "방한", "동상",
          "냉동창고", "방한복", "저체온"],
    "A": ["측정", "분석", "시료", "노출평가", "작업환경측정"],
    "D": ["설비설계", "분진폭발방지", "배관", "압력용기", "화재폭발방지", "가연성가스", "폭발한계"],
    "F": ["화재", "목재가공", "화재폭발", "목분진", "합판", "집진 덕트"],
    "X": ["위험성평가", "리스크", "밀폐공간 위험", "LNG", "저장탱크"],
    "T": ["시험", "독성시험", "피부자극", "눈자극", "안전성시험", "토끼", "드레이즈", "눈 부식"],
}


def predict_classifications(text: str, max_cls: int = 3) -> list[str]:
    """시나리오 텍스트에서 가장 관련 높은 KOSHA 분류 예측"""
    scores = {}
    text_lower = text.lower()
    for cls, keywords in CLASSIFICATION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[cls] = score
    sorted_cls = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [cls for cls, _ in sorted_cls[:max_cls]]


# CLASSIFICATION_TO_ARTICLE_RANGE → taxonomy.get_article_range_for_classification() 대체 (Phase 2)

# 섹션 타입 분류
SECTION_TYPE_MAP = {
    "목적": "purpose",
    "적용범위": "scope",
    "적용 범위": "scope",
    "용어의 정의": "definition",
    "용어의정의": "definition",
    "정의": "definition",
    "부록": "appendix",
    "서식": "appendix",
    "참고문헌": "appendix",
}


class GuideService:
    _BASE = Path(os.environ.get("OHS_BASE_DIR", "/home/blessjin/cashtoss/ohs"))
    GUIDES_DIR = _BASE / "guide"
    CHROMA_DIR = _BASE / "backend" / "data" / "chromadb"
    COLLECTION_NAME = "kosha_guides"

    def __init__(self):
        self._client: Optional[chromadb.ClientAPI] = None
        self._collection = None
        self._openai = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._bm25_index = None
        self._bm25_docs = None

    @property
    def chroma_client(self):
        if self._client is None:
            self.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.CHROMA_DIR),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.chroma_client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    # ── PDF 파일명 파싱 ─────────────────────────────────────

    def parse_guide_filename(self, filename: str) -> Optional[dict]:
        """파일명에서 가이드 정보 추출

        패턴 1: G-1-2023 제목.pdf
        패턴 2: A-G-1-2025 제목.pdf (복합 분류코드)
        패턴 3: A-32-2018_제목.pdf (언더스코어 구분)
        """
        # 패턴 1: 복합 분류코드 (A-G, E-T 등)
        m = re.match(r"^([A-Z]-[A-Z])-(\d+)-(\d{4})[\s_]+(.+)\.pdf$", filename)
        if m:
            return {
                "classification": m.group(1)[0],  # 첫 글자만 분류코드
                "guide_number": int(m.group(2)),
                "guide_year": int(m.group(3)),
                "title": m.group(4).strip().rstrip("_"),
                "guide_code": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
            }

        # 패턴 2: 기본 패턴 (공백 또는 언더스코어)
        m = re.match(r"^([A-Z])-(\d+)-(\d{4})[\s_]+(.+)\.pdf$", filename)
        if m:
            return {
                "classification": m.group(1),
                "guide_number": int(m.group(2)),
                "guide_year": int(m.group(3)),
                "title": m.group(4).strip().rstrip("_"),
                "guide_code": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
            }

        return None

    # ── 관련법규 추출 ────────────────────────────────────────

    def extract_related_regulations(self, text: str) -> List[str]:
        """PDF 개요 텍스트에서 관련 산안법 조문번호 추출"""
        # 개요 영역만 검색 (상위 3000자)
        overview = text[:3000]

        # 조문번호 직접 매칭
        article_pattern = r"제(\d+)조(?:의\d+)?"
        article_nums = re.findall(article_pattern, overview)

        return list(set(f"제{n}조" for n in article_nums))

    # ── 섹션 분해 ────────────────────────────────────────────

    def classify_section_type(self, title: str) -> str:
        """섹션 제목으로 타입 분류"""
        for keyword, stype in SECTION_TYPE_MAP.items():
            if keyword in title:
                return stype
        return "standard"

    def split_into_sections(self, text: str) -> List[dict]:
        """본문을 섹션 단위로 분할"""
        # 숫자 헤더 패턴: "1. ", "2. " (줄 시작)
        pattern = r"\n(\d+)\.\s+(.+)"
        matches = list(re.finditer(pattern, text))

        if not matches:
            # 섹션 분해 실패 시 전체를 하나의 섹션으로
            if len(text.strip()) > 50:
                return [{
                    "section_order": 1,
                    "section_title": "전체",
                    "section_type": "standard",
                    "body_text": text.strip()[:2000],
                }]
            return []

        sections = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()

            section_title = f"{match.group(1)}. {match.group(2).strip()}"
            section_type = self.classify_section_type(section_title)

            # 2000자 초과 시 재분할
            if len(body) > 2000:
                chunks = self._chunk_text(body, max_chars=2000)
                for j, chunk in enumerate(chunks):
                    sections.append({
                        "section_order": len(sections) + 1,
                        "section_title": section_title if j == 0 else f"{section_title} (계속 {j+1})",
                        "section_type": section_type,
                        "body_text": chunk,
                    })
            else:
                sections.append({
                    "section_order": len(sections) + 1,
                    "section_title": section_title,
                    "section_type": section_type,
                    "body_text": body,
                })

        return sections

    def _chunk_text(self, text: str, max_chars: int = 2000) -> List[str]:
        """긴 텍스트를 단락 기준으로 분할"""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 > max_chars and current:
                chunks.append(current.strip())
                current = para
            else:
                current += "\n\n" + para if current else para

        if current.strip():
            chunks.append(current.strip())

        return chunks if chunks else [text[:max_chars]]

    # ── PDF 파싱 + DB 저장 ───────────────────────────────────

    def parse_and_store_all(self, db: Session, force: bool = False) -> dict:
        """모든 KOSHA GUIDE PDF를 파싱하여 DB에 저장"""
        # 이미 파싱된 경우 스킵
        if not force:
            existing = db.query(KoshaGuide).count()
            if existing > 0:
                logger.info(f"이미 {existing}개 KOSHA GUIDE 파싱됨. 스킵.")
                return {"total_parsed": existing, "total_sections": 0, "skipped": True}

        pdf_files = sorted(self.GUIDES_DIR.glob("*.pdf"))
        logger.info(f"KOSHA GUIDE PDF {len(pdf_files)}개 파싱 시작")

        total_parsed = 0
        total_sections = 0
        errors = []

        for pdf_path in pdf_files:
            try:
                info = self.parse_guide_filename(pdf_path.name)
                if not info:
                    errors.append(f"파일명 파싱 실패: {pdf_path.name}")
                    continue

                # PDF 텍스트 추출
                doc = fitz.open(str(pdf_path))
                full_text = ""
                for page in doc:
                    full_text += page.get_text() + "\n"
                total_pages = len(doc)
                doc.close()

                if len(full_text.strip()) < 100:
                    errors.append(f"텍스트 부족: {pdf_path.name}")
                    continue

                # 관련법규 추출
                related_regs = self.extract_related_regulations(full_text)

                # DB 저장 - kosha_guides
                guide = KoshaGuide(
                    guide_code=info["guide_code"],
                    classification=info["classification"],
                    guide_number=info["guide_number"],
                    guide_year=info["guide_year"],
                    title=info["title"],
                    related_regulations=json.dumps(related_regs, ensure_ascii=False) if related_regs else None,
                    pdf_filename=pdf_path.name,
                    total_pages=total_pages,
                    total_chars=len(full_text),
                )
                db.add(guide)
                db.flush()  # guide.id 할당

                # 섹션 분해 + 저장
                sections = self.split_into_sections(full_text)
                for sec in sections:
                    section = GuideSectionModel(
                        guide_id=guide.id,
                        section_order=sec["section_order"],
                        section_title=sec["section_title"],
                        section_type=sec["section_type"],
                        body_text=sec["body_text"],
                        char_count=len(sec["body_text"]),
                    )
                    db.add(section)
                    total_sections += 1

                total_parsed += 1

                if total_parsed % 100 == 0:
                    db.commit()
                    logger.info(f"파싱 진행: {total_parsed}/{len(pdf_files)}")

            except Exception as e:
                errors.append(f"{pdf_path.name}: {e}")
                continue

        db.commit()
        logger.info(f"파싱 완료: {total_parsed}개 가이드, {total_sections}개 섹션, {len(errors)}개 오류")

        if errors:
            logger.warning(f"파싱 오류 {len(errors)}건: {errors[:10]}")

        return {
            "total_parsed": total_parsed,
            "total_sections": total_sections,
            "errors": len(errors),
            "skipped": False,
        }

    # ── ChromaDB 임베딩/인덱싱 ──────────────────────────────

    def build_index(self, db: Session, force: bool = False) -> int:
        """guide_sections를 임베딩하여 ChromaDB에 인덱싱"""
        if not force and self.collection.count() > 0:
            logger.info(f"이미 {self.collection.count()}개 KOSHA GUIDE 섹션 인덱싱됨. 스킵.")
            return self.collection.count()

        if force and self.collection.count() > 0:
            self.chroma_client.delete_collection(self.COLLECTION_NAME)
            self._collection = None

        # DB에서 섹션 조회
        sections = db.query(GuideSectionModel).all()
        if not sections:
            logger.warning("파싱된 섹션이 없습니다. parse_and_store_all() 먼저 실행.")
            return 0

        # guide_id → guide 정보 매핑
        guides = {g.id: g for g in db.query(KoshaGuide).all()}

        batch_size = 50
        total_indexed = 0

        for i in range(0, len(sections), batch_size):
            batch = sections[i:i + batch_size]
            texts = []
            ids = []
            metadatas = []

            for sec in batch:
                guide = guides.get(sec.guide_id)
                if not guide:
                    continue

                text = f"{guide.guide_code} {guide.title}\n{sec.section_title or ''}\n{sec.body_text}"
                doc_id = f"{guide.guide_code}_{sec.section_order}"

                texts.append(text[:8000])  # embedding input 제한
                ids.append(doc_id)
                metadatas.append({
                    "guide_code": guide.guide_code,
                    "classification": guide.classification,
                    "title": guide.title,
                    "section_order": sec.section_order,
                    "section_title": sec.section_title or "",
                    "section_type": sec.section_type or "standard",
                    "guide_id": guide.id,
                })

            if not texts:
                continue

            try:
                response = self._openai.embeddings.create(
                    model="text-embedding-3-small",
                    input=texts,
                )
                embeddings = [item.embedding for item in response.data]

                self.collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=texts,
                    metadatas=metadatas,
                )
                total_indexed += len(texts)

                if total_indexed % 500 == 0:
                    logger.info(f"인덱싱 진행: {total_indexed}/{len(sections)}")

            except Exception as e:
                logger.error(f"임베딩 배치 실패 (인덱스 {i}): {e}")

        logger.info(f"KOSHA GUIDE 인덱싱 완료: {total_indexed}개 섹션")
        return total_indexed

    # ── 자동 매핑 ────────────────────────────────────────────

    def build_mappings(self, db: Session) -> int:
        """산안법 조문 ↔ KOSHA GUIDE 자동 매핑 생성"""
        existing = db.query(RegGuideMapping).count()
        if existing > 0:
            logger.info(f"이미 {existing}개 매핑 존재. 스킵.")
            return existing

        guides = db.query(KoshaGuide).all()
        total_mappings = 0

        for guide in guides:
            # Stage 1: 명시적 매핑 (관련법규에서 추출)
            if guide.related_regulations:
                try:
                    regs = json.loads(guide.related_regulations)
                    for article_num in regs:
                        mapping = RegGuideMapping(
                            article_number=article_num,
                            guide_id=guide.id,
                            mapping_type="explicit",
                            mapping_basis=f"PDF 관련법규 섹션에서 추출",
                            relevance_score=0.95,
                        )
                        db.merge(mapping)
                        total_mappings += 1
                except (json.JSONDecodeError, Exception):
                    pass

            if total_mappings % 500 == 0 and total_mappings > 0:
                db.commit()
                logger.info(f"매핑 진행: {total_mappings}건")

        db.commit()
        logger.info(f"매핑 완료: {total_mappings}건")
        return total_mappings

    # ── KOSHA GUIDE 검색 ────────────────────────────────────

    def search_guides_for_articles(
        self,
        db: Session,
        article_numbers: List[str],
        hazard_description: str = "",
        n_results: int = 3,
    ) -> List[dict]:
        """관련 법조항에 매핑된 KOSHA GUIDE 검색

        1차: reg_guide_mapping에서 명시적/자동 매핑 조회
        2차: 벡터 검색으로 보충
        """
        guide_results: Dict[str, dict] = {}

        # 1차: 매핑 테이블 조회
        for article_num in article_numbers:
            mappings = (
                db.query(RegGuideMapping, KoshaGuide)
                .join(KoshaGuide, RegGuideMapping.guide_id == KoshaGuide.id)
                .filter(RegGuideMapping.article_number == article_num)
                .order_by(RegGuideMapping.relevance_score.desc())
                .limit(5)
                .all()
            )

            for mapping, guide in mappings:
                if guide.guide_code not in guide_results:
                    # 관련 섹션 조회
                    sections = (
                        db.query(GuideSectionModel)
                        .filter(GuideSectionModel.guide_id == guide.id)
                        .filter(GuideSectionModel.section_type.in_(["standard", "procedure"]))
                        .order_by(GuideSectionModel.section_order)
                        .limit(2)
                        .all()
                    )

                    guide_results[guide.guide_code] = {
                        "guide_code": guide.guide_code,
                        "title": guide.title,
                        "classification": guide.classification,
                        "relevant_sections": [
                            {
                                "section_title": s.section_title or "",
                                "excerpt": s.body_text[:200] if s.body_text else "",
                                "section_type": s.section_type or "standard",
                            }
                            for s in sections
                        ],
                        "relevance_score": min(mapping.relevance_score or 0.9, 0.75),
                        "mapping_type": mapping.mapping_type,
                    }

        # 2차: 벡터 검색으로 보충 (매핑이 부족한 경우)
        if len(guide_results) < n_results and hazard_description and self.collection.count() > 0:
            try:
                query = " ".join(article_numbers) + " " + hazard_description
                response = self._openai.embeddings.create(
                    model="text-embedding-3-small",
                    input=[query],
                )
                query_embedding = response.data[0].embedding

                results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results * 2,
                    include=["metadatas", "distances"],
                )

                if results and results["metadatas"] and results["metadatas"][0]:
                    for i, meta in enumerate(results["metadatas"][0]):
                        code = meta.get("guide_code", "")
                        if code in guide_results:
                            continue

                        distance = results["distances"][0][i] if results["distances"] else 0.5
                        score = round(1 - distance, 4)

                        if score < 0.6:
                            continue

                        guide_results[code] = {
                            "guide_code": code,
                            "title": meta.get("title", ""),
                            "classification": meta.get("classification", ""),
                            "relevant_sections": [{
                                "section_title": meta.get("section_title", ""),
                                "excerpt": "",
                                "section_type": meta.get("section_type", "standard"),
                            }],
                            "relevance_score": score,
                            "mapping_type": "auto",
                        }

                        if len(guide_results) >= n_results:
                            break

            except Exception as e:
                logger.warning(f"KOSHA GUIDE 벡터 검색 실패: {e}")

        # 점수 순 정렬, 상위 n개
        sorted_results = sorted(
            guide_results.values(),
            key=lambda x: x["relevance_score"],
            reverse=True,
        )
        return sorted_results[:n_results]

    # ── BM25 인덱스 (가이드 제목 기반) ─────────────────────────
    def _build_guide_bm25_index(self, db: Session):
        """KOSHA 가이드 제목으로 BM25 인덱스 구축 (lazy)"""
        if not HAS_BM25 or self._bm25_index is not None:
            return
        try:
            guides = db.query(KoshaGuide).all()
            docs = []
            tokenized = []
            for g in guides:
                text = f"{g.guide_code} {g.title} {g.classification}"
                tokens = tokenize_korean(text)
                # 제목에서 중요 단어 추가 (·로 분리된 것도)
                for w in (g.title or "").replace("·", " ").replace(",", " ").split():
                    if len(w) >= 2:
                        tokens.append(w)
                tokenized.append(tokens)
                docs.append({
                    "guide_code": g.guide_code,
                    "title": g.title,
                    "classification": g.classification,
                    "guide_id": g.id,
                })
            if tokenized:
                self._bm25_index = BM25Okapi(tokenized)
                self._bm25_docs = docs
                logger.info(f"KOSHA BM25 인덱스 구축: {len(docs)}개 가이드")
        except Exception as e:
            logger.warning(f"KOSHA BM25 인덱스 실패: {e}")

    def search_guides_bm25(self, db: Session, query_text: str, n_results: int = 5) -> List[dict]:
        """BM25 키워드 기반 KOSHA 가이드 검색"""
        if not HAS_BM25:
            return []
        self._build_guide_bm25_index(db)
        if self._bm25_index is None:
            return []

        tokens = tokenize_korean(query_text.replace("·", " ").replace(",", " "))
        if not tokens:
            return []

        scores = self._bm25_index.get_scores(tokens)
        max_s = max(scores) if max(scores) > 0 else 1
        indexed = [(i, scores[i] / max_s) for i in range(len(scores)) if scores[i] > 0]
        indexed.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, norm_score in indexed[:n_results]:
            doc = self._bm25_docs[idx]
            results.append({
                "guide_code": doc["guide_code"],
                "title": doc["title"],
                "classification": doc["classification"],
                "guide_id": doc["guide_id"],
                "bm25_score": round(norm_score, 4),
            })
        return results

    # ── Path B: 직접 벡터 검색 (법조항 우회) ──────────────────

    # 설명문에서 핵심 명사 자동 추출 (키워드 폴백용)
    _DESC_STOP_WORDS = {
        "위험", "사고", "작업", "안전", "관련", "발생", "가능", "경우", "상태", "조치",
        "방치", "예방", "존재", "높음", "관한", "위한", "대한", "인한", "의한", "따른",
        "통한", "해당", "있어", "있음", "없음", "등으로", "인해", "경미한", "심각한",
        "위험이", "수", "할", "등이", "것이", "놓여", "드러난", "무방비로", "젖었을",
        "가능성이", "이어질", "발생할", "흩어져", "떨어져", "위에", "주변에",
        "사용하여", "바닥이", "바닥에", "과정에서", "실수로", "다듬는", "다칠",
    }

    def _extract_key_nouns(self, descriptions: List[str]) -> List[str]:
        """위험 설명에서 핵심 명사를 추출 (GPT 키워드가 없을 때 폴백)"""
        nouns = []
        for desc in descriptions:
            for token in desc.split():
                # 조사/어미 제거 (간이 처리)
                clean = token.rstrip("이가을를은는에서와도의")
                if len(clean) >= 2 and clean not in self._DESC_STOP_WORDS:
                    nouns.append(clean)
        # 중복 제거, 최대 7개
        seen = set()
        unique = []
        for n in nouns:
            if n not in seen:
                seen.add(n)
                unique.append(n)
        return unique[:7]

    def search_guides_by_description(
        self,
        db: Session,
        hazard_descriptions: List[str],
        guide_keywords: List[str] = None,
        n_results: int = 3,
        exclude_codes: List[str] = None,
    ) -> List[dict]:
        """위험 설명 + GPT 키워드로 KOSHA GUIDE 직접 검색 (법조항 우회)

        Path B: 법조항 매핑 없이 위험 설명에서 바로 관련 가이드를 찾는다.
        키워드가 없으면 설명에서 핵심 명사를 자동 추출하여 사용.
        """
        if self.collection.count() == 0:
            return []

        exclude_codes = exclude_codes or []

        # 검색 쿼리 구성 — "안전지침 기술지침" 접미사는 키워드가 적을 때만 추가
        if guide_keywords:
            # GPT 키워드가 충분하면(3개+) 접미사 없이 키워드만 사용 (dilution 방지)
            if len(guide_keywords) >= 3:
                query = " ".join(guide_keywords)
            else:
                query = " ".join(guide_keywords) + " 안전지침"
        else:
            # 키워드 없음: 설명에서 핵심 명사 추출
            extracted = self._extract_key_nouns(hazard_descriptions)
            if extracted:
                query = " ".join(extracted)
                logger.warning(f"KOSHA Path B: GPT 키워드 없음, 자동추출: {extracted}")
            else:
                query = " ".join(hazard_descriptions)[:500]

        if not query.strip():
            return []

        try:
            response = self._openai.embeddings.create(
                model="text-embedding-3-small",
                input=[query],
            )
            query_embedding = response.data[0].embedding

            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results * 3,
                include=["metadatas", "distances"],
            )

            guide_results: Dict[str, dict] = {}
            # 키워드 개수에 따른 동적 threshold
            if guide_keywords and len(guide_keywords) >= 3:
                threshold = 0.38  # 풍부한 키워드: 더 넓은 검색
            elif guide_keywords:
                threshold = 0.42  # 적은 키워드
            else:
                threshold = 0.30  # 키워드 없음: 최대한 넓게

            if results and results["metadatas"] and results["metadatas"][0]:
                for i, meta in enumerate(results["metadatas"][0]):
                    code = meta.get("guide_code", "")
                    if code in guide_results or code in exclude_codes:
                        continue

                    distance = results["distances"][0][i] if results["distances"] else 0.5
                    score = round(1 - distance, 4)

                    if score < threshold:
                        continue

                    # DB에서 해당 가이드의 핵심 섹션 조회
                    guide_id = meta.get("guide_id")
                    sections = []
                    if guide_id:
                        sections = (
                            db.query(GuideSectionModel)
                            .filter(GuideSectionModel.guide_id == guide_id)
                            .filter(GuideSectionModel.section_type.in_(["standard", "procedure"]))
                            .order_by(GuideSectionModel.section_order)
                            .limit(2)
                            .all()
                        )

                    guide_results[code] = {
                        "guide_code": code,
                        "title": meta.get("title", ""),
                        "classification": meta.get("classification", ""),
                        "relevant_sections": [
                            {
                                "section_title": s.section_title or "",
                                "excerpt": s.body_text[:200] if s.body_text else "",
                                "section_type": s.section_type or "standard",
                            }
                            for s in sections
                        ] if sections else [{
                            "section_title": meta.get("section_title", ""),
                            "excerpt": "",
                            "section_type": meta.get("section_type", "standard"),
                        }],
                        "relevance_score": score,
                        "mapping_type": "direct",
                    }

                    if len(guide_results) >= n_results:
                        break

            return sorted(
                guide_results.values(),
                key=lambda x: x["relevance_score"],
                reverse=True,
            )[:n_results]

        except Exception as e:
            logger.warning(f"KOSHA GUIDE 직접 벡터 검색 실패: {e}")
            return []


    # ── Path C: 키워드 타이틀 직접 매칭 (벡터 검색 보완) ────────

    def search_guides_by_title_keywords(
        self,
        db: Session,
        keywords: List[str],
        n_results: int = 3,
        exclude_codes: List[str] = None,
    ) -> List[dict]:
        """키워드로 가이드 타이틀 직접 검색

        벡터 검색의 non-determinism을 보완하기 위한 결정론적 검색.
        복합 키워드 분리, 2글자 이상만, 단어 경계 매칭.
        """
        exclude_codes = exclude_codes or []
        if not keywords:
            return []

        # 복합 키워드를 개별 단어로 분리, 2글자 이상만 사용
        clean_keywords = []
        for kw in keywords:
            for word in kw.split():
                if len(word) >= 2 and word not in {
                    "안전", "관한", "위한", "대한", "예방", "관리", "작업",
                    "방지", "설치", "기준", "기술", "지침", "규정", "시행",
                    "사용", "보건", "산업", "일반", "운용", "프로그램",
                }:
                    clean_keywords.append(word)
        # 중복 제거
        seen = set()
        clean_keywords = [kw for kw in clean_keywords if not (kw in seen or seen.add(kw))]

        if not clean_keywords:
            return []

        logger.warning(f"[KOSHA] Path C 정제 키워드: {clean_keywords}")

        guides = db.query(KoshaGuide).all()
        scored = []

        for guide in guides:
            if guide.guide_code in exclude_codes:
                continue
            title = guide.title or ""
            # 단어 경계 매칭: 키워드가 타이틀의 독립 단어로 포함되는지 확인
            # "수공구" in "수공구 사용 안전지침" → O
            # "칼" in "수산화칼륨" → X (단어 경계 아님)
            title_words = title.replace("·", " ").replace(",", " ").replace("(", " ").replace(")", " ").split()
            hits = 0
            for kw in clean_keywords:
                # 타이틀의 각 단어에 키워드가 포함되는지 (단어 시작부)
                for tw in title_words:
                    if tw.startswith(kw) or kw == tw:
                        hits += 1
                        break
            if hits > 0:
                # 히트 수 기반 점수 (0.5 + 히트 비율 * 0.3)
                score = 0.5 + (hits / len(clean_keywords)) * 0.3
                sections = (
                    db.query(GuideSectionModel)
                    .filter(GuideSectionModel.guide_id == guide.id)
                    .filter(GuideSectionModel.section_type.in_(["standard", "procedure"]))
                    .order_by(GuideSectionModel.section_order)
                    .limit(2)
                    .all()
                )
                scored.append({
                    "guide_code": guide.guide_code,
                    "title": guide.title,
                    "classification": guide.classification,
                    "relevant_sections": [
                        {
                            "section_title": s.section_title or "",
                            "excerpt": s.body_text[:200] if s.body_text else "",
                            "section_type": s.section_type or "standard",
                        }
                        for s in sections
                    ] if sections else [],
                    "relevance_score": round(score, 4),
                    "mapping_type": "title_match",
                })

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return scored[:n_results]

    # ── 가이드 → 법조항 역매핑 ──────────────────────────────

    def get_mapped_articles_for_guides(
        self,
        db: Session,
        guide_codes: List[str],
    ) -> Dict[str, List[dict]]:
        """KOSHA GUIDE 코드 목록에 대해 매핑된 법조항 조회

        Returns:
            {guide_code: [{"article_number": "제86조", "title": "...", ...}, ...]}
        """
        result: Dict[str, List[dict]] = {}

        guides = (
            db.query(KoshaGuide)
            .filter(KoshaGuide.guide_code.in_(guide_codes))
            .all()
        )

        for guide in guides:
            articles = []
            if guide.related_regulations:
                try:
                    regs = json.loads(guide.related_regulations)
                    for article_num in regs:
                        articles.append({
                            "article_number": article_num,
                            "title": "",
                            "content": "",
                            "source_file": "",
                        })
                except (json.JSONDecodeError, Exception):
                    pass
            result[guide.guide_code] = articles

        return result


guide_service = GuideService()
