from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.models.hazard import (
    Hazard, RiskLevel, NormSummary,
    FacetedHazardCodes, GptFreeObservation, CodeGapWarning, PenaltyInfo,
)
from app.models.checklist import Checklist
from app.models.resource import Resource
from app.models.guide import GuideMatch


class TextAnalysisRequest(BaseModel):
    description: str
    workplace_type: Optional[str] = None
    industry_sector: Optional[str] = None


class RecommendedSR(BaseModel):
    """Phase 0.5 — 추천된 SR을 source/layer로 분리해서 노출.

    이전: 응답에 SR ID가 sparql_enrichment.co_applicable_srs로만 노출.
    문제: primary SR (hazard_rule_engine.query_sr_for_facets 결과)이 평가에 안 잡힘 →
          evaluate_catalog.py SR Recall 0%의 진짜 원인 일부.
    해결: primary/coApplicable/she_derived/embedding/rerank 전 source의 SR을
    명시적으로 응답에 노출 → evaluate_catalog.py가 정확한 metric 측정 가능.
    """
    identifier: str            # 예: SR-FALL-001
    source: str                # "primary" | "coApplicable" | "she_derived" | "embedding" | "rerank"
    layer: int                 # 0=SHE, 1=PG @>, 2=embedding, 3=rerank, 4=SPARQL
    confidence: float = 1.0    # 0.0~1.0
    title: Optional[str] = None  # 가독성용 (선택)


class LinkedGuideSummary(BaseModel):
    guide_code: str
    title: str
    relation_type: str
    confidence: float


class NormContext(BaseModel):
    """분석 결과에 포함되는 온톨로지 컨텍스트"""
    article_number: str
    article_title: Optional[str] = None
    norms: List[NormSummary] = []
    linked_guides: List[LinkedGuideSummary] = []


class SparqlEnrichmentSummary(BaseModel):
    """SPARQL 추론 보강 결과 요약"""
    source: str = "pg_only"  # "pg_only" | "pg+sparql" | "sparql_inferred"
    co_applicable_srs: List[dict] = []
    exemptions: List[dict] = []
    high_severity_srs: List[dict] = []
    fuseki_available: bool = False


class AnalysisResponse(BaseModel):
    analysis_id: str
    analysis_type: str  # "image" or "text"
    overall_risk_level: RiskLevel
    summary: str
    hazards: List[Hazard]
    checklist: Checklist
    resources: List[Resource]
    related_guides: List[GuideMatch] = []
    norm_context: List[NormContext] = []
    recommendations: List[str]
    analyzed_at: datetime
    # Phase 3: Dual-Track
    canonical_hazards: Optional[FacetedHazardCodes] = None
    gpt_free_observations: List[GptFreeObservation] = []
    decision_type: str = "deterministic_rule"  # deterministic_rule / embedding_fallback
    code_gap_warnings: List[CodeGapWarning] = []
    penalties: List[PenaltyInfo] = []
    # Phase 5: SPARQL enrichment
    sparql_enrichment: Optional[SparqlEnrichmentSummary] = None
    # Phase 0.5: 추천 SR 명시적 노출 (source/layer/confidence 포함)
    recommended_srs: List[RecommendedSR] = []

    class Config:
        from_attributes = True


class AnalysisHistoryItem(BaseModel):
    analysis_id: str
    analysis_type: str
    overall_risk_level: RiskLevel
    summary: str
    analyzed_at: datetime
    input_preview: Optional[str] = None

    class Config:
        from_attributes = True


class AnalysisHistoryResponse(BaseModel):
    total: int
    items: List[AnalysisHistoryItem]
