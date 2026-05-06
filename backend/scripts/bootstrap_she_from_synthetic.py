#!/usr/bin/env python3
"""Bootstrap SHE patterns from labeled synthetic observation cases.

This is a low-human-workflow bridge:
1. Read synthetic observation JSONL.
2. Keep only cases whose expected behavior says SHE should match.
3. Skip cases already matched by the current SHE catalog unless --include-matched is set.
4. Create compact SHE candidates from normalized facets + visual cues.
5. Optionally upsert them into PostgreSQL as approved_auto patterns.

The generated rows are intentionally traceable via source_model/notes so they
can be reviewed or deprecated later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

os.environ.setdefault("OHS_ENABLE_SHE", "true")

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db.database import SessionLocal  # noqa: E402
from app.services import hazard_rule_engine, she_matcher  # noqa: E402
from app.services.industry_context import industry_hints_for_features  # noqa: E402
from evaluate_synthetic_observations import (  # noqa: E402
    apply_case_work_context_hint,
    infer_features_from_row,
    load_jsonl,
    normalize_features,
)


def feature_hash(features: dict[str, str]) -> str:
    keys = [
        "work_activity",
        "work_context",
        "hazardous_agent",
        "accident_type",
        "agent_state",
        "ppe_state",
        "environmental",
        "temporal_stage",
    ]
    raw = "|".join(f"{key}:{features.get(key, 'OTHER')}" for key in keys)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def build_she_id(features: dict[str, str]) -> str:
    wc = (features.get("work_context") or "OTHER").replace("_", "")
    return f"SHE-{wc}-{feature_hash(features)}"


def first(values: list[str], default: str = "OTHER") -> str:
    return values[0] if values else default


def infer_work_activity(work_context: str) -> str:
    if work_context == "DEMOLITION":
        return "DISMANTLE"
    if work_context in {"GRINDING", "PRESSURE_VESSEL", "ELECTRICAL_WORK"}:
        return "MAINTENANCE"
    if work_context in {"LADDER", "ROPE_ACCESS", "PAINTING"}:
        return "ROUTINE_OPERATION"
    return "OTHER"


def build_features(normalized: dict[str, list[str]], canonical: dict[str, list[str]]) -> dict[str, str]:
    work_context = first(canonical.get("work_contexts") or normalized.get("work_contexts", []))
    return {
        "work_activity": infer_work_activity(work_context),
        "work_context": work_context,
        "hazardous_agent": first(canonical.get("hazardous_agents") or normalized.get("hazardous_agents", [])),
        "accident_type": first(canonical.get("accident_types") or normalized.get("accident_types", [])),
        "agent_state": "OTHER",
        "ppe_state": first(normalized.get("ppe_states", [])),
        "environmental": first(normalized.get("environmental", [])),
        "temporal_stage": "DURING_WORK",
    }


def broadness(features: dict[str, str]) -> float:
    other_count = sum(1 for value in features.values() if value == "OTHER")
    return round(1.0 - other_count / 8.0, 3)


def build_candidate(
    db,
    row: dict[str, Any],
    *,
    sr_limit: int,
    min_matched_dims: int,
    source_model: str,
    include_matched: bool = False,
) -> dict[str, Any] | None:
    expected = row.get("expected_pipeline_behavior") or {}
    if not expected.get("should_match_she"):
        return None

    normalized, notes = normalize_features(row.get("expected_features", {}))
    apply_case_work_context_hint(normalized, row.get("work_context"))
    infer_features_from_row(row, normalized, notes)
    canonical = hazard_rule_engine.apply_rules(
        {
            "accident_types": normalized["accident_types"],
            "hazardous_agents": normalized["hazardous_agents"],
            "work_contexts": normalized["work_contexts"],
            "unknown_codes": [note["from"] for note in notes if note.get("error")],
            "forced_fit_notes": [],
        },
        db,
        allow_context_only_inference=False,
    )

    if not include_matched:
        existing = she_matcher.match_she(
            db,
            canonical["accident_types"],
            canonical["hazardous_agents"],
            canonical["work_contexts"],
            ppe_states=normalized["ppe_states"],
            environmental=normalized["environmental"],
            top_n=3,
            min_matched_dims=min_matched_dims,
            min_agent_only_visual_score=0.15,
        )
        existing_actionable = [
            match for match in existing
            if match.match_status in she_matcher.ACTIONABLE_MATCH_STATUSES
        ]
        if existing_actionable:
            return None

    sr_rows = hazard_rule_engine.query_sr_for_facets(
        db,
        canonical["accident_types"],
        canonical["hazardous_agents"],
        canonical["work_contexts"],
        limit=sr_limit,
    )
    strong_srs = [
        sr["identifier"]
        for sr in sr_rows
        if sr.get("matched_axes", 0) >= 2
    ]
    source_sr_ids = strong_srs[:3] or [sr["identifier"] for sr in sr_rows[:1]]
    if not source_sr_ids:
        return None

    features = build_features(normalized, canonical)
    industry_hints = industry_hints_for_features(features)
    she_id = build_she_id(features)
    visual_triggers = row.get("visual_cues") or [row.get("photo_description", "")]
    case_id = row.get("case_id", "")
    name = f"{row.get('work_context', 'UNKNOWN')} {first(canonical.get('accident_types', []), 'HAZARD')} pattern"

    return {
        "she_id": she_id,
        "name": name[:120],
        "name_pattern": f"synthetic_v2_{case_id.lower()}",
        "features": features,
        "industry_hints": industry_hints,
        "visual_triggers": visual_triggers[:5],
        "rationale": (
            f"Generated from synthetic observation {case_id}; "
            f"expected SHE match but current catalog missed it."
        ),
        "source_sr_ids": source_sr_ids,
        "source_model": source_model,
        "source_prompt_hash": hashlib.md5(source_model.encode("utf-8")).hexdigest(),
        "broadness_score": broadness(features),
        "status": "approved_auto",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": json.dumps(
            {
                "case_id": case_id,
                "case_type": row.get("case_type"),
                "work_context": row.get("work_context"),
                "normalization_notes": notes,
            },
            ensure_ascii=False,
        ),
    }


def merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = candidate["she_id"]
        if key not in merged:
            merged[key] = candidate
            continue
        current = merged[key]
        current["source_sr_ids"] = list(dict.fromkeys(
            current.get("source_sr_ids", []) + candidate.get("source_sr_ids", [])
        ))[:5]
        current["visual_triggers"] = list(dict.fromkeys(
            current.get("visual_triggers", []) + candidate.get("visual_triggers", [])
        ))[:5]
        current["rationale"] += f" Also supported by {candidate['name_pattern']}."
    return list(merged.values())


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def upsert_pg(db, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    db.execute(text("ALTER TABLE she_catalog ADD COLUMN IF NOT EXISTS visual_triggers JSONB"))
    db.execute(text("ALTER TABLE she_catalog ADD COLUMN IF NOT EXISTS industry_hints JSONB"))

    for row in rows:
        db.execute(
            text(
                """
                INSERT INTO she_catalog (
                    she_id, name, name_pattern, features, industry_hints, visual_triggers, rationale,
                    status, broadness_score, source_model, source_prompt_hash,
                    source_sr_ids, notes
                )
                VALUES (
                    :she_id, :name, :name_pattern,
                    CAST(:features AS jsonb), CAST(:industry_hints AS jsonb),
                    CAST(:visual_triggers AS jsonb), :rationale,
                    :status, :broadness_score, :source_model, :source_prompt_hash,
                    CAST(:source_sr_ids AS jsonb), :notes
                )
                ON CONFLICT (she_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    features = EXCLUDED.features,
                    industry_hints = EXCLUDED.industry_hints,
                    visual_triggers = EXCLUDED.visual_triggers,
                    rationale = EXCLUDED.rationale,
                    status = EXCLUDED.status,
                    broadness_score = EXCLUDED.broadness_score,
                    source_model = EXCLUDED.source_model,
                    source_sr_ids = EXCLUDED.source_sr_ids,
                    notes = EXCLUDED.notes
                """
            ),
            {
                **row,
                "features": json.dumps(row["features"], ensure_ascii=False),
                "industry_hints": json.dumps(row["industry_hints"], ensure_ascii=False),
                "visual_triggers": json.dumps(row["visual_triggers"], ensure_ascii=False),
                "source_sr_ids": json.dumps(row["source_sr_ids"], ensure_ascii=False),
            },
        )

        for sr_id in row["source_sr_ids"]:
            db.execute(
                text(
                    """
                    INSERT INTO she_sr_mapping (she_id, sr_id, confidence, source)
                    VALUES (:she_id, :sr_id, 0.85, 'synthetic_bootstrap')
                    ON CONFLICT (she_id, sr_id) DO UPDATE SET
                        confidence = GREATEST(she_sr_mapping.confidence, EXCLUDED.confidence),
                        source = EXCLUDED.source
                    """
                ),
                {"she_id": row["she_id"], "sr_id": sr_id},
            )

            ci_rows = db.execute(
                text("SELECT ci_id FROM ci_sr_mapping WHERE sr_id = :sr_id LIMIT 50"),
                {"sr_id": sr_id},
            ).fetchall()
            for (ci_id,) in ci_rows:
                db.execute(
                    text(
                        """
                        INSERT INTO she_ci_mapping (she_id, ci_id, confidence, source)
                        VALUES (:she_id, :ci_id, 0.65, 'synthetic_bootstrap')
                        ON CONFLICT (she_id, ci_id) DO NOTHING
                        """
                    ),
                    {"she_id": row["she_id"], "ci_id": ci_id},
                )

    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "pictures-json" / "synthetic_observations_v2.jsonl")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "koshaontology" / "data" / "she" / "she-synthetic-v2-bootstrap.jsonl")
    parser.add_argument("--source-model", default="synthetic/bootstrap")
    parser.add_argument("--sr-limit", type=int, default=20)
    parser.add_argument("--min-matched-dims", type=int, default=2)
    parser.add_argument(
        "--include-matched",
        action="store_true",
        help="Regenerate candidates even when the current SHE catalog already matches the case.",
    )
    parser.add_argument("--import-pg", action="store_true")
    args = parser.parse_args()

    rows = load_jsonl(args.input)
    db = SessionLocal()
    try:
        candidates = [
            candidate
            for row in rows
            if (candidate := build_candidate(
                db,
                row,
                sr_limit=args.sr_limit,
                min_matched_dims=args.min_matched_dims,
                source_model=args.source_model,
                include_matched=args.include_matched,
            ))
        ]
        candidates = merge_candidates(candidates)
        write_jsonl(args.output, candidates)
        if args.import_pg:
            upsert_pg(db, candidates)
    finally:
        db.close()

    print(f"input_cases={len(rows)}")
    print(f"generated_candidates={len(candidates)}")
    print(f"output={args.output}")
    print(f"import_pg={args.import_pg}")


if __name__ == "__main__":
    main()
