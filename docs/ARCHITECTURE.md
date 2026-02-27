# OHS 시스템 아키텍처 문서

> 최종 업데이트: 2026-02-27 | 버전: 2.1.0

## 1. 시스템 개요

산업안전보건(OHS) 위험요소 분석 웹 서비스. 작업현장 이미지/텍스트를 AI가 분석하여:
1. 위험요소 식별 (GPT-4.1)
2. 관련 법조항 매칭 (ChromaDB + BM25 하이브리드)
3. KOSHA GUIDE 연결 (3-Path 검색)
4. 규범명제 기반 온톨로지 (LLM 추출)
5. 안전 숏폼영상 추천 (3-Layer 매칭)

## 2. 인프라 구성

```
[사용자 브라우저]
       |
   [Nginx 리버스 프록시]  -- https://${DOMAIN}
       |         |
       v         v
  :3000/80    :8000
  [Frontend]  [Backend]
  React+Vite  FastAPI
              |    |       |
              v    v       v
           SQLite ChromaDB OpenAI API
           (ohs.db) (벡터DB) (gpt-4.1 / gpt-4.1-mini /
                              text-embedding-3-small)
```

### Docker Compose 구성

| 서비스 | 이미지 | 포트 | 비고 |
|--------|--------|------|------|
| backend | ohs-backend (python:3.11-slim) | 127.0.0.1:8000 | FastAPI + Uvicorn |
| frontend | ohs-frontend (Nginx) | 127.0.0.1:3000 | React 빌드 정적 서빙 |

### 볼륨 마운트

| 호스트/볼륨 | 컨테이너 경로 | 모드 | 용도 |
|-------------|---------------|------|------|
| `backend_data` (named) | `/app/data` | rw | SQLite DB + 테스트 결과 |
| `./ohs_articles` | 마운트 경로 | ro | 법조항 PDF 254개 |
| `./guide` | 마운트 경로 | ro | KOSHA GUIDE PDF 1050개 |
| `chromadb_data` (named) | 마운트 경로 | rw | ChromaDB 벡터 DB |

**중요**: 백엔드 코드는 이미지에 COPY (volume mount 아님). 코드 수정 시 반드시 `docker compose up --build` 필요.

### 환경변수

| 변수 | 용도 | 설정 위치 |
|------|------|-----------|
| `OPENAI_API_KEY` | OpenAI API 키 | `.env` |
| `DOMAIN` | 서비스 도메인 | `.env` |
| `ALLOWED_ORIGINS` | CORS 허용 출처 | `docker-compose.yml` |
| `DATABASE_URL` | DB 경로 | `docker-compose.yml` (sqlite:///./data/ohs.db) |

---

## 3. 백엔드 아키텍처

### 3.1 기술 스택

| 패키지 | 버전 | 용도 |
|--------|------|------|
| FastAPI | >= 0.115.0 | 웹 프레임워크 |
| SQLAlchemy | >= 2.0.35 | ORM |
| ChromaDB | >= 1.0.0 | 벡터 DB |
| OpenAI | >= 1.50.0 | GPT/임베딩 API |
| PyMuPDF | >= 1.24.0 | PDF 파싱 |
| kiwipiepy | >= 0.18.0 | 한국어 형태소 분석 |
| rank-bm25 | >= 0.2.2 | BM25 검색 |

### 3.2 OpenAI 모델 사용 현황

| 서비스 | 모델 | 용도 | temp | max_tokens | 포맷 |
|--------|------|------|:----:|:----------:|------|
| openai_client | gpt-4.1 | 이미지/텍스트 위험분석 | 기본값 | 4096 | json_schema |
| norm_extractor | gpt-4.1 | 규범명제 추출 | 0.1 | 4096 | json_schema |
| search_enhancer (쿼리재작성) | gpt-4.1-mini | 일상어→법률용어 | 0.1 | 100 | 텍스트 |
| search_enhancer (재랭킹) | gpt-4.1-mini | 관련성 재평가 | 0.1 | 500 | json_schema |
| article_service | text-embedding-3-small | 법조항 임베딩 | - | - | 벡터 |
| guide_service | text-embedding-3-small | 가이드 임베딩 | - | - | 벡터 |

### 3.3 ChromaDB 컬렉션

| 컬렉션명 | 거리함수 | 용도 | 데이터 규모 |
|----------|:--------:|------|:-----------:|
| `ohs_articles` | cosine | 산안법 조문 | 254 PDF |
| `kosha_guides` | cosine | KOSHA GUIDE 섹션 | 1050 PDF |

### 3.4 DB 스키마 (SQLite)

**7개 테이블:**

1. **analysis_records** - 분석 이력
   - `id`(PK, UUID4), `analysis_type`, `overall_risk_level`, `summary`, `input_preview`, `result_json`, `created_at`

2. **kosha_guides** - KOSHA 가이드 메타
   - `id`(PK), `guide_code`(UNIQUE), `classification`, `guide_number`, `guide_year`, `title`, `related_regulations`, `pdf_filename`, `total_pages`, `total_chars`

3. **guide_sections** - 가이드 섹션 분해
   - `id`(PK), `guide_id`, `section_order`, `section_title`, `section_type`(purpose/scope/definition/standard/procedure/appendix), `body_text`

4. **reg_guide_mapping** - 법조항↔가이드 매핑
   - `id`(PK), `article_number`, `guide_id`, `mapping_type`(explicit/auto), `relevance_score`
   - UNIQUE(article_number, guide_id)

5. **norm_statements** - 규범명제 분해
   - `id`(PK), `article_number`(indexed), `paragraph`, `statement_order`, `subject_role`, `action`, `object`, `condition_text`, `legal_effect`(indexed, OBLIGATION/PROHIBITION/PERMISSION/EXCEPTION), `full_text`, `norm_category`(indexed), `hazard_major`(indexed, physical/chemical/electrical/ergonomic/environmental/biological), `hazard_codes`(JSON array)

6. **semantic_mappings** - 온톨로지 의미적 매핑
   - `id`(PK), `source_type`, `source_id`, `target_type`, `target_id`, `relation_type`(IMPLEMENTS/SUPPLEMENTS/SPECIFIES_CRITERIA/SPECIFIES_METHOD/CROSS_REFERENCES), `confidence`, `discovery_method`, `discovery_tier`(A~F)

7. **safety_videos** - KOSHA 안전 숏폼영상
   - `id`(PK), `title`, `url`(UNIQUE), `category`, `tags`, `hazard_categories`, `is_korean`

---

## 4. 서비스 레이어 상세

### 4.1 서비스 간 호출 관계

```
analysis_service (오케스트레이터)
  ├── openai_client.analyze_image/text()     [gpt-4.1]
  ├── search_enhancer
  │     ├── extract_keywords_for_search()     [kiwipiepy 형태소]
  │     ├── rewrite_queries_batch()           [gpt-4.1-mini]
  │     └── rerank_results()                  [gpt-4.1-mini]
  ├── article_service
  │     ├── search_articles_with_filter()     [ChromaDB + BM25]
  │     └── _find_article_by_number()         [ChromaDB]
  ├── guide_service
  │     ├── predict_classifications()          [키워드 기반]
  │     ├── search_guides_by_title_keywords() [Path C: 제목매칭]
  │     ├── search_guides_by_description()    [Path B: 벡터검색]
  │     └── get_mapped_articles_for_guides()  [역매핑]
  ├── ontology_service
  │     ├── get_article_norms()               [규범명제 조회]
  │     ├── find_related_articles_for_hazards() [벡터+카테고리]
  │     └── get_semantic_boost_for_guides()   [시맨틱 부스트]
  └── video_service
        └── find_related_videos()             [3-Layer 매칭]
```

### 4.2 analysis_service.py - 6단계 파이프라인

**[Phase 0] 키워드 매핑 직접 매칭**
- `keyword_mappings.json` 로드 (lazy, 1회 캐시)
- `match_articles_by_keywords()`: keyword +1점, phrase +2점, 임계값 >= 1
- `match_guides_by_keywords()`: keyword +1점, phrase +3점, 임계값 >= 1

**[Phase 1-A] GPT 힌트 수집**
- GPT `related_article_hints` 추출
- 키워드 매핑 결과를 GPT 힌트에 병합

**[Phase 2-C] LLM 쿼리 재작성**
- `search_enhancer.rewrite_queries_batch()` (gpt-4.1-mini, temp=0.1)
- 일상어 → 법률 용어 변환

**[Phase 2-E] 키워드 추출**
- GPT `recommended_guide_keywords` (최대 5개)
- `search_enhancer.extract_keywords_for_search()` (형태소 분석)
- 병합 후 최대 10개

**KOSHA GUIDE 3-Path 검색**
1. Path C: 제목 키워드 매칭 (결정론적)
2. Path B: 벡터 검색 (확률적)
3. Re-rank: 시맨틱 부스트 + 분류 라우팅 + 키워드 매핑 주입

**Re-rank 점수 조정:**
- keyword_hits > 0: +min(0.35, hits * 0.15)
- explicit 매핑인데 keyword_hits == 0: score *= 0.4 (패널티)
- semantic_boost > 0: +boost
- 분류 라우팅 매칭: +0.08(1st), +0.06(2nd), +0.04(3rd)
- keyword_match raw >= 4: floor 0.995
- keyword_match raw >= 2: floor 0.98
- keyword_match raw >= 1: floor 0.96

**법조항 매칭**
1. GPT 추천 법조항 우선
2. 온톨로지 매칭 보충
3. 필터링 검색 (ChromaDB + BM25 하이브리드, min_score=0.42)
4. LLM 재랭킹 (후보 > 3개일 때, 최대 15개)
   - 최종점수 = original * 0.4 + llm_score * 0.6

**영상 매칭 (3-Layer)**
- Layer 1 카테고리 (weight 0.4)
- Layer 2 키워드 (weight 0.4)
- Layer 3 온톨로지 (weight 0.3)
- 보너스: 한국어 +0.05, 2레이어 +0.1, 3레이어 +0.15

### 4.3 article_service.py - 법조항 관리

- 조문 로드: `load_articles()` (캐시 우선 → PDF 폴백). 구 이름 `parse_all_pdfs()`는 alias로 유지.
- 하이브리드 검색: 벡터 50% + BM25 50%
- 카테고리 장(chapter) 매칭: +0.15 부스트
- BM25 전용 결과: bm25_score >= 0.3일 때 * 0.5로 편입

**카테고리→조문 범위 매핑**: `article_chapters.json` + `taxonomy.py` 기반 (하드코딩 제거됨)

### 4.4 guide_service.py - KOSHA GUIDE 관리

**3-Path 검색:**
- Path C (제목 키워드): 불용어 16개 필터, 단어경계 매칭, score = 0.5 + (hits/total)*0.3
- Path B (벡터): 동적 threshold (키워드 >= 3: 0.38, < 3: 0.42, 없음: 0.30)
- BM25: guide_code + title + classification 토크나이징

**분류 예측**: `CLASSIFICATION_KEYWORDS` 12개 분류코드별 ~180개 키워드
**분류→조문 범위**: `taxonomy.get_article_range_for_classification()` 사용 (하드코딩 `CLASSIFICATION_TO_ARTICLE_RANGE` 제거됨)

### 4.5 ontology_service.py - 온톨로지 매핑

**Phase 1**: 규범명제 분해 (gpt-4.1) + 관계유형 분류
**Phase 2**: 미매핑 자동 발견 (Tier B 키워드 85개, Tier F 벡터)
**상호참조**: 법조항 간 `제N조에 따른/의 규정/을 준용` 패턴 탐지

**시맨틱 부스트 맵:**
```
SPECIFIES_CRITERIA: +0.25
IMPLEMENTS:         +0.20
SPECIFIES_METHOD:   +0.15
CROSS_REFERENCES:   +0.10
SUPPLEMENTS:        +0.05
```

### 4.6 norm_extractor.py - 규범명제 추출

- 동시성: `asyncio.Semaphore(5)`
- 재시도: 3회, 지수 백오프 (2^attempt초)
- 출력: subject_role, action, object, condition_text, legal_effect, norm_category, hazard_major, hazard_codes

### 4.7 search_enhancer.py - 검색 품질 강화

- 형태소 분석: kiwipiepy (NNG, NNP, NNB), 2글자 이상
- 쿼리 재작성: gpt-4.1-mini, temp=0.1, max_tokens=100
- LLM 재랭킹: gpt-4.1-mini, temp=0.1, max_tokens=500, 10점 척도

### 4.8 video_service.py - 숏폼 영상 매칭

- 데이터: `app/data/safety_videos.json`에서 시드
- 3-Layer: 카테고리(0.4) + 키워드(0.4) + 온톨로지(0.3)
- 온톨로지 레이어: `taxonomy.get_chapter_for_article()` 기반 키워드 유추 (하드코딩 범위 제거됨)

### 4.9 온톨로지 데이터 파일

| 파일 | 용도 |
|------|------|
| `app/data/hazard_taxonomy.json` | 통합 분류 체계 (6대분류 + 24세부코드 + 레거시 매핑) |
| `app/data/article_chapters.json` | 산안법 편/장 구조 (27장, 조문 범위 + KOSHA 분류 매핑) |
| `app/utils/taxonomy.py` | 분류/계층 조회 유틸리티 |
| `app/integrations/prompts/prompt_builder.py` | 온톨로지 JSON 기반 동적 SYSTEM_PROMPT 생성 |

---

## 5. API 엔드포인트

### 분석 API

| 메소드 | 경로 | 설명 |
|--------|------|------|
| POST | /api/v1/analysis/image | 이미지 위험분석 (multipart) |
| POST | /api/v1/analysis/text | 텍스트 위험분석 (JSON) |
| GET | /api/v1/analysis/history | 분석 기록 목록 (skip, limit) |
| GET | /api/v1/analysis/{id} | 분석 상세 조회 |
| DELETE | /api/v1/analysis/{id} | 분석 삭제 |

### 온톨로지 API

| 메소드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/v1/ontology/stats | 매핑 통계 |
| GET | /api/v1/ontology/articles/{num}/norms | 규범명제 조회 |
| GET | /api/v1/ontology/articles/{num}/graph | 법조항 그래프 |
| GET | /api/v1/ontology/graph | 전체 그래프 |
| GET | /api/v1/ontology/gap-analysis | 미매핑 분석 |
| GET | /api/v1/ontology/mappings | 매핑 목록 |
| POST | /api/v1/ontology/extract-norms | 규범명제 추출 실행 |
| POST | /api/v1/ontology/classify-mappings | 매핑 분류 실행 |
| POST | /api/v1/ontology/discover-mappings | 미매핑 발견 실행 |

### 기타

| 메소드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/v1/health | 헬스체크 |
| GET | /api/v1/resources | 교육 자료 목록 |

---

## 6. 프론트엔드 아키텍처

### 6.1 기술 스택

React 18 + TypeScript + Vite 5 + Tailwind CSS 3.4 + Zustand

### 6.2 라우팅 (`basename="/ohs"`)

| 경로 | 페이지 | 설명 |
|------|--------|------|
| / | HomePage | 메인 (분석 유형 선택) |
| /analysis?type=image\|text | AnalysisPage | 분석 입력 |
| /result/:id | ResultPage | 분석 결과 (4탭) |
| /history | HistoryPage | 분석 기록 목록 |
| /ontology | OntologyPage | 온톨로지 시각화 |

### 6.3 컴포넌트 계층

```
App → Layout (헤더+네비+푸터)
  ├── HomePage
  ├── AnalysisPage → ImageUploader / TextInput
  ├── ResultPage → ResultSummary / HazardList / RelatedGuides / ChecklistView / ResourceLinks
  ├── HistoryPage
  └── OntologyPage → StatsCard / OntologyGraph(vis-network) / NormDetail
```

### 6.4 상태관리 (Zustand)

단일 스토어 `analysisStore`:
- `currentAnalysis`, `history`, `totalHistory`, `isLoading`, `error`
- AnalysisPage/ResultPage에서 사용, HistoryPage/OntologyPage는 로컬 state

### 6.5 API 클라이언트

- Base URL: `VITE_API_BASE_URL` || `http://localhost:8000/api/v1`
- Timeout: 120초

---

## 7. 앱 시작 초기화 순서

1. `create_tables()` - SQLAlchemy 테이블 생성
2. `article_service.build_index()` - 법조항 ChromaDB 인덱스
3. `guide_service.parse_and_store_all()` - KOSHA PDF 파싱 → DB
4. `guide_service.build_mappings()` - 법조항↔가이드 매핑
5. `guide_service.build_index()` - KOSHA ChromaDB 인덱스
6. `video_service.seed_videos()` - 숏폼 영상 시드

모든 단계는 실패해도 서비스 계속 실행 (try-except).

---

## 8. 에러 핸들링 패턴

| 서비스 | 패턴 |
|--------|------|
| analysis_service | 외부 서비스 실패 → warning 로그 후 계속 (GPT 실패만 상위 전파) |
| norm_extractor | 3회 재시도 + 지수 백오프, Semaphore(5) |
| search_enhancer | 실패 → 폴백 (형태소 키워드 or 원본 순서) |
| article/guide_service | 개별 PDF/배치 실패 → 스킵 후 계속 |
| video_service | URL unique 충돌 → 개별 insert 재시도 |
