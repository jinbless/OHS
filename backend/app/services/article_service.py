"""산안법 조문 PDF 파싱 및 ChromaDB 인덱싱 서비스

KOSHA GUIDE 가이드-법조항 매핑에서 조문 상세 정보 조회 용도로 사용.
BM25 하이브리드 검색 지원 (v2.2)
"""
import os
import re
import json
import logging
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False

from app.config import settings
from app.utils.text_utils import tokenize_korean, extract_article_number

logger = logging.getLogger(__name__)


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


class ArticleService:
    _BASE = Path(os.environ.get("OHS_BASE_DIR", "/home/blessjin/cashtoss/ohs"))
    ARTICLES_DIR = _BASE / "ohs_articles"
    CHROMA_DIR = _BASE / "backend" / "data" / "chromadb"
    CACHE_FILE = _BASE / "backend" / "data" / "articles_cache.json"
    COLLECTION_NAME = "ohs_articles"

    def __init__(self):
        self._client: Optional[chromadb.ClientAPI] = None
        self._collection = None
        self._openai = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._bm25_index = None
        self._bm25_docs = None  # [{article_number, title, content, ...}, ...]

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

    def load_articles(self) -> List[ArticleChunk]:
        """조문 텍스트를 추출 (캐시 우선, 폴백으로 PDF 파싱)"""
        # 1. 캐시 파일이 있으면 캐시에서 로드 (PDF 불필요)
        if self.CACHE_FILE.exists():
            try:
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                chunks = [
                    ArticleChunk(
                        article_number=d.get("article_number", ""),
                        title=d.get("title", ""),
                        content=d.get("content", ""),
                        source_file=d.get("source_file", ""),
                    )
                    for d in data
                ]
                logger.info(f"캐시에서 {len(chunks)}개 조문 로드 완료 ({self.CACHE_FILE.name})")
                return chunks
            except Exception as e:
                logger.warning(f"캐시 로드 실패, PDF 파싱으로 폴백: {e}")

        # 2. 폴백: PDF 파싱
        if not self.ARTICLES_DIR.exists():
            logger.warning(f"PDF 디렉토리 없음: {self.ARTICLES_DIR}")
            return []

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

    # 하위 호환 alias
    parse_all_pdfs = load_articles

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

        chunks = self.load_articles()
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

    # ── 조문 조회 (KOSHA GUIDE 연동용) ─────────────────────

    def _extract_article_number(self, article_number: str) -> Optional[int]:
        """조문번호에서 숫자를 추출 (예: '제42조' → 42, '제42조의2' → 42)"""
        m = re.match(r"제(\d+)조", article_number)
        return int(m.group(1)) if m else None

    # ── BM25 인덱스 구축 ────────────────────────────────────
    def _build_bm25_index(self):
        """ChromaDB 데이터로 BM25 인덱스 구축 (lazy)"""
        if not HAS_BM25:
            return
        if self._bm25_index is not None:
            return

        try:
            all_data = self.collection.get(include=["metadatas", "documents"])
            if not all_data or not all_data["metadatas"]:
                return

            docs = []
            tokenized = []
            for i, meta in enumerate(all_data["metadatas"]):
                doc_text = all_data["documents"][i] if all_data["documents"] else ""
                art_num = meta.get("article_number", "")
                title = meta.get("title", "")
                content = meta.get("content", "")
                combined = f"{art_num} {title} {content} {doc_text}"
                tokens = tokenize_korean(combined)
                tokenized.append(tokens)
                docs.append({
                    "article_number": art_num,
                    "title": title,
                    "content": content[:500],
                    "source_file": meta.get("source_file", ""),
                    "chapter": meta.get("chapter", ""),
                })

            if tokenized:
                self._bm25_index = BM25Okapi(tokenized)
                self._bm25_docs = docs
                logger.info(f"BM25 인덱스 구축 완료: {len(docs)}개 조문")
        except Exception as e:
            logger.warning(f"BM25 인덱스 구축 실패: {e}")

    def search_articles_bm25(self, query_text: str, n_results: int = 10) -> List[dict]:
        """BM25 키워드 기반 검색"""
        if not HAS_BM25:
            return []
        self._build_bm25_index()
        if self._bm25_index is None or self._bm25_docs is None:
            return []

        tokens = tokenize_korean(query_text)
        if not tokens:
            return []

        scores = self._bm25_index.get_scores(tokens)
        # 점수 정규화 (0~1)
        max_score = max(scores) if max(scores) > 0 else 1
        indexed = [(i, scores[i] / max_score) for i in range(len(scores)) if scores[i] > 0]
        indexed.sort(key=lambda x: x[1], reverse=True)

        results = []
        seen = set()
        for idx, norm_score in indexed[:n_results * 2]:
            doc = self._bm25_docs[idx]
            art_num = doc["article_number"]
            if art_num in seen:
                continue
            seen.add(art_num)
            results.append({
                "article_number": art_num,
                "title": doc["title"],
                "content": doc["content"],
                "source_file": doc["source_file"],
                "chapter": doc["chapter"],
                "bm25_score": round(norm_score, 4),
            })
            if len(results) >= n_results:
                break
        return results

    # ── 카테고리 기반 필터링 검색 ────────────────────────────

    # 카테고리 → 관련 장(chapter) 키워드 매핑 (law.go.kr 편/장/절 구조 기반)
    CATEGORY_CHAPTERS = {
        "physical": [
            "작업장", "통로", "보호구", "추락", "붕괴", "비계",
            "기계", "설비", "위험예방", "건설작업", "중량물",
            "하역작업", "벌목", "궤도",
        ],
        "chemical": [
            "폭발", "화재", "위험물", "유해물질", "허가대상", "금지유해",
        ],
        "electrical": [
            "전기",
        ],
        "ergonomic": [
            "근골격계",
        ],
        "environmental": [
            "소음", "진동", "온도", "습도", "분진", "밀폐공간",
            "이상기압", "방사선",
        ],
        "biological": [
            "병원체", "감염",
        ],
    }

    def _is_chapter_match(self, chapter: str, category: str) -> bool:
        """장(chapter) 이름이 카테고리에 해당하는지 확인"""
        keywords = self.CATEGORY_CHAPTERS.get(category, [])
        return any(kw in chapter for kw in keywords)

    def search_articles_with_filter(
        self,
        query_text: str,
        risk_feature_codes: List[str] = None,
        n_results: int = 10,
        min_score: float = 0.45,
    ) -> List[dict]:
        """편/장/절 메타데이터 + 벡터검색 결합

        1차: 카테고리 관련 장(chapter) 내에서 벡터검색 (precision)
        2차: 전체 범위 벡터검색 보충 (recall)
        """
        if self.collection.count() == 0 or not query_text.strip():
            return []

        try:
            response = self._openai.embeddings.create(
                model="text-embedding-3-small",
                input=[query_text],
            )
            query_embedding = response.data[0].embedding
        except Exception as e:
            logger.warning(f"임베딩 생성 실패: {e}")
            return []

        results_map = {}

        # 1차: 벡터검색 후 카테고리 장(chapter) 기반 부스트
        try:
            chroma_results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(n_results * 4, 50),
                include=["metadatas", "distances"],
            )
            if chroma_results and chroma_results["metadatas"] and chroma_results["metadatas"][0]:
                for i, meta in enumerate(chroma_results["metadatas"][0]):
                    art_num_str = meta.get("article_number", "")
                    if not art_num_str:
                        continue

                    distance = chroma_results["distances"][0][i]
                    score = round(1 - distance, 4)
                    if score < min_score:
                        continue

                    # 편/장/절 메타데이터 기반 부스트
                    chapter = meta.get("chapter", "")
                    in_category = False

                    if art_num_str not in results_map or results_map[art_num_str]["score"] < score:
                        results_map[art_num_str] = {
                            "article_number": art_num_str,
                            "title": meta.get("title", ""),
                            "content": meta.get("content", "")[:500],
                            "source_file": meta.get("source_file", ""),
                            "chapter": chapter,
                            "score": score,
                            "in_category_range": in_category,
                        }
        except Exception as e:
            logger.warning(f"벡터검색 실패: {e}")

        # BM25 하이브리드: 벡터 결과에 BM25 점수 병합
        if HAS_BM25:
            bm25_results = self.search_articles_bm25(query_text, n_results=20)
            bm25_map = {r["article_number"]: r["bm25_score"] for r in bm25_results}

            # 기존 벡터 결과에 BM25 점수 병합
            for art_num, info in results_map.items():
                bm25_s = bm25_map.pop(art_num, 0)
                if bm25_s > 0:
                    # 하이브리드: 벡터 50% + BM25 50%
                    info["score"] = round(info["score"] * 0.5 + bm25_s * 0.5, 4)
                    info["bm25_score"] = bm25_s

            # BM25에만 있는 결과도 추가 (벡터가 놓친 것)
            for art_num, bm25_s in bm25_map.items():
                if bm25_s >= 0.3 and art_num not in results_map:
                    # BM25 전용 결과 (벡터 검색에서 누락된 것)
                    bm25_doc = next((r for r in bm25_results if r["article_number"] == art_num), None)
                    if bm25_doc:
                        results_map[art_num] = {
                            "article_number": art_num,
                            "title": bm25_doc["title"],
                            "content": bm25_doc["content"],
                            "source_file": bm25_doc["source_file"],
                            "chapter": bm25_doc.get("chapter", ""),
                            "score": round(bm25_s * 0.5, 4),  # BM25만이므로 절반
                            "in_category_range": False,
                            "bm25_score": bm25_s,
                        }

        sorted_results = sorted(results_map.values(), key=lambda x: x["score"], reverse=True)
        return sorted_results[:n_results]

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
                        "content": meta.get("content", ""),
                        "chapter": meta.get("chapter", ""),
                        "part": meta.get("part", ""),
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
                            "content": meta.get("content", ""),
                            "chapter": meta.get("chapter", ""),
                            "part": meta.get("part", ""),
                        }
        except Exception as e:
            logger.warning(f"조문 조회 실패 ({article_number}): {e}")

        return None


article_service = ArticleService()
