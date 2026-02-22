# kosha-guide-matching-v2 Planning Document

> **Summary**: KOSHA GUIDE 매칭 안정성 개선 - 2-Path에서 3-Path 하이브리드 검색으로 전환
>
> **Project**: OHS (산업안전보건 위험분석)
> **Author**: jinbless
> **Date**: 2026-02-22
> **Status**: Finalized

---

## 1. Overview

### 1.1 Purpose

kosha-guide-mapping v1 (2-Path: Path A 법조항매핑 + Path B 벡터검색) 구현 후, KOSHA GUIDE 매칭 품질이 오히려 저하된 문제를 해결한다. GPT 키워드 비결정성, 임베딩 쿼리 희석, 부적절한 리랭킹 로직 등 근본 원인을 분석하고 3-Path 하이브리드 검색으로 안정성을 확보한다.

### 1.2 Background

- kosha-guide-mapping v1 배포 후, "주방에서 칼 사용" 시나리오에서 G-44-2011(수공구 안전지침)이 결과에 포함되지 않는 등 매칭 품질 저하 확인
- GPT-4.1의 `recommended_guide_keywords`가 호출마다 다른 키워드를 반환 (비결정성)
- Path A의 explicit 매핑(0.75점)이 Path B 직접검색(0.58점)보다 항상 우선되어 무관한 결과 상위 노출
- 키워드가 빈 배열이면 Path B가 0건 반환되는 버그

### 1.3 Related Documents

- 이전 PDCA: `docs/04-report/features/kosha-guide-mapping.report.md`
- 법조항 매칭: `docs/04-report/features/ohs-article-matching.report.md`

---

## 2. Scope

### 2.1 In Scope

- [x] GPT 키워드 비결정성 문제 해결 (결정론적 Path 추가)
- [x] Path C: 타이틀 키워드 매칭 (결정론적 검색) 신규 구현
- [x] Path B: 벡터검색 개선 (자동 키워드 추출 fallback, 동적 threshold)
- [x] Path A: explicit 매핑 페널티 강화
- [x] Re-ranking 로직 개선 (키워드 부스트 + 무관 매핑 페널티)
- [x] 검색 순서 변경: Path C → Path B → Path A
- [x] 디버그 로깅 강화 (WARNING 레벨)

### 2.2 Out of Scope

- GPT 프롬프트 자체 변경 (키워드 생성 품질은 현행 유지)
- ChromaDB 인덱스 재구축
- 새로운 임베딩 모델 적용

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | Path C: 키워드로 KOSHA GUIDE 타이틀 직접 매칭 | High | Done |
| FR-02 | 자동 키워드 추출 (GPT 키워드 없을 때 fallback) | High | Done |
| FR-03 | 복합 키워드 분리 ("수공구 안전관리" → "수공구", "안전관리") | Medium | Done |
| FR-04 | 단어 경계 매칭 (substring false positive 방지) | High | Done |
| FR-05 | 확장된 불용어 필터링 | Medium | Done |
| FR-06 | GPT 키워드 최대 5개 제한 (희석 방지) | Medium | Done |
| FR-07 | Path B description-only threshold 하향 (0.45→0.35) | Medium | Done |
| FR-08 | explicit 매핑 페널티 강화 (0.5x→0.4x) | Medium | Done |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 안정성 | 동일 입력에 대해 핵심 결과 일관 포함 | G-44-2011 반복 테스트 |
| 성능 | 검색 시간 3초 이내 | Docker 컨테이너 로그 |
| 정확도 | Top 5 결과 중 관련 가이드 3건 이상 | 수동 검증 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [x] 3-Path 하이브리드 검색 구현 완료
- [x] G-44-2011이 "주방 칼 사용" 시나리오에서 안정적으로 출력
- [x] Docker 빌드 성공 및 서비스 정상 동작
- [x] WARNING 로그로 각 Path 결과 추적 가능

### 4.2 Quality Criteria

- [x] 기존 법조항 매칭 기능 영향 없음
- [x] 프론트엔드 정상 동작 (KOSHA GUIDE 카드 + 인라인 법조항)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Path C가 너무 많은 결과 반환 | Medium | Medium | 불용어 확장, word boundary 매칭 |
| GPT 키워드가 완전히 빈 배열 | High | Low | _extract_key_nouns() 자동 추출 fallback |
| 키워드 단어 경계 오매칭 ("칼" → "수산화칼륨") | High | Medium | startswith() 기반 word boundary 매칭 |
| Path 간 중복 결과 | Low | High | exclude_codes로 이미 발견된 결과 제외 |

---

## 6. Architecture Considerations

### 6.1 Project Level

Dynamic (FastAPI + React + Docker Compose)

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 결정론적 검색 | DB LIKE / 제목 순회 / Elasticsearch | SQLite 제목 순회 | 1,030건 규모에서 충분한 성능 |
| 키워드 추출 | GPT 호출 / 규칙기반 추출 | 규칙기반 (명사 추출) | 추가 API 비용 없음, 즉시 실행 |
| 검색 순서 | A→B→C / C→B→A | C→B→A | 결정론적→벡터→보조 순으로 안정성 우선 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-22 | Plan document created (post-implementation) | jinbless |
