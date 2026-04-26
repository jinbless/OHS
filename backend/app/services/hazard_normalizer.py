"""Track B GPT 출력을 정규화하여 canonical faceted hazard codes로 변환.

입력: GPT faceted_hazards (accident_types[], hazardous_agents[], work_contexts[])
출력: 정규화된 FacetedHazards (유효한 코드만 + alias 해석)
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ALIASES = None
_TAXONOMY = None


def _load_aliases() -> dict:
    global _ALIASES
    if _ALIASES is None:
        path = Path(__file__).parent.parent / "data" / "hazard_aliases.json"
        with open(path, "r", encoding="utf-8") as f:
            _ALIASES = json.load(f)
    return _ALIASES


def _load_taxonomy() -> dict:
    global _TAXONOMY
    if _TAXONOMY is None:
        path = Path(__file__).parent.parent / "data" / "hazard_taxonomy.json"
        with open(path, "r", encoding="utf-8") as f:
            _TAXONOMY = json.load(f)
    return _TAXONOMY


def _get_valid_codes(axis: str) -> set:
    """축별 유효 코드 세트 (sub 포함)."""
    tax = _load_taxonomy()
    axis_data = tax.get("axes", {}).get(axis, {})
    codes = set()
    for code, info in axis_data.get("codes", {}).items():
        codes.add(code)
        for sub in info.get("sub", []):
            codes.add(sub)
    return codes


def _resolve_alias_code(raw_code: str, axis: str) -> Optional[str]:
    """GPT가 반환한 코드를 정규화. 유효하면 그대로, alias면 해석, 무효면 None."""
    upper = raw_code.upper().strip()
    valid = _get_valid_codes(axis)

    # 직접 매칭
    if upper in valid:
        return upper

    # 레거시 코드 변환
    tax = _load_taxonomy()
    legacy = tax.get("legacy_migration", {}).get(upper)
    if legacy and legacy.get("axis") == axis:
        return legacy["code"]

    # alias 매핑 (Tier 1)
    aliases = _load_aliases()
    tier1 = aliases.get("tier1", {}).get(axis, {})
    for code, terms in tier1.items():
        if upper in [t.upper() for t in terms] or raw_code in terms:
            return code

    return None


def normalize_faceted_hazards(
    gpt_faceted: dict,
    context_text: str = "",
) -> dict:
    """GPT Track B 출력을 정규화.

    Returns:
        {
            "accident_types": ["FALL", ...],
            "hazardous_agents": ["FIRE", ...],
            "work_contexts": ["SCAFFOLD", ...],
            "forced_fit_notes": [...],
            "unknown_codes": [...],   # 매핑 불가 코드
            "alias_resolved": [...],  # alias로 해석된 코드
        }
    """
    result = {
        "accident_types": [],
        "hazardous_agents": [],
        "work_contexts": [],
        "forced_fit_notes": list(gpt_faceted.get("forced_fit_notes", [])),
        "unknown_codes": [],
        "alias_resolved": [],
    }

    axis_map = {
        "accident_types": "accident_type",
        "hazardous_agents": "hazardous_agent",
        "work_contexts": "work_context",
    }

    for field, axis in axis_map.items():
        raw_codes = gpt_faceted.get(field, [])
        seen = set()
        for raw in raw_codes:
            resolved = _resolve_alias_code(raw, axis)
            if resolved and resolved not in seen:
                seen.add(resolved)
                result[field].append(resolved)
                if resolved != raw.upper().strip():
                    result["alias_resolved"].append(
                        f"{raw} → {resolved} ({axis})"
                    )
            elif not resolved:
                # 다른 축에서 찾기
                found_in_other = False
                for other_field, other_axis in axis_map.items():
                    if other_axis == axis:
                        continue
                    alt = _resolve_alias_code(raw, other_axis)
                    if alt:
                        result[other_field].append(alt)
                        result["alias_resolved"].append(
                            f"{raw} → {alt} (cross-axis: {axis}→{other_axis})"
                        )
                        found_in_other = True
                        break
                if not found_in_other:
                    result["unknown_codes"].append(f"{raw} ({axis})")

    # Tier 2: 문맥 조건부 alias (context_text에서 추가 코드 발견)
    if context_text:
        aliases = _load_aliases()
        text_lower = context_text.lower()
        for entry in aliases.get("tier2", []):
            term = entry["term"]
            if term not in text_lower:
                continue
            ctx_requires = entry.get("context_requires", [])
            if ctx_requires and not any(cr in text_lower for cr in ctx_requires):
                continue
            axis_name = entry["axis"]
            code = entry["code"]
            field = axis_name + "s" if axis_name != "work_context" else "work_contexts"
            if axis_name == "accident_type":
                field = "accident_types"
            elif axis_name == "hazardous_agent":
                field = "hazardous_agents"
            if code not in result.get(field, []):
                result[field].append(code)
                result["alias_resolved"].append(
                    f"tier2: '{term}' + context → {code} ({axis_name})"
                )

    # 중복 제거
    for field in ["accident_types", "hazardous_agents", "work_contexts"]:
        result[field] = list(dict.fromkeys(result[field]))

    if result["unknown_codes"]:
        logger.warning(f"[Normalizer] 매핑 불가 코드: {result['unknown_codes']}")
    if result["alias_resolved"]:
        logger.info(f"[Normalizer] Alias 해석: {result['alias_resolved']}")

    return result
