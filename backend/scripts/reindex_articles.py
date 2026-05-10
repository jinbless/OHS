#!/usr/bin/env python3
"""
articles_cache.json (law.go.kr 크롤링 데이터)을 ChromaDB에 재인덱싱.

Usage:
    python3 reindex_articles.py
"""

import json
import logging
import sys
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI

# 프로젝트 루트에서 설정 로드
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).parent.parent / "data" / "articles_cache.json"
CHROMA_DIR = Path(__file__).parent.parent / "data" / "chromadb"
COLLECTION_NAME = "ohs_articles"


def main():
    # 1. 데이터 로드
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)
    logger.info(f"Loaded {len(articles)} articles from {CACHE_FILE}")

    # 2. ChromaDB 클라이언트
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=ChromaSettings(anonymized_telemetry=False),
    )

    # 3. 기존 컬렉션 삭제
    try:
        old_count = client.get_collection(COLLECTION_NAME).count()
        client.delete_collection(COLLECTION_NAME)
        logger.info(f"Deleted old collection ({old_count} items)")
    except Exception:
        pass

    # 4. 새 컬렉션 생성
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # 5. OpenAI 임베딩 + 인덱싱
    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    batch_size = 50
    total_indexed = 0

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]

        # 임베딩 텍스트: 조문번호 + 제목 + 편/장/절 + 내용
        texts = []
        for a in batch:
            parts = [a["article_number"]]
            if a.get("title"):
                parts.append(a["title"])
            # 편/장/절 context 추가 (검색 정확도 향상)
            if a.get("chapter"):
                parts.append(f"[{a['chapter']}]")
            parts.append(a["content"])
            texts.append(" ".join(parts))

        try:
            response = openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            embeddings = [item.embedding for item in response.data]

            # 메타데이터 (ChromaDB)
            metadatas = []
            ids = []
            for a in batch:
                metadatas.append({
                    "article_number": a["article_number"],
                    "title": a.get("title", ""),
                    "content": a["content"][:2000],  # ChromaDB metadata limit
                    "source_file": a.get("source_file", "law.go.kr"),
                    "part": a.get("part", ""),
                    "chapter": a.get("chapter", ""),
                    "section": a.get("section", ""),
                })
                ids.append(f"{a['article_number']}_lawgokr")

            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
            total_indexed += len(batch)
            logger.info(f"Indexed: {total_indexed}/{len(articles)}")

        except Exception as e:
            logger.error(f"Batch {i} failed: {e}")

    logger.info(f"Done! Total indexed: {total_indexed}")

    # 6. 검증
    final_count = collection.count()
    logger.info(f"Collection count: {final_count}")

    # 샘플 검색 테스트
    test_query = "추락 방지 안전대"
    test_emb = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=[test_query],
    ).data[0].embedding

    results = collection.query(
        query_embeddings=[test_emb],
        n_results=3,
        include=["metadatas", "distances"],
    )
    logger.info(f"\nTest query: '{test_query}'")
    for j, (meta, dist) in enumerate(zip(results["metadatas"][0], results["distances"][0])):
        score = 1 - dist
        logger.info(f"  {j+1}. {meta['article_number']} ({meta['title']}) score={score:.3f}")


if __name__ == "__main__":
    main()
