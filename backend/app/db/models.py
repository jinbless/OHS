"""ORM 모델 — PostgreSQL koshaontology DB 직접 참조.

PG 기존 테이블: 읽기 전용 ORM (스키마 변경 없음)
OHS 전용 테이블: ohs_analysis_records, ohs_safety_videos (신규 생성)
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.database import Base
import uuid


# ═══════════════════════════════════════════════════════════
# PG 기존 테이블 — 읽기 전용 ORM (koshaontology 소유)
# ═══════════════════════════════════════════════════════════

class PgKoshaGuide(Base):
    """kosha_guides — PK: guide_code (VARCHAR)"""
    __tablename__ = "kosha_guides"
    __table_args__ = {"extend_existing": True}

    guide_code = Column(String(20), primary_key=True)
    short_code = Column(String(10), unique=True, nullable=False)
    title = Column(Text, nullable=False)
    domain = Column(String(1), nullable=False)  # A/B/C/D/E
    sub_category = Column(Text)
    total_pages = Column(Integer)
    ci_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PgChecklistItem(Base):
    """checklist_items — PK: identifier (VARCHAR, CI-XX-NNN)"""
    __tablename__ = "checklist_items"
    __table_args__ = {"extend_existing": True}

    identifier = Column(String(30), primary_key=True)
    text = Column(Text, nullable=False)
    guide_context = Column(Text)
    additional_detail = Column(Text)
    work_process_phase = Column(String(30))
    binding_force = Column(String(15), nullable=False)  # MANDATORY/RECOMMENDED
    requirement_type = Column(String(25))
    source_section = Column(Text, nullable=False)
    source_guide = Column(String(20), nullable=False)  # FK → kosha_guides
    accident_types = Column(JSONB)
    hazardous_agents = Column(JSONB)
    work_contexts = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PgNormStatement(Base):
    """norm_statements — PK: identifier (VARCHAR, NS-XX-N)"""
    __tablename__ = "norm_statements"
    __table_args__ = {"extend_existing": True}

    identifier = Column(String(30), primary_key=True)
    article_code = Column(String(20), nullable=False)
    law_id = Column(String(10), nullable=False)
    paragraph_ref = Column(Text, nullable=False)
    text = Column(Text, nullable=False)
    has_modality = Column(String(15), nullable=False)  # OBLIGATION/PROHIBITION/...
    has_subject_role = Column(Text)
    has_action = Column(Text)
    has_object = Column(Text)
    has_condition = Column(JSONB)
    has_sanction = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PgSafetyRequirement(Base):
    """safety_requirements — PK: identifier (VARCHAR, SR-XX-NNN)"""
    __tablename__ = "safety_requirements"
    __table_args__ = {"extend_existing": True}

    identifier = Column(String(30), primary_key=True)
    title = Column(Text, nullable=False)
    text = Column(Text, nullable=False)
    requirement_type = Column(String(25), nullable=False)
    binding_force = Column(String(15), nullable=False)
    addresses_hazard = Column(JSONB)
    has_sanction = Column(JSONB)
    accident_types = Column(JSONB)
    hazardous_agents = Column(JSONB)
    work_contexts = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PgArticle(Base):
    """articles — composite PK: (law_type, article_code)"""
    __tablename__ = "articles"
    __table_args__ = {"extend_existing": True}

    law_type = Column(String(10), primary_key=True)
    article_code = Column(String(20), primary_key=True)
    title = Column(Text, nullable=False)
    full_text = Column(Text, nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)
    section = Column(Text)
    paragraph_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PgPenaltyRoute(Base):
    """penalty_routes — composite PK: (law_type, article_code)"""
    __tablename__ = "penalty_routes"
    __table_args__ = {"extend_existing": True}

    law_type = Column(String(10), primary_key=True)
    article_code = Column(String(20), primary_key=True)
    title = Column(Text, nullable=False)
    has_penalty = Column(Boolean, nullable=False, default=False)
    has_administrative_fine = Column(Boolean, nullable=False, default=False)
    criminal_employer_law = Column(Text)
    criminal_employer_penalty = Column(Text)
    criminal_death_law = Column(Text)
    criminal_death_penalty = Column(Text)
    criminal_serious_law = Column(Text)
    criminal_serious_death = Column(Text)
    criminal_serious_injury = Column(Text)
    admin_law = Column(Text)
    admin_max_fine = Column(Text)


class PgCiSrMapping(Base):
    """ci_sr_mapping — composite PK: (ci_id, sr_id)"""
    __tablename__ = "ci_sr_mapping"
    __table_args__ = {"extend_existing": True}

    ci_id = Column(String(30), primary_key=True)
    sr_id = Column(String(30), primary_key=True)


class PgSrArticleMapping(Base):
    """sr_article_mapping — composite PK: (sr_id, law_type, article_code)"""
    __tablename__ = "sr_article_mapping"
    __table_args__ = {"extend_existing": True}

    sr_id = Column(String(30), primary_key=True)
    law_type = Column(String(10), primary_key=True)
    article_code = Column(String(20), primary_key=True)


class PgGuideArticleMapping(Base):
    """guide_article_mapping — composite PK: (guide_code, law_type, article_code)"""
    __tablename__ = "guide_article_mapping"
    __table_args__ = {"extend_existing": True}

    guide_code = Column(String(20), primary_key=True)
    law_type = Column(String(10), primary_key=True)
    article_code = Column(String(20), primary_key=True)


# ═══════════════════════════════════════════════════════════
# OHS 전용 테이블 — 읽기/쓰기 (OHS가 소유)
# ═══════════════════════════════════════════════════════════

class OhsAnalysisRecord(Base):
    """OHS 분석 기록"""
    __tablename__ = "ohs_analysis_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_type = Column(String(10), nullable=False)  # "image" / "text"
    overall_risk_level = Column(String(20), nullable=False)
    summary = Column(Text, nullable=False)
    input_preview = Column(Text)
    image_path = Column(Text)
    result_json = Column(JSONB)
    gpt_free_hazards = Column(JSONB)       # Phase 3: Track A
    coded_hazards = Column(JSONB)           # Phase 3: Track B
    divergence_report = Column(JSONB)       # Phase 3: gap detection
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OhsSafetyVideo(Base):
    """KOSHA 안전영상 (숏폼 + 일반 교육영상)"""
    __tablename__ = "ohs_safety_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    url = Column(String(255), unique=True, nullable=False)
    category = Column(Text, nullable=False)
    tags = Column(Text)                  # JSON array
    hazard_categories = Column(Text, nullable=False)  # JSON array
    hazard_codes = Column(Text)          # JSON array
    description = Column(Text)
    series = Column(String(30))
    is_korean = Column(Integer, nullable=False, default=1)
    thumbnail_url = Column(Text)
    video_type = Column(String(10), nullable=False, default='short')
    duration = Column(String(10))
    playlist = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_osv_hazard_cat', 'hazard_categories'),
        Index('idx_osv_series', 'series'),
        Index('idx_osv_video_type', 'video_type'),
    )


class OhsHazardCodeGap(Base):
    """코드 체계 gap 누적 테이블 — Track A/B 괴리에서 발견된 코드 부족"""
    __tablename__ = "ohs_hazard_code_gaps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gap_type = Column(String(20), nullable=False)  # UNMAPPED / FORCED_FIT
    gpt_free_label = Column(Text)
    nearest_code = Column(String(30))
    forced_fit_note = Column(Text)
    occurrence_count = Column(Integer, nullable=False, default=1)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now())
    sample_analysis_ids = Column(JSONB)  # UUID[] (최대 5개)
    promoted_to_code = Column(String(30))
    promoted_at = Column(DateTime(timezone=True))


# ═══════════════════════════════════════════════════════════
# 하위 호환 별칭 — 기존 import 경로 유지
# ═══════════════════════════════════════════════════════════

# 기존 코드에서 from app.db.models import AnalysisRecord 형태로 사용
AnalysisRecord = OhsAnalysisRecord
KoshaGuide = PgKoshaGuide
NormStatement = PgNormStatement
SafetyVideo = OhsSafetyVideo

# 기존 OHS SQLite 테이블(GuideSection, RegGuideMapping, SemanticMapping)은
# PG 테이블로 대체되었으므로 별칭을 남기지 않음.
# 서비스 코드에서 직접 PG ORM을 사용하도록 수정.
