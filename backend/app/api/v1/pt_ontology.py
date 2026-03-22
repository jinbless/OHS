"""포르투갈어 온톨로지 API 엔드포인트."""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.pt_ontology_service import pt_ontology_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pt-ontology", tags=["PT 온톨로지"])


@router.get("/stats")
async def get_pt_mapping_stats(db: Session = Depends(get_db)):
    """매핑 통계 (PT)"""
    return pt_ontology_service.get_mapping_stats(db)


@router.get("/articles/{article_number}/norms")
async def get_pt_article_norms(article_number: str, db: Session = Depends(get_db)):
    """특정 법조항의 PT 규범명제 + 가이드"""
    return pt_ontology_service.get_article_norms(db, article_number)


@router.get("/articles/{article_number}/graph")
async def get_pt_article_graph(article_number: str, db: Session = Depends(get_db)):
    """특정 법조항 중심 PT 그래프"""
    return pt_ontology_service.get_article_graph(db, article_number)


@router.get("/graph")
async def get_pt_full_graph(limit: int = 100, db: Session = Depends(get_db)):
    """전체 온톨로지 PT 그래프"""
    return pt_ontology_service.get_full_graph(db, limit)
