"""통합 위험 분류 체계 + 법조항 계층 구조 유틸리티

Phase 1: hazard_taxonomy.json 기반 분류 변환
Phase 2: article_chapters.json 기반 계층 조회
Phase 3: faceted 3축 (accident_type / hazardous_agent / work_context) 지원
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_TAXONOMY = None
_CHAPTERS = None

# ── 데이터 로드 ──────────────────────────────────────────


def _load_taxonomy() -> dict:
    global _TAXONOMY
    if _TAXONOMY is None:
        path = Path(__file__).parent.parent / "data" / "hazard_taxonomy.json"
        with open(path, "r", encoding="utf-8") as f:
            _TAXONOMY = json.load(f)
    return _TAXONOMY


# ── Phase 1: 레거시 호환 (기존 함수 유지) ─────────────────


def code_to_major(hazard_code: str) -> Optional[str]:
    """세부코드 → 대분류. 예: 'FALL' → 'physical'"""
    t = _load_taxonomy()
    compat = t.get("legacy_compat", {})
    return compat.get("code_to_major", {}).get(hazard_code.upper())


def major_to_codes(major: str) -> list[str]:
    """대분류 → 세부코드 목록. 예: 'physical' → ['FALL','SLIP',...]"""
    t = _load_taxonomy()
    compat = t.get("legacy_compat", {})
    cat = compat.get("major_categories", {}).get(major, {})
    return cat.get("codes", [])


def legacy_to_majors(norm_category: str) -> list[str]:
    """레거시 norm_category → 가능한 대분류 목록."""
    t = _load_taxonomy()
    compat = t.get("legacy_compat", {})
    result = []
    for major, info in compat.get("major_categories", {}).items():
        if norm_category in info.get("legacy_norm_category", []):
            result.append(major)
    return result


def get_all_codes() -> list[str]:
    """전체 세부코드 목록"""
    t = _load_taxonomy()
    compat = t.get("legacy_compat", {})
    return list(compat.get("code_to_major", {}).keys())


# ── Phase 3: Faceted 3축 ─────────────────────────────────


def get_axis_codes(axis: str) -> dict:
    """축별 코드 딕셔너리 반환. axis: 'accident_type' | 'hazardous_agent' | 'work_context'"""
    t = _load_taxonomy()
    axis_data = t.get("axes", {}).get(axis, {})
    return axis_data.get("codes", {})


def get_axis_label(axis: str) -> str:
    """축 한글 라벨. 예: 'accident_type' → '사고 유형'"""
    t = _load_taxonomy()
    return t.get("axes", {}).get(axis, {}).get("label", axis)


def get_all_axis_code_list(axis: str) -> list[str]:
    """축의 모든 코드(sub 포함) flat list. 예: accident_type → ['FALL','SLIP','COLLISION',...]"""
    codes = get_axis_codes(axis)
    result = []
    for code, info in codes.items():
        result.append(code)
        for sub in info.get("sub", []):
            result.append(sub)
    return result


def get_faceted_code_label(code: str) -> Optional[str]:
    """코드 → 한글 라벨 (모든 축 탐색). 예: 'FALL' → '추락'"""
    t = _load_taxonomy()
    for axis_data in t.get("axes", {}).values():
        for c, info in axis_data.get("codes", {}).items():
            if c == code:
                return info.get("label", code)
            for sub in info.get("sub", []):
                if sub == code:
                    return info.get("label", code)
    return None


def resolve_legacy_code(legacy_code: str) -> Optional[dict]:
    """레거시 코드를 faceted 축+코드로 변환.
    예: 'SCAFFOLDING' → {'axis': 'work_context', 'code': 'SCAFFOLD'}
    """
    t = _load_taxonomy()
    return t.get("legacy_migration", {}).get(legacy_code.upper())


def get_axes() -> list[str]:
    """축 이름 목록"""
    t = _load_taxonomy()
    return list(t.get("axes", {}).keys())


# ── Phase 2: 법조항 계층 구조 ────────────────────────────


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
    """KOSHA 분류코드 → 첫 번째 매칭 조문 범위"""
    if kosha_cls in ("G", "T", "X", "K"):
        return None
    for ch in _load_chapters():
        if kosha_cls in ch.get("kosha_classifications", []):
            return tuple(ch["article_range"])
    return None


def get_all_ranges_for_classification(kosha_cls: str) -> list[tuple[int, int]]:
    """KOSHA 분류코드 → 모든 매칭 조문 범위 목록"""
    if kosha_cls in ("G", "T", "X", "K"):
        return []
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
