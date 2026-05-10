from fastapi import APIRouter

from app.api.v1 import analysis, health, ontology, pt_ontology, sparql

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
router.include_router(ontology.router)
router.include_router(pt_ontology.router)
router.include_router(sparql.router)
