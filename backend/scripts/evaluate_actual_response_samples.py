#!/usr/bin/env python3
"""Replay the 240 actual response samples against the current OHS runtime.

The source report keeps the synthetic-but-product-shaped LLM observations
(`llm_result`) plus the previous compact response.  This script reuses those
LLM observations and calls the current analysis pipeline, so the diff isolates
changes in PostgreSQL data, ontology mappings, and recommendation logic.
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
from app.services.analysis_pipeline import AnalysisRunInput, analysis_pipeline  # noqa: E402


DEFAULT_SOURCE_REPORT = (
    PROJECT_ROOT
    / "pictures-json"
    / "reports"
    / "actual_response_samples_v1_v10_by_industry_safe_negative_20260507_234209.json"
)
DEFAULT_COMPARISON_REPORT = (
    PROJECT_ROOT
    / "pictures-json"
    / "reports"
    / "actual_response_samples_v1_v10_after_pipeb1038_20260509_072955.json"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "pictures-json" / "reports"

OK_BUCKETS = {"legacy_ok", "ambiguous_ok", "negative_ok"}


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    records = report.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError(f"source report has no records: {path}")
    missing = [
        record.get("case_id") or index + 1
        for index, record in enumerate(records)
        if not isinstance(record.get("llm_result"), dict)
    ]
    if missing:
        preview = ", ".join(str(item) for item in missing[:10])
        raise ValueError(
            "source report records must include llm_result. "
            f"Missing examples: {preview}"
        )
    return report


def load_comparison_records(path: Path | None) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    if not path:
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError(f"comparison report has no records: {path}")
    return {record_key(record): record for record in records}


def record_key(record: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        record.get("version"),
        record.get("case_id"),
        record.get("sample_no"),
    )


async def replay_record(db, record: dict[str, Any]) -> dict[str, Any]:
    description = record.get("description") or record.get("case_id") or ""
    input_preview = description[:100] + "..." if len(description) > 100 else description
    response = await analysis_pipeline.run(
        db=db,
        run_input=AnalysisRunInput(
            result=record["llm_result"],
            analysis_type="actual_response_sample",
            input_preview=input_preview,
            full_description=description,
            declared_industry_text=record.get("industry_context"),
        ),
    )
    return compact_response(response)


def compact_response(response) -> dict[str, Any]:
    top_situation = response.situation_matches[0] if response.situation_matches else None
    top_penalty = response.penalty_paths[0] if response.penalty_paths else None
    top_action = response.immediate_actions[0] if response.immediate_actions else None
    top_procedure = response.standard_procedures[0] if response.standard_procedures else None
    return {
        "finding_status": response.finding_status,
        "penalty_exposure_status": response.penalty_exposure_status,
        "overall_risk_level": response.overall_risk_level.value,
        "risk_feature_codes": [feature.code for feature in response.risk_features],
        "situation_count": len(response.situation_matches),
        "top_situation": top_situation.model_dump(mode="json") if top_situation else None,
        "sr_count": len(response.reasoning_trace.safety_requirements),
        "penalty_count": len(response.penalty_paths),
        "top_penalty": top_penalty.model_dump(mode="json") if top_penalty else None,
        "action_count": len(response.immediate_actions),
        "top_action": top_action.model_dump(mode="json") if top_action else None,
        "procedure_count": len(response.standard_procedures),
        "top_procedure": compact_procedure(top_procedure),
    }


def compact_procedure(procedure) -> dict[str, Any] | None:
    if not procedure:
        return None
    return {
        "procedure_id": procedure.procedure_id,
        "title": procedure.title,
        "description": procedure.description,
        "guide_code": procedure.guide_code,
        "work_process": procedure.work_process,
        "confidence": procedure.confidence,
        "step_count": len(procedure.steps),
        "top_steps": [
            step.model_dump(mode="json")
            for step in procedure.steps[:3]
        ],
        "source_sr_ids": procedure.source_sr_ids,
        "source_ci_ids": procedure.source_ci_ids,
        "evidence_summary": procedure.evidence_summary,
    }


def classify_bucket(case_type: str, status: str, penalty: str, expected_status: str, expected_penalty: str) -> str:
    if case_type == "negative":
        return "negative_ok" if status == "not_determined" and penalty == "no_penalty" else "negative_false_positive"
    if case_type == "ambiguous":
        if status == "confirmed" and penalty == "direct":
            return "ambiguous_over_promoted"
        if status == "not_determined" and penalty == "no_penalty":
            return "ambiguous_under_matched"
        return "ambiguous_ok"
    if status == "not_determined":
        return "positive_missed"
    if status == expected_status and penalty == expected_penalty:
        return "legacy_ok"
    if status == "confirmed" and penalty == "direct":
        return "legacy_mismatch"
    return "positive_boundary_demoted"


def top_title(compact: dict[str, Any], key: str) -> str | None:
    value = compact.get(key)
    return value.get("title") if isinstance(value, dict) else None


def build_output_record(
    record: dict[str, Any],
    compact: dict[str, Any],
    comparison_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_source = comparison_record or record
    previous = previous_source.get("compact_response") or {}
    status = compact["finding_status"]
    penalty = compact["penalty_exposure_status"]
    bucket = classify_bucket(
        case_type=record.get("case_type", ""),
        status=status,
        penalty=penalty,
        expected_status=record.get("expected_legacy_status", ""),
        expected_penalty=record.get("expected_legacy_penalty", ""),
    )
    return {
        "sample_no": record.get("sample_no"),
        "version": record.get("version"),
        "industry_context": record.get("industry_context"),
        "case_id": record.get("case_id"),
        "case_type": record.get("case_type"),
        "work_context": record.get("work_context"),
        "description": record.get("description"),
        "expected_legacy_status": record.get("expected_legacy_status"),
        "expected_legacy_penalty": record.get("expected_legacy_penalty"),
        "previous_status": previous_source.get("actual_status") or previous.get("finding_status"),
        "previous_penalty": previous_source.get("actual_penalty") or previous.get("penalty_exposure_status"),
        "previous_bucket": previous_source.get("bucket"),
        "actual_status": status,
        "actual_penalty": penalty,
        "bucket": bucket,
        "status_changed": (previous_source.get("actual_status") or previous.get("finding_status")) != status,
        "top_action_changed": top_title(previous, "top_action") != top_title(compact, "top_action"),
        "top_procedure_changed": top_title(previous, "top_procedure") != top_title(compact, "top_procedure"),
        "old_compact_response": previous,
        "compact_response": compact,
    }


def build_summary(
    records: list[dict[str, Any]],
    source_report: Path,
    comparison_report: Path | None,
    database_note: str,
) -> dict[str, Any]:
    by_case_type: dict[str, dict[str, Any]] = {}
    for case_type, grouped in group_by(records, "case_type").items():
        by_case_type[case_type] = {
            "samples": len(grouped),
            "statuses": dict(Counter(record["actual_status"] for record in grouped)),
            "penalties": dict(Counter(record["actual_penalty"] for record in grouped)),
            "buckets": dict(Counter(record["bucket"] for record in grouped)),
        }

    attention_cases = [record for record in records if record["bucket"] not in OK_BUCKETS]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_report": str(source_report),
        "comparison_report": str(comparison_report) if comparison_report else None,
        "database_note": database_note,
        "total_samples": len(records),
        "case_type_counts": dict(Counter(record.get("case_type") for record in records)),
        "previous_status_counts": dict(Counter(record.get("previous_status") for record in records)),
        "actual_status_counts": dict(Counter(record["actual_status"] for record in records)),
        "previous_penalty_counts": dict(Counter(record.get("previous_penalty") for record in records)),
        "actual_penalty_counts": dict(Counter(record["actual_penalty"] for record in records)),
        "previous_bucket_counts": dict(Counter(record.get("previous_bucket") for record in records)),
        "bucket_counts": dict(Counter(record["bucket"] for record in records)),
        "status_changed_count": sum(1 for record in records if record["status_changed"]),
        "top_action_changed_count": sum(1 for record in records if record["top_action_changed"]),
        "top_procedure_changed_count": sum(1 for record in records if record["top_procedure_changed"]),
        "by_case_type": by_case_type,
        "attention_count": len(attention_cases),
        "attention_cases": [attention_case(record) for record in attention_cases],
    }


def group_by(records: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key) or "")].append(record)
    return dict(grouped)


def attention_case(record: dict[str, Any]) -> dict[str, Any]:
    compact = record["compact_response"]
    top_situation = compact.get("top_situation") or {}
    return {
        "version": record.get("version"),
        "industry_context": record.get("industry_context"),
        "case_id": record.get("case_id"),
        "case_type": record.get("case_type"),
        "previous": [
            record.get("previous_status"),
            record.get("previous_penalty"),
            record.get("previous_bucket"),
        ],
        "actual": [
            record.get("actual_status"),
            record.get("actual_penalty"),
            record.get("bucket"),
        ],
        "top_situation": top_situation.get("title"),
        "top_action": top_title(compact, "top_action"),
        "top_procedure": top_title(compact, "top_procedure"),
    }


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Actual Response Samples Replay",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Source report: `{summary['source_report']}`",
        f"- Comparison report: `{summary['comparison_report']}`",
        f"- Database note: {summary['database_note']}",
        f"- Total samples: {summary['total_samples']}",
        f"- Status counts: `{summary['actual_status_counts']}`",
        f"- Penalty counts: `{summary['actual_penalty_counts']}`",
        f"- Buckets: `{summary['bucket_counts']}`",
        f"- Status changed: {summary['status_changed_count']}",
        f"- Top action changed: {summary['top_action_changed_count']}",
        f"- Top procedure changed: {summary['top_procedure_changed_count']}",
        "",
        "## Attention Cases",
        "",
    ]
    for case in summary["attention_cases"]:
        lines.append(
            "- "
            f"{case['version']} / {case['industry_context']} / {case['case_id']} / {case['case_type']}: "
            f"previous={case['previous']} actual={case['actual']}"
        )
        if case.get("top_action"):
            lines.append(f"  - top_action: {case['top_action']}")
        if case.get("top_procedure"):
            lines.append(f"  - top_procedure: {case['top_procedure']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "sample_no",
        "version",
        "industry_context",
        "case_id",
        "case_type",
        "work_context",
        "previous_status",
        "previous_penalty",
        "previous_bucket",
        "actual_status",
        "actual_penalty",
        "bucket",
        "status_changed",
        "top_action_changed",
        "top_procedure_changed",
        "top_situation",
        "top_action",
        "top_procedure",
        "description",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            compact = record["compact_response"]
            top_situation = compact.get("top_situation") or {}
            writer.writerow({
                **{name: record.get(name) for name in fieldnames},
                "top_situation": top_situation.get("title"),
                "top_action": top_title(compact, "top_action"),
                "top_procedure": top_title(compact, "top_procedure"),
            })


async def replay_records(
    source_records: list[dict[str, Any]],
    comparison_records: dict[tuple[Any, Any, Any], dict[str, Any]],
    limit: int | None,
    show_runtime_log: bool,
) -> list[dict[str, Any]]:
    # Evaluation should not create product analysis history rows.
    original_persist = analysis_pipeline._persist_response
    analysis_pipeline._persist_response = lambda *args, **kwargs: None
    db = SessionLocal()
    try:
        records = []
        for record in source_records[:limit]:
            if show_runtime_log:
                compact = await replay_record(db, record)
            else:
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    compact = await replay_record(db, record)
            records.append(
                build_output_record(
                    record,
                    compact,
                    comparison_record=comparison_records.get(record_key(record)),
                )
            )
        return records
    finally:
        db.close()
        analysis_pipeline._persist_response = original_persist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, default=DEFAULT_SOURCE_REPORT)
    parser.add_argument("--comparison-report", type=Path, default=DEFAULT_COMPARISON_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-prefix", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--show-runtime-log", action="store_true")
    parser.add_argument(
        "--database-note",
        default="current OHS runtime / current PostgreSQL ontology data",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_report = args.source_report.resolve()
    comparison_report = args.comparison_report.resolve() if args.comparison_report else None
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = load_report(source_report)
    comparison_records = load_comparison_records(comparison_report)
    source_records = report["records"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.report_prefix or f"actual_response_samples_replay_{timestamp}"

    records = asyncio.run(
        replay_records(
            source_records,
            comparison_records,
            args.limit,
            args.show_runtime_log,
        )
    )
    summary = build_summary(records, source_report, comparison_report, args.database_note)
    output = {"summary": summary, "records": records}

    json_path = output_dir / f"{prefix}.json"
    md_path = output_dir / f"{prefix}.md"
    csv_path = output_dir / f"{prefix}.csv"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, summary)
    write_csv(csv_path, records)

    print("=== Actual Response Samples Replay ===")
    print(f"source: {source_report}")
    print(f"comparison: {comparison_report}")
    print(f"samples: {summary['total_samples']}")
    print(f"status counts: {summary['actual_status_counts']}")
    print(f"penalty counts: {summary['actual_penalty_counts']}")
    print(f"bucket counts: {summary['bucket_counts']}")
    print(f"status changed: {summary['status_changed_count']}")
    print(f"top action changed: {summary['top_action_changed_count']}")
    print(f"top procedure changed: {summary['top_procedure_changed_count']}")
    print(f"wrote: {json_path}")
    print(f"wrote: {md_path}")
    print(f"wrote: {csv_path}")


if __name__ == "__main__":
    main()
