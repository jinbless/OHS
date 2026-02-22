# Plan: analysis-ontology-integration

> 위험분석 연동 — 기존 analysis_service에 ontology_service 경로 추가

## 1. 배경 및 목표

### 1.1 현재 상태
- `analysis_service._create_response()`가 위험분석 결과를 생성할 때 KOSHA GUIDE 검색은 수행하지만,
  **온톨로지 매핑(semantic_mappings) 데이터를 전혀 활용하지 않는다.**
- `Hazard.legal_reference` 필드가 항상 `None`으로 설정되어 법적 근거 정보가 빠져 있다.
- 가이드 재순위(Re-rank)가 GPT 키워드 + 타이틀 매칭에만 의존하며,
  2,972건의 시맨틱 매핑(5종 관계유형, 4종 발견방법)이 반영되지 않는다.

### 1.2 목표
| # | 목표 | 측정 기준 |
|---|------|----------|
| G-1 | 위험분석 결과에 **관련 법조항 + 규범명제** 자동 연결 | `legal_reference` ≠ None (위험요소당 1개 이상) |
| G-2 | 시맨틱 매핑 기반 **가이드 Re-rank 강화** | IMPLEMENTS/SPECIFIES_CRITERIA 관계 가이드 우선 |
| G-3 | 프론트엔드 결과 페이지에 **규범명제 탭** 추가 | ResultPage에 norms 탭 표시 |

## 2. 범위 (Scope)

### 2.1 In-Scope
- **백엔드**: `analysis_service._create_response()` 수정
  - `ontology_service` 호출로 관련 법조항 매칭
  - `legal_reference` 필드 채우기
  - 시맨틱 매핑 기반 가이드 부스트 추가
- **백엔드**: `AnalysisResponse` 모델에 `norm_statements` 필드 추가
- **프론트엔드**: `ResultPage`에 규범명제 탭 추가
- **프론트엔드**: `HazardList` 컴포넌트에 법적 근거 표시

### 2.2 Out-of-Scope
- 온톨로지 서비스 자체의 수정 (이미 완성됨)
- 새로운 API 엔드포인트 추가 (기존 엔드포인트 내에서 처리)
- AI 분석 프롬프트 수정

## 3. 연동 아키텍처

```
AnalysisService._create_response()
├── [기존] AI 분석 결과 → Hazard 변환
├── [기존] KOSHA GUIDE 검색 (Path C + Path B)
│
├── [NEW] 온톨로지 법조항 매칭
│   ├── 각 Hazard 카테고리 → article_service에서 관련 법조항 검색
│   ├── ontology_service.get_article_norms() → 규범명제 조회
│   └── Hazard.legal_reference 채우기
│
├── [NEW] 시맨틱 매핑 기반 가이드 부스트
│   ├── semantic_mappings에서 관련 가이드 조회
│   ├── relation_type별 가중치: IMPLEMENTS(+0.2), SPECIFIES_CRITERIA(+0.25), SPECIFIES_METHOD(+0.15), SUPPLEMENTS(+0.05)
│   └── 기존 Re-rank 점수에 합산
│
└── [NEW] 응답에 norm_statements 포함
    └── 매칭된 법조항의 규범명제 리스트
```

## 4. 수정 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/analysis_service.py` | ontology_service 연동, legal_reference 채우기, 시맨틱 부스트 |
| `backend/app/models/analysis.py` | `AnalysisResponse`에 `norm_statements` 필드 추가 |
| `backend/app/models/hazard.py` | `Hazard`에 `related_norms` 필드 추가 (Optional) |
| `frontend/src/pages/ResultPage.tsx` | 규범명제 탭 추가 |
| `frontend/src/components/results/NormStatementsView.tsx` | 새 컴포넌트 (규범명제 표시) |
| `frontend/src/components/results/HazardList.tsx` | legal_reference 표시 추가 |

## 5. 위험 요소 및 대응

| 위험 | 영향 | 대응 |
|------|------|------|
| 법조항 매칭이 부정확할 수 있음 | 잘못된 법적 근거 제시 | confidence ≥ 0.7 이상만 표시 |
| 성능 저하 (DB 추가 쿼리) | 응답 시간 증가 | 가이드 검색 후 단일 쿼리로 배치 조회 |
| 규범명제 미추출 법조항 | legal_reference 빈 상태 유지 | None 허용, 프론트에서 미표시 |

## 6. 검증 기준 (Check Phase에서 사용)

- [ ] CR-1: `legal_reference` 필드가 High/Critical 위험요소에 대해 80% 이상 채워짐
- [ ] CR-2: 시맨틱 부스트 적용 후 IMPLEMENTS 관계 가이드가 상위 3개에 포함됨
- [ ] CR-3: 프론트엔드 결과 페이지에 규범명제 탭이 정상 렌더링
- [ ] CR-4: 기존 분석 API 응답 시간 ≤ 기존 대비 +500ms
- [ ] CR-5: 기존 분석 기능 회귀 없음 (hazard, checklist, guide 정상)
