#!/usr/bin/env python3
"""Evaluate Guide recommendation quality on synthetic_observations_v1..v10.

This is intentionally separate from evaluate_synthetic_observations.py, which is
SHE/SR/penalty oriented.  Here the primary object is the top standard procedure:
whether it is supported by Guide-specific usage boundaries instead of generic
keywords or broad SRs alone.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import io
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.database import SessionLocal  # noqa: E402
from app.services import hazard_rule_engine  # noqa: E402
from app.services.analysis_pipeline import AnalysisRunInput, analysis_pipeline  # noqa: E402
from app.services.broad_sr_policy import get_broad_sr_ids  # noqa: E402

DEFAULT_INPUT_GLOB = PROJECT_ROOT / "pictures-json" / "synthetic_observations_v*.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "pictures-json" / "reports"
GUIDE_PROFILES_PATH = BACKEND_DIR / "app" / "data" / "guide_domain_profiles.json"

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
REFERENCE_PROCEDURE_ROLES = {
    "measurement_analysis",
    "test_protocol",
    "health_screening",
    "risk_method",
    "document_reference",
    "management_program",
}
WATCH_GUIDES = {
    "A-G-18-2026",
    "G-116-2014",
    "B-5-2011",
    "A-G-10-2025",
    "B-M-11-2025",
    "B-M-32-2026",
    "H-221-2023",
    "C-C-16-2026",
    "B-E-19-2026",
    "B-E-3-2025",
    "H-110-2013",
    "D-57-2016",
}
OBVIOUS_MISMATCH_CATEGORIES = {
    "visual_trigger_too_broad",
    "broad_sr_overreach",
    "industry_boundary_gap",
    "workprocess_mismatch",
}
OK_CATEGORIES = {"ok", "ok_no_procedure", "expected_no_procedure"}


def load_profiles(path: Path = GUIDE_PROFILES_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("profiles") or {}


def synthetic_paths(pattern: Path) -> list[Path]:
    return sorted(pattern.parent.glob(pattern.name))


def load_synthetic_rows(pattern: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in synthetic_paths(pattern):
        version = path.stem.removeprefix("synthetic_observations_")
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("version", version)
            row.setdefault("line_no", line_no)
            rows.append(row)
    return rows


def severity_for(case_type: str) -> tuple[str, float]:
    if case_type == "positive":
        return "HIGH", 0.92
    if case_type == "ambiguous":
        return "MEDIUM", 0.74
    return "LOW", 0.56


def synthetic_to_llm_result(row: dict[str, Any]) -> dict[str, Any]:
    severity, confidence = severity_for(str(row.get("case_type") or ""))
    visual_cues = [
        {"text": cue, "cue_type": "observable", "confidence": 0.86}
        for cue in row.get("visual_cues", []) or []
        if cue
    ]
    visual_cues.extend(
        {"text": cue, "cue_type": "uncertain", "confidence": 0.62}
        for cue in row.get("uncertain_cues", []) or []
        if cue
    )
    candidates: list[dict[str, Any]] = []
    expected = row.get("expected_features") or {}
    axis_map = {
        "accident_types": "accident_type",
        "hazardous_agents": "hazardous_agent",
        "work_contexts": "work_context",
    }
    for field, axis in axis_map.items():
        for code in expected.get(field, []) or []:
            candidates.append({
                "axis": axis,
                "text": str(code),
                "evidence": row.get("photo_description") or row.get("scene_description") or "synthetic observation",
                "confidence": confidence,
            })
    description = row.get("photo_description") or row.get("scene_description") or row.get("expected_primary_risk") or "synthetic observation"
    return {
        "visual_observations": [
            {
                "text": description,
                "confidence": confidence,
                "severity": severity,
            }
        ],
        "visual_cues": visual_cues,
        "risk_feature_candidates": candidates,
        "overall_assessment": row.get("expected_primary_risk") or "",
        "immediate_actions": [],
    }


def compact_procedure(procedure: Any) -> dict[str, Any] | None:
    if not procedure:
        return None
    return {
        "procedure_id": procedure.procedure_id,
        "title": procedure.title,
        "guide_code": procedure.guide_code,
        "confidence": procedure.confidence,
        "work_process": procedure.work_process,
        "step_count": len(procedure.steps),
        "top_steps": [step.model_dump(mode="json") for step in procedure.steps[:3]],
        "source_sr_ids": list(procedure.source_sr_ids or []),
        "source_ci_ids": list(procedure.source_ci_ids or []),
        "evidence_summary": procedure.evidence_summary,
    }


def compact_legacy(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "guide_code": row.get("guide_code"),
        "title": row.get("title"),
        "confidence": row.get("relevance_score"),
        "source_sr_ids": row.get("source_sr_ids") or [],
        "evidence_summary": row.get("mapping_type") or "legacy_ci_sr_fallback",
    }


def all_expected_feature_codes(row: dict[str, Any]) -> set[str]:
    expected = row.get("expected_features") or {}
    codes: set[str] = set()
    for field in ("accident_types", "hazardous_agents", "work_contexts"):
        codes.update(str(code) for code in expected.get(field, []) or [] if code)
    return codes


def row_text(row: dict[str, Any]) -> str:
    values: list[str] = [
        row.get("industry_context") or "",
        row.get("work_context") or "",
        row.get("photo_description") or "",
        row.get("scene_description") or "",
        row.get("expected_primary_risk") or "",
        row.get("expected_corrective_direction") or "",
        row.get("false_positive_risk") or "",
        row.get("notes_for_evaluation") or "",
    ]
    values.extend(row.get("visual_cues") or [])
    values.extend(row.get("uncertain_cues") or [])
    return " ".join(value for value in values if value).lower()


def profile_terms(profile: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    boundary = profile.get("recommendation_boundary") or {}
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
    return list(dict.fromkeys(terms))


def hit_terms(text: str, terms: list[str], limit: int = 5) -> list[str]:
    hits: list[str] = []
    for term in terms:
        lowered = term.lower()
        if lowered and lowered in text and term not in hits:
            hits.append(term)
        if len(hits) >= limit:
            break
    return hits


def visual_trigger_hits(row: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    text = row_text(row)
    triggers = [str(value) for value in profile.get("visual_triggers") or [] if value]
    triggers.extend(str(value) for value in profile.get("observable_required_cues") or [] if value)
    return hit_terms(text, list(dict.fromkeys(triggers)), limit=5)


def explicit_reference_role_hit(text: str, profile: dict[str, Any]) -> bool:
    role = str(profile.get("procedure_role") or "field_control")
    if role not in REFERENCE_PROCEDURE_ROLES:
        return True
    role_terms = {
        "measurement_analysis": ["작업환경측정", "분석", "시료", "검량선", "측정", "분석기"],
        "test_protocol": ["시험", "독성시험", "평가시험", "실험", "프로토콜"],
        "health_screening": ["건강진단", "검진", "의학적", "문진", "검사"],
        "risk_method": ["위험성평가", "평가 방법", "리스크 평가", "체크리스트 방법"],
        "document_reference": ["문서", "양식", "기록", "보고서", "매뉴얼"],
        "management_program": ["계획", "계획서", "프로그램", "절차서", "관리방안", "비상대피", "비상조치"],
    }[role]
    return bool(hit_terms(text, role_terms, limit=1))


def classify_top_procedure(
    *,
    row: dict[str, Any],
    procedure: dict[str, Any] | None,
    profiles: dict[str, Any],
    broad_sr_ids: set[str],
) -> tuple[str, str, dict[str, Any]]:
    case_type = str(row.get("case_type") or "")
    if not procedure:
        if case_type == "positive":
            return "missing_usage_profile", "positive case produced no standard procedure", {}
        return "ok_no_procedure", "no top procedure for non-positive case", {}

    guide_code = procedure.get("guide_code")
    profile = profiles.get(guide_code or "")
    if not profile:
        return "missing_usage_profile", "top Guide has no usage profile", {"guide_code": guide_code}

    text = row_text(row)
    term_hits = hit_terms(text, profile_terms(profile), limit=5)
    feature_hits = sorted(
        all_expected_feature_codes(row)
        & set(profile.get("feature_codes") or [])
        - GENERIC_FEATURE_CODES
    )
    visual_hits = visual_trigger_hits(row, profile)
    evidence_summary = str(procedure.get("evidence_summary") or "")
    source_sr_ids = set(procedure.get("source_sr_ids") or [])
    broad_only = bool(source_sr_ids) and source_sr_ids <= broad_sr_ids
    detail = {
        "guide_code": guide_code,
        "profile_level": profile.get("profile_level"),
        "procedure_role": profile.get("procedure_role"),
        "term_hits": term_hits,
        "visual_hits": visual_hits,
        "feature_hits": feature_hits,
        "source_sr_ids": sorted(source_sr_ids),
        "evidence_summary": evidence_summary,
    }

    if case_type == "negative":
        if broad_only:
            return "broad_sr_overreach", "negative case received broad-SR-only top Guide", detail
        return "industry_boundary_gap", "negative case received a standard procedure", detail

    if broad_only and not any(token in evidence_summary for token in ("SHE", "usage profile", "visual trigger", "feature")):
        return "broad_sr_overreach", "top Guide is supported only by broad SR ids", detail

    if str(profile.get("procedure_role") or "field_control") in REFERENCE_PROCEDURE_ROLES and not explicit_reference_role_hit(text, profile):
        return "industry_boundary_gap", "reference/method Guide lacks explicit method context", detail

    if "visual trigger" in evidence_summary and not visual_hits:
        return "visual_trigger_too_broad", "visual trigger evidence did not match row cues", detail

    if not (term_hits or feature_hits or visual_hits):
        return "industry_boundary_gap", "top Guide has no usage/profile/feature hit in row context", detail

    top_steps = procedure.get("top_steps") or []
    if top_steps:
        first = top_steps[0]
        step_text = " ".join(
            str(first.get(key) or "")
            for key in ("title", "safety_measures", "source_section")
        ).lower()
        if not hit_terms(step_text + " " + text, term_hits + feature_hits + visual_hits, limit=1):
            # Only flag this when the Guide matched but the displayed procedure is likely arbitrary.
            if len(top_steps) >= 2 and not (first.get("source_sr_ids") or []):
                return "workprocess_mismatch", "Guide matched but first WP step has no contextual/SR support", detail

    return "ok", "top Guide has Guide-specific support", detail


async def replay_row(db: Any, row: dict[str, Any]) -> Any:
    llm_result = synthetic_to_llm_result(row)
    description = row.get("photo_description") or row.get("scene_description") or row.get("case_id") or "synthetic observation"
    return await analysis_pipeline.run(
        db=db,
        run_input=AnalysisRunInput(
            result=llm_result,
            analysis_type="synthetic_guide_recommendation",
            input_preview=description[:120],
            full_description=" ".join(
                filter(None, [
                    row.get("industry_context"),
                    row.get("work_context"),
                    description,
                    row.get("expected_primary_risk"),
                ])
            ),
            declared_industry_text=row.get("industry_context"),
        ),
    )


def legacy_top_for(db: Any, response: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    sr_ids = list(response.reasoning_trace.safety_requirements or [])
    if not sr_ids:
        return None
    rows = hazard_rule_engine.get_guides_from_srs(
        db,
        sr_ids,
        limit=1,
        industry_contexts=[str(row.get("industry_context") or "")],
    )
    return compact_legacy(rows[0]) if rows else None


def build_record(
    row: dict[str, Any],
    response: Any,
    legacy_top: dict[str, Any] | None,
    profiles: dict[str, Any],
    broad_sr_ids: set[str],
) -> dict[str, Any]:
    top_procedure = compact_procedure(response.standard_procedures[0]) if response.standard_procedures else None
    current_category, current_reason, current_detail = classify_top_procedure(
        row=row,
        procedure=top_procedure,
        profiles=profiles,
        broad_sr_ids=broad_sr_ids,
    )
    legacy_category, legacy_reason, legacy_detail = classify_top_procedure(
        row=row,
        procedure=legacy_top,
        profiles=profiles,
        broad_sr_ids=broad_sr_ids,
    )
    return {
        "version": row.get("version"),
        "line_no": row.get("line_no"),
        "case_id": row.get("case_id"),
        "case_type": row.get("case_type"),
        "industry_context": row.get("industry_context"),
        "work_context": row.get("work_context"),
        "photo_description": row.get("photo_description") or row.get("scene_description"),
        "expected_primary_risk": row.get("expected_primary_risk"),
        "expected_corrective_direction": row.get("expected_corrective_direction"),
        "false_positive_risk": row.get("false_positive_risk"),
        "risk_feature_codes": [feature.code for feature in response.risk_features],
        "finding_status": response.finding_status,
        "penalty_exposure_status": response.penalty_exposure_status,
        "sr_ids": list(response.reasoning_trace.safety_requirements or []),
        "procedure_count": len(response.standard_procedures),
        "top_procedure": top_procedure,
        "legacy_top_procedure": legacy_top,
        "current_category": current_category,
        "current_reason": current_reason,
        "current_detail": current_detail,
        "legacy_category": legacy_category,
        "legacy_reason": legacy_reason,
        "legacy_detail": legacy_detail,
    }


def build_summary(records: list[dict[str, Any]], input_pattern: Path) -> dict[str, Any]:
    current_failures = Counter(
        record["current_category"] for record in records if record["current_category"] not in OK_CATEGORIES
    )
    legacy_failures = Counter(
        record["legacy_category"] for record in records if record["legacy_category"] not in OK_CATEGORIES
    )
    current_mismatches = [
        record for record in records if record["current_category"] in OBVIOUS_MISMATCH_CATEGORIES
    ]
    legacy_mismatches = [
        record for record in records if record["legacy_category"] in OBVIOUS_MISMATCH_CATEGORIES
    ]
    reduction = len(legacy_mismatches) - len(current_mismatches)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_pattern": str(input_pattern),
        "total_samples": len(records),
        "version_counts": dict(sorted(Counter(record.get("version") for record in records).items())),
        "case_type_counts": dict(sorted(Counter(record.get("case_type") for record in records).items())),
        "current_failure_counts": dict(sorted(current_failures.items())),
        "legacy_failure_counts": dict(sorted(legacy_failures.items())),
        "current_category_counts": dict(sorted(Counter(record["current_category"] for record in records).items())),
        "legacy_category_counts": dict(sorted(Counter(record["legacy_category"] for record in records).items())),
        "current_obvious_mismatch_count": len(current_mismatches),
        "legacy_obvious_mismatch_count": len(legacy_mismatches),
        "obvious_mismatch_reduction_count": reduction,
        "obvious_mismatch_reduction_ratio": round(reduction / len(legacy_mismatches), 4) if legacy_mismatches else None,
        "top_current_guides": dict(Counter(
            (record.get("top_procedure") or {}).get("guide_code") or "NO_TOP"
            for record in records
        ).most_common(30)),
        "top_legacy_guides": dict(Counter(
            (record.get("legacy_top_procedure") or {}).get("guide_code") or "NO_TOP"
            for record in records
        ).most_common(30)),
        "watch_guide_current_counts": dict(sorted(Counter(
            (record.get("top_procedure") or {}).get("guide_code")
            for record in records
            if (record.get("top_procedure") or {}).get("guide_code") in WATCH_GUIDES
        ).items())),
        "watch_guide_legacy_counts": dict(sorted(Counter(
            (record.get("legacy_top_procedure") or {}).get("guide_code")
            for record in records
            if (record.get("legacy_top_procedure") or {}).get("guide_code") in WATCH_GUIDES
        ).items())),
        "attention_count": sum(1 for record in records if record["current_category"] not in OK_CATEGORIES),
        "attention_cases": [attention_case(record) for record in records if record["current_category"] not in OK_CATEGORIES][:120],
    }


def attention_case(record: dict[str, Any]) -> dict[str, Any]:
    top = record.get("top_procedure") or {}
    return {
        "version": record.get("version"),
        "case_id": record.get("case_id"),
        "case_type": record.get("case_type"),
        "industry_context": record.get("industry_context"),
        "work_context": record.get("work_context"),
        "category": record.get("current_category"),
        "reason": record.get("current_reason"),
        "guide_code": top.get("guide_code"),
        "title": top.get("title"),
        "evidence_summary": top.get("evidence_summary"),
        "detail": record.get("current_detail"),
    }


def write_reports(summary: dict[str, Any], records: list[dict[str, Any]], output_dir: Path, prefix: str) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_dir / f"{prefix}_{timestamp}"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    md_path = base.with_suffix(".md")
    json_path.write_text(
        json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "version", "line_no", "case_id", "case_type", "industry_context", "work_context",
            "finding_status", "penalty_exposure_status", "procedure_count",
            "current_category", "current_reason", "legacy_category", "legacy_reason",
            "current_guide_code", "current_title", "current_evidence",
            "legacy_guide_code", "legacy_title", "legacy_evidence",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            current = record.get("top_procedure") or {}
            legacy = record.get("legacy_top_procedure") or {}
            writer.writerow({
                "version": record.get("version"),
                "line_no": record.get("line_no"),
                "case_id": record.get("case_id"),
                "case_type": record.get("case_type"),
                "industry_context": record.get("industry_context"),
                "work_context": record.get("work_context"),
                "finding_status": record.get("finding_status"),
                "penalty_exposure_status": record.get("penalty_exposure_status"),
                "procedure_count": record.get("procedure_count"),
                "current_category": record.get("current_category"),
                "current_reason": record.get("current_reason"),
                "legacy_category": record.get("legacy_category"),
                "legacy_reason": record.get("legacy_reason"),
                "current_guide_code": current.get("guide_code"),
                "current_title": current.get("title"),
                "current_evidence": current.get("evidence_summary"),
                "legacy_guide_code": legacy.get("guide_code"),
                "legacy_title": legacy.get("title"),
                "legacy_evidence": legacy.get("evidence_summary"),
            })
    md_path.write_text(build_markdown(summary, json_path, csv_path), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "md": md_path}


def build_markdown(summary: dict[str, Any], json_path: Path, csv_path: Path) -> str:
    lines = [
        "# Synthetic Guide Recommendation Evaluation",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- total_samples: `{summary['total_samples']}`",
        f"- current_obvious_mismatch_count: `{summary['current_obvious_mismatch_count']}`",
        f"- legacy_obvious_mismatch_count: `{summary['legacy_obvious_mismatch_count']}`",
        f"- obvious_mismatch_reduction_ratio: `{summary['obvious_mismatch_reduction_ratio']}`",
        f"- json: `{json_path}`",
        f"- csv: `{csv_path}`",
        "",
        "## Current Failure Counts",
        "",
    ]
    for key, value in summary["current_failure_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Watch Guide Current Counts", ""])
    for key, value in summary["watch_guide_current_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Top Attention Cases", ""])
    for record in summary["attention_cases"][:30]:
        lines.append(
            f"- `{record['case_id']}` {record['case_type']} / {record['industry_context']} -> "
            f"`{record['category']}` / `{record.get('guide_code')}` {record.get('title') or ''}"
        )
    lines.append("")
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    profiles = load_profiles()
    broad_sr_ids = get_broad_sr_ids()
    rows = load_synthetic_rows(args.input_glob)
    if args.limit:
        rows = rows[: args.limit]

    # The evaluator should not create product analysis records.
    analysis_pipeline._persist_response = lambda *_, **__: None  # type: ignore[method-assign]

    records: list[dict[str, Any]] = []
    db = SessionLocal()
    try:
        for index, row in enumerate(rows, start=1):
            if args.verbose_pipeline:
                response = await replay_row(db, row)
            else:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    response = await replay_row(db, row)
            legacy = legacy_top_for(db, response, row)
            records.append(build_record(row, response, legacy, profiles, broad_sr_ids))
            if args.progress and index % args.progress == 0:
                print(f"processed {index}/{len(rows)}", flush=True)
    finally:
        db.close()

    summary = build_summary(records, args.input_glob)
    paths = write_reports(summary, records, args.output_dir, args.report_prefix)
    print(json.dumps({"summary": summary, "outputs": {k: str(v) for k, v in paths.items()}}, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-glob", type=Path, default=DEFAULT_INPUT_GLOB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-prefix", default="synthetic_guide_recommendations_v1_v10_usage_profile1")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--progress", type=int, default=100)
    parser.add_argument("--verbose-pipeline", action="store_true")
    return parser.parse_args()


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
