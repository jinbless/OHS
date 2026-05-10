from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from sqlalchemy.orm import Session

from app.integrations.openai_client import openai_client
from app.models.analysis import AnalysisResponse
from app.services.analysis_pipeline import AnalysisRunInput, analysis_pipeline
from app.utils.exceptions import OpenAIAPIError

logger = logging.getLogger(__name__)


class AnalysisService:
    async def analyze_image(
        self,
        db: Session,
        image_base64: str,
        filename: str,
        workplace_type: Optional[str] = None,
        additional_context: Optional[str] = None,
    ) -> AnalysisResponse:
        result = await self._run_ai_analysis(
            lambda: openai_client.analyze_image(
                image_base64=image_base64,
                workplace_type=workplace_type,
                additional_context=additional_context,
            )
        )
        return await analysis_pipeline.run(
            db=db,
            run_input=AnalysisRunInput(
                result=result,
                analysis_type="image",
                input_preview=filename,
                declared_industry_text=workplace_type,
            ),
        )

    async def analyze_text(
        self,
        db: Session,
        description: str,
        workplace_type: Optional[str] = None,
        industry_sector: Optional[str] = None,
    ) -> AnalysisResponse:
        result = await self._run_ai_analysis(
            lambda: openai_client.analyze_text(
                description=description,
                workplace_type=workplace_type,
                industry_sector=industry_sector,
            )
        )
        input_preview = description[:100] + "..." if len(description) > 100 else description
        return await analysis_pipeline.run(
            db=db,
            run_input=AnalysisRunInput(
                result=result,
                analysis_type="text",
                input_preview=input_preview,
                full_description=description,
                declared_industry_text=industry_sector or workplace_type,
            ),
        )

    async def _run_ai_analysis(
        self,
        call: Callable[[], Awaitable[dict]],
    ) -> dict:
        try:
            return await call()
        except OpenAIAPIError:
            raise
        except Exception as exc:
            logger.exception("AI analysis failed")
            raise OpenAIAPIError(
                "AI 분석 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
            ) from exc


analysis_service = AnalysisService()
