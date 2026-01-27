from typing import Optional
from datetime import datetime
import uuid
from sqlalchemy.orm import Session

from app.integrations.openai_client import openai_client
from app.services.resource_service import resource_service
from app.models.analysis import AnalysisResponse
from app.models.hazard import Hazard, RiskLevel, HazardCategory
from app.models.checklist import Checklist, ChecklistItem
from app.db import crud
from app.utils.exceptions import OpenAIAPIError


class AnalysisService:
    async def analyze_image(
        self,
        db: Session,
        image_base64: str,
        filename: str,
        workplace_type: Optional[str] = None,
        additional_context: Optional[str] = None
    ) -> AnalysisResponse:
        """이미지 기반 위험요소 분석"""
        try:
            result = await openai_client.analyze_image(
                image_base64=image_base64,
                workplace_type=workplace_type,
                additional_context=additional_context
            )
        except Exception as e:
            raise OpenAIAPIError(f"AI 분석 실패: {str(e)}")

        return self._create_response(
            db=db,
            result=result,
            analysis_type="image",
            input_preview=filename
        )

    async def analyze_text(
        self,
        db: Session,
        description: str,
        workplace_type: Optional[str] = None,
        industry_sector: Optional[str] = None
    ) -> AnalysisResponse:
        """텍스트 기반 위험요소 분석"""
        try:
            result = await openai_client.analyze_text(
                description=description,
                workplace_type=workplace_type,
                industry_sector=industry_sector
            )
        except Exception as e:
            raise OpenAIAPIError(f"AI 분석 실패: {str(e)}")

        # 입력 미리보기 (최대 100자)
        input_preview = description[:100] + "..." if len(description) > 100 else description

        return self._create_response(
            db=db,
            result=result,
            analysis_type="text",
            input_preview=input_preview
        )

    def _create_response(
        self,
        db: Session,
        result: dict,
        analysis_type: str,
        input_preview: str
    ) -> AnalysisResponse:
        """분석 결과를 응답 형식으로 변환하고 DB에 저장"""
        analysis_id = str(uuid.uuid4())
        analyzed_at = datetime.now()

        # Hazards 변환
        hazards = []
        hazard_categories = []
        for h in result.get("hazards", []):
            category = h.get("category", "physical")
            hazard_categories.append(category)
            hazards.append(Hazard(
                id=h.get("id", str(uuid.uuid4())),
                category=HazardCategory(category) if category in [e.value for e in HazardCategory] else HazardCategory.PHYSICAL,
                name=h.get("name", ""),
                description=h.get("description", ""),
                risk_level=RiskLevel(h.get("risk_level", "medium")),
                location=h.get("location"),
                potential_consequences=h.get("potential_consequences", []),
                preventive_measures=h.get("preventive_measures", []),
                legal_reference=h.get("legal_reference")
            ))

        # Checklist 변환
        checklist_data = result.get("checklist", {})
        checklist_items = []
        for item in checklist_data.get("items", []):
            checklist_items.append(ChecklistItem(
                id=item.get("id", str(uuid.uuid4())),
                category=item.get("category", ""),
                item=item.get("item", ""),
                description=item.get("description"),
                priority=item.get("priority", 1),
                is_mandatory=item.get("is_mandatory", False)
            ))

        checklist = Checklist(
            title=checklist_data.get("title", "안전점검 체크리스트"),
            workplace_type=None,
            items=checklist_items
        )

        # 관련 리소스 가져오기
        resources = resource_service.get_resources_by_categories(hazard_categories)

        # 응답 생성
        response = AnalysisResponse(
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            overall_risk_level=RiskLevel(result.get("overall_risk_level", "medium")),
            summary=result.get("summary", ""),
            hazards=hazards,
            checklist=checklist,
            resources=resources,
            recommendations=result.get("recommendations", []),
            analyzed_at=analyzed_at
        )

        # DB에 저장
        crud.create_analysis_record(
            db=db,
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            overall_risk_level=result.get("overall_risk_level", "medium"),
            summary=result.get("summary", ""),
            input_preview=input_preview,
            result_json=response.model_dump()
        )

        return response


analysis_service = AnalysisService()
