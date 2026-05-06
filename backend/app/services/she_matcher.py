"""Phase 3 Layer 0 — SHE Router (PG-based).

목적:
  GPT description + facets → 매칭되는 active SHE top-N (각 SHE의 8 dim feature
  와 description의 facets가 ≥2 dim 일치). 매칭된 SHE → appliesSR/appliesCI/
  source_guide 자동 follow.

배치 (analysis_service.py L107 직후):
  GPT result → [Layer 0: SHE matcher] → 매칭 SHE list → Layer 1~4가 후보 좁힘

Why PG (not Fuseki)?
  - v2 Fuseki Java는 read-only — SPARQL UPDATE 차단 (Phase 4에서 rebuild 예정)
  - PG she_catalog (645 SHE, JSONB GIN) 이미 적재 + JSONB feature 매칭 ~10ms
  - sr-registry CI/Guide 자동 follow는 PG she_sr_mapping/she_ci_mapping 활용

Feature flag (사용자 비판 #12):
  OHS_ENABLE_SHE=false (default) → Layer 0 skip, 기존 4-layer 유지
  OHS_ENABLE_SHE=true            → Layer 0 active

Future (Phase 3 Track 4):
  GPT DUAL_TRACK_SCHEMA에 situational_features 8축 추가 (사용자 비판 #11)
  → 현재는 Track B 3축 (accident_types, hazardous_agents, work_contexts)으로 매칭
"""
from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.services.industry_context import (
    industry_hints_for_features,
    score_industry_alignment,
)

logger = logging.getLogger(__name__)


UNSAFE_PPE_STATES = {
    "HELMET_MISSING",
    "HARNESS_MISSING",
    "HARNESS_UNTIED",
    "GLOVES_MISSING",
    "MASK_MISSING",
    "GOGGLES_MISSING",
    "SAFETY_SHOES_MISSING",
    "VEST_MISSING",
}

UNSAFE_ENVIRONMENTAL_STATES = {
    "WET_SURFACE",
    "OIL_CONTAMINATION",
    "LOW_LIGHT",
    "CLUTTERED",
    "WINDY_WEATHER",
    "EXTREME_TEMPERATURE",
    "NARROW_SPACE",
    "UNSTABLE_GROUND",
}

NORMAL_PPE_STATES = {
    "HELMET_WORN",
    "HARNESS_WORN",
    "HARNESS_TIED",
    "GLOVE_WORN",
    "MASK_WORN",
    "GOGGLES_WORN",
    "VEST_WORN",
    "SAFETY_SHOES_WORN",
}

HIGH_RISK_AGENT_CONTEXTS = {
    "CHEMICAL_WORK",
    "ELECTRICAL_WORK",
    "GRINDING",
    "MACHINE",
    "WELDING",
    "KITCHEN_COOKING",
    "DEEP_FRYING",
    "GAS_APPLIANCE",
    "HOT_BEVERAGE",
    "COLD_STORAGE",
    "SERVING_FLOOR",
    "STORAGE_SHELF",
    "DRY_CLEANING_SOLVENT",
    "CHEMICAL_SPOTTING",
    "GARMENT_SORTING",
    "CHEMICAL_APPLICATION",
    "INTERIOR_CLEANING",
    "CAGE_CLEANING",
    "ANIMAL_FEEDING",
    "PACKAGE_SORTING",
    "PESTICIDE_SPRAY",
    "FERTILIZER_HANDLING",
    "GREENHOUSE_WORK",
    "HAIR_CHEMICAL",
    "NAIL_CHEMICAL",
    "PAINTING_WOODWORK",
    "FUEL_DISPENSING",
    "STATIC_ELECTRICITY",
    "FUEL_SPILL",
    "UNDERGROUND_TANK",
    "VAPOR_EXPOSURE",
    "ELECTRICAL_OVERLOAD",
    "FIRE_EVACUATION",
    "VENTILATION_POOR",
    "STEAM_IRON",
    "DRYER_OPERATION",
    "HIGH_PRESSURE_WASH",
    "NOISE_EXPOSURE",
}

HIGH_RISK_AGENTS = {
    "FIRE",
    "CHEMICAL",
    "CORROSION",
    "TOXIC",
    "ELECTRICITY",
    "HEAT_COLD",
    "BIOLOGICAL",
    "NOISE",
    "RADIATION",
    "ARC_FLASH",
    "DUST",
}

HAZARDOUS_AGENT_QUERY_EXPANSIONS = {
    "ARC_FLASH": ["ELECTRICITY"],
    "TOXIC": ["CHEMICAL"],
    "CORROSION": ["CHEMICAL"],
    "DUST": ["CHEMICAL"],
}

ACTIONABLE_MATCH_STATUSES = {"confirmed", "candidate"}

UNCERTAINTY_TERMS = (
    "확인 불가", "불명", "판단 곤란", "판단 어려", "가능성", "일시적",
    "착시", "단정", "충분한지", "실제", "일 수",
)

UNCERTAINTY_TERMS = UNCERTAINTY_TERMS + (
    "확인 불가", "확인불가", "확인 어려움", "확인 어렵", "확인 안", "확인이 안",
    "불명", "불분명", "판독 불가", "판독불가", "구분이 어렵", "식별 어려움",
    "알 수 없다", "알 수 없음", "판단 어려움", "판단이 어렵", "사진만으로",
    "사진으로는", "사진으로 확인", "프레임 밖", "화면 밖", "가려져", "흐리게",
    "추정", "가능성", "가능", "의심", "여부", "보이는지", "있는지", "없는지",
    "uncertain", "unclear", "unknown", "ambiguous", "not visible", "hard to tell",
)
UNCERTAINTY_TERMS = tuple(
    term for term in UNCERTAINTY_TERMS
    if term not in {"가능성", "가능", "여부", "보이는지", "있는지", "없는지", "사진으로 확인"}
)

CONFIRMATION_ONLY_TERMS = UNCERTAINTY_TERMS + (
    "여부", "있는지", "없는지", "일 경우", "경우", "라면", "있다면", "없다면",
    "수 있다", "수 있음", "일 수", "잠재", "단정", "기준 이내", "허용 범위",
    "초과 여부", "착용 여부", "작동 여부", "설치 여부", "미설치 시",
    "미착용 시", "누출이라면", "젖어 있다면", "건조됐는지", "정상이라면",
)

DIRECT_VISIBLE_UNSAFE_TERMS = (
    "없음", "없고", "없는 상태", "부재", "미설치", "미체결", "미착용",
    "노출", "손상", "파손", "풀려", "꺼져", "OFF", "고여", "기름",
    "차단", "막혀", "방치", "균열", "개방", "열려", "누출", "연기",
    "불꽃", "화염", "아크", "스파크", "젖어", "미끄러", "과적", "돌출",
    "붕락", "무너", "흘러내린", "회전 중", "가동 중", "움직이고",
    "접근하고", "접근 중", "가까이", "보호구 없이", "무보호",
    "unguarded", "exposed", "damaged", "broken", "missing", "blocked",
    "leaking", "spill", "running", "active operation",
)

DIRECT_UNSAFE_CONDITIONAL_TERMS = (
    "경우", "라면", "있다면", "없다면", "일 수", "수 있다", "수 있음",
    "가능", "가능성", "잠재", "추정", "단정", "여부", "불명", "불분명",
    "불확실", "확인 불가", "확인불가", "확인 어려", "사진만으로",
    "사진으로", "프레임 밖", "화면 밖", "가려", "기준 이내", "허용 범위",
)

STRONG_UNSAFE_OBSERVATION_TERMS = (
    "뚜렷", "완전히", "절단", "찢어", "마모", "풀려", "꺼져", "OFF",
    "가려져", "정상 작동이 불가능", "가동 중", "위험 구역", "인도 주행",
    "보행자 근접", "미설치", "없음", "노출", "손상", "파손", "방치",
    "고여", "기름", "차단", "부착", "가까이", "접근하고", "접근 중",
    "균열", "미끄러운 손잡이",
    "unguarded", "exposed", "damaged", "broken", "blocked", "missing",
    "off state", "running", "active operation",
)

SAFE_NORMAL_OPERATION_TERMS = (
    "LOTO 완료", "LOTO 적용", "잠금표지 완료", "잠금 표지 완료", "전원 차단 확인",
    "전원 차단 완료", "완전 정지", "정지 확인", "정상 설치", "정상 작동",
    "정상 조리", "정상 점등", "녹색 점등", "정기 점검 완료", "최신 정기 점검",
    "검지기 정상", "자동 차단 장치 표시등 녹색", "소화기",
    "보호구 착용", "내열 장갑 착용",
    "lockout complete", "tagout complete", "normal operation", "inspection complete",
)

SAFE_ADMINISTRATIVE_CONTEXT_TERMS = (
    "사무실", "사무소", "관리동", "관리 사무실", "제어실", "모니터링실",
    "컴퓨터 작업", "컴퓨터 화면", "모니터링", "대시보드", "원격 제어",
    "수질 데이터", "발전량", "스케줄", "일정", "도면 검토", "도면 작성",
    "CAD", "확인서", "설계 작업", "작업 지시",
    "교육실", "교육장", "훈련장", "안전 교육", "교육 진행", "교육 중",
    "교육생", "안전 영상",
    "작업 완료 확인", "완공 후", "주차 상태", "붐 접힘", "붐이 접혀",
    "정돈된", "정돈되어", "정리 상태 양호", "안전한 실내",
    "안전한 환경", "안전한 훈련", "통제된 훈련", "정상 가동",
    "경량", "소형 부품", "소형 밸브", "소형 씨앗", "소형 소모품",
    "1~2kg", "수납함", "씨앗 봉지",
    "지상 준비", "지상 작업", "지상 비계 자재", "조립 전", "진입하지 않았다", "외부 도면",
)

SAFE_NORMAL_NEGATION_TERMS = (
    "불가능", "불가", "없음", "없다", "없는", "미설치", "미비치", "부재",
    "미작동", "고장", "가려져", "가림", "차단", "위험", "과열", "과도",
    "여부", "불명", "불분명", "불확실", "추정",
    "not available", "not working", "missing", "absent", "blocked", "disabled",
)

BENIGN_ROUTINE_CLEANING_TERMS = (
    "중성 세제", "물만 사용", "세정제 미사용", "별도 세정제 없이",
    "일상 청소", "식탁 청소", "물 걸레", "물걸레", "정상 주방 환경",
    "neutral detergent", "routine cleaning",
)

ROUTINE_CLEANING_UNSAFE_TERMS = (
    "혼합", "혼합 안전성", "미확인", "불명", "라벨", "MSDS",
    "약품", "오인", "섭취", "잠금 없는", "아동 접근",
)

BENIGN_GROUND_LEVEL_HANDLING_TERMS = (
    "손이 닿는", "손 닿는", "낮은 위치", "발판 없이", "발판 불필요",
    "지상에서 작업", "지상 물품 정리", "작업 가능한 높이",
    "ground-level", "within reach",
)

GROUND_LEVEL_UNSAFE_TERMS = (
    "무거운", "중량물", "혼자", "단독", "상단", "높은", "발끝",
    "발을 걸치", "디딤", "불안정", "시야 차단", "낙하", "과중량",
    "약", "약품", "오인", "섭취", "잠금", "아동", "접근 가능",
    "heavy", "unstable",
)

POSITIVE_FIRE_EXTINGUISHER_TERMS = (
    "소화기 비치", "소화기 설치", "소화기 구비", "소화기 배치",
    "소화기 있음", "소화기 확인", "소화기 준비", "fire extinguisher present",
    "fire extinguisher available",
)

WEAK_ELECTRICAL_TERMS = (
    "라벨", "표기", "회로도", "정리", "꼬이", "겹친", "밀려",
    "정격", "소매", "전원에 연결", "사용하지 않는", "분리된",
)
STRONG_ELECTRICAL_TERMS = (
    "활선", "충전부", "노출", "스파크", "아크", "누전", "접지선",
    "접지", "젖", "습윤", "가로막", "접근", "차단 필요",
    "차단기를 조작", "비상 차단",
)

WEAK_CHEMICAL_TERMS = (
    "시일", "밀착", "들린", "PAPR", "유량", "면체", "성능 저하 가능성",
)
STRONG_CHEMICAL_TERMS = (
    "드럼", "뚜껑", "개방", "냄새", "MSDS", "미게시", "분말",
    "누출", "환기 미흡", "무환기", "호흡보호구 없이", "무보호",
    "증기", "축적",
)

WEAK_LADDER_TERMS = (
    "가려", "부분 가시성", "정확한 각도", "각도 측정", "안정적으로 지지",
)
STRONG_LADDER_TERMS = (
    "최상부", "3점 지지", "다리 들림", "미끄럼 방지", "마모",
    "통행로", "안전 통제",
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower or term in text for term in terms)


def _has_safe_normal_visual_evidence(text: str) -> bool:
    """Return True only for positive safe/normal visual evidence.

    Some short phrases invert their meaning when combined with a nearby
    negative term, for example "정상 작동이 불가능" or "소화기 없음".
    Treat those as unsafe context instead of suppressing the match.
    """
    if not text:
        return False

    lower = text.lower()
    if any(term.lower() in lower for term in POSITIVE_FIRE_EXTINGUISHER_TERMS):
        return True

    for term in SAFE_NORMAL_OPERATION_TERMS:
        term_lower = term.lower()
        if term == "소화기":
            continue

        start = lower.find(term_lower)
        while start >= 0:
            end = start + len(term_lower)
            window = lower[max(0, start - 18): min(len(lower), end + 18)]
            if not any(neg.lower() in window for neg in SAFE_NORMAL_NEGATION_TERMS):
                return True
            start = lower.find(term_lower, start + 1)

    return False


def _has_safe_administrative_visual_context(text: str) -> bool:
    """Detect normal office/training/planning/completed-work scenes.

    These cues describe a non-operational or already-controlled scene. They
    should not promote broad accident labels such as ERGONOMIC/FALL/SLIP into
    actionable SHE matches unless an explicit unsafe state is also visible.
    """
    if not text:
        return False
    if not _contains_any(text, SAFE_ADMINISTRATIVE_CONTEXT_TERMS):
        return False

    unsafe_check_text = text
    for phrase in ("정상 가동 중", "정상 가동", "정상 운영", "정상 작동"):
        unsafe_check_text = unsafe_check_text.replace(phrase, "")
    if _contains_any(unsafe_check_text, STRONG_UNSAFE_OBSERVATION_TERMS):
        return False
    return True


def _has_benign_routine_cleaning_context(text: str) -> bool:
    """Detect everyday cleaning/washing scenes that should not become hazards."""
    return (
        _contains_any(text, BENIGN_ROUTINE_CLEANING_TERMS)
        and not _contains_any(text, ROUTINE_CLEANING_UNSAFE_TERMS)
    )


def _has_benign_ground_level_handling_context(text: str) -> bool:
    """Detect low-height, ground-level sorting/handling scenes."""
    return (
        _contains_any(text, BENIGN_GROUND_LEVEL_HANDLING_TERMS)
        and not _contains_any(text, GROUND_LEVEL_UNSAFE_TERMS)
    )


def _is_compatible_cross_context(feature_context: str, work_contexts: list[str]) -> bool:
    """Allow nearby practical contexts when the ontology is more specific."""
    if not feature_context or not work_contexts:
        return False
    compatible = {
        "GENERAL_WORKPLACE": {
            "WET_FLOOR_WORK",
            "CLEANING_WET",
            "MATERIAL_HANDLING",
            "GRINDING",
            "NIGHT_SOLO_WORK",
            "CROWD_MANAGEMENT",
            "FIRE_EVACUATION",
        },
        "LADDER": {"SCAFFOLD", "ROPE_ACCESS", "HIGH_SHELF_WORK"},
        "MATERIAL_HANDLING": {"LIFT_WORK", "HEAVY_LIFTING", "PACKAGE_SORTING"},
        "VEHICLE": {"LIFT_WORK", "MATERIAL_HANDLING", "FORKLIFT_OPERATION"},
        "CONFINED_SPACE": {"CHEMICAL_WORK", "VENTILATION_POOR", "UNDERGROUND_TANK"},
    }
    return any(feature_context in compatible.get(context, set()) for context in work_contexts)


def _has_direct_visible_unsafe_evidence(text: str) -> bool:
    """Return True when an unsafe condition itself is visibly asserted.

    Conditional statements such as "미설치 시", "누출이라면", or
    "사진만으로 확인 불가" should stay as confirmation candidates.
    """
    if not text:
        return False
    lower = text.lower()
    for term in DIRECT_VISIBLE_UNSAFE_TERMS:
        term_lower = term.lower()
        start = lower.find(term_lower)
        while start >= 0:
            end = start + len(term_lower)
            window = lower[max(0, start - 18): min(len(lower), end + 18)]
            if not any(cond.lower() in window for cond in DIRECT_UNSAFE_CONDITIONAL_TERMS):
                return True
            start = lower.find(term_lower, start + 1)
    return False


def is_direct_penalty_match(match: Any) -> bool:
    """Whether a SHE match is strong enough for direct penalty exposure.

    Candidate SHE still helps find SR/Guide.  Only weak/ambiguous candidates
    are excluded from direct penalty exposure.
    """
    status = getattr(match, "match_status", "")
    reasons = set(getattr(match, "status_reasons", []) or [])
    if status == "confirmed":
        return True
    if status != "candidate":
        return False
    if "confirmation_required" in reasons:
        return False
    return (
        "accident_type_match" in reasons
        or "accident_agent_match" in reasons
        or "unsafe_state" in reasons
    )


def has_observable_violation_signal(
    accident_types: list[str] | None = None,
    hazardous_agents: list[str] | None = None,
    work_contexts: list[str] | None = None,
    ppe_states: list[str] | None = None,
    environmental: list[str] | None = None,
    *,
    high_severity_observation: bool = False,
    visual_cues: list[str] | None = None,
) -> bool:
    """Return True when the observation has enough signal for violation handling.

    Work context + hazardous agent alone is often just "a work situation".
    For penalties/SR assertion, require an accident/risk type or an explicit
    unsafe visual state. This keeps normal protective-work scenes as guide
    candidates instead of treating them as violations.
    """
    unsafe_state = (
        any(state in UNSAFE_PPE_STATES for state in (ppe_states or []))
        or any(state in UNSAFE_ENVIRONMENTAL_STATES for state in (environmental or []))
    )
    visual_text = " ".join(visual_cues or [])
    if (
        _has_benign_routine_cleaning_context(visual_text)
        and not high_severity_observation
        and not any(state in UNSAFE_PPE_STATES for state in (ppe_states or []))
    ):
        return False
    if (
        _has_benign_ground_level_handling_context(visual_text)
        and not high_severity_observation
        and not any(state in UNSAFE_PPE_STATES for state in (ppe_states or []))
    ):
        return False
    safe_non_operational_context = bool(visual_cues) and (
        _has_safe_administrative_visual_context(visual_text)
        or _has_safe_normal_visual_evidence(visual_text)
    )
    if (
        safe_non_operational_context
        and not high_severity_observation
        and not unsafe_state
        and not (accident_types and hazardous_agents)
        and not (
            accident_types
            and bool(set(work_contexts or []) & {"MATERIAL_HANDLING", "VEHICLE", "MACHINE", "ELECTRICAL_WORK"})
        )
    ):
        return False
    if accident_types:
        return True
    if high_severity_observation:
        return True
    if unsafe_state:
        return True
    if (
        bool(set(work_contexts or []) & HIGH_RISK_AGENT_CONTEXTS)
        and bool(set(hazardous_agents or []) & HIGH_RISK_AGENTS)
    ):
        return True
    return False


def _has_unsafe_state(ppe_states: list[str], environmental: list[str]) -> bool:
    return (
        any(state in UNSAFE_PPE_STATES for state in ppe_states)
        or any(state in UNSAFE_ENVIRONMENTAL_STATES for state in environmental)
    )


def _has_normal_cue(ppe_states: list[str]) -> bool:
    return any(state in NORMAL_PPE_STATES for state in ppe_states)


def _expand_hazardous_agents_for_she_query(hazardous_agents: list[str]) -> list[str]:
    expanded = list(dict.fromkeys(hazardous_agents or []))
    for agent in list(expanded):
        for parent in HAZARDOUS_AGENT_QUERY_EXPANSIONS.get(agent, []):
            if parent not in expanded:
                expanded.append(parent)
    return expanded


def _weak_visual_suppression(
    *,
    feature_context: str,
    hazardous_agents: list[str],
    ppe_states: list[str],
    visual_cues: list[str],
) -> tuple[bool, list[str]]:
    """Detect matches that should remain a confirmation candidate.

    These rules do not remove the SHE match. They only prevent a weak visual
    cue from being promoted to a confirmed violation/direct penalty.
    """
    text = " ".join(cue for cue in visual_cues if cue)
    if not text:
        return False, []

    strong_unsafe = _contains_any(text, STRONG_UNSAFE_OBSERVATION_TERMS)
    uncertain = _contains_any(text, UNCERTAINTY_TERMS)
    confirmation_only = _contains_any(text, CONFIRMATION_ONLY_TERMS)
    direct_visible_unsafe = _has_direct_visible_unsafe_evidence(text)
    safe_normal = _has_safe_normal_visual_evidence(text)
    if safe_normal and strong_unsafe and uncertain:
        return True, ["mixed_safe_and_unsafe_visual_evidence"]
    if safe_normal and not strong_unsafe:
        return True, ["normal_operation_visual_evidence"]
    if confirmation_only and not direct_visible_unsafe:
        return True, ["confirmation_only_visual_evidence"]

    if feature_context == "ELECTRICAL_WORK" and (
        "ELECTRICITY" in hazardous_agents or "ARC_FLASH" in hazardous_agents
    ):
        if _contains_any(text, STRONG_ELECTRICAL_TERMS):
            return False, []
        if uncertain or _contains_any(text, WEAK_ELECTRICAL_TERMS):
            return True, ["weak_electrical_visual_evidence"]

    if feature_context == "CHEMICAL_WORK" and (
        "CHEMICAL" in hazardous_agents or "TOXIC" in hazardous_agents or "DUST" in hazardous_agents
    ):
        if _contains_any(text, STRONG_CHEMICAL_TERMS):
            return False, []
        if uncertain or _contains_any(text, WEAK_CHEMICAL_TERMS):
            return True, ["weak_chemical_visual_evidence"]

    if feature_context == "LADDER":
        if _contains_any(text, STRONG_LADDER_TERMS):
            return False, []
        if uncertain or _contains_any(text, WEAK_LADDER_TERMS):
            return True, ["weak_ladder_visual_evidence"]

    if _has_normal_cue(ppe_states) and uncertain and not strong_unsafe:
        return True, ["normal_ppe_with_uncertain_visual_evidence"]

    return False, []


def _classify_match_status(
    *,
    features: dict[str, Any],
    matched_dims: list[str],
    accident_types: list[str],
    hazardous_agents: list[str],
    work_contexts: list[str],
    ppe_states: list[str],
    environmental: list[str],
    visual_score: float,
    visual_cues: list[str],
) -> tuple[str, list[str]]:
    """Classify a SHE match into an actionability level.

    The matcher may find useful nearby patterns. This status says whether the
    match is strong enough to drive SR/penalty logic or should remain context.
    """
    reasons: list[str] = []
    feature_context = features.get("work_context") or "OTHER"
    accident_match = "accident_type" in matched_dims
    agent_match = "hazardous_agent" in matched_dims
    same_context = (
        not work_contexts
        or feature_context == "OTHER"
        or feature_context in work_contexts
    )
    unsafe_state = _has_unsafe_state(ppe_states, environmental)
    unsafe_ppe = any(state in UNSAFE_PPE_STATES for state in ppe_states)
    unsafe_env = any(state in UNSAFE_ENVIRONMENTAL_STATES for state in environmental)
    normal_cue = _has_normal_cue(ppe_states)
    visual_text = " ".join(visual_cues)
    if _has_benign_routine_cleaning_context(visual_text) and not unsafe_ppe:
        return "context_only", ["benign_routine_cleaning_context"]
    if _has_benign_ground_level_handling_context(visual_text) and not unsafe_ppe:
        return "context_only", ["benign_ground_level_handling_context"]
    safe_normal_visual = _has_safe_normal_visual_evidence(visual_text)
    if safe_normal_visual and not accident_types and not unsafe_state:
        return "rejected_by_normal_cue", ["normal_operation_without_accident_signal"]

    if not same_context:
        if accident_match and agent_match:
            return "candidate", ["cross_context", "accident_agent_match"]
        if accident_match and _is_compatible_cross_context(feature_context, work_contexts):
            return "candidate", ["compatible_cross_context", "accident_type_match"]
        if agent_match and unsafe_env and _is_compatible_cross_context(feature_context, work_contexts):
            return "candidate", ["compatible_cross_context", "agent_environment_match"]
        return "context_only", ["cross_context"]

    if "work_context" not in matched_dims and work_contexts:
        return "context_only", ["no_work_context_match"]

    high_risk_agent_context = (
        bool(set(work_contexts) & HIGH_RISK_AGENT_CONTEXTS)
        and bool(set(hazardous_agents) & HIGH_RISK_AGENTS)
        and agent_match
    )
    weak_suppressed, weak_reasons = _weak_visual_suppression(
        feature_context=feature_context,
        hazardous_agents=hazardous_agents,
        ppe_states=ppe_states,
        visual_cues=visual_cues,
    )
    safe_admin_context = _has_safe_administrative_visual_context(visual_text)

    if safe_admin_context and not unsafe_state and not hazardous_agents:
        return "context_only", ["safe_administrative_or_completed_work_context"]

    if normal_cue and not accident_types and not unsafe_ppe:
        return "rejected_by_normal_cue", ["normal_ppe_without_accident_signal"]

    if (
        not accident_types
        and not hazardous_agents
        and not unsafe_ppe
        and unsafe_env
        and visual_score >= 0.5
        and _contains_any(" ".join(visual_cues), UNCERTAINTY_TERMS)
    ):
        return "candidate", ["environment_only_visual_evidence", "confirmation_required"]

    if not accident_types and not hazardous_agents and not unsafe_ppe and unsafe_env:
        return "context_only", ["environment_only_without_risk_signal"]

    if feature_context == "OTHER" and (agent_match or accident_match) and (unsafe_env or hazardous_agents):
        return "candidate", ["generic_context_feature_match"]

    if accident_match:
        reasons.append("accident_type_match")
        if weak_suppressed:
            if (
                "normal_operation_visual_evidence" in weak_reasons
                or "mixed_safe_and_unsafe_visual_evidence" in weak_reasons
            ):
                return "candidate", reasons + weak_reasons + ["confirmation_required"]
            return "candidate", reasons + weak_reasons + ["confirmation_required"]
        if len(matched_dims) >= 3:
            reasons.append("three_axis_match")
            return "confirmed", reasons
        if unsafe_state:
            reasons.append("unsafe_state")
            return "confirmed", reasons
        if visual_score >= 0.3:
            reasons.append("visual_support")
            return "confirmed", reasons
        return "candidate", reasons

    if unsafe_state:
        reasons.append("unsafe_state")
        return "candidate", reasons

    if high_risk_agent_context:
        reasons.append("high_risk_agent_context")
        if weak_suppressed:
            if (
                "normal_operation_visual_evidence" in weak_reasons
                or "mixed_safe_and_unsafe_visual_evidence" in weak_reasons
            ):
                return "candidate", reasons + weak_reasons + ["confirmation_required"]
            return "candidate", reasons + weak_reasons + ["confirmation_required"]
        if _contains_any(" ".join(visual_cues), UNCERTAINTY_TERMS):
            return "candidate", reasons + ["confirmation_required"]
        if visual_score >= 0.5:
            reasons.append("visual_support")
            return "confirmed", reasons
        return "candidate", reasons

    return "context_only", ["weak_context_agent_match"]

_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]{2,}")
_KOREAN_SUFFIXES = (
    "으로부터", "에서", "에게", "으로", "로", "은", "는", "이", "가",
    "을", "를", "에", "의", "와", "과", "도", "만",
)
_STOPWORDS = {
    "작업", "작업자", "작업자가", "작업자는", "작업자들", "상태", "사진",
    "보임", "보이는", "보이지", "있음", "있는", "없음", "없는", "중임",
    "주변", "해당", "구역", "일반", "바로", "아래", "위치", "인근",
}


def _normalize_text(text: str) -> str:
    return " ".join(_TOKEN_RE.findall((text or "").lower()))


def _tokens(text: str) -> set[str]:
    tokens = set()
    for raw in _TOKEN_RE.findall((text or "").lower()):
        token = raw
        for suffix in _KOREAN_SUFFIXES:
            if len(token) > len(suffix) + 1 and token.endswith(suffix):
                token = token[: -len(suffix)]
                break
        if len(token) >= 2 and token not in _STOPWORDS:
            tokens.add(token)
    return tokens


def _visual_trigger_score(visual_cues: list[str], visual_triggers: list[str]) -> float:
    if not visual_cues or not visual_triggers:
        return 0.0

    best = 0.0
    for cue in visual_cues:
        cue_norm = _normalize_text(cue)
        cue_tokens = _tokens(cue)
        if not cue_norm or not cue_tokens:
            continue
        for trigger in visual_triggers:
            trigger_norm = _normalize_text(trigger)
            trigger_tokens = _tokens(trigger)
            if not trigger_norm or not trigger_tokens:
                continue
            overlap = len(cue_tokens & trigger_tokens) / max(1, len(trigger_tokens))
            ratio = SequenceMatcher(None, cue_norm, trigger_norm).ratio()
            best = max(best, overlap, ratio if ratio >= 0.75 else 0.0)
    return round(best, 3)


class SHEMatchResult:
    """1 매칭된 SHE."""
    def __init__(
        self,
        she_id: str,
        name: str,
        features: dict,
        broadness: float,
        match_score: float,
        matched_dims: list[str],
        visual_score: float,
        match_status: str,
        status_reasons: list[str],
        industry_hints: list[str],
        industry_alignment: str,
        industry_reasons: list[str],
        source_sr_ids: list[str],
        applies_sr_ids: list[str],
        applies_ci_ids: list[str],
        source_guides: list[str],
    ):
        self.she_id = she_id
        self.name = name
        self.features = features
        self.broadness = broadness
        self.match_score = match_score      # 0.0~1.0
        self.matched_dims = matched_dims    # 일치한 feature dim 이름
        self.visual_score = visual_score
        self.match_status = match_status
        self.status_reasons = status_reasons
        self.industry_hints = industry_hints
        self.industry_alignment = industry_alignment
        self.industry_reasons = industry_reasons
        self.source_sr_ids = source_sr_ids
        self.applies_sr_ids = applies_sr_ids
        self.applies_ci_ids = applies_ci_ids
        self.source_guides = source_guides

    def to_dict(self) -> dict:
        return {
            "she_id": self.she_id,
            "name": self.name,
            "features": self.features,
            "broadness": self.broadness,
            "match_score": self.match_score,
            "matched_dims": self.matched_dims,
            "visual_score": self.visual_score,
            "match_status": self.match_status,
            "status_reasons": self.status_reasons,
            "industry_hints": self.industry_hints,
            "industry_alignment": self.industry_alignment,
            "industry_reasons": self.industry_reasons,
            "applies_sr_ids": self.applies_sr_ids,
            "applies_ci_count": len(self.applies_ci_ids),
            "source_guides": self.source_guides,
        }


def match_she(
    db: Session,
    accident_types: list[str] | None = None,
    hazardous_agents: list[str] | None = None,
    work_contexts: list[str] | None = None,
    ppe_states: list[str] | None = None,
    environmental: list[str] | None = None,
    visual_cues: list[str] | None = None,
    industry_contexts: list[str] | None = None,
    work_activity: str | None = None,
    top_n: int = 3,
    min_matched_dims: int = 2,
    min_visual_score: float = 0.0,
    min_agent_only_visual_score: float = 0.0,
) -> list[SHEMatchResult]:
    """PG에서 active SHE를 facet 매칭으로 검색.

    Args:
      accident_types/hazardous_agents/work_contexts: GPT Track B 3축 (uppercase enum)
      work_activity: 추론된 work_activity (선택, 없으면 OTHER)
      top_n: 반환할 최대 SHE 수
      min_matched_dims: ≥N dim 일치해야 매칭 (default 2 = strict)

    Returns:
      List of SHEMatchResult sorted by match_score desc.

    Algorithm:
      1. SHE 후보를 features JSONB로 쿼리 (broad filter)
      2. 각 SHE의 8 dim 중 입력 facets와 일치 dim count
      3. min_matched_dims 충족 + match_score = matched / 8
      4. broadness 가중 (specific SHE 우선)
      5. top_n 반환
    """
    if not settings.OHS_ENABLE_SHE:
        return []

    accident_types = accident_types or []
    hazardous_agents = _expand_hazardous_agents_for_she_query(hazardous_agents or [])
    work_contexts = work_contexts or []
    ppe_states = ppe_states or []
    environmental = environmental or []
    visual_cues = visual_cues or []
    industry_contexts = industry_contexts or []
    visual_text = " ".join(cue for cue in visual_cues if cue)
    uncertain_visual = _contains_any(visual_text, UNCERTAINTY_TERMS)

    # Empty input → empty (no matching possible)
    if not (accident_types or hazardous_agents or work_contexts):
        return []

    # Step 1: 후보 SHE 검색 — features JSONB의 work_context 또는 accident_type 또는 hazardous_agent 일치
    # PG에서 OR 조건으로 broad 검색 후 in-Python에서 정밀 매칭
    sql = text("""
        SELECT she_id, name, features, broadness_score, source_sr_ids, visual_triggers
        FROM she_catalog
        WHERE status IN ('approved_auto', 'approved_manual')
          AND (superseded_by IS NULL)
          AND (
                features->>'work_context' = ANY(:wcs)
             OR features->>'hazardous_agent' = ANY(:has)
             OR features->>'accident_type' = ANY(:ats)
          )
        ORDER BY
          (
            CASE WHEN features->>'work_context' = ANY(:wcs) THEN 1 ELSE 0 END
          + CASE WHEN features->>'hazardous_agent' = ANY(:has) THEN 1 ELSE 0 END
          + CASE WHEN features->>'accident_type' = ANY(:ats) THEN 1 ELSE 0 END
          ) DESC,
          broadness_score DESC
        LIMIT 500
    """)
    rows = db.execute(sql, {
        "wcs": work_contexts or [""],
        "has": hazardous_agents or [""],
        "ats": accident_types or [""],
    }).fetchall()

    # Step 2: 정밀 매칭 — 각 SHE의 8 dim 중 일치 dim count
    candidates: list[SHEMatchResult] = []
    for row in rows:
        she_id, name, features, broadness, source_sr_ids, visual_triggers = row
        if isinstance(features, str):
            import json
            features = json.loads(features)
        if isinstance(source_sr_ids, str):
            source_sr_ids = json.loads(source_sr_ids)
        if isinstance(visual_triggers, str):
            visual_triggers = json.loads(visual_triggers)
        visual_triggers = visual_triggers or []

        matched_dims = []
        # work_context
        if features.get("work_context") in work_contexts:
            matched_dims.append("work_context")
        # hazardous_agent
        if features.get("hazardous_agent") in hazardous_agents:
            matched_dims.append("hazardous_agent")
        # accident_type
        if features.get("accident_type") in accident_types:
            matched_dims.append("accident_type")
        # work_activity (선택)
        if work_activity and features.get("work_activity") == work_activity:
            matched_dims.append("work_activity")

        ppe_feature = features.get("ppe_state")
        env_feature = features.get("environmental")
        specific_ppe_states = [state for state in ppe_states if state != "OTHER"]
        specific_environmental = [state for state in environmental if state != "OTHER"]
        specific_mismatches = []
        if specific_ppe_states and ppe_feature and ppe_feature != "OTHER":
            if ppe_feature not in specific_ppe_states:
                if not (
                    uncertain_visual
                    and ppe_feature in UNSAFE_PPE_STATES
                    and any(state in NORMAL_PPE_STATES for state in specific_ppe_states)
                ):
                    specific_mismatches.append("ppe_state")
            else:
                matched_dims.append("ppe_state")
        if specific_environmental and env_feature and env_feature != "OTHER":
            if env_feature not in specific_environmental:
                specific_mismatches.append("environmental")
            else:
                matched_dims.append("environmental")

        if specific_mismatches:
            continue

        visual_score = 0.0
        if visual_cues and visual_triggers:
            visual_score = _visual_trigger_score(visual_cues, visual_triggers)
            if min_visual_score > 0 and visual_score < min_visual_score:
                continue
        elif min_visual_score > 0 and visual_cues:
            continue

        if (
            min_agent_only_visual_score > 0
            and visual_cues
            and "work_context" in matched_dims
            and "hazardous_agent" in matched_dims
            and "accident_type" not in matched_dims
            and "ppe_state" not in matched_dims
            and "environmental" not in matched_dims
            and visual_score < min_agent_only_visual_score
        ):
            continue

        if len(matched_dims) < min_matched_dims:
            continue

        # match_score: matched_dims 수 / 6 (현재 가용 dim) + broadness 가중
        # PG NUMERIC(4,3)이 Decimal 타입으로 반환되므로 float 변환 필수
        broadness_f = float(broadness) if broadness is not None else 0.5
        industry_hints = industry_hints_for_features(features)
        industry_adjustment, industry_alignment, industry_reasons = score_industry_alignment(
            industry_hints,
            industry_contexts,
        )
        match_score = (len(matched_dims) / 6.0) * 0.7 + broadness_f * 0.3
        match_score = max(0.0, min(1.0, match_score + industry_adjustment))
        match_status, status_reasons = _classify_match_status(
            features=features,
            matched_dims=matched_dims,
            accident_types=accident_types,
            hazardous_agents=hazardous_agents,
            work_contexts=work_contexts,
            ppe_states=ppe_states,
            environmental=environmental,
            visual_score=visual_score,
            visual_cues=visual_cues,
        )
        if industry_alignment == "mismatch":
            status_reasons = status_reasons + ["industry_mismatch"]

        candidates.append(SHEMatchResult(
            she_id=she_id,
            name=name,
            features=features,
            broadness=broadness_f,
            match_score=match_score,
            matched_dims=matched_dims,
            visual_score=visual_score,
            match_status=match_status,
            status_reasons=status_reasons,
            industry_hints=industry_hints,
            industry_alignment=industry_alignment,
            industry_reasons=industry_reasons,
            source_sr_ids=source_sr_ids or [],
            applies_sr_ids=[],     # follow-up에서 채움
            applies_ci_ids=[],
            source_guides=[],
        ))

    # Step 3: top_n by match_score desc
    status_rank = {
        "confirmed": 0,
        "candidate": 1,
        "review_candidate": 2,
        "context_only": 3,
        "rejected_by_normal_cue": 4,
    }
    industry_rank = {
        "match": 0,
        "general": 1,
        "unknown": 2,
        "mismatch": 3,
    }
    candidates.sort(key=lambda c: (
        status_rank.get(c.match_status, 9),
        industry_rank.get(c.industry_alignment, 2),
        -c.match_score,
    ))
    top = candidates[:top_n]

    # Step 4: 매칭 SHE의 SR/CI/Guide follow (PG join)
    if top:
        she_ids = [c.she_id for c in top]
        sr_sql = text("""
            SELECT she_id, sr_id, confidence
            FROM she_sr_mapping
            WHERE she_id = ANY(:she_ids)
        """)
        sr_rows = db.execute(sr_sql, {"she_ids": she_ids}).fetchall()
        sr_by_she: dict[str, list[str]] = {}
        for sid, sr_id, conf in sr_rows:
            sr_by_she.setdefault(sid, []).append(sr_id)

        ci_sql = text("""
            SELECT she_id, ci_id
            FROM she_ci_mapping
            WHERE she_id = ANY(:she_ids)
            LIMIT 200
        """)
        ci_rows = db.execute(ci_sql, {"she_ids": she_ids}).fetchall()
        ci_by_she: dict[str, list[str]] = {}
        for sid, ci_id in ci_rows:
            ci_by_she.setdefault(sid, []).append(ci_id)

        # Guide follow: linked CI의 source_guide
        if ci_by_she:
            all_cis = list({ci for cis in ci_by_she.values() for ci in cis})
            g_sql = text("""
                SELECT identifier, source_guide
                FROM checklist_items
                WHERE identifier = ANY(:cis)
            """)
            g_rows = db.execute(g_sql, {"cis": all_cis}).fetchall()
            ci_to_guide = {row[0]: row[1] for row in g_rows}
        else:
            ci_to_guide = {}

        for c in top:
            c.applies_sr_ids = sr_by_she.get(c.she_id, [])
            c.applies_ci_ids = ci_by_she.get(c.she_id, [])
            c.source_guides = sorted(set(
                ci_to_guide[ci] for ci in c.applies_ci_ids if ci in ci_to_guide
            ))

    logger.warning(f"[Layer0/SHE] matched {len(top)} SHE: "
                   f"{[(c.she_id, c.match_status, c.match_score, c.matched_dims, c.industry_alignment) for c in top]}")
    return top


def get_matched_sr_ids(matches: list[SHEMatchResult]) -> list[str]:
    """매칭 SHE 모음의 unique SR identifier list."""
    ids: list[str] = []
    seen: set[str] = set()
    for m in matches:
        for sr in m.applies_sr_ids:
            if sr not in seen:
                seen.add(sr)
                ids.append(sr)
    return ids


def get_matched_guides(matches: list[SHEMatchResult]) -> list[str]:
    """매칭 SHE 모음의 unique source_guide list."""
    guides: list[str] = []
    seen: set[str] = set()
    for m in matches:
        for g in m.source_guides:
            if g not in seen:
                seen.add(g)
                guides.append(g)
    return guides
