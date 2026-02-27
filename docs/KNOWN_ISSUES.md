# OHS 알려진 이슈 및 주의사항

> 최종 업데이트: 2026-02-27

---

## 1. 미매칭 건 (해결되지 않은 실패)

### 법령 조문 1건 (49/50)

| 조문 | 유형 | 실제 매칭 결과 | 원인 |
|------|------|:-------------:|------|
| **제383조** (작업의 제한) | administrative | 제42조, 제51조, 제56조 | 관리적 조항으로 시나리오와 직접 연결이 약함 |

*이전 미매칭이었던 제356조(compound_risk)는 온톨로지 리스트럭처(2026-02-27) 후 해결됨.*

### KOSHA GUIDE 0건 (49/49) — 전체 매칭 달성

온톨로지 리스트럭처(2026-02-27) 이후 KOSHA GUIDE 100% 매칭 달성.

<details>
<summary>이전 미매칭 6건 (키워드 매핑 도입 전)</summary>

| 가이드 | 분류 | 원인 | 해결 방법 |
|--------|:----:|------|-----------|
| X-70-2016 (운전원 행동분석) | X | X분류 특수 가이드 | 키워드 매핑 + 온톨로지 분류 체계로 해결 |
| P-10-2012 | P | 공정안전 가이드 혼동 | 키워드 매핑으로 해결 |
| E-94-2011 (산업용 기계설비 전기장치) | E | 기계(M)와 전기(E) 분류 경계선 | 키워드 매핑으로 해결 |
| A분류 1건 | A | A분류 자체가 소수 | 키워드 매핑으로 해결 |
| C분류 1건 | C | 건설 분류 내 유사 가이드 혼동 | 키워드 매핑으로 해결 |
| H분류 1건 | H | 세분화된 보건 가이드 구별 실패 | 키워드 매핑으로 해결 |

</details>

---

## 2. 건드리면 안 되는 것

### 2.1 keyword_mappings.json

**절대 주의 파일**: `backend/data/keyword_mappings.json`

- 65개 법조항 + 76개 KOSHA 가이드의 수동 키워드/구문 매핑
- **이 파일이 정확도 76% → 98%의 핵심 원인**
- 수정/삭제 시 정확도가 즉시 하락
- 수정 후 반드시 코너 테스트 재실행:
  ```bash
  docker compose exec backend python scripts/run_corner_test.py all
  ```

### 2.2 GPT 시스템 프롬프트

**파일**: `backend/app/integrations/prompts/prompt_builder.py` (동적 생성)
**진입점**: `backend/app/integrations/prompts/analysis_prompts.py` → `build_system_prompt()` 호출

- `hazard_taxonomy.json` + `article_chapters.json` 기반 동적 프롬프트 생성
- 29개 위험유형별 조문 매칭 가이드 테이블 포함 (prompt_builder.py 내 ARTICLE_DETAILS)
- 프롬프트 수정 시 GPT 분석 결과 전체가 변동
- **수정 후 반드시 코너 테스트 재실행 필요**

### 2.3 Re-rank 점수 조정 로직

**파일**: `backend/app/services/analysis_service.py` `_create_response()` 메서드

현재 튜닝된 가중치/임계값:
```
keyword_hits > 0: boost = min(0.35, hits * 0.15)
explicit + no keywords: score *= 0.4
keyword_match raw >= 4: floor = 0.995
keyword_match raw >= 2: floor = 0.98
keyword_match raw >= 1: floor = 0.96
```

이 값들은 100건 테스트로 검증된 최적값. 임의 변경 시 정확도 하락 위험.

### 2.4 코너 테스트 케이스

**파일들**:
- `backend/data/corner_test_articles_100.json`
- `backend/data/corner_test_kosha_100.json`

- 테스트케이스 자체를 수정하면 이전 결과와 비교 불가
- 추가는 OK, 기존 건 수정/삭제는 하지 말 것

---

## 3. 알려진 제한사항

### 3.1 GPT 비결정성

- 동일 시나리오도 실행마다 결과가 다를 수 있음
- 90% ↔ 98% 범위로 변동 가능
- 원인: GPT-4.1의 temperature가 기본값(~1.0)으로 설정됨 (openai_client.py)
- search_enhancer/norm_extractor는 temp=0.1로 안정화됨
- **주의**: 단일 실행 결과로 판단하지 말고, 2~3회 실행 평균으로 판단할 것

### 3.2 Docker 빌드 필수

- 백엔드 코드가 이미지에 COPY되는 구조
- 소스 코드 수정 후 **반드시** `docker compose up --build -d` 필요
- volume mount가 아님 → 코드만 바꿔서는 반영 안 됨
- data/ 디렉토리(DB, 테스트결과)는 named volume으로 빌드해도 유지됨

### 3.3 ChromaDB 인덱스 갱신

- 법조항/가이드 PDF가 변경되면 ChromaDB 재인덱싱 필요
- 방법: 컨테이너 재시작 (lifespan에서 자동 체크) 또는 `force=True`로 재빌드
- ChromaDB 데이터는 named volume (`chromadb_data`)에 저장

### 3.4 SQLite 동시성

- SQLite는 쓰기 동시성이 제한적
- 현재 단일 Uvicorn 워커로 운영 (docker-compose.yml)
- 다중 워커 확장 시 PostgreSQL 전환 필요

### 3.5 키워드 매핑 미대상 조문

- 254개 조문 중 65개만 키워드 매핑 (약 26%)
- 189개 조문은 벡터 검색 + BM25에만 의존
- 매핑 확대 시 정확도 추가 향상 가능하나, 유지보수 부담 증가

### 3.6 KOSHA GUIDE 키워드 매핑 미대상

- 1050개 가이드 중 76개만 키워드 매핑 (약 7%)
- 나머지는 벡터 + BM25 + 명시적 매핑(related_regulations)에 의존

---

## 4. 프론트엔드 알려진 이슈

### 4.1 타입 캐스팅

- `ResultPage.tsx`에서 `(currentAnalysis as any).related_guides` 사용
- `AnalysisResponse` 타입에 이미 정의되어 있으므로 `as any` 불필요
- 기능상 문제 없으나 TypeScript 타입 안전성 약화

### 4.2 상태 관리 불일치

- `HistoryPage`와 `OntologyPage`는 Zustand 스토어 미사용 (로컬 useState)
- analysisStore에 `history`, `totalHistory` 필드가 있지만 미사용
- 기능상 문제 없으나 코드 일관성 부재

### 4.3 온톨로지 타입 위치

- 온톨로지 관련 타입(`MappingStats`, `NormStatement` 등)이 `api/ontologyApi.ts`에 인라인 정의
- `types/` 폴더에 분리하는 것이 구조적으로 바람직

---

## 5. 운영 주의사항

### 5.1 OpenAI API 비용

- 분석 1건당 GPT-4.1 1회 + gpt-4.1-mini 2회 + 임베딩 N회
- 코너 테스트 100건 실행 시 상당한 API 비용 발생
- 불필요한 반복 테스트 주의

### 5.2 분석 API 타임아웃

- 프론트엔드 타임아웃: 120초
- 이미지 분석 시 GPT-4.1 Vision 호출로 30~60초 소요 가능
- 복잡한 시나리오일수록 응답 지연

### 5.3 PDF 파싱 품질

- 일부 PDF에서 텍스트 추출 실패 가능 (이미지 기반 PDF)
- 조문 분리 정규식이 비표준 형식을 놓칠 수 있음
- 새 PDF 추가 시 파싱 결과 확인 필요

---

## 6. 향후 개선 가능 영역

| 영역 | 현재 상태 | 개선 방향 |
|------|-----------|-----------|
| 미매칭 법령 1건 | 제383조 (관리적 조항) | 키워드 매핑 추가 또는 프롬프트 강화 |
| ~~미매칭 KOSHA 6건~~ | **100% 달성 (49/49)** | ~~분류 경계 가이드 키워드 매핑~~ → 해결 완료 |
| openai_client temp | 기본값 (~1.0) | 0.3~0.5로 낮추면 안정성 향상 가능 |
| 키워드 매핑 커버리지 | 법조항 26%, KOSHA 7% | 확대 시 정확도 향상 가능 (유지보수 부담 trade-off) |
| 타입 안전성 | 일부 as any 사용 | TypeScript strict mode 적용 |
