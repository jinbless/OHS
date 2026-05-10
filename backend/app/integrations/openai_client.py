import json
from typing import Optional

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.integrations.prompts.analysis_prompts import (
    IMAGE_ANALYSIS_PROMPT,
    SYSTEM_PROMPT,
    TEXT_ANALYSIS_PROMPT,
)


ONTOLOGY_OBSERVATION_SCHEMA = {
    "name": "ontology_observation",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "visual_observations": {
                "type": "array",
                "description": "Facts directly visible in the photo or described in text.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "confidence": {"type": "number"},
                        "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                    },
                    "required": ["text", "confidence", "severity"],
                    "additionalProperties": False,
                },
            },
            "visual_cues": {
                "type": "array",
                "description": "Short visual cues used for SHE pattern matching.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "cue_type": {
                            "type": "string",
                            "enum": ["object", "state", "absence", "environment", "activity", "other"],
                        },
                        "confidence": {"type": "number"},
                    },
                    "required": ["text", "cue_type", "confidence"],
                    "additionalProperties": False,
                },
            },
            "risk_feature_candidates": {
                "type": "array",
                "description": "Candidate terms for risk:RiskFeature normalization.",
                "items": {
                    "type": "object",
                    "properties": {
                        "axis": {
                            "type": "string",
                            "enum": ["accident_type", "hazardous_agent", "work_context"],
                        },
                        "text": {"type": "string"},
                        "evidence": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                    },
                    "required": ["axis", "text", "evidence", "confidence"],
                    "additionalProperties": False,
                },
            },
            "overall_assessment": {"type": "string"},
            "immediate_actions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "visual_observations",
            "visual_cues",
            "risk_feature_candidates",
            "overall_assessment",
            "immediate_actions",
        ],
        "additionalProperties": False,
    },
}


class OpenAIClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            http_client=httpx.AsyncClient(trust_env=False),
        )
        self.model = "gpt-4.1"

    async def analyze_image(
        self,
        image_base64: str,
        workplace_type: Optional[str] = None,
        additional_context: Optional[str] = None,
    ) -> dict:
        user_prompt = IMAGE_ANALYSIS_PROMPT.format(
            workplace_type=workplace_type or "unknown",
            additional_context=additional_context or "none",
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
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            response_format={"type": "json_schema", "json_schema": ONTOLOGY_OBSERVATION_SCHEMA},
            max_tokens=4096,
        )
        return json.loads(response.choices[0].message.content or "{}")

    async def analyze_text(
        self,
        description: str,
        workplace_type: Optional[str] = None,
        industry_sector: Optional[str] = None,
    ) -> dict:
        user_prompt = TEXT_ANALYSIS_PROMPT.format(
            description=description,
            workplace_type=workplace_type or "unknown",
            industry_sector=industry_sector or "unknown",
        )
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "developer", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_schema", "json_schema": ONTOLOGY_OBSERVATION_SCHEMA},
            max_tokens=4096,
        )
        return json.loads(response.choices[0].message.content or "{}")


openai_client = OpenAIClient()
