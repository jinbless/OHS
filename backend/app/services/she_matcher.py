"""Phase 3 Layer 0 — SHE Router (PG-based).

목적:
  GPT description + facets → 매칭되는 active SHE top-N (각 SHE의 8 dim feature
  와 description의 facets가 ≥2 dim 일치). 매칭된 SHE → appliesSR/appliesCI/
  source_guide 자동 follow.

배치 (analysis_service.py L107 직후):
  GPT result → [Layer 0: SHE matcher] → 매칭 SHE list → Layer 1~4가 후보 좁힘

Why PG (not Fuseki)?
  - v2 Fuseki Java는 read-only — SPARQL UPDATE 차단 (Phase 4에서 rebuild 예정)
  - PG she_catalog (645 SHE, JSONB GIN) 이미 적재 + JSONB feature 매칭 ~10ms
  - sr-registry CI/Guide 자동 follow는 PG she_sr_mapping/she_ci_mapping 활용

Feature flag (사용자 비판 #12):
  OHS_ENABLE_SHE=false (default) → Layer 0 skip, 기존 4-layer 유지
  OHS_ENABLE_SHE=true            → Layer 0 active

Future (Phase 3 Track 4):
  GPT DUAL_TRACK_SCHEMA에 situational_features 8축 추가 (사용자 비판 #11)
  → 현재는 Track B 3축 (accident_types, hazardous_agents, work_contexts)으로 매칭
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


class SHEMatchResult:
    """1 매칭된 SHE."""
    def __init__(
        self,
        she_id: str,
        name: str,
        features: dict,
        broadness: float,
        match_score: float,
        matched_dims: list[str],
        source_sr_ids: list[str],
        applies_sr_ids: list[str],
        applies_ci_ids: list[str],
        source_guides: list[str],
    ):
        self.she_id = she_id
        self.name = name
        self.features = features
        self.broadness = broadness
        self.match_score = match_score      # 0.0~1.0
        self.matched_dims = matched_dims    # 일치한 feature dim 이름
        self.source_sr_ids = source_sr_ids
        self.applies_sr_ids = applies_sr_ids
        self.applies_ci_ids = applies_ci_ids
        self.source_guides = source_guides

    def to_dict(self) -> dict:
        return {
            "she_id": self.she_id,
            "name": self.name,
            "features": self.features,
            "broadness": self.broadness,
            "match_score": self.match_score,
            "matched_dims": self.matched_dims,
            "applies_sr_ids": self.applies_sr_ids,
            "applies_ci_count": len(self.applies_ci_ids),
            "source_guides": self.source_guides,
        }


def match_she(
    db: Session,
    accident_types: list[str] | None = None,
    hazardous_agents: list[str] | None = None,
    work_contexts: list[str] | None = None,
    work_activity: str | None = None,
    top_n: int = 3,
    min_matched_dims: int = 2,
) -> list[SHEMatchResult]:
    """PG에서 active SHE를 facet 매칭으로 검색.

    Args:
      accident_types/hazardous_agents/work_contexts: GPT Track B 3축 (uppercase enum)
      work_activity: 추론된 work_activity (선택, 없으면 OTHER)
      top_n: 반환할 최대 SHE 수
      min_matched_dims: ≥N dim 일치해야 매칭 (default 2 = strict)

    Returns:
      List of SHEMatchResult sorted by match_score desc.

    Algorithm:
      1. SHE 후보를 features JSONB로 쿼리 (broad filter)
      2. 각 SHE의 8 dim 중 입력 facets와 일치 dim count
      3. min_matched_dims 충족 + match_score = matched / 8
      4. broadness 가중 (specific SHE 우선)
      5. top_n 반환
    """
    if not settings.OHS_ENABLE_SHE:
        return []

    accident_types = accident_types or []
    hazardous_agents = hazardous_agents or []
    work_contexts = work_contexts or []

    # Empty input → empty (no matching possible)
    if not (accident_types or hazardous_agents or work_contexts):
        return []

    # Step 1: 후보 SHE 검색 — features JSONB의 work_context 또는 accident_type 또는 hazardous_agent 일치
    # PG에서 OR 조건으로 broad 검색 후 in-Python에서 정밀 매칭
    sql = text("""
        SELECT she_id, name, features, broadness_score, source_sr_ids
        FROM she_catalog
        WHERE status IN ('approved_auto', 'approved_manual')
          AND (superseded_by IS NULL)
          AND (
                features->>'work_context' = ANY(:wcs)
             OR features->>'hazardous_agent' = ANY(:has)
             OR features->>'accident_type' = ANY(:ats)
          )
        LIMIT 500
    """)
    rows = db.execute(sql, {
        "wcs": work_contexts or [""],
        "has": hazardous_agents or [""],
        "ats": accident_types or [""],
    }).fetchall()

    # Step 2: 정밀 매칭 — 각 SHE의 8 dim 중 일치 dim count
    candidates: list[SHEMatchResult] = []
    for row in rows:
        she_id, name, features, broadness, source_sr_ids = row
        if isinstance(features, str):
            import json
            features = json.loads(features)
        if isinstance(source_sr_ids, str):
            import json
            source_sr_ids = json.loads(source_sr_ids)

        matched_dims = []
        # work_context
        if features.get("work_context") in work_contexts:
            matched_dims.append("work_context")
        # hazardous_agent
        if features.get("hazardous_agent") in hazardous_agents:
            matched_dims.append("hazardous_agent")
        # accident_type
        if features.get("accident_type") in accident_types:
            matched_dims.append("accident_type")
        # work_activity (선택)
        if work_activity and features.get("work_activity") == work_activity:
            matched_dims.append("work_activity")

        if len(matched_dims) < min_matched_dims:
            continue

        # match_score: matched_dims 수 / 4 (현재 가용 dim) + broadness 가중
        # PG NUMERIC(4,3)이 Decimal 타입으로 반환되므로 float 변환 필수
        broadness_f = float(broadness) if broadness is not None else 0.5
        match_score = (len(matched_dims) / 4.0) * 0.7 + broadness_f * 0.3

        candidates.append(SHEMatchResult(
            she_id=she_id,
            name=name,
            features=features,
            broadness=broadness_f,
            match_score=match_score,
            matched_dims=matched_dims,
            source_sr_ids=source_sr_ids or [],
            applies_sr_ids=[],     # follow-up에서 채움
            applies_ci_ids=[],
            source_guides=[],
        ))

    # Step 3: top_n by match_score desc
    candidates.sort(key=lambda c: -c.match_score)
    top = candidates[:top_n]

    # Step 4: 매칭 SHE의 SR/CI/Guide follow (PG join)
    if top:
        she_ids = [c.she_id for c in top]
        sr_sql = text("""
            SELECT she_id, sr_id, confidence
            FROM she_sr_mapping
            WHERE she_id = ANY(:she_ids)
        """)
        sr_rows = db.execute(sr_sql, {"she_ids": she_ids}).fetchall()
        sr_by_she: dict[str, list[str]] = {}
        for sid, sr_id, conf in sr_rows:
            sr_by_she.setdefault(sid, []).append(sr_id)

        ci_sql = text("""
            SELECT she_id, ci_id
            FROM she_ci_mapping
            WHERE she_id = ANY(:she_ids)
            LIMIT 200
        """)
        ci_rows = db.execute(ci_sql, {"she_ids": she_ids}).fetchall()
        ci_by_she: dict[str, list[str]] = {}
        for sid, ci_id in ci_rows:
            ci_by_she.setdefault(sid, []).append(ci_id)

        # Guide follow: linked CI의 source_guide
        if ci_by_she:
            all_cis = list({ci for cis in ci_by_she.values() for ci in cis})
            g_sql = text("""
                SELECT identifier, source_guide
                FROM checklist_items
                WHERE identifier = ANY(:cis)
            """)
            g_rows = db.execute(g_sql, {"cis": all_cis}).fetchall()
            ci_to_guide = {row[0]: row[1] for row in g_rows}
        else:
            ci_to_guide = {}

        for c in top:
            c.applies_sr_ids = sr_by_she.get(c.she_id, [])
            c.applies_ci_ids = ci_by_she.get(c.she_id, [])
            c.source_guides = sorted(set(
                ci_to_guide[ci] for ci in c.applies_ci_ids if ci in ci_to_guide
            ))

    logger.warning(f"[Layer0/SHE] matched {len(top)} SHE: "
                   f"{[(c.she_id, c.match_score, c.matched_dims) for c in top]}")
    return top


def get_matched_sr_ids(matches: list[SHEMatchResult]) -> list[str]:
    """매칭 SHE 모음의 unique SR identifier list."""
    ids: list[str] = []
    seen: set[str] = set()
    for m in matches:
        for sr in m.applies_sr_ids:
            if sr not in seen:
                seen.add(sr)
                ids.append(sr)
    return ids


def get_matched_guides(matches: list[SHEMatchResult]) -> list[str]:
    """매칭 SHE 모음의 unique source_guide list."""
    guides: list[str] = []
    seen: set[str] = set()
    for m in matches:
        for g in m.source_guides:
            if g not in seen:
                seen.add(g)
                guides.append(g)
    return guides
