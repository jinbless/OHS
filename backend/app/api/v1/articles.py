from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from app.models.article import ArticleMatch, ArticleSearchResponse, ArticleIndexResponse
from app.services.article_service import article_service

router = APIRouter()


@router.post("/index", response_model=ArticleIndexResponse)
async def build_article_index(force: bool = Query(False, description="기존 인덱스 재생성 여부")):
    """
    산안법 조문 PDF 인덱싱

    ohs_articles 폴더의 모든 PDF를 파싱하여 벡터 인덱스를 생성합니다.
    """
    try:
        total = article_service.build_index(force=force)
        return ArticleIndexResponse(
            total_indexed=total,
            message=f"{total}개 조문이 인덱싱되었습니다."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"인덱싱 실패: {str(e)}")


@router.get("/search", response_model=ArticleSearchResponse)
async def search_articles(
    q: str = Query(..., description="검색 쿼리 (위험요소 설명)"),
    limit: int = Query(5, ge=1, le=20, description="결과 수")
):
    """
    위험요소로 관련 법조항 검색

    위험요소 설명을 입력하면 관련된 산안법 조문을 검색합니다.
    """
    if article_service.collection.count() == 0:
        raise HTTPException(status_code=400, detail="인덱스가 생성되지 않았습니다. POST /articles/index를 먼저 실행해주세요.")

    results = article_service.search_articles(q, n_results=limit)
    return ArticleSearchResponse(
        query=q,
        results=[ArticleMatch(**r) for r in results],
        total=len(results)
    )


@router.get("/status")
async def get_index_status():
    """인덱스 상태 확인"""
    count = article_service.collection.count()
    return {
        "indexed_count": count,
        "is_ready": count > 0
    }
