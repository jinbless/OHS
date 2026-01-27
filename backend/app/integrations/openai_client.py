from openai import AsyncOpenAI
import json
from typing import Optional
from app.config import settings
from app.integrations.prompts.analysis_prompts import (
    SYSTEM_PROMPT,
    IMAGE_ANALYSIS_PROMPT,
    TEXT_ANALYSIS_PROMPT
)


class OpenAIClient:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4o"

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
                {"role": "system", "content": SYSTEM_PROMPT},
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
            response_format={"type": "json_object"},
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
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=4096,
            temperature=0.3
        )

        result = response.choices[0].message.content
        return json.loads(result)


openai_client = OpenAIClient()
