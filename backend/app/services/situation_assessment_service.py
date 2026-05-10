"""SHE matching facade used by product analysis."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.services import she_matcher

logger = logging.getLogger(__name__)


ACTIONABLE_MATCH_STATUSES = she_matcher.ACTIONABLE_MATCH_STATUSES


def has_observable_violation_signal(
    normalized: dict,
    high_severity_observation: bool,
    context_text: str,
) -> bool:
    return she_matcher.has_observable_violation_signal(
        accident_types=normalized.get("accident_types", []),
        hazardous_agents=normalized.get("hazardous_agents", []),
        work_contexts=normalized.get("work_contexts", []),
        ppe_states=normalized.get("ppe_states", []),
        environmental=normalized.get("environmental", []),
        high_severity_observation=high_severity_observation,
        visual_cues=[context_text],
    )


def match_situational_patterns(
    db: Session,
    canonical: dict,
    visual_cues: list[str],
    industry_contexts: list[str],
) -> list[Any]:
    try:
        return she_matcher.match_she(
            db=db,
            accident_types=canonical["accident_types"],
            hazardous_agents=canonical["hazardous_agents"],
            work_contexts=canonical["work_contexts"],
            visual_cues=visual_cues,
            industry_contexts=industry_contexts,
            min_agent_only_visual_score=0.15,
            top_n=5,
            min_matched_dims=2,
        )
    except Exception as exc:
        logger.warning("[SHE] match failed: %s", exc)
        return []


def is_direct_penalty_match(match: Any) -> bool:
    return she_matcher.is_direct_penalty_match(match)
