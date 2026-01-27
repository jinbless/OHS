from sqlalchemy import Column, String, Text, DateTime, Enum as SQLEnum
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
