"""GPT로 KOSHA 유튜브 일반 교육영상 메타데이터 보강 스크립트

- 크롤링한 재해사례 + 안전보건 교육자료 710건 처리
- hazard_codes, description, is_safety 태깅
- safety_videos.json에 병합
"""
import json
import os
import sys
import time
from pathlib import Path
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

INPUT_PATH = Path("/app/data/kosha_youtube_playlists.json")
OUTPUT_PATH = Path(__file__).parent.parent / "app" / "data" / "safety_videos.json"

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

SYSTEM_PROMPT = f"""당신은 산업안전보건 전문가입니다. YouTube 산업안전 교육영상의 메타데이터를 분석합니다.

## 작업
각 영상에 대해 다음을 판단하세요:

1. **is_safety** (boolean): 이 영상이 산업안전보건 교육/홍보와 직접 관련이 있는가?
   - true: 산재예방, 위험작업 안전, 보호구, 재해사례, 안전법규, 유해물질, 건설안전, 특별교육 등
   - false: 단순 홍보/캠페인(응원캠페인), 기관 소개, 이벤트/콘서트, 일반 상식, 산안 무관 콘텐츠

2. **hazard_codes** (string[]): 해당 영상이 다루는 위험 유형. 아래 21개 코드에서 선택 (1~3개).
   is_safety=false이면 빈 배열.

{json.dumps(HAZARD_CODES, ensure_ascii=False, indent=2)}

3. **description** (string): 영상 내용을 한국어 1문장으로 요약 (20~50자).
   is_safety=false이면 빈 문자열.

## 응답 형식
JSON 배열로 응답. 각 항목: {{"idx": <int>, "is_safety": <bool>, "hazard_codes": [...], "description": "..."}}
반드시 입력된 모든 영상에 대해 응답하세요. JSON만 출력하세요.
"""

BATCH_SIZE = 40


def enrich_batch(batch: list[dict]) -> list[dict]:
    """GPT-4.1-mini로 배치 처리"""
    input_data = []
    for v in batch:
        input_data.append({
            "idx": v["idx"],
            "title": v["title"],
            "playlist": v["playlist"],
            "duration": v.get("duration", ""),
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

    if isinstance(parsed, dict):
        for key in ("results", "videos", "data", "items"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        if len(parsed) == 1:
            val = list(parsed.values())[0]
            if isinstance(val, list):
                return val
        raise ValueError(f"Unexpected response structure: {list(parsed.keys())}")

    return parsed


def main():
    # 입력 데이터 로드
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        playlists_data = json.load(f)

    # 재해사례 + 안전보건 교육자료만 처리
    target_playlists = ["재해사례", "안전보건 교육자료"]
    all_videos = []
    idx = 0
    for pname in target_playlists:
        pdata = playlists_data.get(pname, {})
        for v in pdata.get("videos", []):
            all_videos.append({
                "idx": idx,
                "video_id": v["video_id"],
                "title": v["title"],
                "duration": v.get("duration", ""),
                "url": v["url"],
                "playlist": pname,
            })
            idx += 1

    total = len(all_videos)
    print(f"총 {total}개 영상 처리 시작")

    all_results = {}  # idx → result

    for i in range(0, total, BATCH_SIZE):
        batch = all_videos[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n[배치 {batch_num}/{total_batches}] {len(batch)}개 처리 중...")

        try:
            results = enrich_batch(batch)
            for r in results:
                all_results[r["idx"]] = r
            safety_count = sum(1 for r in results if r.get("is_safety"))
            print(f"  완료: {len(results)}개 응답 (안전관련: {safety_count}건)")
        except Exception as e:
            print(f"  ERROR: {e}")
            # 실패 시 개별 재시도
            for v in batch:
                try:
                    results = enrich_batch([v])
                    for r in results:
                        all_results[r["idx"]] = r
                except Exception as e2:
                    print(f"    개별 실패 [{v['idx']}] {v['title'][:30]}: {e2}")

        time.sleep(0.3)

    # 기존 safety_videos.json 로드
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        existing_data = json.load(f)

    existing_videos = existing_data.get("videos", [])
    existing_urls = {v["url"] for v in existing_videos}
    max_id = max((v.get("id", 0) for v in existing_videos), default=0)

    # 새 영상 추가
    added = 0
    skipped_nonsafety = 0
    skipped_dup = 0
    skipped_noresult = 0

    for v in all_videos:
        if v["url"] in existing_urls:
            skipped_dup += 1
            continue

        result = all_results.get(v["idx"])
        if not result:
            skipped_noresult += 1
            continue

        if not result.get("is_safety", False):
            skipped_nonsafety += 1
            continue

        max_id += 1
        new_video = {
            "id": max_id,
            "title": v["title"],
            "url": v["url"],
            "category": v["playlist"],
            "tags": [],
            "hazard_categories": [],
            "series": "",
            "is_korean": True,
            "hazard_codes": result.get("hazard_codes", []),
            "description": result.get("description", ""),
            "video_type": "long",
            "duration": v.get("duration", ""),
            "playlist": v["playlist"],
        }
        existing_videos.append(new_video)
        existing_urls.add(v["url"])
        added += 1

    existing_data["videos"] = existing_videos
    existing_data["total"] = len(existing_videos)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"=== 완료 ===")
    print(f"입력: {total}건")
    print(f"추가: {added}건")
    print(f"중복 스킵: {skipped_dup}건")
    print(f"비안전 제외: {skipped_nonsafety}건")
    print(f"결과없음 스킵: {skipped_noresult}건")
    print(f"최종 safety_videos.json: {len(existing_videos)}건")

    # hazard_codes 분포
    from collections import Counter
    code_counter = Counter()
    for v in existing_videos:
        for c in v.get("hazard_codes", []):
            code_counter[c] += 1
    print(f"\n=== hazard_codes 분포 (전체) ===")
    for k, cnt in code_counter.most_common():
        print(f"  {k}: {cnt}건")


if __name__ == "__main__":
    main()
