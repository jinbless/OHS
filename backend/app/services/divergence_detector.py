"""Track A (자유 분류) vs Track B (코드 분류) 괴리 감지기.

괴리 유형:
- UNMAPPED: Track A에는 있지만 Track B로 매핑 불가
- FORCED_FIT: Track B에 매핑했지만 forced_fit_note 존재
- NOVEL: Track A 라벨이 기존 코드 체계에 없는 새로운 개념
"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def detect_divergence(
    free_hazards: list[dict],
    canonical: dict,
    forced_fit_notes: list[str],
) -> list[dict]:
    """Track A와 Track B 사이의 괴리를 감지.

    Args:
        free_hazards: Track A GPT 자유 분류 목록
        canonical: rule engine 출력 (accident_types, hazardous_agents, work_contexts)
        forced_fit_notes: GPT forced_fit_notes

    Returns:
        list of divergence records
    """
    divergences = []

    # 모든 canonical 코드를 flat set으로
    all_codes = set()
    all_codes.update(canonical.get("accident_types", []))
    all_codes.update(canonical.get("hazardous_agents", []))
    all_codes.update(canonical.get("work_contexts", []))

    # Track A 각 항목에 대해 Track B 매핑 여부 검사
    # 간단한 키워드 기반 매핑 확인 (GPT 라벨 vs 코드 라벨)
    from app.utils.taxonomy import get_faceted_code_label

    code_labels = {}
    for code in all_codes:
        label = get_faceted_code_label(code)
        if label:
            code_labels[code] = label.lower()

    for fh in free_hazards:
        label = fh.get("label", "")
        desc = fh.get("description", "")
        label_lower = label.lower()

        # Track B 코드와 매칭 시도
        matched = False
        for code, code_label in code_labels.items():
            if code_label in label_lower or label_lower in code_label:
                matched = True
                break
            # 코드명 자체가 라벨에 포함
            if code.lower() in label_lower:
                matched = True
                break

        if not matched and len(all_codes) > 0:
            divergences.append({
                "gap_type": "UNMAPPED",
                "gpt_free_label": label,
                "description": desc,
                "nearest_code": None,
                "confidence": fh.get("confidence", 0),
                "severity": fh.get("severity", "MEDIUM"),
            })

    # forced_fit_notes → FORCED_FIT gap
    for note in forced_fit_notes:
        if note and note.strip():
            divergences.append({
                "gap_type": "FORCED_FIT",
                "gpt_free_label": None,
                "description": note,
                "nearest_code": None,
                "confidence": None,
                "severity": None,
            })

    if divergences:
        logger.warning(
            f"[Divergence] {len(divergences)}건 감지: "
            f"{[d['gap_type'] for d in divergences]}"
        )

    return divergences


def save_gaps_to_db(
    db: Session,
    divergences: list[dict],
    analysis_id: str,
) -> int:
    """괴리를 hazard_code_gaps 테이블에 누적 저장.

    Returns: 새로 생성된 gap 수
    """
    from app.db.models import OhsHazardCodeGap

    created = 0
    for div in divergences:
        label = div.get("gpt_free_label") or div.get("description", "")[:100]
        if not label:
            continue

        # 기존 동일 gap 검색 (label + type)
        existing = (
            db.query(OhsHazardCodeGap)
            .filter(
                OhsHazardCodeGap.gpt_free_label == label,
                OhsHazardCodeGap.gap_type == div["gap_type"],
            )
            .first()
        )

        if existing:
            existing.occurrence_count += 1
            existing.last_seen = datetime.utcnow()
            # sample_analysis_ids 업데이트 (최대 5개)
            samples = existing.sample_analysis_ids or []
            if analysis_id not in samples and len(samples) < 5:
                samples.append(analysis_id)
                existing.sample_analysis_ids = samples
        else:
            gap = OhsHazardCodeGap(
                gap_type=div["gap_type"],
                gpt_free_label=label,
                nearest_code=div.get("nearest_code"),
                forced_fit_note=div.get("description") if div["gap_type"] == "FORCED_FIT" else None,
                occurrence_count=1,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                sample_analysis_ids=[analysis_id],
            )
            db.add(gap)
            created += 1

    db.flush()
    return created
