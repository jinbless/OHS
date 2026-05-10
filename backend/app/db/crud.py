from sqlalchemy.orm import Session
from typing import List, Optional
import json
from app.db.models import AnalysisRecord


def create_analysis_record(
    db: Session,
    analysis_id: str,
    analysis_type: str,
    overall_risk_level: str,
    summary: str,
    input_preview: str,
    result_json: dict,
    gpt_free_hazards: dict = None,
    coded_hazards: dict = None,
    divergence_report: dict = None,
) -> AnalysisRecord:
    db_record = AnalysisRecord(
        id=analysis_id,
        analysis_type=analysis_type,
        overall_risk_level=overall_risk_level,
        summary=summary,
        input_preview=input_preview,
        result_json=result_json,  # JSONB — no json.dumps needed
        gpt_free_hazards=gpt_free_hazards,
        coded_hazards=coded_hazards,
        divergence_report=divergence_report,
    )
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    return db_record


def create_product_analysis_record(
    db: Session,
    analysis_id: str,
    analysis_type: str,
    overall_risk_level: str,
    summary: str,
    input_preview: str,
    result_json: dict,
    observations: list[dict],
    risk_features: list[dict],
) -> AnalysisRecord:
    """Persist the current product response while preserving legacy columns."""
    return create_analysis_record(
        db=db,
        analysis_id=analysis_id,
        analysis_type=analysis_type,
        overall_risk_level=overall_risk_level,
        summary=summary,
        input_preview=input_preview,
        result_json=result_json,
        gpt_free_hazards=observations,
        coded_hazards=risk_features,
        divergence_report=None,
    )


def get_analysis_record(db: Session, analysis_id: str) -> Optional[AnalysisRecord]:
    return db.query(AnalysisRecord).filter(AnalysisRecord.id == analysis_id).first()


def get_analysis_history(
    db: Session,
    skip: int = 0,
    limit: int = 20
) -> tuple[int, List[AnalysisRecord]]:
    total = db.query(AnalysisRecord).count()
    records = (
        db.query(AnalysisRecord)
        .order_by(AnalysisRecord.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return total, records


def delete_analysis_record(db: Session, analysis_id: str) -> bool:
    record = db.query(AnalysisRecord).filter(AnalysisRecord.id == analysis_id).first()
    if record:
        db.delete(record)
        db.commit()
        return True
    return False
