# Design: analysis-ontology-integration

> 위험분석 연동 — 기존 analysis_service에 ontology_service 경로 추가

## 1. 구현 순서

```
Step 1: Pydantic 모델 확장
Step 2: 온톨로지 법조항 매칭 메서드 추가 (ontology_service)
Step 3: analysis_service._create_response() 수정
Step 4: 프론트엔드 NormStatementsView 컴포넌트
Step 5: ResultPage 탭 추가 + HazardList legal_reference 표시
Step 6: Docker 재빌드 + 배포
```

## 2. 상세 설계

### Step 1: Pydantic 모델 확장

**`backend/app/models/hazard.py`**
```python
class Hazard(BaseModel):
    # ... 기존 필드 유지
    legal_reference: Optional[str] = None        # 기존 (값 채우기)
    related_norms: List[NormSummary] = []         # NEW

class NormSummary(BaseModel):
    """위험요소에 연결된 규범명제 요약"""
    article_number: str
    legal_effect: str       # OBLIGATION, PROHIBITION, PERMISSION, EXCEPTION
    action: Optional[str]
    full_text: str
```

**`backend/app/models/analysis.py`**
```python
class NormContext(BaseModel):
    """분석 결과에 포함되는 온톨로지 컨텍스트"""
    article_number: str
    article_title: Optional[str]
    norms: List[NormSummary]
    linked_guides: List[LinkedGuideSummary]

class LinkedGuideSummary(BaseModel):
    guide_code: str
    title: str
    relation_type: str
    confidence: float

class AnalysisResponse(BaseModel):
    # ... 기존 필드 유지
    norm_context: List[NormContext] = []           # NEW
```

### Step 2: 온톨로지 법조항 매칭 메서드

**`backend/app/services/ontology_service.py`** — 신규 메서드 추가

```python
def find_related_articles_for_hazards(
    self, db: Session, hazard_descriptions: list[str], hazard_categories: list[str]
) -> list[dict]:
    """위험요소 설명 + 카테고리로 관련 법조항 찾기

    로직:
    1. hazard_descriptions 벡터 검색 → article_service.collection에서 유사 법조항 탑 3
    2. 각 법조항의 규범명제 조회 (norm_statements)
    3. 각 법조항의 시맨틱 매핑 가이드 조회

    Returns: list of {article_number, article_title, norms: [...], linked_guides: [...]}
    """
```

```python
def get_semantic_boost_for_guides(
    self, db: Session, guide_codes: list[str]
) -> dict[str, float]:
    """가이드 코드별 시맨틱 매핑 부스트 점수

    Returns: {guide_code: boost_score}
    - IMPLEMENTS: +0.20
    - SPECIFIES_CRITERIA: +0.25
    - SPECIFIES_METHOD: +0.15
    - SUPPLEMENTS: +0.05
    - CROSS_REFERENCES: +0.10
    """
```

### Step 3: analysis_service._create_response() 수정

```python
def _create_response(self, db, result, analysis_type, input_preview):
    # ... [기존] Hazard 변환, Checklist 변환

    # ... [기존] KOSHA GUIDE 검색 (Path C + Path B)

    # [NEW-1] 시맨틱 매핑 부스트 (Re-rank 단계에 삽입)
    # guide_results_map이 완성된 후, Re-rank 전에:
    semantic_boost = ontology_service.get_semantic_boost_for_guides(
        db, list(guide_results_map.keys())
    )
    # Re-rank 루프에서 semantic_boost 적용

    # ... [기존] 정렬 + 법조항 역매핑

    # [NEW-2] 온톨로지 법조항 매칭
    hazard_descs = [r.get("description", "") for r in result.get("risks", [])]
    hazard_cats = hazard_categories
    norm_context = ontology_service.find_related_articles_for_hazards(
        db, hazard_descs, hazard_cats
    )

    # [NEW-3] Hazard.legal_reference 채우기
    for hazard in hazards:
        best_match = _find_best_norm_for_hazard(hazard, norm_context)
        if best_match:
            hazard.legal_reference = f"{best_match['article_number']} ({best_match['article_title']})"
            hazard.related_norms = best_match['norms'][:3]

    # 응답 생성
    response = AnalysisResponse(
        # ... 기존 필드
        norm_context=norm_context,  # NEW
    )
```

**법조항-위험요소 매칭 로직 (`_find_best_norm_for_hazard`)**:
```
1. HazardCategory → 관련 법조항 범위 매핑
   - physical: 제32조~제67조 (기계·기구 안전)
   - chemical: 제225조~제290조 (화학물질)
   - electrical: 제301조~제339조 (전기)
   - ergonomic: 제656조~제671조 (근골격계)
   - environmental: 제559조~제586조 (소음·진동·온열)
   - biological: 제592조~제604조 (병원체)

2. norm_context에서 카테고리 범위 내 법조항 우선 매칭
3. 범위 내 없으면 벡터 유사도 최상위 법조항 매칭
```

### Step 4: 프론트엔드 NormStatementsView 컴포넌트

**`frontend/src/components/results/NormStatementsView.tsx`**

```
┌─────────────────────────────────────────────┐
│ 📋 관련 법적 근거 (규범명제)                  │
├─────────────────────────────────────────────┤
│ ┌─ 제42조 (보호구의 지급 등)                 │
│ │  ▪ [의무] 사업주는 근로자에게 보호구를...   │
│ │  ▪ [의무] 보호구는 해당 작업에 적합한...     │
│ │                                             │
│ │  연결 가이드:                               │
│ │  • G-34 보호구 안전보건가이드 (95%)         │
│ │  • G-78 개인보호구 관리지침 (88%)           │
│ └────────────────────────────────────────────│
│ ┌─ 제63조 (통로의 설치)                       │
│ │  ▪ [의무] 사업주는 작업장으로 통하는...      │
│ └────────────────────────────────────────────│
└─────────────────────────────────────────────┘
```

### Step 5: ResultPage + HazardList 수정

**ResultPage.tsx**: 탭에 "법적 근거" 추가
```tsx
// 탭 순서: 위험요소 | 안전지침 | 법적 근거 | 체크리스트 | 관련 자료
{activeTab === 'norms' && <NormStatementsView norms={currentAnalysis.norm_context} />}
```

**HazardList.tsx**: 각 Hazard 카드에 `legal_reference` 표시
```tsx
{hazard.legal_reference && (
  <div className="text-xs text-blue-600 mt-2">
    📖 {hazard.legal_reference}
  </div>
)}
```

### Step 6: Docker 재빌드

```bash
cd /home/blessjin/cashtoss/ohs
docker compose up -d --build
```

## 3. 시맨틱 부스트 가중치

| relation_type | boost | 근거 |
|--------------|-------|------|
| SPECIFIES_CRITERIA | +0.25 | 가장 구체적 (정량 기준) |
| IMPLEMENTS | +0.20 | 직접 이행 관계 |
| SPECIFIES_METHOD | +0.15 | 방법 명시 |
| CROSS_REFERENCES | +0.10 | 참조 관계 |
| SUPPLEMENTS | +0.05 | 보충 관계 (약한 연결) |

## 4. 카테고리별 법조항 범위 매핑

| HazardCategory | 법조항 범위 | 근거 |
|---------------|------------|------|
| physical | 제32조~제67조 | 기계·기구 안전조치 |
| chemical | 제225조~제290조 | 유해·위험물질 관리 |
| electrical | 제301조~제339조 | 전기 위험방지 |
| ergonomic | 제656조~제671조 | 근골격계 부담 작업 |
| environmental | 제559조~제586조 | 소음·진동·온열 |
| biological | 제592조~제604조 | 병원체 관리 |

## 5. 검증 기준 (Check Phase)

| ID | 기준 | 측정 방법 | 합격 |
|----|------|----------|------|
| CR-1 | legal_reference 채움률 | 텍스트 분석 → High/Critical hazard 중 legal_reference ≠ None | ≥ 80% |
| CR-2 | 시맨틱 부스트 효과 | IMPLEMENTS 관계 가이드가 상위 3개 중 1개 이상 | True |
| CR-3 | 규범명제 탭 렌더링 | /ohs/result/{id} 페이지에서 법적 근거 탭 표시 | True |
| CR-4 | 응답 시간 | 기존 대비 분석 API 응답 시간 | ≤ +500ms |
| CR-5 | 회귀 테스트 | 기존 hazard/checklist/guide 정상 | True |
