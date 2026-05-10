"""Serving-time policy for broad Safety Requirement candidates.

Broad SRs are useful as supporting evidence, but they are too generic to select
a KOSHA Guide by themselves.  This module keeps the policy data-driven while
falling back to the reviewed broad list if the serving artifact is absent.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BROAD_SR_POLICY_PATH = DATA_DIR / "broad_sr_policy.json"
BROAD_SR_SCORE_MULTIPLIER = 0.35

FALLBACK_BROAD_SR_IDS = frozenset({
    "SR-PPE-002",
    "SR-CHEMICAL-024",
    "SR-CHEMICAL-025",
    "SR-CHEMICAL-026",
    "SR-FIRE_EXPLOSION-015",
    "SR-MGMT-004",
    "SR-ELECTRIC-024",
    "SR-FIRE_EXPLOSION-019",
    "SR-ELECTRIC-011",
    "SR-FIRE_EXPLOSION-008",
    "SR-FIRE_EXPLOSION-001",
    "SR-FIRE_EXPLOSION-037",
})


@lru_cache(maxsize=1)
def load_broad_sr_policy() -> dict:
    if not BROAD_SR_POLICY_PATH.exists():
        return {
            "broad_sr_ids": sorted(FALLBACK_BROAD_SR_IDS),
            "secondary_score_multiplier": BROAD_SR_SCORE_MULTIPLIER,
        }
    try:
        return json.loads(BROAD_SR_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "broad_sr_ids": sorted(FALLBACK_BROAD_SR_IDS),
            "secondary_score_multiplier": BROAD_SR_SCORE_MULTIPLIER,
        }


def get_broad_sr_ids() -> set[str]:
    policy = load_broad_sr_policy()
    return set(policy.get("broad_sr_ids") or FALLBACK_BROAD_SR_IDS)


def get_secondary_score_multiplier() -> float:
    policy = load_broad_sr_policy()
    try:
        return float(policy.get("secondary_score_multiplier") or BROAD_SR_SCORE_MULTIPLIER)
    except (TypeError, ValueError):
        return BROAD_SR_SCORE_MULTIPLIER


def is_broad_sr(sr_id: str | None) -> bool:
    return bool(sr_id and sr_id in get_broad_sr_ids())


def usable_primary_sr_ids(sr_ids: Iterable[str] | None, direct_sr_ids: Iterable[str] | None = None) -> list[str]:
    """Return SRs that can create recommendations without another signal.

    Non-broad SRs are primary.  Direct broad SRs can participate in direct
    candidate scoring, but broad-only CI fallback remains disabled elsewhere to
    avoid generic Guide overexposure.
    """
    direct = set(direct_sr_ids or [])
    broad = get_broad_sr_ids()
    return [
        sr_id
        for sr_id in (sr_ids or [])
        if sr_id and (sr_id not in broad or sr_id in direct)
    ]


def fallback_sr_ids(sr_ids: Iterable[str] | None) -> list[str]:
    """Return SRs safe for legacy SR→CI fallback searches."""
    broad = get_broad_sr_ids()
    return [sr_id for sr_id in (sr_ids or []) if sr_id and sr_id not in broad]
