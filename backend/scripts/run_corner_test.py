"""
코너케이스 대량 매칭 테스트 실행기
- 법령 조문 + KOSHA GUIDE 코너케이스 테스트
- Claude가 직접 작성한 시나리오 (OpenAI API 미사용)

Usage:
  python scripts/run_corner_test.py articles   # 법령 조문 50개
  python scripts/run_corner_test.py kosha       # KOSHA GUIDE 50개
  python scripts/run_corner_test.py all         # 전체 100개
"""
import json
import sys
import time
import requests
from pathlib import Path
from collections import defaultdict

API_BASE = "http://127.0.0.1:8000/api/v1"
DATA_DIR = Path(__file__).parent.parent / "data"


def run_analysis(scenario: str, workplace_type: str) -> dict:
    resp = requests.post(
        f"{API_BASE}/analysis/text",
        json={
            "description": scenario,
            "workplace_type": workplace_type,
            "industry_sector": "general",
        },
        timeout=120,
    )
    if resp.status_code != 200:
        return {"error": resp.status_code, "detail": resp.text[:200]}
    return resp.json()


def run_article_test(use_100=False):
    """법령 조문 코너케이스 테스트"""
    if use_100:
        test_path = DATA_DIR / "corner_test_articles_100.json"
        result_path = DATA_DIR / "corner_article_results_100.json"
    else:
        test_path = DATA_DIR / "corner_test_articles_50.json"
        result_path = DATA_DIR / "corner_article_results.json"

    with open(test_path, "r") as f:
        data = json.load(f)

    test_cases = data["test_cases"]
    total = len(test_cases)

    print("=" * 70)
    print(f"법령 조문 코너케이스 테스트 ({total}개)")
    print("=" * 70)

    results = []
    match_count = 0
    top5_count = 0

    # 코너케이스 유형별 통계
    type_stats = defaultdict(lambda: {"total": 0, "matched": 0})

    for i, tc in enumerate(test_cases):
        art_num = tc["article_number"]
        art_title = tc["article_title"]
        scenario = tc["scenario"]
        workplace = tc["workplace_type"]
        cc_type = tc.get("corner_case_type", "unknown")

        print(f"\n--- [{i+1}/{total}] {art_num} {art_title} [{cc_type}] ---")
        print(f"  시나리오: {scenario[:80]}...")

        type_stats[cc_type]["total"] += 1

        try:
            result = run_analysis(scenario, workplace)
            if "error" in result:
                print(f"  ❌ API 오류: {result}")
                results.append({**tc, "matched": False, "matched_articles": []})
                continue

            # 매칭된 조문 추출
            articles = set()
            for h in result.get("hazards", []):
                ref = h.get("legal_reference", "")
                if ref:
                    num = ref.split("(")[0].split(" ")[0].strip()
                    if num.startswith("제"):
                        articles.add(num)
            for n in result.get("norm_context", []):
                num = n.get("article_number", "")
                if num:
                    articles.add(num)

            matched_articles = sorted(articles, key=lambda x: int(''.join(filter(str.isdigit, x)) or "0"))
            is_matched = art_num in matched_articles

            norm_top5 = [n.get("article_number", "") for n in result.get("norm_context", [])][:5]
            in_top5 = art_num in norm_top5

            if is_matched:
                match_count += 1
                type_stats[cc_type]["matched"] += 1
                print(f"  ✅ 매칭 성공 (결과: {matched_articles[:5]})")
            else:
                print(f"  ❌ 매칭 실패 (기대: {art_num}, 결과: {matched_articles[:5]})")

            if in_top5:
                top5_count += 1

            results.append({
                **tc,
                "matched": is_matched,
                "in_top5_norms": in_top5,
                "matched_articles": matched_articles,
                "norm_top5": norm_top5,
                "hazard_count": len(result.get("hazards", [])),
            })

        except Exception as e:
            print(f"  ❌ 예외: {e}")
            results.append({**tc, "matched": False, "matched_articles": [], "error": str(e)})

        time.sleep(1)

    # 종합 결과
    print("\n" + "=" * 70)
    print("법령 조문 코너케이스 종합 결과")
    print("=" * 70)

    match_rate = match_count / total * 100
    top5_rate = top5_count / total * 100

    print(f"전체 매칭률: {match_count}/{total} = {match_rate:.1f}%")
    print(f"Top-5 Norm 매칭률: {top5_count}/{total} = {top5_rate:.1f}%")

    print(f"\n코너케이스 유형별 매칭률:")
    type_names = {
        "previously_failed": "기존 실패 재도전",
        "compound_risk": "복합 위험",
        "close_articles": "근접 조문 구별",
        "atypical_workplace": "비전형 작업환경",
        "administrative": "관리/행정 조항",
        "equipment_spec": "설비 규격",
        "rare_hazard": "드문 위험",
        "ambiguous": "모호한 표현",
    }
    for ctype, stats in sorted(type_stats.items()):
        rate = stats["matched"] / stats["total"] * 100 if stats["total"] > 0 else 0
        name = type_names.get(ctype, ctype)
        mark = "✅" if rate >= 75 else "⚠️" if rate >= 50 else "❌"
        print(f"  {mark} {name}: {stats['matched']}/{stats['total']} ({rate:.0f}%)")

    # 실패 목록
    failed = [r for r in results if not r["matched"]]
    if failed:
        print(f"\n미매칭 조문 ({len(failed)}건):")
        for f in failed:
            num = f["article_number"]
            title = f["article_title"]
            cc = f.get("corner_case_type", "")
            matched = f.get("matched_articles", [])[:3]
            print(f"  ❌ {num} {title} [{cc}] → 실제: {matched}")

    output = {
        "summary": {
            "total": total,
            "matched": match_count,
            "match_rate": round(match_rate, 1),
            "top5_match_rate": round(top5_rate, 1),
        },
        "results": results,
    }
    with open(result_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {result_path}")
    return match_rate


def run_kosha_test(use_100=False):
    """KOSHA GUIDE 코너케이스 테스트"""
    if use_100:
        test_path = DATA_DIR / "corner_test_kosha_100.json"
        result_path = DATA_DIR / "corner_kosha_results_100.json"
    else:
        test_path = DATA_DIR / "corner_test_kosha_50.json"
        result_path = DATA_DIR / "corner_kosha_results.json"

    with open(test_path, "r") as f:
        data = json.load(f)

    test_cases = data["test_cases"]
    total = len(test_cases)

    print("=" * 70)
    print(f"KOSHA GUIDE 코너케이스 테스트 ({total}개)")
    print("=" * 70)

    results = []
    exact_match = 0
    class_match = 0

    type_stats = defaultdict(lambda: {"total": 0, "exact": 0, "class": 0})
    cls_stats = defaultdict(lambda: {"total": 0, "exact": 0, "class": 0})

    for i, tc in enumerate(test_cases):
        code = tc["guide_code"]
        title = tc["guide_title"]
        scenario = tc["scenario"]
        workplace = tc["workplace_type"]
        expected_cls = code.split("-")[0]
        cc_type = tc.get("corner_case_type", "unknown")

        print(f"\n--- [{i+1}/{total}] {code}: {title[:40]} [{cc_type}] ---")
        print(f"  시나리오: {scenario[:70]}...")

        type_stats[cc_type]["total"] += 1
        cls_stats[expected_cls]["total"] += 1

        try:
            result = run_analysis(scenario, workplace)
            if "error" in result:
                print(f"  ❌ API 오류: {result}")
                results.append({**tc, "exact_match": False, "class_match": False, "matched_guides": []})
                continue

            matched_codes = [g.get("guide_code", "") for g in result.get("related_guides", []) if g.get("guide_code")]
            matched_classes = sorted(set(c.split("-")[0] for c in matched_codes))

            is_exact = code in matched_codes
            is_class = expected_cls in matched_classes

            if is_exact:
                exact_match += 1
                type_stats[cc_type]["exact"] += 1
                cls_stats[expected_cls]["exact"] += 1
                print(f"  ✅ 정확 매칭! (결과: {matched_codes[:3]})")
            elif is_class:
                class_match += 1
                type_stats[cc_type]["class"] += 1
                cls_stats[expected_cls]["class"] += 1
                print(f"  ⚠️ 분류 매칭 (기대: {code}, 결과: {matched_codes[:3]})")
            else:
                print(f"  ❌ 미매칭 (기대: {code}[{expected_cls}], 결과: {matched_codes[:3]})")

            guide_titles = [f"{g.get('guide_code')}: {g.get('title', '')[:30]}" for g in result.get("related_guides", [])[:2]]
            if guide_titles:
                print(f"  KOSHA: {guide_titles}")

            results.append({
                **tc,
                "exact_match": is_exact,
                "class_match": is_class,
                "matched_guides": matched_codes,
                "matched_classifications": matched_classes,
            })

        except Exception as e:
            print(f"  ❌ 예외: {e}")
            results.append({**tc, "exact_match": False, "class_match": False, "matched_guides": [], "error": str(e)})

        time.sleep(1)

    # 종합 결과
    print("\n" + "=" * 70)
    print("KOSHA GUIDE 코너케이스 종합 결과")
    print("=" * 70)

    exact_rate = exact_match / total * 100
    class_rate = (exact_match + class_match) / total * 100

    print(f"정확 매칭률: {exact_match}/{total} = {exact_rate:.1f}%")
    print(f"분류 매칭률: {exact_match + class_match}/{total} = {class_rate:.1f}%")

    print(f"\n코너케이스 유형별:")
    type_names = {
        "E_weak": "E분류 집중",
        "G_weak": "G분류 집중",
        "H_weak": "H분류 집중",
        "B_exact": "B분류 정확매칭",
        "M_exact": "M분류 정확매칭",
        "others": "기타 분류",
    }
    for ctype, stats in sorted(type_stats.items()):
        exact_r = stats["exact"] / stats["total"] * 100 if stats["total"] > 0 else 0
        class_r = (stats["exact"] + stats["class"]) / stats["total"] * 100 if stats["total"] > 0 else 0
        name = type_names.get(ctype, ctype)
        mark = "✅" if exact_r >= 50 else "⚠️" if class_r >= 50 else "❌"
        print(f"  {mark} {name}: 정확 {stats['exact']}/{stats['total']} ({exact_r:.0f}%), 분류 {stats['exact']+stats['class']}/{stats['total']} ({class_r:.0f}%)")

    print(f"\n분류별:")
    for cls, stats in sorted(cls_stats.items()):
        exact_r = stats["exact"] / stats["total"] * 100 if stats["total"] > 0 else 0
        class_r = (stats["exact"] + stats["class"]) / stats["total"] * 100 if stats["total"] > 0 else 0
        mark = "✅" if exact_r >= 50 else "⚠️" if class_r >= 50 else "❌"
        print(f"  {mark} {cls}: 정확 {stats['exact']}/{stats['total']} ({exact_r:.0f}%), 분류 {stats['exact']+stats['class']}/{stats['total']} ({class_r:.0f}%)")

    output = {
        "summary": {
            "total": total,
            "exact_match": exact_match,
            "exact_match_rate": round(exact_rate, 1),
            "class_match": exact_match + class_match,
            "class_match_rate": round(class_rate, 1),
        },
        "results": results,
    }
    with open(result_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {result_path}")
    return exact_rate


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    use_100 = "--100" in sys.argv or "100" in sys.argv

    if mode in ("articles", "all"):
        art_rate = run_article_test(use_100=use_100)

    if mode in ("kosha", "all"):
        if mode == "all":
            print("\n\n" + "🔄" * 35 + "\n")
        kosha_rate = run_kosha_test(use_100=use_100)

    if mode == "all":
        print("\n" + "=" * 70)
        print("전체 코너케이스 종합")
        print("=" * 70)
        print(f"법령 조문: {art_rate:.1f}%")
        print(f"KOSHA GUIDE 정확: {kosha_rate:.1f}%")
