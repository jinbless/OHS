"""KOSHA GUIDE 파싱, 인덱싱, 매핑, 검색 서비스

PDF 파싱 → SQLite 저장 → ChromaDB 임베딩 → 산안법 조문 자동 매핑
"""
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

from app.config import settings
from app.db.models import KoshaGuide, GuideSection as GuideSectionModel, RegGuideMapping

logger = logging.getLogger(__name__)


# ── 분류코드 → 산안법 조문 범위 매핑 ─────────────────────────
CLASSIFICATION_TO_ARTICLE_RANGE = {
    "G": None,           # 일반안전 - 전체 범위
    "C": (328, 419),     # 건설안전
    "D": (328, 419),     # 건설안전(설계)
    "E": (301, 327),     # 전기안전
    "M": (86, 224),      # 기계안전
    "P": (225, 300),     # 공정안전(화재폭발)
    "H": (420, 670),     # 보건
    "B": (420, 670),     # 보건(일반)
    "A": (420, 670),     # 작업환경측정
    "W": (420, 670),     # 작업환경(기타)
    "T": None,           # 교육 - 전체 범위
    "X": None,           # 기타 - 전체 범위
    "O": (420, 670),     # 산업보건
    "F": (225, 300),     # 화재폭발
    "K": None,           # KOSHA 기타
}

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
    GUIDES_DIR = Path("/home/blessjin/cashtoss/ohs/guide")
    CHROMA_DIR = Path("/home/blessjin/cashtoss/ohs/backend/data/chromadb")
    COLLECTION_NAME = "kosha_guides"

    def __init__(self):
        self._client: Optional[chromadb.ClientAPI] = None
        self._collection = None
        self._openai = OpenAI(api_key=settings.OPENAI_API_KEY)

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

    # ── Path B: 직접 벡터 검색 (법조항 우회) ──────────────────

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
        """
        if self.collection.count() == 0:
            return []

        exclude_codes = exclude_codes or []

        # 검색 쿼리 구성: 키워드가 있으면 키워드만 사용 (dilution 방지)
        if guide_keywords:
            query = " ".join(guide_keywords) + " 안전지침 기술지침"
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

            if results and results["metadatas"] and results["metadatas"][0]:
                for i, meta in enumerate(results["metadatas"][0]):
                    code = meta.get("guide_code", "")
                    if code in guide_results or code in exclude_codes:
                        continue

                    distance = results["distances"][0][i] if results["distances"] else 0.5
                    score = round(1 - distance, 4)

                    if score < 0.45:
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


guide_service = GuideService()
