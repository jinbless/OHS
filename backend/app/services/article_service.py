"""산안법 조문 PDF 파싱 및 하이브리드 검색 서비스 (v2)

하이브리드 매칭 파이프라인:
  Stage 1: GPT 직접 추천 (가중치 0.4)
  Stage 2: 카테고리→법조항 하드매핑 (가중치 0.35)
  Stage 3: 벡터 검색 (가중치 0.25)
  Stage 4: 후보 통합 (중복 제거, 최대 10개)
  Stage 5: LLM Reranker (gpt-4.1-mini → 상위 5개)
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

from app.config import settings

logger = logging.getLogger(__name__)


# ── 카테고리 → 법조항 하드매핑 (Design FR-02) ──────────────────

CATEGORY_TO_ARTICLES = {
    # 물리적 위험
    "FALL": {
        "primary": [(42, 52)],
        "secondary": [(53, 71)],
        "keywords": ["추락", "낙하", "안전대", "개구부", "작업발판"],
    },
    "SLIP": {
        "primary": [(3, 6)],
        "secondary": [(21, 30)],
        "keywords": ["전도", "미끄럼", "넘어짐", "바닥"],
    },
    "COLLISION": {
        "primary": [(171, 188)],
        "secondary": [(196, 221)],
        "keywords": ["충돌", "부딪힘", "차량", "지게차"],
    },
    "CRUSH": {
        "primary": [(86, 99)],
        "secondary": [(131, 170)],
        "keywords": ["끼임", "협착", "회전축", "기어"],
    },
    "CUT": {
        "primary": [(103, 109)],
        "secondary": [(86, 99)],
        "keywords": ["절단", "날", "전단기", "톱", "칼"],
    },
    "FALLING_OBJECT": {
        "primary": [(14, 14)],
        "secondary": [(42, 52)],
        "keywords": ["낙하물", "물체 떨어짐", "방호선반"],
    },
    # 화학적 위험
    "CHEMICAL": {
        "primary": [(420, 450)],
        "secondary": [(225, 238)],
        "keywords": ["화학물질", "유해물질", "중독"],
    },
    "FIRE_EXPLOSION": {
        "primary": [(225, 300)],
        "secondary": [(324, 327)],
        "keywords": ["화재", "폭발", "인화성", "가스"],
    },
    "TOXIC": {
        "primary": [(296, 300)],
        "secondary": [(420, 450)],
        "keywords": ["독성", "누출", "중독"],
    },
    "CORROSION": {
        "primary": [(255, 279)],
        "secondary": [(420, 450)],
        "keywords": ["부식", "화학설비", "압력용기"],
    },
    # 전기적 위험
    "ELECTRIC": {
        "primary": [(301, 323)],
        "secondary": [(324, 327)],
        "keywords": ["감전", "전기", "충전부", "접지", "누전"],
    },
    "ELECTRICAL": {
        "primary": [(301, 323)],
        "secondary": [(324, 327)],
        "keywords": ["감전", "전기", "충전부"],
    },
    "ARC_FLASH": {
        "primary": [(301, 311)],
        "secondary": [(318, 323)],
        "keywords": ["아크", "플래시", "전기화상"],
    },
    # 인간공학적 위험
    "ERGONOMIC": {
        "primary": [(655, 665)],
        "secondary": [(385, 386)],
        "keywords": ["근골격계", "반복작업", "부담작업"],
    },
    "REPETITIVE": {
        "primary": [(655, 665)],
        "keywords": ["반복", "근골격계", "부담작업"],
    },
    "HEAVY_LIFTING": {
        "primary": [(655, 665)],
        "secondary": [(385, 386)],
        "keywords": ["중량물", "인력운반", "들어올리기"],
    },
    "POSTURE": {
        "primary": [(655, 665)],
        "keywords": ["자세", "근골격계", "부적절한 자세"],
    },
    # 환경적 위험
    "NOISE": {
        "primary": [(511, 518)],
        "keywords": ["소음", "난청", "진동"],
    },
    "TEMPERATURE": {
        "primary": [(555, 572)],
        "keywords": ["고열", "한랭", "온도", "열사병"],
    },
    "LIGHTING": {
        "primary": [(7, 10)],
        "keywords": ["조명", "조도", "채광"],
    },
    "ENVIRONMENTAL": {
        "primary": [(617, 644)],
        "secondary": [(555, 572)],
        "keywords": ["밀폐", "환경", "질식"],
    },
    # 생물학적 위험
    "BIOLOGICAL": {
        "primary": [(590, 605)],
        "keywords": ["감염", "병원체", "혈액매개"],
    },
}


# ── 조문 데이터 모델 ──────────────────────────────────────────

class ArticleChunk:
    def __init__(self, article_number: str, title: str, content: str, source_file: str):
        self.article_number = article_number
        self.title = title
        self.content = content
        self.source_file = source_file

    def to_dict(self):
        return {
            "article_number": self.article_number,
            "title": self.title,
            "content": self.content,
            "source_file": self.source_file,
        }


# ── Reranker 프롬프트 ─────────────────────────────────────────

RERANKER_PROMPT = """다음 위험요소에 대해, 후보 법조항 중 가장 관련 있는 것을 선택하세요.

## 위험요소
{hazard_summary}

## 후보 법조항
{candidates_json}

각 후보에 대해 관련성 점수(0.0~1.0)를 매기고, 상위 5개만 반환하세요.
관련성 기준: 해당 위험요소를 예방·관리하기 위해 사업주가 준수해야 하는 조문인가?

반드시 아래 JSON 형식으로만 응답하세요:
[
  {{"article_number": "제N조", "relevance_score": 0.95, "reason": "관련 이유"}},
  ...
]"""


class ArticleService:
    ARTICLES_DIR = Path("/home/blessjin/cashtoss/ohs/ohs_articles")
    CHROMA_DIR = Path("/home/blessjin/cashtoss/ohs/backend/data/chromadb")
    CACHE_FILE = Path("/home/blessjin/cashtoss/ohs/backend/data/articles_cache.json")
    COLLECTION_NAME = "ohs_articles"

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

    # ── PDF 파싱 ──────────────────────────────────────────

    def parse_all_pdfs(self) -> List[ArticleChunk]:
        """모든 PDF에서 조문 텍스트를 추출"""
        chunks: List[ArticleChunk] = []
        pdf_files = sorted(self.ARTICLES_DIR.glob("*.pdf"))
        logger.info(f"PDF 파일 {len(pdf_files)}개 파싱 시작")

        for pdf_path in pdf_files:
            try:
                file_chunks = self._parse_single_pdf(pdf_path)
                chunks.extend(file_chunks)
            except Exception as e:
                logger.error(f"PDF 파싱 실패: {pdf_path.name} - {e}")

        logger.info(f"총 {len(chunks)}개 조문 청크 추출 완료")
        return chunks

    def _parse_single_pdf(self, pdf_path: Path) -> List[ArticleChunk]:
        """단일 PDF에서 조문을 추출"""
        doc = fitz.open(str(pdf_path))
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n"
        doc.close()

        file_info = self._parse_filename(pdf_path.name)
        chunks = self._split_into_articles(full_text, pdf_path.name, file_info)

        if not chunks:
            title = file_info.get("title", pdf_path.stem)
            chunks = [ArticleChunk(
                article_number=file_info.get("start", pdf_path.stem),
                title=title,
                content=full_text.strip()[:3000],
                source_file=pdf_path.name,
            )]

        return chunks

    def _parse_filename(self, filename: str) -> dict:
        """파일명에서 조문 정보 추출"""
        info = {}
        m = re.match(r"제(\d+)조(?:_(.+?))?(?:~제(\d+)조)?(?:_(.+?))?\.pdf", filename)
        if m:
            info["start"] = f"제{int(m.group(1))}조"
            if m.group(3):
                info["end"] = f"제{int(m.group(3))}조"
            title_parts = [p for p in [m.group(2), m.group(4)] if p]
            info["title"] = " ".join(title_parts) if title_parts else ""
        return info

    def _split_into_articles(self, text: str, source_file: str, file_info: dict) -> List[ArticleChunk]:
        """텍스트를 조문 단위로 분할"""
        pattern = r"(제\d+조(?:의\d+)?)\s*[\(（]([^)）]+)[\)）]"
        matches = list(re.finditer(pattern, text))

        if not matches:
            return []

        chunks = []
        for i, match in enumerate(matches):
            article_num = match.group(1)
            article_title = match.group(2)
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()

            if len(content) < 30:
                continue
            if len(content) > 2000:
                content = content[:2000]

            chunks.append(ArticleChunk(
                article_number=article_num,
                title=article_title,
                content=content,
                source_file=source_file,
            ))

        return chunks

    # ── 임베딩 + ChromaDB 저장 ─────────────────────────────

    def build_index(self, force: bool = False) -> int:
        """PDF 파싱 → 임베딩 → ChromaDB 인덱싱"""
        if not force and self.collection.count() > 0:
            logger.info(f"이미 {self.collection.count()}개 조문 인덱싱됨. 스킵.")
            return self.collection.count()

        if force and self.collection.count() > 0:
            self.chroma_client.delete_collection(self.COLLECTION_NAME)
            self._collection = None

        chunks = self.parse_all_pdfs()
        if not chunks:
            logger.warning("파싱된 조문이 없습니다.")
            return 0

        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in chunks], f, ensure_ascii=False, indent=2)

        batch_size = 50
        total_indexed = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [f"{c.article_number} {c.title}\n{c.content}" for c in batch]

            try:
                response = self._openai.embeddings.create(
                    model="text-embedding-3-small",
                    input=texts,
                )
                embeddings = [item.embedding for item in response.data]

                self.collection.add(
                    ids=[f"{c.article_number}_{c.source_file}" for c in batch],
                    embeddings=embeddings,
                    documents=texts,
                    metadatas=[c.to_dict() for c in batch],
                )
                total_indexed += len(batch)
                logger.info(f"인덱싱 진행: {total_indexed}/{len(chunks)}")
            except Exception as e:
                logger.error(f"임베딩 배치 실패 (인덱스 {i}): {e}")

        logger.info(f"인덱싱 완료: 총 {total_indexed}개")
        return total_indexed

    # ── Stage 2: 하드매핑 검색 ─────────────────────────────

    def _extract_article_number(self, article_number: str) -> Optional[int]:
        """조문번호에서 숫자를 추출 (예: '제42조' → 42, '제42조의2' → 42)"""
        m = re.match(r"제(\d+)조", article_number)
        return int(m.group(1)) if m else None

    def _search_by_hard_mapping(self, category_code: str) -> List[dict]:
        """카테고리 코드로 하드매핑된 법조항을 ChromaDB에서 직접 조회"""
        mapping = CATEGORY_TO_ARTICLES.get(category_code.upper())
        if not mapping:
            return []

        target_ranges = mapping.get("primary", []) + mapping.get("secondary", [])
        if not target_ranges:
            return []

        # ChromaDB에서 모든 메타데이터를 가져와 조문번호로 필터링
        results = []
        try:
            all_data = self.collection.get(
                include=["metadatas", "documents"],
            )
            if not all_data or not all_data["metadatas"]:
                return []

            for i, meta in enumerate(all_data["metadatas"]):
                article_num = self._extract_article_number(meta.get("article_number", ""))
                if article_num is None:
                    continue

                is_primary = False
                is_match = False
                for rng in mapping.get("primary", []):
                    if rng[0] <= article_num <= rng[1]:
                        is_primary = True
                        is_match = True
                        break
                if not is_match:
                    for rng in mapping.get("secondary", []):
                        if rng[0] <= article_num <= rng[1]:
                            is_match = True
                            break

                if is_match:
                    results.append({
                        "article_number": meta.get("article_number", ""),
                        "title": meta.get("title", ""),
                        "content": meta.get("content", "")[:500],
                        "source_file": meta.get("source_file", ""),
                        "relevance_score": 0.85 if is_primary else 0.65,
                        "source": "hard_mapping",
                    })

        except Exception as e:
            logger.warning(f"하드매핑 검색 실패: {e}")

        return results

    # ── Stage 3: 벡터 검색 (개선) ─────────────────────────

    def search_articles(self, query: str, n_results: int = 5) -> List[dict]:
        """위험요소 설명으로 관련 법조항 검색 (벡터 검색)"""
        if self.collection.count() == 0:
            logger.warning("인덱스가 비어있습니다. build_index() 실행 필요.")
            return []

        response = self._openai.embeddings.create(
            model="text-embedding-3-small",
            input=[query],
        )
        query_embedding = response.data[0].embedding

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        articles = []
        if results and results["metadatas"] and results["metadatas"][0]:
            for i, meta in enumerate(results["metadatas"][0]):
                distance = results["distances"][0][i] if results["distances"] else 0
                articles.append({
                    "article_number": meta.get("article_number", ""),
                    "title": meta.get("title", ""),
                    "content": meta.get("content", "")[:500],
                    "source_file": meta.get("source_file", ""),
                    "relevance_score": round(1 - distance, 4),
                    "source": "vector_search",
                })

        return articles

    def _build_enhanced_query(self, hazard: dict) -> str:
        """하드매핑 키워드를 포함한 향상된 검색 쿼리 생성"""
        category_code = hazard.get("category_code", "").upper()
        mapping = CATEGORY_TO_ARTICLES.get(category_code)

        parts = []
        if mapping:
            parts.extend(mapping.get("keywords", []))
        parts.append(hazard.get("name", ""))
        parts.append(hazard.get("description", ""))

        return " ".join(parts)

    # ── Stage 4: 후보 통합 ────────────────────────────────

    def _merge_candidates(
        self,
        gpt_articles: List[dict],
        hardmap_articles: List[dict],
        vector_articles: List[dict],
    ) -> List[dict]:
        """3개 Stage의 결과를 통합 (가중 점수 합산, 중복 제거)"""
        WEIGHT_GPT = 0.4
        WEIGHT_HARD = 0.35
        WEIGHT_VECTOR = 0.25

        merged: Dict[str, dict] = {}

        def add_results(articles: List[dict], weight: float):
            for a in articles:
                key = a["article_number"]
                weighted_score = a.get("relevance_score", 0.5) * weight
                if key in merged:
                    merged[key]["weighted_score"] += weighted_score
                    # 출처 추가
                    sources = merged[key].get("sources", [])
                    src = a.get("source", "unknown")
                    if src not in sources:
                        sources.append(src)
                    merged[key]["sources"] = sources
                    # 더 높은 content는 유지
                    if len(a.get("content", "")) > len(merged[key].get("content", "")):
                        merged[key]["content"] = a["content"]
                else:
                    merged[key] = {
                        **a,
                        "weighted_score": weighted_score,
                        "sources": [a.get("source", "unknown")],
                    }

        add_results(gpt_articles, WEIGHT_GPT)
        add_results(hardmap_articles, WEIGHT_HARD)
        add_results(vector_articles, WEIGHT_VECTOR)

        # 가중 점수 순 정렬, 상위 10개
        sorted_candidates = sorted(
            merged.values(),
            key=lambda x: x["weighted_score"],
            reverse=True,
        )
        return sorted_candidates[:10]

    # ── Stage 5: LLM Reranker ─────────────────────────────

    def _rerank_with_llm(self, hazard_summary: str, candidates: List[dict]) -> List[dict]:
        """gpt-4.1-mini로 후보를 재평가하여 상위 5개 선정"""
        if not candidates:
            return []

        # 후보가 5개 이하면 reranker 생략
        if len(candidates) <= 5:
            for c in candidates:
                c["relevance_score"] = c.get("weighted_score", c.get("relevance_score", 0.5))
            return candidates

        candidates_for_prompt = []
        for c in candidates:
            candidates_for_prompt.append({
                "article_number": c["article_number"],
                "title": c.get("title", ""),
                "content_preview": c.get("content", "")[:200],
            })

        prompt = RERANKER_PROMPT.format(
            hazard_summary=hazard_summary,
            candidates_json=json.dumps(candidates_for_prompt, ensure_ascii=False, indent=2),
        )

        try:
            response = self._openai.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "당신은 산업안전보건법 전문가입니다. JSON만 응답하세요."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=1024,
            )

            raw = response.choices[0].message.content.strip()
            # JSON 배열 파싱 (```json ... ``` 래핑 처리)
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            reranked = json.loads(raw)

            # 결과를 원본 후보 데이터와 병합
            reranked_map = {r["article_number"]: r for r in reranked}
            final = []
            for c in candidates:
                if c["article_number"] in reranked_map:
                    c["relevance_score"] = reranked_map[c["article_number"]].get("relevance_score", 0.5)
                    c["reranker_reason"] = reranked_map[c["article_number"]].get("reason", "")
                    final.append(c)

            final.sort(key=lambda x: x["relevance_score"], reverse=True)
            return final[:5]

        except Exception as e:
            logger.warning(f"LLM Reranker 실패, 가중점수 기반 폴백: {e}")
            # 폴백: weighted_score 기반 상위 5개
            for c in candidates:
                c["relevance_score"] = c.get("weighted_score", c.get("relevance_score", 0.5))
            return candidates[:5]

    # ── 하이브리드 파이프라인 (메인) ──────────────────────

    def hybrid_search_for_hazards(
        self,
        hazards: List[dict],
        gpt_recommended_articles: Optional[List[dict]] = None,
    ) -> List[dict]:
        """하이브리드 매칭 파이프라인 (5단계)

        Args:
            hazards: GPT가 분석한 위험요소 목록
                     [{"category_code": "FALL", "name": "추락 위험", "description": "..."}]
            gpt_recommended_articles: GPT가 직접 추천한 조문 목록 (Stage 1)
                     [{"article_number": "제42조", "reason": "..."}]

        Returns:
            상위 5개 관련 법조항 리스트
        """
        if self.collection.count() == 0:
            logger.warning("인덱스가 비어있습니다.")
            return []

        # ── Stage 1: GPT 직접 추천 결과 ──
        gpt_articles = []
        if gpt_recommended_articles:
            for rec in gpt_recommended_articles:
                article_num = rec.get("article_number", "")
                # ChromaDB에서 해당 조문의 상세 정보 조회
                matched = self._find_article_by_number(article_num)
                if matched:
                    matched["relevance_score"] = 0.9
                    matched["source"] = "gpt_direct"
                    matched["reranker_reason"] = rec.get("reason", "")
                    gpt_articles.append(matched)

        # ── Stage 2: 하드매핑 ──
        hardmap_articles: Dict[str, dict] = {}
        for hazard in hazards:
            category_code = hazard.get("category_code", "")
            results = self._search_by_hard_mapping(category_code)
            for a in results:
                key = a["article_number"]
                if key not in hardmap_articles or a["relevance_score"] > hardmap_articles[key]["relevance_score"]:
                    hardmap_articles[key] = a

        # ── Stage 3: 벡터 검색 (개선된 쿼리) ──
        vector_articles: Dict[str, dict] = {}
        for hazard in hazards:
            query = self._build_enhanced_query(hazard)
            results = self.search_articles(query, n_results=5)
            for a in results:
                key = a["article_number"]
                if key not in vector_articles or a["relevance_score"] > vector_articles[key]["relevance_score"]:
                    vector_articles[key] = a

        # ── Stage 4: 후보 통합 ──
        candidates = self._merge_candidates(
            gpt_articles=gpt_articles,
            hardmap_articles=list(hardmap_articles.values()),
            vector_articles=list(vector_articles.values()),
        )

        logger.info(
            f"하이브리드 검색 결과 - GPT직접:{len(gpt_articles)}, "
            f"하드매핑:{len(hardmap_articles)}, 벡터:{len(vector_articles)}, "
            f"통합후보:{len(candidates)}"
        )

        # ── Stage 5: LLM Reranker ──
        hazard_summary = "\n".join(
            f"- [{h.get('category_code', '')}] {h.get('name', '')}: {h.get('description', '')}"
            for h in hazards
        )
        final_articles = self._rerank_with_llm(hazard_summary, candidates)

        # 결과 정리 (불필요한 필드 제거)
        clean_results = []
        for a in final_articles:
            clean_results.append({
                "article_number": a["article_number"],
                "title": a.get("title", ""),
                "content": a.get("content", "")[:500],
                "source_file": a.get("source_file", ""),
                "relevance_score": round(a.get("relevance_score", 0.5), 4),
            })

        return clean_results

    def _find_article_by_number(self, article_number: str) -> Optional[dict]:
        """조문번호로 ChromaDB에서 상세 정보 조회"""
        try:
            all_data = self.collection.get(
                include=["metadatas"],
            )
            if not all_data or not all_data["metadatas"]:
                return None

            # 정확한 조문번호 매칭
            for meta in all_data["metadatas"]:
                if meta.get("article_number") == article_number:
                    return {
                        "article_number": meta["article_number"],
                        "title": meta.get("title", ""),
                        "content": meta.get("content", "")[:500],
                        "source_file": meta.get("source_file", ""),
                    }

            # 부분 매칭 (제42조 → 제42조의2 등)
            num = self._extract_article_number(article_number)
            if num:
                for meta in all_data["metadatas"]:
                    meta_num = self._extract_article_number(meta.get("article_number", ""))
                    if meta_num == num:
                        return {
                            "article_number": meta["article_number"],
                            "title": meta.get("title", ""),
                            "content": meta.get("content", "")[:500],
                            "source_file": meta.get("source_file", ""),
                        }
        except Exception as e:
            logger.warning(f"조문 조회 실패 ({article_number}): {e}")

        return None

    # ── 레거시 호환 (기존 search_for_hazards) ──────────────

    def search_for_hazards(self, hazards: List[dict]) -> List[dict]:
        """기존 호환용 - hybrid_search_for_hazards로 위임"""
        return self.hybrid_search_for_hazards(hazards)


article_service = ArticleService()
