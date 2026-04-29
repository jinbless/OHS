#!/usr/bin/env python3
"""Description 기반 SR identifier 재정리.

scenarios-v1.jsonl의 기존 라벨 필드는 사용하지 않는다. 각 행에서
scenario_id와 description만 읽고, pipe-A safety-requirements 결과 JSON의
626개 SR 중 사진 설명에 직접 근거가 있는 SR identifier를 제안한다.

실행:
  PYTHONUTF8=1 python OHS/scripts/eval/review_sr_from_description.py

출력:
  OHS/data/eval/scenario-sr-description-reviewed-v1.jsonl
  OHS/data/eval/scenario-sr-description-reviewed-v1.md
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[3]
OHS = ROOT / "OHS"
KOSHA = ROOT / "koshaontology"

SCENARIOS_FILE = OHS / "data" / "eval" / "scenarios-v1.jsonl"
SR_DIR = KOSHA / "pipe-A" / "data" / "safety-requirements"
OUTPUT_JSONL = OHS / "data" / "eval" / "scenario-sr-description-reviewed-v1.jsonl"
OUTPUT_MD = OHS / "data" / "eval" / "scenario-sr-description-reviewed-v1.md"


@dataclass(frozen=True)
class SR:
    identifier: str
    title: str
    text: str
    references_article: list[str]
    addresses_hazard: list[str]
    source_file: str


@dataclass(frozen=True)
class MatchRule:
    fact: str
    sr_ids: tuple[str, ...]
    confidence: str
    any_patterns: tuple[str, ...] = ()
    all_patterns: tuple[str, ...] = ()
    absent_patterns: tuple[str, ...] = ()
    note: str | None = None

    def matches(self, description: str) -> bool:
        if self.any_patterns and not any(re.search(p, description) for p in self.any_patterns):
            return False
        if self.all_patterns and not all(re.search(p, description) for p in self.all_patterns):
            return False
        if self.absent_patterns and any(re.search(p, description) for p in self.absent_patterns):
            return False
        return True


def load_srs() -> dict[str, SR]:
    """Load finalized SR JSON files only; exclude *-input.json."""
    sr_map: dict[str, SR] = {}
    for path in sorted(SR_DIR.glob("sr-batch-*.json")):
        if path.name.endswith("-input.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("safetyRequirements", []):
            sr = SR(
                identifier=item["identifier"],
                title=item.get("title", ""),
                text=item.get("text", ""),
                references_article=list(item.get("referencesArticle") or []),
                addresses_hazard=list(item.get("addressesHazard") or []),
                source_file=path.name,
            )
            if sr.identifier in sr_map:
                raise ValueError(f"Duplicate SR identifier: {sr.identifier}")
            sr_map[sr.identifier] = sr
    return sr_map


def load_scenarios() -> list[dict[str, str]]:
    """Read only scenario_id and description from each JSONL row."""
    scenarios: list[dict[str, str]] = []
    with SCENARIOS_FILE.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            scenario_id = row.get("scenario_id")
            description = row.get("description")
            if not scenario_id or not description:
                raise ValueError(f"Missing scenario_id or description at line {line_no}")
            scenarios.append({"scenario_id": scenario_id, "description": description})
    return scenarios


RULES: tuple[MatchRule, ...] = (
    # 고소/추락/비계
    MatchRule(
        fact="높은 장소 또는 비계 위 작업으로 추락 위험이 보임",
        sr_ids=("SR-FALL-001",),
        confidence="high",
        any_patterns=(r"비계 위|사다리 위|플랫폼|높[은이]|[0-9]+\s*m|[0-9]+미터|고소",),
        all_patterns=(r"작업|서 있|진행|수행",),
    ),
    MatchRule(
        fact="안전대 또는 안전벨트 미착용이 보임",
        sr_ids=("SR-FALL-003", "SR-PPE-002"),
        confidence="high",
        any_patterns=(
            r"안전대[^.]{0,18}(매지|없|않|미착용|보이지|제대로 착용되어 있지)",
            r"안전벨트[^.]{0,18}(매지|없|않|미착용|보이지)",
        ),
    ),
    MatchRule(
        fact="비계 작업발판 또는 비계 구조에서 작업 중임",
        sr_ids=("SR-SCAFFOLD-003",),
        confidence="high",
        any_patterns=(r"비계",),
        all_patterns=(r"작업|서 있|올라|진행|수행",),
    ),
    MatchRule(
        fact="비계 흔들림, 고정 불량 또는 구조 안정성 우려가 보임",
        sr_ids=("SR-SCAFFOLD-005",),
        confidence="high",
        all_patterns=(r"비계", r"흔들|불안정|고정이 불안|안정성|지지대|변형|침하"),
        note="비계 흔들림/불안정은 전용 관찰 SR 대신 비계 점검 및 즉시 보수 SR로 매핑했다.",
    ),
    MatchRule(
        fact="고소 작업 장소에 난간·방호장치가 없거나 부족해 보임",
        sr_ids=("SR-FALL-002", "SR-WORKPLACE-011"),
        confidence="medium",
        any_patterns=(r"안전 장치가 설치되어 있지|안전 장치가 보이지|난간.*(없|보이지)|보호.*장치.*(없|부족)|가드.*(없|보이지)",),
        all_patterns=(r"높|비계|사다리|플랫폼|구덩이|가장자리",),
    ),
    MatchRule(
        fact="안전모 또는 기본 보호구 미착용이 보임",
        sr_ids=("SR-PPE-002",),
        confidence="high",
        any_patterns=(
            r"안전모[^.]{0,18}(착용하지|없|미착용|보이지)",
            r"헬멧[^.]{0,18}(착용하지|없|없이|보이지)",
            r"보호구[^.]{0,20}(없|미착용|착용하지|제대로 착용하지|보이지)",
            r"보호 장비[^.]{0,20}(없|미착용|착용하지|제대로 착용하지|보이지)",
        ),
    ),
    # 정리정돈/통로/비상기구
    MatchRule(
        fact="공구·자재·물건이 바닥이나 작업공간에 흩어져 전도 위험이 보임",
        sr_ids=("SR-WORKPLACE-001",),
        confidence="high",
        any_patterns=(r"흩어|널려|정리되지|정돈되지|어수선|무질서|혼잡|복잡|발 디딜|바닥[^.]{0,25}(물건|공구|자재|부품|전선)",),
    ),
    MatchRule(
        fact="이동 동선, 통로 또는 접근성이 방해받는 상태가 보임",
        sr_ids=("SR-PASSAGE-002",),
        confidence="high",
        any_patterns=(r"통로|동선|이동.*(불편|어려|방해|주의)|접근.*(쉽지|어렵|곤란)|출입.*(어렵|협소)|지나가는 데 방해",),
    ),
    MatchRule(
        fact="비상용 기구 또는 소화기에 접근하기 어려워 보임",
        sr_ids=("SR-WORKPLACE-016", "SR-PASSAGE-002"),
        confidence="high",
        all_patterns=(r"소화기|비상", r"접근.*(쉽지|어렵|곤란)|가려|막혀|방해"),
        note="소화기 접근성 전용 SR은 없어 비상용 기구 이용 가능 상태와 통로 유지관리 SR로 매핑했다.",
    ),
    MatchRule(
        fact="소화기 또는 소화설비가 필요한 화재 대응 맥락이 보임",
        sr_ids=("SR-FIRE_EXPLOSION-019",),
        confidence="medium",
        any_patterns=(r"소화기|소화설비|방화 담요",),
    ),
    MatchRule(
        fact="바닥에 물기·액체·기름·먼지가 보여 미끄러짐 또는 오염 위험이 있음",
        sr_ids=("SR-WORKPLACE-001",),
        confidence="high",
        any_patterns=(r"바닥[^.]{0,25}(젖|액체|기름|누수|흘러|미끄러|먼지|분진)",),
    ),
    # 전기
    MatchRule(
        fact="전선·케이블 노출, 엉킴 또는 절연 관리 문제가 보임",
        sr_ids=("SR-ELECTRIC-013",),
        confidence="high",
        any_patterns=(r"전선|케이블|배선",),
        all_patterns=(r"노출|엉켜|어지럽|복잡|흐트러|전기 패널|패널",),
    ),
    MatchRule(
        fact="통로 또는 바닥에 전선이 있어 이동 중 전기·전도 위험이 보임",
        sr_ids=("SR-ELECTRIC-015", "SR-PASSAGE-002"),
        confidence="high",
        all_patterns=(r"전선|케이블|배선", r"바닥|통로|이동|발밑"),
    ),
    MatchRule(
        fact="전기 패널이나 전기기계·기구의 충전부 접촉 위험이 보임",
        sr_ids=("SR-ELECTRIC-001", "SR-ELECTRIC-018"),
        confidence="high",
        any_patterns=(r"전기 패널|전기 장치|전기 설비|배전반|패널.*열",),
    ),
    # 밀폐공간/조명/환기
    MatchRule(
        fact="밀폐되거나 좁은 공간에서 산소·유해가스 확인이 필요한 작업임",
        sr_ids=("SR-CONFINED-001",),
        confidence="high",
        any_patterns=(r"밀폐|폐쇄|좁은 공간|좁고|협소|공기 흐름이 제한",),
    ),
    MatchRule(
        fact="밀폐·협소 공간의 환기 부족 또는 공기질 우려가 보임",
        sr_ids=("SR-CONFINED-002",),
        confidence="high",
        any_patterns=(r"환기|공기 흐름|연기|통풍|습기",),
        all_patterns=(r"밀폐|폐쇄|좁|협소|공간",),
    ),
    MatchRule(
        fact="작업 공간 조명이 어둡거나 시야 확보가 어려움",
        sr_ids=("SR-WORKPLACE-006",),
        confidence="medium",
        any_patterns=(r"어둡|조명.*(부족|충분하지|낮아)|시야 확보가 어려|손전등|휴대용 조명",),
    ),
    # 굴착/토사
    MatchRule(
        fact="굴착면, 흙벽 또는 흙더미로 인한 붕괴·토사 낙하 위험이 보임",
        sr_ids=("SR-EXCAVATION-003",),
        confidence="high",
        any_patterns=(r"굴착|구덩이|땅을 파|깊게 파인|흙벽|흙더미|토사",),
        all_patterns=(r"지지대 없이|노출|붕괴|무너|불안정|가장자리|흙더미|깊",),
    ),
    MatchRule(
        fact="굴착기 또는 굴착기계 주변 작업으로 접촉 위험이 보임",
        sr_ids=("SR-EXCAVATION-005", "SR-CONSTRUCTION_EQUIP-004"),
        confidence="high",
        any_patterns=(r"굴착기|굴착 장비|중장비",),
    ),
    MatchRule(
        fact="구덩이·굴착 가장자리에서 추락 위험이 보임",
        sr_ids=("SR-FALL-002",),
        confidence="medium",
        all_patterns=(r"구덩이|굴착|깊게 파인", r"가장자리|아래|내려다|안전 장치.*보이지|펜스.*불안정"),
    ),
    # 기계/컨베이어/소음
    MatchRule(
        fact="기계 위험부위 또는 움직이는 부품에 대한 방호가 부족해 보임",
        sr_ids=("SR-MACHINE-002",),
        confidence="high",
        any_patterns=(r"기계|장비|부품|절단기|절삭",),
        all_patterns=(r"작동 중|가동|움직|보호 장치.*부족|방호|가드.*없|덮개.*없",),
    ),
    MatchRule(
        fact="금속 절단·가공 작업에서 절삭편 비산 위험이 보임",
        sr_ids=("SR-MACHINE-005",),
        confidence="high",
        any_patterns=(r"절단기|절삭|금속 조각|금속재",),
        all_patterns=(r"작업|조정|가공|절단",),
    ),
    MatchRule(
        fact="기계 운전 시작 전 안전확인이 필요한 상황임",
        sr_ids=("SR-MACHINE-004",),
        confidence="medium",
        any_patterns=(r"작동시키기 전|가동 전|운전 시작 전|시작하기 전",),
        all_patterns=(r"기계|장비|절단기",),
    ),
    MatchRule(
        fact="기계 점검·정비 중 운전정지 또는 잠금조치가 필요한 상황임",
        sr_ids=("SR-MACHINE-007",),
        confidence="high",
        any_patterns=(r"점검|정비|수리|내부를 들여다|패널.*확인|조작 패널",),
        all_patterns=(r"기계|장비|설비",),
    ),
    MatchRule(
        fact="기계·설비의 보호장치가 해체되었거나 기능이 부족해 보임",
        sr_ids=("SR-MACHINE-008",),
        confidence="medium",
        any_patterns=(r"보호 장치.*(부족|없|보이지)|방호장치.*(부족|없|해체)|가드.*(없|보이지)",),
        all_patterns=(r"기계|장비|컨베이어",),
    ),
    MatchRule(
        fact="컨베이어 주변 또는 가까운 위치에서 작업 중임",
        sr_ids=("SR-CONVEYOR-005", "SR-CONVEYOR-002"),
        confidence="high",
        any_patterns=(r"컨베이어",),
    ),
    MatchRule(
        fact="컨베이어에서 화물 이탈·낙하 또는 끼임 위험이 보임",
        sr_ids=("SR-CONVEYOR-001", "SR-CONVEYOR-003"),
        confidence="medium",
        all_patterns=(r"컨베이어", r"물건|화물|상자|낙하|이탈|벨트와 가까"),
    ),
    MatchRule(
        fact="소음이 큰 작업장으로 보임",
        sr_ids=("SR-NOISE-001",),
        confidence="medium",
        any_patterns=(r"소음|시끄럽|귀마개",),
    ),
    MatchRule(
        fact="소음 작업에서 청력보호구가 필요하거나 미착용 상태로 보임",
        sr_ids=("SR-NOISE-004",),
        confidence="medium",
        any_patterns=(r"소음|시끄럽",),
        absent_patterns=(r"귀마개.*착용|청력보호구.*착용",),
    ),
    # 크레인/양중/하역운반
    MatchRule(
        fact="크레인으로 중량물 또는 자재를 들어 올리는 작업이 보임",
        sr_ids=("SR-CRANE-011",),
        confidence="high",
        any_patterns=(r"크레인",),
        all_patterns=(r"들어 올|매달|이동|조종|무전|신호|작업",),
    ),
    MatchRule(
        fact="매달린 물체 또는 낙하물 아래·주변에서 작업자가 노출됨",
        sr_ids=("SR-WORKPLACE-012", "SR-CRANE-011"),
        confidence="high",
        any_patterns=(r"매달|들어 올|낙하|떨어질|위쪽.*물체|이동 경로 아래",),
    ),
    MatchRule(
        fact="건설기계·중장비와 작업자 접촉 위험이 보임",
        sr_ids=("SR-CONSTRUCTION_EQUIP-004",),
        confidence="high",
        any_patterns=(r"중장비|건설 기계|건설 장비|굴착기|장비의 바로 옆|장비 사이",),
    ),
    MatchRule(
        fact="지게차 등 차량계 하역운반기계와 작업자 접촉 위험이 보임",
        sr_ids=("SR-VEHICLE-002",),
        confidence="high",
        any_patterns=(r"지게차|차량계|하역운반",),
        all_patterns=(r"주변|가까이|근처|작업자|이동",),
    ),
    MatchRule(
        fact="지게차 또는 차량계 하역운반기계의 화물 적재 안정성 우려가 보임",
        sr_ids=("SR-VEHICLE-003",),
        confidence="high",
        any_patterns=(r"지게차|차량계|하역운반",),
        all_patterns=(r"상자|박스|화물|팔레트|적재|고정되지|불안정",),
    ),
    MatchRule(
        fact="인력으로 중량물을 취급해 근골격계 부담이 보임",
        sr_ids=("SR-ERGONOMIC-007",),
        confidence="medium",
        any_patterns=(r"큰 상자|무거|상자를 안고|중량물|자세를 낮추",),
        all_patterns=(r"옮기|운반|이동|올리",),
    ),
    # 화학/화재/누출
    MatchRule(
        fact="화학물질 용기·드럼통의 저장 또는 배치 안전관리가 필요함",
        sr_ids=("SR-CHEMICAL-018",),
        confidence="high",
        any_patterns=(r"화학 물질|화학물질|드럼통|용기|저장 탱크|컨테이너",),
    ),
    MatchRule(
        fact="화학물질 누수·누출 또는 바닥 오염이 보임",
        sr_ids=("SR-CHEMICAL-012", "SR-CHEMICAL-020", "SR-WORKPLACE-001"),
        confidence="high",
        any_patterns=(r"누수|누출|액체가 흘러|흘러 있는|오염",),
        all_patterns=(r"화학|드럼통|용기|저장 탱크|액체",),
    ),
    MatchRule(
        fact="화학물질 취급 작업에서 국소배기 또는 환기 관리가 필요해 보임",
        sr_ids=("SR-CHEMICAL-002",),
        confidence="medium",
        any_patterns=(r"화학 물질|화학물질|유해물질",),
        all_patterns=(r"환기|통풍|연기|가스|냄새",),
    ),
    MatchRule(
        fact="화학물질 취급 작업에서 보호구가 필요하거나 미흡해 보임",
        sr_ids=("SR-CHEMICAL-025", "SR-CHEMICAL-026", "SR-PPE-002"),
        confidence="medium",
        any_patterns=(r"화학 물질|화학물질|드럼통|용기|저장 탱크",),
        all_patterns=(r"보호.*(없|미흡|제대로 착용하지|필요)|장갑|마스크|보안경|고글",),
    ),
    MatchRule(
        fact="화재·폭발 가능성 또는 발화 대응 설비가 필요한 장소임",
        sr_ids=("SR-FIRE_EXPLOSION-001", "SR-FIRE_EXPLOSION-019"),
        confidence="medium",
        any_patterns=(r"불꽃|화재|폭발|방화|인화|소화기|소화설비",),
        all_patterns=(r"화학|용기|드럼통|전기|기계|창고|위험",),
    ),
)


def add_match(
    matches: dict[str, dict[str, Any]],
    sr_map: dict[str, SR],
    sr_id: str,
    fact: str,
    confidence: str,
) -> None:
    if sr_id not in sr_map:
        raise KeyError(f"Rule references unknown SR identifier: {sr_id}")
    sr = sr_map[sr_id]
    entry = matches.setdefault(
        sr_id,
        {
            "sr_id": sr_id,
            "title": sr.title,
            "source_file": sr.source_file,
            "matched_description_facts": [],
            "confidence": confidence,
        },
    )
    if fact not in entry["matched_description_facts"]:
        entry["matched_description_facts"].append(fact)
    if confidence == "high":
        entry["confidence"] = "high"


def apply_rules(description: str, sr_map: dict[str, SR]) -> tuple[list[dict[str, Any]], list[str]]:
    matches: dict[str, dict[str, Any]] = {}
    unmapped: list[str] = []
    for rule in RULES:
        if not rule.matches(description):
            continue
        for sr_id in rule.sr_ids:
            add_match(matches, sr_map, sr_id, rule.fact, rule.confidence)
        if rule.note and rule.note not in unmapped:
            unmapped.append(rule.note)

    evidence = sorted(
        matches.values(),
        key=lambda x: (
            0 if x["confidence"] == "high" else 1,
            x["source_file"],
            x["sr_id"],
        ),
    )
    return evidence, unmapped


def summarize_description(description: str, limit: int = 110) -> str:
    compact = re.sub(r"\s+", " ", description).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def render_markdown(results: list[dict[str, Any]], sr_count: int) -> str:
    selected_counts = Counter(sr_id for row in results for sr_id in row["selected_sr_ids"])
    lines: list[str] = [
        "# Description 기반 SR Identifier 재정리 결과",
        "",
        "기존 라벨 필드는 사용하지 않고, 각 시나리오의 `description`만 기준으로 SR을 다시 제안했다.",
        "",
        "## Summary",
        "",
        f"- Scenario rows: {len(results)}",
        f"- SR source count: {sr_count}",
        f"- Scenarios with selected SR: {sum(1 for row in results if row['selected_sr_ids'])}",
        f"- Unique selected SR: {len(selected_counts)}",
        "",
        "## Top Selected SR",
        "",
        "| SR | Count |",
        "|---|---:|",
    ]
    for sr_id, count in selected_counts.most_common(20):
        lines.append(f"| `{sr_id}` | {count} |")

    lines.extend(["", "## Scenario Review", ""])
    for row in results:
        lines.append(f"### {row['scenario_id']}")
        lines.append("")
        lines.append(f"**Description 요약:** {summarize_description(row['description'], 180)}")
        lines.append("")
        lines.append("| 선택 SR | 제목 | 근거 | 신뢰도 |")
        lines.append("|---|---|---|---|")
        if row["evidence"]:
            for ev in row["evidence"]:
                facts = "<br>".join(ev["matched_description_facts"])
                lines.append(f"| `{ev['sr_id']}` | {ev['title']} | {facts} | {ev['confidence']} |")
        else:
            lines.append("| - | - | 명확히 매핑할 SR 없음 | - |")
        if row["unmapped_facts"]:
            lines.append("")
            lines.append("**매핑 메모:**")
            for fact in row["unmapped_facts"]:
                lines.append(f"- {fact}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    sr_map = load_srs()
    scenarios = load_scenarios()

    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        evidence, unmapped = apply_rules(scenario["description"], sr_map)
        results.append(
            {
                "scenario_id": scenario["scenario_id"],
                "description": scenario["description"],
                "selected_sr_ids": [ev["sr_id"] for ev in evidence],
                "evidence": evidence,
                "unmapped_facts": unmapped,
                "review_status": "proposed",
            }
        )

    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSONL.open("w", encoding="utf-8", newline="\n") as f:
        for row in results:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    OUTPUT_MD.write_text(render_markdown(results, len(sr_map)), encoding="utf-8", newline="\n")

    selected_counts = Counter(sr_id for row in results for sr_id in row["selected_sr_ids"])
    print(f"Loaded SRs: {len(sr_map)}")
    print(f"Reviewed scenarios: {len(results)}")
    print(f"Scenarios with selected SR: {sum(1 for row in results if row['selected_sr_ids'])}")
    print(f"Unique selected SR: {len(selected_counts)}")
    print(f"Wrote: {OUTPUT_JSONL}")
    print(f"Wrote: {OUTPUT_MD}")


if __name__ == "__main__":
    main()
