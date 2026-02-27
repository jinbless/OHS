# Plan: "법적 근거" 탭 제거

## 개요

| 항목 | 내용 |
|------|------|
| **기능명** | remove-legal-basis-tab |
| **작성일** | 2026-02-23 |
| **목적** | 결과 페이지에서 "법적 근거" 탭 및 관련 기능 제거 |
| **영향도** | 낮음 (UI 탭 제거, 백엔드 데이터는 유지) |

## 현황 분석

### 현재 화면 구성 (ResultPage 탭 구조)

```
[ 위험요소(5) ] [ 안전지침 & 법조항(5) ] [ 법적 근거(10) ] [ 체크리스트(4) ] [ 관련 자료(5) ]
                                          ^^^^^^^^^^^^^^^^
                                          ← 제거 대상
```

### "법적 근거" 관련 코드 위치

| 파일 | 위치 | 내용 | 변경유형 |
|------|------|------|----------|
| `frontend/src/pages/ResultPage.tsx` | L10 | `NormStatementsView` import | **삭제** |
| `frontend/src/pages/ResultPage.tsx` | L18 | activeTab 타입에 `'norms'` 포함 | **수정** |
| `frontend/src/pages/ResultPage.tsx` | L112-123 | "법적 근거" 탭 버튼 | **삭제** |
| `frontend/src/pages/ResultPage.tsx` | L150 | `NormStatementsView` 렌더링 | **삭제** |
| `frontend/src/components/results/HazardList.tsx` | L70-77 | 위험요소 카드의 `법적 근거:` 배지 | **삭제** |
| `frontend/src/components/results/NormStatementsView.tsx` | 전체 | 법적 근거 컴포넌트 | **삭제(파일)** |

### 변경하지 않는 항목 (백엔드 유지)

- `backend/app/api/v1/ontology.py` - 온톨로지 API 엔드포인트 유지
- `backend/app/services/ontology_service.py` - 온톨로지 서비스 유지
- `frontend/src/pages/OntologyPage.tsx` - 온톨로지 페이지(별도 라우트) 유지
- `frontend/src/api/ontologyApi.ts` - API 모듈 유지 (OntologyPage에서 사용)
- 백엔드 분석 시 `norm_context` 데이터 생성 로직 유지 (데이터 무결성)

## 변경 계획

### Step 1: ResultPage.tsx 수정

1. `NormStatementsView` import 제거 (L10)
2. `activeTab` 타입에서 `'norms'` 제거 (L18)
3. "법적 근거" 탭 버튼 블록 제거 (L112-123)
4. `norms` 탭 콘텐츠 렌더링 제거 (L150)

### Step 2: HazardList.tsx 수정

1. 위험요소 카드에서 `법적 근거:` 배지 제거 (L70-77)

### Step 3: NormStatementsView.tsx 삭제

1. `frontend/src/components/results/NormStatementsView.tsx` 파일 삭제

## 영향도 분석

- **사용자 영향**: 결과 페이지에서 "법적 근거" 탭이 사라지고, 위험요소 카드의 법적 근거 배지도 제거됨
- **온톨로지 페이지**: `/ontology` 라우트는 별도 페이지로 영향 없음
- **백엔드 API**: 변경 없음 — `norm_context` 데이터는 계속 반환되지만 프론트엔드에서 표시하지 않음
- **빌드 영향**: 미사용 import 제거로 번들 사이즈 소폭 감소

## 리스크

- **낮음**: 프론트엔드 UI 변경만 해당, 백엔드 로직 변경 없음
- 추후 법적 근거 기능이 다시 필요할 경우, git 히스토리에서 복구 가능

## 완료 조건

- [ ] "법적 근거" 탭이 결과 페이지에서 보이지 않음
- [ ] 위험요소 카드에서 "법적 근거:" 배지가 보이지 않음
- [ ] NormStatementsView.tsx 파일 삭제됨
- [ ] 빌드 에러 없음
- [ ] 나머지 탭(위험요소, 안전지침 & 법조항, 체크리스트, 관련 자료) 정상 동작
