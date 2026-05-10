"""공통 텍스트 처리 유틸리티

중복 제거를 위해 서비스 전체에서 사용하는 토크나이징/키워드 처리 함수를 통합.
"""
import re
from typing import List


# ── 조사 제거 접미사 (통합) ──────────────────────────────────
JOSA_SUFFIX = "이가을를은는에서와도의로으로"


def tokenize_korean(text: str, min_length: int = 2) -> List[str]:
    """한국어 텍스트를 공백 기반으로 토크나이징하고 조사를 제거.

    Args:
        text: 입력 텍스트
        min_length: 최소 토큰 길이 (기본 2글자)

    Returns:
        토큰 리스트
    """
    tokens = []
    for w in text.split():
        clean = w.rstrip(JOSA_SUFFIX)
        if len(clean) >= min_length:
            tokens.append(clean)
    return tokens


def extract_article_number(text: str) -> int:
    """'제42조' → 42, '제42조의2' → 42 형태로 조문 번호 추출.

    Args:
        text: 조문 번호 문자열

    Returns:
        정수 조문 번호. 추출 실패 시 0.
    """
    m = re.search(r"제(\d+)조", text)
    return int(m.group(1)) if m else 0
