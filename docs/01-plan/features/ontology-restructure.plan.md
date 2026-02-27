# Plan: ontology-restructure

> 온톨로지 구조 재설계 — 다양한 데이터 유형의 정확한 법령/지침 매칭을 위한 기반

## 1. 배경 및 목표

### 1.1 현재 상태 (AS-IS)

**온톨로지 3대 구조적 문제:**

| # | 문제 | 위치 | 영향 |
|---|------|------|------|
| P-1 | **데이터 소스 불일치**: 법조항은 law.go.kr 크롤링(690건) → `articles_cache.json` 사용 중이나, 코드 구조(`parse_all_pdfs()`, `source_file`)가 여전히 PDF 기반 설계 | `article_service.py`, `ontology_service.py` (6회 호출) | 새 데이터 유형 추가 시 확장 불가 |
| P-2 | **하드코딩된 조문 범위**: `CATEGORY_ARTICLE_RANGE`가 3곳에 각각 다른 값으로 하드코딩 | `ontology_service.py:1089`, `analysis_service.py:638`, `guide_service.py:79` | 편/장/절 구조 변경 시 3곳 수동 수정 필요 |
| P-3 | **규범명제-프롬프트 단절**: `norm_extractor.py`의 규범명제 카테고리(safety/procedure/equipment/management)와 `analysis_prompts.py`의 위험 카테고리(FALL/CRUSH/CHEMICAL 등)가 서로 다른 분류 체계 사용 | `norm_extractor.py`, `analysis_prompts.py` | 위험요소↔규범명제 매칭 시 카테고리 변환 누락 |

**온톨로지 레이어 현황:**

```
L1: 법조항 원문 (ArticleChunk)
    → article_number, title, content, source_file ← PDF 잔재

L2: 규범명제 (NormStatement)
    → subject_role, action, object, condition_text, legal_effect
    → norm_category: safety | procedure | equipment | management ← 4분류

L3: 의미적 매핑 (SemanticMapping)
    → source(article) ↔ target(guide/article)
    → relation_type: IMPLEMENTS | SUPPLEMENTS | SPECIFIES_CRITERIA | SPECIFIES_METHOD | CROSS_REFERENCES

L4: 위험 분석 (analysis_service)
    → category_code: FALL | CRUSH | CHEMICAL ... ← 24분류
    → hazard_category: physical | chemical | electrical | ergonomic | environmental | biological ← 6분류
```

**문제**: L2(4분류)와 L4(6분류, 24세부코드)가 **서로 다른 분류 체계**를 사용하여 정확한 연결이 불가능.

### 1.2 향후 확장 요구사항

| 데이터 유형 | 현재 | 목표 |
|-------------|------|------|
| 법령 조문 | articles_cache.json (690건) | law.go.kr 구조화 데이터 (편/장/절 계층) |
| KOSHA GUIDE | PDF 1050건 → ChromaDB | 유지 + 섹션별 규범명제 매핑 |
| 사례 영상 | safety_videos.json (3-Layer 매칭) | 온톨로지 기반 정확 매핑 |
| 작업 현장 사진 | GPT Vision 분석만 | 분석 결과 → 온톨로지 노드 매핑 |
| 사고 사례 DB | 없음 | 사고유형 → 법조항/가이드 역추적 |

### 1.3 목표

| # | 목표 | 측정 기준 |
|---|------|----------|
| G-1 | **통합 분류 체계** 구축: L2(규범명제)와 L4(위험분석)가 동일한 카테고리 코드 사용 | 분류 변환 코드 제거, 단일 매핑 테이블 |
| G-2 | **법조항 계층 구조** 도입: 편/장/절 메타데이터로 `CATEGORY_ARTICLE_RANGE` 하드코딩 제거 | 하드코딩 3곳 → DB 기반 조회 |
| G-3 | **다중 데이터 유형 매핑 지원**: article, guide, video, image_analysis 모두 SemanticMapping으로 연결 | source_type/target_type 확장 |
| G-4 | **LLM 프롬프트 온톨로지 연동**: 규범명제 기반으로 GPT 프롬프트가 자동 구성 | 프롬프트에 규범명제 컨텍스트 주입 |
| G-5 | **기존 정확도 유지**: 법령 ≥ 98%, KOSHA ≥ 93% | 코너 테스트 통과 |

---

## 2. 범위 (Scope)

### 2.1 In-Scope

**Phase 1: 분류 체계 통합 (핵심)**
- 통합 카테고리 코드 정의 (6대분류 + 24세부코드 → norm_category 매핑)
- `NormStatement.norm_category` 확장 (4분류 → 6+24 체계)
- `norm_extractor.py` 프롬프트 수정 (통합 코드 사용)
- `analysis_prompts.py`에 규범명제 카테고리 코드 반영

**Phase 2: 법조항 계층 구조 도입**
- `ArticleChunk` 확장: `part`, `chapter`, `section` 필드 추가
- `articles_cache.json` 스키마 확장 (계층 메타데이터)
- `CATEGORY_ARTICLE_RANGE` → DB 기반 조회로 전환 (3곳 통합)
- `article_service.parse_all_pdfs()` → `article_service.load_articles()` 리네이밍

**Phase 3: 다중 데이터 유형 매핑**
- `SemanticMapping.source_type/target_type` 확장: `video`, `image_analysis`, `accident_case`
- `video_service` 온톨로지 연동 (현재 3-Layer → SemanticMapping 기반)
- 이미지 분석 결과 → 온톨로지 노드 자동 생성

**Phase 4: LLM 프롬프트 온톨로지 연동**
- `analysis_prompts.py` 동적 생성: 규범명제 DB 기반 조문 구조 자동 구성
- `norm_extractor.py` 프롬프트 개선: 통합 카테고리 코드 + 계층 컨텍스트

### 2.2 Out-of-Scope
- law.go.kr API 직접 연동 (별도 plan으로 분리)
- PostgreSQL 전환 (현 SQLite 유지)
- 프론트엔드 온톨로지 시각화 대폭 개편 (기존 vis.js 유지)
- 사고 사례 DB 크롤링/구축 (구조만 준비)

---

## 3. 상세 설계

### 3.1 통합 분류 체계 (Unified Taxonomy)

```
┌─────────────────────────────────────────────────────────┐
│                  통합 카테고리 코드                        │
├─────────────┬──────────────────┬─────────────────────────┤
│ 대분류(6)   │ 세부코드(24)      │ 현재 norm_category 매핑  │
├─────────────┼──────────────────┼─────────────────────────┤
│ physical    │ FALL             │ safety                  │
│             │ SLIP             │ safety                  │
│             │ COLLISION        │ safety                  │
│             │ CRUSH            │ safety                  │
│             │ CUT              │ safety                  │
│             │ FALLING_OBJECT   │ safety                  │
├─────────────┼──────────────────┼─────────────────────────┤
│ chemical    │ CHEMICAL         │ safety                  │
│             │ FIRE_EXPLOSION   │ safety                  │
│             │ TOXIC            │ safety                  │
│             │ CORROSION        │ safety                  │
├─────────────┼──────────────────┼─────────────────────────┤
│ electrical  │ ELECTRIC         │ safety → equipment      │
│             │ ARC_FLASH        │ safety → equipment      │
├─────────────┼──────────────────┼─────────────────────────┤
│ ergonomic   │ ERGONOMIC        │ procedure               │
│             │ REPETITIVE       │ procedure               │
│             │ HEAVY_LIFTING    │ procedure               │
│             │ POSTURE          │ procedure               │
├─────────────┼──────────────────┼─────────────────────────┤
│ environmental│ NOISE           │ procedure               │
│             │ TEMPERATURE      │ safety                  │
│             │ LIGHTING         │ procedure               │
│             │ ENVIRONMENTAL    │ safety                  │
├─────────────┼──────────────────┼─────────────────────────┤
│ biological  │ BIOLOGICAL       │ safety                  │
└─────────────┴──────────────────┴─────────────────────────┘
```

**변경점**: `NormStatement.norm_category`를 `hazard_major` (6대분류) + `hazard_code` (24세부코드)로 분리

### 3.2 법조항 계층 구조

**articles_cache.json 스키마 확장:**

```json
{
  "article_number": "제42조",
  "title": "추락의 방지",
  "content": "...",
  "part": "제2편 안전기준",
  "chapter": "제1장 추락·붕괴 위험 방지",
  "section": null,
  "hazard_major": "physical",
  "hazard_codes": ["FALL"],
  "article_range_start": 42,
  "article_range_end": 55
}
```

**CATEGORY_ARTICLE_RANGE 제거 방법:**

현재 3곳 하드코딩:
```python
# ontology_service.py:1089-1096
CATEGORY_ARTICLE_RANGE = {
    "physical": [(32, 67), (86, 166)], ...
}

# analysis_service.py:638-645
CATEGORY_ARTICLE_RANGE = {
    "physical": [(3, 70), (86, 224), (328, 419)], ...
}

# guide_service.py:79-95
CLASSIFICATION_TO_ARTICLE_RANGE = {
    "G": None, "C": (328, 419), ...
}
```

→ **단일 매핑 테이블** `article_category_map.json`으로 통합:
```json
{
  "chapter_to_category": {
    "제1장 추락·붕괴 위험 방지": {"major": "physical", "codes": ["FALL", "FALLING_OBJECT"]},
    "제2장 폭발·화재·위험물": {"major": "chemical", "codes": ["FIRE_EXPLOSION", "CHEMICAL"]},
    "제3장 전기 안전": {"major": "electrical", "codes": ["ELECTRIC", "ARC_FLASH"]}
  },
  "classification_to_category": {
    "G": null,
    "C": {"major": "physical", "chapter_range": "제4장 건설작업"},
    "E": {"major": "electrical", "chapter_range": "제3장 전기 안전"},
    "M": {"major": "physical", "chapter_range": "제1장 기계·기구"}
  }
}
```

### 3.3 SemanticMapping 확장

현재:
```
source_type: "article" | "norm_statement"
target_type: "guide" | "article"
```

확장 후:
```
source_type: "article" | "norm_statement" | "hazard_code"
target_type: "guide" | "article" | "video" | "image_analysis" | "accident_case"
```

**새 relation_type 추가:**
```
기존 5종 유지:
  IMPLEMENTS, SUPPLEMENTS, SPECIFIES_CRITERIA, SPECIFIES_METHOD, CROSS_REFERENCES

신규 3종:
  ILLUSTRATES        - 영상/사진이 법조항/가이드를 시각적으로 예시
  DEMONSTRATES_RISK  - 사고사례가 위험요소를 실증
  ADDRESSES          - 법조항/가이드가 위험코드를 다룸
```

### 3.4 LLM 프롬프트 온톨로지 연동

**현재**: `analysis_prompts.py`에 산안법 전체 조문 구조가 **정적 문자열**로 하드코딩 (200+ 줄)

**개선**: 규범명제 DB에서 동적 생성

```python
# 개선 후 (개념 코드)
def build_article_structure_prompt(db: Session) -> str:
    """규범명제 DB에서 프롬프트용 조문 구조 동적 생성"""
    norms = db.query(NormStatement).order_by(NormStatement.article_number).all()

    # 장별 그룹핑 → 프롬프트 텍스트 생성
    chapters = group_by_chapter(norms)
    prompt_lines = []
    for chapter, articles in chapters.items():
        prompt_lines.append(f"#### {chapter}")
        for art in articles:
            prompt_lines.append(f"- {art.article_number}({art.title}): {art.effect_description}")

    return "\n".join(prompt_lines)
```

**장점**:
- 규범명제 추가/수정 시 프롬프트 자동 반영
- 조문 구조 변경에 강건
- 프롬프트 크기 최적화 가능 (관련 장만 포함)

---

## 4. 수정 파일 목록

### Phase 1: 분류 체계 통합

| 파일 | 변경 내용 |
|------|----------|
| `backend/app/db/models.py` | `NormStatement`에 `hazard_major`, `hazard_code` 필드 추가 |
| `backend/app/services/norm_extractor.py` | 프롬프트 수정: 통합 카테고리 코드 사용 |
| `backend/app/models/ontology.py` | `NormStatementResponse`에 새 필드 반영 |
| `backend/data/article_category_map.json` | **신규** - 통합 매핑 테이블 |

### Phase 2: 법조항 계층 구조

| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/article_service.py` | `parse_all_pdfs()` → `load_articles()` 리네이밍, 계층 필드 지원 |
| `backend/app/services/ontology_service.py` | `CATEGORY_ARTICLE_RANGE` 제거 → DB 조회 |
| `backend/app/services/analysis_service.py` | `CATEGORY_ARTICLE_RANGE` 제거 → 공통 매핑 참조 |
| `backend/app/services/guide_service.py` | `CLASSIFICATION_TO_ARTICLE_RANGE` → 공통 매핑 참조 |
| `backend/data/articles_cache.json` | 스키마 확장 (part, chapter, section) |

### Phase 3: 다중 데이터 유형 매핑

| 파일 | 변경 내용 |
|------|----------|
| `backend/app/db/models.py` | `SemanticMapping` source_type/target_type 확장 |
| `backend/app/services/video_service.py` | 온톨로지 매핑 기반으로 전환 |
| `backend/app/services/ontology_service.py` | 영상/이미지 매핑 발견 메서드 추가 |

### Phase 4: LLM 프롬프트 동적 생성

| 파일 | 변경 내용 |
|------|----------|
| `backend/app/integrations/prompts/analysis_prompts.py` | 정적 조문구조 → 동적 생성 함수 |
| `backend/app/integrations/openai_client.py` | 프롬프트 빌더 호출 연동 |
| `backend/app/services/norm_extractor.py` | 계층 컨텍스트 추가 |

---

## 5. 실행 순서 및 의존성

```
Phase 1 (분류 체계 통합) ─── 독립 실행 가능
    ↓
Phase 2 (법조항 계층 구조) ── Phase 1 결과 활용
    ↓
Phase 3 (다중 데이터 유형) ── Phase 2 결과 활용
    ↓
Phase 4 (LLM 프롬프트 연동) ─ Phase 1+2 필수
```

**권장 실행 단위**: Phase 1 → Phase 2를 먼저 완료하고 코너 테스트 검증 후 Phase 3 → 4 진행

---

## 6. 위험 요소 및 대응

| 위험 | 영향도 | 대응 |
|------|:------:|------|
| 규범명제 재추출 시 GPT 비용 발생 (690건 × gpt-4.1) | 높음 | 기존 규범명제 유지, 신규 필드만 LLM으로 보충 |
| `articles_cache.json` 스키마 변경으로 캐시 호환성 깨짐 | 중간 | 마이그레이션 스크립트 작성, 이전 포맷 폴백 지원 |
| 하드코딩 제거 시 기존 정확도 하락 | 높음 | Phase별 코너 테스트 필수 실행 |
| 프롬프트 동적 생성 시 토큰 수 변동 | 중간 | 장(chapter) 단위 필터링으로 토큰 제어 |
| `norm_extractor` 프롬프트 변경으로 기존 규범명제와 불일치 | 높음 | 신규 필드 별도 컬럼, 기존 데이터 유지 |

---

## 7. 검증 기준 (Check Phase 결과 — 2026-02-27 완료)

- [x] CR-1: 통합 카테고리 코드로 `NormStatement` ↔ `Hazard` 직접 매핑 가능 → `hazard_major` + `hazard_codes` 필드 추가
- [x] CR-2: `CATEGORY_ARTICLE_RANGE` 하드코딩 3곳 모두 제거 → `taxonomy.py` 통합
- [x] CR-3: `articles_cache.json`에 part/chapter/section 계층 메타데이터 포함 → `article_chapters.json` 기반
- [x] CR-4: `parse_all_pdfs()` → `load_articles()`로 리네이밍, 6곳 호출부 모두 수정 → alias 유지
- [x] CR-5: 코너 테스트 법령 ≥ 98%, KOSHA ≥ 93% 유지 → **법령 98.0% (49/50), KOSHA 100.0% (49/49)**
- [x] CR-6: SemanticMapping에 video/image_analysis 타입 매핑 가능 → `video_service.py` taxonomy 연동
- [x] CR-7: LLM 프롬프트에서 DB 기반 동적 조문 구조 사용 → `prompt_builder.py` 구현
- [x] CR-8: 기존 API 응답 형식 호환성 유지 (breaking change 없음) → 신규 필드 추가만

---

## 8. 현재 코드 대비 변경 영향 분석

### 8.1 `parse_all_pdfs()` 호출 지점 (6곳)

| 위치 | 용도 | 변경 방법 |
|------|------|-----------|
| `ontology_service.py:52` | 규범명제 추출 대상 로드 | → `load_articles()` |
| `ontology_service.py:229` | 미매핑 법조항 발견 | → `load_articles()` |
| `ontology_service.py:342` | 미매핑 가이드 매칭용 법조항 | → `load_articles()` |
| `ontology_service.py:528` | 상호참조 발견 | → `load_articles()` |
| `ontology_service.py:686` | 매핑 통계 | → `load_articles()` |
| `ontology_service.py:769` | 갭 분석 | → `load_articles()` |

### 8.2 `CATEGORY_ARTICLE_RANGE` 하드코딩 (3곳)

| 위치 | 현재 값 | 차이점 |
|------|---------|--------|
| `ontology_service.py:1089-1096` | physical: [(32,67),(86,166)] | 가장 좁은 범위 |
| `analysis_service.py:638-645` | physical: [(3,70),(86,224),(328,419)] | 가장 넓은 범위 |
| `guide_service.py:79-95` | M: (86,224), C: (328,419) | KOSHA 분류 기반 |

→ 3곳의 **범위가 서로 불일치**하는 것 자체가 버그 소지. 통합 매핑으로 일원화 필수.

### 8.3 norm_category 불일치

| norm_extractor 출력 | analysis_service 입력 | 매핑 필요 |
|---------------------|----------------------|-----------|
| safety | physical, chemical, electrical, environmental, biological | 1:5 |
| procedure | ergonomic, environmental | 1:2 |
| equipment | physical, electrical | 1:2 |
| management | (직접 대응 없음) | 별도 처리 |

→ 현재 `find_related_articles_for_hazards()`에서 `hazard_categories` (6분류)를 받아 `CATEGORY_ARTICLE_RANGE`로 변환하지만, norm_category와의 교차 매핑이 없어 **온톨로지 규범명제가 정확한 위험 유형과 연결되지 않음**.
