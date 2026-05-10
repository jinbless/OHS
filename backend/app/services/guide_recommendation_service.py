"""Guide, WorkProcess, and checklist recommendation facade."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    PgChecklistItem,
    PgCiSrMapping,
    PgGuideEntityFeatureCandidate,
    PgGuideSrLinkCandidate,
    PgGuideVisualTriggerCandidate,
    PgKoshaGuide,
    PgWorkProcess,
    PgWpSrMapping,
)
from app.services import hazard_rule_engine
from app.services.broad_sr_policy import (
    fallback_sr_ids,
    get_broad_sr_ids,
    get_secondary_score_multiplier,
    usable_primary_sr_ids,
)
from app.services.guide_domain_profile import evaluate_guide_domain_profile, get_guide_domain_profile
from app.services.industry_context import infer_industry_context, score_industry_alignment


SERVING_CONFIDENCE = 0.65
SERVING_REVIEW_STATUSES = ("candidate", "asserted")
GENERIC_FEATURE_CODES = {
    "GENERAL_WORKPLACE",
    "CHEMICAL",
    "CHEMICAL_EXPOSURE",
    "CHEMICAL_WORK",
    "FIRE",
    "EXPLOSION",
    "FIRE_EXPLOSION",
    "ELECTRICAL_WORK",
    "ELECTRICITY",
    "MACHINE",
    "ERGONOMIC",
    "VENTILATION_POOR",
}
BROAD_FEATURE_CODES = {
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
}
REFERENCE_PROCEDURE_ROLES = {
    "measurement_analysis",
    "test_protocol",
    "health_screening",
    "risk_method",
    "document_reference",
    "management_program",
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def _risk_feature_codes(risk_features: list[Any] | None) -> dict[str, set[str]]:
    result = {"accident_type": set(), "hazardous_agent": set(), "work_context": set()}
    for feature in risk_features or []:
        axis = getattr(feature, "axis", None) or (feature.get("axis") if isinstance(feature, dict) else None)
        code = getattr(feature, "code", None) or (feature.get("code") if isinstance(feature, dict) else None)
        if axis in result and code:
            result[axis].add(code)
    return result


def _flat_feature_codes(risk_features: list[Any] | None) -> list[str]:
    codes = []
    for values in _risk_feature_codes(risk_features).values():
        codes.extend(sorted(values))
    return _unique(codes)


def _she_ci_ids(she_matches: list[Any] | None) -> list[str]:
    ci_ids = []
    for match in she_matches or []:
        ci_ids.extend(list(getattr(match, "applies_ci_ids", []) or []))
    return _unique(ci_ids)


def _she_source_guides(she_matches: list[Any] | None) -> list[str]:
    guides = []
    for match in she_matches or []:
        guides.extend(list(getattr(match, "source_guides", []) or []))
    return _unique(guides)


def _visual_bonus(text: str, visual_cues: list[str] | None) -> float:
    if not text or not visual_cues:
        return 0.0
    lower = text.lower()
    hits = sum(1 for cue in visual_cues if cue and cue.lower() in lower)
    return min(0.15, hits * 0.05)


def _is_broad_secondary(sr_id: str | None, broad_sr_ids: set[str], direct_sr_ids: set[str]) -> bool:
    return bool(sr_id and sr_id in broad_sr_ids and sr_id not in direct_sr_ids)


def _non_generic_feature(feature_code: str | None) -> bool:
    return bool(feature_code and feature_code not in GENERIC_FEATURE_CODES)


def _guide_specific_feature(feature_code: str | None) -> bool:
    return bool(_non_generic_feature(feature_code) and feature_code not in BROAD_FEATURE_CODES)


def _context_blob(visual_cues: list[str] | None, context_text: str | None) -> str:
    return " ".join([*(visual_cues or []), context_text or ""]).lower()


def _matches_visual_trigger(candidate: PgGuideVisualTriggerCandidate, context_blob: str) -> bool:
    if not context_blob:
        return False
    for value in (candidate.trigger_text, candidate.evidence):
        lowered = (value or "").lower()
        if lowered and lowered in context_blob:
            return True
    return False


def _domain_profile_text(
    guide: PgKoshaGuide | None,
    work_processes: list[PgWorkProcess] | None = None,
    profile_bits: list[str] | None = None,
) -> str:
    bits = []
    if guide:
        bits.extend([guide.title or "", guide.sub_category or ""])
    for wp in (work_processes or [])[:8]:
        bits.extend([wp.process_name or "", wp.safety_measures or "", wp.source_section or ""])
    bits.extend(profile_bits or [])
    return " ".join(bits)


def _guide_candidate_profile_bits(db: Session, guide_codes: list[str]) -> dict[str, list[str]]:
    if not guide_codes:
        return {}
    bits: dict[str, list[str]] = defaultdict(list)
    try:
        feature_rows = (
            db.query(
                PgGuideEntityFeatureCandidate.guide_code,
                PgGuideEntityFeatureCandidate.feature_code,
                PgGuideEntityFeatureCandidate.evidence,
            )
            .filter(PgGuideEntityFeatureCandidate.guide_code.in_(guide_codes))
            .filter(PgGuideEntityFeatureCandidate.confidence >= SERVING_CONFIDENCE)
            .filter(PgGuideEntityFeatureCandidate.review_status.in_(SERVING_REVIEW_STATUSES))
            .limit(max(120, len(guide_codes) * 10))
            .all()
        )
        for guide_code, feature_code, evidence in feature_rows:
            bits[guide_code].extend([feature_code or "", evidence or ""])

        trigger_rows = (
            db.query(
                PgGuideVisualTriggerCandidate.guide_code,
                PgGuideVisualTriggerCandidate.trigger_text,
                PgGuideVisualTriggerCandidate.evidence,
            )
            .filter(PgGuideVisualTriggerCandidate.guide_code.in_(guide_codes))
            .filter(PgGuideVisualTriggerCandidate.confidence >= SERVING_CONFIDENCE)
            .filter(PgGuideVisualTriggerCandidate.review_status.in_(SERVING_REVIEW_STATUSES))
            .limit(max(120, len(guide_codes) * 10))
            .all()
        )
        for guide_code, trigger_text, evidence in trigger_rows:
            bits[guide_code].extend([trigger_text or "", evidence or ""])
    except SQLAlchemyError:
        db.rollback()
    return bits



def _manual_profile_terms(profile: dict | None) -> list[str]:
    if not profile:
        return []
    boundary = profile.get("recommendation_boundary") or {}
    terms: list[str] = []
    for key in (
        "required_context_terms",
        "visual_triggers",
        "industry_alignment",
        "intended_workplaces",
        "intended_tasks",
        "observable_required_cues",
    ):
        values = profile.get(key) or []
        if isinstance(values, list):
            terms.extend(str(value) for value in values if value)
    terms.extend(str(value) for value in (boundary.get("include_when") or []) if value)
    return _unique(terms)


def _term_hits(text: str, terms: list[str], limit: int = 3) -> list[str]:
    hits: list[str] = []
    lowered_text = (text or "").lower()
    for term in terms:
        lowered = term.lower()
        if lowered and lowered in lowered_text and term not in hits:
            hits.append(term)
        if len(hits) >= limit:
            break
    return hits


def _score_usage_profile(
    profile: dict | None,
    *,
    visual_cues: list[str] | None,
    context_text: str | None,
    feature_codes: list[str],
    industry_contexts: list[str] | None,
) -> tuple[float, list[str], bool]:
    if not profile:
        return 0.0, [], False
    context = _context_blob(visual_cues, context_text)
    profile_terms = _manual_profile_terms(profile)
    term_hits = _term_hits(context, profile_terms, limit=4)
    profile_feature_codes = set(profile.get("feature_codes") or [])
    feature_hits = sorted(set(feature_codes) & profile_feature_codes)
    non_generic_feature_hits = [code for code in feature_hits if _guide_specific_feature(code)]
    industry_hits = _term_hits(
        " ".join([*(industry_contexts or []), context_text or ""]).lower(),
        [str(value) for value in (profile.get("industry_alignment") or []) if value],
        limit=2,
    )
    role = str(profile.get("procedure_role") or "field_control")
    if role in REFERENCE_PROCEDURE_ROLES and not (term_hits or industry_hits):
        return 0.0, [], False
    if str(profile.get("profile_level") or "general") == "exclusive" and not term_hits:
        return 0.0, [], False
    if not (term_hits or non_generic_feature_hits):
        return 0.0, [], False

    score = min(
        0.32,
        len(term_hits) * 0.045
        + len(non_generic_feature_hits) * 0.055
        + len(industry_hits) * 0.025,
    )
    if score <= 0:
        return 0.0, [], False
    reasons = []
    if term_hits:
        reasons.append(f"usage profile terms:{','.join(term_hits[:2])}")
    if non_generic_feature_hits:
        reasons.append(f"usage profile features:{','.join(non_generic_feature_hits[:2])}")
    if industry_hits:
        reasons.append(f"usage profile industry:{','.join(industry_hits[:2])}")
    return score, reasons, bool(term_hits or non_generic_feature_hits or industry_hits)



def _reference_role_context_hit(profile: dict | None, visual_cues: list[str] | None, context_text: str | None) -> bool:
    if not profile:
        return True
    role = str(profile.get("procedure_role") or "field_control")
    if role not in REFERENCE_PROCEDURE_ROLES:
        return True
    role_terms = {
        "measurement_analysis": ["작업환경측정", "분석", "시료", "검량선", "측정", "분석기", "계측", "모니터링"],
        "test_protocol": ["시험", "독성시험", "평가시험", "실험", "프로토콜"],
        "health_screening": ["건강진단", "검진", "의학적", "문진", "검사"],
        "risk_method": ["위험성평가", "평가 방법", "리스크 평가", "체크리스트 방법"],
        "document_reference": ["문서", "양식", "기록", "보고서", "매뉴얼"],
        "management_program": ["계획", "계획서", "프로그램", "절차서", "관리방안", "비상대피", "비상조치"],
    }.get(role, [])
    return bool(_term_hits(_context_blob(visual_cues, context_text), role_terms, limit=1))

def _rank_work_processes(
    work_processes: list[PgWorkProcess],
    *,
    profile: dict | None,
    visual_cues: list[str] | None,
    context_text: str | None,
    wp_sr_map: dict[str, set[str]],
) -> list[PgWorkProcess]:
    if not work_processes:
        return []
    primary_ids = set((profile or {}).get("primary_work_process_ids") or [])
    profile_terms = _manual_profile_terms(profile)
    context = _context_blob(visual_cues, context_text)
    ranked: list[tuple[float, int, PgWorkProcess]] = []
    for index, wp in enumerate(work_processes):
        wp_text = " ".join(filter(None, [wp.process_name, wp.safety_measures, wp.source_section])).lower()
        score = 0.0
        if wp.identifier in primary_ids:
            score += 1.2
        if wp_sr_map.get(wp.identifier):
            score += 0.7
        score += min(0.45, len(_term_hits(wp_text, profile_terms, limit=6)) * 0.075)
        score += min(0.35, len(_term_hits(context, [wp.process_name or "", wp.source_section or ""], limit=4)) * 0.08)
        ranked.append((score, int(wp.process_order or index + 1), wp))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [wp for _, _, wp in ranked]

def get_immediate_checklist_items(
    db: Session,
    sr_ids: list[str],
    direct_sr_ids: list[str] | None = None,
    limit: int = 12,
    risk_features: list[Any] | None = None,
    she_matches: list[Any] | None = None,
    visual_cues: list[str] | None = None,
    industry_contexts: list[str] | None = None,
    context_text: str | None = None,
) -> list[dict]:
    """Return immediate actions with SHE/SR/feature evidence scoring.

    Existing asserted CI→SR rows remain the strongest source. Candidate rows
    improve recall but keep their confidence/evidence separate.
    """
    if not sr_ids and not she_matches and not risk_features:
        return []

    scores: dict[str, float] = defaultdict(float)
    sr_by_ci: dict[str, set[str]] = defaultdict(set)
    evidence_by_ci: dict[str, list[str]] = defaultdict(list)
    ci_rows: dict[str, PgChecklistItem] = {}
    direct_sr_set = set(direct_sr_ids or [])
    broad_sr_ids = get_broad_sr_ids()
    broad_multiplier = get_secondary_score_multiplier()
    pending_broad_scores: dict[str, float] = defaultdict(float)
    pending_broad_sr_by_ci: dict[str, set[str]] = defaultdict(set)
    pending_broad_evidence: dict[str, list[str]] = defaultdict(list)
    pending_broad_rows: dict[str, PgChecklistItem] = {}
    guide_specific_ci_ids: set[str] = set()
    pending_generic_feature_scores: dict[str, float] = defaultdict(float)
    pending_generic_feature_evidence: dict[str, list[str]] = defaultdict(list)
    pending_generic_feature_rows: dict[str, PgChecklistItem] = {}

    if sr_ids:
        rows = (
            db.query(PgChecklistItem, PgCiSrMapping.sr_id)
            .join(PgCiSrMapping, PgCiSrMapping.ci_id == PgChecklistItem.identifier)
            .filter(PgCiSrMapping.sr_id.in_(sr_ids))
            .limit(limit * 6)
            .all()
        )
        for ci, sr_id in rows:
            if _is_broad_secondary(sr_id, broad_sr_ids, direct_sr_set):
                pending_broad_rows[ci.identifier] = ci
                pending_broad_sr_by_ci[ci.identifier].add(sr_id)
                pending_broad_scores[ci.identifier] += 0.85 * broad_multiplier
                pending_broad_evidence[ci.identifier].append("broad asserted CI-SR")
                continue
            ci_rows[ci.identifier] = ci
            sr_by_ci[ci.identifier].add(sr_id)
            scores[ci.identifier] += 0.85 * (broad_multiplier if sr_id in broad_sr_ids else 1.0)
            evidence_by_ci[ci.identifier].append("asserted CI-SR")
            guide_specific_ci_ids.add(ci.identifier)

    she_ids = _she_ci_ids(she_matches)
    if she_ids:
        for ci in (
            db.query(PgChecklistItem)
            .filter(PgChecklistItem.identifier.in_(she_ids))
            .limit(limit * 3)
            .all()
        ):
            ci_rows[ci.identifier] = ci
            scores[ci.identifier] += 1.0
            evidence_by_ci[ci.identifier].append("SHE related checklist cue")
            guide_specific_ci_ids.add(ci.identifier)

    feature_codes = _flat_feature_codes(risk_features)
    try:
        if sr_ids:
            candidate_rows = (
                db.query(PgChecklistItem, PgGuideSrLinkCandidate)
                .join(PgGuideSrLinkCandidate, PgGuideSrLinkCandidate.entity_id == PgChecklistItem.identifier)
                .filter(PgGuideSrLinkCandidate.entity_type == "CI")
                .filter(PgGuideSrLinkCandidate.sr_id.in_(sr_ids))
                .filter(PgGuideSrLinkCandidate.confidence >= SERVING_CONFIDENCE)
                .filter(PgGuideSrLinkCandidate.review_status.in_(SERVING_REVIEW_STATUSES))
                .limit(limit * 6)
                .all()
            )
            for ci, candidate in candidate_rows:
                if _is_broad_secondary(candidate.sr_id, broad_sr_ids, direct_sr_set):
                    pending_broad_rows[ci.identifier] = ci
                    pending_broad_sr_by_ci[ci.identifier].add(candidate.sr_id)
                    pending_broad_scores[ci.identifier] += float(candidate.confidence or 0) * 0.8 * broad_multiplier
                    pending_broad_evidence[ci.identifier].append(candidate.evidence)
                    continue
                ci_rows[ci.identifier] = ci
                sr_by_ci[ci.identifier].add(candidate.sr_id)
                multiplier = broad_multiplier if candidate.sr_id in broad_sr_ids else 1.0
                scores[ci.identifier] += float(candidate.confidence or 0) * 0.8 * multiplier
                evidence_by_ci[ci.identifier].append(candidate.evidence)
                guide_specific_ci_ids.add(ci.identifier)

        if feature_codes:
            feature_rows = (
                db.query(PgChecklistItem, PgGuideEntityFeatureCandidate)
                .join(PgGuideEntityFeatureCandidate, PgGuideEntityFeatureCandidate.entity_id == PgChecklistItem.identifier)
                .filter(PgGuideEntityFeatureCandidate.entity_type == "CI")
                .filter(PgGuideEntityFeatureCandidate.feature_code.in_(feature_codes))
                .filter(PgGuideEntityFeatureCandidate.confidence >= SERVING_CONFIDENCE)
                .filter(PgGuideEntityFeatureCandidate.review_status.in_(SERVING_REVIEW_STATUSES))
                .limit(limit * 8)
                .all()
            )
            for ci, candidate in feature_rows:
                if _guide_specific_feature(candidate.feature_code):
                    ci_rows[ci.identifier] = ci
                    scores[ci.identifier] += float(candidate.confidence or 0) * 0.25
                    evidence_by_ci[ci.identifier].append(candidate.evidence)
                    guide_specific_ci_ids.add(ci.identifier)
                    continue
                pending_generic_feature_rows[ci.identifier] = ci
                pending_generic_feature_scores[ci.identifier] += float(candidate.confidence or 0) * 0.12
                pending_generic_feature_evidence[ci.identifier].append(candidate.evidence)
    except SQLAlchemyError:
        db.rollback()

    for identifier, pending_score in pending_generic_feature_scores.items():
        if identifier not in guide_specific_ci_ids and scores.get(identifier, 0.0) <= 0:
            continue
        ci_rows[identifier] = ci_rows.get(identifier) or pending_generic_feature_rows[identifier]
        scores[identifier] += pending_score
        evidence_by_ci[identifier].extend(pending_generic_feature_evidence.get(identifier, []))

    for identifier, pending_score in pending_broad_scores.items():
        if identifier not in guide_specific_ci_ids and scores.get(identifier, 0.0) <= 0:
            continue
        ci_rows[identifier] = ci_rows.get(identifier) or pending_broad_rows[identifier]
        scores[identifier] += pending_score
        sr_by_ci[identifier].update(pending_broad_sr_by_ci.get(identifier, set()))
        evidence_by_ci[identifier].extend(pending_broad_evidence.get(identifier, []))

    safe_fallback_sr_ids = fallback_sr_ids(sr_ids)
    if not ci_rows and safe_fallback_sr_ids:
        return hazard_rule_engine.get_checklist_from_srs(db, safe_fallback_sr_ids, limit=limit)

    ranked = []
    for identifier, ci in ci_rows.items():
        score = scores[identifier] + _visual_bonus(ci.text or "", visual_cues)
        ranked.append((score, identifier, ci))
    ranked.sort(key=lambda row: row[0], reverse=True)

    source_guides = _unique([ci.source_guide for _, _, ci in ranked if ci.source_guide])
    guides = (
        {
            guide.guide_code: guide
            for guide in db.query(PgKoshaGuide).filter(PgKoshaGuide.guide_code.in_(source_guides)).all()
        }
        if source_guides
        else {}
    )
    profile_bits = _guide_candidate_profile_bits(db, source_guides)

    results = []
    for score, identifier, ci in ranked:
        guide = guides.get(ci.source_guide)
        domain_decision = evaluate_guide_domain_profile(
            guide_code=ci.source_guide,
            title=guide.title if guide else None,
            profile_text=_domain_profile_text(guide, profile_bits=profile_bits.get(ci.source_guide, [])),
            industry_contexts=industry_contexts,
            risk_feature_codes=feature_codes,
            visual_cues=visual_cues,
            context_text=context_text,
        )
        if domain_decision.exclude:
            continue
        results.append({
            "identifier": ci.identifier,
            "text": ci.text,
            "binding_force": ci.binding_force,
            "source_guide": ci.source_guide,
            "source_section": ci.source_section,
            "source_sr_ids": sorted(sr_by_ci.get(identifier, set())),
            "relevance_score": round(min(0.99, score / 2.0), 4),
            "evidence_summary": "; ".join(_unique(evidence_by_ci.get(identifier, []))[:3]),
        })
        if len(results) >= limit:
            break
    return results


def get_standard_guides(
    db: Session,
    sr_ids: list[str],
    direct_sr_ids: list[str] | None = None,
    limit: int = 6,
    industry_contexts: list[str] | None = None,
    risk_features: list[Any] | None = None,
    she_matches: list[Any] | None = None,
    visual_cues: list[str] | None = None,
    context_text: str | None = None,
) -> list[dict]:
    """Return Guide recommendations centered on WorkProcess steps."""
    industry_contexts = industry_contexts or []
    guide_scores: dict[str, float] = defaultdict(float)
    guide_reasons: dict[str, list[str]] = defaultdict(list)
    wp_sr_map: dict[str, set[str]] = defaultdict(set)
    feature_codes = _flat_feature_codes(risk_features)
    direct_sr_set = set(direct_sr_ids or [])
    broad_sr_ids = get_broad_sr_ids()
    broad_multiplier = get_secondary_score_multiplier()
    primary_sr_ids = usable_primary_sr_ids(sr_ids, direct_sr_ids)
    safe_fallback_sr_ids = fallback_sr_ids(sr_ids)
    pending_broad_scores: dict[str, float] = defaultdict(float)
    pending_broad_reasons: dict[str, list[str]] = defaultdict(list)
    pending_broad_wp_sr_map: dict[str, set[str]] = defaultdict(set)
    pending_broad_wp_source: dict[str, str] = {}
    pending_generic_feature_scores: dict[str, float] = defaultdict(float)
    pending_generic_feature_reasons: dict[str, list[str]] = defaultdict(list)
    guide_specific_signals: set[str] = set()
    context_blob = _context_blob(visual_cues, context_text)
    she_source_guides = _she_source_guides(she_matches)
    if not sr_ids and not she_source_guides:
        return []

    for guide_code in she_source_guides:
        guide_scores[guide_code] += 1.0
        guide_reasons[guide_code].append("SHE source guide")
        guide_specific_signals.add(guide_code)

    if sr_ids:
        rows = (
            db.query(PgWorkProcess, PgWpSrMapping.sr_id)
            .join(PgWpSrMapping, PgWpSrMapping.wp_id == PgWorkProcess.identifier)
            .filter(PgWpSrMapping.sr_id.in_(sr_ids))
            .limit(limit * 20)
            .all()
        )
        for wp, sr_id in rows:
            if _is_broad_secondary(sr_id, broad_sr_ids, direct_sr_set):
                pending_broad_scores[wp.source_guide] += 0.35 * broad_multiplier
                pending_broad_reasons[wp.source_guide].append("broad asserted WP-SR")
                pending_broad_wp_sr_map[wp.identifier].add(sr_id)
                pending_broad_wp_source[wp.identifier] = wp.source_guide
                continue
            guide_scores[wp.source_guide] += 0.35 * (broad_multiplier if sr_id in broad_sr_ids else 1.0)
            guide_reasons[wp.source_guide].append("asserted WP-SR")
            wp_sr_map[wp.identifier].add(sr_id)
            guide_specific_signals.add(wp.source_guide)

    try:
        if sr_ids:
            candidate_rows = (
                db.query(PgGuideSrLinkCandidate)
                .filter(PgGuideSrLinkCandidate.entity_type.in_(["WP", "GUIDE", "CI"]))
                .filter(PgGuideSrLinkCandidate.sr_id.in_(sr_ids))
                .filter(PgGuideSrLinkCandidate.confidence >= SERVING_CONFIDENCE)
                .filter(PgGuideSrLinkCandidate.review_status.in_(SERVING_REVIEW_STATUSES))
                .limit(limit * 30)
                .all()
            )
            for candidate in candidate_rows:
                weight = 0.34 if candidate.entity_type == "WP" else 0.18
                if _is_broad_secondary(candidate.sr_id, broad_sr_ids, direct_sr_set):
                    pending_broad_scores[candidate.guide_code] += (
                        float(candidate.confidence or 0) * weight * broad_multiplier
                    )
                    pending_broad_reasons[candidate.guide_code].append(f"broad {candidate.entity_type} SR candidate")
                    if candidate.entity_type == "WP":
                        pending_broad_wp_sr_map[candidate.entity_id].add(candidate.sr_id)
                        pending_broad_wp_source[candidate.entity_id] = candidate.guide_code
                    continue
                multiplier = broad_multiplier if candidate.sr_id in broad_sr_ids else 1.0
                guide_scores[candidate.guide_code] += float(candidate.confidence or 0) * weight * multiplier
                guide_reasons[candidate.guide_code].append(f"{candidate.entity_type} SR candidate")
                if candidate.entity_type == "WP":
                    wp_sr_map[candidate.entity_id].add(candidate.sr_id)
                guide_specific_signals.add(candidate.guide_code)

        if feature_codes:
            feature_rows = (
                db.query(PgGuideEntityFeatureCandidate)
                .filter(PgGuideEntityFeatureCandidate.entity_type.in_(["WP", "GUIDE", "CI"]))
                .filter(PgGuideEntityFeatureCandidate.feature_code.in_(feature_codes))
                .filter(PgGuideEntityFeatureCandidate.confidence >= SERVING_CONFIDENCE)
                .filter(PgGuideEntityFeatureCandidate.review_status.in_(SERVING_REVIEW_STATUSES))
                .limit(limit * 50)
                .all()
            )
            for candidate in feature_rows:
                weight = 0.16 if candidate.entity_type == "WP" else 0.08
                if _guide_specific_feature(candidate.feature_code):
                    guide_scores[candidate.guide_code] += float(candidate.confidence or 0) * weight
                    guide_reasons[candidate.guide_code].append(f"{candidate.entity_type} feature")
                    guide_specific_signals.add(candidate.guide_code)
                    continue
                pending_generic_feature_scores[candidate.guide_code] += float(candidate.confidence or 0) * weight * 0.5
                pending_generic_feature_reasons[candidate.guide_code].append(f"generic {candidate.entity_type} feature")

        if context_blob:
            trigger_rows = (
                db.query(PgGuideVisualTriggerCandidate)
                .filter(PgGuideVisualTriggerCandidate.confidence >= SERVING_CONFIDENCE)
                .filter(PgGuideVisualTriggerCandidate.review_status.in_(SERVING_REVIEW_STATUSES))
                .limit(800)
                .all()
            )
            for candidate in trigger_rows:
                if not _matches_visual_trigger(candidate, context_blob):
                    continue
                weight = 0.18 if candidate.entity_type == "WP" else 0.10
                guide_scores[candidate.guide_code] += float(candidate.confidence or 0) * weight
                guide_reasons[candidate.guide_code].append(f"{candidate.entity_type} visual trigger")
                guide_specific_signals.add(candidate.guide_code)
    except SQLAlchemyError:
        db.rollback()

    candidate_guide_codes = set(guide_scores) | set(pending_broad_scores) | set(pending_generic_feature_scores)
    for guide_code in sorted(candidate_guide_codes):
        usage_score, usage_reasons, usage_signal = _score_usage_profile(
            get_guide_domain_profile(guide_code),
            visual_cues=visual_cues,
            context_text=context_text,
            feature_codes=feature_codes,
            industry_contexts=industry_contexts,
        )
        if usage_score <= 0:
            continue
        guide_scores[guide_code] += usage_score
        guide_reasons[guide_code].extend(usage_reasons)
        if usage_signal:
            guide_specific_signals.add(guide_code)

    for guide_code, pending_score in pending_generic_feature_scores.items():
        if guide_code not in guide_specific_signals and guide_scores.get(guide_code, 0.0) <= 0:
            continue
        guide_scores[guide_code] += pending_score
        guide_reasons[guide_code].extend(pending_generic_feature_reasons.get(guide_code, []))

    for guide_code, pending_score in pending_broad_scores.items():
        if guide_code not in guide_specific_signals and guide_scores.get(guide_code, 0.0) <= 0:
            continue
        guide_scores[guide_code] += pending_score
        guide_reasons[guide_code].extend(pending_broad_reasons.get(guide_code, []))
    for wp_id, pending_srs in pending_broad_wp_sr_map.items():
        source_guide = pending_broad_wp_source.get(wp_id)
        if source_guide and source_guide not in guide_specific_signals:
            continue
        wp_sr_map[wp_id].update(pending_srs)

    if safe_fallback_sr_ids:
        for row in hazard_rule_engine.get_guides_from_srs(
            db,
            safe_fallback_sr_ids,
            limit=max(limit, 8),
            industry_contexts=industry_contexts,
        ):
            guide_code = row.get("guide_code")
            if not guide_code:
                continue
            guide_scores[guide_code] += float(row.get("relevance_score", 0) or 0) * 0.4
            guide_reasons[guide_code].append("CI-SR fallback")
            guide_specific_signals.add(guide_code)

    if not guide_scores:
        return []

    guide_codes = list(guide_scores)
    guides = {
        guide.guide_code: guide
        for guide in db.query(PgKoshaGuide).filter(PgKoshaGuide.guide_code.in_(guide_codes)).all()
    }
    wp_rows = (
        db.query(PgWorkProcess)
        .filter(PgWorkProcess.source_guide.in_(guide_codes))
        .order_by(PgWorkProcess.source_guide, PgWorkProcess.process_order)
        .all()
    )
    wp_by_guide: dict[str, list[PgWorkProcess]] = defaultdict(list)
    for wp in wp_rows:
        wp_by_guide[wp.source_guide].append(wp)

    # Fill source_sr_ids for displayed steps even when they came from asserted mapping only.
    wp_ids = [wp.identifier for wp in wp_rows]
    if wp_ids:
        for mapping in db.query(PgWpSrMapping).filter(PgWpSrMapping.wp_id.in_(wp_ids)).all():
            if not sr_ids or mapping.sr_id in sr_ids:
                wp_sr_map[mapping.wp_id].add(mapping.sr_id)

    ci_by_guide: dict[str, set[str]] = defaultdict(set)
    if safe_fallback_sr_ids:
        rows = (
            db.query(PgChecklistItem.source_guide, PgChecklistItem.identifier)
            .join(PgCiSrMapping, PgCiSrMapping.ci_id == PgChecklistItem.identifier)
            .filter(PgCiSrMapping.sr_id.in_(safe_fallback_sr_ids))
            .limit(200)
            .all()
        )
        for guide_code, ci_id in rows:
            ci_by_guide[guide_code].add(ci_id)

    profile_bits = _guide_candidate_profile_bits(db, guide_codes)
    ranked_guides = []
    for guide_code, raw_score in guide_scores.items():
        guide = guides.get(guide_code)
        if not guide:
            continue
        manual_profile = get_guide_domain_profile(guide_code)
        domain_decision = evaluate_guide_domain_profile(
            guide_code=guide_code,
            title=guide.title,
            profile_text=_domain_profile_text(
                guide,
                work_processes=wp_by_guide.get(guide_code, []),
                profile_bits=profile_bits.get(guide_code, []),
            ),
            industry_contexts=industry_contexts,
            risk_feature_codes=feature_codes,
            visual_cues=visual_cues,
            context_text=context_text,
        )
        if domain_decision.exclude or domain_decision.alignment == "domain_mismatch":
            continue
        if not _reference_role_context_hit(manual_profile, visual_cues, context_text):
            continue
        guide_industry = infer_industry_context(text=" ".join(filter(None, [guide.title, guide.sub_category])))
        industry_adjustment, industry_alignment, _ = score_industry_alignment(
            guide_industry.active_industries,
            industry_contexts,
        )
        if domain_decision.family:
            guide_reasons[guide_code].append(
                f"{domain_decision.level}:{domain_decision.alignment}:{domain_decision.family}"
            )
        displayed_alignment = (
            domain_decision.alignment
            if domain_decision.alignment != "general"
            else industry_alignment
        )
        final_score = min(
            0.99,
            max(0.0, 0.45 + raw_score * 0.12 + industry_adjustment + domain_decision.score_adjustment),
        )
        ranked_guides.append((final_score, displayed_alignment, guide_code, guide))
    ranked_guides.sort(key=lambda row: row[0], reverse=True)

    results = []
    for final_score, industry_alignment, guide_code, guide in ranked_guides[:limit]:
        steps = []
        manual_profile = get_guide_domain_profile(guide_code)
        ranked_work_processes = _rank_work_processes(
            wp_by_guide.get(guide_code, []),
            profile=manual_profile,
            visual_cues=visual_cues,
            context_text=context_text,
            wp_sr_map=wp_sr_map,
        )
        for wp in ranked_work_processes[:8]:
            steps.append({
                "step_id": wp.identifier,
                "order": int(wp.process_order or len(steps) + 1),
                "title": wp.process_name,
                "safety_measures": wp.safety_measures,
                "source_section": wp.source_section,
                "source_sr_ids": sorted(wp_sr_map.get(wp.identifier, set())),
            })
        source_sr_ids = sorted({sr for step in steps for sr in step.get("source_sr_ids", [])})
        results.append({
            "guide_code": guide.guide_code,
            "title": guide.title,
            "classification": guide.domain,
            "industry_alignment": industry_alignment,
            "relevant_sections": [step.get("source_section") for step in steps if step.get("source_section")],
            "relevance_score": round(final_score, 4),
            "mapping_type": "she_sr_wp_guide",
            "ci_hit_count": len(ci_by_guide.get(guide_code, set())),
            "work_process_steps": steps,
            "source_sr_ids": source_sr_ids or primary_sr_ids[:5],
            "source_ci_ids": sorted(ci_by_guide.get(guide_code, set()))[:12],
            "evidence_summary": "; ".join(_unique(guide_reasons.get(guide_code, []))[:4]),
        })
    return results
