#!/usr/bin/env python3
"""사진 한 장에 대한 OHS 분석 파이프라인 단계별 진단.

실행: PYTHONUTF8=1 PYTHONPATH=. python scripts/diagnose_image.py <image_path>

진단 단계:
  1. GPT 응답 (Track A 자유 / Track B faceted / risks)
  2. faceted 정규화 (normalize_faceted_hazards)
  3. rule engine (apply_rules → canonical)
  4. divergence (Track A vs Track B 미스매치)
  5. SR 매핑 (query_sr_for_facets) — 사진과 의미적 일치 여부 체크
  6. CI 매핑 (get_checklist_from_srs) — 추천 체크리스트 항목
  7. 진단 요약 (각 단계 row count + sample, 미스매치 알림)
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

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


async def main(image_path: str):
    img = Path(image_path)
    assert img.exists(), f"이미지 파일 없음: {img}"
    img_b64 = base64.b64encode(img.read_bytes()).decode()
    print(f"[INFO] 이미지: {img} ({img.stat().st_size:,} bytes)")

    # ── Step 1: GPT 호출 ──
    hr("[1/7] GPT-4o 사진 분석 (OHS prompt 그대로)")
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
    hr("[2/7] hazard_normalizer.normalize_faceted_hazards")
    from app.services.hazard_normalizer import normalize_faceted_hazards
    context_text = " ".join(f.get("description", "") for f in free)
    normalized = normalize_faceted_hazards(faceted, context_text)
    print(f"  정규화 전 → 후:")
    print(f"    accident_types:   {faceted.get('accident_types')} → {normalized.get('accident_types')}")
    print(f"    hazardous_agents: {faceted.get('hazardous_agents')} → {normalized.get('hazardous_agents')}")
    print(f"    work_contexts:    {faceted.get('work_contexts')} → {normalized.get('work_contexts')}")

    # ── Step 3: Rule engine canonical ──
    hr("[3/7] hazard_rule_engine.apply_rules → canonical")
    from app.services import hazard_rule_engine
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        canonical = hazard_rule_engine.apply_rules(normalized, db)
        print(f"  canonical (적용 규칙: {canonical.get('applied_rules', [])}):")
        print(f"    accident_types:   {canonical['accident_types']}")
        print(f"    hazardous_agents: {canonical['hazardous_agents']}")
        print(f"    work_contexts:    {canonical['work_contexts']}")
        print(f"    confidence:       {canonical.get('confidence')}")

        # ── Step 4: Divergence ──
        hr("[4/7] divergence_detector — Track A vs B 미스매치")
        from app.services.divergence_detector import detect_divergence
        divergences = detect_divergence(free, canonical, faceted.get("forced_fit_notes", []))
        print(f"  divergence: {len(divergences)}건")
        for d in divergences[:5]:
            print(f"    [{d.get('gap_type')}] {d.get('gpt_free_label', '')}: {d.get('description', '')[:80]}")

        # ── Step 5: SR 매핑 ──
        hr("[5/7] PG SR 매핑 (query_sr_for_facets)")
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

        # ── Step 6: CI 추천 ──
        hr("[6/7] CI 추천 (get_checklist_from_srs)")
        sr_ids = [sr["identifier"] for sr in sr_results]
        ci_data = hazard_rule_engine.get_checklist_from_srs(db, sr_ids, limit=15)
        print(f"  추천 CI: {len(ci_data)}건")
        for ci in ci_data[:15]:
            txt = (ci.get("text", "") or "").strip()[:80]
            print(f"    [{ci.get('binding_force', '')}] {ci.get('identifier', '')}: {txt}")
            print(f"        guide={ci.get('source_guide', '')} section={ci.get('source_section', '')}")

        # ── Step 7: 진단 요약 ──
        hr("[7/7] 진단 요약")
        print(f"  GPT free 위험 수:       {len(free)}")
        print(f"  GPT faceted forced_fit: {len(forced)} (>0이면 enum 부족 시그널)")
        print(f"  divergence:             {len(divergences)} (>0이면 Track A↔B 갭)")
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
        out_path.write_text(json.dumps({
            "image": str(img),
            "gpt_response": result,
            "normalized": normalized,
            "canonical": canonical,
            "divergence": divergences,
            "sr_results": sr_results,
            "ci_data": ci_data,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  [OK] 전체 응답 저장: {out_path}")

    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diagnose_image.py <image_path>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
