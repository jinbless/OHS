# Plan: "추가 참고 법조항" 기능 제거

## 배경

결과 화면의 "추가 참고 법조항" 탭 기능이 더 이상 필요하지 않음.
"안전지침 & 법조항" (KOSHA GUIDE) 탭에서 이미 가이드별 매핑된 법조항을 보여주고 있어 중복됨.

## 제거 범위 분석

### 영향도 요약

| 구분 | 파일 | 작업 | 비고 |
|------|------|------|------|
| **FE 삭제** | `components/results/RelatedArticles.tsx` | 파일 삭제 | 전용 컴포넌트 |
| **FE 수정** | `pages/ResultPage.tsx` | 탭/import 제거 | L9, L18, L112-123, L149 |
| **FE 수정** | `types/analysis.ts` | `ArticleMatch` 인터페이스, `related_articles` 필드 제거 | L5-11, L50 |
| **BE 삭제** | `api/v1/articles.py` | 파일 삭제 | `/articles/*` 엔드포인트 (FE 미사용) |
| **BE 수정** | `api/v1/router.py` | articles 라우터 제거 | L2, L9 |
| **BE 수정** | `models/analysis.py` | `related_articles` 필드 제거 | L7, L30 |
| **BE 수정** | `models/article.py` | `ArticleSearchResponse` 삭제 | L13-16 (ArticleMatch, ArticleIndexResponse 유지) |
| **BE 수정** | `services/analysis_service.py` | 독립 법조항 검색 블록 제거 | L166-185, L290-295 |
| **BE 수정** | `services/analysis_service.py` | GUIDE Path A (법조항 기반 가이드 검색) 제거 | L228-240 |
| **BE 수정** | `services/analysis_service.py` | 응답 생성에서 `related_articles` 제거 | L318 |
| **BE 수정** | `integrations/openai_client.py` | GPT 스키마에서 `related_articles` 제거 | L68-86, L93 |
| **BE 수정** | `integrations/prompts/analysis_prompts.py` | 관련 프롬프트 문구 제거 | L25-52, L76, L86 |
| **BE 수정** | `services/article_service.py` | 하이브리드 파이프라인 코드 제거 | 대폭 축소 |
| **BE 수정** | `main.py` | PDF 정적 파일 서빙 제거 | L71-73 |

### 유지해야 할 코드 (KOSHA GUIDE가 의존)

`article_service.py`에서 아래 기능은 **KOSHA GUIDE 가이드-법조항 매핑**에 여전히 사용됨:

1. **`_find_article_by_number()`** — `analysis_service.py:276`에서 가이드에 매핑된 법조항 상세 정보 조회
2. **`build_index()`** — `main.py:23`에서 앱 시작 시 ChromaDB 인덱스 빌드
3. **`collection` 프로퍼티** — ChromaDB 컬렉션 접근
4. **PDF 파싱 관련 메서드** — `build_index()`가 의존
5. **`ArticleMatch` 모델** — 가이드의 `mapped_articles` 상세 정보에 사용
6. **`ArticleIndexResponse` 모델** — 향후 관리용 유지 가능

### 제거할 코드 (article_service.py 내)

| 코드 | 라인 | 설명 |
|------|------|------|
| `CATEGORY_TO_ARTICLES` 매핑 | L28-139 | 하드매핑 테이블 |
| `RERANKER_PROMPT` | L162-177 | LLM Reranker 프롬프트 |
| `_search_by_hard_mapping()` | L348-398 | Stage 2 |
| `search_articles()` | L402-433 | Stage 3 벡터 검색 (API에서만 사용) |
| `_build_enhanced_query()` | L435-446 | 향상 쿼리 |
| `_merge_candidates()` | L450-495 | Stage 4 |
| `_rerank_with_llm()` | L499-559 | Stage 5 |
| `hybrid_search_for_hazards()` | L563-647 | 메인 파이프라인 |
| `search_for_hazards()` | L687-689 | 레거시 호환 |

## 구현 순서

### Step 1: 백엔드 — GPT 스키마 정리
- `openai_client.py`: `related_articles` 필드를 스키마에서 제거
- `analysis_prompts.py`: 법조항 추천 관련 프롬프트 문구 제거

### Step 2: 백엔드 — analysis_service 정리
- 독립 법조항 검색 블록 제거 (L166-185)
- Path A 가이드 검색 제거 (L228-240)
- 법조항 중복제거 블록 제거 (L290-295)
- 응답에서 `related_articles=related_articles` → `related_articles=[]` 또는 필드 제거
- 불필요 import 제거

### Step 3: 백엔드 — article_service 축소
- 하이브리드 파이프라인 관련 코드 전부 제거
- `_find_article_by_number()`, `build_index()`, PDF 파싱 코드만 유지

### Step 4: 백엔드 — API/모델/라우터 정리
- `api/v1/articles.py` 삭제
- `api/v1/router.py`에서 articles 라우터 제거
- `models/article.py`에서 `ArticleSearchResponse` 제거
- `models/analysis.py`에서 `related_articles` 필드 제거
- `main.py`에서 PDF 정적 파일 서빙 제거

### Step 5: 프론트엔드 — UI/타입 정리
- `components/results/RelatedArticles.tsx` 삭제
- `pages/ResultPage.tsx`: import, 탭 버튼, 탭 컨텐츠 제거
- `types/analysis.ts`: `ArticleMatch` 인터페이스, `related_articles` 필드 제거

## 주의사항

- DB에 이미 저장된 분석 결과(`result_json`)에는 `related_articles`가 포함되어 있음.
  → `AnalysisResponse`에서 필드를 `= []` 기본값으로 유지하면 역호환 가능
- `article_service._find_article_by_number()`는 가이드 법조항 enrichment에 필수
- ChromaDB 데이터(`backend/data/chromadb`)는 유지 (가이드 법조항 조회에 필요)
