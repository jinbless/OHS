"""통합 위험 분류 체계 + 법조항 계층 구조 유틸리티

Phase 1: hazard_taxonomy.json 기반 분류 변환
Phase 2: article_chapters.json 기반 계층 조회
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_TAXONOMY = None
_CHAPTERS = None

# ── Phase 1: 통합 분류 체계 ──────────────────────────────────

def _load_taxonomy() -> dict:
    global _TAXONOMY
    if _TAXONOMY is None:
        path = Path(__file__).parent.parent / "data" / "hazard_taxonomy.json"
        with open(path, "r", encoding="utf-8") as f:
            _TAXONOMY = json.load(f)
    return _TAXONOMY


def code_to_major(hazard_code: str) -> Optional[str]:
    """세부코드 → 대분류. 예: 'FALL' → 'physical'"""
    t = _load_taxonomy()
    return t["code_to_major"].get(hazard_code.upper())


def major_to_codes(major: str) -> list[str]:
    """대분류 → 세부코드 목록. 예: 'physical' → ['FALL','SLIP',...]"""
    t = _load_taxonomy()
    cat = t["major_categories"].get(major, {})
    return cat.get("codes", [])


def legacy_to_majors(norm_category: str) -> list[str]:
    """레거시 norm_category → 가능한 대분류 목록."""
    t = _load_taxonomy()
    result = []
    for major, info in t["major_categories"].items():
        if norm_category in info.get("legacy_norm_category", []):
            result.append(major)
    return result


def get_all_codes() -> list[str]:
    """전체 세부코드 목록"""
    t = _load_taxonomy()
    return list(t["code_to_major"].keys())


# ── Phase 2: 법조항 계층 구조 ────────────────────────────────

def _load_chapters() -> list:
    global _CHAPTERS
    if _CHAPTERS is None:
        path = Path(__file__).parent.parent / "data" / "article_chapters.json"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _CHAPTERS = data["chapters"]
    return _CHAPTERS


def get_chapter_for_article(article_num: int) -> Optional[dict]:
    """조문 번호 → 장(chapter) 정보 반환"""
    for ch in _load_chapters():
        r = ch["article_range"]
        if r[0] <= article_num <= r[1]:
            return ch
    return None


def get_articles_for_category(hazard_major: str) -> list[tuple[int, int]]:
    """대분류 → 조문 범위 목록 (CATEGORY_ARTICLE_RANGE 대체)"""
    ranges = []
    for ch in _load_chapters():
        if ch.get("hazard_major") == hazard_major:
            ranges.append(tuple(ch["article_range"]))
    return ranges


def get_article_range_for_classification(kosha_cls: str) -> Optional[tuple[int, int]]:
    """KOSHA 분류코드 → 첫 번째 매칭 조문 범위 (CLASSIFICATION_TO_ARTICLE_RANGE 대체)
    None을 반환하면 전체 범위(필터 없음)"""
    if kosha_cls in ("G", "T", "X", "K"):
        return None  # 전체 범위
    for ch in _load_chapters():
        if kosha_cls in ch.get("kosha_classifications", []):
            return tuple(ch["article_range"])
    return None


def get_all_ranges_for_classification(kosha_cls: str) -> list[tuple[int, int]]:
    """KOSHA 분류코드 → 모든 매칭 조문 범위 목록"""
    if kosha_cls in ("G", "T", "X", "K"):
        return []  # 전체 범위 (필터 없음)
    ranges = []
    for ch in _load_chapters():
        if kosha_cls in ch.get("kosha_classifications", []):
            ranges.append(tuple(ch["article_range"]))
    return ranges


def get_classifications_for_article(article_num: int) -> list[str]:
    """조문 번호 → 관련 KOSHA 분류코드 목록"""
    ch = get_chapter_for_article(article_num)
    if ch:
        return ch.get("kosha_classifications", [])
    return []
