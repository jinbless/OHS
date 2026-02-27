# Design: ontology-restructure

> Plan 문서: `docs/01-plan/features/ontology-restructure.plan.md`
> 온톨로지 구조 재설계 — 구현 상세 설계
> **구현 완료: 2026-02-27** | 법령 98.0% (49/50), KOSHA 100.0% (49/49)

---

## 1. 구현 순서 (Phase 1 → 2 → 3 → 4) — 전체 완료

```
Phase 1: 분류 체계 통합        [완료] ✅ hazard_taxonomy.json + taxonomy.py + DB 스키마
    ↓
Phase 2: 법조항 계층 구조       [완료] ✅ article_chapters.json + 하드코딩 3곳 제거 + 리네이밍
    ↓
Phase 3: 다중 데이터 유형 매핑   [완료] ✅ video_service.py taxonomy 연동
    ↓
Phase 4: LLM 프롬프트 동적 생성  [완료] ✅ prompt_builder.py + analysis_prompts.py 동적화
```

---

## 2. Phase 1: 분류 체계 통합

### 2.1 통합 분류 코드 정의

**파일 신규**: `backend/app/data/hazard_taxonomy.json`

```json
{
  "version": "1.0",
  "major_categories": {
    "physical": {
      "label": "물리적 위험",
      "codes": ["FALL", "SLIP", "COLLISION", "CRUSH", "CUT", "FALLING_OBJECT"],
      "legacy_norm_category": ["safety", "equipment"]
    },
    "chemical": {
      "label": "화학적 위험",
      "codes": ["CHEMICAL", "FIRE_EXPLOSION", "TOXIC", "CORROSION"],
      "legacy_norm_category": ["safety"]
    },
    "electrical": {
      "label": "전기적 위험",
      "codes": ["ELECTRIC", "ARC_FLASH"],
      "legacy_norm_category": ["safety", "equipment"]
    },
    "ergonomic": {
      "label": "인간공학적 위험",
      "codes": ["ERGONOMIC", "REPETITIVE", "HEAVY_LIFTING", "POSTURE"],
      "legacy_norm_category": ["procedure"]
    },
    "environmental": {
      "label": "환경적 위험",
      "codes": ["NOISE", "TEMPERATURE", "LIGHTING", "ENVIRONMENTAL"],
      "legacy_norm_category": ["safety", "procedure"]
    },
    "biological": {
      "label": "생물학적 위험",
      "codes": ["BIOLOGICAL"],
      "legacy_norm_category": ["safety"]
    }
  },
  "code_to_major": {
    "FALL": "physical",
    "SLIP": "physical",
    "COLLISION": "physical",
    "CRUSH": "physical",
    "CUT": "physical",
    "FALLING_OBJECT": "physical",
    "CHEMICAL": "chemical",
    "FIRE_EXPLOSION": "chemical",
    "TOXIC": "chemical",
    "CORROSION": "chemical",
    "ELECTRIC": "electrical",
    "ARC_FLASH": "electrical",
    "ERGONOMIC": "ergonomic",
    "REPETITIVE": "ergonomic",
    "HEAVY_LIFTING": "ergonomic",
    "POSTURE": "ergonomic",
    "NOISE": "environmental",
    "TEMPERATURE": "environmental",
    "LIGHTING": "environmental",
    "ENVIRONMENTAL": "environmental",
    "BIOLOGICAL": "biological"
  }
}
```

### 2.2 DB 스키마 변경

**파일**: `backend/app/db/models.py`

`NormStatement` 테이블에 2개 컬럼 추가 (기존 `norm_category` 유지):

```python
class NormStatement(Base):
    __tablename__ = "norm_statements"

    # ... 기존 필드 유지 ...

    # 기존 (하위 호환)
    norm_category = Column(String(20), nullable=True, index=True)

    # 신규: 통합 분류 체계
    hazard_major = Column(String(20), nullable=True, index=True)   # physical|chemical|...
    hazard_codes = Column(Text, nullable=True)                      # JSON array: ["FALL","SLIP"]

    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

**마이그레이션 전략**: SQLite ALTER TABLE로 컬럼 추가 → 기존 데이터는 `hazard_major=null` 상태 유지 → Phase 4에서 LLM으로 보충

### 2.3 분류 변환 유틸리티

**파일 신규**: `backend/app/utils/taxonomy.py`

```python
"""통합 위험 분류 체계 유틸리티"""
import json
from pathlib import Path
from typing import Optional

_TAXONOMY = None

def _load_taxonomy() -> dict:
    global _TAXONOMY
    if _TAXONOMY is None:
        path = Path(__file__).parent.parent / "data" / "hazard_taxonomy.json"
        with open(path, "r", encoding="utf-8") as f:
            _TAXONOMY = json.load(f)
    return _TAXONOMY

def code_to_major(hazard_code: str) -> Optional[str]:
    """세부코드 → 대분류. 예: 'FALL' → 'physical'"""
    t = _load_taxonomy()
    return t["code_to_major"].get(hazard_code.upper())

def major_to_codes(major: str) -> list[str]:
    """대분류 → 세부코드 목록. 예: 'physical' → ['FALL','SLIP',...]"""
    t = _load_taxonomy()
    cat = t["major_categories"].get(major, {})
    return cat.get("codes", [])

def legacy_to_major(norm_category: str) -> list[str]:
    """레거시 norm_category → 가능한 대분류 목록. 예: 'safety' → ['physical','chemical',...]"""
    t = _load_taxonomy()
    result = []
    for major, info in t["major_categories"].items():
        if norm_category in info.get("legacy_norm_category", []):
            result.append(major)
    return result

def get_all_codes() -> list[str]:
    """전체 세부코드 목록"""
    t = _load_taxonomy()
    return list(t["code_to_major"].keys())
```

### 2.4 norm_extractor.py 프롬프트 수정

**파일**: `backend/app/services/norm_extractor.py`

**변경 1**: `SYSTEM_PROMPT` 수정 — `norm_category` 설명에 통합 코드 추가

```python
SYSTEM_PROMPT = """당신은 산업안전보건법 법조항 분석 전문가입니다.
주어진 법조항 텍스트를 규범명제(NormStatement) 단위로 분해하세요.

각 규범명제는 다음 구조를 가집니다:
- subject_role: 의무/권리의 주체 (사업주, 근로자, 관리감독자, 안전관리자 등)
- action: 구체적 행위 (설치, 점검, 교부, 착용, 배치 등)
- object: 행위의 대상/객체 (안전난간, 방호장치, 보호구, 안전표지 등)
- condition_text: 적용 조건 (높이2m이상, 인화성물질, 상시근로자5인이상 등). 없으면 null.
- legal_effect: 다음 중 하나만 사용:
  - OBLIGATION: ~해야 한다 (의무)
  - PROHIBITION: ~하여서는 아니 된다 (금지)
  - PERMISSION: ~할 수 있다 (허용)
  - EXCEPTION: ~의 경우에는 그러하지 아니하다 (예외)
- effect_description: 효과를 간략히 설명 (예: "안전난간 설치 의무", "사용 금지")
- paragraph: 해당 항 번호 (제1항, 제2항 등). 없으면 null.
- norm_category: 다음 중 하나:
  - safety: 안전/위험 관련 (추락, 감전, 화재, 폭발 등)
  - procedure: 절차/관리 (신고, 보고, 교육, 점검 등)
  - equipment: 설비/장비 (보호구, 기계, 장치 등)
  - management: 행정/관리 (서류, 기록, 자격 등)
- hazard_major: 규범명제가 다루는 위험의 대분류 (하나만):
  - physical: 물리적 (추락, 전도, 충돌, 끼임, 절단, 낙하물)
  - chemical: 화학적 (유해물질, 화재/폭발, 독성, 부식)
  - electrical: 전기적 (감전, 아크플래시)
  - ergonomic: 인간공학적 (반복작업, 중량물, 부적절한 자세)
  - environmental: 환경적 (소음, 온도, 조명, 밀폐공간)
  - biological: 생물학적 (감염, 병원체)
  - null: 특정 위험 유형에 해당하지 않는 관리/행정 조항
- hazard_codes: 규범명제가 다루는 세부 위험코드 (JSON 배열, 해당하는 것만):
  물리적: FALL(추락), SLIP(전도), COLLISION(충돌), CRUSH(끼임), CUT(절단), FALLING_OBJECT(낙하물)
  화학적: CHEMICAL(유해물질), FIRE_EXPLOSION(화재/폭발), TOXIC(독성), CORROSION(부식)
  전기적: ELECTRIC(감전), ARC_FLASH(아크플래시)
  인간공학적: ERGONOMIC(근골격계), REPETITIVE(반복작업), HEAVY_LIFTING(중량물), POSTURE(부적절자세)
  환경적: NOISE(소음), TEMPERATURE(온도), LIGHTING(조명), ENVIRONMENTAL(밀폐/환경)
  생물학적: BIOLOGICAL(감염/병원체)

규칙:
1. 하나의 법조항에 여러 의무/금지가 있으면 각각 별개의 규범명제로 분해
2. 항(①, ② 등)이 있으면 항 단위로 분해
3. 단서 조항("다만...")은 EXCEPTION으로 별도 분해
4. full_text는 해당 규범명제에 대응하는 원문 텍스트를 그대로 포함
5. hazard_major는 규범명제 내용을 기준으로 가장 적합한 하나만 선택
6. hazard_codes는 해당하는 세부코드를 모두 포함 (1~3개)

반드시 JSON 배열로만 응답하세요. 추가 설명 없이 JSON만 출력합니다."""
```

**변경 2**: `NORM_SCHEMA` 에 신규 필드 추가

```python
NORM_SCHEMA = {
    "name": "norm_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "norms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject_role": {"type": ["string", "null"]},
                        "action": {"type": ["string", "null"]},
                        "object": {"type": ["string", "null"]},
                        "condition_text": {"type": ["string", "null"]},
                        "legal_effect": {
                            "type": "string",
                            "enum": ["OBLIGATION", "PROHIBITION", "PERMISSION", "EXCEPTION"]
                        },
                        "effect_description": {"type": ["string", "null"]},
                        "paragraph": {"type": ["string", "null"]},
                        "norm_category": {
                            "type": "string",
                            "enum": ["safety", "procedure", "equipment", "management"]
                        },
                        "hazard_major": {
                            "type": ["string", "null"],
                            "enum": ["physical", "chemical", "electrical",
                                     "ergonomic", "environmental", "biological", None]
                        },
                        "hazard_codes": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "full_text": {"type": "string"}
                    },
                    "required": [
                        "subject_role", "action", "object", "condition_text",
                        "legal_effect", "effect_description", "paragraph",
                        "norm_category", "hazard_major", "hazard_codes", "full_text"
                    ],
                    "additionalProperties": False
                }
            }
        },
        "required": ["norms"],
        "additionalProperties": False
    }
}
```

**변경 3**: `NormExtractor.extract_norms()` — 신규 필드 저장 로직

```python
# extract_norms() 내부, validate 후:
norm["hazard_major"] = norm.get("hazard_major")
norm["hazard_codes"] = json.dumps(
    norm.get("hazard_codes", []), ensure_ascii=False
)
```

### 2.5 ontology_service.py 수정

**변경**: `extract_all_norms()` — 신규 필드 DB 저장

```python
# ontology_service.py, extract_all_norms() 내부:
stmt = NormStatement(
    article_number=norm["article_number"],
    paragraph=norm.get("paragraph"),
    statement_order=norm.get("statement_order", 1),
    subject_role=norm.get("subject_role"),
    action=norm.get("action"),
    object=norm.get("object"),
    condition_text=norm.get("condition_text"),
    legal_effect=norm["legal_effect"],
    effect_description=norm.get("effect_description"),
    full_text=norm["full_text"],
    norm_category=norm.get("norm_category"),
    hazard_major=norm.get("hazard_major"),        # NEW
    hazard_codes=norm.get("hazard_codes"),          # NEW (JSON string)
)
```

### 2.6 ontology 응답 모델 수정

**파일**: `backend/app/models/ontology.py`

```python
class NormStatementResponse(BaseModel):
    # ... 기존 필드 ...
    norm_category: Optional[str] = None
    hazard_major: Optional[str] = None      # NEW
    hazard_codes: List[str] = []            # NEW
```

---

## 3. Phase 2: 법조항 계층 구조

### 3.1 조문 계층 매핑 데이터

**파일 신규**: `backend/app/data/article_chapters.json`

```json
{
  "version": "1.0",
  "description": "산업안전보건기준에 관한 규칙 편/장 구조",
  "chapters": [
    {
      "part": "제1편 총칙",
      "chapter": "제2장 작업장",
      "article_range": [3, 21],
      "hazard_major": null,
      "kosha_classifications": ["G"]
    },
    {
      "part": "제1편 총칙",
      "chapter": "제3장 통로",
      "article_range": [22, 31],
      "hazard_major": "physical",
      "hazard_codes": ["FALL", "SLIP"],
      "kosha_classifications": ["G", "C"]
    },
    {
      "part": "제1편 총칙",
      "chapter": "제4장 보호구",
      "article_range": [32, 35],
      "hazard_major": "physical",
      "kosha_classifications": ["G", "B"]
    },
    {
      "part": "제2편 안전기준",
      "chapter": "제6장 추락·붕괴 위험 방지",
      "article_range": [42, 55],
      "hazard_major": "physical",
      "hazard_codes": ["FALL", "FALLING_OBJECT"],
      "kosha_classifications": ["G", "C"]
    },
    {
      "part": "제2편 안전기준",
      "chapter": "제7장 비계",
      "article_range": [56, 70],
      "hazard_major": "physical",
      "hazard_codes": ["FALL"],
      "kosha_classifications": ["C"]
    },
    {
      "part": "제2편 안전기준",
      "chapter": "제1장 기계·기구 위험예방",
      "article_range": [86, 131],
      "hazard_major": "physical",
      "hazard_codes": ["CRUSH", "CUT", "COLLISION"],
      "kosha_classifications": ["M"]
    },
    {
      "part": "제2편 안전기준",
      "chapter": "크레인·양중기",
      "article_range": [132, 170],
      "hazard_major": "physical",
      "hazard_codes": ["CRUSH", "FALLING_OBJECT", "COLLISION"],
      "kosha_classifications": ["M", "C", "B"]
    },
    {
      "part": "제2편 안전기준",
      "chapter": "건설기계·차량",
      "article_range": [172, 224],
      "hazard_major": "physical",
      "hazard_codes": ["COLLISION", "CRUSH", "FALL"],
      "kosha_classifications": ["C", "M"]
    },
    {
      "part": "제2편 안전기준",
      "chapter": "제2장 폭발·화재·위험물",
      "article_range": [225, 300],
      "hazard_major": "chemical",
      "hazard_codes": ["FIRE_EXPLOSION", "CHEMICAL", "TOXIC"],
      "kosha_classifications": ["P", "F"]
    },
    {
      "part": "제2편 안전기준",
      "chapter": "제3장 전기 안전",
      "article_range": [301, 327],
      "hazard_major": "electrical",
      "hazard_codes": ["ELECTRIC", "ARC_FLASH"],
      "kosha_classifications": ["E"]
    },
    {
      "part": "제2편 안전기준",
      "chapter": "제4장 건설작업 위험예방",
      "article_range": [329, 419],
      "hazard_major": "physical",
      "hazard_codes": ["FALL", "CRUSH", "COLLISION"],
      "kosha_classifications": ["C"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제1장 관리대상 유해물질",
      "article_range": [420, 451],
      "hazard_major": "chemical",
      "hazard_codes": ["CHEMICAL", "TOXIC"],
      "kosha_classifications": ["H", "P"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제2장 허가대상 유해물질·석면",
      "article_range": [452, 511],
      "hazard_major": "chemical",
      "hazard_codes": ["CHEMICAL", "TOXIC"],
      "kosha_classifications": ["H"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제4장 소음·진동",
      "article_range": [512, 521],
      "hazard_major": "environmental",
      "hazard_codes": ["NOISE"],
      "kosha_classifications": ["A", "H"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제6장 온도·습도·유해물질접촉",
      "article_range": [558, 572],
      "hazard_major": "environmental",
      "hazard_codes": ["TEMPERATURE", "CHEMICAL"],
      "kosha_classifications": ["W", "H"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제7장 방사선",
      "article_range": [573, 591],
      "hazard_major": "environmental",
      "hazard_codes": ["ENVIRONMENTAL"],
      "kosha_classifications": ["H"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제8장 병원체",
      "article_range": [592, 604],
      "hazard_major": "biological",
      "hazard_codes": ["BIOLOGICAL"],
      "kosha_classifications": ["H"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제9장 분진",
      "article_range": [606, 617],
      "hazard_major": "environmental",
      "hazard_codes": ["ENVIRONMENTAL"],
      "kosha_classifications": ["H", "A"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제10장 밀폐공간",
      "article_range": [618, 644],
      "hazard_major": "environmental",
      "hazard_codes": ["ENVIRONMENTAL"],
      "kosha_classifications": ["E", "X"]
    },
    {
      "part": "제3편 보건기준",
      "chapter": "제12장 근골격계 건강장해",
      "article_range": [656, 673],
      "hazard_major": "ergonomic",
      "hazard_codes": ["ERGONOMIC", "REPETITIVE", "HEAVY_LIFTING", "POSTURE"],
      "kosha_classifications": ["H", "M"]
    }
  ]
}
```

### 3.2 계층 조회 유틸리티

**파일에 추가**: `backend/app/utils/taxonomy.py`

```python
_CHAPTERS = None

def _load_chapters() -> list:
    global _CHAPTERS
    if _CHAPTERS is None:
        path = Path(__file__).parent.parent / "data" / "article_chapters.json"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _CHAPTERS = data["chapters"]
    return _CHAPTERS

def get_chapter_for_article(article_num: int) -> Optional[dict]:
    """조문 번호 → 장(chapter) 정보 반환"""
    for ch in _load_chapters():
        r = ch["article_range"]
        if r[0] <= article_num <= r[1]:
            return ch
    return None

def get_articles_for_category(hazard_major: str) -> list[tuple[int, int]]:
    """대분류 → 조문 범위 목록 (CATEGORY_ARTICLE_RANGE 대체)"""
    ranges = []
    for ch in _load_chapters():
        if ch.get("hazard_major") == hazard_major:
            ranges.append(tuple(ch["article_range"]))
    return ranges

def get_articles_for_classification(kosha_cls: str) -> Optional[tuple[int, int]]:
    """KOSHA 분류코드 → 조문 범위 (CLASSIFICATION_TO_ARTICLE_RANGE 대체)"""
    for ch in _load_chapters():
        if kosha_cls in ch.get("kosha_classifications", []):
            return tuple(ch["article_range"])
    return None

def get_classifications_for_article(article_num: int) -> list[str]:
    """조문 번호 → 관련 KOSHA 분류코드 목록"""
    ch = get_chapter_for_article(article_num)
    if ch:
        return ch.get("kosha_classifications", [])
    return []
```

### 3.3 하드코딩 제거: 3곳 수정

**수정 1**: `ontology_service.py` — `CATEGORY_ARTICLE_RANGE` 제거

```python
# 삭제:
# CATEGORY_ARTICLE_RANGE = { "physical": [...], ... }

# 대체: find_related_articles_for_hazards() 내부
from app.utils.taxonomy import get_articles_for_category

# 변경 전:
#   cat_ranges.extend(self.CATEGORY_ARTICLE_RANGE.get(cat, []))
# 변경 후:
    cat_ranges.extend(get_articles_for_category(cat))
```

**수정 2**: `analysis_service.py` — `CATEGORY_ARTICLE_RANGE` 제거

```python
# 삭제:
# CATEGORY_ARTICLE_RANGE = { "physical": [...], ... }

# 대체: _find_best_norm_for_hazard() 는 기존 로직 유지 (키워드 기반 매칭)
# CATEGORY_ARTICLE_RANGE 참조하던 폴백 로직은 taxonomy 유틸로 대체
from app.utils.taxonomy import get_articles_for_category
```

**수정 3**: `guide_service.py` — `CLASSIFICATION_TO_ARTICLE_RANGE` 제거

```python
# 삭제:
# CLASSIFICATION_TO_ARTICLE_RANGE = { "G": None, "C": (328, 419), ... }

# 대체: 외부에서 참조하는 곳은 taxonomy로 전환
from app.utils.taxonomy import get_articles_for_classification

# 함수 제공 (하위 호환):
CLASSIFICATION_TO_ARTICLE_RANGE = None  # 제거 후 import 에러 방지

def get_article_range_for_classification(cls: str) -> Optional[tuple]:
    return get_articles_for_classification(cls)
```

### 3.4 article_service.py 리네이밍

```python
# 변경 전: def parse_all_pdfs(self) -> List[ArticleChunk]:
# 변경 후:
def load_articles(self) -> List[ArticleChunk]:
    """조문 데이터 로드 (캐시 우선, PDF 폴백)"""
    # 내부 로직은 동일 (캐시 → PDF)
    ...

# 하위 호환 alias:
def parse_all_pdfs(self) -> List[ArticleChunk]:
    """@deprecated: load_articles()를 사용하세요"""
    return self.load_articles()
```

**호출부 6곳**: `ontology_service.py` 내 모든 `article_service.parse_all_pdfs()` → `article_service.load_articles()`

### 3.5 articles_cache.json 스키마 확장

**기존**:
```json
{"article_number": "제42조", "title": "추락의 방지", "content": "...", "source_file": "..."}
```

**확장 후**:
```json
{
  "article_number": "제42조",
  "title": "추락의 방지",
  "content": "...",
  "source_file": "",
  "part": "제2편 안전기준",
  "chapter": "제6장 추락·붕괴 위험 방지",
  "section": null,
  "hazard_major": "physical",
  "hazard_codes": ["FALL"]
}
```

**구현**: 빌드 시 `article_chapters.json`을 참조하여 각 조문의 계층 메타데이터 자동 부여

```python
# article_service.py, load_articles() 또는 build_index()에 추가:
from app.utils.taxonomy import get_chapter_for_article, extract_article_number

def _enrich_with_chapter(self, chunk: ArticleChunk) -> ArticleChunk:
    """ArticleChunk에 계층 메타데이터 추가"""
    num = extract_article_number(chunk.article_number)
    if num:
        ch = get_chapter_for_article(num)
        if ch:
            chunk.part = ch.get("part", "")
            chunk.chapter = ch.get("chapter", "")
            chunk.hazard_major = ch.get("hazard_major")
            chunk.hazard_codes = ch.get("hazard_codes", [])
    return chunk
```

---

## 4. Phase 3: 다중 데이터 유형 매핑

### 4.1 SemanticMapping 확장

**DB 변경 없음** — `source_type`, `target_type`은 이미 `String(20)`으로 자유 문자열.

**코드 레벨 문서화** (새 값 추가):

```python
# 허용 source_type:
SOURCE_TYPES = {"article", "norm_statement", "hazard_code"}

# 허용 target_type:
TARGET_TYPES = {"guide", "article", "video", "image_analysis", "accident_case"}

# 새 relation_type:
RELATION_TYPES = {
    # 기존
    "IMPLEMENTS", "SUPPLEMENTS", "SPECIFIES_CRITERIA",
    "SPECIFIES_METHOD", "CROSS_REFERENCES",
    # 신규
    "ILLUSTRATES",         # 영상/사진 → 법조항/가이드 (시각적 예시)
    "DEMONSTRATES_RISK",   # 사고사례 → 위험코드 (실증)
    "ADDRESSES",           # 법조항/가이드 → 위험코드 (다룸)
}
```

### 4.2 video_service 온톨로지 연동

**현재**: `video_service.match_by_ontology()` — 법조항 번호 → 하드코딩된 범위로 키워드 유추

```python
# 현재 video_service.py:191-196 (하드코딩)
if 32 <= num <= 67 or 86 <= num <= 166:
    match_keywords.update(["추락", "건설", "비계", "사다리", "끼임"])
elif 225 <= num <= 290:
    match_keywords.update(["화학", "폭발", "중독"])
```

**변경 후**: `taxonomy` 유틸 사용

```python
from app.utils.taxonomy import get_chapter_for_article

def match_by_ontology(self, db, norm_articles, guide_classifications, limit=10):
    # ...
    for article in norm_articles:
        num = extract_article_number(article)
        if num:
            ch = get_chapter_for_article(num)
            if ch:
                # 장 제목에서 키워드 추출
                chapter_words = re.findall(r'[가-힣]{2,}', ch["chapter"])
                match_keywords.update(chapter_words)
                # hazard_codes로 추가 키워드
                for code in ch.get("hazard_codes", []):
                    match_keywords.update(CODE_KEYWORDS.get(code, []))
    # ...
```

### 4.3 향후 확장 지점 (Phase 3에서 구조만 준비)

```python
# ontology_service.py에 추가:
async def create_video_mappings(self, db: Session) -> dict:
    """SafetyVideo ↔ 법조항/가이드 매핑 자동 생성"""
    videos = db.query(SafetyVideo).all()
    new_mappings = 0
    for video in videos:
        cats = json.loads(video.hazard_categories) if video.hazard_categories else []
        for cat in cats:
            # hazard_code → 관련 법조항 범위
            major = code_to_major(cat)
            if major:
                ranges = get_articles_for_category(major)
                # SemanticMapping(source_type="video", target_type="article", relation_type="ILLUSTRATES")
                ...
    return {"new_mappings": new_mappings}
```

---

## 5. Phase 4: LLM 프롬프트 동적 생성

### 5.1 프롬프트 빌더

**파일 신규**: `backend/app/integrations/prompts/prompt_builder.py`

```python
"""온톨로지 기반 동적 프롬프트 생성"""
import json
from typing import Optional
from sqlalchemy.orm import Session
from app.db.models import NormStatement
from app.utils.taxonomy import _load_chapters

def build_article_structure_section(db: Optional[Session] = None) -> str:
    """프롬프트용 조문 구조 섹션 생성

    우선순위:
    1. DB에 규범명제가 있으면 DB 기반 동적 생성
    2. 없으면 article_chapters.json 기반 정적 생성
    """
    if db:
        norm_count = db.query(NormStatement).count()
        if norm_count > 0:
            return _build_from_norms(db)

    return _build_from_chapters()

def _build_from_chapters() -> str:
    """article_chapters.json 기반 정적 생성 (폴백)"""
    chapters = _load_chapters()
    lines = ["## 산업안전보건기준에 관한 규칙 — 편/장 구조\n"]
    current_part = ""
    for ch in chapters:
        if ch["part"] != current_part:
            current_part = ch["part"]
            lines.append(f"\n### {current_part}\n")
        r = ch["article_range"]
        major = ch.get("hazard_major", "일반")
        lines.append(f"- **{ch['chapter']}** (제{r[0]}조~제{r[1]}조) [{major}]")
    return "\n".join(lines)

def _build_from_norms(db: Session) -> str:
    """규범명제 DB 기반 동적 생성"""
    from sqlalchemy import distinct
    # 조문별 대표 규범명제 조회
    articles = db.query(
        NormStatement.article_number,
        NormStatement.hazard_major,
    ).distinct(NormStatement.article_number).order_by(
        NormStatement.article_number
    ).all()

    chapters = _load_chapters()
    lines = ["## 산업안전보건기준에 관한 규칙 — 조문별 위험 유형\n"]
    current_chapter = ""
    for art_num, hazard_major in articles:
        # 장 찾기
        from app.utils.text_utils import extract_article_number
        num = extract_article_number(art_num)
        ch = None
        for c in chapters:
            if c["article_range"][0] <= num <= c["article_range"][1]:
                ch = c
                break
        ch_name = ch["chapter"] if ch else "기타"
        if ch_name != current_chapter:
            current_chapter = ch_name
            lines.append(f"\n### {ch_name}\n")
        hm = hazard_major or "general"
        lines.append(f"- {art_num} [{hm}]")
    return "\n".join(lines)
```

### 5.2 analysis_prompts.py 수정

**변경 방향**: 200줄 정적 조문구조 → `prompt_builder` 호출로 대체

```python
# analysis_prompts.py

# 정적 부분 (위험분석 가이드, category_code 목록 등)은 유지
SYSTEM_PROMPT_HEADER = """당신은 산업안전보건 전문가입니다.
작업현장의 위험요소를 분석하고 산업재해 예방을 위한 조언을 제공합니다.

분석 시 다음 사항을 고려하세요:
1. 물리적 위험요소 (추락, 끼임, 충돌, 낙하물, 절단 등)
2. 화학적 위험요소 (유해물질, 화재/폭발, 부식성 물질 등)
3. 전기적 위험요소 (감전, 아크 플래시 등)
4. 인간공학적 위험요소 (반복작업, 중량물 취급, 부적절한 자세 등)
5. 환경적 위험요소 (소음, 온도, 조명 등)

한국 산업안전보건법 기준을 참고하여 분석하세요.
모든 응답은 한국어로 작성하세요.

## category_code 목록
... (유지) ...

## 핵심 조문 매칭 가이드 (반드시 참고)
... (유지) ...

## KOSHA GUIDE 검색 키워드
... (유지) ...
"""

# 동적 부분: DB 연결 시 동적 생성, 없으면 정적 폴백
_CACHED_ARTICLE_STRUCTURE = None

def get_system_prompt(db=None) -> str:
    """시스템 프롬프트 반환 (조문 구조 동적 생성)"""
    global _CACHED_ARTICLE_STRUCTURE
    if _CACHED_ARTICLE_STRUCTURE is None:
        from app.integrations.prompts.prompt_builder import build_article_structure_section
        _CACHED_ARTICLE_STRUCTURE = build_article_structure_section(db)
    return SYSTEM_PROMPT_HEADER + "\n\n" + _CACHED_ARTICLE_STRUCTURE

# 기존 호환: SYSTEM_PROMPT 변수 유지 (정적 폴백)
SYSTEM_PROMPT = SYSTEM_PROMPT_HEADER + "\n\n" + _STATIC_ARTICLE_STRUCTURE
```

### 5.3 openai_client.py 수정

```python
# 변경 전:
from app.integrations.prompts.analysis_prompts import SYSTEM_PROMPT

# 변경 후:
from app.integrations.prompts.analysis_prompts import get_system_prompt

class OpenAIClient:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4.1"
        self._system_prompt = None

    def _get_prompt(self, db=None) -> str:
        if self._system_prompt is None:
            self._system_prompt = get_system_prompt(db)
        return self._system_prompt

    async def analyze_text(self, description, workplace_type=None,
                           industry_sector=None, db=None) -> dict:
        prompt = self._get_prompt(db)
        # ... 이하 동일, SYSTEM_PROMPT → prompt 사용 ...
```

---

## 6. 마이그레이션 계획

### 6.1 기존 규범명제 데이터 처리

**방침**: 기존 690건 규범명제의 `hazard_major`/`hazard_codes`는 **DB에서 삭제하지 않고** null 상태로 유지.

**보충 방법 2가지** (선택):

| 방법 | 비용 | 정확도 | 시간 |
|------|:----:|:------:|:----:|
| A. 규칙 기반 | 0 | 85% | 즉시 |
| B. LLM 재추출 | GPT-4.1 × 690건 | 98% | ~10분 |

**방법 A (Phase 2에서 실행)**: `article_chapters.json` 기반 자동 부여

```python
# 마이그레이션 스크립트
def migrate_norm_hazard_fields(db: Session):
    norms = db.query(NormStatement).filter(NormStatement.hazard_major.is_(None)).all()
    for norm in norms:
        num = extract_article_number(norm.article_number)
        ch = get_chapter_for_article(num)
        if ch:
            norm.hazard_major = ch.get("hazard_major")
            norm.hazard_codes = json.dumps(ch.get("hazard_codes", []))
    db.commit()
```

**방법 B (선택사항)**: `norm_extractor`로 기존 규범명제 재처리 (hazard_major/hazard_codes만)

### 6.2 ChromaDB 인덱스

**변경 불필요** — ChromaDB 메타데이터에 새 필드 추가는 re-index 시 자동 반영. 기존 인덱스는 유지.

### 6.3 하위 호환성

| 항목 | 호환성 |
|------|--------|
| `parse_all_pdfs()` | alias로 유지, deprecation 경고 |
| `norm_category` | 기존 필드 유지, 신규 필드와 공존 |
| `CLASSIFICATION_TO_ARTICLE_RANGE` | `guide_service.py`에서 import하던 외부 코드 대비 |
| API 응답 | 신규 필드 추가만 (기존 필드 변경 없음) |
| `articles_cache.json` | 신규 필드 추가만 (기존 필드 유지) |

---

## 7. 테스트 전략 — 결과 (2026-02-27)

### 7.1 Phase별 검증 결과

| Phase | 검증 항목 | 방법 | 결과 |
|-------|-----------|------|:----:|
| 1 | norm_extractor가 hazard_major/hazard_codes 정상 출력 | DB 확인 | ✅ |
| 1 | taxonomy 유틸 정상 동작 | 서비스 동작 확인 | ✅ |
| 2 | CATEGORY_ARTICLE_RANGE 하드코딩 완전 제거 | grep 잔존 0건 | ✅ |
| 2 | 코너 테스트 법령 ≥ 98%, KOSHA ≥ 93% | `run_corner_test.py all` | ✅ 98.0%, 100.0% |
| 3 | video_service taxonomy 연동 | 서비스 동작 확인 | ✅ |
| 4 | 프롬프트 동적 생성 정상 동작 | 분석 API 호출 확인 | ✅ |
| 4 | 코너 테스트 최종 | `run_corner_test.py all` | ✅ 법령 98.0%, KOSHA 100.0% |

### 7.2 회귀 방지

```bash
# 매 Phase 완료 후 필수 실행:
docker compose build --no-cache
docker compose up -d
docker compose exec backend python scripts/run_corner_test.py all
```

---

## 8. 파일 변경 총정리

### 신규 파일 (4개)

| 파일 | Phase | 내용 |
|------|:-----:|------|
| `backend/app/data/hazard_taxonomy.json` | 1 | 통합 분류 체계 (6대분류 + 24세부코드) |
| `backend/app/utils/taxonomy.py` | 1+2 | 분류/계층 조회 유틸리티 |
| `backend/app/data/article_chapters.json` | 2 | 산안법 편/장 구조 매핑 |
| `backend/app/integrations/prompts/prompt_builder.py` | 4 | 동적 프롬프트 생성 |

### 수정 파일 (10개)

| 파일 | Phase | 변경 내용 |
|------|:-----:|----------|
| `backend/app/db/models.py` | 1 | NormStatement에 hazard_major, hazard_codes 추가 |
| `backend/app/services/norm_extractor.py` | 1 | 프롬프트 + 스키마 + 저장 로직 |
| `backend/app/models/ontology.py` | 1 | NormStatementResponse에 신규 필드 |
| `backend/app/services/article_service.py` | 2 | parse_all_pdfs → load_articles 리네이밍, 계층 보강 |
| `backend/app/services/ontology_service.py` | 1+2 | CATEGORY_ARTICLE_RANGE 제거, parse_all_pdfs → load_articles |
| `backend/app/services/analysis_service.py` | 2 | CATEGORY_ARTICLE_RANGE 제거, taxonomy 참조 |
| `backend/app/services/guide_service.py` | 2 | CLASSIFICATION_TO_ARTICLE_RANGE → taxonomy |
| `backend/app/services/video_service.py` | 3 | 하드코딩 범위 → taxonomy 참조 |
| `backend/app/integrations/prompts/analysis_prompts.py` | 4 | 동적 프롬프트 호출 |
| `backend/app/integrations/openai_client.py` | 4 | get_system_prompt() 연동 |

### 데이터 파일 수정 (1개)

| 파일 | Phase | 변경 |
|------|:-----:|------|
| `backend/data/articles_cache.json` | 2 | 계층 메타데이터 추가 (part, chapter, hazard_major, hazard_codes) |
