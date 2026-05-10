"""Guide domain profile matching for recommendation ranking.

The rules in this module are serving-time guards, not legal evidence.  They
keep domain-specific KOSHA Guides from outranking more relevant procedures when
the observed workplace context does not match the Guide's intended domain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
GUIDE_DOMAIN_PROFILES_PATH = DATA_DIR / "guide_domain_profiles.json"
BROAD_FEATURE_CODES = frozenset({
    "FALL",
    "SLIP",
    "COLLISION",
    "FALLING_OBJECT",
    "CRUSH",
    "CUT",
    "COLLAPSE",
    "ERGONOMIC",
    "BURN",
    "ELECTRIC_SHOCK",
    "EXPLOSION",
    "CHEMICAL_EXPOSURE",
    "MATERIAL_HANDLING",
    "MACHINE",
    "VEHICLE",
    "CHEMICAL",
    "FIRE",
    "ELECTRICITY",
    "ELECTRICAL_WORK",
})
REFERENCE_PROCEDURE_ROLES = frozenset({
    "measurement_analysis",
    "test_protocol",
    "health_screening",
    "risk_method",
    "document_reference",
    "management_program",
})


@dataclass(frozen=True)
class GuideDomainRule:
    family: str
    level: str
    guide_codes: frozenset[str] = frozenset()
    guide_terms: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()
    english_context_terms: tuple[str, ...] = ()
    industry_codes: frozenset[str] = frozenset()
    feature_codes: frozenset[str] = frozenset()
    mismatch_penalty: float = -0.18


@dataclass
class GuideDomainDecision:
    family: str | None = None
    level: str = "general"
    alignment: str = "general"
    score_adjustment: float = 0.0
    exclude: bool = False
    evidence: list[str] = field(default_factory=list)


GUIDE_DOMAIN_RULES = (
    GuideDomainRule(
        family="port_cargo",
        level="exclusive",
        guide_codes=frozenset({"A-G-18-2026"}),
        guide_terms=("항만하역", "항만 하역"),
        context_terms=(
            "항만", "부두", "선박", "본선", "선창", "선석", "안벽", "해상",
            "해치", "현문", "현문사다리", "갱웨이", "라싱", "컨테이너 크레인",
            "항만하역", "항만 하역", "부두운영", "선사", "화물선",
        ),
        english_context_terms=("port", "berth", "vessel", "cargo ship", "container ship", "gangway", "stevedoring"),
    ),
    GuideDomainRule(
        family="shipbuilding_dock",
        level="exclusive",
        guide_codes=frozenset({"G-116-2014", "B-5-2011"}),
        guide_terms=("선박건조", "선박 건조", "조선업", "도크 내 선박", "조선"),
        context_terms=("조선", "선박", "선박건조", "선박 건조", "선박 수리", "선대", "선박 블록"),
        english_context_terms=("shipyard", "shipbuilding", "dockyard", "vessel"),
    ),
    GuideDomainRule(
        family="food_facility",
        level="exclusive",
        guide_codes=frozenset({"A-G-10-2025"}),
        guide_terms=("급식실", "조리", "주방"),
        context_terms=("급식", "주방", "조리", "식당", "음식점", "튀김", "오븐", "가스레인지", "카페"),
        english_context_terms=("kitchen", "cafeteria", "restaurant"),
        industry_codes=frozenset({"FOOD_SERVICE", "CAFE_BEVERAGE"}),
        feature_codes=frozenset({"KITCHEN_COOKING", "FOOD_PREP", "DEEP_FRYING", "GAS_APPLIANCE"}),
    ),
    GuideDomainRule(
        family="eyewash_chemical",
        level="exclusive",
        guide_codes=frozenset({"C-C-16-2026"}),
        guide_terms=("세안설비", "세안 설비", "샤워설비"),
        context_terms=("세안", "비상샤워", "샤워", "안구", "화학", "산성", "강산", "염산", "알칼리", "부식성", "실험실", "유해물질"),
        english_context_terms=("eyewash", "emergency shower", "laboratory", "corrosive"),
        industry_codes=frozenset({"MANUFACTURING"}),
        feature_codes=frozenset({"CHEMICAL_WORK", "CHEMICAL_SPOTTING"}),
    ),
    GuideDomainRule(
        family="electrical_substation",
        level="exclusive",
        guide_codes=frozenset({"B-E-3-2025"}),
        guide_terms=("변전실", "수변전", "양압유지"),
        context_terms=("변전", "수변전", "전기실", "양압", "배전반", "개폐장치"),
        english_context_terms=("substation", "switchgear"),
        feature_codes=frozenset({"ELECTRICAL_WORK"}),
    ),
    GuideDomainRule(
        family="lightning_protection",
        level="exclusive",
        guide_codes=frozenset({"B-E-19-2026"}),
        guide_terms=("피뢰", "낙뢰"),
        context_terms=("피뢰", "낙뢰", "피뢰침", "수뢰부", "접지극", "건축물"),
        english_context_terms=("lightning", "lightning rod"),
    ),
    GuideDomainRule(
        family="toxic_gas_transfer",
        level="domain_specific",
        guide_codes=frozenset({"D-57-2016"}),
        guide_terms=("가스상 급성 독성물질", "독성물질의 하역", "출하시"),
        context_terms=("독성가스", "가스상 급성", "시안화수소", "염소", "암모니아", "탱크로리", "출하", "충전"),
        english_context_terms=("toxic gas", "hydrogen cyanide", "chlorine", "ammonia"),
        industry_codes=frozenset({"MANUFACTURING"}),
    ),
    GuideDomainRule(
        family="hazardous_atmosphere",
        level="domain_specific",
        guide_codes=frozenset({"B-E-21-2026", "B-E-20-2026"}),
        guide_terms=("방폭", "폭발위험", "정전도장"),
        context_terms=("방폭", "폭발위험", "인화성", "가연성", "유증기", "분진폭발", "도장", "스프레이", "용제"),
        english_context_terms=("explosive atmosphere", "flammable", "spray painting"),
        industry_codes=frozenset({"MANUFACTURING", "GAS_STATION", "DRY_CLEANING"}),
        feature_codes=frozenset({"FIRE_EXPLOSION", "STATIC_ELECTRICITY", "VAPOR_EXPOSURE"}),
    ),
    GuideDomainRule(
        family="crystalline_silica",
        level="domain_specific",
        guide_codes=frozenset({"H-110-2013"}),
        guide_terms=("유리규산", "결정형"),
        context_terms=("유리규산", "결정형", "실리카", "석영", "분진", "분쇄", "연마", "샌딩", "채석", "터널"),
        english_context_terms=("silica", "quartz"),
    ),
    GuideDomainRule(
        family="warehouse_logistics",
        level="domain_specific",
        guide_codes=frozenset({"H-221-2023", "B-M-11-2025"}),
        guide_terms=("물류센터", "지게차"),
        context_terms=("물류센터", "창고", "물류", "지게차", "팔레트", "랙", "상하차", "하역장", "적재", "보관"),
        english_context_terms=("warehouse", "forklift", "pallet"),
        industry_codes=frozenset({"WAREHOUSE_STORAGE", "DELIVERY_LOGISTICS", "RETAIL_CONVENIENCE", "MANUFACTURING"}),
        feature_codes=frozenset({"FORKLIFT_OPERATION", "PACKAGE_SORTING", "LOADING_DOCK", "STORAGE_SHELF", "MATERIAL_HANDLING", "BOX_HANDLING"}),
    ),
    GuideDomainRule(
        family="construction_equipment",
        level="domain_specific",
        guide_codes=frozenset({"D-C-10-2026", "B-M-9-2025", "B-M-8-2025"}),
        guide_terms=("이동식크레인", "건설장비", "타워크레인"),
        context_terms=("이동식크레인", "타워크레인", "항타기", "항발기", "건설장비", "양중", "크레인"),
        english_context_terms=("mobile crane", "tower crane"),
        industry_codes=frozenset({"CONSTRUCTION", "MANUFACTURING"}),
        feature_codes=frozenset({"CRANE", "CONSTRUCTION_EQUIP"}),
    ),
    GuideDomainRule(
        family="scaffold_fall",
        level="domain_specific",
        guide_codes=frozenset({"D-C-7-2026", "A-G-1-2025"}),
        guide_terms=("비계", "추락방호망", "추락 방호망"),
        context_terms=("비계", "추락방호망", "추락 방호망", "방호망", "고소작업", "추락"),
        english_context_terms=("scaffold", "fall protection"),
        industry_codes=frozenset({"CONSTRUCTION"}),
        feature_codes=frozenset({"SCAFFOLD", "FALL"}),
    ),
    GuideDomainRule(
        family="steel_stacking",
        level="domain_specific",
        guide_codes=frozenset({"B-M-32-2026"}),
        guide_terms=("철강제품", "철강 제품"),
        context_terms=("철강", "강재", "철근", "h형강", "코일", "적재"),
        english_context_terms=("steel", "coil"),
        industry_codes=frozenset({"MANUFACTURING", "WAREHOUSE_STORAGE", "CONSTRUCTION"}),
        feature_codes=frozenset({"STEELWORK", "MATERIAL_HANDLING"}),
    ),
)


def evaluate_guide_domain_profile(
    *,
    guide_code: str | None,
    title: str | None,
    profile_text: str | None,
    industry_contexts: Iterable[str] | None,
    risk_feature_codes: Iterable[str] | None,
    visual_cues: Iterable[str] | None,
    context_text: str | None,
) -> GuideDomainDecision:
    profile = _manual_profile(guide_code)
    rule = _match_rule(guide_code, title, profile_text)
    context_blob = _blob([*(visual_cues or []), context_text or ""])
    industries = set(industry_contexts or [])
    features = set(risk_feature_codes or [])

    if profile:
        manual_decision = _evaluate_manual_profile(profile, context_blob, industries, features)
        if manual_decision and manual_decision.alignment != "general":
            return manual_decision

    if rule:
        rule_decision = _evaluate_rule(rule, context_blob, industries, features)
        if rule_decision.exclude or rule_decision.alignment != "general":
            return rule_decision

    if profile and manual_decision:
        return manual_decision

    return GuideDomainDecision()


def _evaluate_rule(
    rule: GuideDomainRule,
    context_blob: str,
    industries: set[str],
    features: set[str],
) -> GuideDomainDecision:

    evidence: list[str] = []
    term_hit = _find_term_hit(context_blob, rule.context_terms, rule.english_context_terms)
    if term_hit:
        evidence.append(f"context_term:{term_hit}")
    industry_hit = sorted(industries & set(rule.industry_codes))
    if industry_hit:
        evidence.append(f"industry:{industry_hit[0]}")
    feature_hit = sorted((features & set(rule.feature_codes)) - BROAD_FEATURE_CODES)
    if feature_hit:
        evidence.append(f"feature:{feature_hit[0]}")

    if term_hit or feature_hit:
        return GuideDomainDecision(
            family=rule.family,
            level=rule.level,
            alignment="domain_match",
            score_adjustment=0.02 if rule.level == "domain_specific" else 0.0,
            evidence=evidence,
        )

    if rule.level == "exclusive":
        return GuideDomainDecision(
            family=rule.family,
            level=rule.level,
            alignment="domain_excluded",
            score_adjustment=-1.0,
            exclude=True,
            evidence=["exclusive_domain_mismatch"],
        )

    return GuideDomainDecision(
        family=rule.family,
        level=rule.level,
        alignment="domain_mismatch",
        score_adjustment=rule.mismatch_penalty,
        exclude=False,
        evidence=["domain_specific_mismatch"],
    )


@lru_cache(maxsize=1)
def _load_manual_profiles() -> dict[str, dict]:
    if not GUIDE_DOMAIN_PROFILES_PATH.exists():
        return {}
    try:
        data = json.loads(GUIDE_DOMAIN_PROFILES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    profiles = data.get("profiles")
    return profiles if isinstance(profiles, dict) else {}


def get_guide_domain_profile(guide_code: str | None) -> dict | None:
    return _manual_profile(guide_code)


def _manual_profile(guide_code: str | None) -> dict | None:
    if not guide_code:
        return None
    profile = _load_manual_profiles().get(guide_code)
    return profile if isinstance(profile, dict) else None


def _evaluate_manual_profile(
    profile: dict,
    context_blob: str,
    industries: set[str],
    features: set[str],
) -> GuideDomainDecision | None:
    level = str(profile.get("profile_level") or "general")
    family = profile.get("domain_family")
    procedure_role = str(profile.get("procedure_role") or "field_control")
    if level == "general":
        return GuideDomainDecision(
            family=family,
            level="general",
            alignment="general",
        )

    confidence = _to_float(profile.get("confidence"), default=0.0)
    feature_codes = set(profile.get("feature_codes") or [])
    visual_triggers = list(profile.get("visual_triggers") or [])
    required_terms = list(profile.get("required_context_terms") or [])
    include_terms = list((profile.get("recommendation_boundary") or {}).get("include_when") or [])
    industry_terms = list(profile.get("industry_alignment") or [])
    observable_terms = list(profile.get("observable_required_cues") or [])
    workplace_terms = list(profile.get("intended_workplaces") or [])
    task_terms = list(profile.get("intended_tasks") or [])
    negative_terms = [
        *list(profile.get("negative_context_terms") or []),
        *list((profile.get("recommendation_boundary") or {}).get("exclude_when") or []),
        *list(profile.get("negative_boundaries") or []),
    ]

    manual_terms = _unique_terms([
        *required_terms,
        *include_terms,
        *visual_triggers,
        *industry_terms,
        *observable_terms,
        *workplace_terms,
        *task_terms,
    ])
    korean_terms, english_terms = _split_manual_terms(manual_terms)
    negative_korean_terms, negative_english_terms = _split_manual_terms(_unique_terms(negative_terms))

    evidence: list[str] = []
    negative_hit = _find_term_hit(context_blob, negative_korean_terms, negative_english_terms)
    if negative_hit:
        if level == "exclusive" or procedure_role in REFERENCE_PROCEDURE_ROLES:
            return GuideDomainDecision(
                family=family,
                level=level,
                alignment="domain_excluded",
                score_adjustment=-1.0,
                exclude=True,
                evidence=[f"manual_negative_boundary:{negative_hit}"],
            )
        evidence.append(f"manual_negative_boundary:{negative_hit}")

    term_hit = _find_term_hit(context_blob, korean_terms, english_terms)
    if term_hit:
        evidence.append(f"manual_context_term:{term_hit}")

    industry_hit = _find_term_hit(_blob([*industries, context_blob]), industry_terms, ())
    if industry_hit:
        evidence.append(f"manual_industry:{industry_hit}")

    feature_hit = sorted(features & feature_codes)
    non_generic_feature_hit = [code for code in feature_hit if code not in BROAD_FEATURE_CODES and code not in {"GENERAL_WORKPLACE", "CHEMICAL_EXPOSURE", "CHEMICAL_WORK", "FIRE_EXPLOSION", "ELECTRICAL_WORK", "ERGONOMIC", "VENTILATION_POOR"}]
    if non_generic_feature_hit:
        evidence.append(f"manual_feature:{non_generic_feature_hit[0]}")

    if (
        (term_hit or non_generic_feature_hit)
        and not all(item.startswith("manual_negative_boundary:") for item in evidence)
    ):
        if level == "exclusive" and not term_hit:
            return GuideDomainDecision(
                family=family,
                level=level,
                alignment="domain_excluded",
                score_adjustment=-1.0,
                exclude=True,
                evidence=["manual_exclusive_context_mismatch", *evidence],
            )
        adjustment = 0.03 if level == "domain_specific" else 0.04
        if procedure_role in REFERENCE_PROCEDURE_ROLES and not (term_hit or industry_hit):
            adjustment = min(adjustment, 0.01)
        return GuideDomainDecision(
            family=family,
            level=level,
            alignment="domain_match",
            score_adjustment=adjustment,
            evidence=evidence,
        )

    if procedure_role in REFERENCE_PROCEDURE_ROLES:
        if level == "exclusive" and confidence >= 0.70:
            return GuideDomainDecision(
                family=family,
                level=level,
                alignment="domain_excluded",
                score_adjustment=-1.0,
                exclude=True,
                evidence=[f"manual_reference_role_mismatch:{procedure_role}"],
            )
        return GuideDomainDecision(
            family=family,
            level=level,
            alignment="domain_mismatch",
            score_adjustment=-0.24,
            exclude=False,
            evidence=[f"manual_reference_role_mismatch:{procedure_role}"],
        )

    if level == "exclusive" and confidence >= 0.78:
        return GuideDomainDecision(
            family=family,
            level=level,
            alignment="domain_excluded",
            score_adjustment=-1.0,
            exclude=True,
            evidence=["manual_exclusive_domain_mismatch"],
        )

    if level in {"exclusive", "domain_specific"}:
        return GuideDomainDecision(
            family=family,
            level=level,
            alignment="domain_mismatch",
            score_adjustment=-0.18 if level == "exclusive" else -0.12,
            exclude=False,
            evidence=["manual_domain_specific_mismatch"],
        )

    return GuideDomainDecision(
        family=family,
        level=level,
        alignment="general",
    )

def _match_rule(guide_code: str | None, title: str | None, profile_text: str | None) -> GuideDomainRule | None:
    guide_text = _blob([title or "", profile_text or ""])
    for rule in GUIDE_DOMAIN_RULES:
        if guide_code and guide_code in rule.guide_codes:
            return rule
        if _find_term_hit(guide_text, rule.guide_terms, ()):
            return rule
    return None


def _blob(values: Iterable[str]) -> str:
    return " ".join(value for value in values if value).lower()


def _find_term_hit(text: str, terms: Iterable[str], english_terms: Iterable[str]) -> str | None:
    for term in terms:
        lowered = term.lower()
        if lowered and lowered in text:
            return term
    for term in english_terms:
        lowered = term.lower()
        if lowered and re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", text):
            return term
    return None


def _split_manual_terms(terms: Iterable[str]) -> tuple[list[str], list[str]]:
    korean_terms: list[str] = []
    english_terms: list[str] = []
    for term in terms:
        if not term:
            continue
        if _is_english_like(term):
            english_terms.append(term)
        else:
            korean_terms.append(term)
    return korean_terms, english_terms


def _is_english_like(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return bool(letters) and all(ord(char) < 128 for char in letters)


def _unique_terms(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
