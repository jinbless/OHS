from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.models.checklist import Checklist
from app.models.guide import GuideMatch
from app.models.hazard import (
    CodeGapWarning,
    FacetedHazardCodes,
    GptFreeObservation,
    Hazard,
    NormSummary,
    PenaltyCandidate,
    PenaltyInfo,
    PenaltyPath,
    RiskLevel,
)
from app.models.resource import Resource


class TextAnalysisRequest(BaseModel):
    description: str
    workplace_type: Optional[str] = None
    industry_sector: Optional[str] = None


class RecommendedSR(BaseModel):
    """Safety requirement candidate exposed with source and rank context."""
    identifier: str
    source: str
    layer: int
    confidence: float = 1.0
    title: Optional[str] = None


class ActionRecommendation(BaseModel):
    """Structured corrective-action recommendation for API/UI responses."""
    rank: int
    source: str
    match_reason: str
    requirement_id: Optional[str] = None
    requirement_title: Optional[str] = None
    guide_code: Optional[str] = None
    guide_title: Optional[str] = None
    checklist_id: Optional[str] = None
    checklist_text: Optional[str] = None
    confidence: float = 1.0
    display_group: str = "legal_basis"
    urgency: str = "reference"


class LinkedGuideSummary(BaseModel):
    guide_code: str
    title: str
    relation_type: str
    confidence: float


class NormContext(BaseModel):
    """Legal context included in an analysis result."""
    article_number: str
    article_title: Optional[str] = None
    norms: List[NormSummary] = []
    linked_guides: List[LinkedGuideSummary] = []


class SparqlEnrichmentSummary(BaseModel):
    """SPARQL enrichment summary."""
    source: str = "pg_only"
    co_applicable_srs: List[dict] = []
    exemptions: List[dict] = []
    high_severity_srs: List[dict] = []
    fuseki_available: bool = False


class IndustryContextSummary(BaseModel):
    """Declared/inferred industry context used as a ranking signal."""
    declared_industries: List[str] = []
    inferred_industries: List[str] = []
    primary_industry: Optional[str] = None
    primary_label: Optional[str] = None
    confidence: float = 0.0
    needs_confirmation: bool = False
    confirmation_question: Optional[str] = None
    evidence: List[str] = []


class AnalysisResponse(BaseModel):
    analysis_id: str
    analysis_type: str
    overall_risk_level: RiskLevel
    summary: str
    hazards: List[Hazard]
    checklist: Checklist
    resources: List[Resource]
    related_guides: List[GuideMatch] = []
    norm_context: List[NormContext] = []
    recommendations: List[str]
    analyzed_at: datetime
    canonical_hazards: Optional[FacetedHazardCodes] = None
    gpt_free_observations: List[GptFreeObservation] = []
    decision_type: str = "deterministic_rule"
    code_gap_warnings: List[CodeGapWarning] = []
    penalties: List[PenaltyInfo] = []
    penalty_candidates: List[PenaltyCandidate] = []
    penalty_paths: List[PenaltyPath] = []
    sparql_enrichment: Optional[SparqlEnrichmentSummary] = None
    recommended_srs: List[RecommendedSR] = []
    finding_status: str = "not_determined"
    penalty_exposure_status: str = "no_penalty"
    action_recommendations: List[ActionRecommendation] = []
    industry_context: Optional[IndustryContextSummary] = None

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
