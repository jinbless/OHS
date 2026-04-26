"""온톨로지 기반 매핑 API 응답 모델"""
from pydantic import BaseModel
from typing import Optional, List


# --- 규범명제 ---

class NormStatementResponse(BaseModel):
    id: Optional[str] = None
    article_number: str
    paragraph: Optional[str] = None
    statement_order: int = 0
    subject_role: Optional[str] = None
    action: Optional[str] = None
    object: Optional[str] = None
    condition_text: Optional[str] = None
    legal_effect: Optional[str] = None
    effect_description: Optional[str] = None
    full_text: Optional[str] = None
    norm_category: Optional[str] = None
    hazard_major: Optional[str] = None
    hazard_codes: List[str] = []


class LinkedGuideInfo(BaseModel):
    guide_code: str
    title: str
    classification: Optional[str] = None
    relation_type: str = "IMPLEMENTS"
    confidence: float = 0.9
    discovery_method: str = "pg_mapping"


class ArticleNormsResponse(BaseModel):
    article_number: str
    article_title: Optional[str] = None
    total_norms: int
    norms: List[NormStatementResponse]
    linked_guides: List[LinkedGuideInfo]


# --- 의미적 매핑 ---

class SemanticMappingResponse(BaseModel):
    id: Optional[str] = None
    source_type: str = "article"
    source_id: str = ""
    source_label: Optional[str] = None
    target_type: str = "guide"
    target_id: str = ""
    target_label: Optional[str] = None
    target_title: Optional[str] = None
    relation_type: str = "IMPLEMENTS"
    relation_detail: Optional[str] = None
    confidence: float = 0.9
    discovery_method: str = "pg_mapping"
    discovery_tier: Optional[str] = None


# --- 매핑 통계 ---

class MappingStatsResponse(BaseModel):
    total_articles: int
    total_guides: int
    total_norms: int = 0
    total_sr: int = 0
    total_ci: int = 0
    explicit_mapped_articles: int = 0
    semantic_mapped_articles: int = 0
    all_mapped_articles: int = 0
    all_mapped_guides: int = 0
    total_explicit_mappings: int = 0
    total_semantic_mappings: int = 0
    relation_distribution: dict = {}
    method_distribution: dict = {}


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
    total_articles: int = 0
    mapped_articles: int = 0
    unmapped_count: int = 0
    coverage_pct: float = 0.0
    unmapped_articles: list = []


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
