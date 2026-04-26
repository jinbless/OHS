from openai import AsyncOpenAI
import json
from typing import Optional
from app.config import settings
from app.integrations.prompts.analysis_prompts import (
    SYSTEM_PROMPT,
    IMAGE_ANALYSIS_PROMPT,
    TEXT_ANALYSIS_PROMPT
)


# ═══ Dual-Track JSON Schema (Phase 3) ═══
# Track A: 자유 분류 (코드 제약 없음)
# Track B: Faceted 3축 코드 분류 + 기존 호환 필드
DUAL_TRACK_SCHEMA = {
    "name": "risk_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            # ── Track A: 자유 분류 ──
            "free_hazards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "위험요소 자유 명칭 (한글)"
                        },
                        "description": {
                            "type": "string",
                            "description": "위험 상황 상세 설명"
                        },
                        "confidence": {
                            "type": "number",
                            "description": "신뢰도 (0.0 ~ 1.0)"
                        },
                        "visual_evidence": {
                            "type": ["string", "null"],
                            "description": "이미지/텍스트에서 근거가 되는 관찰 내용"
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                            "description": "위험도"
                        }
                    },
                    "required": ["label", "description", "confidence", "visual_evidence", "severity"],
                    "additionalProperties": False
                },
                "description": "Track A: 코드 제약 없이 자유롭게 기술한 위험요소"
            },
            # ── Track B: Faceted 3축 코드 분류 ──
            "faceted_hazards": {
                "type": "object",
                "properties": {
                    "accident_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "사고 유형 코드: FALL, SLIP, COLLISION, FALLING_OBJECT, CRUSH, CUT, COLLAPSE, ERGONOMIC"
                    },
                    "hazardous_agents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "유해 인자 코드: CHEMICAL, DUST, TOXIC, CORROSION, RADIATION, FIRE, ELECTRICITY, ARC_FLASH, NOISE, HEAT_COLD, BIOLOGICAL"
                    },
                    "work_contexts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "작업 맥락 코드: SCAFFOLD, CONFINED_SPACE, EXCAVATION, MACHINE, VEHICLE, CRANE, RAIL, CONVEYOR, PRESSURE_VESSEL, STEELWORK, MATERIAL_HANDLING, GENERAL_WORKPLACE"
                    },
                    "forced_fit_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "정확히 맞는 코드가 없어 억지로 매핑한 경우 이유 기록"
                    }
                },
                "required": ["accident_types", "hazardous_agents", "work_contexts", "forced_fit_notes"],
                "additionalProperties": False
            },
            # ── 기존 호환 필드 ──
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
            },
            "recommended_guide_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "KOSHA GUIDE 검색용 한국어 키워드 (최대 5개)"
            },
            "related_article_hints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "article_number": {
                            "type": "string",
                            "description": "관련 법조항 번호 (예: '제42조')"
                        },
                        "reason": {
                            "type": "string",
                            "description": "이 조문이 관련된 이유 (1문장)"
                        }
                    },
                    "required": ["article_number", "reason"],
                    "additionalProperties": False
                },
                "description": "관련 조문번호 (최대 5개)"
            }
        },
        "required": [
            "free_hazards", "faceted_hazards",
            "risks", "overall_assessment", "immediate_actions",
            "recommended_guide_keywords", "related_article_hints"
        ],
        "additionalProperties": False
    }
}


class OpenAIClient:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4.1"

    async def analyze_image(
        self,
        image_base64: str,
        workplace_type: Optional[str] = None,
        additional_context: Optional[str] = None
    ) -> dict:
        """이미지 기반 위험요소 분석 (Dual-Track)"""
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
                "json_schema": DUAL_TRACK_SCHEMA
            },
            max_tokens=4096
        )

        result = response.choices[0].message.content
        return json.loads(result)

    async def analyze_text(
        self,
        description: str,
        workplace_type: Optional[str] = None,
        industry_sector: Optional[str] = None
    ) -> dict:
        """텍스트 기반 위험요소 분석 (Dual-Track)"""
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
                "json_schema": DUAL_TRACK_SCHEMA
            },
            max_tokens=4096
        )

        result = response.choices[0].message.content
        return json.loads(result)


openai_client = OpenAIClient()
