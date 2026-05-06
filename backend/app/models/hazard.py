from pydantic import BaseModel
from enum import Enum
from typing import List, Optional


class HazardCategory(str, Enum):
    PHYSICAL = "physical"
    CHEMICAL = "chemical"
    BIOLOGICAL = "biological"
    ERGONOMIC = "ergonomic"
    ELECTRICAL = "electrical"
    ENVIRONMENTAL = "environmental"


class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class NormSummary(BaseModel):
    """위험요소에 연결된 규범명제 요약"""
    article_number: str
    legal_effect: str
    action: Optional[str] = None
    full_text: str


class FacetedHazardCodes(BaseModel):
    """Faceted 3축 canonical hazard codes (결정론적)"""
    accident_types: List[str] = []
    hazardous_agents: List[str] = []
    work_contexts: List[str] = []
    applied_rules: List[str] = []
    confidence: float = 0.0


class GptFreeObservation(BaseModel):
    """Track A: GPT 자유 관찰"""
    label: str
    description: str
    confidence: float
    visual_evidence: Optional[str] = None
    severity: str = "MEDIUM"


class CodeGapWarning(BaseModel):
    """코드 체계 gap 경고"""
    gap_type: str  # UNMAPPED / FORCED_FIT
    gpt_free_label: Optional[str] = None
    description: str


class PenaltyInfo(BaseModel):
    """벌칙 경로 정보"""
    article_code: str
    title: str
    criminal_employer_penalty: Optional[str] = None
    criminal_death_penalty: Optional[str] = None
    admin_max_fine: Optional[str] = None


class PenaltyCandidate(BaseModel):
    """Condition-aware penalty candidate from pen:PenaltyRule."""
    penalty_rule_id: str
    exposure_type: str  # direct_candidate | conditional
    condition_label: str
    subject_role: Optional[str] = None
    accident_outcome: Optional[str] = None
    violated_norm_id: Optional[str] = None
    violated_article_id: Optional[str] = None
    delegated_from_article_id: Optional[str] = None
    penalty_article_id: Optional[str] = None
    sanction_type: Optional[str] = None
    penalty_description: Optional[str] = None
    severity_score: Optional[int] = None
    basis_text: Optional[str] = None
    source_sr_id: Optional[str] = None


class PenaltyPath(BaseModel):
    """Business-facing penalty notice grouped into coarse outcome paths."""
    path_type: str  # general_incident | death | serious_accident
    title: str
    notice_level: str  # photo_based | external_fact_required | conditional
    summary: str
    penalty_rule_ids: List[str] = []
    penalty_descriptions: List[str] = []
    article_refs: List[dict] = []
    max_severity_score: Optional[int] = None
    source_sr_ids: List[str] = []


class Hazard(BaseModel):
    id: str
    category: HazardCategory
    name: str
    description: str
    risk_level: RiskLevel
    location: Optional[str] = None
    potential_consequences: List[str]
    preventive_measures: List[str]
    legal_reference: Optional[str] = None
    related_norms: List[NormSummary] = []
