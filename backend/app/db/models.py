from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Enum as SQLEnum, UniqueConstraint, Index
from sqlalchemy.sql import func
from app.db.database import Base
from app.models.hazard import RiskLevel
import uuid


class AnalysisRecord(Base):
    __tablename__ = "analysis_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_type = Column(String(10), nullable=False)  # "image" or "text"
    overall_risk_level = Column(String(20), nullable=False)
    summary = Column(Text, nullable=False)
    input_preview = Column(Text, nullable=True)  # 텍스트 입력 또는 이미지 파일명
    result_json = Column(Text, nullable=False)  # 전체 결과 JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KoshaGuide(Base):
    __tablename__ = "kosha_guides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guide_code = Column(String(30), unique=True, nullable=False)  # "G-1-2023"
    classification = Column(String(5), nullable=False)  # "G"
    guide_number = Column(Integer, nullable=False)  # 1
    guide_year = Column(Integer, nullable=False)  # 2023
    title = Column(Text, nullable=False)
    author = Column(Text, nullable=True)
    related_regulations = Column(Text, nullable=True)  # JSON array of article numbers
    pdf_filename = Column(Text, nullable=False)
    total_pages = Column(Integer, nullable=True)
    total_chars = Column(Integer, nullable=True)
    parsed_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GuideSection(Base):
    __tablename__ = "guide_sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guide_id = Column(Integer, nullable=False)  # FK to kosha_guides.id
    section_order = Column(Integer, nullable=False)
    section_title = Column(Text, nullable=True)
    section_type = Column(String(20), nullable=True)  # purpose/scope/definition/standard/procedure/appendix
    body_text = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RegGuideMapping(Base):
    __tablename__ = "reg_guide_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_number = Column(String(30), nullable=False)  # "제42조"
    guide_id = Column(Integer, nullable=False)  # FK to kosha_guides.id
    mapping_type = Column(String(20), nullable=False)  # "explicit" / "auto"
    mapping_basis = Column(Text, nullable=True)
    relevance_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('article_number', 'guide_id', name='uq_reg_guide'),
    )


class NormStatement(Base):
    """법조항을 규범명제(요건→효과) 단위로 분해한 결과"""
    __tablename__ = "norm_statements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_number = Column(String(30), nullable=False, index=True)  # "제42조"
    paragraph = Column(String(20), nullable=True)  # "제1항"
    statement_order = Column(Integer, nullable=False, default=1)

    # 규범명제 구성요소 (온톨로지 L3 레이어)
    subject_role = Column(Text, nullable=True)       # "사업주" | "근로자" | "관리감독자"
    action = Column(Text, nullable=True)             # "추락방지조치" | "설치" | "점검"
    object = Column(Text, nullable=True)             # "안전난간" | "방호장치" | "보호구"
    condition_text = Column(Text, nullable=True)     # "높이 2m 이상" | "인화성 물질 부근"
    legal_effect = Column(String(20), nullable=False, index=True)  # OBLIGATION | PROHIBITION | PERMISSION | EXCEPTION
    effect_description = Column(Text, nullable=True)  # "설치 의무" | "사용 금지"

    # 메타데이터
    full_text = Column(Text, nullable=False)
    norm_category = Column(String(20), nullable=True, index=True)  # safety | procedure | equipment | management

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('article_number', 'paragraph', 'statement_order', name='uq_norm_stmt'),
    )


class SemanticMapping(Base):
    """온톨로지 기반 의미적 매핑 (기존 reg_guide_mapping 보강)"""
    __tablename__ = "semantic_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 소스 (법조항 or 규범명제)
    source_type = Column(String(20), nullable=False)  # "article" | "norm_statement"
    source_id = Column(String(50), nullable=False)    # "제42조" or norm_statement.id

    # 타겟 (가이드 or 법조항)
    target_type = Column(String(20), nullable=False)  # "guide" | "article"
    target_id = Column(String(50), nullable=False)    # guide_id or "제44조"

    # 관계 정보 (온톨로지 L4 레이어)
    relation_type = Column(String(30), nullable=False)  # IMPLEMENTS | SUPPLEMENTS | ...
    relation_detail = Column(Text, nullable=True)

    # 발견 메타데이터
    confidence = Column(Float, nullable=False, default=0.0)
    discovery_method = Column(String(20), nullable=False)  # "llm" | "vector" | "reference" | "keyword"
    discovery_tier = Column(String(5), nullable=True)      # "A" ~ "F"

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('source_type', 'source_id', 'target_type', 'target_id', 'relation_type',
                         name='uq_semantic_map'),
        Index('idx_sm_source', 'source_type', 'source_id'),
        Index('idx_sm_target', 'target_type', 'target_id'),
        Index('idx_sm_relation', 'relation_type'),
        Index('idx_sm_confidence', 'confidence'),
    )


class SafetyVideo(Base):
    """KOSHA 안전 숏폼영상"""
    __tablename__ = "safety_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    url = Column(String(255), unique=True, nullable=False)
    category = Column(Text, nullable=False)          # 원본 분야 (예: "건설안전 / 추락예방")
    tags = Column(Text, nullable=True)               # JSON array of keywords
    hazard_categories = Column(Text, nullable=False)  # JSON array (예: ["physical","fall"])
    series = Column(String(30), nullable=True)        # 시리즈명
    is_korean = Column(Integer, nullable=False, default=1)  # 1=한국어, 0=영어
    thumbnail_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_sv_hazard_cat', 'hazard_categories'),
        Index('idx_sv_series', 'series'),
    )
