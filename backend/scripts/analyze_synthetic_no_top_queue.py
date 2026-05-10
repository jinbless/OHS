#!/usr/bin/env python3
"""Classify NO_TOP positive cases from synthetic Guide recommendation reports.

The Guide evaluator intentionally reports positive rows with no standard
procedure as `missing_usage_profile`.  This helper separates those rows into
fixture gaps, taxonomy gaps, and Guide usage-profile gaps so the next repair
step is structural instead of keyword-by-keyword.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "pictures-json" / "reports"

SERVICE_FEATURES = {
    "HAIR_WASH",
    "DOG_GROOMING",
    "CAT_HANDLING",
    "SKIN_DEVICE",
    "CASHIER_AREA",
    "WET_FLOOR_WORK",
    "GREENHOUSE_WORK",
}
CHEMICAL_FEATURES = {"CHEMICAL", "CHEMICAL_WORK", "CHEMICAL_EXPOSURE", "TOXIC", "CHEMICAL_SPOTTING", "DRY_CLEANING_SOLVENT"}
MACHINE_FEATURES = {"MACHINE", "CRUSH", "CUT", "SAWING", "INJECTION_MOLDING", "TIRE_CHANGE"}
ELECTRICAL_FEATURES = {"ELECTRICITY", "ELECTRICAL_WORK", "ELECTRIC_SHOCK", "ARC_FLASH"}
CONSTRUCTION_FEATURES = {"FALL", "LADDER", "SCAFFOLD", "LIFT_WORK", "EXCAVATION", "COLLAPSE"}
HANDLING_FEATURES = {"MATERIAL_HANDLING", "BOX_HANDLING", "FALLING_OBJECT", "SHELF_STOCKING"}
HEAT_FEATURES = {"BURN", "HEAT_COLD", "HOT_BEVERAGE", "DEEP_FRYING"}


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_report() -> Path:
    candidates = sorted(DEFAULT_OUTPUT_DIR.glob("synthetic_guide_recommendations_v1_v10_usage_profile*.json"))
    if not candidates:
        raise FileNotFoundError("No synthetic Guide recommendation report found")
    return candidates[-1]


def text_blob(row: dict[str, Any]) -> str:
    values = [
        row.get("industry_context") or "",
        row.get("work_context") or "",
        row.get("photo_description") or "",
        row.get("scene_description") or "",
        row.get("expected_primary_risk") or "",
        row.get("expected_corrective_direction") or "",
    ]
    return " ".join(value for value in values if value).lower()


def classify(row: dict[str, Any]) -> tuple[str, str]:
    features = set(row.get("risk_feature_codes") or [])
    industry = str(row.get("industry_context") or "")
    work_context = str(row.get("work_context") or "")
    blob = text_blob(row)
    if (
        not row.get("photo_description")
        and not row.get("scene_description")
        and not row.get("expected_primary_risk")
        and not row.get("expected_corrective_direction")
    ):
        return "synthetic_fixture_gap", "positive row has no photo/risk/corrective text"
    if features & SERVICE_FEATURES or any(token in industry for token in ("반려동물", "미용", "펫샵", "재활", "요양", "복지", "미용실")):
        return "service_sector_taxonomy_gap", "service/healthcare/pet-care risk lacks stable Guide profile"
    if features & CHEMICAL_FEATURES or "chemical" in work_context.lower() or "화학" in blob:
        return "chemical_profile_gap", "chemical task has no Guide-specific procedure after domain guards"
    if features & MACHINE_FEATURES or "machine" in work_context.lower() or "기계" in blob:
        return "machine_profile_gap", "machine task has no Guide-specific procedure after domain guards"
    if features & ELECTRICAL_FEATURES or "electric" in work_context.lower() or "전기" in blob:
        return "electrical_profile_gap", "electrical task has no Guide-specific procedure after domain guards"
    if features & CONSTRUCTION_FEATURES or any(token in blob for token in ("건설", "굴착", "사다리", "비계", "추락")):
        return "construction_fall_profile_gap", "construction/fall task has no Guide-specific procedure after domain guards"
    if features & HANDLING_FEATURES or any(token in blob for token in ("적재", "중량물", "상자", "팔레트", "선반")):
        return "material_handling_profile_gap", "material handling/storage task has no Guide-specific procedure after domain guards"
    if features & HEAT_FEATURES or any(token in blob for token in ("화상", "고온", "뜨거운", "튀김")):
        return "burn_heat_profile_gap", "burn/heat task has no Guide-specific procedure after domain guards"
    return "other_taxonomy_gap", "no stable taxonomy/profile bucket"


def build_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for record in report.get("records", []) or []:
        if record.get("current_category") != "missing_usage_profile":
            continue
        if (record.get("top_procedure") or {}).get("guide_code"):
            continue
        bucket, reason = classify(record)
        rows.append({
            "bucket": bucket,
            "reason": reason,
            "version": record.get("version"),
            "case_id": record.get("case_id"),
            "case_type": record.get("case_type"),
            "industry_context": record.get("industry_context"),
            "work_context": record.get("work_context"),
            "risk_feature_codes": ",".join(record.get("risk_feature_codes") or []),
            "photo_description": record.get("photo_description") or record.get("scene_description"),
            "expected_primary_risk": record.get("expected_primary_risk"),
            "expected_corrective_direction": record.get("expected_corrective_direction"),
        })
    return rows


def write_outputs(rows: list[dict[str, Any]], source: Path, output_dir: Path, prefix: str) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_dir / f"{prefix}_{timestamp}"
    bucket_counts = Counter(row["bucket"] for row in rows)
    feature_counts: Counter[str] = Counter()
    industry_counts: Counter[str] = Counter()
    work_counts: Counter[str] = Counter()
    for row in rows:
        feature_counts.update(code for code in row["risk_feature_codes"].split(",") if code)
        industry_counts[str(row.get("industry_context") or "")] += 1
        work_counts[str(row.get("work_context") or "")] += 1

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_report": str(source),
        "total_no_top": len(rows),
        "bucket_counts": dict(bucket_counts.most_common()),
        "top_features": dict(feature_counts.most_common(40)),
        "top_industries": dict(industry_counts.most_common(30)),
        "top_work_contexts": dict(work_counts.most_common(30)),
    }
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    md_path = base.with_suffix(".md")

    json_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["bucket"])
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Synthetic Guide NO_TOP Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_report: `{source}`",
        f"- total_no_top: `{len(rows)}`",
        "",
        "## Buckets",
        "",
        "| bucket | count |",
        "| --- | ---: |",
    ]
    for bucket, count in bucket_counts.most_common():
        lines.append(f"| `{bucket}` | {count} |")
    lines.extend(["", "## Top Features", "", "| feature | count |", "| --- | ---: |"])
    for feature, count in feature_counts.most_common(20):
        lines.append(f"| `{feature}` | {count} |")
    lines.extend(["", "## Next Interpretation", "", "- `synthetic_fixture_gap` should usually be removed from Guide quality failure counts or repaired in the synthetic fixture.", "- Other buckets need taxonomy, Guide usage profile, or WorkProcess coverage repair before candidate DB import.", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "md": md_path}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-prefix", default="synthetic_guide_no_top_queue")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source_report or latest_report()
    report = load_report(source)
    rows = build_rows(report)
    outputs = write_outputs(rows, source, args.output_dir, args.report_prefix)
    print(json.dumps({"total_no_top": len(rows), "outputs": {key: str(value) for key, value in outputs.items()}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
