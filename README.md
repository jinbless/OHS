# OHS product

`OHS`는 온톨로지 기반 KOSHA 위험요소 분석 product의 백엔드/프론트 구현 프로젝트다.

현재 목표는 사업주가 사진이나 텍스트를 입력하면 위험요약, 즉시 조치, 표준 개선 절차, 벌칙 3경로, 근거 보기를 제공하는 것이다.

## Current Flow

```text
photo/text input
→ observations and visual cues
→ risk:RiskFeature normalization
→ she:SituationalHazardPattern matching
→ SR / Article / WorkProcess / Guide / CI / PenaltyPath lookup
→ business-owner result screen
```

LLM은 법령 판단자가 아니라 관찰 사실과 시각 단서를 추출하는 역할이다. 법령/SR/가이드/벌칙 연결은 물질화된 온톨로지 데이터와 Python/PostgreSQL 조회 로직이 담당한다.

Guide 추천은 단순 Guide title 랭킹이 아니라 `SHE/SR → WorkProcess/Guide → ChecklistItem` 순서로 구성한다. 중신뢰 후보는 추천 점수에는 쓰지만 법적 확정 근거처럼 표시하지 않는다.

## Backend Structure

핵심 서비스 파일:

```text
backend/app/services/analysis_service.py
  OpenAI 호출 진입점과 기존 API 호환 래퍼

backend/app/services/analysis_pipeline.py
  전체 분석 오케스트레이션

backend/app/services/hazard_normalizer.py
  LLM 단서와 텍스트를 risk feature 후보로 정규화

backend/app/services/risk_rule_service.py
  정규화 feature 보정과 규칙 기반 feature 확장

backend/app/services/she_matcher.py
backend/app/services/she_match_models.py
  SHE pattern 매칭, 상태 판정, DTO

backend/app/services/sr_lookup_service.py
  SR 후보 조회

backend/app/services/guide_recommendation_service.py
  ChecklistItem 즉시 조치와 Guide/WorkProcess 표준 절차 추천
  risk feature, SHE match, visual cue, industry context를 함께 사용

backend/app/services/guide_domain_profile.py
  Guide 고유 업종/작업장 문맥과 사진 문맥의 불일치 평가
  exclusive mismatch는 제외, domain_specific mismatch는 감점

backend/app/services/penalty_path_service.py
  PenaltyRule 후보를 PenaltyPath 3경로로 그룹화
```

중요 데이터 파일:

```text
backend/app/data/risk_feature_aliases.json
backend/app/data/risk_feature_catalog.json
```

PostgreSQL의 Guide 보강 후보 테이블:

```text
guide_entity_feature_candidates
guide_sr_link_candidates
guide_visual_trigger_candidates
```

레거시 resource/video/category 기반 파일은 product 런타임에서 제거했다.

## Frontend Structure

결과 화면은 다음 패널 중심이다.

```text
frontend/src/components/results/RiskOverviewPanel.tsx
frontend/src/components/results/ImmediateActionsPanel.tsx
frontend/src/components/results/GuideProcedurePanel.tsx
frontend/src/components/results/PenaltyPathPanel.tsx
frontend/src/components/results/ReasoningTracePanel.tsx
```

분석 실행 중복은 `frontend/src/hooks/useRunAnalysis.ts`로 묶었다.

`standard_procedures`는 기존 카드 호환 필드(`title`, `description`, `guide_code`, `confidence`)를 유지하면서, `steps`가 있으면 WorkProcess 절차형 목록으로 표시한다.

## Run Locally

백엔드:

```bash
cd C:/project/arch-bot/OHS/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

프론트:

```bash
cd C:/project/arch-bot/OHS/frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

브라우저:

```text
http://127.0.0.1:5173/ohs/
```

## Environment

백엔드 기본값:

```text
DATABASE_URL=postgresql://kosha:1229@localhost/kosha
FUSEKI_ENDPOINT=http://localhost:3030/kosha/sparql
FUSEKI_ENABLED=true
```

프론트 개발 fallback:

```text
http://localhost:8001/api/v1
```

실제 OpenAI 이미지/텍스트 분석에는 `OPENAI_API_KEY`가 필요하다. 없으면 분석 API가 503을 반환할 수 있다.

## Validation

Python compile:

```bash
cd C:/project/arch-bot/OHS/backend
python -c "import pathlib; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in pathlib.Path('.').rglob('*.py') if '__pycache__' not in p.parts]; print('compile ok')"
```

Frontend build:

```bash
cd C:/project/arch-bot/OHS/frontend
npm run build
```

Synthetic smoke:

```bash
cd C:/project/arch-bot/OHS/backend
python scripts/evaluate_synthetic_observations.py --input ../../pictures-json/synthetic_observations_v10.jsonl --report-prefix synthetic_observations_v10_domain_guard2
```

Actual response 240 replay:

```bash
cd C:/project/arch-bot/OHS/backend
python scripts/evaluate_actual_response_samples.py --report-prefix actual_response_samples_v1_v10_domain_guard2_vs_pipeb1038
```

Current baseline:

```text
Python compile: OK
frontend npm run build: OK
v10 domain_guard2:
  SHE recall 100.0%
  SHE false negative 0
  SHE false positive 0
  normal suppression 100.0%
actual response 240 domain_guard2:
  status changed 0
  negative_false_positive 10
  positive_missed 2
  top action changed 195
  top procedure changed 196
  A-G-18 top procedure 51 -> 3
  G-116 top procedure 5 -> 0
  A-G-10 top procedure 14 -> 3
  A-G-18 residual 3건은 모두 항만 하역업 샘플
```

## Current Open Work

1. `WORKPLAN_LLM_DOMAIN_GUARD.md`의 30 Guide LLM 파일럿은 외부 API 전송 명시 승인 후 실행한다.
2. domain guard 1차 일반화 결과를 LLM 후보와 240 replay 표본으로 추가 조정한다.
3. 브라우저 자동화로 분석 화면까지 timeout 없이 smoke test한다.
4. `VisualTrigger`를 SR + Guide + WorkProcess + ChecklistItem 기반으로 더 구체화한다.
5. WorkProcess step 품질 점수와 industry alignment 점수를 더 세분화한다.

## Notes

- `OHS`는 루트 `arch-bot`과 별도 git repository다.
- `frontend/node_modules/**`는 vendor 영역이므로 문서 최신화 대상에서 제외한다.
- 현재 product는 PostgreSQL 물질화 조회를 serving path로 사용한다. OWL reasoner는 런타임 필수 의존성이 아니라 배치 검증/운영 분석 도구로 본다.

### Latest Broad SR Policy Validation (2026-05-09)

Runtime now reads local serving artifacts instead of koshaontology working files:

```text
OHS/backend/app/data/guide_domain_profiles.json
OHS/backend/app/data/broad_sr_policy.json
```

Serving candidate gates:

```text
confidence >= 0.65
review_status in ('candidate', 'asserted')
broad SRs are secondary-only and cannot create standard procedures or legacy fallback results by themselves
```

Latest validation:

```text
Python compile / backend compileall: OK
frontend npm run build: OK
v10 synthetic: SHE recall 100.0%, FN 0, FP 0
actual response 240: status changed 0, negative_false_positive 10, positive_missed 2, ambiguous_over_promoted 5
A-G-18 top procedure 33 -> 3 vs pipeb1038 comparison; residual 3 are all 항만 하역업
watch Guide top procedure total 57 -> 39 (31.6% reduction)
```

Reports:

```text
pictures-json/reports/synthetic_observations_v10_domain_guard_broad_sr_policy_report.md
pictures-json/reports/actual_response_samples_v1_v10_domain_guard1_vs_pipeb1038_broad_sr_policy.md
pictures-json/reports/actual_response_samples_v1_v10_domain_guard1_vs_pipeb1038_broad_sr_policy_watch_summary.md
```
### Latest Usage Profile Guide Evaluation (2026-05-09)

Guide recommendations now consume the 1,038 manual Guide usage profiles exported from Pipe-B. Standard procedure scoring is guarded so broad SRs, broad/generic features, and industry alignment cannot create top Guide procedures alone.

New Guide-specific evaluator:

```bash
cd C:/project/arch-bot/OHS/backend
python scripts/evaluate_synthetic_guide_recommendations.py --report-prefix synthetic_guide_recommendations_v1_v10_usage_profile1
```

Latest validation:

```text
synthetic Guide v1~v10: 2,360 samples
legacy obvious top Guide mismatch: 1,149
current obvious top Guide mismatch: 533
reduction: 53.61%
v10 synthetic SHE recall 100.0%, FN 0, FP 0
actual response 240 status changed 0
negative_false_positive 10
positive_missed 2
ambiguous_over_promoted 5
backend compileall OK
frontend npm run build OK
```

Latest reports:

```text
pictures-json/reports/synthetic_guide_recommendations_v1_v10_usage_profile1_20260509_230048.md
pictures-json/reports/synthetic_observations_v10_usage_profile1_report.md
pictures-json/reports/actual_response_samples_v1_v10_usage_profile1_vs_pipeb1038.md
```

### Latest Usage Profile Attention Correction (2026-05-09)

The OHS runtime now evaluates manual Guide profiles before legacy hardcoded domain rules. Legacy rules are fallback only. Exclusive Guides cannot be promoted by feature-only hits, and `management_program` Guides require explicit planning/program context.

Latest validation:

```text
synthetic Guide v1~v10: 2,360 samples
legacy obvious top Guide mismatch: 1,150
current obvious top Guide mismatch: 361
reduction: 68.61%
v10 synthetic SHE recall 100.0%, FN 0, FP 0
actual response 240 status changed 0
negative_false_positive 10
positive_missed 2
ambiguous_over_promoted 5
backend compileall OK
frontend npm run build OK
```

Latest reports:

```text
pictures-json/reports/synthetic_guide_recommendations_v1_v10_usage_profile2_20260509_233015.md
pictures-json/reports/synthetic_observations_v10_usage_profile2_report.md
pictures-json/reports/actual_response_samples_v1_v10_usage_profile2_vs_pipeb1038.md
```

### Latest Usage Profile Correction v3/v5 (2026-05-10)

The second structural repair pass tightened Guide matching so industry alignment cannot promote a Guide by itself. `exclusive` and `domain_specific` profiles now need Guide-specific term/context evidence before becoming top standard procedures.

Latest validation:

```text
synthetic Guide v1~v10: 2,360 samples
legacy obvious top Guide mismatch: 1,151
current obvious top Guide mismatch: 220
reduction: 80.89%
NO_TOP: 404, including synthetic_fixture_gap 72
v10 synthetic SHE recall 100.0%, FN 0, FP 0
actual response 240 status changed 0
negative_false_positive 10
positive_missed 2
ambiguous_over_promoted 5
backend compileall OK
frontend npm run build OK
```

Latest reports:

```text
pictures-json/reports/synthetic_guide_recommendations_v1_v10_usage_profile5_20260510_000306.md
pictures-json/reports/synthetic_guide_no_top_queue_usage_profile5_20260510_000435.md
pictures-json/reports/synthetic_observations_v10_usage_profile5_report.md
pictures-json/reports/actual_response_samples_v1_v10_usage_profile5_vs_pipeb1038.md
```

### Latest Usage Profile v11 (2026-05-10)

The current accepted OHS runtime baseline is `usage_profile11`. Guide recommendations now require actionable SHE evidence before SHE can directly create standard procedures/checklist items. Context-only SHE still informs reasoning and status, but it no longer creates top Guide procedures by itself.

Latest validation:

```text
synthetic Guide v1~v10: 2,360 samples
legacy obvious top Guide mismatch: 1,145
current obvious top Guide mismatch: 165
reduction: 85.59%
NO_TOP: 395
v10 synthetic SHE recall 100.0%, FN 0, FP 0
actual response 240 status changed 0
negative_false_positive 10
positive_missed 2
ambiguous_over_promoted 5
backend compileall OK
frontend npm run build OK
```

Latest reports:

```text
pictures-json/reports/synthetic_guide_recommendations_v1_v10_usage_profile11_20260510_011317.md
pictures-json/reports/synthetic_guide_no_top_queue_usage_profile11_20260510_011333.md
pictures-json/reports/synthetic_observations_v10_usage_profile11_report.md
pictures-json/reports/actual_response_samples_v1_v10_usage_profile11_vs_pipeb1038.md
```

Rejected approach: widening hazard/risk text alias inference at status level. It reduced some NO_TOP cases but changed actual 240 status behavior, so remaining Guide coverage should be handled through usage profiles, visual triggers, and WorkProcess relevance.
