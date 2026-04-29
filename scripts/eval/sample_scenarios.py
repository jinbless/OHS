#!/usr/bin/env python3
"""Phase 0.2 — Stratified Sampling: catalog-v1.jsonl → scenarios-v1.jsonl

전략:
  1. 각 Bundle에 work_context primary axis 부여 (PG facets로 enrichment)
  2. work_context 분야 12개 stratum: SCAFFOLD, CONFINED_SPACE, EXCAVATION, MACHINE,
     VEHICLE, CRANE, CONVEYOR, CONSTRUCTION_EQUIP, PRESSURE_VESSEL, STEELWORK,
     MATERIAL_HANDLING, GENERAL_WORKPLACE (+ ETC)
  3. source 비율 cap: PA11/R2 합계 ≤50%, SR_REGISTRY ≤30%, 나머지 20%
  4. 각 stratum에서 결정론적 random (md5 hash sort + SEED)
  5. Bundle 품질 필터: SR 수 ≥1 AND (CI 수 ≥3 OR Guide 수 ≥1)

출력 size: --target 옵션 (default 100, 500까지 확장 가능)

실행:
  PYTHONUTF8=1 python OHS/scripts/eval/sample_scenarios.py --target 100
  PYTHONUTF8=1 python OHS/scripts/eval/sample_scenarios.py --target 500
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[3]
OHS = ROOT / "OHS"
INPUT = OHS / "data" / "eval" / "catalog-v1.jsonl"
OUTPUT = OHS / "data" / "eval" / "scenarios-v1.jsonl"

PG_DSN = "dbname=kosha user=kosha password=1229 host=localhost port=5432"
SEED = "phase0-catalog-baseline-2026-04-27"

# 12개 work_context stratum (hazard-taxonomy-unified.json 기반)
WORK_CONTEXTS = [
    "SCAFFOLD",
    "CONFINED_SPACE",
    "EXCAVATION",
    "MACHINE",
    "VEHICLE",
    "CRANE",
    "CONVEYOR",
    "CONSTRUCTION_EQUIP",
    "PRESSURE_VESSEL",
    "STEELWORK",
    "MATERIAL_HANDLING",
    "GENERAL_WORKPLACE",
]
ETC = "ETC"

# Source 비율 cap (catalog 내 분포 ≠ sample 내 분포)
SOURCE_QUOTA = {
    "R2": 0.10,         # validated pair 핵심 (10%)
    "PA11": 0.30,       # Guide cluster (30%)
    "SR_REGISTRY": 0.30, # SR 중심 (30%)
    "CI_MAPPING": 0.10,  # CI 중심 (10%)
    "GUIDE_INTERLINK": 0.10, # 인용 네트워크 (10%)
    "FACETED": 0.10,     # 분류 cross (10%)
}


def md5_hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def enrich_with_facets(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """각 Bundle의 sr_set/ci_set에 대해 PG에서 facets union 조회."""
    import psycopg2
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()

    # Bundle별 facets enrichment
    for bd in bundles:
        srs = bd.get("sr_set") or []
        cis = bd.get("ci_set") or []
        # 이미 primary_facets 있으면 (FACETED source) skip
        if bd.get("primary_facets") and (
            bd["primary_facets"].get("accident_types") or
            bd["primary_facets"].get("hazardous_agents") or
            bd["primary_facets"].get("work_contexts")
        ):
            continue
        accs, hazs, wcs = set(), set(), set()
        if srs:
            cur.execute("""
                SELECT
                  COALESCE(jsonb_agg(DISTINCT v) FILTER (WHERE v IS NOT NULL), '[]'::jsonb)
                FROM safety_requirements,
                     LATERAL jsonb_array_elements_text(COALESCE(accident_types, '[]'::jsonb)) AS v
                WHERE identifier = ANY(%s)
            """, (srs,))
            r = cur.fetchone()
            if r and r[0]:
                accs.update(r[0])
            cur.execute("""
                SELECT
                  COALESCE(jsonb_agg(DISTINCT v) FILTER (WHERE v IS NOT NULL), '[]'::jsonb)
                FROM safety_requirements,
                     LATERAL jsonb_array_elements_text(COALESCE(hazardous_agents, '[]'::jsonb)) AS v
                WHERE identifier = ANY(%s)
            """, (srs,))
            r = cur.fetchone()
            if r and r[0]:
                hazs.update(r[0])
            cur.execute("""
                SELECT
                  COALESCE(jsonb_agg(DISTINCT v) FILTER (WHERE v IS NOT NULL), '[]'::jsonb)
                FROM safety_requirements,
                     LATERAL jsonb_array_elements_text(COALESCE(work_contexts, '[]'::jsonb)) AS v
                WHERE identifier = ANY(%s)
            """, (srs,))
            r = cur.fetchone()
            if r and r[0]:
                wcs.update(r[0])
        if cis and not (accs or hazs or wcs):
            # CI 기반 보완 (SR이 없거나 facet이 없으면)
            cur.execute("""
                SELECT
                  COALESCE(jsonb_agg(DISTINCT v) FILTER (WHERE v IS NOT NULL), '[]'::jsonb)
                FROM checklist_items,
                     LATERAL jsonb_array_elements_text(COALESCE(work_contexts, '[]'::jsonb)) AS v
                WHERE identifier = ANY(%s)
            """, (cis,))
            r = cur.fetchone()
            if r and r[0]:
                wcs.update(r[0])
        bd["primary_facets"] = {
            "accident_types": sorted(accs),
            "hazardous_agents": sorted(hazs),
            "work_contexts": sorted(wcs),
        }

    cur.close()
    conn.close()
    return bundles


def assign_primary_work_context(bd: dict[str, Any]) -> str:
    """Bundle에 primary work_context 1개 부여 (stratification axis)."""
    wcs = bd.get("primary_facets", {}).get("work_contexts") or []
    # 첫 번째 매치되는 stratum
    for wc in WORK_CONTEXTS:
        if wc in wcs:
            return wc
    return ETC


def filter_quality(bd: dict[str, Any]) -> bool:
    """품질 필터: SR 수 ≥1 AND (CI 수 ≥3 OR Guide 수 ≥1)."""
    srs = bd.get("sr_set") or []
    cis = bd.get("ci_set") or []
    guides = bd.get("guide_set") or []
    if len(srs) < 1:
        return False
    if len(cis) < 3 and len(guides) < 1:
        return False
    return True


def stratified_sample(
    bundles: list[dict[str, Any]],
    target: int,
) -> list[dict[str, Any]]:
    """work_context × source 두 축으로 stratified sampling.

    1. work_context로 stratum 분리 (12 + ETC = 13개)
    2. 각 stratum 내에서 source quota 비율 적용
    3. 결정론적 hash sort + 상위 N
    """
    # 품질 필터
    qualified = [bd for bd in bundles if filter_quality(bd)]
    print(f"[STRAT] 품질 필터 통과: {len(qualified)}/{len(bundles)}")

    # Bundle별 work_context tag
    for bd in qualified:
        bd["_strat_wc"] = assign_primary_work_context(bd)

    # work_context별 분포
    wc_counts = Counter(bd["_strat_wc"] for bd in qualified)
    print(f"[STRAT] work_context 분포 (qualified): "
          f"{dict(sorted(wc_counts.items(), key=lambda x: -x[1]))}")

    # 활성 stratum: ETC 제외 + ≥5 bundle 보유 stratum만
    active_strata = [wc for wc in WORK_CONTEXTS if wc_counts.get(wc, 0) >= 5]
    if not active_strata:
        active_strata = list(WORK_CONTEXTS)
    print(f"[STRAT] 활성 stratum {len(active_strata)}개: {active_strata}")

    per_stratum = target // len(active_strata)
    print(f"[STRAT] stratum당 target = {per_stratum}")

    # source quota: 각 stratum 내에서 source별 quota 비율 적용
    selected: list[dict[str, Any]] = []
    for wc in active_strata:
        in_stratum = [bd for bd in qualified if bd["_strat_wc"] == wc]
        # 결정론적 hash sort
        in_stratum.sort(key=lambda b: md5_hash(b["bundle_id"] + SEED))

        by_source: dict[str, list[dict]] = defaultdict(list)
        for bd in in_stratum:
            by_source[bd["source"]].append(bd)

        stratum_selected: list[dict] = []
        for src, quota in SOURCE_QUOTA.items():
            n = max(1, int(per_stratum * quota))
            stratum_selected.extend(by_source.get(src, [])[:n])

        # quota를 못 채운 경우 다른 source에서 보충
        if len(stratum_selected) < per_stratum:
            remaining = [bd for bd in in_stratum if bd not in stratum_selected]
            stratum_selected.extend(remaining[:per_stratum - len(stratum_selected)])

        selected.extend(stratum_selected[:per_stratum])

    # ETC stratum 보충 (남은 quota)
    remaining_target = target - len(selected)
    if remaining_target > 0:
        etc_qualified = [bd for bd in qualified if bd["_strat_wc"] == ETC]
        etc_qualified.sort(key=lambda b: md5_hash(b["bundle_id"] + SEED))
        selected.extend(etc_qualified[:remaining_target])

    return selected[:target]


def to_scenario(bd: dict[str, Any], idx: int) -> dict[str, Any]:
    """Bundle → Scenario JSON 객체 (description은 Phase 0.3에서 추가됨)."""
    return {
        "scenario_id": f"SC-{idx:04d}",
        "bundle_id": bd["bundle_id"],
        "source": bd["source"],
        "work_context": bd.get("_strat_wc"),
        "ground_truth": {
            "sr_set": bd["sr_set"],
            "ci_set": bd["ci_set"],
            "guide_set": bd["guide_set"],
        },
        "primary_facets": bd["primary_facets"],
        "metadata": bd.get("metadata", {}),
        "description": None,  # Phase 0.3에서 합성
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=100,
                        help="목표 시나리오 수 (default 100, 500 권장)")
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    print(f"[INFO] input:  {args.input}")
    print(f"[INFO] output: {args.output}")
    print(f"[INFO] target: {args.target}")
    print(f"[INFO] SEED:   {SEED}")

    bundles = []
    with args.input.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            bundles.append(json.loads(line))
    print(f"[INFO] catalog: {len(bundles)} bundles")

    print(f"\n[STEP1] Facets enrichment (PG)...")
    bundles = enrich_with_facets(bundles)
    enriched = sum(1 for bd in bundles
                   if bd.get("primary_facets", {}).get("work_contexts"))
    print(f"        work_context 부여: {enriched}/{len(bundles)}")

    print(f"\n[STEP2] Stratified sampling...")
    selected = stratified_sample(bundles, args.target)
    print(f"        선택: {len(selected)}")

    # 통계
    src_dist = Counter(bd["source"] for bd in selected)
    wc_dist = Counter(bd["_strat_wc"] for bd in selected)
    print(f"\n[STAT] source 분포:")
    for s, c in sorted(src_dist.items(), key=lambda x: -x[1]):
        print(f"  {s:18s} {c:>4d}  ({100*c/len(selected):.1f}%)")
    print(f"\n[STAT] work_context 분포:")
    for wc, c in sorted(wc_dist.items(), key=lambda x: -x[1]):
        print(f"  {wc:20s} {c:>4d}")

    # SR/CI 통계
    sr_total = sum(len(bd["sr_set"]) for bd in selected)
    ci_total = sum(len(bd["ci_set"]) for bd in selected)
    g_total = sum(len(bd["guide_set"]) for bd in selected)
    print(f"\n[STAT] ground truth 평균:")
    print(f"  SR/scenario:    {sr_total/len(selected):.1f}")
    print(f"  CI/scenario:    {ci_total/len(selected):.1f}")
    print(f"  Guide/scenario: {g_total/len(selected):.1f}")

    # 출력
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scenarios = [to_scenario(bd, i + 1) for i, bd in enumerate(selected)]
    with args.output.open("w", encoding="utf-8") as fh:
        for sc in scenarios:
            fh.write(json.dumps(sc, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"\n[OK] {args.output} 생성 완료 ({len(scenarios)} scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
