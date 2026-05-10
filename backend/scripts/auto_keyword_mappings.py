"""
실패한 테스트 케이스에서 자동으로 키워드 매핑을 생성
- 시나리오 텍스트에서 핵심 키워드/phrases를 추출
- 기존 keyword_mappings.json에 병합

Usage:
  python scripts/auto_keyword_mappings.py
"""
import json
import re
from pathlib import Path
from openai import OpenAI

DATA_DIR = Path(__file__).parent.parent / "data"
client = OpenAI()


def extract_keywords_with_gpt(items: list[dict], item_type: str) -> list[dict]:
    """GPT를 이용해 실패 케이스에서 키워드/phrases 추출"""
    results = []
    batch_size = 15

    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start:batch_start + batch_size]

        if item_type == "article":
            items_text = "\n".join([
                f"- {it['article_number']} ({it.get('article_title','')}) 시나리오: {it['scenario'][:150]}"
                for it in batch
            ])
            prompt = f"""다음 산업안전보건법 조문들의 시나리오에서 해당 조문을 식별하는 데 핵심적인 키워드와 phrases를 추출하세요.
키워드는 2~4글자의 핵심 단어, phrases는 4~10글자의 정확한 구문입니다.

{items_text}

JSON 배열로 응답하세요:
[
  {{
    "article_number": "제XX조",
    "title": "조문 제목 (짧게)",
    "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
    "phrases": ["정확한 구문1", "정확한 구문2", "정확한 구문3"]
  }}
]"""
        else:  # kosha
            items_text = "\n".join([
                f"- {it['guide_code']} [{it.get('classification','')}] ({it.get('guide_title','')[:40]}) 시나리오: {it['scenario'][:150]}"
                for it in batch
            ])
            prompt = f"""다음 KOSHA GUIDE들의 시나리오에서 해당 가이드를 식별하는 데 핵심적인 키워드와 phrases를 추출하세요.
키워드는 2~4글자의 핵심 단어, phrases는 4~15글자의 정확한 구문입니다.

{items_text}

JSON 배열로 응답하세요:
[
  {{
    "guide_code": "X-XX-XXXX",
    "title": "가이드 제목 (짧게)",
    "classification": "분류코드",
    "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
    "phrases": ["정확한 구문1", "정확한 구문2", "정확한 구문3"]
  }}
]"""

        try:
            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break
            if isinstance(data, list):
                results.extend(data)
            print(f"  Extracted {len(data)} entries (batch {batch_start//batch_size + 1})")
        except Exception as e:
            print(f"  Error: {e}")

    return results


def main():
    mappings_path = DATA_DIR / "keyword_mappings.json"
    with open(mappings_path) as f:
        mappings = json.load(f)

    # ═══ 법조항 실패 분석 ═══
    art_results_path = DATA_DIR / "corner_article_results_100.json"
    if art_results_path.exists():
        with open(art_results_path) as f:
            art_data = json.load(f)

        art_failed = [r for r in art_data["results"] if not r["matched"]]
        existing_art_keys = set(mappings.get("article_keywords", {}).keys())
        new_art_failed = [r for r in art_failed if r["article_number"] not in existing_art_keys]

        print(f"법조항 실패: {len(art_failed)}건, 기존 매핑 없는 것: {len(new_art_failed)}건")

        if new_art_failed:
            print("법조항 키워드 추출 중...")
            art_kw = extract_keywords_with_gpt(new_art_failed, "article")

            added = 0
            for entry in art_kw:
                num = entry.get("article_number", "")
                if num and num not in mappings.get("article_keywords", {}):
                    mappings.setdefault("article_keywords", {})[num] = {
                        "title": entry.get("title", ""),
                        "keywords": entry.get("keywords", []),
                        "phrases": entry.get("phrases", []),
                    }
                    added += 1
            print(f"법조항 매핑 추가: {added}건")

    # ═══ KOSHA 실패 분석 ═══
    kosha_results_path = DATA_DIR / "corner_kosha_results_100.json"
    if kosha_results_path.exists():
        with open(kosha_results_path) as f:
            kosha_data = json.load(f)

        kosha_failed = [r for r in kosha_data["results"] if not r.get("exact_match")]
        existing_guide_keys = set(mappings.get("guide_keywords", {}).keys())
        new_kosha_failed = [r for r in kosha_failed if r["guide_code"] not in existing_guide_keys]

        print(f"\nKOSHA 실패: {len(kosha_failed)}건, 기존 매핑 없는 것: {len(new_kosha_failed)}건")

        if new_kosha_failed:
            print("KOSHA 키워드 추출 중...")
            guide_kw = extract_keywords_with_gpt(new_kosha_failed, "kosha")

            added = 0
            for entry in guide_kw:
                code = entry.get("guide_code", "")
                if code and code not in mappings.get("guide_keywords", {}):
                    mappings.setdefault("guide_keywords", {})[code] = {
                        "title": entry.get("title", ""),
                        "keywords": entry.get("keywords", []),
                        "phrases": entry.get("phrases", []),
                        "classification": entry.get("classification", ""),
                    }
                    added += 1
            print(f"KOSHA 매핑 추가: {added}건")

    # 저장
    with open(mappings_path, "w") as f:
        json.dump(mappings, f, ensure_ascii=False, indent=2)
    print(f"\n총 article 매핑: {len(mappings.get('article_keywords', {}))}건")
    print(f"총 guide 매핑: {len(mappings.get('guide_keywords', {}))}건")
    print(f"저장 완료: {mappings_path}")


if __name__ == "__main__":
    main()
