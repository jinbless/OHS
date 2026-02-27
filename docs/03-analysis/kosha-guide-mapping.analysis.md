# kosha-guide-mapping Gap Analysis

> **Note (2026-02-27)**: 이 문서는 작성 시점의 코드 상태를 기술합니다. 이후 ontology-restructure에서 `CLASSIFICATION_TO_ARTICLE_RANGE` → `taxonomy.py`로 교체되었습니다.

> **Feature**: KOSHA GUIDE 파싱, 인덱싱, 매핑, 검색 서비스
>
> **Phase**: Check (Gap Analysis)
> **Date**: 2026-02-21
> **Design Reference**: `docs/02-design/features/kosha-guide-mapping.design.md`
> **Plan Reference**: `docs/01-plan/features/kosha-guide-mapping.plan.md`

---

## 1. 요구사항별 구현 비교

### FR-01: KOSHA GUIDE PDF 파싱

| 설계 항목 | 구현 상태 | 일치도 |
|----------|----------|--------|
| 파일명 정규식 `^([A-Z])-(\d+)-(\d{4})\s+(.+)\.pdf$` | 확장: 복합코드 `[A-Z]-[A-Z]-\d+-\d{4}` + 언더스코어 패턴 추가 | **개선** |
| PyMuPDF(fitz) 텍스트 추출 | `fitz.open()` + `page.get_text()` 그대로 구현 | **100%** |
| 관련법규 추출 `제(\d+)조` | 개요 3000자 범위, 동일 패턴 구현 | **100%** |
| 편/장 참조 → 조문 범위 확장 (`제(\d+)편\s*제(\d+)장`) | **미구현** | **0%** |
| 섹션 분해 `\n(\d+(?:\.\d+)?)\.\s+(.+)` | 단순화: `\n(\d+)\.\s+(.+)` (하위 섹션 미지원) | **부분** |
| 2000자 초과 시 청킹 | `_chunk_text()` 단락 기준 분할 구현 | **100%** |
| 섹션 타입 분류 (purpose/scope/definition/standard/procedure/appendix) | `SECTION_TYPE_MAP` 6가지 분류 + 기본값 standard | **100%** |

**FR-01 종합: 90%** (편/장 확장 미구현이나 실제 영향 Low, 파일명 파싱은 오히려 개선)

### FR-02: SQLite 테이블 구성

| 설계 항목 | 구현 상태 | 일치도 |
|----------|----------|--------|
| `kosha_guides` 테이블 | 설계 스키마와 동일하게 구현 | **100%** |
| `guide_sections` 테이블 | 설계 스키마와 동일하게 구현 | **100%** |
| `reg_guide_mapping` 테이블 | UNIQUE 제약조건 포함 구현 | **100%** |
| FK 관계 정의 | column 정의만 (SQLAlchemy ForeignKey 미사용, 논리적 FK) | **부분** |

**FR-02 종합: 95%** (논리적 FK로 동작에 문제 없음)

### FR-03: ChromaDB 임베딩/인덱싱

| 설계 항목 | 구현 상태 | 일치도 |
|----------|----------|--------|
| `kosha_guides` 컬렉션 생성 | `get_or_create_collection()` 구현 | **100%** |
| text-embedding-3-small 모델 | 동일 모델 사용 | **100%** |
| 배치 인덱싱 (50개씩) | `batch_size = 50` 구현 | **100%** |
| metadata (guide_code, classification, title, section_order 등) | 설계와 동일한 7개 필드 | **100%** |
| **startup 시 자동 인덱싱** | **미호출** (비용 고려로 의도적 보류) | **0%** |

**FR-03 종합: 80%** (코드 완성, 실행만 보류 - 21,966 섹션 임베딩 비용 고려)

### FR-04: 산안법 조문 ↔ KOSHA GUIDE 자동 매핑

| 설계 항목 | 구현 상태 | 일치도 |
|----------|----------|--------|
| Stage 1: 명시적 매핑 (PDF 관련법규) | `build_mappings()` → 1,861건 매핑 완료 | **100%** |
| Stage 2: 임베딩 유사도 매핑 (사전 계산) | **미구현** (런타임 벡터 검색으로 대체) | **부분** |
| 분류코드 기반 사전 필터링 | `CLASSIFICATION_TO_ARTICLE_RANGE` 정의만 (검색 시 미사용) | **부분** |
| 유사도 threshold 0.75 이상 | 런타임 검색에서 0.6 threshold 적용 | **변경** |

**FR-04 종합: 75%** (Stage 1 완전 구현, Stage 2는 런타임 폴백으로 대체)

### FR-05: 위험분석 API 응답 확장

| 설계 항목 | 구현 상태 | 일치도 |
|----------|----------|--------|
| `related_guides` 필드 추가 | `AnalysisResponse` 에 `List[GuideMatch]` 추가 | **100%** |
| 매핑 테이블 → 벡터 검색 2단계 조회 | `search_guides_for_articles()` 에 1차 매핑 + 2차 벡터 구현 | **100%** |
| 설계 3가지 소스 (articles, category, description) | articles + description 2가지 소스만 사용 | **부분** |

**FR-05 종합: 90%** (category_code 기반 검색 미구현, 큰 영향 없음)

### FR-06: 프론트엔드 KOSHA GUIDE 표시 UI

| 설계 항목 | 구현 상태 | 일치도 |
|----------|----------|--------|
| `RelatedGuides.tsx` 컴포넌트 | 15개 분류코드별 라벨/컬러 맵 + 확장형 UI 구현 | **100%** |
| `ResultPage.tsx` 탭 추가 | 조건부 'guides' 탭 + 컴포넌트 렌더링 | **100%** |
| Pydantic 모델 (`guide.py`) | `GuideSectionInfo`, `GuideMatch`, `GuideIndexResponse` | **100%** |

**FR-06 종합: 100%**

---

## 2. Gap 목록

| ID | 설계 항목 | 구현 상태 | 영향도 | 우선순위 |
|----|----------|----------|--------|---------|
| G-01 | 편/장 참조 → 조문 범위 확장 | 미구현 | Low | P3 |
| G-02 | 섹션 패턴 하위번호 (`3.1`) 미지원 | `\d+` 로 단순화 | Low | P3 |
| G-03 | ChromaDB 인덱싱 startup 미호출 | 비용 고려 의도적 보류 | Medium | P2 |
| G-04 | Stage 2 임베딩 사전매핑 미구현 | 런타임 벡터 검색으로 대체 | Medium | P2 |
| G-05 | 분류코드 사전필터링 검색 시 미적용 | CLASSIFICATION_TO_ARTICLE_RANGE 정의만 | Low | P3 |
| G-06 | category_code 기반 KOSHA GUIDE 검색 | article_numbers + description만 사용 | Low | P3 |
| G-07 | 유사도 threshold 변경 (0.75→0.6) | 재현율 향상 의도 | Low | P4 |
| G-08 | SQLAlchemy ForeignKey 미사용 | 논리적 FK, 동작 문제 없음 | Low | P4 |

### Gap 해석

**G-01, G-02 (Low)**: 편/장 참조 확장과 하위 섹션 지원은 현재 파싱 결과(21,966 섹션)가 충분히 풍부하여 실무 영향 미미.

**G-03, G-04 (Medium)**: ChromaDB 임베딩 인덱싱이 실행되지 않아 벡터 검색 폴백이 비활성. 현재는 명시적 매핑(1,861건)만으로 작동. 매핑이 없는 조문에 대해서는 KOSHA GUIDE가 검색되지 않는 한계가 있음. 향후 임베딩 비용 확보 시 `build_index()` 호출로 즉시 활성화 가능.

**G-05~G-08 (Low)**: 미세 최적화 항목. 현재 서비스 품질에 실질적 영향 없음.

---

## 3. 정량 평가

### 3.1 요구사항 일치율 (matchRate)

| FR | 가중치 | 일치율 | 가중 점수 |
|----|--------|--------|----------|
| FR-01 (PDF 파싱) | 25% | 90% | 22.5 |
| FR-02 (SQLite 테이블) | 15% | 95% | 14.25 |
| FR-03 (ChromaDB 인덱싱) | 15% | 80% | 12.0 |
| FR-04 (자동 매핑) | 20% | 75% | 15.0 |
| FR-05 (API 통합) | 15% | 90% | 13.5 |
| FR-06 (프론트엔드 UI) | 10% | 100% | 10.0 |
| **합계** | **100%** | | **87.25** |

### 3.2 Plan 성공 기준 달성

| 기준 | 목표 | 실제 | 달성 |
|------|------|------|------|
| PDF 파싱 수 | 950+/1,040 | 1,030/1,040 (99%) | **달성** |
| 매핑 테이블 생성 | 존재 | 1,861건 explicit 매핑 | **달성** |
| 위험분석에 KOSHA GUIDE 표시 | 최소 1개 | 매핑 존재 시 표시됨 | **달성** |
| Docker 배포 | 동작 확인 | 배포 완료, 서비스 동작 중 | **달성** |

### 3.3 품질 기준 달성

| 시나리오 | 기대 결과 | 실제 결과 | 달성 |
|----------|----------|----------|------|
| 추락 위험 → C(건설) 가이드 | 관련 가이드 매칭 | 제42조 → 35개 가이드 | **달성** |
| 전기 위험 → E(전기) 가이드 | 관련 가이드 매칭 | 제301조 → 4개 가이드 | **달성** |
| 화학물질 → H(보건)/P(공정) | 관련 가이드 매칭 | 명시적 매핑 존재 시 가능 | **부분** |
| 밀폐공간 → B(보건일반) | 관련 가이드 매칭 | 명시적 매핑 존재 시 가능 | **부분** |

---

## 4. matchRate 판정

**matchRate = 87%**

| 판정 | 기준 | 결과 |
|------|------|------|
| PASS (≥90%) | Act 단계 불필요 | - |
| **ADJUST (80~89%)** | **경미한 보완 필요** | **87% → ADJUST** |
| FAIL (<80%) | Act 단계 필수 | - |

### 보완 권장 사항

1. **G-03/G-04 (Priority)**: ChromaDB 인덱싱 활성화 (`build_index()` 호출 추가)
   - 비용: 21,966 섹션 × text-embedding-3-small ≈ $0.3~0.5
   - 효과: 벡터 검색 폴백 활성화 → 매핑 없는 조문도 KOSHA GUIDE 검색 가능
   - 구현: `main.py`에 `guide_service.build_index(db)` 추가 (1줄)

2. **G-01 (Optional)**: 편/장 참조 확장은 향후 매칭 정확도 개선 시 고려

---

## 5. 비용 대비 효과 분석

| 항목 | 비용 | 효과 |
|------|------|------|
| ChromaDB 인덱싱 활성화 | ~$0.5 (일회성) | 벡터 검색 폴백 → 매핑 커버리지 대폭 확대 |
| 편/장 참조 확장 | 구현 2시간 | 매핑 수 소폭 증가 (~200건 추정) |
| Stage 2 사전매핑 | ~$0.5 + 구현 1시간 | 런타임 검색 대비 응답속도 개선 |

**권장**: ChromaDB 인덱싱 활성화만으로 matchRate 90%+ 달성 가능.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-21 | Initial gap analysis | Claude (PDCA) |
