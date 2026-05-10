"""검색 품질 강화 서비스

Phase 2 개선사항을 통합:
- E: 한국어 형태소 분석 (kiwipiepy)
- C: LLM 쿼리 재작성 (일상어 → 법률 용어)
- D: LLM 재랭킹 (검색 결과 의미적 재평가)
"""
import json
import logging
from typing import List, Optional

from openai import AsyncOpenAI
from app.config import settings
from app.utils.text_utils import tokenize_korean

logger = logging.getLogger(__name__)

# ── E: 한국어 형태소 분석 ─────────────────────────────────────

_kiwi = None


def get_kiwi():
    """kiwipiepy 인스턴스를 lazy-load"""
    global _kiwi
    if _kiwi is None:
        try:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
            logger.info("kiwipiepy 형태소 분석기 로드 완료")
        except ImportError:
            logger.warning("kiwipiepy 미설치 - 폴백 키워드 추출 사용")
            _kiwi = False  # 설치 안 됨 표시
    return _kiwi if _kiwi is not False else None


def extract_nouns(text: str) -> List[str]:
    """텍스트에서 명사를 추출 (kiwipiepy 사용, 없으면 폴백)"""
    kiwi = get_kiwi()
    if kiwi:
        try:
            tokens = kiwi.tokenize(text)
            # NNG(일반명사), NNP(고유명사), NNB(의존명사) 추출
            nouns = []
            for t in tokens:
                if t.tag.startswith("NN") and len(t.form) >= 2:
                    nouns.append(t.form)
            # 중복 제거, 순서 유지
            seen = set()
            unique = []
            for n in nouns:
                if n not in seen:
                    seen.add(n)
                    unique.append(n)
            return unique
        except Exception as e:
            logger.warning(f"형태소 분석 실패, 폴백 사용: {e}")

    # 폴백: 기존 방식 (split + 조사 제거)
    stopwords = {
        "위험", "사고", "작업", "안전", "관련", "발생", "가능", "경우", "상태",
        "조치", "방치", "예방", "존재", "높음", "관한", "위한", "대한", "인한",
    }
    words = [w for w in tokenize_korean(text) if w not in stopwords]
    seen = set()
    return [w for w in words if not (w in seen or seen.add(w))]


def extract_keywords_for_search(descriptions: List[str]) -> List[str]:
    """위험요소 설명 목록에서 검색용 키워드 추출"""
    all_nouns = []
    for desc in descriptions:
        all_nouns.extend(extract_nouns(desc))

    # 빈도 기반 정렬
    freq = {}
    for n in all_nouns:
        freq[n] = freq.get(n, 0) + 1

    sorted_nouns = sorted(freq.keys(), key=lambda x: freq[x], reverse=True)
    return sorted_nouns[:10]


# ── C: LLM 쿼리 재작성 ──────────────────────────────────────

QUERY_REWRITE_PROMPT = """위험요소 설명을 산업안전보건법 조문 검색에 적합한 법률 키워드로 변환하세요.

규칙:
1. 일상 용어를 법률 용어로 변환 (예: "높은 곳" → "추락", "전기줄" → "충전부 감전")
2. 핵심 명사만 공백으로 구분하여 출력
3. 최대 10개 키워드
4. 추가 설명 없이 키워드만 출력

예시:
- "주방에 날카로운 칼이 놓여있다" → "절단 수공구 날 방호장치 보관 안전조치"
- "사다리에서 페인트칠 작업 중" → "추락 사다리 고소작업 방지 안전대"
- "밀폐된 탱크 내부 점검" → "밀폐공간 산소결핍 환기 질식 보호구"
"""


async def rewrite_query_for_legal_search(description: str) -> Optional[str]:
    """위험요소 설명 → 법률 검색 쿼리 변환 (gpt-4.1-mini)"""
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": QUERY_REWRITE_PROMPT},
                {"role": "user", "content": description}
            ],
            max_tokens=100,
            temperature=0.1,
        )
        rewritten = response.choices[0].message.content.strip()
        logger.info(f"[쿼리재작성] '{description[:50]}...' → '{rewritten}'")
        return rewritten
    except Exception as e:
        logger.warning(f"쿼리 재작성 실패: {e}")
        return None


async def rewrite_queries_batch(descriptions: List[str]) -> str:
    """여러 위험요소 설명을 하나의 검색 쿼리로 통합 변환"""
    combined = " / ".join(d[:100] for d in descriptions)
    rewritten = await rewrite_query_for_legal_search(combined)
    if rewritten:
        return rewritten
    # 폴백: 형태소 분석 키워드
    keywords = extract_keywords_for_search(descriptions)
    return " ".join(keywords)


# ── D: LLM 재랭킹 ───────────────────────────────────────────

RERANK_PROMPT = """당신은 산업안전보건법 전문가입니다.
아래 위험요소와 법조항/가이드 후보의 관련성을 평가하세요.

위험요소:
{hazard_text}

후보 목록:
{candidates_text}

각 후보에 대해 관련성 점수(0~10)를 매기세요.
- 10: 직접적으로 해당 위험을 규율하는 조문
- 7~9: 관련 위험 유형을 다루는 조문
- 4~6: 간접적 관련
- 0~3: 무관

JSON 배열로만 응답: [{"id": "후보번호", "score": 점수}]"""


RERANK_SCHEMA = {
    "name": "rerank_results",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "rankings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "score": {"type": "number"}
                    },
                    "required": ["id", "score"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["rankings"],
        "additionalProperties": False
    }
}


async def rerank_results(
    hazard_descriptions: List[str],
    candidates: List[dict],
    max_candidates: int = 15,
) -> List[dict]:
    """LLM 재랭킹: 후보를 의미적 관련성으로 재평가

    candidates: [{"id": "...", "title": "...", "content": "...", "original_score": float, ...}]
    Returns: 동일 리스트를 재정렬하여 반환
    """
    if not candidates or not hazard_descriptions:
        return candidates

    # 후보가 적으면 재랭킹 비용 대비 효과 낮음
    if len(candidates) <= 3:
        return candidates

    # 상위 N개만 재랭킹 (비용 절약)
    to_rerank = candidates[:max_candidates]

    hazard_text = "\n".join(f"- {d}" for d in hazard_descriptions)
    candidates_text = "\n".join(
        f"[{i+1}] {c.get('article_number', c.get('guide_code', '?'))}: "
        f"{c.get('title', '')} — {c.get('content', c.get('excerpt', ''))[:100]}"
        for i, c in enumerate(to_rerank)
    )

    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "산업안전보건법 전문가로서 위험요소와 후보의 관련성을 JSON으로 평가."
                },
                {
                    "role": "user",
                    "content": RERANK_PROMPT.format(
                        hazard_text=hazard_text,
                        candidates_text=candidates_text,
                    )
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": RERANK_SCHEMA
            },
            max_tokens=500,
            temperature=0.1,
        )

        result = json.loads(response.choices[0].message.content)
        rankings = result.get("rankings", [])

        # 점수 매핑
        score_map = {}
        for r in rankings:
            try:
                idx = int(r["id"]) - 1 if r["id"].isdigit() else -1
                if 0 <= idx < len(to_rerank):
                    score_map[idx] = r["score"] / 10.0  # 0~1로 정규화
            except (ValueError, KeyError):
                continue

        # 원본 점수와 LLM 점수를 가중 평균 (LLM 60%, 원본 40%)
        for i, c in enumerate(to_rerank):
            if i in score_map:
                original = c.get("original_score", c.get("relevance_score", c.get("score", 0.5)))
                llm_score = score_map[i]
                c["rerank_score"] = round(original * 0.4 + llm_score * 0.6, 4)
                c["llm_relevance"] = llm_score
            else:
                c["rerank_score"] = c.get("original_score", c.get("relevance_score", c.get("score", 0.5)))

        # 재랭킹 점수로 재정렬
        to_rerank.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

        logger.info(f"[재랭킹] {len(to_rerank)}개 후보 재정렬 완료")
        return to_rerank + candidates[max_candidates:]

    except Exception as e:
        logger.warning(f"LLM 재랭킹 실패 (원본 순서 유지): {e}")
        return candidates
