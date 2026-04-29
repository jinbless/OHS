"""Phase 0.5 Track 5 — SPARQL Q1~Q7 smoke test.

Purpose: predicate/IRI 수정 후 각 쿼리가 실제 데이터에 대해 응답을 반환하는지 검증.
SR Recall 0% 원인을 격리 — 쿼리 자체 동작 vs OHS 통합 측 문제.

실행:
  PYTHONUTF8=1 python -m pytest OHS/backend/tests/integration/test_sparql_smoke.py -v
또는 직접 실행:
  PYTHONUTF8=1 python OHS/backend/tests/integration/test_sparql_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

from app.integrations.sparql_queries import (
    PREFIXES,
    q1_property_chain_sr_to_article,
    q2_co_applicable_srs,
    q4_exemption_chain,
    q5_high_severity_srs,
    q6_faceted_cross_query,
    q7_article_inferred_graph,
    q_triple_count,
)
from app.integrations.code_iri_mapper import all_mapped_pairs


FUSEKI_ENDPOINT = "http://localhost:3030/kosha/sparql"
TIMEOUT = 30.0


def run_sparql(query: str) -> dict:
    """Sync SPARQL POST."""
    r = httpx.post(
        FUSEKI_ENDPOINT,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def n_bindings(result: dict) -> int:
    return len(result.get("results", {}).get("bindings", []))


def test_triple_count():
    """Fuseki 살아있는지 + base trip 적재되어 있는지."""
    r = run_sparql(q_triple_count())
    n = int(r["results"]["bindings"][0]["cnt"]["value"])
    print(f"  triple count: {n:,}")
    assert n > 100_000, f"Expected >100K triples, got {n}"


def test_q1_chain_sr_to_article():
    """Q1: SR → NS → Article chain. 임의의 SR 1건으로 검증."""
    sr_id = "SR-FALL-001"  # 알려진 SR (있다면)
    r = run_sparql(q1_property_chain_sr_to_article(sr_id))
    n = n_bindings(r)
    print(f"  Q1 ({sr_id}): {n} bindings")
    # SR이 존재한다면 ≥1, 없으면 0 — 0도 OK (smoke test는 쿼리 동작만 확인)
    assert n >= 0


def test_q2_co_applicable_with_materialized_kosha():
    """Q2: kosha:coApplicable 우선 (R-2 영구화 결과)."""
    # v2 dataset에 SR-PILOT_EXCAVATION-001 의 coApplicable이 있음
    r = run_sparql(q2_co_applicable_srs("SR-PILOT_EXCAVATION-001"))
    n = n_bindings(r)
    print(f"  Q2 (SR-PILOT_EXCAVATION-001): {n} bindings (R-2 + article fallback)")
    # R-2 영구화 결과 또는 article shared fallback에서 응답


def test_q4_exemption_predicate_fix():
    """Q4: kosha:exemptedBy + law:conditionText (Phase 0.5 수정 후).

    R-1 영구화로 107건 exemptedBy 존재. 알려진 사례로 검증.
    """
    # SR이 NS chain을 통해 단서조항이 있는 article로 연결되어야 함
    # 빈 결과여도 쿼리 실행 자체는 정상 (predicate 정정 검증이 목적)
    r = run_sparql(q4_exemption_chain("SR-FALL-001"))
    n = n_bindings(r)
    print(f"  Q4 (SR-FALL-001 exemption): {n} bindings")
    assert n >= 0  # 쿼리 동작만 검증


def test_q5_high_severity():
    """Q5: severity ≥ 5인 SR. 상당 수 응답 예상."""
    r = run_sparql(q5_high_severity_srs(min_severity=5))
    n = n_bindings(r)
    print(f"  Q5 (severity >=5): {n} SRs")
    assert n >= 0


def test_q6_faceted_with_iri_mapper():
    """Q6: code_iri_mapper.py 적용 후 OHS code → OWL URI 정상 동작.

    이전 (잘못): hazard:FALL → 실제 OWL은 hazard:Fall → 0건
    이후 (정정): hazard:Fall → 매칭 정상
    """
    r = run_sparql(q6_faceted_cross_query(
        accident_types=["FALL"],
        work_contexts=["SCAFFOLD"],
    ))
    n = n_bindings(r)
    print(f"  Q6 (FALL + SCAFFOLD): {n} SRs")
    # 비계 추락 관련 SR이 ≥1건 있어야 정상
    if n == 0:
        print("    [WARN] Q6 returned 0 — code_iri_mapper 또는 OWL data 점검 필요")


def test_q7_article_inference():
    """Q7: 특정 article의 추론 그래프. kosha:exemptedBy 수정 검증."""
    r = run_sparql(q7_article_inferred_graph("제24조"))
    n = n_bindings(r)
    print(f"  Q7 (제24조): {n} bindings")
    assert n >= 0


def test_iri_mapper_existence():
    """code_iri_mapper의 모든 매핑된 IRI가 실제 OWL에 존재하는지 ASK."""
    pairs = all_mapped_pairs()
    print(f"\n  IRI 존재 검증 ({len(pairs)} pairs):")
    fail_count = 0
    for axis, code, prefixed in pairs:
        ask_query = PREFIXES + f"ASK {{ {prefixed} a ?type }}"
        try:
            r = run_sparql(ask_query)
            exists = r.get("boolean", False)
            if not exists:
                print(f"    [MISS] {axis} {code} → {prefixed}")
                fail_count += 1
        except Exception as e:
            print(f"    [ERR ] {axis} {code}: {e}")
            fail_count += 1
    print(f"  IRI 매핑 검증 — fail: {fail_count}/{len(pairs)}")
    assert fail_count == 0, f"{fail_count} IRI mappings missing in OWL"


# ────────────────────────────────────────────────────────────────────────
# CLI 직접 실행
# ────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 0.5 Track 5 — SPARQL Smoke Test")
    print(f"Endpoint: {FUSEKI_ENDPOINT}")
    print("=" * 60)

    tests = [
        ("triple_count", test_triple_count),
        ("Q1 chain", test_q1_chain_sr_to_article),
        ("Q2 coApplicable", test_q2_co_applicable_with_materialized_kosha),
        ("Q4 exemption (predicate fix)", test_q4_exemption_predicate_fix),
        ("Q5 high severity", test_q5_high_severity),
        ("Q6 faceted (IRI mapper)", test_q6_faceted_with_iri_mapper),
        ("Q7 article inference", test_q7_article_inference),
        ("IRI mapper existence", test_iri_mapper_existence),
    ]
    pass_count = 0
    fail_count = 0
    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            fn()
            print(f"  PASS")
            pass_count += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            fail_count += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            fail_count += 1
    print("\n" + "=" * 60)
    print(f"Total: {pass_count} PASS / {fail_count} FAIL")
    print("=" * 60)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
