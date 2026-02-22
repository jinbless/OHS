from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.models.hazard import Hazard, RiskLevel, NormSummary
from app.models.checklist import Checklist
from app.models.resource import Resource
from app.models.guide import GuideMatch


class ImageAnalysisRequest(BaseModel):
    workplace_type: Optional[str] = None
    additional_context: Optional[str] = None


class TextAnalysisRequest(BaseModel):
    description: str
    workplace_type: Optional[str] = None
    industry_sector: Optional[str] = None


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
