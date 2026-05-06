"""Phase 4 E2E 검증 스크립트 — GPT 호출 없이 Dual-Track 파이프라인 전체 검증.

GPT 응답을 시뮬레이션하여 다음 체인을 검증:
  GPT(시뮬) → normalizer → rule_engine → SR → CI → Penalty → Checklist

실행: sudo docker exec ohs-backend python scripts/test_e2e_scenarios.py
"""
import sys
import json
from datetime import datetime

# DB 설정
from app.db.database import SessionLocal, create_tables
from app.services.hazard_normalizer import normalize_faceted_hazards
from app.services.hazard_rule_engine import (
    apply_rules, query_sr_for_facets, get_checklist_from_srs, get_penalties_for_srs,
)
from app.services.divergence_detector import detect_divergence, save_gaps_to_db

create_tables()

SCENARIOS = [
    {
        "name": "시나리오 1: 비계 가장자리 추락 위험",
        "description": "건설 현장에서 비계 작업 중 안전난간이 미설치된 상태",
        "gpt_faceted": {
            "accident_types": ["FALL"],
            "hazardous_agents": [],
            "work_contexts": ["SCAFFOLD"],
            "forced_fit_notes": [],
        },
        "gpt_free": [
            {"label": "비계 추락 위험", "description": "안전난간 미설치 상태에서 작업", "confidence": 0.95, "severity": "HIGH"},
            {"label": "작업발판 불량", "description": "발판 고정 상태 불량", "confidence": 0.8, "severity": "MEDIUM"},
        ],
        "expect": {
            "accident_types": ["FALL"],  # SCAFFOLD→FALL 교차추론은 이미 FALL 있으므로 중복 없음
            "work_contexts_contains": "SCAFFOLD",
            "sr_min": 5,
            "ci_min": 1,
        },
    },
    {
        "name": "시나리오 2: 밀폐공간 용접 (복합 위험)",
        "description": "밀폐된 탱크 내부에서 용접 작업 중 유해가스 발생",
        "gpt_faceted": {
            "accident_types": [],
            "hazardous_agents": ["CHEMICAL", "FIRE"],
            "work_contexts": ["CONFINED_SPACE"],
            "forced_fit_notes": [],
        },
        "gpt_free": [
            {"label": "밀폐공간 질식 위험", "description": "환기 불충분한 상태에서 용접", "confidence": 0.9, "severity": "HIGH"},
            {"label": "화재 위험", "description": "용접 불꽃에 의한 화재", "confidence": 0.85, "severity": "HIGH"},
        ],
        "expect": {
            "agent_contains": "TOXIC",  # CONFINED_SPACE+CHEMICAL → TOXIC 교차추론
            "work_contexts_contains": "CONFINED_SPACE",
            "sr_min": 5,
        },
    },
    {
        "name": "시나리오 3: 지게차-보행자 혼재",
        "description": "물류 창고에서 지게차와 보행자가 같은 통로 사용",
        "gpt_faceted": {
            "accident_types": ["COLLISION"],
            "hazardous_agents": [],
            "work_contexts": ["VEHICLE"],
            "forced_fit_notes": [],
        },
        "gpt_free": [
            {"label": "지게차 충돌 위험", "description": "보행자 통로와 차량 통로 미분리", "confidence": 0.9, "severity": "HIGH"},
        ],
        "expect": {
            "accident_types": ["COLLISION"],
            "work_contexts_contains": "VEHICLE",
            "sr_min": 5,
        },
    },
    {
        "name": "시나리오 4: 화학물질 취급 (코드 gap 테스트)",
        "description": "화학물질 저장소에서 독성 물질 취급 중 드론 접근",
        "gpt_faceted": {
            "accident_types": [],
            "hazardous_agents": ["TOXIC"],
            "work_contexts": [],
            "forced_fit_notes": ["드론 관련 위험은 현재 코드에 정확히 맞지 않음"],
        },
        "gpt_free": [
            {"label": "독성물질 노출", "description": "보호장비 미착용 상태에서 취급", "confidence": 0.85, "severity": "HIGH"},
            {"label": "드론 충돌 위험", "description": "무인기가 화학물질 저장구역 접근", "confidence": 0.7, "severity": "MEDIUM"},
        ],
        "expect": {
            "agent_contains": "TOXIC",
            "divergence_min": 1,  # 드론 충돌 = UNMAPPED 또는 forced_fit
        },
    },
]


def run_scenario(scenario: dict, db) -> dict:
    """시나리오 실행 및 결과 반환."""
    name = scenario["name"]
    desc = scenario["description"]

    # 1. Normalizer
    normalized = normalize_faceted_hazards(scenario["gpt_faceted"], desc)

    # 2. Rule Engine
    canonical = apply_rules(normalized, db, allow_context_only_inference=False)

    # 3. SR 조회
    srs = query_sr_for_facets(
        db, canonical["accident_types"], canonical["hazardous_agents"], canonical["work_contexts"]
    )
    sr_ids = [s["identifier"] for s in srs]

    # 4. CI 조회
    cis = get_checklist_from_srs(db, sr_ids, limit=30)

    # 5. Penalty 조회
    penalties = get_penalties_for_srs(db, sr_ids)

    # 6. Divergence
    divergences = detect_divergence(
        scenario["gpt_free"],
        canonical,
        scenario["gpt_faceted"].get("forced_fit_notes", []),
    )

    return {
        "name": name,
        "canonical": canonical,
        "sr_count": len(srs),
        "ci_count": len(cis),
        "penalty_count": len(penalties),
        "divergences": divergences,
        "srs_sample": [s["identifier"] for s in srs[:3]],
        "cis_sample": [c["text"][:50] for c in cis[:3]],
        "penalties_sample": [
            f"{p['article_code']}: {p['title']}" for p in penalties[:3]
        ],
    }


def validate(result: dict, expect: dict) -> list[str]:
    """기대값 검증. 실패 메시지 리스트 반환."""
    errors = []

    if "accident_types" in expect:
        if set(expect["accident_types"]) != set(result["canonical"]["accident_types"]):
            errors.append(
                f"AT mismatch: expected {expect['accident_types']}, "
                f"got {result['canonical']['accident_types']}"
            )

    if "agent_contains" in expect:
        if expect["agent_contains"] not in result["canonical"]["hazardous_agents"]:
            errors.append(
                f"AG missing: expected {expect['agent_contains']} in "
                f"{result['canonical']['hazardous_agents']}"
            )

    if "work_contexts_contains" in expect:
        if expect["work_contexts_contains"] not in result["canonical"]["work_contexts"]:
            errors.append(
                f"WC missing: expected {expect['work_contexts_contains']} in "
                f"{result['canonical']['work_contexts']}"
            )

    if "sr_min" in expect:
        if result["sr_count"] < expect["sr_min"]:
            errors.append(f"SR count {result['sr_count']} < min {expect['sr_min']}")

    if "ci_min" in expect:
        if result["ci_count"] < expect["ci_min"]:
            errors.append(f"CI count {result['ci_count']} < min {expect['ci_min']}")

    if "divergence_min" in expect:
        if len(result["divergences"]) < expect["divergence_min"]:
            errors.append(
                f"Divergence count {len(result['divergences'])} < min {expect['divergence_min']}"
            )

    return errors


def main():
    db = SessionLocal()
    all_passed = True
    results = []

    try:
        for scenario in SCENARIOS:
            result = run_scenario(scenario, db)
            errors = validate(result, scenario["expect"])
            passed = len(errors) == 0

            status = "PASS" if passed else "FAIL"
            print(f"\n{'='*60}")
            print(f"[{status}] {result['name']}")
            print(f"  Canonical: AT={result['canonical']['accident_types']}, "
                  f"AG={result['canonical']['hazardous_agents']}, "
                  f"WC={result['canonical']['work_contexts']}")
            print(f"  Rules: {result['canonical']['applied_rules']}")
            print(f"  Confidence: {result['canonical']['confidence']}")
            print(f"  SR: {result['sr_count']}건, CI: {result['ci_count']}건, "
                  f"Penalty: {result['penalty_count']}건")
            print(f"  Divergences: {len(result['divergences'])}건")

            if result["srs_sample"]:
                print(f"  SR samples: {result['srs_sample']}")
            if result["cis_sample"]:
                print(f"  CI samples: {result['cis_sample']}")
            if result["penalties_sample"]:
                print(f"  Penalty samples: {result['penalties_sample']}")
            if result["divergences"]:
                for d in result["divergences"]:
                    print(f"  Gap: {d['gap_type']} — {d.get('gpt_free_label', d.get('description', '')[:40])}")

            if errors:
                all_passed = False
                for e in errors:
                    print(f"  ERROR: {e}")

            results.append({"status": status, **result})

    finally:
        db.close()

    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)
    print(f"결과: {passed}/{total} PASS")

    if not all_passed:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
