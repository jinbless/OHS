"""SafetyRequirement lookup facade for the analysis pipeline."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import PgSrArticleMapping
from app.services import hazard_rule_engine


def query_safety_requirements(
    db: Session,
    accident_types: list[str],
    hazardous_agents: list[str],
    work_contexts: list[str],
    industry_contexts: list[str] | None = None,
) -> list[dict]:
    return hazard_rule_engine.query_sr_for_facets(
        db,
        accident_types,
        hazardous_agents,
        work_contexts,
        industry_contexts=industry_contexts,
    )


def article_ids_for_srs(db: Session, sr_ids: list[str]) -> list[str]:
    if not sr_ids:
        return []
    rows = (
        db.query(PgSrArticleMapping)
        .filter(PgSrArticleMapping.sr_id.in_(sr_ids))
        .limit(30)
        .all()
    )
    return list(
        dict.fromkeys(
            f"{row.law_type}_{row.article_code}"
            for row in rows
            if row.law_type and row.article_code
        )
    )
