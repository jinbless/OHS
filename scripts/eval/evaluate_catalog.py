#!/usr/bin/env python3
"""Phase 0.4 — Catalog Baseline 평가: scenarios-v1.jsonl을 OHS analysis_service에
직접 입력 → 추천된 Guide/SR/CI를 ground truth와 비교 → metric 산출.

Direct module invocation (HTTP API와 동일한 코드 path):
  scenario.description → analysis_service.analyze_text(db, description, ...)
  → AnalysisResponse → 추천 정보 추출

Metrics (2026-04-27 사용자 통찰 반영 — CI는 Guide 종속 단위):
  PRIMARY:
    G_Recall@k, G_Precision@k, G_F1  (Guide-level — 작업 절차 단위, 라벨링과 일치)
    SR_Recall@k                       (SPARQL enrichment + recommended_srs)
  SECONDARY:
    forced_fit_rate                   (code_gap_warnings 발생률)
    divergence_rate
    work_context F1 분산
    latency p50/p95
  DEPRECATED:
    CI Precision/F1                   (CI는 가이드 implementation detail로 재정의 —
                                        Guide 평가가 의미 단위. legacy로만 유지)

Output:
  OHS/data/eval/baseline-v1.report.md
  OHS/data/eval/baseline-v1.report.json (raw per-scenario)

실행:
  PYTHONUTF8=1 PYTHONPATH=OHS/backend python OHS/scripts/eval/evaluate_catalog.py
  PYTHONUTF8=1 PYTHONPATH=OHS/backend python OHS/scripts/eval/evaluate_catalog.py --limit 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[3]
OHS_DIR = ROOT / "OHS"
INPUT = OHS_DIR / "data" / "eval" / "scenarios-v1.jsonl"
OUTPUT_REPORT_MD = OHS_DIR / "data" / "eval" / "baseline-v1.report.md"
OUTPUT_REPORT_JSON = OHS_DIR / "data" / "eval" / "baseline-v1.report.json"

# Add OHS/backend to PYTHONPATH so app module imports work
sys.path.insert(0, str(OHS_DIR / "backend"))

# Ensure OPENAI_API_KEY is in env (analysis_service uses openai_client which reads from settings)
if not os.environ.get("OPENAI_API_KEY"):
    env_file = OHS_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                break


# ────────────────────────────────────────────────────────────────────────
# Guide code normalizer — backend uses "B-M-17-2026" / sr-registry uses "BM17".
# 둘을 같은 정규형으로 정렬.
# ────────────────────────────────────────────────────────────────────────

def normalize_guide_code(code: str) -> str:
    """Guide code 정규화.

    Examples:
      "B-M-17-2026" → "BM17"
      "A-G-18-2026" → "AG18"
      "G-60-2012"   → "G60"
      "DC10"        → "DC10"
      "AG18"        → "AG18"
    """
    if not code:
        return ""
    parts = code.split("-")
    # 마지막 4자리 숫자(연도) 제거
    if parts and len(parts[-1]) == 4 and parts[-1].isdigit():
        parts = parts[:-1]
    return "".join(parts)


def normalize_guides(codes: list[str]) -> list[str]:
    """Guide code 리스트를 정규화 + 중복 제거 (순서 보존)."""
    seen = set()
    out = []
    for c in codes:
        n = normalize_guide_code(c)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ────────────────────────────────────────────────────────────────────────
# Metric helpers
# ────────────────────────────────────────────────────────────────────────

def recall_at_k(recommended: list[str], ground_truth: list[str], k: int) -> float:
    if not ground_truth:
        return 0.0
    top_k = set(recommended[:k])
    hit = len(top_k & set(ground_truth))
    return hit / len(set(ground_truth))


def precision_at_k(recommended: list[str], ground_truth: list[str], k: int) -> float:
    if not recommended:
        return 0.0
    top_k = recommended[:k]
    if not top_k:
        return 0.0
    hit = len(set(top_k) & set(ground_truth))
    return hit / len(top_k)


def f1(p: float, r: float) -> float:
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


# ────────────────────────────────────────────────────────────────────────
# Per-scenario evaluation
# ────────────────────────────────────────────────────────────────────────

async def evaluate_one(
    analysis_service,
    db,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """1 시나리오를 OHS에 입력 → 추천 추출 → metric 계산."""
    desc = scenario["description"]
    gt = scenario["ground_truth"]
    sr_set_gt = set(gt.get("sr_set") or [])
    ci_set_gt = set(gt.get("ci_set") or [])
    guide_set_gt = set(gt.get("guide_set") or [])

    t0 = time.monotonic()
    try:
        resp = await analysis_service.analyze_text(
            db=db,
            description=desc,
            workplace_type=None,
            industry_sector=None,
        )
    except Exception as e:
        return {
            "scenario_id": scenario["scenario_id"],
            "work_context": scenario.get("work_context"),
            "source": scenario.get("source"),
            "error": str(e)[:300],
            "latency_s": time.monotonic() - t0,
        }
    latency_s = time.monotonic() - t0

    # ── Guide 추천 추출 (관계_guides) — 정규화 적용 ──
    rec_guides_raw = [g.guide_code for g in (resp.related_guides or [])]
    rec_guides = normalize_guides(rec_guides_raw)
    guide_set_gt_norm = set(normalize_guide_code(g) for g in guide_set_gt)

    # ── SR 추천 추출 (Phase 0.5: recommended_srs 우선 + sparql fallback) ──
    rec_srs: list[str] = []
    rec_srs_detail: list[dict] = []  # source/layer/confidence 포함

    # 1순위: Phase 0.5에서 추가된 recommended_srs (primary + coApplicable + ...)
    for r_sr in (resp.recommended_srs or []):
        sid = r_sr.identifier
        if sid and sid not in rec_srs:
            rec_srs.append(sid)
            rec_srs_detail.append({
                "identifier": sid,
                "source": r_sr.source,
                "layer": r_sr.layer,
                "confidence": r_sr.confidence,
            })

    # 2순위 fallback: sparql_enrichment (recommended_srs 비어있는 구버전 호환)
    if not rec_srs:
        sparql_enrich = resp.sparql_enrichment
        if sparql_enrich:
            for co_sr in (sparql_enrich.co_applicable_srs or []):
                sid = co_sr.get("sr_id") if isinstance(co_sr, dict) else None
                if sid:
                    rec_srs.append(sid)

    # ── CI: source_ref/text fuzzy. v1 응답에는 CI ID 직접 노출 없음.
    #     단순 추출은 어려우므로 CI 수만 카운트 (CI Recall은 SR Recall이 proxy)
    rec_ci_texts = [item.item for item in (resp.checklist.items if resp.checklist else [])]

    # ── 메트릭 (정규화된 guide_code 사용) ──
    g_r5 = recall_at_k(rec_guides, list(guide_set_gt_norm), 5)
    g_r10 = recall_at_k(rec_guides, list(guide_set_gt_norm), 10)
    g_p5 = precision_at_k(rec_guides, list(guide_set_gt_norm), 5)
    g_f1 = f1(g_p5, g_r5)

    sr_r5 = recall_at_k(rec_srs, list(sr_set_gt), 5) if rec_srs else 0.0
    sr_r10 = recall_at_k(rec_srs, list(sr_set_gt), 10) if rec_srs else 0.0

    forced = len(resp.code_gap_warnings or [])
    forced_fit = forced > 0

    can = resp.canonical_hazards
    can_wc = (can.work_contexts if can else []) or []
    wc_match = scenario.get("work_context") in can_wc if scenario.get("work_context") else False

    return {
        "scenario_id": scenario["scenario_id"],
        "work_context": scenario.get("work_context"),
        "source": scenario.get("source"),
        "ground_truth_size": {
            "sr": len(sr_set_gt),
            "ci": len(ci_set_gt),
            "guide": len(guide_set_gt),
        },
        "recommended": {
            "guides_raw": rec_guides_raw,
            "guides_normalized": rec_guides,
            "srs": rec_srs,
            "srs_detail": rec_srs_detail,  # Phase 0.5 source/layer/confidence
            "ci_count": len(rec_ci_texts),
        },
        "ground_truth_normalized": {
            "guides": sorted(guide_set_gt_norm),
        },
        "metrics": {
            "guide_recall_5": g_r5,
            "guide_recall_10": g_r10,
            "guide_precision_5": g_p5,
            "guide_f1": g_f1,
            "sr_recall_5": sr_r5,
            "sr_recall_10": sr_r10,
            "forced_fit": forced_fit,
            "forced_fit_count": forced,
            "wc_match": wc_match,
            "latency_s": latency_s,
        },
        "canonical_hazards": {
            "accident_types": (can.accident_types if can else []) or [],
            "hazardous_agents": (can.hazardous_agents if can else []) or [],
            "work_contexts": can_wc,
        },
    }


# ────────────────────────────────────────────────────────────────────────
# Aggregate + Report
# ────────────────────────────────────────────────────────────────────────

def aggregate(per_scenario: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in per_scenario if not r.get("error")]
    errors = [r for r in per_scenario if r.get("error")]

    def avg(key_path: list[str]) -> float:
        vals = []
        for r in valid:
            v = r
            for k in key_path:
                v = v.get(k, {}) if isinstance(v, dict) else None
                if v is None:
                    break
            if isinstance(v, (int, float)):
                vals.append(float(v))
            elif isinstance(v, bool):
                vals.append(1.0 if v else 0.0)
        return statistics.mean(vals) if vals else 0.0

    def percentile(key_path: list[str], p: float) -> float:
        vals = []
        for r in valid:
            v = r
            for k in key_path:
                v = v.get(k, {}) if isinstance(v, dict) else None
                if v is None:
                    break
            if isinstance(v, (int, float)):
                vals.append(float(v))
        if not vals:
            return 0.0
        vals.sort()
        idx = max(0, min(len(vals) - 1, int(round(p * (len(vals) - 1)))))
        return vals[idx]

    overall = {
        "n_total": len(per_scenario),
        "n_valid": len(valid),
        "n_error": len(errors),
        "guide_recall_5": avg(["metrics", "guide_recall_5"]),
        "guide_recall_10": avg(["metrics", "guide_recall_10"]),
        "guide_precision_5": avg(["metrics", "guide_precision_5"]),
        "guide_f1": avg(["metrics", "guide_f1"]),
        "sr_recall_5": avg(["metrics", "sr_recall_5"]),
        "sr_recall_10": avg(["metrics", "sr_recall_10"]),
        "forced_fit_rate": avg(["metrics", "forced_fit"]),
        "forced_fit_avg_count": avg(["metrics", "forced_fit_count"]),
        "wc_match_rate": avg(["metrics", "wc_match"]),
        "latency_p50_s": percentile(["metrics", "latency_s"], 0.5),
        "latency_p95_s": percentile(["metrics", "latency_s"], 0.95),
    }

    # work_context 별 F1 분산
    by_wc: dict[str, list[float]] = defaultdict(list)
    for r in valid:
        wc = r.get("work_context") or "ETC"
        by_wc[wc].append(r["metrics"]["guide_f1"])
    wc_stats: dict[str, Any] = {}
    for wc, vs in by_wc.items():
        wc_stats[wc] = {
            "n": len(vs),
            "guide_f1_mean": statistics.mean(vs) if vs else 0.0,
            "guide_f1_stdev": statistics.stdev(vs) if len(vs) >= 2 else 0.0,
        }
    if len(wc_stats) >= 2:
        means = [s["guide_f1_mean"] for s in wc_stats.values()]
        overall["work_context_f1_variance"] = statistics.variance(means)
    else:
        overall["work_context_f1_variance"] = 0.0

    # source 별
    by_src: dict[str, list[float]] = defaultdict(list)
    for r in valid:
        by_src[r.get("source", "?")].append(r["metrics"]["guide_f1"])
    src_stats = {
        s: {"n": len(vs), "guide_f1_mean": statistics.mean(vs) if vs else 0.0}
        for s, vs in by_src.items()
    }

    return {
        "overall": overall,
        "by_work_context": wc_stats,
        "by_source": src_stats,
        "errors": errors[:10],  # 처음 10개만
    }


def write_md_report(agg: dict[str, Any], path: Path):
    overall = agg["overall"]
    by_wc = agg["by_work_context"]
    by_src = agg["by_source"]

    lines = []
    lines.append("# Phase 0 Catalog Baseline Report (v1)")
    lines.append("")
    lines.append(f"생성: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"시나리오: {overall['n_valid']}/{overall['n_total']} 성공 ({overall['n_error']} 실패)")
    lines.append("")
    lines.append("**Metric 평가 단위 (2026-04-27 사용자 통찰 반영)**:")
    lines.append("- **Guide (작업 절차)** = primary — 사용자에게 의미 있는 단위. 라벨링과 일치.")
    lines.append("- **SR (법령 의무)** = primary — 독립 단위.")
    lines.append("- **CI (체크 항목)** = Guide 종속 implementation detail — 개별 평가 X. Guide 매칭 시 자동 follow.")
    lines.append("")
    lines.append("## Primary Metrics")
    lines.append("")
    lines.append("| Metric | Value | 평가 단위 |")
    lines.append("|---|---:|---|")
    lines.append(f"| **Guide Recall@5** ★ | {overall['guide_recall_5']:.3f} | 작업 절차 |")
    lines.append(f"| **Guide Recall@10** ★ | {overall['guide_recall_10']:.3f} | 작업 절차 |")
    lines.append(f"| **Guide Precision@5** ★ | {overall['guide_precision_5']:.3f} | 작업 절차 |")
    lines.append(f"| **Guide F1** ★ | {overall['guide_f1']:.3f} | 작업 절차 |")
    lines.append(f"| **SR Recall@5** ★ | {overall['sr_recall_5']:.3f} | 법령 의무 |")
    lines.append(f"| **SR Recall@10** ★ | {overall['sr_recall_10']:.3f} | 법령 의무 |")
    lines.append("")
    lines.append("## Secondary Metrics (시스템 건강도)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Forced-fit Rate | {overall['forced_fit_rate']:.1%} |")
    lines.append(f"| Forced-fit Avg Count | {overall['forced_fit_avg_count']:.2f} |")
    lines.append(f"| Work-context Match Rate | {overall['wc_match_rate']:.1%} |")
    lines.append(f"| work_context F1 Variance | {overall['work_context_f1_variance']:.4f} |")
    lines.append(f"| Latency p50 | {overall['latency_p50_s']:.2f}s |")
    lines.append(f"| Latency p95 | {overall['latency_p95_s']:.2f}s |")
    lines.append("")
    lines.append("## By work_context")
    lines.append("")
    lines.append("| work_context | n | Guide F1 mean | F1 stdev |")
    lines.append("|---|---:|---:|---:|")
    for wc, s in sorted(by_wc.items(), key=lambda x: -x[1]["guide_f1_mean"]):
        lines.append(f"| {wc} | {s['n']} | {s['guide_f1_mean']:.3f} | {s['guide_f1_stdev']:.3f} |")
    lines.append("")
    lines.append("## By source")
    lines.append("")
    lines.append("| source | n | Guide F1 mean |")
    lines.append("|---|---:|---:|")
    for s_name, s_data in sorted(by_src.items(), key=lambda x: -x[1]["guide_f1_mean"]):
        lines.append(f"| {s_name} | {s_data['n']} | {s_data['guide_f1_mean']:.3f} |")
    lines.append("")

    # Sanity gates
    lines.append("## Phase 0 Sanity Gates")
    lines.append("")
    gate_g1 = "PASS" if overall["guide_recall_10"] >= 0.30 else "FAIL"
    gate_g2 = "PASS" if overall["work_context_f1_variance"] <= 0.30 else "FAIL"
    lines.append(f"- [{gate_g1}] Guide Recall@10 ≥ 30%: {overall['guide_recall_10']:.1%}")
    lines.append(f"- [{gate_g2}] work_context F1 variance ≤ 0.30: {overall['work_context_f1_variance']:.4f}")
    lines.append(f"- [INFO] forced_fit baseline: {overall['forced_fit_rate']:.1%} (Phase 1 개선 목표)")
    lines.append("")

    if agg["errors"]:
        lines.append("## Errors (first 10)")
        lines.append("")
        for e in agg["errors"]:
            lines.append(f"- {e['scenario_id']}: {e.get('error', '')[:100]}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────

async def main_async(args):
    # Lazy import (after sys.path setup)
    from app.db.database import SessionLocal, create_tables
    from app.services.analysis_service import analysis_service

    # Tables
    try:
        create_tables()
    except Exception as e:
        print(f"[WARN] create_tables: {e}")

    scenarios = []
    with args.input.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            sc = json.loads(line)
            if sc.get("description"):
                scenarios.append(sc)
    print(f"[INFO] {len(scenarios)} scenarios with description")

    if args.pilot_wcs:
        wcs = set(args.pilot_wcs.split(","))
        before = len(scenarios)
        scenarios = [s for s in scenarios if s.get("work_context") in wcs]
        print(f"[INFO] pilot_wcs={wcs} filter: {before} → {len(scenarios)}")
    if args.limit:
        scenarios = scenarios[:args.limit]
        print(f"[INFO] limit={args.limit} applied → {len(scenarios)}")

    sem = asyncio.Semaphore(args.batch)

    results: list[dict] = [None] * len(scenarios)  # type: ignore

    async def worker(idx: int, sc: dict):
        async with sem:
            db = SessionLocal()
            try:
                r = await evaluate_one(analysis_service, db, sc)
                results[idx] = r
                m = r.get("metrics") or {}
                print(f"  [{idx+1:3d}/{len(scenarios)}] "
                      f"{sc['scenario_id']}  G_R@10={m.get('guide_recall_10', 0):.2f}  "
                      f"SR_R@10={m.get('sr_recall_10', 0):.2f}  "
                      f"forced={int(m.get('forced_fit_count', 0))}  "
                      f"lat={m.get('latency_s', 0):.1f}s"
                      + (f"  ERR" if r.get("error") else ""))
            finally:
                db.close()

    print(f"\n[STEP] Catalog baseline evaluation (batch={args.batch})...")
    t_start = time.monotonic()
    await asyncio.gather(*[worker(i, sc) for i, sc in enumerate(scenarios)])
    elapsed = time.monotonic() - t_start
    print(f"\n[OK] {len(scenarios)} 시나리오 평가 완료 ({elapsed:.1f}s)")

    # Aggregate + report
    agg = aggregate(results)

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("w", encoding="utf-8") as fh:
        json.dump({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input_file": str(args.input),
            "total_elapsed_s": elapsed,
            "aggregate": agg,
            "per_scenario": results,
        }, fh, ensure_ascii=False, indent=2)
    print(f"[OK] {args.output_json}")

    write_md_report(agg, args.output_md)
    print(f"[OK] {args.output_md}")

    # 요약 출력
    o = agg["overall"]
    print("\n" + "=" * 60)
    print(f"  Guide Recall@10: {o['guide_recall_10']:.3f}")
    print(f"  Guide Precision@5: {o['guide_precision_5']:.3f}")
    print(f"  Guide F1: {o['guide_f1']:.3f}")
    print(f"  SR Recall@10: {o['sr_recall_10']:.3f}")
    print(f"  Forced-fit Rate: {o['forced_fit_rate']:.1%}")
    print(f"  Latency p50/p95: {o['latency_p50_s']:.1f}s / {o['latency_p95_s']:.1f}s")
    print(f"  Sanity gate G_R@10≥30%: {'PASS' if o['guide_recall_10'] >= 0.30 else 'FAIL'}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output-md", type=Path, default=OUTPUT_REPORT_MD)
    parser.add_argument("--output-json", type=Path, default=OUTPUT_REPORT_JSON)
    parser.add_argument("--limit", type=int, default=None,
                        help="최대 시나리오 수 (sanity check 용)")
    parser.add_argument("--pilot-wcs", type=str, default=None,
                        help="콤마-구분 work_context 필터 (예: SCAFFOLD,EXCAVATION,MACHINE)")
    parser.add_argument("--batch", type=int, default=3,
                        help="동시 호출 수 (default 3 — backend OpenAI rate limit 보호)")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
