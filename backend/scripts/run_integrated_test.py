"""
통합 매칭 테스트 — 법령 + KOSHA GUIDE + 숏폼영상
- 기존 100개 법령 코너테스트 시나리오 활용
- 각 시나리오별 법조항 매칭 정확도 + KOSHA GUIDE 관련성 + 숏폼 영상 관련성 검증

Usage:
  python scripts/run_integrated_test.py           # 전체 100건
  python scripts/run_integrated_test.py --limit 10  # 10건만
"""
import json
import sys
import time
import requests
from pathlib import Path
from collections import Counter, defaultdict

API_BASE = "http://127.0.0.1:8000/api/v1"
DATA_DIR = Path(__file__).parent.parent / "data"

# hazard_code → 한글 매핑
HAZARD_CODE_KR = {
    "FALL": "추락", "SLIP": "미끄러짐", "COLLISION": "충돌", "CRUSH": "끼임",
    "CUT": "절단", "FALLING_OBJECT": "낙하물", "CHEMICAL": "화학물질",
    "FIRE_EXPLOSION": "화재폭발", "TOXIC": "중독질식", "CORROSION": "부식",
    "ELECTRIC": "감전", "ARC_FLASH": "아크플래시", "ERGONOMIC": "인간공학",
    "REPETITIVE": "반복작업", "HEAVY_LIFTING": "중량물", "POSTURE": "자세",
    "NOISE": "소음", "TEMPERATURE": "온열", "LIGHTING": "조명",
    "ENVIRONMENTAL": "환경위험", "BIOLOGICAL": "생물학적",
}

# 위험유형 → 관련 hazard_code 매핑 (영상 평가용)
# 키워드 포함 매칭: expected_hazard_type 문자열에 키가 포함되면 매칭
HAZARD_TYPE_TO_CODES = {
    # 물리적 위험
    "추락": ["FALL", "FALLING_OBJECT"],
    "미끄러짐": ["SLIP", "FALL"],
    "넘어짐": ["SLIP", "FALL"],
    "끼임": ["CRUSH"],
    "협착": ["CRUSH"],
    "절단": ["CUT"],
    "충돌": ["COLLISION"],
    "부딪힘": ["COLLISION"],
    "낙하": ["FALLING_OBJECT", "FALL"],
    "낙하물": ["FALLING_OBJECT", "FALL"],
    "붕괴": ["FALLING_OBJECT", "FALL", "CRUSH"],
    "매몰": ["FALLING_OBJECT", "CRUSH", "ENVIRONMENTAL"],
    "전도": ["COLLISION", "CRUSH"],
    "비산물": ["COLLISION", "FALLING_OBJECT"],
    "파손": ["COLLISION", "FALLING_OBJECT"],
    "말림": ["CRUSH", "CUT"],
    # 전기적 위험
    "감전": ["ELECTRIC", "ARC_FLASH"],
    "전기": ["ELECTRIC", "ARC_FLASH"],
    "누전": ["ELECTRIC"],
    "아크": ["ARC_FLASH", "ELECTRIC"],
    # 화학적 위험
    "화재": ["FIRE_EXPLOSION"],
    "폭발": ["FIRE_EXPLOSION"],
    "화상": ["FIRE_EXPLOSION", "TEMPERATURE"],
    "고온": ["TEMPERATURE", "FIRE_EXPLOSION"],
    "화학물질": ["CHEMICAL", "TOXIC"],
    "유해물질": ["CHEMICAL", "TOXIC"],
    "유해가스": ["TOXIC", "ENVIRONMENTAL", "CHEMICAL", "FIRE_EXPLOSION"],
    "중독": ["TOXIC", "CHEMICAL"],
    "질식": ["TOXIC", "ENVIRONMENTAL", "CHEMICAL"],
    "밀폐공간": ["TOXIC", "ENVIRONMENTAL"],
    "분진": ["ENVIRONMENTAL", "CHEMICAL"],
    "석면": ["CHEMICAL", "ENVIRONMENTAL"],
    "발암": ["CHEMICAL", "TOXIC"],
    "부식": ["CORROSION", "CHEMICAL"],
    "피부": ["CHEMICAL", "CORROSION"],
    "흡입": ["TOXIC", "ENVIRONMENTAL", "CHEMICAL"],
    "누출": ["CHEMICAL", "TOXIC"],
    "오염": ["CHEMICAL", "ENVIRONMENTAL"],
    "중금속": ["CHEMICAL", "TOXIC"],
    # 인간공학적 위험
    "근골격계": ["ERGONOMIC", "REPETITIVE", "HEAVY_LIFTING", "POSTURE"],
    "요통": ["ERGONOMIC", "HEAVY_LIFTING", "POSTURE"],
    "자세": ["POSTURE", "ERGONOMIC"],
    "반복": ["REPETITIVE", "ERGONOMIC"],
    "중량물": ["HEAVY_LIFTING"],
    "부상": ["ERGONOMIC", "COLLISION"],
    # 환경적 위험
    "소음": ["NOISE"],
    "난청": ["NOISE"],
    "청력": ["NOISE"],
    "온열": ["TEMPERATURE"],
    "환기": ["ENVIRONMENTAL", "TOXIC"],
    "조명": ["LIGHTING"],
    "시력": ["LIGHTING", "ERGONOMIC"],
    "눈의 피로": ["LIGHTING", "ERGONOMIC"],
    "VDT": ["ERGONOMIC", "LIGHTING"],
    # 생물학적 위험
    "감염": ["BIOLOGICAL"],
    "병원체": ["BIOLOGICAL"],
    # 기타
    "방사": ["ENVIRONMENTAL"],
    "트라우마": ["ERGONOMIC"],
    "가스": ["TOXIC", "ENVIRONMENTAL", "FIRE_EXPLOSION"],
    "압축": ["FIRE_EXPLOSION", "ENVIRONMENTAL"],
    "감압": ["ENVIRONMENTAL"],
    "기계": ["CRUSH", "CUT"],
    "신체": ["CRUSH", "CUT"],
    "안전수칙": [],  # 일반적 - 코드 없음
    "두부": ["FALLING_OBJECT", "COLLISION"],
    "발 손상": ["CRUSH", "COLLISION"],
    "발에": ["CRUSH", "COLLISION"],
    "산소결핍": ["TOXIC", "ENVIRONMENTAL"],
    "호흡기": ["TOXIC", "ENVIRONMENTAL", "CHEMICAL"],
    "진폐": ["ENVIRONMENTAL", "CHEMICAL"],
    "결핍": ["TOXIC", "ENVIRONMENTAL"],
}


def _resolve_expected_codes(expected_hazard_types: list) -> set:
    """expected_hazard_types 리스트 → 관련 hazard_codes set 변환.
    정확 매칭 우선, 없으면 부분 문자열(키 포함) 매칭."""
    codes = set()
    for ht in expected_hazard_types:
        # 정확 매칭
        if ht in HAZARD_TYPE_TO_CODES:
            codes.update(HAZARD_TYPE_TO_CODES[ht])
            continue
        # 부분 문자열 매칭: ht에 키워드가 포함되어 있으면
        for key, key_codes in HAZARD_TYPE_TO_CODES.items():
            if key in ht:
                codes.update(key_codes)
    return codes


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


def evaluate_article_match(result: dict, expected_article: str) -> dict:
    """법조항 매칭 평가"""
    import re
    num_match = re.search(r'(\d+)', expected_article)
    expected_num = num_match.group(1) if num_match else ""

    norm_context = result.get("norm_context", [])
    matched_articles = [nc.get("article_number", "") for nc in norm_context]

    found = False
    rank = -1
    for i, art in enumerate(matched_articles):
        if expected_num and expected_num in art:
            found = True
            rank = i + 1
            break

    return {
        "found": found,
        "rank": rank,
        "total_articles": len(matched_articles),
        "top3": matched_articles[:3],
    }


def evaluate_guide_match(result: dict, expected_hazard_types: list) -> dict:
    """KOSHA GUIDE 매칭 평가"""
    related_guides = result.get("related_guides", [])
    guide_count = len(related_guides)
    guide_codes = [g.get("guide_code", "") for g in related_guides]

    return {
        "count": guide_count,
        "top3": guide_codes[:3],
        "has_guides": guide_count > 0,
    }


def evaluate_video_match(result: dict, expected_hazard_types: list) -> dict:
    """숏폼 영상 매칭 평가 (v2: 서브카테고리 직접 매칭)
    - 영상 0건 = "correct_empty" (매칭할 영상 없으면 안 보여주는 게 정답)
    - 영상 있으면 relevant 비율로 good/partial/poor 판정
    """
    resources = result.get("resources", [])
    videos = [r for r in resources if r.get("type") == "video"]
    video_count = len(videos)

    if video_count == 0:
        return {"count": 0, "relevance": "correct_empty", "score": 1.0, "details": []}

    # 기대 hazard_code 추출 (확장 매핑)
    expected_codes = _resolve_expected_codes(expected_hazard_types)

    relevant_count = 0
    details = []
    for v in videos:
        v_codes = set(v.get("hazard_categories", []))
        overlap = v_codes & expected_codes
        is_relevant = len(overlap) > 0
        if is_relevant:
            relevant_count += 1
        details.append({
            "title": v.get("title", "")[:40],
            "codes": list(v_codes),
            "relevant": is_relevant,
        })

    relevance_ratio = relevant_count / video_count if video_count > 0 else 0
    if relevance_ratio >= 0.6:
        relevance = "good"
    elif relevance_ratio >= 0.3:
        relevance = "partial"
    else:
        relevance = "poor"

    return {
        "count": video_count,
        "relevant_count": relevant_count,
        "relevance": relevance,
        "score": relevance_ratio,
        "details": details,
    }


def main():
    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    test_path = DATA_DIR / "corner_test_articles_100.json"
    with open(test_path, "r") as f:
        data = json.load(f)

    test_cases = data["test_cases"]
    if limit:
        test_cases = test_cases[:limit]

    total = len(test_cases)
    print(f"=== 통합 매칭 테스트 ({total}건) ===\n")

    # 결과 수집
    article_results = {"found": 0, "not_found": 0, "errors": 0}
    guide_results = {"has_guides": 0, "no_guides": 0}
    video_results = {"good": 0, "partial": 0, "poor": 0, "correct_empty": 0}
    video_code_coverage = Counter()
    failed_cases = []
    all_results = []

    for i, tc in enumerate(test_cases):
        scenario = tc["scenario"]
        expected_article = tc["article_number"]
        expected_hazards = tc.get("expected_hazard_types", [])
        workplace = tc.get("workplace_type", "일반")

        print(f"[{i+1}/{total}] {expected_article} ({tc.get('article_title','')})")
        sys.stdout.flush()

        try:
            result = run_analysis(scenario, workplace)
        except Exception as e:
            print(f"  ERROR: {e}")
            article_results["errors"] += 1
            continue

        if "error" in result:
            print(f"  API ERROR: {result['error']}")
            article_results["errors"] += 1
            continue

        # 평가
        art_eval = evaluate_article_match(result, expected_article)
        guide_eval = evaluate_guide_match(result, expected_hazards)
        video_eval = evaluate_video_match(result, expected_hazards)

        # 법조항
        if art_eval["found"]:
            article_results["found"] += 1
            art_status = f"✓ (#{art_eval['rank']})"
        else:
            article_results["not_found"] += 1
            art_status = f"✗ (got: {art_eval['top3']})"
            failed_cases.append({
                "article": expected_article,
                "title": tc.get("article_title", ""),
                "scenario": scenario[:60],
                "got": art_eval["top3"],
            })

        # KOSHA GUIDE
        if guide_eval["has_guides"]:
            guide_results["has_guides"] += 1
        else:
            guide_results["no_guides"] += 1

        # 영상
        video_results[video_eval["relevance"]] += 1
        for v in video_eval["details"]:
            for c in v["codes"]:
                video_code_coverage[c] += 1

        # 영상 상세 출력 (문제 있는 경우만)
        video_status = f"{video_eval['count']}건/{video_eval['relevance']}"
        if video_eval["relevance"] == "poor" and video_eval["count"] > 0:
            poor_titles = [d["title"] for d in video_eval["details"] if not d["relevant"]]
            print(f"  법조항={art_status} | GUIDE={guide_eval['count']}건 | 영상={video_status}")
            print(f"  ⚠ 무관 영상: {poor_titles[:2]}")
        else:
            print(f"  법조항={art_status} | GUIDE={guide_eval['count']}건 | 영상={video_status}")

        all_results.append({
            "article": expected_article,
            "article_match": art_eval,
            "guide_match": guide_eval,
            "video_match": video_eval,
        })

        time.sleep(0.3)

    # ── 최종 요약 ──
    tested = total - article_results["errors"]
    print(f"\n{'='*60}")
    print(f"=== 테스트 결과 요약 ({tested}/{total}건 완료) ===")
    print(f"{'='*60}")

    # 법조항
    art_acc = article_results["found"] / tested * 100 if tested > 0 else 0
    print(f"\n📋 법조항 매칭: {article_results['found']}/{tested} ({art_acc:.1f}%)")
    if failed_cases:
        print(f"  미매칭 {len(failed_cases)}건:")
        for fc in failed_cases[:5]:
            print(f"    - {fc['article']} ({fc['title'][:20]}) → got: {fc['got']}")

    # KOSHA GUIDE
    guide_pct = guide_results["has_guides"] / tested * 100 if tested > 0 else 0
    print(f"\n📚 KOSHA GUIDE 연계: {guide_results['has_guides']}/{tested} ({guide_pct:.1f}%)")

    # 숏폼 영상
    good_n = video_results["good"]
    partial_n = video_results["partial"]
    poor_n = video_results["poor"]
    empty_n = video_results["correct_empty"]
    correct_n = good_n + partial_n + empty_n  # 적중 = good + partial + 정상빈칸
    video_accuracy = correct_n / tested * 100 if tested > 0 else 0
    print(f"\n🎬 숏폼 영상 매칭 (정확도: {correct_n}/{tested} = {video_accuracy:.1f}%):")
    print(f"  좋음(60%↑):  {good_n}건")
    print(f"  부분(30%↑):  {partial_n}건")
    print(f"  미흡(<30%):  {poor_n}건 (오매칭)")
    print(f"  정상빈칸:    {empty_n}건 (매칭영상 없어서 안 보여줌 = 정답)")

    # 영상 코드 분포
    print(f"\n🏷️ 매칭된 영상 hazard_code 분포:")
    for code, cnt in video_code_coverage.most_common(10):
        kr = HAZARD_CODE_KR.get(code, code)
        print(f"  {kr}({code}): {cnt}건")

    # 결과 저장
    output_path = DATA_DIR / "integrated_test_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "summary": {
                "total": total,
                "tested": tested,
                "article_accuracy": art_acc,
                "guide_coverage": guide_pct,
                "video_accuracy": video_accuracy,
                "video_good": good_n,
                "video_partial": partial_n,
                "video_poor": poor_n,
                "video_correct_empty": empty_n,
            },
            "failed_articles": failed_cases,
            "video_code_distribution": dict(video_code_coverage.most_common()),
            "details": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
