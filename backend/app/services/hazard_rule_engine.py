"""Deterministic Rule Engine — Track B 정규화 결과를 최종 canonical codes로 확정.

결정론적 보장: 동일 입력 → 동일 출력.
점수 기반 확정 + 교차 추론 규칙 적용.
"""
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from sqlalchemy.orm import Session
from app.services.industry_context import infer_industry_context, score_industry_alignment

logger = logging.getLogger(__name__)

CORE = Namespace("https://cashtoss.info/ontology/core#")
LAW = Namespace("https://cashtoss.info/ontology/law#")
PEN = Namespace("https://cashtoss.info/ontology/penalty#")
SR = Namespace("https://cashtoss.info/ontology/sr#")

_PENALTY_INDEX: Optional[dict] = None

# ═══ 교차 추론 규칙 (SWRL 대응) ═══
# work_context → 암시적 accident_type/agent 추가
CROSS_INFERENCE_RULES = [
    # R-1: 비계 → 추락
    {"if_context": "SCAFFOLD", "imply_accident": "FALL"},
    # R-2: 밀폐공간 + 화학물질 → 독성 위험
    {"if_context": "CONFINED_SPACE", "if_agent": "CHEMICAL", "imply_agent": "TOXIC"},
    # R-3: 크레인 → 낙하물
    {"if_context": "CRANE", "imply_accident": "FALLING_OBJECT"},
    # R-4: 기계 → 끼임
    {"if_context": "MACHINE", "imply_accident": "CRUSH"},
    # R-5: 굴착 → 붕괴
    {"if_context": "EXCAVATION", "imply_accident": "COLLAPSE"},
    # R-6: 차량 → 충돌
    {"if_context": "VEHICLE", "imply_accident": "COLLISION"},
    # R-7: 압력용기 → 폭발
    {"if_context": "PRESSURE_VESSEL", "imply_agent": "FIRE"},
]

WORK_CONTEXT_QUERY_EXPANSIONS = {
    "LIFT_WORK": ["VEHICLE", "MACHINE", "MATERIAL_HANDLING"],
    "OIL_DRAIN": ["VEHICLE", "CHEMICAL_WORK"],
    "TIRE_CHANGE": ["VEHICLE", "PRESSURE_VESSEL", "MACHINE"],
    "WELDING_REPAIR": ["WELDING", "VEHICLE"],
    "EV_BATTERY": ["ELECTRICAL_WORK", "VEHICLE"],
    "HAIR_CHEMICAL": ["CHEMICAL_WORK", "GENERAL_WORKPLACE"],
    "NAIL_CHEMICAL": ["CHEMICAL_WORK", "GENERAL_WORKPLACE"],
    "HOT_TOOL": ["ELECTRICAL_WORK", "GENERAL_WORKPLACE"],
    "SKIN_DEVICE": ["ELECTRICAL_WORK", "MACHINE", "GENERAL_WORKPLACE"],
    "HAIR_WASH": ["GENERAL_WORKPLACE"],
    "SHELF_STOCKING": ["STORAGE_SHELF", "MATERIAL_HANDLING", "GENERAL_WORKPLACE"],
    "NIGHT_SOLO": ["GENERAL_WORKPLACE"],
    "COLD_DISPLAY": ["COLD_STORAGE", "ELECTRICAL_WORK", "GENERAL_WORKPLACE"],
    "BOX_HANDLING": ["MATERIAL_HANDLING", "STORAGE_SHELF", "GENERAL_WORKPLACE"],
    "CASHIER_AREA": ["ELECTRICAL_WORK", "GENERAL_WORKPLACE"],
    "SAWING": ["MACHINE", "MATERIAL_HANDLING"],
    "SANDING": ["GRINDING", "MACHINE", "CHEMICAL_WORK"],
    "PAINTING_WOODWORK": ["PAINTING", "CHEMICAL_WORK"],
    "LADDER_INTERIOR": ["LADDER", "GENERAL_WORKPLACE"],
    "NAIL_GUN": ["MACHINE", "PRESSURE_VESSEL"],
}

WORK_CONTEXT_QUERY_EXPANSIONS.update({
    "DRY_CLEANING_SOLVENT": ["CHEMICAL_WORK", "CONFINED_SPACE", "GENERAL_WORKPLACE"],
    "CHEMICAL_SPOTTING": ["CHEMICAL_WORK", "GENERAL_WORKPLACE"],
    "PRESS_MACHINE": ["MACHINE", "GENERAL_WORKPLACE"],
    "WASHING_MACHINE": ["MACHINE", "GENERAL_WORKPLACE"],
    "STEAM_IRON": ["HOT_TOOL", "ELECTRICAL_WORK", "GENERAL_WORKPLACE"],
    "GARMENT_SORTING": ["MATERIAL_HANDLING", "GENERAL_WORKPLACE"],
    "HIGH_PRESSURE_WASH": ["MACHINE", "PRESSURE_VESSEL", "GENERAL_WORKPLACE"],
    "CHEMICAL_APPLICATION": ["CHEMICAL_WORK", "GENERAL_WORKPLACE"],
    "WAX_POLISHING": ["CHEMICAL_WORK", "CLEANING_WET", "GENERAL_WORKPLACE"],
    "CONVEYOR_WASH": ["CONVEYOR", "MACHINE", "CLEANING_WET"],
    "INTERIOR_CLEANING": ["CLEANING_WET", "GENERAL_WORKPLACE"],
    "WET_FLOOR_WORK": ["CLEANING_WET", "GENERAL_WORKPLACE"],
    "DOG_GROOMING": ["GENERAL_WORKPLACE"],
    "CAT_HANDLING": ["GENERAL_WORKPLACE"],
    "PET_BATHING": ["CLEANING_WET", "GENERAL_WORKPLACE"],
    "DRYER_OPERATION": ["MACHINE", "ELECTRICAL_WORK", "GENERAL_WORKPLACE"],
    "CAGE_CLEANING": ["CLEANING_WET", "GENERAL_WORKPLACE"],
    "ANIMAL_FEEDING": ["GENERAL_WORKPLACE"],
    "FORKLIFT_OPERATION": ["VEHICLE", "MATERIAL_HANDLING"],
    "HEAVY_LIFTING": ["MATERIAL_HANDLING"],
    "HIGH_SHELF_WORK": ["STORAGE_SHELF", "MATERIAL_HANDLING"],
    "LOADING_DOCK": ["MATERIAL_HANDLING", "VEHICLE"],
    "PACKAGE_SORTING": ["MATERIAL_HANDLING", "CONVEYOR"],
    "CONVEYOR_BELT": ["CONVEYOR", "MACHINE"],
    "PESTICIDE_SPRAY": ["CHEMICAL_WORK", "GENERAL_WORKPLACE"],
    "FARM_MACHINERY": ["MACHINE", "VEHICLE", "GENERAL_WORKPLACE"],
    "GREENHOUSE_WORK": ["CHEMICAL_WORK", "GENERAL_WORKPLACE"],
    "HARVEST_WORK": ["MATERIAL_HANDLING", "GENERAL_WORKPLACE"],
    "IRRIGATION": ["CLEANING_WET", "GENERAL_WORKPLACE"],
    "FERTILIZER_HANDLING": ["CHEMICAL_WORK", "MATERIAL_HANDLING"],
    "ELECTRICAL_OVERLOAD": ["ELECTRICAL_WORK", "GENERAL_WORKPLACE"],
    "FIRE_EVACUATION": ["GENERAL_WORKPLACE"],
    "VENTILATION_POOR": ["CONFINED_SPACE", "GENERAL_WORKPLACE"],
    "CLEANING_NIGHT": ["CLEANING_WET", "NIGHT_SOLO", "GENERAL_WORKPLACE"],
    "CROWD_MANAGEMENT": ["GENERAL_WORKPLACE"],
    "NOISE_EXPOSURE": ["MACHINE", "GENERAL_WORKPLACE"],
    "FUEL_DISPENSING": ["CHEMICAL_WORK", "VEHICLE", "GENERAL_WORKPLACE"],
    "STATIC_ELECTRICITY": ["ELECTRICAL_WORK", "CHEMICAL_WORK", "GENERAL_WORKPLACE"],
    "FUEL_SPILL": ["CHEMICAL_WORK", "CLEANING_WET", "GENERAL_WORKPLACE"],
    "UNDERGROUND_TANK": ["CONFINED_SPACE", "CHEMICAL_WORK", "PRESSURE_VESSEL"],
    "VAPOR_EXPOSURE": ["CHEMICAL_WORK", "CONFINED_SPACE", "GENERAL_WORKPLACE"],
    "NIGHT_SOLO_WORK": ["NIGHT_SOLO", "GENERAL_WORKPLACE"],
})

CROSS_INFERENCE_RULES.extend([
    {"if_context": "PRESS_MACHINE", "imply_accident": "CRUSH"},
    {"if_context": "WASHING_MACHINE", "imply_accident": "CRUSH"},
    {"if_context": "DRYER_OPERATION", "imply_agent": "HEAT_COLD"},
    {"if_context": "CONVEYOR_WASH", "imply_accident": "CRUSH"},
    {"if_context": "CONVEYOR_BELT", "imply_accident": "CRUSH"},
    {"if_context": "FORKLIFT_OPERATION", "imply_accident": "COLLISION"},
    {"if_context": "HIGH_SHELF_WORK", "imply_accident": "FALLING_OBJECT"},
    {"if_context": "LOADING_DOCK", "imply_accident": "COLLISION"},
    {"if_context": "FARM_MACHINERY", "imply_accident": "CRUSH"},
    {"if_context": "ELECTRICAL_OVERLOAD", "imply_agent": "ELECTRICITY"},
    {"if_context": "FIRE_EVACUATION", "imply_agent": "FIRE"},
    {"if_context": "NOISE_EXPOSURE", "imply_agent": "NOISE"},
    {"if_context": "FUEL_DISPENSING", "imply_agent": "FIRE"},
    {"if_context": "STATIC_ELECTRICITY", "imply_agent": "ELECTRICITY"},
    {"if_context": "FUEL_SPILL", "imply_agent": "FIRE"},
    {"if_context": "UNDERGROUND_TANK", "imply_agent": "TOXIC"},
    {"if_context": "VAPOR_EXPOSURE", "imply_agent": "TOXIC"},
])


def _expand_work_contexts_for_query(work_contexts: list[str]) -> list[str]:
    """Keep specific contexts while searching SRs through reusable parent contexts."""
    expanded: list[str] = []
    for code in work_contexts or []:
        if code not in expanded:
            expanded.append(code)
        for parent in WORK_CONTEXT_QUERY_EXPANSIONS.get(code, []):
            if parent not in expanded:
                expanded.append(parent)
    return expanded

# ═══ 배제 규칙 (모순 검출) ═══
EXCLUSION_RULES = [
    # SLIP은 FALL의 하위 → 동시 존재 시 FALL만 유지
    {"if_both": ("FALL", "SLIP"), "keep": "FALL", "axis": "accident_type"},
    # DUST는 CHEMICAL 하위 → 동시 존재 시 DUST 유지 (더 구체적)
    {"if_both": ("CHEMICAL", "DUST"), "keep": "DUST", "axis": "hazardous_agent"},
    {"if_both": ("CHEMICAL", "TOXIC"), "keep": "TOXIC", "axis": "hazardous_agent"},
    {"if_both": ("CHEMICAL", "CORROSION"), "keep": "CORROSION", "axis": "hazardous_agent"},
    {"if_both": ("ELECTRICITY", "ARC_FLASH"), "keep": "ARC_FLASH", "axis": "hazardous_agent"},
]


def apply_rules(
    normalized: dict,
    db: Optional[Session] = None,
    allow_context_only_inference: bool = False,
) -> dict:
    """결정론적 규칙 엔진.

    입력: normalize_faceted_hazards() 결과
    출력: {
        "accident_types": [...],
        "hazardous_agents": [...],
        "work_contexts": [...],
        "applied_rules": [...],    # 적용된 규칙 설명
        "confidence": float,       # 전체 신뢰도 (0~1)
    }
    """
    accident_types = list(normalized.get("accident_types", []))
    hazardous_agents = list(normalized.get("hazardous_agents", []))
    work_contexts = list(normalized.get("work_contexts", []))
    applied_rules = []

    # 1) 교차 추론 규칙 적용
    for rule in CROSS_INFERENCE_RULES:
        ctx = rule.get("if_context")
        if ctx and ctx not in work_contexts:
            continue

        if_agent = rule.get("if_agent")
        if if_agent and if_agent not in hazardous_agents:
            continue

        if (
            not allow_context_only_inference
            and ctx
            and not if_agent
            and not accident_types
            and not hazardous_agents
        ):
            continue

        implied_acc = rule.get("imply_accident")
        if implied_acc and implied_acc not in accident_types:
            accident_types.append(implied_acc)
            applied_rules.append(
                f"R-cross: {ctx} → +{implied_acc} (accident_type)"
            )

        implied_agent = rule.get("imply_agent")
        if implied_agent and implied_agent not in hazardous_agents:
            hazardous_agents.append(implied_agent)
            applied_rules.append(
                f"R-cross: {ctx}+{if_agent or ''} → +{implied_agent} (agent)"
            )

    # 2) 배제 규칙 (구체성 우선)
    for rule in EXCLUSION_RULES:
        a, b = rule["if_both"]
        keep = rule["keep"]
        axis = rule["axis"]
        target = accident_types if axis == "accident_type" else hazardous_agents

        if a in target and b in target:
            remove = a if keep == b else b
            target.remove(remove)
            applied_rules.append(
                f"R-exclude: {a}+{b} → keep {keep}, drop {remove}"
            )

    # 3) 신뢰도 계산
    total_codes = len(accident_types) + len(hazardous_agents) + len(work_contexts)
    unknown_count = len(normalized.get("unknown_codes", []))
    forced_count = len(normalized.get("forced_fit_notes", []))

    if total_codes == 0:
        confidence = 0.0
    else:
        # 기본 신뢰도: 코드 수에 비례, unknown/forced_fit에 페널티
        base = min(1.0, total_codes * 0.15 + 0.3)
        penalty = unknown_count * 0.1 + forced_count * 0.05
        confidence = max(0.0, min(1.0, base - penalty))

    result = {
        "accident_types": list(dict.fromkeys(accident_types)),
        "hazardous_agents": list(dict.fromkeys(hazardous_agents)),
        "work_contexts": list(dict.fromkeys(work_contexts)),
        "applied_rules": applied_rules,
        "confidence": round(confidence, 2),
    }

    if applied_rules:
        logger.info(f"[RuleEngine] 적용 규칙: {applied_rules}")

    return result


def query_sr_for_facets(
    db: Session,
    accident_types: list[str],
    hazardous_agents: list[str],
    work_contexts: list[str],
    limit: int = 50,
    industry_contexts: Optional[list[str]] = None,
) -> list[dict]:
    """Faceted codes → PG safety_requirements JSONB 쿼리.

    각 축 OR 매칭, 축 간 AND (최소 1축 이상 매칭).
    """
    from app.db.models import PgSafetyRequirement
    from sqlalchemy import or_

    industry_contexts = industry_contexts or []
    query_work_contexts = _expand_work_contexts_for_query(work_contexts)

    query = db.query(PgSafetyRequirement)
    conditions = []

    for code in accident_types:
        conditions.append(
            PgSafetyRequirement.accident_types.op("@>")(f'["{code}"]')
        )
    for code in hazardous_agents:
        conditions.append(
            PgSafetyRequirement.hazardous_agents.op("@>")(f'["{code}"]')
        )
    for code in query_work_contexts:
        conditions.append(
            PgSafetyRequirement.work_contexts.op("@>")(f'["{code}"]')
        )

    # 레거시 addresses_hazard도 fallback
    legacy_codes = accident_types + hazardous_agents + query_work_contexts
    for code in legacy_codes:
        conditions.append(
            PgSafetyRequirement.addresses_hazard.op("@>")(f'["{code}"]')
        )

    if not conditions:
        return []

    results = query.filter(or_(*conditions)).all()

    def _contains_any(values, codes):
        values = values or []
        return [code for code in codes if code in values]

    scored = []
    for sr in results:
        sr_accident_types = sr.accident_types or []
        sr_hazardous_agents = sr.hazardous_agents or []
        sr_work_contexts = sr.work_contexts or []
        sr_legacy = sr.addresses_hazard or []

        accident_hits = _contains_any(sr_accident_types, accident_types)
        agent_hits = _contains_any(sr_hazardous_agents, hazardous_agents)
        context_hits = _contains_any(sr_work_contexts, query_work_contexts)
        legacy_hits = _contains_any(sr_legacy, accident_types + hazardous_agents + query_work_contexts)
        matched_axes = sum(1 for hits in [accident_hits, agent_hits, context_hits] if hits)
        total_hits = len(set(accident_hits + agent_hits + context_hits + legacy_hits))
        industry_hints = sr.applicable_industry or []
        industry_adjustment, industry_alignment, _ = score_industry_alignment(
            industry_hints,
            industry_contexts,
        )
        score = 0.25 + matched_axes * 0.25 + total_hits * 0.05
        score = max(0.0, min(1.0, score + industry_adjustment))
        scored.append((score, matched_axes, total_hits, industry_alignment, sr))

    scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)

    return [
        {
            "identifier": sr.identifier,
            "title": sr.title,
            "text": sr.text,
            "binding_force": sr.binding_force,
            "accident_types": sr.accident_types or [],
            "hazardous_agents": sr.hazardous_agents or [],
            "work_contexts": sr.work_contexts or [],
            "applicable_industry": sr.applicable_industry or [],
            "industry_alignment": industry_alignment,
            "score": score,
            "matched_axes": matched_axes,
        }
        for score, matched_axes, _, industry_alignment, sr in scored[:limit]
    ]


def get_checklist_from_srs(
    db: Session,
    sr_ids: list[str],
    limit: int = 20,
) -> list[dict]:
    """SR IDs → ci_sr_mapping → checklist_items 조회."""
    from app.db.models import PgCiSrMapping, PgChecklistItem

    if not sr_ids:
        return []

    ci_ids = (
        db.query(PgCiSrMapping.ci_id)
        .filter(PgCiSrMapping.sr_id.in_(sr_ids))
        .limit(limit * 2)
        .all()
    )
    ci_id_list = [row[0] for row in ci_ids]

    if not ci_id_list:
        return []

    items = (
        db.query(PgChecklistItem)
        .filter(PgChecklistItem.identifier.in_(ci_id_list))
        .limit(limit)
        .all()
    )

    return [
        {
            "identifier": ci.identifier,
            "text": ci.text,
            "binding_force": ci.binding_force,
            "source_guide": ci.source_guide,
            "source_section": ci.source_section,
        }
        for ci in items
    ]


def get_guides_from_srs(
    db: Session,
    sr_ids: list[str],
    limit: int = 5,
    industry_contexts: Optional[list[str]] = None,
) -> list[dict]:
    """SR IDs → ci_sr_mapping → checklist_items.source_guide → kosha_guides 역추적.

    Faceted 코드로 찾은 SR에 연결된 KOSHA Guide를 반환.
    CI 연결 수가 많은 가이드일수록 관련도 높음.
    """
    from app.db.models import PgCiSrMapping, PgChecklistItem, PgKoshaGuide
    from sqlalchemy import func

    industry_contexts = industry_contexts or []

    if not sr_ids:
        return []

    # SR→CI→source_guide 그룹핑 (CI 연결 수 = relevance)
    guide_counts = (
        db.query(
            PgChecklistItem.source_guide,
            func.count(PgChecklistItem.identifier).label("ci_count"),
        )
        .join(PgCiSrMapping, PgCiSrMapping.ci_id == PgChecklistItem.identifier)
        .filter(PgCiSrMapping.sr_id.in_(sr_ids))
        .group_by(PgChecklistItem.source_guide)
        .order_by(func.count(PgChecklistItem.identifier).desc())
        .limit(limit)
        .all()
    )

    if not guide_counts:
        return []

    guide_codes = [row[0] for row in guide_counts]
    ci_count_map = {row[0]: row[1] for row in guide_counts}

    guides = (
        db.query(PgKoshaGuide)
        .filter(PgKoshaGuide.guide_code.in_(guide_codes))
        .all()
    )

    results = []
    for g in guides:
        ci_hits = ci_count_map.get(g.guide_code, 0)
        # CI 연결 수 기반 점수: 10+ → 0.95, 5+ → 0.90, 1+ → 0.85
        guide_industry = infer_industry_context(
            text=" ".join(filter(None, [g.title, g.sub_category])),
        )
        industry_adjustment, industry_alignment, _ = score_industry_alignment(
            guide_industry.active_industries,
            industry_contexts,
        )
        score = min(0.99, max(0.0, 0.80 + ci_hits * 0.02 + industry_adjustment))
        results.append({
            "guide_code": g.guide_code,
            "title": g.title,
            "classification": g.domain,
            "industry_hints": guide_industry.active_industries,
            "industry_alignment": industry_alignment,
            "relevant_sections": [],
            "relevance_score": score,
            "mapping_type": "sr_ci_link",
            "ci_hit_count": ci_hits,
        })

    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    logger.info(f"[SR→CI→Guide] {len(results)} guides found: {[r['guide_code'] for r in results]}")
    return results


async def enrich_sr_with_sparql(
    sr_results: list[dict],
    accident_types: list[str],
    hazardous_agents: list[str],
    work_contexts: list[str],
) -> dict:
    """PG SR 결과를 Fuseki SPARQL로 보강.

    단일 축이면 PG-only, 복합 축(2+)이면 Fuseki 교차 추론.
    Fuseki 장애 시 빈 보강 반환 (PG 결과 그대로 유지).
    """
    from app.integrations.sparql_client import sparql_client
    from app.integrations import sparql_queries as sq

    axis_count = sum(1 for a in [accident_types, hazardous_agents, work_contexts] if a)

    enrichment = {
        "source": "pg_only",
        "co_applicable_srs": [],
        "exemptions": [],
        "high_severity_srs": [],
        "fuseki_available": sparql_client.is_available(),
    }

    if axis_count < 2 or not sparql_client.is_available():
        return enrichment

    enrichment["source"] = "pg+sparql"
    sr_ids = [sr["identifier"] for sr in sr_results]

    # Q2: coApplicable SR discovery (for first 3 SRs)
    for sr_id in sr_ids[:3]:
        co_srs = await sparql_client.query(sq.q2_co_applicable_srs(sr_id), cache_ttl=300)
        for co in co_srs:
            if co.get("coSrId") and co["coSrId"] not in sr_ids:
                enrichment["co_applicable_srs"].append({
                    "sr_id": co["coSrId"],
                    "title": co.get("coSrTitle", ""),
                    "article_code": co.get("artCode", ""),
                    "discovered_via": sr_id,
                })

    # Q4: Exemption chain (for first 3 SRs)
    for sr_id in sr_ids[:3]:
        exemptions = await sparql_client.query(sq.q4_exemption_chain(sr_id), cache_ttl=300)
        for ex in exemptions:
            enrichment["exemptions"].append({
                "exempt_ns_id": ex.get("exemptNsId", ""),
                "article_code": ex.get("exemptArtCode", ""),
                "condition": ex.get("condition"),
                "applies_to_sr": sr_id,
            })

    # Q5: High-severity SRs
    high_srs = await sparql_client.query(sq.q5_high_severity_srs(min_severity=5), cache_ttl=600)
    matched_high = [
        {"sr_id": h["srId"], "severity": h.get("severity"), "penalty": h.get("penaltyDesc", "")}
        for h in high_srs
        if h.get("srId") in sr_ids
    ]
    enrichment["high_severity_srs"] = matched_high

    # Q6: Faceted cross-query for additional SRs (if multi-axis)
    if axis_count >= 2:
        sparql_srs = await sparql_client.query(
            sq.q6_faceted_cross_query(accident_types, hazardous_agents, work_contexts, limit=20),
            cache_ttl=300,
        )
        for s in sparql_srs:
            sid = s.get("srId")
            if sid and sid not in sr_ids and sid not in [c["sr_id"] for c in enrichment["co_applicable_srs"]]:
                enrichment["co_applicable_srs"].append({
                    "sr_id": sid,
                    "title": s.get("srTitle", ""),
                    "article_code": s.get("artCode", ""),
                    "discovered_via": "faceted_cross_query",
                })

    logger.info(
        f"[SPARQL] Enrichment: {len(enrichment['co_applicable_srs'])} co-applicable, "
        f"{len(enrichment['exemptions'])} exemptions, {len(enrichment['high_severity_srs'])} high-severity"
    )

    return enrichment


def _local_id(value) -> Optional[str]:
    if value is None:
        return None
    return str(value).rsplit("#", 1)[-1]


def _literal_text(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, Literal):
        return str(value)
    return str(value)


def _condition_label(subject_role: Optional[str], accident_outcome: Optional[str]) -> str:
    role_labels = {
        "Employer": "사업주",
        "Contractor": "수급인",
    }
    outcome_labels = {
        "SimpleViolation": "단순 위반 가능성",
        "Death": "사망 발생 시",
        "SeriousAccident": "중대재해 요건 충족 시",
    }
    role = role_labels.get(subject_role or "", subject_role or "주체 미정")
    outcome = outcome_labels.get(accident_outcome or "", accident_outcome or "결과 미정")
    return f"{role} - {outcome}"


def _ontology_instances_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "koshaontology"
        / "ontology"
        / "kosha-instances.ttl"
    )


def _penalty_rule_to_dict(graph: Graph, pr_uri: URIRef) -> dict:
    sanction_uri = graph.value(pr_uri, PEN.hasSanction)
    condition_uri = graph.value(pr_uri, PEN.hasCondition)
    subject_role = _local_id(graph.value(condition_uri, PEN.requiresSubjectRole)) if condition_uri else None
    accident_outcome = _local_id(graph.value(condition_uri, PEN.requiresAccidentOutcome)) if condition_uri else None
    sanction_type = None
    if sanction_uri:
        for type_uri in graph.objects(sanction_uri, RDF.type):
            sanction_type = _local_id(type_uri)
            break

    severity = graph.value(sanction_uri, PEN.severityScore) if sanction_uri else None
    try:
        severity_score = int(str(severity)) if severity is not None else None
    except ValueError:
        severity_score = None

    return {
        "penalty_rule_id": _local_id(pr_uri),
        "condition_label": _condition_label(subject_role, accident_outcome),
        "subject_role": subject_role,
        "accident_outcome": accident_outcome,
        "violated_norm_id": _local_id(graph.value(pr_uri, PEN.violatedNorm)),
        "violated_article_id": _local_id(graph.value(pr_uri, PEN.violatedArticle)),
        "delegated_from_article_id": _local_id(graph.value(pr_uri, PEN.delegatedFrom)),
        "penalty_article_id": _local_id(graph.value(pr_uri, PEN.penaltyArticle)),
        "sanction_type": sanction_type,
        "penalty_description": _literal_text(
            graph.value(sanction_uri, PEN.penaltyDescription) if sanction_uri else None
        ),
        "severity_score": severity_score,
        "basis_text": _literal_text(graph.value(pr_uri, PEN.penaltyBasisText)),
    }


def _load_penalty_index() -> dict:
    global _PENALTY_INDEX
    if _PENALTY_INDEX is not None:
        return _PENALTY_INDEX

    instances_path = _ontology_instances_path()
    if not instances_path.exists():
        logger.warning("[PenaltyCondition] instances TTL not found: %s", instances_path)
        _PENALTY_INDEX = {"sr_to_candidates": {}}
        return _PENALTY_INDEX

    graph = Graph()
    graph.parse(instances_path, format="turtle")

    sr_to_candidates: dict[str, list[dict]] = defaultdict(list)
    for sr_uri, ns_uri in graph.subject_objects(SR.derivedFromNS):
        sr_id = _local_id(sr_uri)
        if not sr_id:
            continue
        for pr_uri in graph.objects(ns_uri, PEN.hasPenaltyRule):
            candidate = _penalty_rule_to_dict(graph, pr_uri)
            sr_to_candidates[sr_id].append(candidate)

    _PENALTY_INDEX = {"sr_to_candidates": dict(sr_to_candidates)}
    logger.info(
        "[PenaltyCondition] loaded %s SR penalty mappings from %s",
        len(sr_to_candidates),
        instances_path,
    )
    return _PENALTY_INDEX


def get_penalty_candidates_for_srs(
    sr_ids: list[str],
    direct_sr_ids: Optional[list[str]] = None,
    limit: int = 80,
) -> list[dict]:
    """Return condition-aware penalty candidates for SR IDs.

    direct_sr_ids should contain SRs reached through strong evidence such as a
    matched SHE pattern. SimpleViolation rules from other broad candidates are
    still exposed, but only as conditional candidates.
    """
    if not sr_ids:
        return []

    index = _load_penalty_index()
    sr_to_candidates = index.get("sr_to_candidates", {})
    direct_set = set(direct_sr_ids or [])
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for sr_id in sr_ids:
        for candidate in sr_to_candidates.get(sr_id, []):
            key = (sr_id, candidate.get("penalty_rule_id") or "")
            if key in seen:
                continue
            seen.add(key)
            item = dict(candidate)
            item["source_sr_id"] = sr_id
            if item.get("accident_outcome") == "SimpleViolation" and sr_id in direct_set:
                item["exposure_type"] = "direct_candidate"
            else:
                item["exposure_type"] = "conditional"
            results.append(item)

    results.sort(
        key=lambda item: (
            0 if item.get("exposure_type") == "direct_candidate" else 1,
            -(item.get("severity_score") or 0),
            item.get("penalty_rule_id") or "",
        )
    )
    return results[:limit]


PENALTY_PATH_CONFIG = {
    "SimpleViolation": {
        "path_type": "general_incident",
        "title": "일반 위반 또는 일반 산재 발생 시",
        "order": 0,
    },
    "Death": {
        "path_type": "death",
        "title": "사망 발생 시",
        "order": 1,
    },
    "SeriousAccident": {
        "path_type": "serious_accident",
        "title": "중대재해 요건 충족 시",
        "order": 2,
    },
}


def _unique_values(values: list[Optional[str]]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _penalty_path_summary(path_type: str, notice_level: str) -> str:
    if path_type == "general_incident":
        if notice_level == "photo_based":
            return (
                "사진상 확인된 위험요소가 개선되지 않으면 일반 위반 또는 일반 산재 관련 "
                "벌칙 문제가 될 수 있습니다."
            )
        return (
            "사진만으로 위반 주체나 모든 사실관계를 확정할 수 없으므로, 일반 위반 또는 "
            "일반 산재 가능성으로 안내합니다."
        )
    if path_type == "death":
        return "사진만으로 확정할 수 없지만, 사고가 사망으로 이어진 경우 적용될 수 있는 벌칙 경로입니다."
    if path_type == "serious_accident":
        return "사진만으로 확정할 수 없지만, 중대재해처벌법상 요건이 충족되는 경우 검토될 수 있는 벌칙 경로입니다."
    return "추가 사실 확인이 필요한 벌칙 안내 경로입니다."


def _article_refs_for_path(items: list[dict]) -> list[dict]:
    refs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    ref_fields = [
        ("violated_article_id", "violated_article", "위반 조문"),
        ("delegated_from_article_id", "delegated_from", "위임 근거 조문"),
        ("penalty_article_id", "penalty_article", "실제 벌칙 조문"),
    ]
    for item in items:
        for field, ref_type, label in ref_fields:
            article_id = item.get(field)
            if not article_id:
                continue
            key = (ref_type, article_id)
            if key in seen:
                continue
            seen.add(key)
            refs.append({
                "ref_type": ref_type,
                "label": label,
                "article_id": article_id,
            })
    return refs


def build_penalty_paths(candidates: list[dict], finding_status: str = "not_determined") -> list[dict]:
    """Group detailed PenaltyRule candidates into three business-facing paths."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        outcome = candidate.get("accident_outcome")
        if outcome in PENALTY_PATH_CONFIG:
            grouped[outcome].append(candidate)

    paths: list[dict] = []
    for outcome, config in PENALTY_PATH_CONFIG.items():
        items = grouped.get(outcome, [])
        if not items:
            continue

        path_type = config["path_type"]
        direct_general = (
            outcome == "SimpleViolation"
            and finding_status in {"confirmed", "suspected"}
            and any(item.get("exposure_type") == "direct_candidate" for item in items)
        )
        if outcome == "SimpleViolation":
            notice_level = "photo_based" if direct_general else "conditional"
        else:
            notice_level = "external_fact_required"

        paths.append({
            "path_type": path_type,
            "title": config["title"],
            "notice_level": notice_level,
            "summary": _penalty_path_summary(path_type, notice_level),
            "penalty_rule_ids": _unique_values([item.get("penalty_rule_id") for item in items]),
            "penalty_descriptions": _unique_values([item.get("penalty_description") for item in items]),
            "article_refs": _article_refs_for_path(items),
            "max_severity_score": max(
                [item.get("severity_score") or 0 for item in items],
                default=0,
            ) or None,
            "source_sr_ids": _unique_values([item.get("source_sr_id") for item in items]),
        })

    paths.sort(key=lambda item: PENALTY_PATH_CONFIG[
        "SimpleViolation" if item["path_type"] == "general_incident"
        else "Death" if item["path_type"] == "death"
        else "SeriousAccident"
    ]["order"])
    return paths


def summarize_penalty_candidates(candidates: list[dict]) -> list[dict]:
    """Build legacy PenaltyInfo-compatible rows from PenaltyRule candidates."""
    summaries: dict[str, dict] = {}
    for item in candidates:
        article_code = item.get("penalty_article_id") or item.get("violated_article_id") or ""
        if not article_code:
            continue
        summary = summaries.setdefault(
            article_code,
            {
                "article_code": article_code,
                "title": item.get("basis_text") or article_code,
                "criminal_employer_penalty": None,
                "criminal_death_penalty": None,
                "admin_max_fine": None,
            },
        )
        desc = item.get("penalty_description")
        if not desc:
            continue
        if item.get("accident_outcome") == "Death":
            summary["criminal_death_penalty"] = summary["criminal_death_penalty"] or desc
        elif item.get("sanction_type") == "AdministrativeFine":
            summary["admin_max_fine"] = summary["admin_max_fine"] or desc
        elif item.get("subject_role") == "Employer":
            summary["criminal_employer_penalty"] = summary["criminal_employer_penalty"] or desc
    return list(summaries.values())


def get_penalties_for_srs(
    db: Session,
    sr_ids: list[str],
) -> list[dict]:
    """SR IDs -> sr_article_mapping -> norm_statements.has_sanction 조회."""
    from app.db.models import PgArticle, PgNormStatement, PgSrArticleMapping

    if not sr_ids:
        return []

    mappings = (
        db.query(PgSrArticleMapping)
        .filter(PgSrArticleMapping.sr_id.in_(sr_ids))
        .all()
    )

    penalties = []
    seen = set()
    for m in mappings:
        key = (m.law_type, m.article_code)
        if key in seen:
            continue
        seen.add(key)

        article = (
            db.query(PgArticle)
            .filter(
                PgArticle.law_type == m.law_type,
                PgArticle.article_code == m.article_code,
            )
            .first()
        )
        norm_statements = (
            db.query(PgNormStatement)
            .filter(
                PgNormStatement.law_id == m.law_type,
                PgNormStatement.article_code == m.article_code,
                PgNormStatement.has_sanction.isnot(None),
            )
            .all()
        )

        penalty = {
            "article_code": m.article_code,
            "title": article.title if article else m.article_code,
            "criminal_employer_penalty": None,
            "criminal_death_penalty": None,
            "criminal_serious_death": None,
            "criminal_serious_injury": None,
            "admin_max_fine": None,
        }
        for ns in norm_statements:
            sanction = ns.has_sanction or {}
            criminal = sanction.get("criminal") or {}
            employer = criminal.get("violation_employer") or {}
            death = criminal.get("death") or {}
            serious = criminal.get("seriousAccident") or {}
            admin = sanction.get("administrative") or sanction.get("admin") or {}

            penalty["criminal_employer_penalty"] = (
                penalty["criminal_employer_penalty"] or employer.get("penalty")
            )
            penalty["criminal_death_penalty"] = (
                penalty["criminal_death_penalty"]
                or death.get("penalty")
                or death.get("death")
            )
            penalty["criminal_serious_death"] = (
                penalty["criminal_serious_death"] or serious.get("death")
            )
            penalty["criminal_serious_injury"] = (
                penalty["criminal_serious_injury"] or serious.get("injury")
            )
            penalty["admin_max_fine"] = (
                penalty["admin_max_fine"]
                or admin.get("max_fine")
                or admin.get("penalty")
            )

        if any(v for k, v in penalty.items() if k not in {"article_code", "title"}):
            penalties.append(penalty)

    return penalties
