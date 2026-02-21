# ohs-article-matching Planning Document

> **Summary**: 위험요소 분석 결과와 산안법 조문의 정확한 매칭 시스템 구축
>
> **Project**: OHS 위험요소 분석 서비스
> **Version**: 2.0.0
> **Author**: Claude (PDCA)
> **Date**: 2026-02-21
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

현재 위험요소 분석 후 관련 법조항 매칭의 정확도가 낮은 문제를 해결한다.
사용자가 사진을 찍어 위험요소를 식별하면, 해당 위험요소에 **실제로 관련 있는** 산업안전보건기준에 관한 규칙 조문을 정확하게 연결하여 보여준다.

### 1.2 Background

**현재 문제점 분석:**

| 문제 | 원인 | 영향 |
|------|------|------|
| 매칭 정확도 낮음 | 임베딩 유사도만으로 검색 (의미적 유사 ≠ 법적 관련) | 칼/가위 위험 → 전혀 관련 없는 굴착작업 조문 매칭 |
| 카테고리 매핑 부재 | GPT category_code와 법조항 편/장/절 구조 간 매핑 없음 | 추락 위험인데 화학물질 조문이 나옴 |
| LLM 재평가 없음 | 벡터 검색 결과를 그대로 반환 | 부정확한 결과를 필터링하지 못함 |
| 검색 쿼리 품질 | hazard name + description 그대로 사용 | 법률 용어와 일상 용어 간 갭 |

**예시 (주방 칼/가위 사진):**
- 식별된 위험요소: "절단 위험", "날카로운 도구 노출"
- 기대 법조항: 제3조(전도의 방지), 제80조(날·전단기 위험 방지) 등
- 현재 결과: 굴착작업, 벌목작업 등 무관한 조문

### 1.3 Related Documents

- 현재 구현: `backend/app/services/article_service.py`
- GPT 프롬프트: `backend/app/integrations/prompts/analysis_prompts.py`
- 법조항 PDF: `ohs_articles/` (254개 PDF, 442개 조문 파싱 완료)

---

## 2. Scope

### 2.1 In Scope

- [x] 산안법 조문 편/장/절 구조 메타데이터 구축
- [x] 위험요소 카테고리 → 법조항 장/절 하드 매핑 테이블
- [x] LLM 기반 검색 쿼리 최적화 (위험요소 → 법률 용어 변환)
- [x] LLM 기반 검색 결과 재랭킹 (Reranker)
- [x] 종합 매칭 파이프라인 (하드매핑 + 벡터검색 + LLM 재평가)

### 2.2 Out of Scope

- 법조항 전문 검색 (키워드 기반)
- 사용자별 매칭 이력 기반 개인화
- 법 개정 자동 업데이트

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 산안법 편/장/절 구조 메타데이터 추출 및 인덱싱 | High | Pending |
| FR-02 | 위험 카테고리별 법조항 장/절 하드매핑 테이블 | High | Pending |
| FR-03 | LLM 기반 검색 쿼리 재작성 (위험요소 → 법률 키워드) | High | Pending |
| FR-04 | 벡터 검색 + 하드매핑 결합 (Hybrid Search) | High | Pending |
| FR-05 | LLM Reranker (검색 결과 재평가 및 관련성 점수 보정) | Medium | Pending |
| FR-06 | GPT 분석 시 관련 조문번호 직접 생성하도록 프롬프트 개선 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 정확도 | 매칭 정확도 80% 이상 (상위 3개 중 1개 이상 정확) | 테스트 시나리오 20건 검증 |
| 응답시간 | 매칭 포함 전체 분석 10초 이내 | API 응답시간 측정 |
| 비용 | LLM 호출 추가 비용 분석당 $0.05 이내 | OpenAI 사용량 모니터링 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 테스트 시나리오 20건 중 16건 이상 정확한 매칭 (80%)
- [ ] 기존 대비 매칭 정확도 2배 이상 개선
- [ ] 응답시간 10초 이내 유지
- [ ] 배포 완료 및 프로덕션 동작 확인

### 4.2 Quality Criteria

- [ ] 칼/가위 → 절단 관련 조문 (제80조 등) 매칭
- [ ] 높은 곳 작업 → 추락 관련 조문 (제42조~제66조) 매칭
- [ ] 전기 노출 → 전기 관련 조문 (제301조~제325조) 매칭
- [ ] 화학물질 → 유해물질 조문 (제225조~제299조) 매칭

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| LLM 추가 호출로 응답시간 증가 | Medium | High | 병렬 처리 + 캐싱 적용 |
| LLM 비용 증가 | Medium | Medium | mini 모델 사용, 프롬프트 최소화 |
| 법조항 구조 파싱 오류 | High | Low | 수동 매핑 테이블로 보완 |
| 모호한 위험요소의 매칭 어려움 | Medium | Medium | 복수 조문 제시 + 관련도 표시 |

---

## 6. Architecture Considerations

### 6.1 Project Level

| Level | Selected |
|-------|:--------:|
| **Dynamic** | **V** |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 매칭 전략 | 벡터만 / 하드매핑만 / **하이브리드** | 하이브리드 | 정확도 최대화 |
| 쿼리 최적화 | 없음 / 키워드 추출 / **LLM 재작성** | LLM 재작성 | 법률 용어 갭 해소 |
| 재랭킹 | 없음 / 규칙기반 / **LLM 재평가** | LLM 재평가 | 맥락 이해 필요 |
| GPT 모델 | gpt-4.1 / **gpt-4.1-mini** | gpt-4.1-mini | 재랭킹은 mini로 충분, 비용 절감 |

### 6.3 매칭 파이프라인 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                     매칭 파이프라인 v2                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [1] GPT 위험요소 분석 (기존)                                │
│       → category_code, description, recommendations        │
│       → **NEW: related_article_numbers** (GPT가 직접 추천)   │
│                                                             │
│  [2] 하드매핑 (카테고리 → 장/절)                             │
│       → FALL → 제6장 제1절 (제42조~제66조)                   │
│       → ELECTRIC → 제3편 제1장 (제301조~제325조)             │
│       → CUT → 제2편 제1장 제9절 (제80조~제86조)              │
│                                                             │
│  [3] 벡터 검색 (기존 ChromaDB, 쿼리 개선)                    │
│       → LLM 쿼리 재작성: "칼이 놓여있음"                     │
│         → "절단 위험 날카로운 도구 보관 안전조치"              │
│                                                             │
│  [4] 결과 통합 + LLM 재랭킹                                 │
│       → [1]+[2]+[3] 후보 취합 (중복 제거)                    │
│       → GPT-4.1-mini로 관련성 재평가                         │
│       → 최종 상위 5개 반환                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. Implementation Plan

### Phase 1: 메타데이터 + 하드매핑 (FR-01, FR-02)

1. 산안법 편/장/절 구조 매핑 테이블 작성
2. 위험 카테고리 → 관련 장/절 하드매핑 딕셔너리
3. ChromaDB 메타데이터에 편/장/절 정보 추가
4. 하드매핑 기반 1차 필터링 로직

### Phase 2: GPT 프롬프트 개선 (FR-06)

1. GPT 분석 시 관련 조문번호를 직접 응답에 포함하도록 프롬프트 수정
2. JSON Schema에 `related_article_numbers` 필드 추가
3. 산안법 조문 목차를 시스템 프롬프트에 포함

### Phase 3: 검색 쿼리 최적화 + 재랭킹 (FR-03, FR-04, FR-05)

1. 위험요소 description → 법률 키워드 변환 (GPT-4.1-mini)
2. 하이브리드 검색: 하드매핑 결과 + 벡터 검색 결과 통합
3. LLM 재랭킹: 후보 조문을 GPT가 재평가

### Phase 4: 통합 테스트 + 배포

1. 20건 테스트 시나리오 작성 및 검증
2. 응답시간 + 비용 최적화
3. Docker 재빌드 + 프로덕션 배포

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`ohs-article-matching.design.md`)
2. [ ] 산안법 편/장/절 구조 분석 및 매핑 테이블 확정
3. [ ] 구현 시작

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-21 | Initial draft | Claude (PDCA) |
