#!/usr/bin/env python3
"""Phase 0.3 — Description 합성: scenarios-v1.jsonl 의 각 시나리오에
GPT-4o가 사진을 봤을 때 출력할 한국어 description 을 합성.

원리: OHS production이 GPT-4o vision을 사용하므로, 합성 description도
같은 GPT-4o로 만들어야 token-distribution KL divergence가 최소화됨.

프롬프트 핵심 제약:
  - 4~6 문장 한국어
  - 위험요소(추락/끼임/감전 등) 직접 명명 금지
  - SR/CI/Guide 식별자 노출 금지
  - 시각적 단서만 (자세/설비/환경/보호구/누유/균열 등)
  - 자연스러운 vision 묘사 톤

caching: scenario.description 이미 있으면 skip (중간 실패 후 재실행 가능)

실행:
  PYTHONUTF8=1 python OHS/scripts/eval/synthesize_descriptions.py
  PYTHONUTF8=1 python OHS/scripts/eval/synthesize_descriptions.py --batch 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[3]
OHS = ROOT / "OHS"
INPUT = OHS / "data" / "eval" / "scenarios-v1.jsonl"
OUTPUT = INPUT  # in-place update

ENV_FILE = OHS / ".env"


def load_openai_key() -> str:
    if "OPENAI_API_KEY" in os.environ:
        return os.environ["OPENAI_API_KEY"]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("OPENAI_API_KEY not found")


# ────────────────────────────────────────────────────────────────────────
# Prompt
# ────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 산업안전 검사관이자 사진 묘사 전문가입니다.
주어진 작업현장 시나리오를 GPT-4 Vision이 실제 사진을 봤을 때 출력할 만한 자연스러운 한국어 description으로 변환해주세요.

엄격한 규칙:
1. 4~6개 문장. 각 문장은 자연스러운 한국어 사진 묘사 톤.
2. 위험요소 명칭 절대 금지 (예: "추락 위험", "감전 사고", "끼임" 등 직접 명명 X).
3. SR/CI/Guide 식별자(SR-, CI-, DC-, AG- 등) 절대 노출 X.
4. 시각적 단서만 묘사 가능: 작업자 자세, 설비/도구/장비, 장소 환경, 보호구 착용 상태, 주변 상태(누유/균열/정돈), 작업 단계 추정.
5. 단순 나열 금지. 사진 한 장을 자연스럽게 묘사하는 톤 (예: "작업자 두 명이 약 3m 높이의 비계 위에서 단열재를 설치하고 있다. 한 명은 안전대를 매고 있지만 다른 한 명은 매지 않은 상태이다.").
6. 4~6 문장만 출력. 메타정보, 머리말, JSON, 설명 등 추가 텍스트 절대 금지."""

USER_PROMPT_TEMPLATE = """다음 작업현장 시나리오의 description을 합성해주세요.

【 작업맥락 (work_context) 】
{work_context}

【 사고유형 후보 (accident_types) 】
{accident_types}

【 유해인자 후보 (hazardous_agents) 】
{hazardous_agents}

【 메타데이터 】
- source: {source}
{metadata_lines}

【 출력 】
4~6 문장의 한국어 description만 출력. 다른 텍스트 없이 description 본문만."""


def build_user_prompt(scenario: dict[str, Any]) -> str:
    pf = scenario.get("primary_facets", {})
    md = scenario.get("metadata", {})
    md_lines = []
    if md.get("article"):
        md_lines.append(f"- 관련 조문: {md['article']}")
    if md.get("hazards_legacy"):
        md_lines.append(f"- legacy hazard codes: {', '.join(md['hazards_legacy'])}")
    if md.get("guide_code"):
        md_lines.append(f"- 가이드: {md['guide_code']}")
    if md.get("source_guide") and md.get("referenced_guide"):
        md_lines.append(f"- 가이드 인용: {md['source_guide']} → {md['referenced_guide']}")
    if md.get("addressesHazard"):
        md_lines.append(f"- 직접 다룬 hazard: {', '.join(md['addressesHazard'])}")
    if md.get("industries"):
        md_lines.append(f"- 산업: {', '.join(md['industries'])}")

    metadata_lines = "\n".join(md_lines) if md_lines else "(추가 메타 없음)"

    return USER_PROMPT_TEMPLATE.format(
        work_context=scenario.get("work_context") or "GENERAL_WORKPLACE",
        accident_types=", ".join(pf.get("accident_types", [])) or "(없음)",
        hazardous_agents=", ".join(pf.get("hazardous_agents", [])) or "(없음)",
        source=scenario.get("source", ""),
        metadata_lines=metadata_lines,
    )


# ────────────────────────────────────────────────────────────────────────
# OpenAI async call (with retry)
# ────────────────────────────────────────────────────────────────────────

async def synthesize_one(client, scenario: dict[str, Any], max_retry: int = 3) -> str:
    user_prompt = build_user_prompt(scenario)
    last_err = None
    for attempt in range(max_retry):
        try:
            r = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=400,
            )
            txt = (r.choices[0].message.content or "").strip()
            if not txt:
                raise RuntimeError("empty response")
            return txt
        except Exception as e:
            last_err = e
            await asyncio.sleep(2 ** attempt)
    raise last_err  # type: ignore


async def main_async(args):
    api_key = load_openai_key()
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key)

    scenarios: list[dict[str, Any]] = []
    with args.input.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            scenarios.append(json.loads(line))
    print(f"[INFO] {len(scenarios)} scenarios")

    pending = [sc for sc in scenarios if not sc.get("description")]
    print(f"[INFO] pending (description 없음): {len(pending)}")

    if not pending:
        print("[OK] 모든 description 합성 완료. 작업 없음.")
        return

    sem = asyncio.Semaphore(args.batch)

    async def worker(sc: dict[str, Any], idx: int):
        async with sem:
            try:
                desc = await synthesize_one(client, sc)
                sc["description"] = desc
                # 길이 sanity
                n_sentences = sum(1 for ch in desc if ch in ".!?")
                tag = "OK" if 3 <= n_sentences <= 8 else "WARN"
                print(f"  [{idx:3d}/{len(pending)}] {tag} {sc['scenario_id']} ({len(desc)} chars, ~{n_sentences} sentences)")
            except Exception as e:
                print(f"  [{idx:3d}] ERROR {sc['scenario_id']}: {e}")
                sc["description"] = None

    print(f"\n[STEP] GPT-4o description 합성 (batch={args.batch})...")
    await asyncio.gather(*[
        worker(sc, i + 1) for i, sc in enumerate(pending)
    ])

    # 즉시 저장 (cache 가치)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for sc in scenarios:
            fh.write(json.dumps(sc, ensure_ascii=False, separators=(",", ":")) + "\n")

    completed = sum(1 for sc in scenarios if sc.get("description"))
    print(f"\n[OK] {args.output} 갱신 완료 ({completed}/{len(scenarios)} description 보유)")

    # 샘플 출력
    print(f"\n[샘플 3건]")
    for sc in scenarios[:3]:
        if sc.get("description"):
            print(f"\n  --- {sc['scenario_id']} (work_context={sc['work_context']}) ---")
            print(f"  {sc['description']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--batch", type=int, default=5,
                        help="동시 호출 수 (default 5)")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
