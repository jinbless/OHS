from sqlalchemy.orm import Session
from typing import List, Optional
import json
from app.db.models import AnalysisRecord
from app.models.analysis import AnalysisResponse, AnalysisHistoryItem


def create_analysis_record(
    db: Session,
    analysis_id: str,
    analysis_type: str,
    overall_risk_level: str,
    summary: str,
    input_preview: str,
    result_json: dict
) -> AnalysisRecord:
    db_record = AnalysisRecord(
        id=analysis_id,
        analysis_type=analysis_type,
        overall_risk_level=overall_risk_level,
        summary=summary,
        input_preview=input_preview,
        result_json=json.dumps(result_json, ensure_ascii=False, default=str)
    )
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    return db_record


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
