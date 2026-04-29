"""Phase 2.5 — Ground Truth 라벨링 Streamlit app (D14 — single file, ~150 LOC).

Phase 0 catalog 시나리오 100건 중 SCAFFOLD/EXCAVATION/MACHINE 33건을
사용자 본인이 직접 라벨링 → 시스템과 독립된 gold standard catalog 구축.

목적:
  - Day 5 결정 게이트 평가용 (SR Recall@10 ≥30% on gold)
  - Phase 6 최종 PASS 판정의 정직한 기준
  - 시스템 자기참조 (catalog 1) 문제 해결

UI:
  - 좌측: description + facets + metadata
  - 우측: SR rapidfuzz 검색 + 5-row picklist + Save→next
  - 하단: progress bar + labeler_notes

실행:
  pip install -r OHS/requirements-eval.txt  # streamlit, rapidfuzz 설치
  streamlit run OHS/scripts/eval/label_ground_truth.py

출력:
  OHS/data/eval/gold-truth-v1.jsonl
  - description + correct_srs[] + correct_cis[] + correct_guides[] + labeler_notes + timestamp
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# Optional: rapidfuzz (없으면 단순 substring search)
try:
    from rapidfuzz import process, fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

# DB connection (sr-registry에서 SR 검색용)
try:
    import psycopg2
    HAS_PG = True
except ImportError:
    HAS_PG = False

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS_FILE = ROOT / "OHS" / "data" / "eval" / "scenarios-v1.jsonl"
GOLD_FILE = ROOT / "OHS" / "data" / "eval" / "gold-truth-v1.jsonl"
SR_REGISTRY = ROOT / "koshaontology" / "pipe-C" / "data" / "sr-registry.json"
# 사용자 review 완료 파일 — v2 우선 사용 (selected_guide_codes 포함), v1 fallback
REVIEWED_FILE_V2 = ROOT / "OHS" / "data" / "eval" / "scenario-sr-description-reviewed-v2.jsonl"
REVIEWED_FILE_V1 = ROOT / "OHS" / "data" / "eval" / "scenario-sr-description-reviewed-v1.jsonl"
# Static SR → Guide default rules (확장 가능)
SR_GUIDE_RULES_FILE = ROOT / "OHS" / "data" / "eval" / "sr-guide-default-rules.json"

PILOT_WCS = {"SCAFFOLD", "EXCAVATION", "MACHINE"}


def normalize_guide_code(code: str) -> str:
    """Full guide_code (예: 'A-G-1-2025') → short_code (예: 'AG1').

    UI는 short_code 기준으로 체크박스 key/표시 구성하므로 v2의 selected_guide_codes
    (full)을 short로 변환해야 매칭 가능.
    """
    if not code:
        return ""
    parts = code.split("-")
    # 마지막 4자리 숫자(연도) 제거
    if parts and len(parts[-1]) == 4 and parts[-1].isdigit():
        parts = parts[:-1]
    return "".join(parts)


@st.cache_data
def load_scenarios() -> list[dict]:
    """100건 전체 시나리오 (Phase 0.2의 catalog) — pilot 3 wc 제한 해제.

    이유: scenario-sr-description-reviewed-v1.jsonl이 100건 전체에 대한 정답을 가지고 있어,
    사용자가 100건 모두 라벨링 가능 (Pilot 3 wc 제한 해제).
    """
    scenarios = []
    with SCENARIOS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            sc = json.loads(line)
            if sc.get("description"):
                scenarios.append(sc)
    return scenarios


@st.cache_data
def load_sr_guide_rules() -> dict[str, list[str]]:
    """SR → Guide static default rules 로드.

    Returns: sr_id → [guide_short_code, ...]
    """
    if not SR_GUIDE_RULES_FILE.exists():
        return {}
    try:
        data = json.loads(SR_GUIDE_RULES_FILE.read_text(encoding="utf-8"))
        result = {}
        for rule in data.get("rules", []):
            sr_id = rule.get("sr_id")
            guides = rule.get("default_guides", [])
            if sr_id and guides:
                result[sr_id] = list(guides)
        return result
    except Exception:
        return {}


@st.cache_data
def load_reviewed_default_srs() -> dict[str, dict]:
    """scenario-sr-description-reviewed-v{2|1}.jsonl 로드.

    v2 우선 사용 (selected_guide_codes 포함), v1 fallback.

    Returns: scenario_id → {
        selected_sr_ids: [...],
        selected_guide_codes_full: [...],   # v2: full guide_code (A-G-1-2025)
        selected_guide_codes_short: [...],  # short_code 변환 (AG1) — UI 매칭용
        evidence: [...],
        unmapped_facts: [...],
        review_status: ...,
        sr_guide_mapping: {...},            # v2 only: SR → Guide 세부 매핑
        version: 'v2' | 'v1'
    }
    """
    if REVIEWED_FILE_V2.exists():
        f = REVIEWED_FILE_V2
        version = "v2"
    elif REVIEWED_FILE_V1.exists():
        f = REVIEWED_FILE_V1
        version = "v1"
    else:
        return {}

    result = {}
    with f.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = d.get("scenario_id")
            if not sid:
                continue
            full_codes = d.get("selected_guide_codes", [])
            short_codes = [normalize_guide_code(c) for c in full_codes]
            result[sid] = {
                "selected_sr_ids": d.get("selected_sr_ids", []),
                "selected_guide_codes_full": full_codes,
                "selected_guide_codes_short": short_codes,
                "evidence": d.get("evidence", []),
                "unmapped_facts": d.get("unmapped_facts", []),
                "review_status": d.get("review_status"),
                "sr_guide_mapping": d.get("sr_guide_mapping", {}),
                "version": version,
            }
    return result


@st.cache_data
def load_sr_registry() -> list[dict]:
    """sr-registry.json 626 SR + title/text 검색용."""
    data = json.loads(SR_REGISTRY.read_text(encoding="utf-8"))
    return data.get("registry", [])


@st.cache_data
def load_sr_linked_map() -> dict[str, dict]:
    """SR identifier → {linkedCI[], linkedGuides[]} 인덱스."""
    data = json.loads(SR_REGISTRY.read_text(encoding="utf-8"))
    sr_map = {}
    for sr in data.get("registry", []):
        pb = sr.get("pipeB") or {}
        sr_map[sr["identifier"]] = {
            "linkedCI": pb.get("linkedCI") or [],
            "linkedGuides": pb.get("linkedGuides") or [],
        }
    return sr_map


@st.cache_data
def load_ci_titles() -> dict[str, str]:
    """PG checklist_items에서 CI text 일부 가져옴 (표시용)."""
    if not HAS_PG:
        return {}
    try:
        conn = psycopg2.connect("dbname=kosha user=kosha password=1229 host=localhost port=5432")
        cur = conn.cursor()
        cur.execute("SELECT identifier, LEFT(text, 80) FROM checklist_items")
        result = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        conn.close()
        return result
    except Exception:
        return {}


@st.cache_data
def load_guide_titles() -> dict[str, dict]:
    """PG kosha_guides → short_code(예: AG1) → {guide_code, title, pdf_path} 인덱스.

    sr-registry의 linkedGuides는 short_code (AG1) 형식이고
    PG primary key는 guide_code (A-G-1-2025) 형식이므로
    short_code 기준 lookup이 필요.
    """
    if not HAS_PG:
        return {}
    try:
        conn = psycopg2.connect("dbname=kosha user=kosha password=1229 host=localhost port=5432")
        cur = conn.cursor()
        cur.execute("SELECT short_code, guide_code, title, pdf_path FROM kosha_guides")
        result = {}
        for short_code, guide_code, title, pdf_path in cur.fetchall():
            result[short_code] = {
                "guide_code": guide_code,
                "title": (title or "")[:120],
                "pdf_path": pdf_path or "",
            }
        cur.close()
        conn.close()
        return result
    except Exception:
        return {}


def load_existing_gold() -> dict[str, dict]:
    """이미 라벨링된 gold-truth 로드 (resume)."""
    if not GOLD_FILE.exists():
        return {}
    by_id = {}
    with GOLD_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            by_id[row["scenario_id"]] = row
    return by_id


def append_gold(record: dict):
    """JSONL append (atomic)."""
    GOLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 이미 있으면 update, 없으면 append
    existing = load_existing_gold()
    existing[record["scenario_id"]] = record
    with GOLD_FILE.open("w", encoding="utf-8") as f:
        for r in existing.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def search_sr(srs: list[dict], query: str, limit: int = 20) -> list[dict]:
    """SR title + text fuzzy 검색."""
    if not query.strip():
        return srs[:limit]
    if HAS_RAPIDFUZZ:
        # rapidfuzz의 process.extract 사용
        keys = [f"{s['identifier']} {s.get('title', '')} {s.get('text', '')[:100]}" for s in srs]
        matches = process.extract(query, keys, scorer=fuzz.WRatio, limit=limit)
        return [srs[i] for _, _, i in matches]
    else:
        # substring fallback
        q_lower = query.lower()
        matched = [s for s in srs if q_lower in (s["identifier"] + s.get("title", "") + s.get("text", "")).lower()]
        return matched[:limit]


# ────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="OHS Ground Truth Labeling", layout="wide")
st.title("OHS Phase 2.5 — Ground Truth Labeling")
st.caption(f"100 시나리오 전체 (reviewed default 보유) | Output: `{GOLD_FILE.relative_to(ROOT)}`")

scenarios = load_scenarios()
srs = load_sr_registry()
sr_linked_map = load_sr_linked_map()
ci_titles = load_ci_titles()
guide_titles = load_guide_titles()
existing_gold = load_existing_gold()
reviewed_default = load_reviewed_default_srs()
sr_guide_rules = load_sr_guide_rules()
# SR identifier → SR dict 인덱스 (검색 결과에 없어도 lookup 가능)
sr_by_id = {s["identifier"]: s for s in srs}

st.sidebar.header(f"Progress: {len(existing_gold)}/{len(scenarios)}")
st.sidebar.progress(len(existing_gold) / max(len(scenarios), 1))

# Scenario picker
labeled_ids = set(existing_gold.keys())
unlabeled = [sc for sc in scenarios if sc["scenario_id"] not in labeled_ids]
all_options = [f"{sc['scenario_id']} ({sc['work_context']}, {sc['source']})" + (" ✓" if sc["scenario_id"] in labeled_ids else "")
               for sc in scenarios]
default_idx = 0
if unlabeled:
    next_id = unlabeled[0]["scenario_id"]
    default_idx = next(i for i, sc in enumerate(scenarios) if sc["scenario_id"] == next_id)

selected_idx = st.sidebar.radio("Select scenario:", range(len(scenarios)),
                                 format_func=lambda i: all_options[i],
                                 index=default_idx)
sc = scenarios[selected_idx]
existing = existing_gold.get(sc["scenario_id"])

# Two-column layout — 두 column 모두 fixed height + 자체 scroll
# (페이지 자체 scroll로 description이 위로 사라지는 문제 해결)
col_left, col_right = st.columns([1, 1])

with col_left.container(height=900, border=True):
    st.subheader(f"📷 {sc['scenario_id']}")
    st.markdown(f"**work_context:** `{sc['work_context']}`  | **source:** `{sc['source']}`")
    st.markdown("**Description (GPT-4o synthesized):**")
    st.info(sc["description"])

    facets = sc.get("primary_facets", {})
    st.markdown("**Faceted hints:**")
    st.write(f"- accident_types: `{facets.get('accident_types', [])}`")
    st.write(f"- hazardous_agents: `{facets.get('hazardous_agents', [])}`")
    st.write(f"- work_contexts: `{facets.get('work_contexts', [])}`")

    md = sc.get("metadata", {})
    if md:
        with st.expander("Catalog metadata (참조용 — Bundle source)"):
            st.json(md)

    gt = sc.get("ground_truth", {})
    with st.expander("Catalog ground_truth (참조용 — 시스템 출력 derived)"):
        st.write(f"- sr_set ({len(gt.get('sr_set', []))}): {gt.get('sr_set', [])}")
        st.write(f"- guide_set ({len(gt.get('guide_set', []))}): {gt.get('guide_set', [])[:10]}{'...' if len(gt.get('guide_set', [])) > 10 else ''}")

with col_right.container(height=900, border=True):
    st.subheader("✏️ Label as Domain Expert")

    # ── Selection state persistence (Fix 2: 검색어 변경 시 선택 손실 방지) ──
    # session_state 키: scenario_id 별로 분리
    sel_key = f"selected_srs_{sc['scenario_id']}"
    init_key = f"init_done_{sc['scenario_id']}"
    if sel_key not in st.session_state:
        # 초기값 우선순위: 1) gold-truth-v1.jsonl 저장된 라벨 → 2) reviewed-v1.jsonl default → 3) empty
        if existing and existing.get("correct_srs"):
            initial = set(existing["correct_srs"])
            init_source = "기존 라벨 resume"
        elif sc["scenario_id"] in reviewed_default:
            initial = set(reviewed_default[sc["scenario_id"]]["selected_sr_ids"])
            init_source = "reviewed-v1.jsonl default"
        else:
            initial = set()
            init_source = "empty"
        st.session_state[sel_key] = initial
        st.session_state[init_key] = init_source

    selected_set: set[str] = st.session_state[sel_key]
    if selected_set:
        st.caption(f"💾 Source: {st.session_state.get(init_key, '?')} ({len(selected_set)} SRs)")

    # Reviewed evidence 표시 (선택 판단 도움)
    if sc["scenario_id"] in reviewed_default:
        with st.expander("📌 Review evidence (사전 review 결과 — 각 SR의 매칭 근거)", expanded=False):
            rev = reviewed_default[sc["scenario_id"]]
            for ev in rev.get("evidence", []):
                facts = ev.get("matched_description_facts") or []
                st.write(f"**`{ev.get('sr_id')}`** ({ev.get('confidence')}) — {ev.get('title', '')[:80]}")
                for f in facts:
                    st.caption(f"  → {f}")
            unm = rev.get("unmapped_facts") or []
            if unm:
                st.markdown("**unmapped_facts (매핑 누락):**")
                for f in unm:
                    st.caption(f"  ⚠ {f}")

    query = st.text_input("SR 검색 (title/text/id fuzzy):",
                          placeholder="예: 비계, 안전대, 추락방지",
                          key=f"sr_search_{sc['scenario_id']}")
    matched_srs = search_sr(srs, query, limit=15)
    matched_ids = {s["identifier"] for s in matched_srs}

    # ── Section 1: 이미 선택된 SR (검색 결과 무관 — 검색 변경에도 유지) ──
    if selected_set:
        st.markdown(f"**✅ 선택된 SR ({len(selected_set)}) — 검색 결과 무관:**")
        for sr_id in sorted(selected_set):
            sr_info = sr_by_id.get(sr_id, {})
            title = sr_info.get("title", "(SR registry에 없음)")
            ck = st.checkbox(
                f"`{sr_id}` — {title[:80]}",
                value=True,
                key=f"selected_sr_{sr_id}_{sc['scenario_id']}",
            )
            if not ck:
                # 체크 해제 → set에서 제거 + rerun
                selected_set.discard(sr_id)
                st.session_state[sel_key] = selected_set
                st.rerun()

    # ── Section 2: 검색 결과 (이미 선택된 것 제외) ──
    new_matches = [s for s in matched_srs if s["identifier"] not in selected_set]
    if new_matches:
        st.markdown(f"**🔍 검색 결과 ({len(new_matches)}) — 추가 선택:**")
        for s in new_matches:
            ck = st.checkbox(
                f"`{s['identifier']}` — {s.get('title', '')[:80]}",
                value=False,
                key=f"unselected_sr_{s['identifier']}_{sc['scenario_id']}",
            )
            if ck:
                # 체크 → set에 추가 + rerun
                selected_set.add(s["identifier"])
                st.session_state[sel_key] = selected_set
                st.rerun()
    elif query:
        st.caption(f"(검색 결과가 모두 이미 선택됨)")

    selected_sr_ids = sorted(selected_set)

    # ── CI는 가이드 종속 단위 (사용자 통찰): Guide 위주 라벨링, CI는 readonly 참고용 ──
    st.markdown("---")
    st.markdown(f"**📚 선택된 SR ({len(selected_sr_ids)}개)의 정답 Guide(절차)를 선택하세요:**")
    st.caption("💡 CI는 가이드의 implementation detail — 가이드 선택 시 자동으로 평가에 follow됩니다.")

    # 자동 collected — SR linkedGuides
    auto_cis: dict[str, set[str]] = {}    # ci_id → {sr_id, ...}
    auto_guides: dict[str, set[str]] = {}  # short_code → {sr_id 또는 "reviewed-v2"}
    for sr_id in selected_sr_ids:
        linked = sr_linked_map.get(sr_id, {})
        for ci in linked.get("linkedCI", []):
            auto_cis.setdefault(ci, set()).add(sr_id)
        for g in linked.get("linkedGuides", []):
            auto_guides.setdefault(g, set()).add(sr_id)

    # 기존 라벨링 시 저장된 list (resume 시 default)
    prev_guides = set(existing.get("correct_guides", [])) if existing else set()

    # reviewed-v2의 selected_guide_codes (short) — 처음 라벨링 시 default 체크
    rev_v2_default_guides: set[str] = set()
    if sc["scenario_id"] in reviewed_default:
        rev_v2_default_guides = set(reviewed_default[sc["scenario_id"]].get("selected_guide_codes_short", []))

    # Static SR→Guide rules (예: SR-WORKPLACE-001 → G11)
    rule_default_guides: set[str] = set()
    rule_source_by_guide: dict[str, set[str]] = {}  # guide → {sr_id, ...} 출처 추적
    for sr_id in selected_sr_ids:
        for g in sr_guide_rules.get(sr_id, []):
            rule_default_guides.add(g)
            rule_source_by_guide.setdefault(g, set()).add(sr_id)

    # 처음 라벨링 시 default 체크되어야 할 가이드 = v2 ∪ rule
    initial_default_guides = rev_v2_default_guides | rule_default_guides

    # default 가이드 중 SR-linkedGuides에 없는 것도 화면에 표시
    # (v2 review 또는 static rule이 명시적으로 추가한 가이드)
    for g in initial_default_guides:
        if g not in auto_guides:
            # 출처 표시: rule이 있으면 SR ID, 그렇지 않으면 reviewed-v2
            if g in rule_source_by_guide:
                auto_guides[g] = {f"rule:{','.join(sorted(rule_source_by_guide[g]))}"}
            else:
                auto_guides[g] = {"reviewed-v2"}

    # Guide 체크박스 (1급 시민 — 라벨링 핵심 단위)
    selected_guides: list[str] = []
    if auto_guides:
        for short_code in sorted(auto_guides.keys()):
            src_srs = ", ".join(sorted(auto_guides[short_code]))
            # PG에서 풍부한 정보 (full guide_code + title + pdf_path)
            info = guide_titles.get(short_code, {})
            if info:
                full_code = info.get("guide_code", "")
                title = info.get("title", "")
                pdf_path = info.get("pdf_path", "")
                # 사용자 요청 형식: AG1 (A-G-1-2025 추락방호망 설치 기술지원규정.pdf) ← SR: ...
                if pdf_path:
                    label = f"`{short_code}` — `{pdf_path}` ← SR: {src_srs}"
                else:
                    label = f"`{short_code}` ({full_code}) {title} ← SR: {src_srs}"
            else:
                label = f"`{short_code}` ← SR: {src_srs}"
            # default 우선순위:
            #   1. resume (existing gold-truth) → prev_guides
            #   2. 처음 + (reviewed-v2 default ∪ static rule) → ON
            #   3. 그 외 → OFF (사용자가 추가 선택)
            if existing:
                is_default = short_code in prev_guides
            else:
                is_default = short_code in initial_default_guides
            ck = st.checkbox(
                label,
                value=is_default,
                key=f"guide_{short_code}_{sc['scenario_id']}",
            )
            if ck:
                selected_guides.append(short_code)

    # 추가 Guide 자유 입력 (sr-registry에 없는 가이드)
    with st.expander("➕ 추가 Guide 자유 입력 (자동 link에 없는 가이드)"):
        extra_guides = st.text_area(
            "Guide codes (comma/줄바꿈 separated):",
            value="",
            height=60,
            key=f"extra_g_{sc['scenario_id']}",
        )

    # CI는 readonly 참고용 (가이드 종속이므로 개별 라벨링 X)
    if selected_guides and ci_titles:
        # short_code (AG1) → full guide_code (A-G-1-2025) 변환 (PG checklist_items.source_guide는 full code)
        full_codes = [
            guide_titles[sc].get("guide_code", "")
            for sc in selected_guides
            if sc in guide_titles and guide_titles[sc].get("guide_code")
        ]
        with st.expander(f"📋 [참고] 선택된 Guide에 종속된 CI (개별 라벨링 X — Guide 평가 시 자동 follow)", expanded=False):
            st.caption("이 CI들은 정답 평가에서 자동으로 산입됩니다. 직접 선택할 필요 없습니다.")
            if full_codes:
                try:
                    conn = psycopg2.connect("dbname=kosha user=kosha password=1229 host=localhost port=5432")
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT identifier, LEFT(text, 100) FROM checklist_items
                        WHERE source_guide = ANY(%s)
                        ORDER BY identifier LIMIT 30
                    """, (full_codes,))
                    rows = cur.fetchall()
                    cur.close()
                    conn.close()
                    st.write(f"가이드 {len(full_codes)}개 → CI {len(rows)}건 (앞 30개만 표시):")
                    for r in rows:
                        st.write(f"  • `{r[0]}` — {r[1]}")
                except Exception as e:
                    st.write(f"(PG 조회 실패: {e})")

    labeler_notes = st.text_area(
        "Labeler notes (모호함/근거/판단 이유 등):",
        value=existing.get("labeler_notes", "") if existing else "",
        height=120,
    )

    if st.button("💾 Save & next", type="primary"):
        # Guide만 라벨링 (CI는 자동 follow). 자유 입력 추가 가이드 합침.
        extra_guide_list = [g.strip() for g in extra_guides.replace("\n", ",").split(",") if g.strip()]
        guides = sorted(set(selected_guides) | set(extra_guide_list))
        # CI는 빈 list (Guide-derived 자동 평가)
        cis: list[str] = []
        record = {
            "scenario_id": sc["scenario_id"],
            "work_context": sc["work_context"],
            "source": sc["source"],
            "description": sc["description"],
            "correct_srs": selected_sr_ids,
            "correct_guides": guides,
            "correct_cis": cis,  # deprecated: empty (CI는 Guide-derived 자동 follow)
            "labeling_schema": "v2_guide_centric",  # CI는 Guide 종속 단위로 변경 (2026-04-27)
            "labeler_notes": labeler_notes,
            "labeled_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "labeler": os.environ.get("USER", os.environ.get("USERNAME", "anonymous")),
        }
        append_gold(record)
        # session_state 유지 — 다음 시나리오 자동 선택 시에도 자기 키만 사용하므로 OK
        st.success(f"✅ Saved {sc['scenario_id']} ({len(selected_sr_ids)} SRs, {len(guides)} Guides) — CI는 Guide-derived 자동 평가")
        st.rerun()

st.markdown("---")
st.caption(f"⚠ rapidfuzz: {'enabled' if HAS_RAPIDFUZZ else 'disabled (substring fallback)'} | "
           f"📁 Gold file: `{GOLD_FILE}`")
