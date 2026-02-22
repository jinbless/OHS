"""산안법 조문 PDF 파싱 및 ChromaDB 인덱싱 서비스

KOSHA GUIDE 가이드-법조항 매핑에서 조문 상세 정보 조회 용도로 사용.
"""
import re
import json
import logging
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI

from app.config import settings

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

    # ── 조문 조회 (KOSHA GUIDE 연동용) ─────────────────────

    def _extract_article_number(self, article_number: str) -> Optional[int]:
        """조문번호에서 숫자를 추출 (예: '제42조' → 42, '제42조의2' → 42)"""
        m = re.match(r"제(\d+)조", article_number)
        return int(m.group(1)) if m else None

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


article_service = ArticleService()
