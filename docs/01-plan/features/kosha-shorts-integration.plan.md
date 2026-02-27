# Plan: KOSHA 숏폼영상 온톨로지 연계

## 개요

| 항목 | 내용 |
|------|------|
| **기능명** | kosha-shorts-integration |
| **작성일** | 2026-02-23 |
| **목적** | KOSHA 안전 숏폼영상 233개를 온톨로지와 연계하여 위험요소 분석 결과의 "관련 자료" 탭에 맥락에 맞는 영상을 노출 |
| **영향도** | 중간 (백엔드 리소스 시스템 확장 + 프론트엔드 영상 카드 추가) |

---

## 현황 분석

### 현재 리소스 시스템

```
분석 요청 → GPT 위험요소 식별 → hazard_categories 추출
                                       ↓
                    resource_service.get_resources_by_categories()
                                       ↓
                    resources.json (정적 10개) → 카테고리 substring 매칭 → max 5개
                                       ↓
                              "관련 자료" 탭에 표시
```

**문제점**:
- 정적 JSON 파일에 10개 리소스만 존재
- 단순 카테고리 substring 매칭 (온톨로지 활용 없음)
- 영상 콘텐츠 부족

### KOSHA 숏폼영상 데이터 (233개)

| 데이터 필드 | 예시 |
|-------------|------|
| 제목 | `[안전쏙] 바닥 개구부_안전수칙` |
| URL | `https://youtube.com/shorts/...` |
| 분야 | `건설안전 / 개구부` |

**분야 분포** (상위 10개):
- 이지애의 안전있수다 시리즈: 21개
- 건설업 YES or NO 시리즈: 20개
- 안전쏙 시리즈: 20개
- 안전일터 응원캠페인: 18개
- 이수지의 괜찮으시겠어요? 시리즈: 15개
- 중대재해처벌법 시리즈: 12개
- 안전법규 (안전 PLAY): 11개
- 조선업 3D 재해사례: 9개

### 온톨로지 구조 (활용 가능한 연결고리)

```
SemanticMapping 테이블 (핵심)
├── article_number (법조항) ←→ guide_id (KOSHA 가이드)
├── relation_type: IMPLEMENTS | SPECIFIES_CRITERIA | SPECIFIES_METHOD | ...
├── confidence: 0.0 ~ 1.0
└── discovery_method: explicit | llm | vector | keyword

NormStatement 테이블
├── article_number, action, object, condition_text
├── legal_effect: OBLIGATION | PROHIBITION | PERMISSION | EXCEPTION
└── norm_category: safety | procedure | equipment | management
```

---

## 연계 아이디어: 3-Layer 매칭

### Layer 1: 카테고리 직접 매칭 (기존 방식 확장)

영상의 "분야"를 기존 `hazard_categories`에 매핑:

```
영상 분야                    →  hazard_category
──────────────────────────────────────────────
건설안전 / 추락예방          →  physical, fall
건설안전 / 사다리            →  physical, fall
화학안전 / 폭발예방          →  chemical, explosion
기계끼임                     →  physical, mechanical
밀폐공간 / 질식예방          →  chemical, suffocation
전기안전                     →  electrical
온열질환 / 폭염              →  environmental, heat
```

→ 기존 `get_resources_by_categories()`에 영상도 포함되어 자동 매칭

### Layer 2: 키워드 매칭 (제목 ↔ 위험요소 설명)

GPT가 추출한 위험요소 설명과 영상 제목 간 키워드 매칭:

```python
# 위험요소: "작업자가 이동식 사다리에서 추락할 위험"
# 매칭 키워드: 사다리, 추락

# → 영상 매칭:
# [이수지의 괜찮으시겠어요?] 이동식 사다리(방지장치 설치)
# [건설업 YES or NO] 사다리 재해예방
# [안전 PLAY] 산업안전보건 기준 - 추락(2)
```

### Layer 3: 온톨로지 경유 매칭 (핵심 차별화)

```
위험요소 → 관련 법조항(article) → SemanticMapping → KOSHA 가이드
                                                         ↓
                                              가이드 분류코드 ← → 영상 분야
```

**구체적 흐름:**

1. 분석에서 `norm_context`로 관련 법조항이 이미 식별됨 (예: 제42조 추락위험방지)
2. `SemanticMapping`에서 해당 법조항에 연결된 가이드 조회 (예: G-44-2011 수공구 안전지침)
3. 가이드의 classification(G=일반안전, C=건설안전, M=기계안전 등)으로 영상 필터
4. 영상의 분야 태그와 가이드 키워드 교차 매칭

**예시:**

```
위험요소: "칼, 가위 등 예리한 도구의 노출"
  ↓ vector search
법조항: 제42조 (추락위험방지) + 제80조 (절단기 방호)
  ↓ SemanticMapping
가이드: G-44-2011(수공구 안전지침), M-178-2014(베니어 절단기계)
  ↓ classification 매핑
영상 분야 매칭: "제조업 / 기계끼임", "제조업 / 식품가공 기계"
  ↓
결과: [3D] 기계 끼임 사고, [안전쏙] 식품가공용기계_안전수칙
```

---

## 구현 방안

### Option A: resources.json 확장 (간단)

- `resources.json`에 233개 영상을 `type: "video"`로 추가
- `hazard_categories` 필드에 매핑된 카테고리 넣기
- 기존 매칭 로직 그대로 활용

**장점**: 변경 최소, 빠른 구현
**단점**: Layer 2, 3 매칭 불가, 카테고리 매핑 수작업

### Option B: DB 테이블 + ChromaDB 임베딩 (권장)

#### 새 테이블: `safety_videos`

```python
class SafetyVideo(Base):
    __tablename__ = "safety_videos"

    id: int (PK)
    title: str                    # 영상 제목
    url: str                      # YouTube Shorts URL
    category: str                 # 분야 (원본)
    tags: str (JSON)              # 키워드 태그 ["추락", "사다리", "건설"]
    hazard_categories: str (JSON) # ["physical", "fall"]
    guide_classifications: str    # 관련 가이드 분류 ["G", "C"]
    thumbnail_url: str            # YouTube 썸네일
    is_korean: bool               # 한국어 여부
    series: str                   # 시리즈명 (안전쏙, YES or NO 등)
```

#### ChromaDB 임베딩

```python
# 영상 제목 + 분야를 임베딩하여 벡터 검색 가능하게
collection = chroma_client.get_or_create_collection("safety_videos")
collection.add(
    documents=[f"{video.title} {video.category}"],
    metadatas=[{"url": video.url, "category": video.category}],
    ids=[str(video.id)]
)
```

#### 매칭 서비스 확장

```python
class VideoService:
    def find_related_videos(self, hazard_descs, hazard_categories, norm_articles):
        results = []

        # Layer 1: 카테고리 매칭
        cat_matches = self.match_by_category(hazard_categories)

        # Layer 2: 제목 키워드 매칭
        keyword_matches = self.match_by_keywords(hazard_descs)

        # Layer 3: 온톨로지 경유 매칭
        ontology_matches = self.match_by_ontology(norm_articles)

        # 통합 스코어링 + 중복 제거
        return self.merge_and_rank(cat_matches, keyword_matches, ontology_matches, max=5)
```

**장점**: 3-Layer 매칭, 의미적 검색, 확장 용이
**단점**: 구현 범위 넓음

### Option C: 하이브리드 (실용적 절충)

- `resources.json`에 영상 추가 (Layer 1)
- `resource_service`에 제목 키워드 매칭 로직 추가 (Layer 2)
- 온톨로지 연계는 가이드 classification 기반 필터만 적용 (Layer 3 간소화)

**장점**: 적절한 노력 대비 효과
**단점**: 벡터 검색 없음, 정확도 약간 떨어짐

---

## 프론트엔드 변경

### ResourceLinks.tsx 영상 카드 개선

현재 `type: "video"`도 지원하지만, YouTube Shorts에 최적화된 UI 추가:

```
┌──────────────────────────────────┐
│ 🎬 [YouTube 썸네일]              │
│ [이지애의 안전있수다]             │
│ 지게차 재해예방(작업계획서)        │
│ 🏷 물류 / 지게차 안전             │
│ ▶ 숏폼 보기                      │
└──────────────────────────────────┘
```

- YouTube Shorts 썸네일 자동 생성: `https://img.youtube.com/vi/{VIDEO_ID}/0.jpg`
- 분야 태그 표시
- 시리즈명 배지 (안전쏙, YES or NO 등)

---

## 카테고리 매핑표 (영상 분야 → hazard_category)

| 영상 분야 키워드 | hazard_categories |
|-----------------|-------------------|
| 추락, 떨어짐, 사다리, 비계, 개구부, 지붕 | `["physical", "fall"]` |
| 끼임, 기계, 프레스, 롤러, 컨베이어, 로봇 | `["physical", "mechanical"]` |
| 화학, 폭발, 중독, 유해물질 | `["chemical"]` |
| 밀폐공간, 질식 | `["chemical", "suffocation"]` |
| 전기, 감전, 정전, 활선 | `["electrical"]` |
| 온열질환, 폭염 | `["environmental", "heat"]` |
| 화재, 용접, 화기 | `["fire"]` |
| 지게차, 크레인, 굴착기, 화물자동차 | `["physical", "vehicle"]` |
| 넘어짐, 미끄러짐 | `["physical", "slip"]` |
| 낙하물, 부딪힘 | `["physical", "struck"]` |
| 분진, 건강장해, 근골격계 | `["health"]` |
| 위험성평가 | `["management"]` |

---

## 기대 효과

| 항목 | Before | After |
|------|--------|-------|
| 관련 자료 수 | 정적 10개 | 233개 영상 + 기존 10개 |
| 매칭 방식 | 카테고리 substring | 3-Layer (카테고리 + 키워드 + 온톨로지) |
| 콘텐츠 유형 | 주로 문서/웹사이트 | 숏폼 영상 중심 |
| 사용자 경험 | 일반적 링크 | YouTube 썸네일 + 시리즈 배지 |
| 온톨로지 활용 | 법조항/가이드만 | 법조항 → 가이드 → 영상까지 연결 |

---

## 리스크

- **YouTube URL 유효성**: 영상 삭제/비공개 전환 시 dead link 발생 가능
- **카테고리 매핑 정확도**: 영상 분야 태그가 broad하여 오매칭 가능
- **영상 수 증가**: 채널 업데이트 시 수동 관리 필요 (자동화 고려)

## 다음 단계

구현 방안 A/B/C 중 선택 후 Design 단계 진행
