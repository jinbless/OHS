from openai import AsyncOpenAI
import json
from typing import Optional
from app.config import settings
from app.integrations.prompts.analysis_prompts import (
    SYSTEM_PROMPT,
    IMAGE_ANALYSIS_PROMPT,
    TEXT_ANALYSIS_PROMPT
)


# JSON Schema 정의 (위험분석 응답 구조)
RISK_ANALYSIS_SCHEMA = {
    "name": "risk_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category_code": {
                            "type": "string",
                            "description": "위험 카테고리 코드 (FALL, ELECTRIC, FIRE_EXPLOSION 등)"
                        },
                        "category_name": {
                            "type": "string",
                            "description": "위험 카테고리 한글명"
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                            "description": "위험도"
                        },
                        "confidence": {
                            "type": "number",
                            "description": "신뢰도 (0.0 ~ 1.0)"
                        },
                        "description": {
                            "type": "string",
                            "description": "위험 상황 설명"
                        },
                        "location": {
                            "type": ["string", "null"],
                            "description": "이미지 내 위험 위치"
                        },
                        "recommendations": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "권장 조치사항"
                        }
                    },
                    "required": ["category_code", "category_name", "severity", "confidence", "description", "location", "recommendations"],
                    "additionalProperties": False
                }
            },
            "overall_assessment": {
                "type": "string",
                "description": "전반적인 안전 평가"
            },
            "immediate_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "즉시 필요한 조치사항"
            }
        },
        "required": ["risks", "overall_assessment", "immediate_actions"],
        "additionalProperties": False
    }
}


class OpenAIClient:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-5.2"

    async def analyze_image(
        self,
        image_base64: str,
        workplace_type: Optional[str] = None,
        additional_context: Optional[str] = None
    ) -> dict:
        """이미지 기반 위험요소 분석"""
        user_prompt = IMAGE_ANALYSIS_PROMPT.format(
            workplace_type=workplace_type or "미지정",
            additional_context=additional_context or "없음"
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "developer", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": RISK_ANALYSIS_SCHEMA
            },
            reasoning_effort="high",
            max_tokens=4096,
            temperature=0.3
        )

        result = response.choices[0].message.content
        return json.loads(result)

    async def analyze_text(
        self,
        description: str,
        workplace_type: Optional[str] = None,
        industry_sector: Optional[str] = None
    ) -> dict:
        """텍스트 기반 위험요소 분석"""
        user_prompt = TEXT_ANALYSIS_PROMPT.format(
            description=description,
            workplace_type=workplace_type or "미지정",
            industry_sector=industry_sector or "미지정"
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "developer", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": RISK_ANALYSIS_SCHEMA
            },
            reasoning_effort="high",
            max_tokens=4096,
            temperature=0.3
        )

        result = response.choices[0].message.content
        return json.loads(result)


openai_client = OpenAIClient()
