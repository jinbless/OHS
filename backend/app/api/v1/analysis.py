from fastapi import APIRouter, UploadFile, File, Form, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
import json

from app.db.database import get_db
from app.db import crud
from app.models.analysis import (
    TextAnalysisRequest,
    AnalysisResponse,
    AnalysisHistoryItem,
    AnalysisHistoryResponse
)
from app.services.analysis_service import analysis_service
from app.utils.file_handler import file_handler
from app.utils.exceptions import AnalysisNotFoundError

router = APIRouter()


@router.post("/image", response_model=AnalysisResponse)
async def analyze_image(
    image: UploadFile = File(..., description="분석할 이미지 파일"),
    workplace_type: Optional[str] = Form(None, description="작업장 유형"),
    additional_context: Optional[str] = Form(None, description="추가 상황 설명"),
    db: Session = Depends(get_db)
):
    """
    이미지 기반 위험요소 분석

    작업현장 이미지를 업로드하면 AI가 산업재해 위험요소를 분석합니다.
    """
    # 파일 검증
    await file_handler.validate_image(image)

    # 이미지를 Base64로 변환
    image_base64 = await file_handler.image_to_base64(image)

    # 분석 수행
    result = await analysis_service.analyze_image(
        db=db,
        image_base64=image_base64,
        filename=image.filename or "unknown",
        workplace_type=workplace_type,
        additional_context=additional_context
    )

    return result


@router.post("/text", response_model=AnalysisResponse)
async def analyze_text(
    request: TextAnalysisRequest,
    db: Session = Depends(get_db)
):
    """
    텍스트 기반 위험요소 분석

    작업 상황을 텍스트로 설명하면 AI가 산업재해 위험요소를 분석합니다.
    """
    result = await analysis_service.analyze_text(
        db=db,
        description=request.description,
        workplace_type=request.workplace_type,
        industry_sector=request.industry_sector
    )

    return result


@router.get("/history", response_model=AnalysisHistoryResponse)
async def get_analysis_history(
    skip: int = Query(0, ge=0, description="건너뛸 항목 수"),
    limit: int = Query(20, ge=1, le=100, description="조회할 항목 수"),
    db: Session = Depends(get_db)
):
    """
    분석 기록 목록 조회

    저장된 분석 기록을 최신순으로 조회합니다.
    """
    total, records = crud.get_analysis_history(db, skip=skip, limit=limit)

    items = [
        AnalysisHistoryItem(
            analysis_id=r.id,
            analysis_type=r.analysis_type,
            overall_risk_level=r.overall_risk_level,
            summary=r.summary,
            analyzed_at=r.created_at,
            input_preview=r.input_preview
        )
        for r in records
    ]

    return AnalysisHistoryResponse(total=total, items=items)


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str,
    db: Session = Depends(get_db)
):
    """
    특정 분석 결과 조회

    저장된 분석 결과를 상세 조회합니다.
    """
    record = crud.get_analysis_record(db, analysis_id)
    if not record:
        raise AnalysisNotFoundError(analysis_id)

    result_data = record.result_json if isinstance(record.result_json, dict) else json.loads(record.result_json)
    return AnalysisResponse(**result_data)


@router.delete("/{analysis_id}")
async def delete_analysis(
    analysis_id: str,
    db: Session = Depends(get_db)
):
    """
    분석 기록 삭제
    """
    success = crud.delete_analysis_record(db, analysis_id)
    if not success:
        raise AnalysisNotFoundError(analysis_id)

    return {"message": "분석 기록이 삭제되었습니다.", "analysis_id": analysis_id}
