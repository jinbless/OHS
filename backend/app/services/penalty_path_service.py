"""PenaltyPath construction facade."""
from __future__ import annotations

from app.models.hazard import PenaltyPath
from app.services import hazard_rule_engine


def get_penalty_candidates(
    sr_ids: list[str],
    direct_sr_ids: list[str] | None = None,
) -> list[dict]:
    return hazard_rule_engine.get_penalty_candidates_for_srs(
        sr_ids,
        direct_sr_ids=direct_sr_ids,
    )


def build_penalty_paths(
    candidates: list[dict],
    finding_status: str,
) -> list[PenaltyPath]:
    return [
        PenaltyPath(**item)
        for item in hazard_rule_engine.build_penalty_paths(
            candidates,
            finding_status=finding_status,
        )
    ]
