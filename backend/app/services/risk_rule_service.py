"""Risk feature rule facade for product analysis.

This module keeps the analysis pipeline from depending on the larger legacy
hazard_rule_engine module directly.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.services import hazard_rule_engine


def apply_risk_rules(
    normalized: dict,
    db: Optional[Session] = None,
    allow_context_only_inference: bool = False,
) -> dict:
    return hazard_rule_engine.apply_rules(
        normalized,
        db=db,
        allow_context_only_inference=allow_context_only_inference,
    )
