#!/usr/bin/env python3
"""Backfill she_catalog.visual_triggers from JSONL source files."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.database import SessionLocal  # noqa: E402


def load_rows(paths: list[Path]) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            she_id = item.get("she_id")
            triggers = item.get("visual_triggers") or []
            if she_id and triggers:
                rows[she_id] = triggers
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        default=[
            PROJECT_ROOT / "koshaontology" / "data" / "she" / "she-approved-v1.jsonl",
            PROJECT_ROOT / "koshaontology" / "data" / "she" / "she-synthetic-v2-bootstrap.jsonl",
        ],
    )
    args = parser.parse_args()

    rows = load_rows(args.input)
    db = SessionLocal()
    try:
        db.execute(text("ALTER TABLE she_catalog ADD COLUMN IF NOT EXISTS visual_triggers JSONB"))
        updated = 0
        for she_id, triggers in rows.items():
            result = db.execute(
                text(
                    """
                    UPDATE she_catalog
                    SET visual_triggers = CAST(:triggers AS jsonb)
                    WHERE she_id = :she_id
                    """
                ),
                {
                    "she_id": she_id,
                    "triggers": json.dumps(triggers, ensure_ascii=False),
                },
            )
            updated += result.rowcount or 0
        db.commit()
    finally:
        db.close()

    print(f"source_rows={len(rows)}")
    print(f"updated_rows={updated}")


if __name__ == "__main__":
    main()
