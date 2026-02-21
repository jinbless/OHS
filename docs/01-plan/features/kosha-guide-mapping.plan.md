# kosha-guide-mapping Planning Document

> **Summary**: 산안법 조문 ↔ KOSHA GUIDE 매핑 DB 구축 및 위험분석 결과에 KOSHA GUIDE 연결
>
> **Project**: OHS 위험요소 분석 서비스
> **Version**: 1.0.0
> **Author**: Claude (PDCA)
> **Date**: 2026-02-21
> **Status**: Draft
> **Design Reference**: `산업안전보건규칙_KOSHA_GUIDE_매핑_DB_설계_cashtoss.info`

---

## 1. Overview

### 1.1 Purpose

현재 OHS 서비스는 위험요소 분석 후 관련 **산안법 조문**만 제시하고 있다.
KOSHA GUIDE(안전보건공단 기술지침)는 법 조문을 현장에서 실무적으로 이행하기 위한 가이드이므로,
위험분석 결과에 **관련 KOSHA GUIDE**도 함께 제시하면 실무 활용도가 크게 향상된다.

### 1.2 Background

**현재 자산:**
- 산안법 조문 254개 PDF, 442개 조문 ChromaDB 인덱싱 완료
- KOSHA GUIDE 1,040개 PDF 다운로드 완료 (`guide/` 폴더)
- 하이브리드 매칭 파이프라인 v2 가동 중

**KOSHA GUIDE PDF 분류 (15개 분야):**

| 분류코드 | 분야 | PDF 수 |
|---------|------|--------|
| A | 작업환경측정·분석 | 172 |
| C | 건설안전 | 154 |
| H | 보건 | 141 |
| E | 전기안전 | 117 |
| P | 공정안전 | 101 |
| M | 기계안전 | 94 |
| G | 일반안전 | 65 |
| B | 보건(일반) | 63 |
| D | 건설안전(설계) | 55 |
| X | 기타 | 32 |
| T | 교육·훈련 | 21 |
| W | 작업환경(기타) | 20 |
| O | 산업보건(기타) | 2 |
| F | 화재·폭발 | 2 |
| K | KOSHA(기타) | 1 |
| **합계** | | **1,040** |

### 1.3 Related Documents

- 설계 참고: `산업안전보건규칙_KOSHA_GUIDE_매핑_DB_설계_cashtoss.info`
- 현재 법조항 매칭: `backend/app/services/article_service.py`
- 현재 분석 서비스: `backend/app/services/analysis_service.py`

---

## 2. Scope

### 2.1 In Scope (Phase 1 - MVP)

- [x] KOSHA GUIDE PDF 파싱 (메타데이터 + 섹션 분해)
- [x] SQLite에 KOSHA GUIDE 메타데이터 저장
- [x] KOSHA GUIDE 섹션 임베딩 → ChromaDB 인덱싱
- [x] 산안법 조문 ↔ KOSHA GUIDE 매핑 테이블 (자동 매핑)
- [x] 위험분석 결과에 관련 KOSHA GUIDE 표시
- [x] 프론트엔드 KOSHA GUIDE 섹션 표시 컴포넌트

### 2.2 Out of Scope (향후)

- PostgreSQL + pgvector 마이그레이션 (현재 SQLite + ChromaDB 유지)
- 버전 관리 (Immutable Append 패턴) - 초기에는 단일 버전만
- 자동 변경 감지 스케줄러 (cron)
- 관리자 매핑 관리 UI (드래그앤드롭, 검토 큐)
- 한국어 형태소 분석 (mecab-ko)
- guide_transitions (신구 연계 테이블)

### 2.3 Scope 축소 근거

설계 참고 문서는 엔터프라이즈 수준의 전체 시스템을 기술하고 있으나,
현재 프로젝트는 **SQLite + ChromaDB** 기반 MVP이므로:

1. **DB**: PostgreSQL 대신 SQLite 테이블 + ChromaDB 벡터 인덱스 유지
2. **버전 관리**: 현 시점 데이터만 관리 (개정 이력 추적 불필요)
3. **매핑**: AI 자동 매핑으로 초기 구축, 수동 검토 UI는 향후
4. **검색**: 기존 하이브리드 파이프라인에 KOSHA GUIDE 레이어 추가

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | KOSHA GUIDE PDF 파싱 (제목, 분류코드, 섹션 분해) | High | Pending |
| FR-02 | SQLite에 kosha_guides + guide_sections 테이블 생성 | High | Pending |
| FR-03 | KOSHA GUIDE 섹션 임베딩 → ChromaDB 인덱싱 | High | Pending |
| FR-04 | 산안법 조문 ↔ KOSHA GUIDE 자동 매핑 (임베딩 유사도 기반) | High | Pending |
| FR-05 | 위험분석 API 응답에 관련 KOSHA GUIDE 포함 | Medium | Pending |
| FR-06 | 프론트엔드 KOSHA GUIDE 표시 UI | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| 파싱 성공률 | 1,040개 PDF 중 95% 이상 파싱 성공 | 파싱 로그 확인 |
| 인덱싱 | 전체 인덱싱 30분 이내 완료 | 실행 시간 측정 |
| 응답시간 | KOSHA GUIDE 포함 전체 분석 15초 이내 | API 응답시간 |
| 디스크 | ChromaDB 인덱스 증가분 2GB 이내 | 디스크 사용량 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] KOSHA GUIDE 1,040개 중 950개 이상 파싱/인덱싱 완료
- [ ] 산안법 조문 ↔ KOSHA GUIDE 매핑 테이블 생성
- [ ] 위험분석 결과에 관련 KOSHA GUIDE 최소 1개 이상 표시
- [ ] Docker 배포 완료 및 프로덕션 동작 확인

### 4.2 Quality Criteria

- [ ] 추락 위험 → KOSHA GUIDE C(건설안전) 관련 지침 매칭
- [ ] 전기 위험 → KOSHA GUIDE E(전기안전) 관련 지침 매칭
- [ ] 화학물질 → KOSHA GUIDE H(보건) 또는 P(공정안전) 관련 지침 매칭
- [ ] 밀폐공간 → KOSHA GUIDE B(보건일반) 관련 지침 매칭

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| PDF 파싱 실패 (스캔 이미지, 복잡한 테이블) | High | Medium | pdfplumber + 폴백(PyMuPDF), 실패 PDF 로그 |
| ChromaDB 인덱스 크기 폭증 (기존 442 + 새 수만 개) | Medium | Medium | 섹션 단위 청킹, 별도 컬렉션 분리 |
| 임베딩 API 비용 | Medium | Low | batch 처리, 캐시 활용 |
| 자동 매핑 정확도 낮음 | Medium | Medium | 분류코드 기반 사전 필터링 + 임베딩 유사도 |
| 응답시간 증가 | Medium | Medium | KOSHA GUIDE 검색을 병렬 처리 |

---

## 6. Architecture Considerations

### 6.1 Project Level

| Level | Selected |
|-------|:--------:|
| **Dynamic** | **V** |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| DB | PostgreSQL+pgvector / **SQLite+ChromaDB** | SQLite+ChromaDB | 기존 스택 유지, MVP 우선 |
| PDF 파서 | pdfplumber / **PyMuPDF(fitz)** / Tika | PyMuPDF | 이미 사용 중, 속도 빠름 |
| ChromaDB 구조 | 단일 컬렉션 / **분리 컬렉션** | 분리 | ohs_articles + kosha_guides 분리 |
| 매핑 방식 | 수동 / **자동(임베딩)** / 하이브리드 | 자동 | 1,040건 수동 매핑 비현실적 |
| 임베딩 모델 | text-embedding-3-small | 동일 | 기존과 일관성 유지 |

### 6.3 데이터 흐름

```
┌─────────────────────────────────────────────────────────────┐
│              KOSHA GUIDE 매핑 파이프라인                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [1] PDF 파싱 (1,040개)                                     │
│       → 메타데이터: guide_code, title, classification       │
│       → 섹션 분해: 목적/범위/정의/기준/절차/부록             │
│                                                             │
│  [2] 데이터 저장                                            │
│       → SQLite: kosha_guides, guide_sections 테이블         │
│       → ChromaDB: kosha_guides 컬렉션 (섹션별 임베딩)       │
│                                                             │
│  [3] 자동 매핑                                              │
│       → 산안법 조문 임베딩 ↔ KOSHA GUIDE 섹션 임베딩        │
│       → 분류코드 기반 사전 필터링                            │
│       → reg_guide_mapping 테이블 생성                       │
│                                                             │
│  [4] 서비스 통합                                            │
│       → 위험분석 결과 → 관련 조문 → 매핑된 KOSHA GUIDE      │
│       → API 응답에 포함                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. Implementation Plan

### Phase 1: PDF 파싱 + DB 스키마 (FR-01, FR-02)

1. SQLite에 `kosha_guides`, `guide_sections` 테이블 생성
2. KOSHA GUIDE PDF 파싱 스크립트 작성
   - 파일명에서 guide_code, classification 추출
   - 본문에서 섹션 단위 분해 (1.목적, 2.적용범위, ...)
3. 1,040개 PDF 배치 파싱 실행

### Phase 2: 임베딩 + 인덱싱 (FR-03)

1. ChromaDB `kosha_guides` 컬렉션 생성
2. guide_sections 텍스트 임베딩 (text-embedding-3-small)
3. 배치 인덱싱 (50개씩)

### Phase 3: 자동 매핑 (FR-04)

1. 산안법 조문별 가장 관련 높은 KOSHA GUIDE 검색
2. 분류코드 사전 필터링 (예: FALL → C/G 분류 우선)
3. `reg_guide_mapping` 테이블에 매핑 저장

### Phase 4: 서비스 통합 + UI (FR-05, FR-06)

1. `analysis_service.py`에서 매핑된 KOSHA GUIDE 조회
2. API 응답에 `related_guides` 필드 추가
3. 프론트엔드 KOSHA GUIDE 표시 컴포넌트 추가
4. Docker 재빌드 + 프로덕션 배포

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`kosha-guide-mapping.design.md`)
2. [ ] PDF 파싱 프로토타입 (샘플 5개로 검증)
3. [ ] 구현 시작

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-21 | Initial draft | Claude (PDCA) |
