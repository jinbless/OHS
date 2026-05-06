#!/usr/bin/env python3
"""사진 한 장에 대한 OHS 분석 파이프라인 단계별 진단.

실행: PYTHONUTF8=1 PYTHONPATH=. python scripts/diagnose_image.py <image_path>

진단 단계:
  1. GPT 응답 (Track A 자유 / Track B faceted / risks)
  2. faceted 정규화 (normalize_faceted_hazards)
  3. rule engine (apply_rules → canonical)
  4. SHE 매칭 (사진 특징 → 재사용 위험상황 패턴)
  5. divergence (Track A vs Track B 미스매치)
  6. SR 매핑 (query_sr_for_facets) — 사진과 의미적 일치 여부 체크
  7. CI 매핑 (get_checklist_from_srs) — 추천 체크리스트 항목
  8. 진단 요약 + app TTL 물질화
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, RDFS, XSD

# OHS backend 모듈 import 위해 cwd를 PYTHONPATH로
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# UTF-8 console
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def hr(title: str = ""):
    print("\n" + "=" * 60)
    if title:
        print(title)
        print("=" * 60)


APP = Namespace("https://cashtoss.info/ontology/app#")
RISK = Namespace("https://cashtoss.info/ontology/risk#")
SHE = Namespace("https://cashtoss.info/ontology/risk/situation#")
SR = Namespace("https://cashtoss.info/ontology/sr#")
PEN = Namespace("https://cashtoss.info/ontology/penalty#")
GUIDE = Namespace("https://cashtoss.info/ontology/guide#")
HAZARD = Namespace("https://cashtoss.info/ontology/risk/hazard#")
AGENT = Namespace("https://cashtoss.info/ontology/risk/agent#")
CONTEXT = Namespace("https://cashtoss.info/ontology/risk/context#")

ACCIDENT_TYPE_TO_URI = {
    "FALL": HAZARD.Fall,
    "SLIP": HAZARD.Slip,
    "COLLISION": HAZARD.Collision,
    "FALLING_OBJECT": HAZARD.FallingObject,
    "CRUSH": HAZARD.Crush,
    "CUT": HAZARD.Cut,
    "COLLAPSE": HAZARD.Collapse,
    "ERGONOMIC": HAZARD.Ergonomic,
}
HAZARDOUS_AGENT_TO_URI = {
    "CHEMICAL": AGENT.Chemical,
    "DUST": AGENT.Dust,
    "TOXIC": AGENT.Toxic,
    "CORROSION": AGENT.Corrosion,
    "RADIATION": AGENT.Radiation,
    "FIRE": AGENT.Fire,
    "ELECTRICITY": AGENT.Electricity,
    "ARC_FLASH": AGENT.ArcFlash,
    "NOISE": AGENT.Noise,
    "HEAT_COLD": AGENT.HeatCold,
    "BIOLOGICAL": AGENT.Biological,
}
WORK_CONTEXT_TO_URI = {
    "SCAFFOLD": CONTEXT.Scaffold,
    "CONFINED_SPACE": CONTEXT.ConfinedSpace,
    "EXCAVATION": CONTEXT.Excavation,
    "MACHINE": CONTEXT.Machine,
    "VEHICLE": CONTEXT.Vehicle,
    "CRANE": CONTEXT.Crane,
    "CONVEYOR": CONTEXT.Conveyor,
    "ROBOT": CONTEXT.Robot,
    "CONSTRUCTION_EQUIP": CONTEXT.ConstructionEquip,
    "RAIL": CONTEXT.Rail,
    "PRESSURE_VESSEL": CONTEXT.PressureVessel,
    "STEELWORK": CONTEXT.Steelwork,
    "MATERIAL_HANDLING": CONTEXT.MaterialHandling,
}


def safe_fragment(value: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")
    return fragment or "item"


def ontology_term(ns: Namespace, identifier: str):
    return ns[quote(str(identifier), safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")]


def canonical_feature_terms(canonical: dict) -> list:
    terms = []
    for value in canonical.get("accident_types", []) or []:
        if value in ACCIDENT_TYPE_TO_URI:
            terms.append(ACCIDENT_TYPE_TO_URI[value])
    for value in canonical.get("hazardous_agents", []) or []:
        if value in HAZARDOUS_AGENT_TO_URI:
            terms.append(HAZARDOUS_AGENT_TO_URI[value])
    for value in canonical.get("work_contexts", []) or []:
        if value in WORK_CONTEXT_TO_URI:
            terms.append(WORK_CONTEXT_TO_URI[value])
    return list(dict.fromkeys(terms))


def find_penalty_rules_for_srs(sr_ids: list[str], limit: int = 40) -> list[str]:
    """SR -> NormStatement -> PenaltyRule 경로를 RDF 인스턴스 파일에서 찾는다."""
    if not sr_ids:
        return []

    root = Path(__file__).resolve().parents[3]
    ontology_dir = root / "koshaontology" / "ontology"
    instances_path = ontology_dir / "kosha-instances.ttl"
    if not instances_path.exists():
        return []

    graph = Graph()
    graph.parse(instances_path, format="turtle")

    penalty_rules: list[str] = []
    seen: set[str] = set()
    for sr_id in sr_ids:
        sr_uri = ontology_term(SR, sr_id)
        for ns_uri in graph.objects(sr_uri, SR.derivedFromNS):
            for pr_uri in graph.objects(ns_uri, PEN.hasPenaltyRule):
                pr_id = str(pr_uri).rsplit("#", 1)[-1]
                if pr_id not in seen:
                    seen.add(pr_id)
                    penalty_rules.append(pr_id)
                if len(penalty_rules) >= limit:
                    return penalty_rules
    return penalty_rules


def write_app_ttl(
    out_path: Path,
    img: Path,
    result: dict,
    canonical: dict,
    free_hazards: list[dict],
    divergences: list[dict],
    she_matches: list[dict],
    sr_results: list[dict],
    ci_data: list[dict],
    penalty_rule_ids: list[str],
) -> None:
    """사진 1장 진단 결과를 app 실행 레이어 RDF로 물질화한다."""
    graph = Graph()
    graph.bind("app", APP)
    graph.bind("she", SHE)
    graph.bind("sr", SR)
    graph.bind("pen", PEN)
    graph.bind("guide", GUIDE)
    graph.bind("hazard", HAZARD)
    graph.bind("agent", AGENT)
    graph.bind("context", CONTEXT)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)

    case_key = safe_fragment(img.stem)
    case_uri = APP[f"Case_{case_key}"]
    photo_uri = APP[f"Photo_{case_key}"]
    observation_uri = APP[f"Observation_{case_key}"]
    finding_uri = APP[f"Finding_{case_key}"]
    action_uri = APP[f"Action_{case_key}"]
    penalty_exposure_uri = APP[f"PenaltyExposure_{case_key}"]

    graph.add((case_uri, RDF.type, APP.InspectionCase))
    graph.add((case_uri, APP.hasPhoto, photo_uri))
    graph.add((case_uri, APP.hasFinding, finding_uri))
    graph.add((case_uri, RDFS.label, Literal(f"{img.name} 분석 건", lang="ko")))

    graph.add((photo_uri, RDF.type, APP.UploadedPhoto))
    graph.add((photo_uri, APP.fileName, Literal(img.name)))
    graph.add((photo_uri, APP.hasObservation, observation_uri))

    graph.add((observation_uri, RDF.type, APP.VisualObservation))
    graph.add((observation_uri, RDFS.label, Literal("사진 기반 관찰 사실", lang="ko")))
    confidence = canonical.get("confidence") or 0
    graph.add((observation_uri, APP.confidence, Literal(str(confidence), datatype=XSD.decimal)))

    feature_terms = canonical_feature_terms(canonical)
    cue_source = free_hazards[:8] or [{"label": "관찰 사실", "description": json.dumps(canonical, ensure_ascii=False)}]
    for idx, hazard in enumerate(cue_source, start=1):
        cue_uri = APP[f"VisualCue_{case_key}_{idx}"]
        label = (hazard.get("label") or f"시각 단서 {idx}").strip()
        cue_text = (
            hazard.get("visual_evidence")
            or hazard.get("description")
            or label
            or "사진 관찰 단서"
        )
        graph.add((cue_uri, RDF.type, APP.VisualCue))
        graph.add((cue_uri, RDFS.label, Literal(label, lang="ko")))
        graph.add((cue_uri, APP.visualCueText, Literal(cue_text)))
        graph.add((observation_uri, APP.hasVisualCue, cue_uri))
        for feature_uri in feature_terms:
            graph.add((cue_uri, APP.mappedTo, feature_uri))

    graph.add((finding_uri, RDF.type, APP.HazardFinding))
    graph.add((finding_uri, APP.basedOnObservation, observation_uri))
    graph.add((finding_uri, APP.recommendsAction, action_uri))
    graph.add((finding_uri, APP.hasPenaltyExposure, penalty_exposure_uri))
    if divergences:
        graph.add((finding_uri, APP.hasFindingStatus, APP.NeedsClarificationFinding))
    elif she_matches:
        graph.add((finding_uri, APP.hasFindingStatus, APP.SuspectedFinding))
    else:
        graph.add((finding_uri, APP.hasFindingStatus, APP.NotDeterminedFinding))

    for idx, match in enumerate(she_matches, start=1):
        match_uri = APP[f"SituationMatch_{case_key}_{idx}"]
        graph.add((match_uri, RDF.type, APP.SituationMatch))
        graph.add((match_uri, APP.matchesSituation, ontology_term(SHE, match["she_id"])))
        graph.add((match_uri, APP.matchConfidence, Literal(str(match.get("match_score", 0)), datatype=XSD.decimal)))
        if match.get("name"):
            graph.add((match_uri, RDFS.label, Literal(match["name"], lang="ko")))
        graph.add((finding_uri, APP.hasSituationMatch, match_uri))

    selected_sr_ids: list[str] = []
    for match in she_matches:
        for sr_id in match.get("applies_sr_ids", []) or []:
            if sr_id not in selected_sr_ids:
                selected_sr_ids.append(sr_id)
    for sr in sr_results:
        sr_id = sr.get("identifier")
        if sr_id and sr_id not in selected_sr_ids:
            selected_sr_ids.append(sr_id)

    graph.add((action_uri, RDF.type, APP.CorrectiveAction))
    she_sr_set = {
        sr_id
        for match in she_matches
        for sr_id in match.get("applies_sr_ids", []) or []
    }
    for rank, sr_id in enumerate(selected_sr_ids[:30], start=1):
        recommendation_uri = APP[f"ActionRecommendation_{case_key}_{rank}"]
        graph.add((action_uri, APP.citesRequirement, ontology_term(SR, sr_id)))
        graph.add((action_uri, APP.hasActionRecommendation, recommendation_uri))
        graph.add((recommendation_uri, RDF.type, APP.ActionRecommendation))
        graph.add((recommendation_uri, APP.forAction, action_uri))
        graph.add((recommendation_uri, APP.recommendedRequirement, ontology_term(SR, sr_id)))
        graph.add((recommendation_uri, APP.recommendationRank, Literal(rank, datatype=XSD.integer)))
        source = "SHE_MATCH" if sr_id in she_sr_set else "FACET_SR_CANDIDATE"
        graph.add((recommendation_uri, APP.recommendationSource, Literal(source)))
        reason = "SHE 위험상황 패턴에서 직접 연결된 안전요구사항" if sr_id in she_sr_set else "정규화 특징으로 조회된 후보 안전요구사항"
        graph.add((recommendation_uri, APP.matchReason, Literal(reason, lang="ko")))

    guides: list[str] = []
    for match in she_matches:
        guides.extend(match.get("source_guides", []) or [])
    for ci in ci_data:
        if ci.get("source_guide"):
            guides.append(ci["source_guide"])
    for guide_id in list(dict.fromkeys(guides))[:20]:
        graph.add((action_uri, APP.guidedBy, ontology_term(GUIDE, guide_id)))

    ci_ids = []
    for match in she_matches:
        ci_ids.extend(match.get("applies_ci_ids", []) or [])
    ci_ids.extend(ci.get("identifier") for ci in ci_data if ci.get("identifier"))
    for ci_id in list(dict.fromkeys(ci_ids))[:30]:
        graph.add((action_uri, APP.usesChecklistCue, ontology_term(GUIDE, ci_id)))

    graph.add((penalty_exposure_uri, RDF.type, APP.PenaltyExposure))
    if penalty_rule_ids:
        graph.add((penalty_exposure_uri, APP.hasPenaltyExposureStatus, APP.ConditionalPenaltyExposure))
    else:
        graph.add((penalty_exposure_uri, APP.hasPenaltyExposureStatus, APP.NoPenaltyExposure))
    for pr_id in penalty_rule_ids:
        graph.add((penalty_exposure_uri, APP.possiblePenalty, ontology_term(PEN, pr_id)))

    graph.serialize(out_path, format="turtle", encoding="utf-8")


async def main(image_path: str):
    img = Path(image_path)
    assert img.exists(), f"이미지 파일 없음: {img}"
    img_b64 = base64.b64encode(img.read_bytes()).decode()
    print(f"[INFO] 이미지: {img} ({img.stat().st_size:,} bytes)")

    # ── Step 1: GPT 호출 ──
    hr("[1/8] GPT-4o 사진 분석 (OHS prompt 그대로)")
    from app.integrations.openai_client import openai_client
    result = await openai_client.analyze_image(
        image_base64=img_b64,
        workplace_type=None,
        additional_context=None,
    )

    free = result.get("free_hazards", [])
    faceted = result.get("faceted_hazards", {})
    risks = result.get("risks", [])
    print(f"\n  Track A (free_hazards): {len(free)}건")
    for f in free[:6]:
        print(f"    [{f.get('severity')}] {f.get('label')}: {f.get('description')[:80]}")
        if f.get("visual_evidence"):
            print(f"        근거: {f.get('visual_evidence')[:80]}")

    print(f"\n  Track B (faceted_hazards):")
    print(f"    accident_types:    {faceted.get('accident_types')}")
    print(f"    hazardous_agents:  {faceted.get('hazardous_agents')}")
    print(f"    work_contexts:     {faceted.get('work_contexts')}")
    forced = faceted.get("forced_fit_notes", [])
    if forced:
        print(f"    ⚠ forced_fit_notes ({len(forced)}건):")
        for n in forced:
            print(f"        - {n}")

    print(f"\n  risks (호환 필드): {len(risks)}건")
    for r in risks[:5]:
        print(f"    [{r.get('severity')}] {r.get('category_code')}/{r.get('category_name')}: {r.get('description')[:60]}")

    # ── Step 2: Faceted 정규화 ──
    hr("[2/8] hazard_normalizer.normalize_faceted_hazards")
    from app.services.hazard_normalizer import normalize_faceted_hazards
    context_text = " ".join(f.get("description", "") for f in free)
    normalized = normalize_faceted_hazards(faceted, context_text)
    print(f"  정규화 전 → 후:")
    print(f"    accident_types:   {faceted.get('accident_types')} → {normalized.get('accident_types')}")
    print(f"    hazardous_agents: {faceted.get('hazardous_agents')} → {normalized.get('hazardous_agents')}")
    print(f"    work_contexts:    {faceted.get('work_contexts')} → {normalized.get('work_contexts')}")

    # ── Step 3: Rule engine canonical ──
    hr("[3/8] hazard_rule_engine.apply_rules → canonical")
    from app.services import hazard_rule_engine
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        canonical = hazard_rule_engine.apply_rules(
            normalized,
            db,
            allow_context_only_inference=False,
        )
        print(f"  canonical (적용 규칙: {canonical.get('applied_rules', [])}):")
        print(f"    accident_types:   {canonical['accident_types']}")
        print(f"    hazardous_agents: {canonical['hazardous_agents']}")
        print(f"    work_contexts:    {canonical['work_contexts']}")
        print(f"    confidence:       {canonical.get('confidence')}")

        # ── Step 4: SHE matcher ──
        hr("[4/8] SHE matcher — 사진 특징 → 위험상황 패턴")
        she_matches = []
        she_error = None
        try:
            from app.services import she_matcher
            she_matches = [
                m.to_dict()
                for m in she_matcher.match_she(
                    db,
                    canonical["accident_types"],
                    canonical["hazardous_agents"],
                    canonical["work_contexts"],
                    top_n=5,
                    min_matched_dims=2,
                )
            ]
        except Exception as exc:
            she_error = str(exc)

        if she_error:
            print(f"  ❌ SHE 매칭 실패: {she_error}")
        else:
            print(f"  매칭 SHE: {len(she_matches)}건")
            for match in she_matches[:5]:
                print(f"    {match['she_id']}: {match.get('name', '')[:70]}")
                print(f"        score={match.get('match_score')} dims={match.get('matched_dims')} SR={match.get('applies_sr_ids')}")

        she_sr_ids = []
        for match in she_matches:
            for sr_id in match.get("applies_sr_ids", []) or []:
                if sr_id not in she_sr_ids:
                    she_sr_ids.append(sr_id)

        # ── Step 5: Divergence ──
        hr("[5/8] divergence_detector — Track A vs B 미스매치")
        from app.services.divergence_detector import detect_divergence
        divergences = detect_divergence(free, canonical, faceted.get("forced_fit_notes", []))
        print(f"  divergence: {len(divergences)}건")
        for d in divergences[:5]:
            print(f"    [{d.get('gap_type')}] {d.get('gpt_free_label', '')}: {d.get('description', '')[:80]}")

        # ── Step 6: SR 매핑 ──
        hr("[6/8] PG SR 매핑 (query_sr_for_facets)")
        sr_results = hazard_rule_engine.query_sr_for_facets(
            db,
            canonical["accident_types"],
            canonical["hazardous_agents"],
            canonical["work_contexts"],
        )
        print(f"  매칭된 SR: {len(sr_results)}건")
        for sr in sr_results[:10]:
            print(f"    {sr['identifier']}: {sr.get('title', '')[:60]}")
            ah = sr.get("addresses_hazard", [])
            at = sr.get("accident_types", [])
            ag = sr.get("hazardous_agents", [])
            wc = sr.get("work_contexts", [])
            print(f"        addresses_hazard={ah}  accident={at}  agent={ag}  ctx={wc}")

        # ── Step 7: CI 추천 ──
        hr("[7/8] CI 추천 (get_checklist_from_srs)")
        sr_ids = list(dict.fromkeys(she_sr_ids + [sr["identifier"] for sr in sr_results]))
        ci_data = hazard_rule_engine.get_checklist_from_srs(db, sr_ids, limit=15)
        print(f"  추천 CI: {len(ci_data)}건")
        for ci in ci_data[:15]:
            txt = (ci.get("text", "") or "").strip()[:80]
            print(f"    [{ci.get('binding_force', '')}] {ci.get('identifier', '')}: {txt}")
            print(f"        guide={ci.get('source_guide', '')} section={ci.get('source_section', '')}")

        # ── Step 8: 진단 요약 ──
        hr("[8/8] 진단 요약")
        print(f"  GPT free 위험 수:       {len(free)}")
        print(f"  GPT faceted forced_fit: {len(forced)} (>0이면 enum 부족 시그널)")
        print(f"  divergence:             {len(divergences)} (>0이면 Track A↔B 갭)")
        print(f"  매칭 SHE:               {len(she_matches)}")
        print(f"  매칭 SR:                {len(sr_results)}")
        print(f"  추천 CI:                {len(ci_data)}")

        # 자동 진단
        hr("자동 진단")
        if len(forced) > 0:
            print("  ⚠ enum에 없는 위험: forced_fit_notes 다수 → faceted enum 보강 필요")
        if len(divergences) > 0:
            print("  ⚠ Track A의 위험이 Track B canonical에 누락 → 정규화/rule 보강 필요")
        if len(sr_results) == 0:
            print("  ❌ 매칭 SR 0건 → faceted SR 매핑 자체가 없음 (Pipe-A faceted 태깅 갭)")
        elif len(ci_data) == 0:
            print("  ❌ SR은 있으나 CI 0건 → SR-CI 연결 빈약 (Pipe-B basedOnSR 매핑 갭)")
        # 의미 일치 평가 (heuristic): 사용자 묘사 키워드 vs CI 텍스트
        keywords_from_image = []
        for f in free:
            txt = (f.get("description", "") + " " + f.get("label", "")).lower()
            for kw in ["오일", "기름", "누유", "미끄럼", "정비", "전기", "절연", "케이블", "진동",
                      "윤활", "유체", "부식", "화재", "발판", "그레이팅"]:
                if kw in txt and kw not in keywords_from_image:
                    keywords_from_image.append(kw)
        print(f"  GPT가 본 사진 핵심 키워드: {keywords_from_image}")
        if ci_data:
            ci_hit = 0
            ci_no_hit_samples = []
            for ci in ci_data:
                txt = (ci.get("text", "") or "").lower()
                if any(kw in txt for kw in keywords_from_image):
                    ci_hit += 1
                elif len(ci_no_hit_samples) < 3:
                    ci_no_hit_samples.append(ci.get("text", "")[:60])
            print(f"  추천 CI 중 사진 키워드 포함: {ci_hit}/{len(ci_data)} ({ci_hit/len(ci_data):.0%})")
            if ci_hit / len(ci_data) < 0.3:
                print("  ❌ 의미 미스매치: CI 다수가 사진 핵심 키워드와 무관")
                print(f"     (사진 키워드 {keywords_from_image}와 무관한 CI 샘플:)")
                for s in ci_no_hit_samples:
                    print(f"     - {s}")

        # 최종 결과 JSON 저장 (선택)
        out_dir = Path(__file__).resolve().parents[1] / "data" / "diagnosis"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"diagnose_{img.stem}.json"
        app_ttl_path = out_dir / f"diagnose_{img.stem}.app.ttl"
        penalty_rule_ids = find_penalty_rules_for_srs(sr_ids)
        write_app_ttl(
            app_ttl_path,
            img,
            result,
            canonical,
            free,
            divergences,
            she_matches,
            sr_results,
            ci_data,
            penalty_rule_ids,
        )
        out_path.write_text(json.dumps({
            "image": str(img),
            "gpt_response": result,
            "normalized": normalized,
            "canonical": canonical,
            "she_matches": she_matches,
            "divergence": divergences,
            "sr_results": sr_results,
            "ci_data": ci_data,
            "penalty_rule_ids": penalty_rule_ids,
            "app_ttl": str(app_ttl_path),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  [OK] 전체 응답 저장: {out_path}")
        print(f"  [OK] app 실행 인스턴스 TTL 저장: {app_ttl_path}")

    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diagnose_image.py <image_path>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
