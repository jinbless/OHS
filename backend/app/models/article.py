from pydantic import BaseModel
from typing import List, Optional


class ArticleMatch(BaseModel):
    article_number: str
    title: str
    content: str  # 미리보기 (최대 500자)
    source_file: str
    relevance_score: float


class ArticleSearchResponse(BaseModel):
    query: str
    results: List[ArticleMatch]
    total: int


class ArticleIndexResponse(BaseModel):
    total_indexed: int
    message: str
