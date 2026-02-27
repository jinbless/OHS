# kosha-guide-mapping Design Document

> **Note (2026-02-27)**: 이 문서는 작성 시점의 코드 상태를 기술합니다. 이후 ontology-restructure에서 `CLASSIFICATION_TO_ARTICLE_RANGE` → `taxonomy.py`로 교체되었습니다.

> **Summary**: KOSHA GUIDE PDF 파싱, DB 저장, 산안법 조문 매핑, 서비스 통합 설계
>
> **Project**: OHS 위험요소 분석 서비스
> **Version**: 1.0.0
> **Author**: Claude (PDCA)
> **Date**: 2026-02-21
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/kosha-guide-mapping.plan.md`

---

## 1. KOSHA GUIDE PDF 구조 분석 (실제 파싱 결과)

### 1.1 파일명 패턴

```
{분류코드}-{번호}-{연도} {제목}.pdf

예시:
  G-1-2023 소용량 탱크 및 드럼의 화기작업에 관한 안전지침.pdf
  C-05-2016 건설공사 돌관작업 안전보건작업 지침.pdf
  E-1-2012 가공 전선로에서의 위험방지에 관한 기술지침.pdf
  M-1-2013 CNC 선반의 날아오는 가공물 등에 의한 위험방지 기술지침.pdf
```

파싱 정규식: `^([A-Z])-(\d+)-(\d{4})\s+(.+)\.pdf$`

### 1.2 PDF 본문 구조

```
[헤더]
  KOSHA GUIDE
  {분류코드} - {번호} - {연도}
  {제목}
  {연도}. {월}
  한국산업안전보건공단

[개요 섹션] ← 메타데이터 추출
  ○ 작성자: ...
  ○ 개정자: ...
  ○ 제·개정경과: ...
  ○ 관련규격 및 자료: ...
  ○ 관련법규·규칙·고시 등: ...    ← ★ 매핑 핵심 정보
  ○ 기술지침의 적용 및 문의: ...

[본문 섹션] ← 섹션 분해 대상
  1. 목적
  2. 적용범위
  3. 용어의 정의
  4. (본문 - 기준/방법/절차)
  ...
  N. 부록/서식
```

### 1.3 관련법규 추출 (자동 매핑 핵심)

PDF 개요 섹션의 "관련법규" 부분에서 산안법 조문번호를 직접 추출할 수 있다:

```
예시 (M-1-2013):
  "산업안전보건기준에 관한 규칙 제90조(날아오는 가공물 등에 의한 위험의 방지)"

예시 (C-05-2016):
  "산업안전보건기준에 관한 규칙 제2편 제4장 건설작업 등에 의한 위험예방"

예시 (E-1-2012):
  "산업안전보건기준에 관한 규칙 제2편 제3장(전기로 인한 위험방지)"
```

정규식: `제(\d+)조(?:의\d+)?` → 조문번호 추출
편/장 참조: `제(\d+)편\s*제(\d+)장` → 편/장 범위로 조문 확장

---

## 2. 데이터 모델 설계 (FR-02)

### 2.1 SQLite 테이블

#### kosha_guides (KOSHA GUIDE 메타데이터)

```sql
CREATE TABLE IF NOT EXISTS kosha_guides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guide_code TEXT NOT NULL UNIQUE,       -- "G-1-2023"
    classification TEXT NOT NULL,           -- "G"
    guide_number INTEGER NOT NULL,          -- 1
    guide_year INTEGER NOT NULL,            -- 2023
    title TEXT NOT NULL,                    -- "소용량 탱크 및 드럼의..."
    author TEXT,                            -- 작성자
    related_regulations TEXT,               -- 관련법규 원문 (JSON array)
    pdf_filename TEXT NOT NULL,             -- 원본 PDF 파일명
    total_pages INTEGER,                    -- PDF 페이지 수
    total_chars INTEGER,                    -- 텍스트 총 문자수
    parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### guide_sections (KOSHA GUIDE 섹션)

```sql
CREATE TABLE IF NOT EXISTS guide_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guide_id INTEGER NOT NULL REFERENCES kosha_guides(id),
    section_order INTEGER NOT NULL,         -- 섹션 순서
    section_title TEXT,                     -- "1. 목적", "3. 용어의 정의" 등
    section_type TEXT,                      -- purpose/scope/definition/standard/procedure/appendix
    body_text TEXT NOT NULL,                -- 섹션 본문 (최대 2000자)
    char_count INTEGER,                     -- 본문 길이
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### reg_guide_mapping (조문-가이드 매핑)

```sql
CREATE TABLE IF NOT EXISTS reg_guide_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_number TEXT NOT NULL,            -- "제42조", "제90조" 등
    guide_id INTEGER NOT NULL REFERENCES kosha_guides(id),
    mapping_type TEXT NOT NULL,              -- "explicit" (PDF 명시) / "auto" (임베딩 유사도)
    mapping_basis TEXT,                      -- 매핑 근거 설명
    relevance_score REAL,                   -- 자동 매핑인 경우 유사도 점수
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(article_number, guide_id)
);
```

### 2.2 ChromaDB 컬렉션

```python
# 기존 컬렉션 (유지)
ohs_articles:  442개 조문 청크 (text-embedding-3-small)

# 신규 컬렉션
kosha_guides:  KOSHA GUIDE 섹션별 임베딩
  - id: "{guide_code}_{section_order}"
  - document: "{section_title}\n{body_text}"
  - metadata: {
      guide_code, classification, title, section_order,
      section_title, section_type, guide_id
    }
```

---

## 3. PDF 파싱 파이프라인 설계 (FR-01)

### 3.1 파싱 흐름

```
1,040개 PDF 파일
    │
    ▼
[파일명 파싱] guide_code, classification, year, title 추출
    │
    ▼
[PyMuPDF] 전체 텍스트 추출
    │
    ▼
[개요 파싱] 관련법규 → 조문번호 추출 (자동 매핑용)
    │
    ▼
[섹션 분해] 숫자 헤더("1. ", "2. ") 기준 분할
    │
    ▼
[청킹] 2000자 초과 섹션 → 단락 기준 재분할
    │
    ▼
[DB 저장] kosha_guides + guide_sections 테이블
```

### 3.2 파일명 파싱

```python
import re

def parse_guide_filename(filename: str) -> dict:
    """파일명에서 가이드 정보 추출"""
    pattern = r"^([A-Z])-(\d+)-(\d{4})\s+(.+)\.pdf$"
    m = re.match(pattern, filename)
    if m:
        return {
            "classification": m.group(1),
            "guide_number": int(m.group(2)),
            "guide_year": int(m.group(3)),
            "title": m.group(4),
            "guide_code": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
        }
    return None
```

### 3.3 관련법규 파싱 (자동 매핑 핵심)

```python
def extract_related_regulations(text: str) -> list[str]:
    """PDF 텍스트에서 관련 산안법 조문번호 추출"""
    # 조문번호 직접 매칭
    article_pattern = r"제(\d+)조(?:의\d+)?"
    articles = re.findall(article_pattern, text[:3000])  # 개요 영역만

    # 편/장 참조 → 조문 범위로 확장
    chapter_pattern = r"제(\d+)편\s*제(\d+)장"
    chapters = re.findall(chapter_pattern, text[:3000])

    return list(set(f"제{n}조" for n in articles))
```

### 3.4 섹션 분해

```python
def split_into_sections(text: str) -> list[dict]:
    """본문을 섹션 단위로 분할"""
    # 숫자 헤더 패턴: "1. ", "2. ", "3.1 " 등
    pattern = r"\n(\d+(?:\.\d+)?)\.\s+(.+)"
    matches = list(re.finditer(pattern, text))

    sections = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        # 2000자 초과 시 재분할
        if len(body) > 2000:
            chunks = chunk_text(body, max_chars=2000)
            for j, chunk in enumerate(chunks):
                sections.append({
                    "section_order": len(sections) + 1,
                    "section_title": match.group(0).strip(),
                    "section_type": classify_section(match.group(2)),
                    "body_text": chunk,
                })
        else:
            sections.append({
                "section_order": len(sections) + 1,
                "section_title": match.group(0).strip(),
                "section_type": classify_section(match.group(2)),
                "body_text": body,
            })

    return sections
```

---

## 4. 자동 매핑 전략 (FR-04)

### 4.1 2단계 매핑

```
┌──────────────────────────────────────────────────────┐
│              자동 매핑 파이프라인                       │
├──────────────────────────────────────────────────────┤
│                                                      │
│  [Stage 1] 명시적 매핑 (관련법규 파싱)               │
│    PDF "관련법규" 섹션에서 추출한 조문번호로 직접 매핑 │
│    → mapping_type = "explicit"                       │
│    → 높은 신뢰도 (relevance_score = 0.95)            │
│                                                      │
│  [Stage 2] 임베딩 유사도 매핑                         │
│    KOSHA GUIDE 섹션 임베딩 ↔ 산안법 조문 임베딩      │
│    → mapping_type = "auto"                           │
│    → relevance_score = cosine_similarity             │
│    → threshold: 0.75 이상만 매핑                     │
│                                                      │
│  [필터링] 분류코드 기반 사전 필터링                   │
│    G(일반) → 전체 조문                               │
│    C(건설) → 제328조~제419조 (건설작업)              │
│    E(전기) → 제301조~제327조 (전기위험)              │
│    M(기계) → 제86조~제224조 (기계기구)               │
│    P(공정) → 제225조~제300조 (폭발화재)              │
│    H(보건) → 제420조~제670조 (보건기준)              │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### 4.2 분류코드 → 조문 범위 매핑

```python
CLASSIFICATION_TO_ARTICLE_RANGE = {
    "G": None,                # 일반안전 - 전체 범위
    "C": (328, 419),         # 건설안전
    "D": (328, 419),         # 건설안전(설계)
    "E": (301, 327),         # 전기안전
    "M": (86, 224),          # 기계안전
    "P": (225, 300),         # 공정안전(화재폭발)
    "H": (420, 670),         # 보건
    "B": (420, 670),         # 보건(일반)
    "A": (420, 670),         # 작업환경측정(보건 관련)
    "W": (420, 670),         # 작업환경(기타)
    "T": None,               # 교육 - 전체 범위
    "X": None,               # 기타 - 전체 범위
    "O": (420, 670),         # 산업보건
    "F": (225, 300),         # 화재폭발
    "K": None,               # KOSHA 기타
}
```

---

## 5. 서비스 통합 설계 (FR-05)

### 5.1 위험분석 결과 → KOSHA GUIDE 연결 흐름

```
위험분석 결과
    │
    ├─ related_articles (산안법 조문 5개)
    │     │
    │     ▼
    │   [reg_guide_mapping 조회]
    │     → 각 조문에 매핑된 KOSHA GUIDE 목록
    │
    ├─ category_code (위험 카테고리)
    │     │
    │     ▼
    │   [분류코드 기반 KOSHA GUIDE 검색]
    │     → 해당 분류의 KOSHA GUIDE 중 유사도 높은 것
    │
    └─ description (위험 설명)
          │
          ▼
        [ChromaDB kosha_guides 컬렉션 벡터 검색]
          → 설명과 가장 유사한 KOSHA GUIDE 섹션
```

### 5.2 API 응답 확장

```json
{
  "analysis_id": "...",
  "hazards": [...],
  "related_articles": [...],
  "related_guides": [
    {
      "guide_code": "G-1-2023",
      "title": "소용량 탱크 및 드럼의 화기작업에 관한 안전지침",
      "classification": "G",
      "relevant_sections": [
        {
          "section_title": "4. 세부 안전기준",
          "excerpt": "소용량 탱크 내부의 가연성 물질을...",
          "section_type": "standard"
        }
      ],
      "relevance_score": 0.89,
      "mapping_type": "explicit"
    }
  ]
}
```

### 5.3 Pydantic 모델

```python
class GuideSection(BaseModel):
    section_title: str
    excerpt: str
    section_type: str

class GuideMatch(BaseModel):
    guide_code: str
    title: str
    classification: str
    relevant_sections: list[GuideSection]
    relevance_score: float
    mapping_type: str  # "explicit" / "auto"
```

---

## 6. 수정 대상 파일 목록

| 파일 | 변경 내용 | 신규/수정 |
|------|----------|----------|
| `backend/app/services/guide_service.py` | KOSHA GUIDE 파싱, 인덱싱, 검색 서비스 | 신규 |
| `backend/app/models/guide.py` | GuideMatch, GuideSection Pydantic 모델 | 신규 |
| `backend/app/db/models.py` | kosha_guides, guide_sections, reg_guide_mapping 테이블 | 수정 |
| `backend/app/services/analysis_service.py` | KOSHA GUIDE 조회 로직 추가 | 수정 |
| `backend/app/models/analysis.py` | AnalysisResponse에 related_guides 추가 | 수정 |
| `frontend/src/components/results/RelatedGuides.tsx` | KOSHA GUIDE 표시 컴포넌트 | 신규 |

---

## 7. 구현 순서

```
[1] backend/app/db/models.py - SQLite 테이블 정의 (kosha_guides, guide_sections, reg_guide_mapping)
[2] backend/app/services/guide_service.py - PDF 파싱 + DB 저장
[3] backend/app/services/guide_service.py - ChromaDB 임베딩/인덱싱
[4] backend/app/services/guide_service.py - 자동 매핑 (명시적 + 임베딩)
[5] backend/app/models/guide.py - Pydantic 모델
[6] backend/app/services/analysis_service.py - 분석 결과에 KOSHA GUIDE 통합
[7] backend/app/models/analysis.py - API 응답 모델 확장
[8] frontend/src/components/results/RelatedGuides.tsx - UI 컴포넌트
[9] 테스트 및 검증
[10] Docker 재빌드 + 배포
```

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-21 | Initial design | Claude (PDCA) |
