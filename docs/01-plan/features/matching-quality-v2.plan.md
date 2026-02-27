# matching-quality-v2 Planning Document

> **Note (2026-02-27)**: 이 문서에서 언급된 `CATEGORY_ARTICLE_RANGE`는 ontology-restructure에서 `taxonomy.py`로 교체되었습니다.

> **Summary**: 분석 결과 ↔ 법조항/KOSHA GUIDE 매칭 품질 전면 개선
>
> **Project**: OHS 위험요소 분석 서비스
> **Version**: 2.1.0
> **Author**: Claude (PDCA)
> **Date**: 2026-02-26
> **Status**: Draft

---

## 1. 현재 문제 진단

### 1.1 매칭 파이프라인 현황

```
[GPT 분석] → risks + recommended_guide_keywords
     │
     ├→ [법조항 매칭] vector search (ChromaDB) + category range filter
     │       threshold: 0.55 (너무 관대 or 너무 엄격)
     │       결과: 의미적으로 유사하지만 실제로 무관한 조문이 상위에 올라옴
     │
     ├→ [KOSHA GUIDE 매칭] 3-Path (C: 타이틀키워드, B: 벡터, Re-rank)
     │       Path C: 단순 startswith 매칭 → 복합어/유사어 놓침
     │       Path B: "키워드 + 안전지침 기술지침" 쿼리 → 의미 희석
     │       Re-rank: 키워드 카운팅 + 고정 부스트 → 정교하지 못함
     │
     └→ [영상 매칭] 3-Layer (카테고리 + 키워드 + 온톨로지)
             ↑ 법조항/가이드 매칭이 부정확하면 여기도 부정확
```

### 1.2 근본 원인 분석

| # | 문제 | 원인 | 영향도 |
|---|------|------|:------:|
| 1 | **임베딩 한계** | text-embedding-3-small이 한국 법률/안전 도메인에서 의미 구분력 부족 | 높음 |
| 2 | **매핑 커버리지 부족** | explicit 매핑만 1,861건. 법조항 47%, 가이드 33% 미매핑 | 높음 |
| 3 | **한국어 토큰화 부재** | `split()` 기반 키워드 추출 → 조사/어미 잔존, 복합명사 미분리 | 높음 |
| 4 | **쿼리 품질 낮음** | 위험요소 일상 설명을 그대로 검색 → 법률 용어와 갭 | 중간 |
| 5 | **재랭킹 미비** | 단순 키워드 카운팅. 의미적 관련성 재평가 없음 | 중간 |
| 6 | **피드백 루프 없음** | 매칭 결과의 정확성 측정/학습 메커니즘 없음 | 낮음 |
| 7 | **GPT 키워드 품질 변동** | recommended_guide_keywords가 부정확하면 Path C 전체 실패 | 중간 |

### 1.3 데이터 커버리지 현황 (docs/법조항_가이드_매핑현황.md 기준)

```
법조항 442개                        KOSHA GUIDE 1,030개
  매핑O: 234개 (53%)                 매핑O: 687개 (67%)
  매핑X: 208개 (47%)                 매핑X: 343개 (33%)
  ── 중 안전/위험 63개 (우선)         ── 중 안전/위험 198개 (우선)
  ── 중 절차/관리 68개 (낮음)         ── 중 절차/측정 52개 (낮음)
  1개 가이드만 연결: 137개 (59%)
```

---

## 2. 개선 아이디어 (우선순위 순)

### Idea A: GPT 프롬프트 강화 — 법조항 직접 추천 (영향도: 최고, 난이도: 낮음)

**현재:** GPT가 `recommended_guide_keywords`만 반환
**개선:** GPT가 `related_article_hints` (관련 법조항 번호 + 근거)도 직접 반환

```
변경점:
1. SYSTEM_PROMPT에 산안법 장/절 목차 요약 추가 (~500토큰)
2. JSON Schema에 related_article_hints 필드 추가
3. GPT가 추천한 조문번호를 벡터검색 결과와 교차 검증
```

**기대효과:** GPT는 이미 산안법 지식을 갖고 있음. 벡터검색이 놓치는 의미적 연관성을 GPT가 보완.
**비용:** 프롬프트 ~500토큰 추가 → 분석당 ~$0.002 증가

---

### Idea B: 카테고리 기반 하드필터링 강화 (영향도: 높음, 난이도: 낮음)

**현재:** `CATEGORY_ARTICLE_RANGE`로 범위 필터링하지만 벡터검색 **후** 보충용으로만 사용
**개선:** 벡터검색 **전** ChromaDB `where` 조건으로 메타데이터 필터링

```python
# 현재: 전체 컬렉션에서 검색 후 카테고리 보충
results = collection.query(query_embeddings=[emb], n_results=10)

# 개선: 카테고리 범위 내에서만 검색 (precision 향상)
results = collection.query(
    query_embeddings=[emb],
    n_results=10,
    where={"article_num_int": {"$gte": 32, "$lte": 67}}  # physical: 추락/끼임
)
```

**전제:** ChromaDB 인덱싱 시 `article_num_int` 메타데이터 추가 필요
**기대효과:** 검색 범위를 좁혀 precision 크게 향상. 화학 위험인데 건설 조문이 나오는 문제 해결.

---

### Idea C: LLM 기반 쿼리 재작성 (영향도: 높음, 난이도: 중간)

**현재:** 위험요소 description을 그대로 임베딩 → "칼이 테이블 위에 놓여있음" → 법률 용어와 괴리
**개선:** GPT-4.1-mini로 쿼리를 법률 용어로 변환

```
입력: "주방에 날카로운 칼이 무방비로 놓여있어 절단 사고 위험"
변환: "절단 위험 수공구 날 방호장치 안전조치 보관"
```

**구현:**
```python
async def rewrite_query_for_legal_search(description: str) -> str:
    """위험요소 설명 → 법률 검색 쿼리 변환"""
    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{
            "role": "system",
            "content": "위험요소 설명을 산업안전보건법 조문 검색에 적합한 법률 키워드로 변환하세요. 핵심 명사만 공백으로 구분하여 출력."
        }, {
            "role": "user",
            "content": description
        }],
        max_tokens=100
    )
    return response.choices[0].message.content
```

**비용:** gpt-4.1-mini → 분석당 ~$0.001 추가
**기대효과:** 일상 언어 ↔ 법률 용어 갭 해소

---

### Idea D: Cross-Encoder 재랭킹 (영향도: 높음, 난이도: 중간)

**현재:** 키워드 카운팅 + 고정 부스트로 재랭킹
**개선:** 검색 후보를 GPT-4.1-mini로 관련성 재평가

```
후보 10개 → GPT가 각각 관련성 점수 (0~10) 매김 → 상위 5개 반환
```

**구현:**
```python
RERANK_PROMPT = """위험요소와 법조항/가이드의 관련성을 0~10으로 평가하세요.
위험요소: {hazard_description}
후보:
{candidates}
JSON 배열로 [{id, score, reason}] 반환"""
```

**비용:** ~100토큰 입력 × 후보 수 → 분석당 ~$0.003
**기대효과:** 의미적 관련성을 정확히 평가. 단순 키워드 매칭의 한계 극복.

---

### Idea E: 한국어 형태소 분석 도입 (영향도: 중간, 난이도: 중간)

**현재:** `split()` + 조사 strip으로 키워드 추출 → 품질 낮음
**개선:** Kiwi/Mecab 등 한국어 형태소 분석기 도입

```python
# 현재
keywords = [w.rstrip("이가을를은는") for w in desc.split() if len(w) >= 2]

# 개선 (kiwi)
from kiwipiepy import Kiwi
kiwi = Kiwi()
tokens = kiwi.tokenize(desc)
keywords = [t.form for t in tokens if t.tag.startswith('NN')]  # 명사만 추출
```

**후보 라이브러리:**
- `kiwipiepy`: 순수 Python, pip install 가능, 빠름
- `konlpy + mecab`: 더 정확하지만 시스템 의존성 있음

**기대효과:** "추락방지조치" → ["추락", "방지", "조치"], "안전난간설치" → ["안전", "난간", "설치"]

---

### Idea F: 임베딩 모델 업그레이드 (영향도: 중간, 난이도: 높음)

**현재:** `text-embedding-3-small` (1536차원)
**옵션:**

| 모델 | 차원 | 비용 | 한국어 성능 |
|------|------|------|------------|
| text-embedding-3-small (현재) | 1536 | $0.02/1M tokens | 보통 |
| text-embedding-3-large | 3072 | $0.13/1M tokens | 좋음 |
| 로컬 multilingual-e5-large | 1024 | 무료 | 매우 좋음 |

**고려사항:**
- 모델 변경 시 전체 재인덱싱 필요 (법조항 442개 + 가이드 섹션 수천개)
- ChromaDB 컬렉션 재생성
- 비용 vs 품질 트레이드오프

**추천:** text-embedding-3-large로 업그레이드 (6.5배 비용이지만 재인덱싱 1회성)

---

### Idea G: Hybrid Search (BM25 + Vector) (영향도: 중간, 난이도: 높음)

**현재:** 벡터검색만 사용 → 키워드 정확매칭을 놓침
**개선:** BM25 키워드검색 + 벡터검색 결과를 RRF(Reciprocal Rank Fusion)로 병합

```
BM25: "추락 방지" → 제42조 (정확 매칭)
Vector: "높은 곳에서 떨어질 위험" → 제42조 (의미 매칭)
RRF: 두 결과를 랭크 기반으로 병합
```

**구현 옵션:**
1. SQLite FTS5 활용 (이미 SQLite 사용 중)
2. 별도 BM25 라이브러리 (rank_bm25)
3. ChromaDB의 향후 하이브리드 서치 지원 대기

---

### Idea H: 온톨로지 매핑 자동 확장 실행 (영향도: 높음, 난이도: 낮음)

**현재:** `POST /ontology/discover-mappings` API가 이미 구현되어 있지만 실행 여부 불명확
**개선:** 미매핑 자동 발견을 실행하여 커버리지 확대

```
현재: explicit 매핑만 1,861건 (법조항 53% 커버)
목표: explicit + semantic 매핑으로 법조항 80%+ 커버
```

**즉시 실행 가능:**
1. `/ontology/extract-norms` → 규범명제 추출
2. `/ontology/classify-mappings` → 매핑 관계 분류
3. `/ontology/discover-mappings` → 미매핑 발견 (벡터+키워드+참조)

---

## 3. 추천 구현 순서

### Phase 1: Quick Wins (1~2일, 코드 변경 최소)

| 순서 | 아이디어 | 예상 효과 | 작업량 |
|:----:|---------|----------|:------:|
| 1 | **H: 온톨로지 매핑 확장 실행** | 커버리지 53% → 80%+ | 낮음 (API 호출) |
| 2 | **A: GPT 프롬프트에 법조항 목차 + 직접 추천** | 정확도 크게 향상 | 낮음 |
| 3 | **B: 카테고리 하드필터링 강화** | 무관한 조문 제거 | 낮음 |

### Phase 2: Core Improvements (3~5일)

| 순서 | 아이디어 | 예상 효과 | 작업량 |
|:----:|---------|----------|:------:|
| 4 | **C: LLM 쿼리 재작성** | 검색 쿼리 품질 향상 | 중간 |
| 5 | **D: Cross-Encoder 재랭킹** | 결과 정렬 정확도 향상 | 중간 |
| 6 | **E: 한국어 형태소 분석** | 키워드 추출 품질 향상 | 중간 |

### Phase 3: Advanced (1주+)

| 순서 | 아이디어 | 예상 효과 | 작업량 |
|:----:|---------|----------|:------:|
| 7 | **F: 임베딩 모델 업그레이드** | 전반적 검색 품질 향상 | 높음 |
| 8 | **G: Hybrid Search** | recall + precision 동시 향상 | 높음 |

---

## 4. 비용/효과 요약

```
                    효과 ↑
                    │
         [A: GPT추천] ★★★   [D: 재랭킹]
                    │           ★★
         [H: 매핑확장] ★★★
                    │        [C: 쿼리재작성]
         [B: 필터링] ★★        ★★
                    │
                    │     [E: 형태소] [F: 임베딩] [G: 하이브리드]
                    │        ★           ★★          ★★
                    └──────────────────────────────────── 비용/작업량 →
                   낮음                                    높음
```

**Phase 1만으로도 체감 가능한 개선 예상.** 특히 A(GPT 직접 추천) + H(매핑 확장)의 조합이 가장 ROI 높음.

---

## 5. 다음 단계

- [ ] 우선 적용할 아이디어 선택 (A~H 중)
- [ ] 선택된 아이디어의 Design 문서 작성
- [ ] 구현 → 테스트 시나리오 20건 검증

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-26 | Initial draft - 8개 개선 아이디어 정리 | Claude (PDCA) |
