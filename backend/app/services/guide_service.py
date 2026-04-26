"""KOSHA GUIDE 인덱싱, 매핑, 검색 서비스

PostgreSQL koshaontology DB 직접 참조 (PDF 파싱 불필요 — 이미 796 guides 적재)
ChromaDB 임베딩 + BM25 하이브리드 검색 유지
"""
import os
import re
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict

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
from app.db.models import (
    PgKoshaGuide as KoshaGuide,
    PgChecklistItem,
    PgGuideArticleMapping,
    PgArticle,
)

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


class GuideService:
    _BASE = Path(os.environ.get("OHS_BASE_DIR", "/home/blessjin/cashtoss/ohs"))
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

    # ── PDF 파싱 (PG에 이미 796 guides 존재 → 스킵) ───────────

    def parse_and_store_all(self, db: Session, force: bool = False) -> dict:
        """PG kosha_guides에 이미 데이터 존재 → 카운트만 반환."""
        existing = db.query(KoshaGuide).count()
        if existing > 0:
            logger.info(f"PG kosha_guides: {existing}개 가이드 (PDF 파싱 불필요)")
            return {"total_parsed": existing, "total_sections": 0, "skipped": True}
        return {"total_parsed": 0, "total_sections": 0, "skipped": True}

    # ── ChromaDB 임베딩/인덱싱 (CI 텍스트 기반) ──────────────

    def build_index(self, db: Session, force: bool = False) -> int:
        """checklist_items를 임베딩하여 ChromaDB에 인덱싱"""
        if not force and self.collection.count() > 0:
            logger.info(f"이미 {self.collection.count()}개 인덱싱됨. 스킵.")
            return self.collection.count()

        if force and self.collection.count() > 0:
            self.chroma_client.delete_collection(self.COLLECTION_NAME)
            self._collection = None

        # PG에서 가이드 정보 로드
        guides = {g.guide_code: g for g in db.query(KoshaGuide).all()}

        # CI를 가이드별로 그룹핑하여 섹션 단위로 인덱싱
        # source_section 기준으로 그룹핑
        from sqlalchemy import func as sa_func
        sections = (
            db.query(
                PgChecklistItem.source_guide,
                PgChecklistItem.source_section,
                sa_func.string_agg(PgChecklistItem.text, '\n')
            )
            .group_by(PgChecklistItem.source_guide, PgChecklistItem.source_section)
            .all()
        )

        if not sections:
            logger.warning("checklist_items가 비어있습니다.")
            return 0

        batch_size = 50
        total_indexed = 0
        batch_texts = []
        batch_ids = []
        batch_metas = []

        for source_guide, source_section, combined_text in sections:
            guide = guides.get(source_guide)
            if not guide or not combined_text:
                continue

            text = f"{guide.guide_code} {guide.title}\n{source_section}\n{combined_text}"
            doc_id = f"{source_guide}_{hash(source_section) % 100000}"

            batch_texts.append(text[:8000])
            batch_ids.append(doc_id)
            batch_metas.append({
                "guide_code": guide.guide_code,
                "classification": guide.domain,
                "title": guide.title,
                "section_order": 0,
                "section_title": source_section or "",
                "section_type": "standard",
                "guide_id": guide.guide_code,
            })

            if len(batch_texts) >= batch_size:
                total_indexed += self._embed_and_add(batch_texts, batch_ids, batch_metas)
                batch_texts, batch_ids, batch_metas = [], [], []

        if batch_texts:
            total_indexed += self._embed_and_add(batch_texts, batch_ids, batch_metas)

        logger.info(f"KOSHA GUIDE 인덱싱 완료: {total_indexed}개 섹션")
        return total_indexed

    def _embed_and_add(self, texts, ids, metadatas) -> int:
        try:
            response = self._openai.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            embeddings = [item.embedding for item in response.data]
            self.collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
            return len(texts)
        except Exception as e:
            logger.error(f"임베딩 배치 실패: {e}")
            return 0

    # ── 자동 매핑 (PG guide_article_mapping 사용) ────────────

    def build_mappings(self, db: Session) -> int:
        """PG guide_article_mapping에 이미 데이터 존재 → 카운트 반환."""
        existing = db.query(PgGuideArticleMapping).count()
        if existing > 0:
            logger.info(f"PG guide_article_mapping: {existing}개 매핑 존재")
            return existing
        logger.info("PG guide_article_mapping: 0건 (Phase 2 Step 2-5에서 이관)")
        return 0

    # ── KOSHA GUIDE 검색 (guide_article_mapping 기반) ────────

    def search_guides_for_articles(
        self,
        db: Session,
        article_numbers: List[str],
        hazard_description: str = "",
        n_results: int = 3,
    ) -> List[dict]:
        """관련 법조항에 매핑된 KOSHA GUIDE 검색

        1차: guide_article_mapping에서 매핑 조회
        2차: 벡터 검색으로 보충
        """
        guide_results: Dict[str, dict] = {}

        # 1차: PG guide_article_mapping 조회
        for article_num in article_numbers:
            mappings = (
                db.query(PgGuideArticleMapping, KoshaGuide)
                .join(KoshaGuide, PgGuideArticleMapping.guide_code == KoshaGuide.guide_code)
                .filter(PgGuideArticleMapping.article_code == article_num)
                .limit(5)
                .all()
            )

            for mapping, guide in mappings:
                if guide.guide_code not in guide_results:
                    # CI에서 관련 항목 가져오기
                    cis = (
                        db.query(PgChecklistItem)
                        .filter(PgChecklistItem.source_guide == guide.guide_code)
                        .limit(3)
                        .all()
                    )
                    guide_results[guide.guide_code] = {
                        "guide_code": guide.guide_code,
                        "title": guide.title,
                        "classification": guide.domain,
                        "relevant_sections": [
                            {
                                "section_title": ci.source_section or "",
                                "excerpt": ci.text[:200] if ci.text else "",
                                "section_type": "standard",
                            }
                            for ci in cis
                        ],
                        "relevance_score": 0.90,
                        "mapping_type": "explicit",
                    }

        # 2차: 벡터 검색으로 보충
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
                                "section_type": "standard",
                            }],
                            "relevance_score": score,
                            "mapping_type": "auto",
                        }
                        if len(guide_results) >= n_results:
                            break
            except Exception as e:
                logger.warning(f"KOSHA GUIDE 벡터 검색 실패: {e}")

        sorted_results = sorted(guide_results.values(), key=lambda x: x["relevance_score"], reverse=True)
        return sorted_results[:n_results]

    # ── BM25 인덱스 (가이드 제목 기반) ─────────────────────────
    def _build_guide_bm25_index(self, db: Session):
        if not HAS_BM25 or self._bm25_index is not None:
            return
        try:
            guides = db.query(KoshaGuide).all()
            docs = []
            tokenized = []
            for g in guides:
                text = f"{g.guide_code} {g.title} {g.domain}"
                tokens = tokenize_korean(text)
                for w in (g.title or "").replace("·", " ").replace(",", " ").split():
                    if len(w) >= 2:
                        tokens.append(w)
                tokenized.append(tokens)
                docs.append({
                    "guide_code": g.guide_code,
                    "title": g.title,
                    "classification": g.domain,
                    "guide_id": g.guide_code,
                })
            if tokenized:
                self._bm25_index = BM25Okapi(tokenized)
                self._bm25_docs = docs
                logger.info(f"KOSHA BM25 인덱스 구축: {len(docs)}개 가이드")
        except Exception as e:
            logger.warning(f"KOSHA BM25 인덱스 실패: {e}")

    def search_guides_bm25(self, db: Session, query_text: str, n_results: int = 5) -> List[dict]:
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

    _DESC_STOP_WORDS = {
        "위험", "사고", "작업", "안전", "관련", "발생", "가능", "경우", "상태", "조치",
        "방치", "예방", "존재", "높음", "관한", "위한", "대한", "인한", "의한", "따른",
        "통한", "해당", "있어", "있음", "없음", "등으로", "인해", "경미한", "심각한",
        "위험이", "수", "할", "등이", "것이", "놓여", "드러난", "무방비로", "젖었을",
        "가능성이", "이어질", "발생할", "흩어져", "떨어져", "위에", "주변에",
        "사용하여", "바닥이", "바닥에", "과정에서", "실수로", "다듬는", "다칠",
    }

    def _extract_key_nouns(self, descriptions: List[str]) -> List[str]:
        nouns = []
        for desc in descriptions:
            for token in desc.split():
                clean = token.rstrip("이가을를은는에서와도의")
                if len(clean) >= 2 and clean not in self._DESC_STOP_WORDS:
                    nouns.append(clean)
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
        """위험 설명 + GPT 키워드로 KOSHA GUIDE 직접 검색 (법조항 우회)"""
        if self.collection.count() == 0:
            return []
        exclude_codes = exclude_codes or []

        if guide_keywords:
            if len(guide_keywords) >= 3:
                query = " ".join(guide_keywords)
            else:
                query = " ".join(guide_keywords) + " 안전지침"
        else:
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
            if guide_keywords and len(guide_keywords) >= 3:
                threshold = 0.38
            elif guide_keywords:
                threshold = 0.42
            else:
                threshold = 0.30

            if results and results["metadatas"] and results["metadatas"][0]:
                for i, meta in enumerate(results["metadatas"][0]):
                    code = meta.get("guide_code", "")
                    if code in guide_results or code in exclude_codes:
                        continue
                    distance = results["distances"][0][i] if results["distances"] else 0.5
                    score = round(1 - distance, 4)
                    if score < threshold:
                        continue

                    # PG에서 해당 가이드의 CI 조회
                    guide_code = str(meta.get("guide_id") or code)
                    cis = (
                        db.query(PgChecklistItem)
                        .filter(PgChecklistItem.source_guide == guide_code)
                        .limit(2)
                        .all()
                    )

                    guide_results[code] = {
                        "guide_code": code,
                        "title": meta.get("title", ""),
                        "classification": meta.get("classification", ""),
                        "relevant_sections": [
                            {
                                "section_title": ci.source_section or "",
                                "excerpt": ci.text[:200] if ci.text else "",
                                "section_type": "standard",
                            }
                            for ci in cis
                        ] if cis else [{
                            "section_title": meta.get("section_title", ""),
                            "excerpt": "",
                            "section_type": "standard",
                        }],
                        "relevance_score": score,
                        "mapping_type": "direct",
                    }
                    if len(guide_results) >= n_results:
                        break

            return sorted(guide_results.values(), key=lambda x: x["relevance_score"], reverse=True)[:n_results]

        except Exception as e:
            logger.warning(f"KOSHA GUIDE 직접 벡터 검색 실패: {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return []

    # ── Path C: 키워드 타이틀 직접 매칭 ────────────────────────

    def search_guides_by_title_keywords(
        self,
        db: Session,
        keywords: List[str],
        n_results: int = 3,
        exclude_codes: List[str] = None,
    ) -> List[dict]:
        exclude_codes = exclude_codes or []
        if not keywords:
            return []

        clean_keywords = []
        for kw in keywords:
            for word in kw.split():
                if len(word) >= 2 and word not in {
                    "안전", "관한", "위한", "대한", "예방", "관리", "작업",
                    "방지", "설치", "기준", "기술", "지침", "규정", "시행",
                    "사용", "보건", "산업", "일반", "운용", "프로그램",
                }:
                    clean_keywords.append(word)
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
            title_words = title.replace("·", " ").replace(",", " ").replace("(", " ").replace(")", " ").split()
            hits = 0
            for kw in clean_keywords:
                for tw in title_words:
                    if tw.startswith(kw) or kw == tw:
                        hits += 1
                        break
            if hits > 0:
                score = 0.5 + (hits / len(clean_keywords)) * 0.3
                cis = (
                    db.query(PgChecklistItem)
                    .filter(PgChecklistItem.source_guide == guide.guide_code)
                    .limit(2)
                    .all()
                )
                scored.append({
                    "guide_code": guide.guide_code,
                    "title": guide.title,
                    "classification": guide.domain,
                    "relevant_sections": [
                        {
                            "section_title": ci.source_section or "",
                            "excerpt": ci.text[:200] if ci.text else "",
                            "section_type": "standard",
                        }
                        for ci in cis
                    ] if cis else [],
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
        result: Dict[str, List[dict]] = {}

        mappings = (
            db.query(PgGuideArticleMapping, PgArticle)
            .join(PgArticle, (PgGuideArticleMapping.law_type == PgArticle.law_type) &
                  (PgGuideArticleMapping.article_code == PgArticle.article_code))
            .filter(PgGuideArticleMapping.guide_code.in_(guide_codes))
            .all()
        )

        for mapping, article in mappings:
            gc = mapping.guide_code
            if gc not in result:
                result[gc] = []
            result[gc].append({
                "article_number": article.article_code,
                "title": article.title or "",
                "content": article.full_text[:200] if article.full_text else "",
                "source_file": "",
            })

        # 매핑 없는 가이드도 빈 리스트로 포함
        for gc in guide_codes:
            if gc not in result:
                result[gc] = []

        return result


guide_service = GuideService()
