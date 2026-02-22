"""온톨로지 API 엔드포인트.

기존 /api/v1/ 라우터에 /ontology/ 접두사로 추가.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.ontology_service import ontology_service
from app.models.ontology import (
    ArticleNormsResponse,
    MappingStatsResponse,
    GapAnalysisResponse,
    SemanticMappingResponse,
    ExtractionResult,
    ClassificationResult,
    DiscoveryResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ontology", tags=["온톨로지"])

# ── 조회 API ──────────────────────────────────────────────────

@router.get("/stats", response_model=MappingStatsResponse)
async def get_mapping_stats(db: Session = Depends(get_db)):
    """매핑 통계: 전체 현황 + before/after 비교"""
    return ontology_service.get_mapping_stats(db)


@router.get("/articles/{article_number}/norms", response_model=ArticleNormsResponse)
async def get_article_norms(article_number: str, db: Session = Depends(get_db)):
    """특정 법조항의 규범명제 목록 + 연결 가이드"""
    return ontology_service.get_article_norms(db, article_number)


@router.get("/articles/{article_number}/graph")
async def get_article_graph(article_number: str, db: Session = Depends(get_db)):
    """특정 법조항 중심 그래프 데이터 (vis.js 호환 nodes/edges)"""
    return ontology_service.get_article_graph(db, article_number)


@router.get("/graph")
async def get_full_graph(limit: int = 100, db: Session = Depends(get_db)):
    """전체 온톨로지 그래프 (노드 수 제한)"""
    return ontology_service.get_full_graph(db, limit)


@router.get("/gap-analysis", response_model=GapAnalysisResponse)
async def get_gap_analysis(db: Session = Depends(get_db)):
    """미매핑 현황 분석"""
    return ontology_service.get_gap_analysis(db)


@router.get("/mappings")
async def get_semantic_mappings(
    relation_type: Optional[str] = None,
    discovery_method: Optional[str] = None,
    min_confidence: float = 0.0,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """의미적 매핑 목록 조회 (필터링)"""
    return ontology_service.get_semantic_mappings(
        db,
        relation_type=relation_type,
        discovery_method=discovery_method,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )


# ── 실행 API (관리자용) ──────────────────────────────────────

@router.post("/extract-norms")
async def trigger_norm_extraction(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """전체 법조항 규범명제 추출 실행 (일괄)

    LLM API를 사용하여 442개 법조항을 규범명제로 분해합니다.
    소요 시간: 약 30분
    """
    result = await ontology_service.extract_all_norms(db)
    return result


@router.post("/classify-mappings")
async def trigger_mapping_classification(db: Session = Depends(get_db)):
    """기존 매핑 관계 유형 자동 분류 실행"""
    result = await ontology_service.classify_existing_mappings(db)
    return result


@router.post("/discover-mappings")
async def trigger_mapping_discovery(db: Session = Depends(get_db)):
    """미매핑 자동 발견 실행 (벡터+키워드+참조)

    3단계 파이프라인:
    1. 미매핑 법조항 → 가이드 발견 (벡터 유사도)
    2. 미매핑 가이드 → 법조항 발견 (키워드+범위)
    3. 법조항 간 상호 참조 발견
    """
    results = {}

    # Step 1: 미매핑 법조항 → 가이드
    r1 = await ontology_service.discover_unmapped_articles(db)
    results["unmapped_articles"] = r1

    # Step 2: 미매핑 가이드 → 법조항
    r2 = await ontology_service.discover_unmapped_guides(db)
    results["unmapped_guides"] = r2

    # Step 3: 법조항 간 참조
    r3 = await ontology_service.discover_cross_references(db)
    results["cross_references"] = r3

    results["status"] = "completed"
    results["new_mappings_found"] = (
        r1.get("new_mappings", 0) +
        r2.get("new_mappings", 0) +
        r3.get("new_references", 0)
    )

    return results
