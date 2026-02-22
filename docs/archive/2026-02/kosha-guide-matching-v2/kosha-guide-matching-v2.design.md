# kosha-guide-matching-v2 Design Document

> **Summary**: 3-Path 하이브리드 KOSHA GUIDE 검색 아키텍처 설계
>
> **Project**: OHS (산업안전보건 위험분석)
> **Author**: jinbless
> **Date**: 2026-02-22
> **Status**: Finalized
> **Planning Doc**: [kosha-guide-matching-v2.plan.md](../01-plan/features/kosha-guide-matching-v2.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- GPT 키워드 비결정성에 영향받지 않는 안정적인 KOSHA GUIDE 검색
- 3단계 파이프라인으로 recall과 precision 동시 개선
- 기존 2-Path 아키텍처와의 하위 호환성 유지

### 1.2 Design Principles

- 결정론적 검색(Path C)을 최우선으로 실행하여 핵심 결과 안정성 확보
- 벡터 검색(Path B)으로 시맨틱 매칭 보완
- 법조항 매핑(Path A)은 보조 역할로 격하, 키워드 무관 시 강한 페널티

---

## 2. Architecture

### 2.1 3-Path Hybrid Search Pipeline

```
GPT-4.1 분석 결과
  │
  ├── recommended_guide_keywords (비결정적, 0~5개)
  ├── risks[].description (위험 설명)
  └── related_articles (법조항 번호)
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: 키워드 준비                                         │
│  effective_keywords = GPT keywords || auto-extract(descs)   │
│  GPT keywords 최대 5개 제한                                  │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Path C: 타이틀 키워드 매칭 (결정론적)                          │
│  - 복합 키워드 분리 → 불용어 제거 → 2자 이상 필터             │
│  - SQLite 전체 순회, word boundary 매칭 (startswith)          │
│  - Score: 0.5 + (hits / total_keywords) * 0.3                │
│  - 최대 5건                                                  │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Path B: 벡터 검색 (시맨틱, exclude Path C)                    │
│  - Query: keywords + hazard descriptions                     │
│  - Threshold: 0.45 (with keywords) / 0.35 (desc-only)       │
│  - ChromaDB cosine similarity                                │
│  - 최대 5건 (Path C 제외)                                    │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Path A: 법조항 매핑 (보조, exclude Path C+B)                  │
│  - related_articles → RegGuideMapping → KoshaGuide           │
│  - explicit mapping score: 0.75                              │
│  - 최대 5건 (Path C, B 제외)                                 │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Re-ranking                                                   │
│  - 키워드 hit → +0.15/hit (최대 +0.35)                       │
│  - explicit + no keyword hit → score * 0.4 (강한 페널티)      │
│  - 점수 순 정렬, Top 5                                       │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Enrichment                                                   │
│  - 각 Guide에 mapped_articles 추가 (역매핑)                   │
│  - 독립 법조항에서 Guide 커버 조문 제외                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
User Input → GPT-4.1 분석 → 키워드 준비 → Path C → Path B → Path A → Re-rank → Enrich → Response
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| Path C (search_guides_by_title_keywords) | SQLite KoshaGuide 테이블 | 제목 기반 결정론적 검색 |
| Path B (search_guides_by_description) | ChromaDB kosha_sections | 벡터 시맨틱 검색 |
| Path A (search_guides_for_articles) | RegGuideMapping 테이블 | 법조항→가이드 매핑 |
| _extract_key_nouns | 없음 (규칙 기반) | GPT 키워드 fallback |

---

## 3. Data Model

### 3.1 Path C 키워드 처리

```python
# 복합 키워드 분리
"수공구 안전관리" → ["수공구", "안전관리"]

# 불용어 제거 (20개)
_STOP_WORDS = {"안전", "관한", "위한", "대한", "예방", "관리", "작업",
               "방지", "설치", "기준", "기술", "지침", "규정", "시행",
               "사용", "보건", "산업", "일반", "운용", "프로그램"}

# 2자 미만 제거 (false positive 방지)
"칼" (1자) → 제거 (→ "수산화칼륨" 오매칭 방지)

# Word boundary 매칭
title_word.startswith(keyword) or keyword == title_word
```

### 3.2 Re-ranking 수식

```
for each guide in results:
  keyword_hits = count(kw in title for kw in effective_keywords)

  if keyword_hits > 0:
    boost = min(0.35, keyword_hits * 0.15)
    score = min(0.99, score + boost)
  elif mapping_type == "explicit":
    score = score * 0.4  # 강한 페널티
```

---

## 4. Implementation Guide

### 4.1 Modified Files

| File | Changes |
|------|---------|
| `backend/app/services/guide_service.py` | Path C 신규, Path B 개선, 키워드 추출 추가 |
| `backend/app/services/analysis_service.py` | 3-Path 오케스트레이션, re-ranking, enrichment |

### 4.2 Implementation Order

1. [x] `_extract_key_nouns()` - 자동 키워드 추출 메서드
2. [x] `search_guides_by_title_keywords()` - Path C 신규 메서드
3. [x] `search_guides_by_description()` 개선 - 동적 threshold
4. [x] `analysis_service._create_response()` 수정 - C→B→A 순서, re-ranking

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-22 | Design document created (post-implementation) | jinbless |
