"""
테스트 케이스 자동 생성기
- 기존 테스트셋에 없는 법조항/KOSHA 가이드를 선택
- GPT를 이용해 시나리오를 자동 생성
- 기존 테스트 데이터에 병합

Usage:
  python scripts/generate_test_cases.py articles 50   # 법조항 50개 추가
  python scripts/generate_test_cases.py kosha 51       # KOSHA 51개 추가
"""
import json
import sys
import random
import time
from pathlib import Path
from openai import OpenAI

DATA_DIR = Path(__file__).parent.parent / "data"
client = OpenAI()

CORNER_TYPES_ARTICLES = [
    "compound_risk",      # 복합 위험
    "close_articles",     # 근접 조문 구별
    "atypical_workplace", # 비전형 작업환경
    "equipment_spec",     # 설비 규격
    "administrative",     # 관리/행정
    "rare_hazard",        # 드문 위험
    "ambiguous",          # 모호한 표현
]

CORNER_TYPES_KOSHA = [
    "exact_match",    # 정확 매칭 테스트
    "similar_guide",  # 유사 가이드 구별
    "cross_domain",   # 교차 도메인
    "specific_detail",# 세부 규정
]


def generate_article_scenarios(articles: list[dict], count: int) -> list[dict]:
    """법조항 시나리오 생성"""
    selected = random.sample(articles, min(count, len(articles)))
    results = []

    batch_size = 10
    for batch_start in range(0, len(selected), batch_size):
        batch = selected[batch_start:batch_start + batch_size]

        articles_text = "\n".join([
            f"- {a['article_number']} {a['title']}: {a['content'][:150]}"
            for a in batch
        ])

        prompt = f"""다음 산업안전보건법 조문들에 대해 각각 테스트용 시나리오를 작성해주세요.
시나리오는 해당 조문이 적용되는 실제 작업 현장 상황을 묘사해야 합니다.
조문 번호를 직접 언급하지 마세요. 일반인이 작업 현장을 관찰하고 보고하는 식으로 작성하세요.

조문 목록:
{articles_text}

JSON 배열로 응답하세요:
[
  {{
    "article_number": "제XX조",
    "scenario": "작업 현장 상황 묘사 (2~3문장, 한국어)",
    "workplace_type": "작업장 유형",
    "expected_hazard_types": ["위험유형1", "위험유형2"]
  }}
]"""

        try:
            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            if isinstance(data, dict) and "scenarios" in data:
                data = data["scenarios"]
            elif isinstance(data, dict) and "test_cases" in data:
                data = data["test_cases"]
            elif isinstance(data, dict):
                # Try to find any list value
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break

            for item in data:
                art_num = item.get("article_number", "")
                # Find matching article info
                art_info = next((a for a in batch if a["article_number"] == art_num), None)
                if art_info:
                    results.append({
                        "article_number": art_num,
                        "article_title": art_info["title"],
                        "chapter": art_info.get("chapter", ""),
                        "scenario": item["scenario"],
                        "workplace_type": item.get("workplace_type", "일반"),
                        "expected_hazard_types": item.get("expected_hazard_types", []),
                        "corner_case_type": random.choice(CORNER_TYPES_ARTICLES),
                    })

            print(f"  Generated {len(data)} article scenarios (batch {batch_start//batch_size + 1})")
        except Exception as e:
            print(f"  Error: {e}")

        time.sleep(1)

    return results


def generate_kosha_scenarios(guides: list[dict], count: int) -> list[dict]:
    """KOSHA 가이드 시나리오 생성"""
    selected = random.sample(guides, min(count, len(guides)))
    results = []

    batch_size = 10
    for batch_start in range(0, len(selected), batch_size):
        batch = selected[batch_start:batch_start + batch_size]

        guides_text = "\n".join([
            f"- {g['guide_code']} [{g['classification']}]: {g['title']}"
            for g in batch
        ])

        prompt = f"""다음 KOSHA GUIDE(안전보건기술지침)들에 대해 각각 테스트용 시나리오를 작성해주세요.
시나리오는 해당 가이드가 적용되는 실제 작업 현장 상황을 묘사해야 합니다.
가이드 코드나 가이드 제목을 직접 언급하지 마세요.

가이드 목록:
{guides_text}

JSON 배열로 응답하세요:
[
  {{
    "guide_code": "X-XX-XXXX",
    "scenario": "작업 현장 상황 묘사 (2~3문장, 한국어)",
    "workplace_type": "작업장 유형"
  }}
]"""

        try:
            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break

            for item in data:
                code = item.get("guide_code", "")
                guide_info = next((g for g in batch if g["guide_code"] == code), None)
                if guide_info:
                    results.append({
                        "guide_code": code,
                        "guide_title": guide_info["title"],
                        "classification": guide_info["classification"],
                        "scenario": item["scenario"],
                        "workplace_type": item.get("workplace_type", "일반"),
                        "expected_hazard_types": [],
                        "corner_case_type": random.choice(CORNER_TYPES_KOSHA),
                    })

            print(f"  Generated {len(data)} KOSHA scenarios (batch {batch_start//batch_size + 1})")
        except Exception as e:
            print(f"  Error: {e}")

        time.sleep(1)

    return results


def run_articles(extra_count: int):
    """법조항 테스트 확대"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    # Load existing test cases (use 100 if available, else 50)
    existing_path = DATA_DIR / "corner_test_articles_100.json"
    if not existing_path.exists():
        existing_path = DATA_DIR / "corner_test_articles_50.json"
    with open(existing_path) as f:
        existing = json.load(f)
    existing_nums = {tc["article_number"] for tc in existing["test_cases"]}
    print(f"Existing article test cases: {len(existing['test_cases'])}")
    print(f"Existing article numbers: {len(existing_nums)}")

    # Get all articles from DB (norm_statements table)
    engine = create_engine("sqlite:////app/data/ohs.db")
    with Session(engine) as session:
        rows = session.execute(text(
            "SELECT article_number, norm_category, "
            "GROUP_CONCAT(full_text, ' ') as content "
            "FROM norm_statements GROUP BY article_number"
        )).fetchall()

    available = [
        {"article_number": r[0], "title": r[1] or "", "chapter": "", "content": r[2] or ""}
        for r in rows
        if r[0] not in existing_nums
    ]
    random.shuffle(available)
    print(f"Available new articles: {len(available)}")

    # Generate new scenarios
    print(f"\nGenerating {extra_count} new article scenarios...")
    new_cases = generate_article_scenarios(available, extra_count)
    print(f"Generated {len(new_cases)} new scenarios")

    # Merge
    merged = {
        "description": f"법령 조문 코너케이스 테스트 ({len(existing['test_cases']) + len(new_cases)}개)",
        "test_cases": existing["test_cases"] + new_cases,
    }

    output_path = DATA_DIR / "corner_test_articles_100.json"
    with open(output_path, "w") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {output_path} ({len(merged['test_cases'])} total)")


def run_kosha(extra_count: int):
    """KOSHA 테스트 확대"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    existing_path = DATA_DIR / "corner_test_kosha_100.json"
    if not existing_path.exists():
        existing_path = DATA_DIR / "corner_test_kosha_50.json"
    with open(existing_path) as f:
        existing = json.load(f)
    existing_codes = {tc["guide_code"] for tc in existing["test_cases"]}
    print(f"Existing KOSHA test cases: {len(existing['test_cases'])}")

    engine = create_engine("sqlite:////app/data/ohs.db")
    with Session(engine) as session:
        rows = session.execute(text(
            "SELECT guide_code, classification, title FROM kosha_guides ORDER BY RANDOM()"
        )).fetchall()

    available = [
        {"guide_code": r[0], "classification": r[1], "title": r[2]}
        for r in rows
        if r[0] not in existing_codes
    ]

    # 분류별 균등 선택
    by_cls = {}
    for g in available:
        cls = g["classification"]
        by_cls.setdefault(cls, []).append(g)

    # 분류별로 골고루 선택
    selected = []
    per_cls = max(1, extra_count // len(by_cls))
    for cls, guides in sorted(by_cls.items()):
        n = min(per_cls, len(guides))
        selected.extend(random.sample(guides, n))

    # 부족분 채우기
    remaining = [g for g in available if g not in selected]
    if len(selected) < extra_count:
        extra = random.sample(remaining, min(extra_count - len(selected), len(remaining)))
        selected.extend(extra)
    selected = selected[:extra_count]

    print(f"Available new guides: {len(available)}")
    cls_counts = {}
    for g in selected:
        cls_counts[g["classification"]] = cls_counts.get(g["classification"], 0) + 1
    print(f"Selected by classification: {cls_counts}")

    print(f"\nGenerating {len(selected)} new KOSHA scenarios...")
    new_cases = generate_kosha_scenarios(selected, len(selected))
    print(f"Generated {len(new_cases)} new scenarios")

    merged = {
        "description": f"KOSHA GUIDE 코너케이스 테스트 ({len(existing['test_cases']) + len(new_cases)}개)",
        "test_cases": existing["test_cases"] + new_cases,
    }

    output_path = DATA_DIR / "corner_test_kosha_100.json"
    with open(output_path, "w") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {output_path} ({len(merged['test_cases'])} total)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    if mode in ("articles", "all"):
        run_articles(count)
    if mode in ("kosha", "all"):
        run_kosha(count + 1 if mode == "all" else count)
