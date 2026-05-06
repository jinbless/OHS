"""Industry-context inference and matching helpers.

Industry should not be a mandatory first-step question.  The service infers it
from the observed work context/text, lets a declared value override it, and
exposes ambiguity so the UI can ask only when it matters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


INDUSTRY_LABELS = {
    "FOOD_SERVICE": "음식점/주방",
    "CAFE_BEVERAGE": "카페/음료",
    "RETAIL_CONVENIENCE": "소매/편의점",
    "DELIVERY_LOGISTICS": "배달/운송",
    "WAREHOUSE_STORAGE": "창고/보관",
    "CONSTRUCTION": "건설업",
    "MANUFACTURING": "제조업",
    "AUTO_REPAIR": "자동차 정비",
    "BEAUTY_SERVICE": "미용업",
    "WOODWORK_INTERIOR": "목공/인테리어",
    "DRY_CLEANING": "세탁/드라이클리닝",
    "CAR_WASH": "세차장",
    "PET_SERVICE": "반려동물 미용/펫샵",
    "AGRICULTURE_HORTICULTURE": "농업/원예/화훼",
    "ENTERTAINMENT_PC_KARAOKE": "PC방/노래방",
    "GAS_STATION": "주유소",
    "GENERAL": "일반 사업장",
}

WORK_CONTEXT_INDUSTRY_HINTS = {
    "KITCHEN_COOKING": ["FOOD_SERVICE"],
    "FOOD_PREP": ["FOOD_SERVICE"],
    "DEEP_FRYING": ["FOOD_SERVICE"],
    "GAS_APPLIANCE": ["FOOD_SERVICE"],
    "HOT_BEVERAGE": ["CAFE_BEVERAGE", "FOOD_SERVICE"],
    "CLEANING_WET": ["FOOD_SERVICE", "CAFE_BEVERAGE", "RETAIL_CONVENIENCE"],
    "COLD_STORAGE": ["FOOD_SERVICE", "WAREHOUSE_STORAGE", "RETAIL_CONVENIENCE"],
    "SERVING_FLOOR": ["FOOD_SERVICE", "CAFE_BEVERAGE", "RETAIL_CONVENIENCE"],
    "DELIVERY_RIDER": ["DELIVERY_LOGISTICS"],
    "STORAGE_SHELF": ["WAREHOUSE_STORAGE", "RETAIL_CONVENIENCE"],
    "SCAFFOLD": ["CONSTRUCTION"],
    "EXCAVATION": ["CONSTRUCTION"],
    "CRANE": ["CONSTRUCTION", "MANUFACTURING"],
    "CONSTRUCTION_EQUIP": ["CONSTRUCTION"],
    "DEMOLITION": ["CONSTRUCTION"],
    "ELECTRICAL_WORK": ["CONSTRUCTION", "MANUFACTURING"],
    "CHEMICAL_WORK": ["MANUFACTURING"],
    "WELDING": ["CONSTRUCTION", "MANUFACTURING"],
    "LADDER": ["CONSTRUCTION", "GENERAL"],
    "ROPE_ACCESS": ["CONSTRUCTION"],
    "PAINTING": ["CONSTRUCTION", "MANUFACTURING", "GENERAL"],
    "MACHINE": ["MANUFACTURING"],
    "CONVEYOR": ["MANUFACTURING"],
    "ROBOT": ["MANUFACTURING"],
    "PRESSURE_VESSEL": ["MANUFACTURING"],
    "STEELWORK": ["MANUFACTURING"],
    "MATERIAL_HANDLING": ["WAREHOUSE_STORAGE", "MANUFACTURING"],
    "VEHICLE": ["DELIVERY_LOGISTICS", "CONSTRUCTION", "GENERAL"],
    "LIFT_WORK": ["AUTO_REPAIR"],
    "OIL_DRAIN": ["AUTO_REPAIR"],
    "TIRE_CHANGE": ["AUTO_REPAIR"],
    "WELDING_REPAIR": ["AUTO_REPAIR", "MANUFACTURING"],
    "EV_BATTERY": ["AUTO_REPAIR", "MANUFACTURING"],
    "HAIR_CHEMICAL": ["BEAUTY_SERVICE"],
    "NAIL_CHEMICAL": ["BEAUTY_SERVICE"],
    "HOT_TOOL": ["BEAUTY_SERVICE"],
    "SKIN_DEVICE": ["BEAUTY_SERVICE"],
    "HAIR_WASH": ["BEAUTY_SERVICE"],
    "SHELF_STOCKING": ["RETAIL_CONVENIENCE", "WAREHOUSE_STORAGE"],
    "NIGHT_SOLO": ["RETAIL_CONVENIENCE"],
    "COLD_DISPLAY": ["RETAIL_CONVENIENCE", "FOOD_SERVICE"],
    "BOX_HANDLING": ["RETAIL_CONVENIENCE", "WAREHOUSE_STORAGE"],
    "CASHIER_AREA": ["RETAIL_CONVENIENCE"],
    "SAWING": ["WOODWORK_INTERIOR", "MANUFACTURING"],
    "SANDING": ["WOODWORK_INTERIOR", "MANUFACTURING"],
    "PAINTING_WOODWORK": ["WOODWORK_INTERIOR", "CONSTRUCTION"],
    "LADDER_INTERIOR": ["WOODWORK_INTERIOR", "CONSTRUCTION", "GENERAL"],
    "NAIL_GUN": ["WOODWORK_INTERIOR", "CONSTRUCTION"],
    "DRY_CLEANING_SOLVENT": ["DRY_CLEANING"],
    "PRESS_MACHINE": ["DRY_CLEANING", "MANUFACTURING"],
    "WASHING_MACHINE": ["DRY_CLEANING"],
    "STEAM_IRON": ["DRY_CLEANING"],
    "CHEMICAL_SPOTTING": ["DRY_CLEANING"],
    "GARMENT_SORTING": ["DRY_CLEANING"],
    "HIGH_PRESSURE_WASH": ["CAR_WASH"],
    "CHEMICAL_APPLICATION": ["CAR_WASH"],
    "WAX_POLISHING": ["CAR_WASH"],
    "CONVEYOR_WASH": ["CAR_WASH"],
    "INTERIOR_CLEANING": ["CAR_WASH"],
    "WET_FLOOR_WORK": ["CAR_WASH", "FOOD_SERVICE", "GENERAL"],
    "DOG_GROOMING": ["PET_SERVICE"],
    "CAT_HANDLING": ["PET_SERVICE"],
    "PET_BATHING": ["PET_SERVICE"],
    "DRYER_OPERATION": ["PET_SERVICE", "DRY_CLEANING"],
    "CAGE_CLEANING": ["PET_SERVICE"],
    "ANIMAL_FEEDING": ["PET_SERVICE"],
    "FORKLIFT_OPERATION": ["WAREHOUSE_STORAGE"],
    "HEAVY_LIFTING": ["WAREHOUSE_STORAGE"],
    "HIGH_SHELF_WORK": ["WAREHOUSE_STORAGE", "RETAIL_CONVENIENCE"],
    "LOADING_DOCK": ["WAREHOUSE_STORAGE", "DELIVERY_LOGISTICS"],
    "PACKAGE_SORTING": ["WAREHOUSE_STORAGE", "DELIVERY_LOGISTICS"],
    "CONVEYOR_BELT": ["WAREHOUSE_STORAGE", "MANUFACTURING"],
    "PESTICIDE_SPRAY": ["AGRICULTURE_HORTICULTURE"],
    "FARM_MACHINERY": ["AGRICULTURE_HORTICULTURE"],
    "GREENHOUSE_WORK": ["AGRICULTURE_HORTICULTURE"],
    "HARVEST_WORK": ["AGRICULTURE_HORTICULTURE"],
    "IRRIGATION": ["AGRICULTURE_HORTICULTURE"],
    "FERTILIZER_HANDLING": ["AGRICULTURE_HORTICULTURE"],
    "ELECTRICAL_OVERLOAD": ["ENTERTAINMENT_PC_KARAOKE", "GENERAL"],
    "FIRE_EVACUATION": ["ENTERTAINMENT_PC_KARAOKE", "GENERAL"],
    "VENTILATION_POOR": ["ENTERTAINMENT_PC_KARAOKE", "DRY_CLEANING", "GENERAL"],
    "CLEANING_NIGHT": ["ENTERTAINMENT_PC_KARAOKE", "GAS_STATION", "GENERAL"],
    "CROWD_MANAGEMENT": ["ENTERTAINMENT_PC_KARAOKE"],
    "NOISE_EXPOSURE": ["ENTERTAINMENT_PC_KARAOKE", "MANUFACTURING"],
    "FUEL_DISPENSING": ["GAS_STATION"],
    "STATIC_ELECTRICITY": ["GAS_STATION"],
    "FUEL_SPILL": ["GAS_STATION"],
    "UNDERGROUND_TANK": ["GAS_STATION"],
    "VAPOR_EXPOSURE": ["GAS_STATION"],
    "NIGHT_SOLO_WORK": ["GAS_STATION", "RETAIL_CONVENIENCE"],
    "GENERAL_WORKPLACE": ["GENERAL"],
}

DECLARED_ALIASES = {
    "음식점": "FOOD_SERVICE",
    "외식": "FOOD_SERVICE",
    "식당": "FOOD_SERVICE",
    "주방": "FOOD_SERVICE",
    "조리": "FOOD_SERVICE",
    "food": "FOOD_SERVICE",
    "restaurant": "FOOD_SERVICE",
    "kitchen": "FOOD_SERVICE",
    "카페": "CAFE_BEVERAGE",
    "커피": "CAFE_BEVERAGE",
    "음료": "CAFE_BEVERAGE",
    "cafe": "CAFE_BEVERAGE",
    "coffee": "CAFE_BEVERAGE",
    "편의점": "RETAIL_CONVENIENCE",
    "소매": "RETAIL_CONVENIENCE",
    "매장": "RETAIL_CONVENIENCE",
    "retail": "RETAIL_CONVENIENCE",
    "convenience": "RETAIL_CONVENIENCE",
    "배달": "DELIVERY_LOGISTICS",
    "운송": "DELIVERY_LOGISTICS",
    "이륜": "DELIVERY_LOGISTICS",
    "오토바이": "DELIVERY_LOGISTICS",
    "delivery": "DELIVERY_LOGISTICS",
    "logistics": "DELIVERY_LOGISTICS",
    "창고": "WAREHOUSE_STORAGE",
    "보관": "WAREHOUSE_STORAGE",
    "적재": "WAREHOUSE_STORAGE",
    "warehouse": "WAREHOUSE_STORAGE",
    "storage": "WAREHOUSE_STORAGE",
    "건설": "CONSTRUCTION",
    "공사": "CONSTRUCTION",
    "비계": "CONSTRUCTION",
    "construction": "CONSTRUCTION",
    "제조": "MANUFACTURING",
    "공장": "MANUFACTURING",
    "기계": "MANUFACTURING",
    "manufacturing": "MANUFACTURING",
    "factory": "MANUFACTURING",
    "자동차": "AUTO_REPAIR",
    "정비소": "AUTO_REPAIR",
    "자동차정비": "AUTO_REPAIR",
    "카센터": "AUTO_REPAIR",
    "auto repair": "AUTO_REPAIR",
    "garage": "AUTO_REPAIR",
    "미용": "BEAUTY_SERVICE",
    "미용업": "BEAUTY_SERVICE",
    "헤어": "BEAUTY_SERVICE",
    "네일": "BEAUTY_SERVICE",
    "beauty": "BEAUTY_SERVICE",
    "salon": "BEAUTY_SERVICE",
    "목공": "WOODWORK_INTERIOR",
    "인테리어": "WOODWORK_INTERIOR",
    "실내공사": "WOODWORK_INTERIOR",
    "woodwork": "WOODWORK_INTERIOR",
    "interior": "WOODWORK_INTERIOR",
    "세탁": "DRY_CLEANING",
    "드라이클리닝": "DRY_CLEANING",
    "dry cleaning": "DRY_CLEANING",
    "세차": "CAR_WASH",
    "car wash": "CAR_WASH",
    "반려동물": "PET_SERVICE",
    "펫샵": "PET_SERVICE",
    "동물미용": "PET_SERVICE",
    "pet": "PET_SERVICE",
    "농업": "AGRICULTURE_HORTICULTURE",
    "원예": "AGRICULTURE_HORTICULTURE",
    "화훼": "AGRICULTURE_HORTICULTURE",
    "농경": "AGRICULTURE_HORTICULTURE",
    "agriculture": "AGRICULTURE_HORTICULTURE",
    "PC방": "ENTERTAINMENT_PC_KARAOKE",
    "피시방": "ENTERTAINMENT_PC_KARAOKE",
    "노래방": "ENTERTAINMENT_PC_KARAOKE",
    "karaoke": "ENTERTAINMENT_PC_KARAOKE",
    "주유소": "GAS_STATION",
    "gas station": "GAS_STATION",
    "일반": "GENERAL",
    "general": "GENERAL",
}

TEXT_KEYWORD_HINTS = {
    "FOOD_SERVICE": ["주방", "조리", "식당", "음식점", "튀김", "가스레인지", "오븐"],
    "CAFE_BEVERAGE": ["카페", "커피", "음료", "스팀", "에스프레소", "뜨거운 음료"],
    "RETAIL_CONVENIENCE": ["편의점", "매장", "진열대", "계산대", "고객 통로"],
    "DELIVERY_LOGISTICS": ["배달", "오토바이", "이륜차", "라이더", "도로", "배송"],
    "WAREHOUSE_STORAGE": ["창고", "적재", "보관", "랙", "선반", "팔레트"],
    "CONSTRUCTION": ["건설", "공사", "비계", "굴착", "철골", "해체", "고소작업"],
    "MANUFACTURING": ["제조", "공장", "기계", "컨베이어", "프레스", "로봇", "설비"],
    "AUTO_REPAIR": [
        "자동차", "정비소", "카센터", "리프트", "타이어", "오일", "차량 하부",
        "전기차", "고전압 배터리", "정비사",
    ],
    "BEAUTY_SERVICE": [
        "미용", "미용실", "헤어", "파마약", "염색약", "네일", "아세톤",
        "고데기", "샴푸", "피부 장비",
    ],
    "WOODWORK_INTERIOR": [
        "목공", "인테리어", "톱", "샌딩", "목재", "도장", "타카", "네일건",
        "실내 사다리",
    ],
    "DRY_CLEANING": [
        "세탁", "드라이클리닝", "PERC", "퍼클로로에틸렌", "스팀 다리미",
        "얼룩 제거", "세탁물", "건조기",
    ],
    "CAR_WASH": [
        "세차", "고압 세척", "왁스", "광택", "세차장", "차체", "세차 컨베이어",
    ],
    "PET_SERVICE": [
        "반려동물", "펫샵", "애견", "고양이", "동물 미용", "드라이어",
        "케이지", "목욕",
    ],
    "AGRICULTURE_HORTICULTURE": [
        "농약", "비료", "온실", "하우스", "농기계", "수확", "관개", "농경지",
        "화훼", "원예",
    ],
    "ENTERTAINMENT_PC_KARAOKE": [
        "PC방", "피시방", "노래방", "룸", "서버실", "비상구", "유도등",
        "방음", "고객 과밀",
    ],
    "GAS_STATION": [
        "주유소", "주유기", "휘발유", "연료", "지하 탱크", "유증기",
        "정전기", "캐노피",
    ],
}


@dataclass
class IndustryContext:
    declared_industries: list[str] = field(default_factory=list)
    inferred_industries: list[str] = field(default_factory=list)
    primary_industry: str | None = None
    confidence: float = 0.0
    needs_confirmation: bool = False
    confirmation_question: str | None = None
    evidence: list[str] = field(default_factory=list)

    @property
    def active_industries(self) -> list[str]:
        values = self.declared_industries or self.inferred_industries
        return list(dict.fromkeys(values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_industries": self.declared_industries,
            "inferred_industries": self.inferred_industries,
            "primary_industry": self.primary_industry,
            "primary_label": INDUSTRY_LABELS.get(self.primary_industry or ""),
            "confidence": self.confidence,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_question": self.confirmation_question,
            "evidence": self.evidence,
        }


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def normalize_industry_context(value: str | None) -> list[str]:
    if not value:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    upper = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_").upper()
    if upper in INDUSTRY_LABELS:
        return [upper]

    raw_lower = raw.lower()
    hits = []
    for term, code in DECLARED_ALIASES.items():
        if term.lower() in raw_lower or term in raw:
            hits.append(code)
    return _dedupe(hits)


def industry_hints_for_work_contexts(work_contexts: list[str] | None) -> list[str]:
    hints: list[str] = []
    for context in work_contexts or []:
        hints.extend(WORK_CONTEXT_INDUSTRY_HINTS.get(context, []))
    return _dedupe(hints)


def industry_hints_for_features(features: dict[str, Any] | None) -> list[str]:
    if not features:
        return []
    context = features.get("work_context")
    contexts = [context] if isinstance(context, str) and context else []
    return industry_hints_for_work_contexts(contexts)


def infer_industry_context(
    *,
    work_contexts: list[str] | None = None,
    text: str = "",
    declared: str | None = None,
) -> IndustryContext:
    declared_industries = normalize_industry_context(declared)
    scores: dict[str, float] = {}
    evidence: list[str] = []

    for industry in industry_hints_for_work_contexts(work_contexts):
        scores[industry] = scores.get(industry, 0.0) + 1.0
        evidence.append(f"work_context->{industry}")

    lower_text = (text or "").lower()
    for industry, terms in TEXT_KEYWORD_HINTS.items():
        for term in terms:
            if term.lower() in lower_text or term in text:
                scores[industry] = scores.get(industry, 0.0) + 0.5
                evidence.append(f"text:{term}->{industry}")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    inferred = [industry for industry, _ in ranked]
    primary = None
    confidence = 0.0
    needs_confirmation = False

    if declared_industries:
        primary = declared_industries[0]
        confidence = 0.95
        if inferred and primary not in inferred[:3]:
            needs_confirmation = True
    elif ranked:
        primary, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = min(0.9, 0.45 + top_score * 0.15)
        if len(ranked) > 1 and top_score - second_score < 0.35:
            needs_confirmation = True
    else:
        primary = None
        confidence = 0.0

    question = None
    if needs_confirmation:
        choices = declared_industries or inferred[:3]
        labels = [
            INDUSTRY_LABELS.get(code, code)
            for code in choices
        ]
        if labels:
            question = f"사진 상황이 {' / '.join(labels)} 중 어디에 더 가까운지 확인이 필요합니다."

    return IndustryContext(
        declared_industries=declared_industries,
        inferred_industries=inferred,
        primary_industry=primary,
        confidence=round(confidence, 2),
        needs_confirmation=needs_confirmation,
        confirmation_question=question,
        evidence=_dedupe(evidence)[:8],
    )


def score_industry_alignment(
    candidate_hints: list[str] | None,
    active_industries: list[str] | None,
) -> tuple[float, str, list[str]]:
    """Return a small ranking adjustment and explanation.

    Industry is a prioritization signal, not a hard validation rule.
    """
    hints = set(candidate_hints or [])
    active = set(active_industries or [])
    if not hints or not active:
        return 0.0, "unknown", []
    overlap = sorted(hints & active)
    if overlap:
        return 0.06, "match", [f"industry_match:{code}" for code in overlap]
    if "GENERAL" in hints or "GENERAL" in active:
        return 0.01, "general", []
    return -0.04, "mismatch", [
        f"candidate={','.join(sorted(hints))}",
        f"context={','.join(sorted(active))}",
    ]
