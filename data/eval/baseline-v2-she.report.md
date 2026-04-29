# Phase 0 Catalog Baseline Report (v1)

생성: 2026-04-28T11:24:26
시나리오: 33/33 성공 (0 실패)

**Metric 평가 단위 (2026-04-27 사용자 통찰 반영)**:
- **Guide (작업 절차)** = primary — 사용자에게 의미 있는 단위. 라벨링과 일치.
- **SR (법령 의무)** = primary — 독립 단위.
- **CI (체크 항목)** = Guide 종속 implementation detail — 개별 평가 X. Guide 매칭 시 자동 follow.

## Primary Metrics

| Metric | Value | 평가 단위 |
|---|---:|---|
| **Guide Recall@5** ★ | 0.019 | 작업 절차 |
| **Guide Recall@10** ★ | 0.019 | 작업 절차 |
| **Guide Precision@5** ★ | 0.012 | 작업 절차 |
| **Guide F1** ★ | 0.013 | 작업 절차 |
| **SR Recall@5** ★ | 0.052 | 법령 의무 |
| **SR Recall@10** ★ | 0.063 | 법령 의무 |

## Secondary Metrics (시스템 건강도)

| Metric | Value |
|---|---:|
| Forced-fit Rate | 100.0% |
| Forced-fit Avg Count | 3.91 |
| Work-context Match Rate | 100.0% |
| work_context F1 Variance | 0.0005 |
| Latency p50 | 20.10s |
| Latency p95 | 30.57s |

## By work_context

| work_context | n | Guide F1 mean | F1 stdev |
|---|---:|---:|---:|
| SCAFFOLD | 11 | 0.039 | 0.092 |
| EXCAVATION | 11 | 0.000 | 0.000 |
| MACHINE | 11 | 0.000 | 0.000 |

## By source

| source | n | Guide F1 mean |
|---|---:|---:|
| GUIDE_INTERLINK | 6 | 0.048 |
| SR_REGISTRY | 9 | 0.016 |
| PA11 | 15 | 0.000 |
| FACETED | 3 | 0.000 |

## Phase 0 Sanity Gates

- [FAIL] Guide Recall@10 ≥ 30%: 1.9%
- [PASS] work_context F1 variance ≤ 0.30: 0.0005
- [INFO] forced_fit baseline: 100.0% (Phase 1 개선 목표)
