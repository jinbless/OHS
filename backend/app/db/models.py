from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Enum as SQLEnum, UniqueConstraint
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
