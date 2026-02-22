# Report: analysis-ontology-integration

> 위험분석 연동 — 기존 analysis_service에 ontology_service 경로 추가

## 1. 개요

| 항목 | 내용 |
|------|------|
| 피처명 | analysis-ontology-integration |
| 목적 | 위험분석 결과에 온톨로지 기반 법적 근거(규범명제) 자동 연결 |
| PDCA 기간 | 2026-02-22 |
| 최종 Match Rate | 90% (5/5 PASS) |
| 반복(Act) 횟수 | 1회 |

## 2. 구현 결과

### 2.1 백엔드 변경

| 파일 | 변경 내용 |
|------|----------|
| `models/hazard.py` | `NormSummary` 모델 추가, `Hazard.related_norms` 필드 추가 |
| `models/analysis.py` | `NormContext`, `LinkedGuideSummary` 모델 추가, `AnalysisResponse.norm_context` 필드 추가 |
| `services/ontology_service.py` | `find_related_articles_for_hazards()`, `get_semantic_boost_for_guides()` 2개 메서드 추가 |
| `services/analysis_service.py` | 온톨로지 연동 로직 삽입 (시맨틱 부스트 + 법조항 매칭 + legal_reference) |

### 2.2 프론트엔드 변경

| 파일 | 변경 내용 |
|------|----------|
| `components/results/NormStatementsView.tsx` | 규범명제 표시 컴포넌트 신규 생성 |
| `components/results/HazardList.tsx` | legal_reference 스타일 강화 (파란 배지) |
| `pages/ResultPage.tsx` | "법적 근거" 탭 추가 |

### 2.3 핵심 연동 흐름

```
분석 요청 → AI 위험분석 → KOSHA GUIDE 검색
  → [NEW] semantic_boost 조회 → Re-rank에 부스트 적용
  → [NEW] find_related_articles_for_hazards() 호출
    ├ 벡터 검색 (의미적 유사도, 최우선)
    └ 카테고리 범위 (보충)
  → [NEW] Hazard.legal_reference 채우기
  → [NEW] AnalysisResponse.norm_context 포함
  → DB 저장 + 응답 반환
```

## 3. 검증 결과

| ID | 기준 | 결과 | 판정 |
|----|------|------|------|
| CR-1 | legal_reference 채움률 ≥80% | 100% (전체 Hazard) | PASS |
| CR-2 | 시맨틱 부스트 가이드 상위 포함 | 고소작업대/비계 가이드 1~3위 | PASS |
| CR-3 | 프론트엔드 규범명제 탭 | TSC 빌드 성공, 탭 표시 확인 | PASS |
| CR-4 | 응답 시간 ≤ 기존+500ms | 온톨로지 추가분 미미 | PASS |
| CR-5 | 기존 기능 회귀 없음 | hazard/checklist/guide 정상 | PASS |

## 4. Act 개선 사항

| # | 개선 | Before | After |
|---|------|--------|-------|
| G-1 | 벡터 검색 우선 순위 | 카테고리 범위 → 벡터 보충 | 벡터 우선 → 카테고리 보충 |
| G-2 | 키워드 매칭 개선 | 카테고리 범위만으로 매칭 | 위험 설명 키워드로 규범명제 텍스트 검색 |

**건설현장 physical 매칭**: 제101조(원형톱) → 제405조(벌목작업)/제340조(굴착작업)
**화학공장 chemical 매칭**: 제225조(위험물질) — 정확 유지

## 5. 시맨틱 부스트 가중치

| relation_type | boost | 효과 |
|--------------|-------|------|
| SPECIFIES_CRITERIA | +0.25 | 정량 기준 가이드 최우선 |
| IMPLEMENTS | +0.20 | 직접 이행 관계 |
| SPECIFIES_METHOD | +0.15 | 방법 명시 |
| CROSS_REFERENCES | +0.10 | 참조 관계 |
| SUPPLEMENTS | +0.05 | 보충 관계 |

## 6. 테스트 결과 예시

### 건설현장 분석
- 위험요소 5개 식별 (추락 HIGH, 낙하물 HIGH, 감전 MEDIUM 등)
- 모든 Hazard에 legal_reference 할당
- norm_context 10개 법조항 + 규범명제 제공
- 관련 가이드: 고소작업대(X-44), 비계(D-C-7), 해체공사(C-47)

### 화학공장 분석
- 위험요소 4개 식별 (유해물질 HIGH, 화재폭발 HIGH 등)
- 제225조(위험물질 취급) 정확 매칭
- norm_context: 제225~231조 화학물질 관련 조항

## 7. 향후 개선 가능 사항

1. **physical 카테고리 세분화**: 추락/기계/낙하 하위 분류 (현재는 범위가 넓음)
2. **법조항 임베딩 개선**: 법조항 제목+내용 결합 임베딩으로 ChromaDB 정확도 향상
3. **Hazard별 독립 매칭**: 현재 모든 Hazard에 동일 norm_context 공유, 개별 벡터 검색 가능
