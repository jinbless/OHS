# kosha-guide-mapping Completion Report

> **Feature**: KOSHA GUIDE PDF 파싱, 인덱싱, 산안법 조문 매핑, 검색 서비스
>
> **Phase**: Report (완료)
> **Date**: 2026-02-21
> **PDCA Cycle**: Plan → Design → Do → Check (87% → ADJUST → 보완) → Report

---

## 1. 요약

KOSHA GUIDE(안전보건공단 기술지침) 1,040개 PDF를 파싱하여 산안법 조문과 자동 매핑하고,
위험분석 결과에 관련 KOSHA GUIDE를 함께 제시하는 기능을 구현 완료.

| 항목 | 수치 |
|------|------|
| PDF 파싱 성공 | **1,030 / 1,040** (99%) |
| 섹션 추출 | **21,966개** |
| 명시적 매핑 (PDF 관련법규) | **1,861건** |
| ChromaDB 인덱싱 | **21,966 섹션** (218MB) |
| 벡터 검색 폴백 | **활성** |

## 2. PDCA 이력

### Plan (2026-02-21 16:00)
- 1,040개 KOSHA GUIDE PDF 분석
- 15개 분류코드 파악 (G/C/D/E/M/P/H/B/A/W/T/X/O/F/K)
- MVP 스코프 확정: SQLite + ChromaDB 기반

### Design (2026-02-21 16:30)
- PDF 본문 구조 분석 (헤더/개요/본문 섹션)
- 핵심 발견: PDF "관련법규" 섹션에서 산안법 조문번호 직접 추출 가능
- 3 SQLite 테이블 + 1 ChromaDB 컬렉션 설계
- 2단계 자동 매핑 전략 (명시적 + 임베딩 유사도)

### Do (2026-02-21 17:00)
- 구현 파일 9개 신규/수정

| 파일 | 변경 | 내용 |
|------|------|------|
| `backend/app/db/models.py` | 수정 | KoshaGuide, GuideSection, RegGuideMapping 모델 |
| `backend/app/models/guide.py` | 신규 | GuideSectionInfo, GuideMatch Pydantic 모델 |
| `backend/app/services/guide_service.py` | 신규 | 파싱/인덱싱/매핑/검색 핵심 서비스 (522줄) |
| `backend/app/models/analysis.py` | 수정 | related_guides 필드 추가 |
| `backend/app/services/analysis_service.py` | 수정 | KOSHA GUIDE 검색 통합 |
| `backend/app/main.py` | 수정 | startup 시 파싱/매핑/인덱싱 자동 실행 |
| `frontend/src/components/results/RelatedGuides.tsx` | 신규 | KOSHA GUIDE 표시 UI |
| `frontend/src/pages/ResultPage.tsx` | 수정 | guides 탭 추가 |
| `docker-compose.yml` | 수정 | guide 볼륨 마운트 |

### Check (2026-02-21)
- **matchRate: 87% (ADJUST)**
- 주요 Gap: ChromaDB 인덱싱 startup 미호출 (G-03)
- 보완: `main.py`에 `build_index()` 호출 추가
- 보완 후 인덱싱 완료: 21,966 섹션 → 218MB ChromaDB

## 3. 기술 상세

### 3.1 PDF 파싱 파이프라인

```
1,040 PDF → 파일명 정규식 → PyMuPDF 텍스트 추출
    → 관련법규 조문번호 추출 (제N조 패턴)
    → 섹션 분해 (숫자 헤더 기준)
    → 2000자 청킹 → SQLite 저장
```

**파일명 정규식** (3패턴):
1. 기본: `([A-Z])-(\d+)-(\d{4})[\s_]+(.+)\.pdf`
2. 복합코드: `([A-Z]-[A-Z])-(\d+)-(\d{4})[\s_]+(.+)\.pdf`
3. 처리 불가 (10건): 스캔 PDF 9건 + 파일명 이상 1건

### 3.2 자동 매핑

- **Stage 1 (명시적)**: PDF "관련법규" 섹션에서 `제(\d+)조` 패턴 추출 → 1,861건
- **Stage 2 (벡터 폴백)**: 매핑 테이블에 없는 경우 ChromaDB 벡터 검색으로 보충
- **분류코드 범위**: 15개 분류코드 → 산안법 조문 범위 매핑 테이블 정의

### 3.3 검색 흐름

```
위험분석 완료
  → related_articles (법조항 5개)
  → article_numbers 추출
  → reg_guide_mapping 테이블 조회 (1차)
  → ChromaDB 벡터 검색 보충 (2차)
  → related_guides (최대 3개) 반환
```

### 3.4 검증된 매핑 예시

| 조문 | 매핑 GUIDE 수 | 대표 예시 |
|------|-------------|----------|
| 제42조 (추락) | 35개 | 추락방호망, 안전대, 비계 관련 가이드 |
| 제301조 (전기) | 4개 | 전기작업, 절연용구 관련 가이드 |

## 4. 프론트엔드 UI

- `RelatedGuides.tsx`: 15개 분류코드별 라벨/컬러 태그
- 확장형 카드 UI (guide_code + 분류 뱃지 + 관련 섹션 미리보기)
- 조건부 탭 표시 (KOSHA GUIDE 존재 시에만 탭 노출)

## 5. 인프라

- Docker Compose: `./guide:/home/blessjin/cashtoss/ohs/guide:ro` 볼륨 마운트
- ChromaDB: `chromadb_data` 볼륨 (기존 ohs_articles + 신규 kosha_guides)
- SQLite: `ohs.db` 내 3개 테이블 추가 (37MB → 포함)
- 서비스 시작 시 자동 초기화 (parse → map → index, 이미 있으면 스킵)

## 6. 파싱 오류 목록 (10/1,040)

| 유형 | 건수 | 원인 |
|------|------|------|
| 텍스트 부족 (스캔 PDF) | 9 | 이미지 기반 PDF, OCR 미지원 |
| 파일명 파싱 실패 | 1 | `D-27- 2021` (공백 이상) |

## 7. 남은 과제 (향후)

| 항목 | 우선순위 | 비고 |
|------|---------|------|
| 편/장 참조 → 조문 범위 확장 | P3 | 매핑 수 소폭 증가 예상 |
| 섹션 하위번호 (`3.1`) 지원 | P3 | 현재 충분한 섹션 수 |
| Stage 2 사전매핑 (batch) | P2 | 런타임 검색 대체 중 |
| SQLite DB 볼륨 영속성 | P1 | 현재 컨테이너 재생성 시 재파싱 |
| 스캔 PDF OCR 지원 | P3 | 9건 미파싱 대상 |

## 8. 비용

| 항목 | 비용 |
|------|------|
| ChromaDB 인덱싱 (text-embedding-3-small, 21,966 섹션) | ~$0.4 (일회성) |
| 분석 시 벡터 검색 폴백 (per request) | ~$0.001 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-02-21 | Initial completion report | Claude (PDCA) |
