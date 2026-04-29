# Phase 0 Catalog Baseline Report (v1)

생성: 2026-04-27T20:08:40
시나리오: 100/100 성공 (0 실패)

## Overall Metrics

| Metric | Value |
|---|---:|
| Guide Recall@5 | 0.084 |
| Guide Recall@10 | 0.084 |
| Guide Precision@5 | 0.040 |
| Guide F1 | 0.044 |
| SR Recall@5 | 0.000 |
| SR Recall@10 | 0.000 |
| Forced-fit Rate | 100.0% |
| Forced-fit Avg Count | 4.67 |
| Work-context Match Rate | 83.0% |
| work_context F1 Variance | 0.0024 |
| Latency p50 | 33.42s |
| Latency p95 | 47.07s |

## By work_context

| work_context | n | Guide F1 mean | F1 stdev |
|---|---:|---:|---:|
| CRANE | 11 | 0.113 | 0.157 |
| MATERIAL_HANDLING | 11 | 0.102 | 0.153 |
| CONSTRUCTION_EQUIP | 11 | 0.097 | 0.143 |
| CONVEYOR | 6 | 0.093 | 0.148 |
| CONFINED_SPACE | 11 | 0.026 | 0.086 |
| GENERAL_WORKPLACE | 11 | 0.015 | 0.050 |
| SCAFFOLD | 11 | 0.000 | 0.000 |
| EXCAVATION | 11 | 0.000 | 0.000 |
| MACHINE | 11 | 0.000 | 0.000 |
| ETC | 6 | 0.000 | 0.000 |

## By source

| source | n | Guide F1 mean |
|---|---:|---:|
| SR_REGISTRY | 36 | 0.090 |
| GUIDE_INTERLINK | 15 | 0.057 |
| PA11 | 42 | 0.008 |
| FACETED | 7 | 0.000 |

## Phase 0 Sanity Gates

- [FAIL] Guide Recall@10 ≥ 30%: 8.4%
- [PASS] work_context F1 variance ≤ 0.30: 0.0024
- [INFO] forced_fit baseline: 100.0% (Phase 1 개선 목표)
