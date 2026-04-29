#!/usr/bin/env python3
"""Map selected SR identifiers to KOSHA Guides using guide filenames only.

Inputs:
  - OHS/data/eval/scenario-sr-description-reviewed-v1.jsonl
  - koshaontology/pipe-B/data/guide-inventory.json

The matcher only inspects each guide pdfPath basename. It does not read Guide
PDF/JSON bodies and does not use any scenario catalog labels.

Output:
  OHS/data/eval/scenario-sr-description-reviewed-v2.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath, Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[3]
OHS = ROOT / "OHS"
KOSHA = ROOT / "koshaontology"

INPUT_JSONL = OHS / "data" / "eval" / "scenario-sr-description-reviewed-v1.jsonl"
GUIDE_INVENTORY = KOSHA / "pipe-B" / "data" / "guide-inventory.json"
OUTPUT_JSONL = OHS / "data" / "eval" / "scenario-sr-description-reviewed-v2.jsonl"

MAX_GUIDES_PER_SR = 5


@dataclass(frozen=True)
class Term:
    label: str
    pattern: str
    priority: int = 10


@dataclass(frozen=True)
class GuideFile:
    guide_code: str
    short_code: str
    filename: str


COMMON_TERMS = (
    "작업",
    "안전",
    "관리",
    "기술지침",
    "기술지원규정",
    "지침",
    "규정",
)


PREFIX_TERMS: dict[str, tuple[Term, ...]] = {
    "SCAFFOLD": (
        Term("비계", r"비계", 100),
    ),
    "FALL": (
        Term("추락방호망", r"추락방호망|추락방망", 120),
        Term("추락", r"추락", 110),
        Term("떨어짐", r"떨어짐", 100),
        Term("안전대", r"안전대(?!책)", 100),
        Term("사다리", r"사다리", 85),
    ),
    "PASSAGE": (
        Term("통로", r"통로", 110),
        Term("계단", r"계단", 95),
        Term("경사로", r"경사로", 95),
        Term("발판사다리", r"발판사다리", 100),
    ),
    "WORKPLACE": (
        Term("넘어짐", r"넘어짐", 120),
        Term("조명", r"조명|조도", 110),
        Term("비상구", r"비상구|비상통로|비상조치|비상대응", 105),
        Term("낙하물", r"낙하물|떨어짐", 105),
        Term("작업장 내 통로", r"작업장 내 통로", 100),
        Term("작업장", r"작업장", 20),
    ),
    "ELECTRIC": (
        Term("방폭전기", r"방폭전기", 125),
        Term("정전전로", r"정전전로", 115),
        Term("충전전로", r"충전전로", 115),
        Term("전선", r"전선|전선로", 110),
        Term("전기", r"전기", 100),
    ),
    "MACHINE": (
        Term("회전기계", r"회전기계", 120),
        Term("끼임", r"끼임", 115),
        Term("절단", r"절단", 115),
        Term("기계", r"기계", 90),
    ),
    "CONVEYOR": (
        Term("컨베이어", r"컨베이어", 120),
    ),
    "CRANE": (
        Term("이동식 크레인", r"이동식\s*크레인|이동식크레인", 125),
        Term("타워크레인", r"타워크레인", 120),
        Term("크레인", r"크레인", 110),
        Term("줄걸이", r"줄걸이", 100),
        Term("와이어로프", r"와이어로프", 95),
    ),
    "VEHICLE": (
        Term("지게차", r"지게차", 120),
        Term("운반차량", r"운반차량", 110),
    ),
    "EXCAVATION": (
        Term("굴착기", r"굴착기", 120),
        Term("굴착", r"굴착", 115),
        Term("토공", r"토공", 105),
    ),
    "CONFINED": (
        Term("밀폐공간", r"밀폐공간", 125),
    ),
    "CHEMICAL": (
        Term("화학물질", r"화학물질", 120),
        Term("화학설비", r"화학설비", 115),
        Term("화학", r"화학", 95),
        Term("유해물질", r"유해물질", 110),
    ),
    "FIRE_EXPLOSION": (
        Term("화재", r"화재", 115),
        Term("폭발", r"폭발", 115),
        Term("용접", r"용접|용단", 110),
        Term("소화", r"소화기|소화설비|소화약제|포\s*소화|소화\s*장치", 100),
        Term("방폭", r"방폭", 100),
    ),
    "NOISE": (
        Term("소음", r"소음", 120),
        Term("청력보호구", r"청력보호구", 110),
    ),
    "PPE": (
        Term("개인보호구", r"개인보호구", 120),
        Term("호흡보호구", r"호흡보호구", 115),
        Term("청력보호구", r"청력보호구", 110),
        Term("보호구", r"보호구", 100),
        Term("안전대", r"안전대(?!책)", 95),
    ),
    "CONSTRUCTION_EQUIP": (
        Term("건설기계", r"건설기계|건설 기계", 120),
        Term("굴착기", r"굴착기", 110),
        Term("크레인", r"크레인", 100),
    ),
    "ERGONOMIC": (
        Term("인력운반작업", r"인력운반작업|인력운반", 120),
        Term("중량물", r"중량물", 110),
        Term("근골격계", r"근골격계", 105),
    ),
}


SR_SPECIFIC_TERMS: dict[str, tuple[Term, ...]] = {
    "SR-FALL-001": (
        Term("추락방호망", r"추락방호망|추락방망", 130),
        Term("사다리", r"사다리", 95),
    ),
    "SR-FALL-003": (
        Term("안전대", r"안전대(?!책)", 130),
    ),
    "SR-WORKPLACE-001": (
        Term("넘어짐", r"넘어짐", 130),
    ),
    "SR-WORKPLACE-006": (
        Term("조명", r"조명|조도", 130),
    ),
    "SR-WORKPLACE-012": (
        Term("낙하물", r"낙하물|떨어짐", 130),
    ),
    "SR-WORKPLACE-016": (
        Term("비상조치", r"비상조치|비상대응|비상구|비상통로", 130),
    ),
    "SR-ELECTRIC-013": (
        Term("전선", r"전선|전선로", 130),
    ),
    "SR-ELECTRIC-015": (
        Term("전선", r"전선|전선로", 130),
        Term("통로", r"통로", 100),
    ),
    "SR-MACHINE-005": (
        Term("절단", r"절단", 130),
        Term("끼임", r"끼임", 120),
    ),
    "SR-MACHINE-007": (
        Term("정비", r"정비|보수", 110),
        Term("기계", r"기계", 100),
    ),
    "SR-CONVEYOR-001": (
        Term("컨베이어", r"컨베이어", 130),
    ),
    "SR-CONVEYOR-002": (
        Term("컨베이어", r"컨베이어", 130),
    ),
    "SR-CONVEYOR-003": (
        Term("컨베이어", r"컨베이어", 130),
        Term("낙하물", r"낙하물|떨어짐", 110),
    ),
    "SR-CRANE-011": (
        Term("크레인", r"크레인", 130),
        Term("줄걸이", r"줄걸이", 115),
    ),
    "SR-VEHICLE-002": (
        Term("지게차", r"지게차", 130),
        Term("운반차량", r"운반차량", 120),
    ),
    "SR-VEHICLE-003": (
        Term("지게차", r"지게차", 130),
        Term("운반차량", r"운반차량", 120),
    ),
    "SR-CHEMICAL-018": (
        Term("화학물질", r"화학물질", 130),
    ),
    "SR-CHEMICAL-025": (
        Term("호흡보호구", r"호흡보호구", 130),
        Term("화학물질", r"화학물질", 115),
    ),
    "SR-CHEMICAL-026": (
        Term("보호구", r"보호구", 115),
        Term("화학물질", r"화학물질", 115),
    ),
    "SR-FIRE_EXPLOSION-019": (
        Term("소화", r"소화기|소화설비|소화약제|포\s*소화|소화\s*장치", 130),
        Term("화재", r"화재", 115),
    ),
}


def sr_prefix(sr_id: str) -> str:
    body = sr_id.removeprefix("SR-")
    match = re.match(r"([A-Z_]+)-\d+$", body)
    return match.group(1) if match else body


def load_review_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with INPUT_JSONL.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if "scenario_id" not in row or "selected_sr_ids" not in row:
                raise ValueError(f"Missing required v1 fields at line {line_no}")
            rows.append(row)
    return rows


def load_guide_files() -> list[GuideFile]:
    data = json.loads(GUIDE_INVENTORY.read_text(encoding="utf-8"))
    files: list[GuideFile] = []
    for guide in data.get("guides", []):
        pdf_path = guide.get("pdfPath")
        if not pdf_path:
            continue
        files.append(
            GuideFile(
                guide_code=guide["guideCode"],
                short_code=guide["shortCode"],
                filename=PurePosixPath(pdf_path).name,
            )
        )
    return files


def terms_for_sr(sr_id: str) -> tuple[Term, ...]:
    prefix = sr_prefix(sr_id)
    combined: OrderedDict[str, Term] = OrderedDict()
    specific_terms = SR_SPECIFIC_TERMS.get(sr_id, ())
    for term in specific_terms:
        combined[term.label] = term
    if specific_terms:
        return tuple(combined.values())
    for term in PREFIX_TERMS.get(prefix, ()):
        combined.setdefault(term.label, term)
    return tuple(combined.values())


def is_common_only(matches: list[Term]) -> bool:
    return bool(matches) and all(term.label in COMMON_TERMS for term in matches)


def confidence_for(matches: list[Term]) -> str:
    if len(matches) >= 2 or any(term.priority >= 120 for term in matches):
        return "high"
    return "medium"


def match_guides_for_sr(sr_id: str, guide_files: list[GuideFile]) -> list[dict[str, Any]]:
    terms = terms_for_sr(sr_id)
    if not terms:
        return []

    scored: list[tuple[int, int, str, GuideFile, list[Term]]] = []
    for guide in guide_files:
        matched = [term for term in terms if re.search(term.pattern, guide.filename)]
        if not matched or is_common_only(matched):
            continue
        score = sum(term.priority for term in matched)
        scored.append((score, len(matched), guide.filename, guide, matched))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    results: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for _, _, _, guide, matched in scored:
        if guide.guide_code in seen_codes:
            continue
        seen_codes.add(guide.guide_code)
        results.append(
            {
                "guide_code": guide.guide_code,
                "short_code": guide.short_code,
                "filename": guide.filename,
                "matched_filename_terms": [term.label for term in matched],
                "confidence": confidence_for(matched),
            }
        )
        if len(results) >= MAX_GUIDES_PER_SR:
            break
    return results


def enrich_row(row: dict[str, Any], guide_files: list[GuideFile]) -> dict[str, Any]:
    out = dict(row)
    sr_mappings: list[dict[str, Any]] = []
    selected_codes: OrderedDict[str, None] = OrderedDict()

    for sr_id in row.get("selected_sr_ids", []):
        matched_guides = match_guides_for_sr(sr_id, guide_files)
        sr_mappings.append({"sr_id": sr_id, "matched_guides": matched_guides})
        for guide in matched_guides:
            selected_codes.setdefault(guide["guide_code"], None)

    out["selected_guide_codes"] = list(selected_codes.keys())
    out["sr_guide_mapping"] = sr_mappings
    out["guide_mapping_method"] = "filename_only"
    out["review_status"] = "proposed"
    return out


def main() -> None:
    rows = load_review_rows()
    guide_files = load_guide_files()
    enriched = [enrich_row(row, guide_files) for row in rows]

    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSONL.open("w", encoding="utf-8", newline="\n") as f:
        for row in enriched:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    with_guides = sum(1 for row in enriched if row["selected_guide_codes"])
    unique_guides = {
        guide_code
        for row in enriched
        for guide_code in row["selected_guide_codes"]
    }
    print(f"Loaded review rows: {len(rows)}")
    print(f"Loaded guide filenames: {len(guide_files)}")
    print(f"Rows with matched guides: {with_guides}")
    print(f"Unique matched guides: {len(unique_guides)}")
    print(f"Wrote: {OUTPUT_JSONL}")


if __name__ == "__main__":
    main()
