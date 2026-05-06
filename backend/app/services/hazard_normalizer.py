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

TEXT_WORK_CONTEXT_HINTS = {
    "ELECTRICAL_WORK": [
        "분전반", "차단기", "활선", "충전부", "접지", "누전", "전기 작업",
        "전선", "케이블", "멀티탭",
    ],
    "LADDER": ["사다리", "발판", "3점 지지", "최상부"],
    "CHEMICAL_WORK": [
        "화학", "MSDS", "드럼", "용제", "분말", "유기용제", "화학물질",
    ],
    "WELDING": ["용접", "아크", "차광", "용접 흄", "흄"],
    "LIFT_WORK": ["리프트", "차량 하부", "잭 스탠드", "고정 핀", "하부 작업"],
    "OIL_DRAIN": ["폐오일", "오일팬", "오일 팬", "오일 드레인", "엔진오일"],
    "TIRE_CHANGE": ["타이어", "공기압", "에어 임팩트", "임팩트 렌치", "고압 에어"],
    "WELDING_REPAIR": ["차체 용접", "연료 탱크", "용접 수리", "용접 불꽃"],
    "EV_BATTERY": ["전기차", "고전압 배터리", "배터리 커버", "절연 장갑"],
    "HAIR_CHEMICAL": ["파마약", "염색약", "미용 약품", "헤어 화학"],
    "NAIL_CHEMICAL": ["네일", "아세톤", "리무버", "젤 네일", "알코올 램프"],
    "HOT_TOOL": ["고데기", "드라이어", "열기구", "고온 도구", "미용기구"],
    "SKIN_DEVICE": ["피부 장비", "레이저", "자외선", "광선 장비", "피부관리"],
    "HAIR_WASH": ["샴푸", "세정", "머리 감기", "샴푸대", "온수"],
    "SHELF_STOCKING": ["진열대", "선반", "상품 진열", "매대", "상부 선반"],
    "NIGHT_SOLO": ["야간", "단독 근무", "심야", "혼자 근무"],
    "COLD_DISPLAY": ["냉장 진열대", "냉동 진열대", "쇼케이스", "냉장고"],
    "BOX_HANDLING": ["박스", "상자", "적재", "운반", "물류 박스"],
    "CASHIER_AREA": ["계산대", "카운터", "전선", "멀티탭", "고객 통로"],
    "SAWING": ["톱", "절단기", "원형톱", "목재 절단", "테이블쏘"],
    "SANDING": ["샌딩", "연마", "분진", "샌더", "목분"],
    "PAINTING_WOODWORK": ["도장", "페인트", "스테인", "희석제", "목공 도장"],
    "LADDER_INTERIOR": ["실내 사다리", "인테리어 사다리", "천장 작업", "벽면 작업"],
    "NAIL_GUN": ["타카", "네일건", "공압 공구", "못 박기", "에어 타카"],
}

TEXT_WORK_CONTEXT_HINTS.update({
    "DRY_CLEANING_SOLVENT": ["드라이클리닝", "PERC", "퍼클로로에틸렌", "세탁 용제"],
    "PRESS_MACHINE": ["프레스", "프레스 기계"],
    "WASHING_MACHINE": ["세탁기"],
    "STEAM_IRON": ["스팀 다리미", "다리미"],
    "CHEMICAL_SPOTTING": ["얼룩 제거", "스팟팅"],
    "GARMENT_SORTING": ["세탁물 분류", "의류 분류"],
    "HIGH_PRESSURE_WASH": ["고압 세척", "고압 세척기"],
    "CHEMICAL_APPLICATION": ["세차 화학약품", "화학 약품 도포"],
    "WAX_POLISHING": ["왁스", "광택"],
    "CONVEYOR_WASH": ["컨베이어 세차"],
    "INTERIOR_CLEANING": ["차량 내부 청소", "실내 청소"],
    "WET_FLOOR_WORK": ["젖은 바닥", "습윤 바닥"],
    "DOG_GROOMING": ["강아지 미용", "애견 미용"],
    "CAT_HANDLING": ["고양이 취급", "고양이 핸들링"],
    "PET_BATHING": ["반려동물 목욕", "펫 목욕"],
    "DRYER_OPERATION": ["건조기", "드라이어"],
    "CAGE_CLEANING": ["케이지 청소"],
    "ANIMAL_FEEDING": ["동물 급식", "사료 급여"],
    "FORKLIFT_OPERATION": ["지게차 작업", "지게차"],
    "HEAVY_LIFTING": ["중량물", "과하중"],
    "HIGH_SHELF_WORK": ["높은 선반", "고소 선반"],
    "LOADING_DOCK": ["하역 도크", "도크"],
    "PACKAGE_SORTING": ["택배 분류", "소포 분류"],
    "CONVEYOR_BELT": ["컨베이어 벨트"],
    "PESTICIDE_SPRAY": ["농약 살포", "살충제 살포"],
    "FARM_MACHINERY": ["농기계", "트랙터", "관리기"],
    "GREENHOUSE_WORK": ["온실", "비닐하우스"],
    "HARVEST_WORK": ["수확", "농경지"],
    "IRRIGATION": ["관개", "수로"],
    "FERTILIZER_HANDLING": ["비료 취급", "비료"],
    "ELECTRICAL_OVERLOAD": ["전기 과부하", "멀티탭 과부하"],
    "FIRE_EVACUATION": ["비상구", "화재 대피", "유도등"],
    "VENTILATION_POOR": ["환기 불량", "밀폐 환기"],
    "CLEANING_NIGHT": ["야간 청소"],
    "CROWD_MANAGEMENT": ["과밀", "밀집 인원"],
    "NOISE_EXPOSURE": ["소음 노출", "고소음"],
    "FUEL_DISPENSING": ["주유", "주유기"],
    "STATIC_ELECTRICITY": ["정전기"],
    "FUEL_SPILL": ["연료 유출", "휘발유 유출"],
    "UNDERGROUND_TANK": ["지하 탱크", "탱크 맨홀"],
    "VAPOR_EXPOSURE": ["유증기", "연료 증기"],
    "NIGHT_SOLO_WORK": ["야간 단독", "심야 단독"],
})


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

    if context_text:
        for code, terms in TEXT_WORK_CONTEXT_HINTS.items():
            if code in result["work_contexts"]:
                continue
            if any(term.lower() in text_lower or term in context_text for term in terms):
                result["work_contexts"].append(code)
                result["alias_resolved"].append(
                    f"text-context: {code} (work_context)"
                )
        if len(result["work_contexts"]) > 1 and "GENERAL_WORKPLACE" in result["work_contexts"]:
            result["work_contexts"] = [
                code for code in result["work_contexts"] if code != "GENERAL_WORKPLACE"
            ]

    if result["unknown_codes"]:
        logger.warning(f"[Normalizer] 매핑 불가 코드: {result['unknown_codes']}")
    if result["alias_resolved"]:
        logger.info(f"[Normalizer] Alias 해석: {result['alias_resolved']}")

    return result
