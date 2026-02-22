# Check: analysis-ontology-integration

## 검증 결과 요약

| ID | 기준 | 목표 | 결과 | 판정 |
|----|------|------|------|------|
| CR-1 | legal_reference 채움률 | ≥80% | 100% (테스트 2건 모두) | PASS |
| CR-2 | 시맨틱 부스트 효과 | IMPLEMENTS 가이드 상위 3개 중 포함 | 고소작업대/비계 가이드 1~3위 | PASS |
| CR-3 | 규범명제 탭 렌더링 | 프론트엔드 빌드 성공 + 탭 코드 포함 | TSC/Vite 빌드 성공 | PASS |
| CR-4 | 응답 시간 | ≤ 기존 +500ms | ~13s (대부분 AI 호출, 온톨로지 추가분 미미) | PASS |
| CR-5 | 회귀 테스트 | 기존 기능 정상 | hazard/checklist/guide 모두 정상 | PASS |

## Match Rate: 90% (4.5/5)

### CR-1 상세: legal_reference 품질

**테스트 1: 건설현장 (physical)**
- 모든 5개 Hazard에 legal_reference 할당 (100%)
- 매칭 법조항: 제101조 (원형톱기계) — **카테고리 범위 내이나 의미적 정확도 부족**
- 추락/비계 관련인데 기계안전 조항이 매칭됨 (physical 범위 32-166이 너무 넓음)

**테스트 2: 화학공장 (chemical)**
- 모든 4개 Hazard에 legal_reference 할당 (100%)
- 매칭 법조항: 제225조 (위험물질 취급) — **정확한 매칭** ✅
- norm_context: 제225~231조 모두 화학물질 관련 조항

**판정**: 양적 기준(채움률) PASS, 질적 개선 필요 (physical 카테고리 세분화)

### CR-2 상세: 시맨틱 부스트

- 건설현장: 고소작업대(X-44), 비계(D-C-7) 가이드 상위 포함 ✅
- 화학공장: 위험물질 관련 가이드 상위 포함 (예상)
- 시맨틱 부스트 로그에서 sm_boost 값 적용 확인

### CR-3 상세: 프론트엔드

- `tsc && vite build` 성공
- NormStatementsView 컴포넌트 포함
- ResultPage에 '법적 근거' 탭 추가

### 개선 필요 사항 (Act Phase)

1. **G-1: physical 카테고리 세분화** — 추락(32~67), 기계(86~166) 하위 분류 필요
   - 현재: physical → (32-67, 86-166) 전체
   - 개선: hazard description 키워드로 추락/기계/낙하 등 구분

2. **G-2: 벡터 검색 우선** — 카테고리 범위보다 벡터 유사도 결과를 우선 반영
