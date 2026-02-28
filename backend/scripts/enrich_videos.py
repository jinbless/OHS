"""GPT로 safety_videos.json 메타데이터 보강 스크립트

- hazard_codes: 21개 세부코드로 재분류
- description: 한글 설명 생성
- is_safety: 산업안전 관련 여부 판별 (비안전 영상 필터링용)
"""
import json
import os
import sys
import time
from pathlib import Path
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

DATA_PATH = Path(__file__).parent.parent / "app" / "data" / "safety_videos.json"

HAZARD_CODES = {
    "FALL": "추락 (높은 곳에서 떨어짐)",
    "SLIP": "미끄러짐/넘어짐",
    "COLLISION": "충돌/부딪힘",
    "CRUSH": "끼임/협착",
    "CUT": "절단/베임",
    "FALLING_OBJECT": "낙하물/떨어지는 물체",
    "CHEMICAL": "화학물질 노출/누출",
    "FIRE_EXPLOSION": "화재/폭발",
    "TOXIC": "중독/유해가스/질식",
    "CORROSION": "부식성 물질",
    "ELECTRIC": "감전/전기사고",
    "ARC_FLASH": "아크 플래시",
    "ERGONOMIC": "인간공학적 위험 (일반)",
    "REPETITIVE": "반복작업",
    "HEAVY_LIFTING": "중량물 취급",
    "POSTURE": "부적절한 자세",
    "NOISE": "소음",
    "TEMPERATURE": "온도(고온/저온/온열질환)",
    "LIGHTING": "조명/시야",
    "ENVIRONMENTAL": "환경적 위험 (밀폐공간/분진 등)",
    "BIOLOGICAL": "생물학적 위험 (감염/병원체)",
}

SYSTEM_PROMPT = f"""당신은 산업안전보건 전문가입니다. YouTube Shorts 안전교육 영상의 메타데이터를 분석합니다.

## 작업
각 영상에 대해 다음을 판단하세요:

1. **is_safety** (boolean): 이 영상이 산업안전보건 교육/홍보와 직접 관련이 있는가?
   - true: 산재예방, 위험작업 안전, 보호구, 재해사례, 안전법규, 유해물질, 건설안전 등
   - false: 단순 홍보/캠페인(응원캠페인), 기관 소개, 이벤트, 일반 상식, 산안 무관 콘텐츠

2. **hazard_codes** (string[]): 해당 영상이 다루는 위험 유형. 아래 21개 코드에서 선택 (1~3개).
   is_safety=false이면 빈 배열.

{json.dumps(HAZARD_CODES, ensure_ascii=False, indent=2)}

3. **description** (string): 영상 내용을 한국어 1문장으로 요약 (20~50자).
   is_safety=false이면 빈 문자열.

## 응답 형식
JSON 배열로 응답. 각 항목: {{"id": <int>, "is_safety": <bool>, "hazard_codes": [...], "description": "..."}}
반드시 입력된 모든 영상에 대해 응답하세요. JSON만 출력하세요.
"""

BATCH_SIZE = 30


def enrich_batch(videos_batch: list[dict]) -> list[dict]:
    """GPT-4.1-mini로 배치 처리"""
    # 필요한 정보만 전달
    input_data = []
    for v in videos_batch:
        input_data.append({
            "id": v["id"],
            "title": v["title"],
            "category": v["category"],
            "tags": v.get("tags", []),
        })

    user_msg = json.dumps(input_data, ensure_ascii=False)

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content
    parsed = json.loads(content)

    # response_format=json_object일 때 배열이 아닌 객체로 올 수 있음
    if isinstance(parsed, dict):
        # {"results": [...]} 또는 {"videos": [...]} 형태
        for key in ("results", "videos", "data", "items"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        # 키가 하나뿐이면 그 값 사용
        if len(parsed) == 1:
            val = list(parsed.values())[0]
            if isinstance(val, list):
                return val
        raise ValueError(f"Unexpected response structure: {list(parsed.keys())}")

    return parsed


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    videos = data["videos"]
    total = len(videos)
    print(f"총 {total}개 영상 처리 시작")

    all_results = {}  # id → result

    for i in range(0, total, BATCH_SIZE):
        batch = videos[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n[배치 {batch_num}/{total_batches}] {len(batch)}개 처리 중...")

        try:
            results = enrich_batch(batch)
            for r in results:
                all_results[r["id"]] = r
            print(f"  완료: {len(results)}개 응답")

            # 결과 요약
            safety_count = sum(1 for r in results if r.get("is_safety"))
            non_safety = [r for r in results if not r.get("is_safety")]
            if non_safety:
                print(f"  비안전 영상 {len(non_safety)}건:")
                for r in non_safety:
                    v = next((v for v in batch if v["id"] == r["id"]), None)
                    if v:
                        print(f"    - [{v['category']}] {v['title'][:40]}")

        except Exception as e:
            print(f"  ERROR: {e}")
            # 실패한 배치는 개별 처리 시도하지 않고 스킵
            continue

        time.sleep(0.5)  # rate limit 방지

    # 결과 병합
    print(f"\n=== 결과 병합 ===")
    enriched_videos = []
    removed_count = 0
    kept_count = 0

    for v in videos:
        result = all_results.get(v["id"])
        if not result:
            # GPT 응답 누락 → 기존 데이터 유지
            enriched_videos.append(v)
            kept_count += 1
            continue

        if not result.get("is_safety", True):
            removed_count += 1
            continue

        # 보강된 데이터 병합
        v["hazard_codes"] = result.get("hazard_codes", [])
        v["description"] = result.get("description", "")
        # 기존 hazard_categories는 유지 (호환성)
        enriched_videos.append(v)
        kept_count += 1

    data["videos"] = enriched_videos
    data["total"] = len(enriched_videos)

    # 백업 후 저장
    backup_path = DATA_PATH.with_suffix(".json.bak")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(json.loads(open(DATA_PATH).read()), f, ensure_ascii=False, indent=2)
    print(f"백업: {backup_path}")

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n=== 완료 ===")
    print(f"유지: {kept_count}건")
    print(f"제거: {removed_count}건")
    print(f"최종: {len(enriched_videos)}건")

    # hazard_codes 분포
    from collections import Counter
    code_counter = Counter()
    for v in enriched_videos:
        for c in v.get("hazard_codes", []):
            code_counter[c] += 1
    print(f"\n=== hazard_codes 분포 ===")
    for k, cnt in code_counter.most_common():
        print(f"  {k}: {cnt}건")


if __name__ == "__main__":
    main()
