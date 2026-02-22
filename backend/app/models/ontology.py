"""온톨로지 기반 매핑 API 응답 모델"""
from pydantic import BaseModel
from typing import Optional, List


# --- 규범명제 ---

class NormStatementResponse(BaseModel):
    id: int
    article_number: str
    paragraph: Optional[str] = None
    statement_order: int
    subject_role: Optional[str] = None
    action: Optional[str] = None
    object: Optional[str] = None
    condition_text: Optional[str] = None
    legal_effect: str  # OBLIGATION | PROHIBITION | PERMISSION | EXCEPTION
    effect_description: Optional[str] = None
    full_text: str
    norm_category: Optional[str] = None


class LinkedGuideInfo(BaseModel):
    guide_code: str
    title: str
    classification: str
    relation_type: str  # IMPLEMENTS | SUPPLEMENTS | ...
    confidence: float
    discovery_method: str


class ArticleNormsResponse(BaseModel):
    article_number: str
    article_title: Optional[str] = None
    total_norms: int
    norms: List[NormStatementResponse]
    linked_guides: List[LinkedGuideInfo]


# --- 의미적 매핑 ---

class SemanticMappingResponse(BaseModel):
    id: int
    source_type: str
    source_id: str
    source_label: Optional[str] = None
    target_type: str
    target_id: str
    target_label: Optional[str] = None
    relation_type: str
    relation_detail: Optional[str] = None
    confidence: float
    discovery_method: str
    discovery_tier: Optional[str] = None


# --- 매핑 통계 ---

class MappingStatsResponse(BaseModel):
    total_articles: int
    mapped_articles: int
    unmapped_articles: int
    total_guides: int
    mapped_guides: int
    unmapped_guides: int
    total_explicit_mappings: int
    total_semantic_mappings: int
    mapping_by_relation_type: dict
    mapping_by_discovery: dict
    coverage_improvement: dict


# --- 매핑 갭 분석 ---

class UnmappedArticle(BaseModel):
    article_number: str
    article_title: Optional[str] = None
    norm_category: Optional[str] = None
    suggested_guides: List[LinkedGuideInfo] = []


class UnmappedGuide(BaseModel):
    guide_code: str
    title: str
    classification: str
    suggested_articles: List[str] = []


class GapAnalysisResponse(BaseModel):
    unmapped_articles: List[UnmappedArticle]
    unmapped_guides: List[UnmappedGuide]
    high_priority_count: int


# --- 실행 결과 ---

class ExtractionResult(BaseModel):
    status: str
    total_articles: int
    processed: int
    total_norms_extracted: int
    errors: List[str] = []


class ClassificationResult(BaseModel):
    status: str
    total_mappings: int
    classified: int
    by_relation_type: dict


class DiscoveryResult(BaseModel):
    status: str
    new_mappings_found: int
    unmapped_articles_resolved: int
    unmapped_guides_resolved: int
