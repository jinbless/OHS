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

    # GPT-5.2 category_code → HazardCategory 매핑
    CATEGORY_MAP = {
        "FALL": "physical",
        "COLLISION": "physical",
        "CRUSH": "physical",
        "CUT": "physical",
        "FALLING_OBJECT": "physical",
        "SLIP": "physical",
        "PHYSICAL": "physical",
        "CHEMICAL": "chemical",
        "FIRE_EXPLOSION": "chemical",
        "CORROSION": "chemical",
        "TOXIC": "chemical",
        "ELECTRIC": "electrical",
        "ELECTRICAL": "electrical",
        "ARC_FLASH": "electrical",
        "ERGONOMIC": "ergonomic",
        "REPETITIVE": "ergonomic",
        "HEAVY_LIFTING": "ergonomic",
        "POSTURE": "ergonomic",
        "NOISE": "environmental",
        "TEMPERATURE": "environmental",
        "LIGHTING": "environmental",
        "ENVIRONMENTAL": "environmental",
        "BIOLOGICAL": "biological",
    }

    def _map_category(self, category_code: str) -> str:
        """GPT-5.2 category_code를 HazardCategory 값으로 변환"""
        return self.CATEGORY_MAP.get(category_code.upper(), "physical")

    def _derive_overall_risk_level(self, risks: list) -> str:
        """risks의 최고 severity에서 overall_risk_level 도출"""
        severity_priority = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
        severity_order = ["HIGH", "MEDIUM", "LOW"]
        for sev in severity_order:
            if any(r.get("severity") == sev for r in risks):
                return severity_priority[sev]
        return "medium"

    def _create_response(
        self,
        db: Session,
        result: dict,
        analysis_type: str,
        input_preview: str
    ) -> AnalysisResponse:
        """GPT-5.2 분석 결과를 응답 형식으로 변환하고 DB에 저장"""
        analysis_id = str(uuid.uuid4())
        analyzed_at = datetime.now()

        # GPT-5.2 risks → Hazards 변환
        hazards = []
        hazard_categories = []
        for r in result.get("risks", []):
            category = self._map_category(r.get("category_code", "PHYSICAL"))
            hazard_categories.append(category)
            hazards.append(Hazard(
                id=str(uuid.uuid4()),
                category=HazardCategory(category) if category in [e.value for e in HazardCategory] else HazardCategory.PHYSICAL,
                name=r.get("category_name", ""),
                description=r.get("description", ""),
                risk_level=RiskLevel(r.get("severity", "MEDIUM").lower()),
                location=r.get("location"),
                potential_consequences=[r.get("description", "")],
                preventive_measures=r.get("recommendations", []),
                legal_reference=None
            ))

        # GPT-5.2 immediate_actions → Checklist 변환
        checklist_items = []
        for i, action in enumerate(result.get("immediate_actions", []), start=1):
            checklist_items.append(ChecklistItem(
                id=str(uuid.uuid4()),
                category="즉시 조치",
                item=action,
                description=None,
                priority=i,
                is_mandatory=True
            ))

        checklist = Checklist(
            title="안전점검 체크리스트",
            workplace_type=None,
            items=checklist_items
        )

        # 관련 리소스 가져오기
        resources = resource_service.get_resources_by_categories(hazard_categories)

        # overall_risk_level 도출
        overall_risk_level = self._derive_overall_risk_level(result.get("risks", []))

        # GPT-5.2 overall_assessment → summary
        summary = result.get("overall_assessment", "")

        # immediate_actions → recommendations
        recommendations = result.get("immediate_actions", [])

        # 응답 생성
        response = AnalysisResponse(
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            overall_risk_level=RiskLevel(overall_risk_level),
            summary=summary,
            hazards=hazards,
            checklist=checklist,
            resources=resources,
            recommendations=recommendations,
            analyzed_at=analyzed_at
        )

        # DB에 저장
        crud.create_analysis_record(
            db=db,
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            overall_risk_level=overall_risk_level,
            summary=summary,
            input_preview=input_preview,
            result_json=response.model_dump()
        )

        return response


analysis_service = AnalysisService()
