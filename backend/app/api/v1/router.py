from fastapi import APIRouter
from app.api.v1 import analysis, resources, health, ontology, pt_ontology

router = APIRouter()

router.include_router(health.router, tags=["헬스체크"])
router.include_router(analysis.router, prefix="/analysis", tags=["분석"])
router.include_router(resources.router, prefix="/resources", tags=["리소스"])
router.include_router(ontology.router)
router.include_router(pt_ontology.router)
