"""Deterministic Rule Engine — Track B 정규화 결과를 최종 canonical codes로 확정.

결정론적 보장: 동일 입력 → 동일 출력.
점수 기반 확정 + 교차 추론 규칙 적용.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

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
) -> list[dict]:
    """Faceted codes → PG safety_requirements JSONB 쿼리.

    각 축 OR 매칭, 축 간 AND (최소 1축 이상 매칭).
    """
    from app.db.models import PgSafetyRequirement
    from sqlalchemy import or_, cast, String

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
    for code in work_contexts:
        conditions.append(
            PgSafetyRequirement.work_contexts.op("@>")(f'["{code}"]')
        )

    # 레거시 addresses_hazard도 fallback
    legacy_codes = accident_types + hazardous_agents + work_contexts
    for code in legacy_codes:
        conditions.append(
            PgSafetyRequirement.addresses_hazard.op("@>")(f'["{code}"]')
        )

    if not conditions:
        return []

    results = query.filter(or_(*conditions)).limit(limit).all()

    return [
        {
            "identifier": sr.identifier,
            "title": sr.title,
            "text": sr.text,
            "binding_force": sr.binding_force,
            "accident_types": sr.accident_types or [],
            "hazardous_agents": sr.hazardous_agents or [],
            "work_contexts": sr.work_contexts or [],
        }
        for sr in results
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
) -> list[dict]:
    """SR IDs → ci_sr_mapping → checklist_items.source_guide → kosha_guides 역추적.

    Faceted 코드로 찾은 SR에 연결된 KOSHA Guide를 반환.
    CI 연결 수가 많은 가이드일수록 관련도 높음.
    """
    from app.db.models import PgCiSrMapping, PgChecklistItem, PgKoshaGuide
    from sqlalchemy import func

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
        score = min(0.97, 0.80 + ci_hits * 0.02)
        results.append({
            "guide_code": g.guide_code,
            "title": g.title,
            "classification": g.domain,
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


def get_penalties_for_srs(
    db: Session,
    sr_ids: list[str],
) -> list[dict]:
    """SR IDs → sr_article_mapping → penalty_routes 조회."""
    from app.db.models import PgSrArticleMapping, PgPenaltyRoute

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

        route = (
            db.query(PgPenaltyRoute)
            .filter(
                PgPenaltyRoute.law_type == m.law_type,
                PgPenaltyRoute.article_code == m.article_code,
            )
            .first()
        )
        if route and route.has_penalty:
            penalties.append({
                "article_code": route.article_code,
                "title": route.title,
                "criminal_employer_penalty": route.criminal_employer_penalty,
                "criminal_death_penalty": route.criminal_death_penalty,
                "criminal_serious_death": route.criminal_serious_death,
                "criminal_serious_injury": route.criminal_serious_injury,
                "admin_max_fine": route.admin_max_fine,
            })

    return penalties
