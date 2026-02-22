"""LLM을 활용한 법조항 규범명제 자동 추출 서비스.

온톨로지 보고서의 NormStatement(주체-행위-객체-요건-효과) 패턴 적용.
"""
import json
import asyncio
import logging
from typing import List, Optional

from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 산업안전보건법 법조항 분석 전문가입니다.
주어진 법조항 텍스트를 규범명제(NormStatement) 단위로 분해하세요.

각 규범명제는 다음 구조를 가집니다:
- subject_role: 의무/권리의 주체 (사업주, 근로자, 관리감독자, 안전관리자 등)
- action: 구체적 행위 (설치, 점검, 교부, 착용, 배치 등)
- object: 행위의 대상/객체 (안전난간, 방호장치, 보호구, 안전표지 등)
- condition_text: 적용 조건 (높이2m이상, 인화성물질, 상시근로자5인이상 등). 없으면 null.
- legal_effect: 다음 중 하나만 사용:
  - OBLIGATION: ~해야 한다 (의무)
  - PROHIBITION: ~하여서는 아니 된다 (금지)
  - PERMISSION: ~할 수 있다 (허용)
  - EXCEPTION: ~의 경우에는 그러하지 아니하다 (예외)
- effect_description: 효과를 간략히 설명 (예: "안전난간 설치 의무", "사용 금지")
- paragraph: 해당 항 번호 (제1항, 제2항 등). 없으면 null.
- norm_category: 다음 중 하나:
  - safety: 안전/위험 관련 (추락, 감전, 화재, 폭발 등)
  - procedure: 절차/관리 (신고, 보고, 교육, 점검 등)
  - equipment: 설비/장비 (보호구, 기계, 장치 등)
  - management: 행정/관리 (서류, 기록, 자격 등)

규칙:
1. 하나의 법조항에 여러 의무/금지가 있으면 각각 별개의 규범명제로 분해
2. 항(①, ② 등)이 있으면 항 단위로 분해
3. 단서 조항("다만...")은 EXCEPTION으로 별도 분해
4. full_text는 해당 규범명제에 대응하는 원문 텍스트를 그대로 포함

반드시 JSON 배열로만 응답하세요. 추가 설명 없이 JSON만 출력합니다."""

NORM_SCHEMA = {
    "name": "norm_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "norms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject_role": {"type": ["string", "null"]},
                        "action": {"type": ["string", "null"]},
                        "object": {"type": ["string", "null"]},
                        "condition_text": {"type": ["string", "null"]},
                        "legal_effect": {
                            "type": "string",
                            "enum": ["OBLIGATION", "PROHIBITION", "PERMISSION", "EXCEPTION"]
                        },
                        "effect_description": {"type": ["string", "null"]},
                        "paragraph": {"type": ["string", "null"]},
                        "norm_category": {
                            "type": "string",
                            "enum": ["safety", "procedure", "equipment", "management"]
                        },
                        "full_text": {"type": "string"}
                    },
                    "required": [
                        "subject_role", "action", "object", "condition_text",
                        "legal_effect", "effect_description", "paragraph",
                        "norm_category", "full_text"
                    ],
                    "additionalProperties": False
                }
            }
        },
        "required": ["norms"],
        "additionalProperties": False
    }
}

VALID_EFFECTS = {"OBLIGATION", "PROHIBITION", "PERMISSION", "EXCEPTION"}
VALID_CATEGORIES = {"safety", "procedure", "equipment", "management"}


class NormExtractor:
    """법조항 텍스트에서 규범명제를 추출하는 서비스"""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4.1"
        self._semaphore = asyncio.Semaphore(5)

    async def extract_norms(self, article_number: str, article_text: str) -> List[dict]:
        """단일 법조항에서 규범명제 목록 추출"""
        user_prompt = f"법조항: {article_number}\n본문:\n{article_text}"

        async with self._semaphore:
            for attempt in range(3):
                try:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "developer", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        response_format={
                            "type": "json_schema",
                            "json_schema": NORM_SCHEMA
                        },
                        max_tokens=4096,
                        temperature=0.1,
                    )

                    result = json.loads(response.choices[0].message.content)
                    norms = result.get("norms", [])

                    # 검증 및 보정
                    validated = []
                    for i, norm in enumerate(norms):
                        if self.validate_norm(norm):
                            norm["statement_order"] = i + 1
                            norm["article_number"] = article_number
                            validated.append(norm)

                    logger.info(f"{article_number}: {len(validated)}개 규범명제 추출")
                    return validated

                except Exception as e:
                    logger.warning(f"{article_number} 추출 실패 (시도 {attempt + 1}/3): {e}")
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)

        logger.error(f"{article_number}: 규범명제 추출 최종 실패")
        return []

    async def batch_extract(self, articles: List[dict]) -> dict:
        """복수 법조항 일괄 처리 (배치)

        Args:
            articles: [{"article_number": "제42조", "content": "..."}]

        Returns:
            {"total": N, "processed": N, "norms": [...], "errors": [...]}
        """
        all_norms = []
        errors = []

        tasks = [
            self.extract_norms(a["article_number"], a["content"])
            for a in articles
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for article, result in zip(articles, results):
            if isinstance(result, Exception):
                errors.append(f"{article['article_number']}: {str(result)}")
            elif result:
                all_norms.extend(result)

        return {
            "total": len(articles),
            "processed": len(articles) - len(errors),
            "norms": all_norms,
            "errors": errors,
        }

    def validate_norm(self, norm: dict) -> bool:
        """추출된 규범명제 유효성 검증"""
        # legal_effect 필수
        effect = norm.get("legal_effect")
        if not effect or effect not in VALID_EFFECTS:
            return False

        # full_text 필수
        if not norm.get("full_text"):
            return False

        # norm_category 보정
        cat = norm.get("norm_category")
        if cat and cat not in VALID_CATEGORIES:
            norm["norm_category"] = "management"  # 기본값

        return True


norm_extractor = NormExtractor()
