# Phase 0 Catalog Baseline Report (v1)

생성: 2026-04-27T22:38:20
시나리오: 100/100 성공 (0 실패)

## Overall Metrics

| Metric | Value |
|---|---:|
| Guide Recall@5 | 0.062 |
| Guide Recall@10 | 0.062 |
| Guide Precision@5 | 0.042 |
| Guide F1 | 0.041 |
| SR Recall@5 | 0.026 |
| SR Recall@10 | 0.049 |
| Forced-fit Rate | 100.0% |
| Forced-fit Avg Count | 4.51 |
| Work-context Match Rate | 83.0% |
| work_context F1 Variance | 0.0015 |
| Latency p50 | 29.61s |
| Latency p95 | 40.79s |

## By work_context

| work_context | n | Guide F1 mean | F1 stdev |
|---|---:|---:|---:|
| CONSTRUCTION_EQUIP | 11 | 0.105 | 0.152 |
| MATERIAL_HANDLING | 11 | 0.086 | 0.135 |
| CRANE | 11 | 0.082 | 0.141 |
| SCAFFOLD | 11 | 0.039 | 0.092 |
| CONVEYOR | 6 | 0.037 | 0.091 |
| CONFINED_SPACE | 11 | 0.026 | 0.086 |
| GENERAL_WORKPLACE | 11 | 0.015 | 0.050 |
| EXCAVATION | 11 | 0.000 | 0.000 |
| MACHINE | 11 | 0.000 | 0.000 |
| ETC | 6 | 0.000 | 0.000 |

## By source

| source | n | Guide F1 mean |
|---|---:|---:|
| GUIDE_INTERLINK | 15 | 0.076 |
| SR_REGISTRY | 36 | 0.073 |
| PA11 | 42 | 0.008 |
| FACETED | 7 | 0.000 |

## Phase 0 Sanity Gates

- [FAIL] Guide Recall@10 ≥ 30%: 6.2%
- [PASS] work_context F1 variance ≤ 0.30: 0.0015
- [INFO] forced_fit baseline: 100.0% (Phase 1 개선 목표)
