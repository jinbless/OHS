#!/usr/bin/env python3
"""Phase 0.1 — Bundle 통합: 7개 source → catalog-v1.jsonl

7 sources:
  S1 R-2 coApplicable      → kosha-instances-v2-pilot.ttl (94 pair → cluster)
  S2 PA-11 sr:guidedBy     → sr-registry.json linkedGuides (Guide 단위 cluster)
  S3 sr-registry           → 626 SR + linkedCI/linkedGuides (SR 중심 bundle)
  S4 ci_sr_mapping (PG)    → SR ↔ CI matrix (CI 중심 bundle)
  S5 guide_inter_links     → Guide ↔ Guide (인용 네트워크)
  S6 Faceted 3축 (PG)      → (accident_type, hazardous_agent, work_context) tuple cluster
  S7 Paragraph cluster     → pilot v2 SR (paragraphKey 단위)

Output:
  OHS/data/eval/catalog-v1.jsonl  (한 줄에 한 Bundle 객체)

Bundle schema:
  {
    "bundle_id": "BD-{SOURCE}-{seq:04d}",
    "source": "R2|PA11|SR_REGISTRY|CI_MAPPING|GUIDE_INTERLINK|FACETED|PARAGRAPH",
    "sr_set": [...],
    "ci_set": [...],
    "guide_set": [...],
    "primary_facets": {"accident_types": [], "hazardous_agents": [], "work_contexts": []},
    "metadata": {...}
  }

실행:
  PYTHONUTF8=1 python OHS/scripts/eval/build_catalog.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[3]  # arch-bot/
KOSHA = ROOT / "koshaontology"
OHS = ROOT / "OHS"

SR_REGISTRY = KOSHA / "pipe-C" / "data" / "sr-registry.json"
GUIDE_INTERLINKS = KOSHA / "pipe-C" / "data" / "guide-interlinks.json"
PILOT_TTL = KOSHA / "pipe-A" / "data" / "pilot" / "kosha-instances-v2-pilot.ttl"
PILOT_SR_DIR = KOSHA / "pipe-A" / "data" / "pilot" / "safety-requirements-v2"

OUTPUT = OHS / "data" / "eval" / "catalog-v1.jsonl"

PG_DSN = "dbname=kosha user=kosha password=1229 host=localhost port=5432"


# ────────────────────────────────────────────────────────────────────────
# Source 1: R-2 coApplicable from TTL
# ────────────────────────────────────────────────────────────────────────

# `sr:SR-PILOT_X-001 ... kosha:coApplicable sr:SR-PILOT_X-002, sr:SR-PILOT_X-003 ;`
# Parse TTL block by block.
SR_BLOCK_RE = re.compile(
    r"sr:(SR-PILOT_[A-Z_]+-\d+)\s+a\s+sr:SafetyRequirement\s*;(.*?)(?=\n\nsr:|\Z)",
    re.DOTALL,
)
COAPP_RE = re.compile(r"kosha:coApplicable\s+((?:sr:SR-PILOT_[A-Z_]+-\d+\s*,?\s*)+)\s*;")
SR_REF_RE = re.compile(r"sr:(SR-PILOT_[A-Z_]+-\d+)")
ARTICLE_RE = re.compile(r"sr:directlyAppliesToArticle\s+law:RULE_(제\d+조(?:의\d+)?)")
HAZARD_RE = re.compile(r"sr:addressesHazard\s+hazard:([A-Z_]+)")


def load_r2_clusters() -> list[dict[str, Any]]:
    """R-2 coApplicable에서 SR 클러스터 추출.

    같은 article을 공유하는 SR들이 자연 cluster (paragraph 단위 chunking 결과).
    coApplicable 양방향 그래프 → connected component → cluster.
    """
    text = PILOT_TTL.read_text(encoding="utf-8")
    # cluster: article → set(SR)
    article_to_srs: dict[str, set[str]] = defaultdict(set)
    sr_to_hazard: dict[str, str] = {}

    for m in SR_BLOCK_RE.finditer(text):
        sr_id = m.group(1)
        body = m.group(2)
        art_m = ARTICLE_RE.search(body)
        haz_m = HAZARD_RE.search(body)
        if art_m:
            article_to_srs[art_m.group(1)].add(sr_id)
        if haz_m:
            sr_to_hazard[sr_id] = haz_m.group(1)

    bundles: list[dict[str, Any]] = []
    for seq, (article, sr_set) in enumerate(sorted(article_to_srs.items()), start=1):
        if len(sr_set) < 2:
            continue  # cluster는 ≥2
        hazards = sorted({sr_to_hazard.get(sr) for sr in sr_set if sr_to_hazard.get(sr)})
        bundles.append({
            "bundle_id": f"BD-R2-{seq:04d}",
            "source": "R2",
            "sr_set": sorted(sr_set),
            "ci_set": [],
            "guide_set": [],
            "primary_facets": {
                "accident_types": [],
                "hazardous_agents": [],
                "work_contexts": [],
            },
            "metadata": {
                "article": article,
                "hazards_legacy": hazards,
                "sr_count": len(sr_set),
            },
        })
    return bundles


# ────────────────────────────────────────────────────────────────────────
# Source 2: PA-11 (sr:guidedBy) from sr-registry linkedGuides
# ────────────────────────────────────────────────────────────────────────

def load_pa11_clusters(registry: list[dict]) -> list[dict[str, Any]]:
    """같은 Guide를 공유하는 SR들이 자연 cluster (PA-11 sr:guidedBy)."""
    guide_to_srs: dict[str, list[str]] = defaultdict(list)
    sr_to_hazard: dict[str, list[str]] = {}
    for entry in registry:
        sr_id = entry["identifier"]
        sr_to_hazard[sr_id] = entry.get("addressesHazard") or []
        for g in (entry.get("pipeB") or {}).get("linkedGuides") or []:
            guide_to_srs[g].append(sr_id)

    bundles: list[dict[str, Any]] = []
    for seq, (guide, sr_list) in enumerate(sorted(guide_to_srs.items()), start=1):
        if len(sr_list) < 2:
            continue
        haz_union = sorted({h for sr in sr_list for h in sr_to_hazard.get(sr, [])})
        bundles.append({
            "bundle_id": f"BD-PA11-{seq:04d}",
            "source": "PA11",
            "sr_set": sorted(set(sr_list)),
            "ci_set": [],
            "guide_set": [guide],
            "primary_facets": {
                "accident_types": [],
                "hazardous_agents": [],
                "work_contexts": [],
            },
            "metadata": {
                "guide_code": guide,
                "hazards_legacy": haz_union,
                "sr_count": len(set(sr_list)),
            },
        })
    return bundles


# ────────────────────────────────────────────────────────────────────────
# Source 3: sr-registry (SR 중심 — 1 SR + linked CI/Guide)
# ────────────────────────────────────────────────────────────────────────

def load_sr_registry_bundles(registry: list[dict]) -> list[dict[str, Any]]:
    """SR 중심 bundle: 1 SR + 그 SR의 모든 linkedCI[]/linkedGuides[]."""
    bundles: list[dict[str, Any]] = []
    for seq, entry in enumerate(registry, start=1):
        pb = entry.get("pipeB") or {}
        ci_set = sorted(set(pb.get("linkedCI") or []))
        guide_set = sorted(set(pb.get("linkedGuides") or []))
        if not ci_set and not guide_set:
            continue  # 비어있는 bundle은 skip
        bundles.append({
            "bundle_id": f"BD-SRREG-{seq:04d}",
            "source": "SR_REGISTRY",
            "sr_set": [entry["identifier"]],
            "ci_set": ci_set,
            "guide_set": guide_set,
            "primary_facets": {
                "accident_types": [],
                "hazardous_agents": [],
                "work_contexts": [],
            },
            "metadata": {
                "sr_title": entry.get("title", "")[:120],
                "addressesHazard": entry.get("addressesHazard") or [],
                "ci_count": len(ci_set),
                "guide_count": len(guide_set),
                "industries": (pb.get("applicableIndustry") or []),
            },
        })
    return bundles


# ────────────────────────────────────────────────────────────────────────
# Source 4: ci_sr_mapping (PG) → CI 중심 bundle
# ────────────────────────────────────────────────────────────────────────

def load_ci_mapping_bundles(conn) -> list[dict[str, Any]]:
    """1 CI ↔ 매핑된 모든 SR (CI 한 항목이 여러 SR을 호출하는 경우의 자연 cluster)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ci_id, ARRAY_AGG(DISTINCT sr_id ORDER BY sr_id) AS srs
        FROM ci_sr_mapping
        WHERE sr_id IS NOT NULL
        GROUP BY ci_id
        HAVING COUNT(DISTINCT sr_id) >= 2
        ORDER BY ci_id
    """)
    rows = cur.fetchall()
    cur.close()
    bundles: list[dict[str, Any]] = []
    for seq, (ci_id, srs) in enumerate(rows, start=1):
        bundles.append({
            "bundle_id": f"BD-CIMAP-{seq:04d}",
            "source": "CI_MAPPING",
            "sr_set": list(srs),
            "ci_set": [ci_id],
            "guide_set": [],
            "primary_facets": {
                "accident_types": [],
                "hazardous_agents": [],
                "work_contexts": [],
            },
            "metadata": {"sr_count": len(srs)},
        })
    return bundles


# ────────────────────────────────────────────────────────────────────────
# Source 5: guide_inter_links → 가이드 인용 네트워크
# ────────────────────────────────────────────────────────────────────────

def load_guide_interlink_bundles(registry: list[dict]) -> list[dict[str, Any]]:
    """Guide A → Guide B 인용 시 두 가이드의 SR/CI union (이슈 인접 시나리오)."""
    text = GUIDE_INTERLINKS.read_text(encoding="utf-8")
    data = json.loads(text)
    links = data.get("interLinks") or data.get("links") or data.get("rows") or []
    # 가이드 → SR 매핑 (linkedGuides 역방향)
    guide_to_srs: dict[str, set[str]] = defaultdict(set)
    sr_to_ci: dict[str, set[str]] = {}
    for entry in registry:
        sr_id = entry["identifier"]
        pb = entry.get("pipeB") or {}
        sr_to_ci[sr_id] = set(pb.get("linkedCI") or [])
        for g in pb.get("linkedGuides") or []:
            guide_to_srs[g].add(sr_id)

    bundles: list[dict[str, Any]] = []
    seq = 1
    seen: set[tuple] = set()
    for link in links:
        src = link.get("sourceGuide") or link.get("source_guide") or link.get("source")
        ref = link.get("referencedGuide") or link.get("referenced_guide") or link.get("target")
        if not (src and ref) or src == ref:
            continue
        key = tuple(sorted([src, ref]))
        if key in seen:
            continue
        seen.add(key)
        sr_union = guide_to_srs.get(src, set()) | guide_to_srs.get(ref, set())
        if len(sr_union) < 2:
            continue
        ci_union = sorted({c for sr in sr_union for c in sr_to_ci.get(sr, set())})
        bundles.append({
            "bundle_id": f"BD-GIL-{seq:04d}",
            "source": "GUIDE_INTERLINK",
            "sr_set": sorted(sr_union),
            "ci_set": ci_union,
            "guide_set": sorted([src, ref]),
            "primary_facets": {
                "accident_types": [],
                "hazardous_agents": [],
                "work_contexts": [],
            },
            "metadata": {
                "source_guide": src,
                "referenced_guide": ref,
                "sr_count": len(sr_union),
                "reference_type": link.get("referenceType") or link.get("reference_type"),
            },
        })
        seq += 1
    return bundles


# ────────────────────────────────────────────────────────────────────────
# Source 6: Faceted 3축 (PG) → (accident, hazardous_agent, work_context) tuple cluster
# ────────────────────────────────────────────────────────────────────────

def load_faceted_bundles(conn) -> list[dict[str, Any]]:
    """동일한 (accident_types, hazardous_agents, work_contexts) tuple을 공유하는
    SR/CI 묶음 → top N 빈도 조합 위주로 cluster 생성.
    """
    cur = conn.cursor()
    # 단일 조합으로 공유되는 SR과 그에 매핑된 CI 모음
    cur.execute("""
        WITH sr_grp AS (
          SELECT
            COALESCE(accident_types::text,    '[]') AS at,
            COALESCE(hazardous_agents::text,  '[]') AS ha,
            COALESCE(work_contexts::text,     '[]') AS wc,
            ARRAY_AGG(DISTINCT identifier ORDER BY identifier) AS srs,
            COUNT(*) AS sr_count
          FROM safety_requirements
          WHERE accident_types IS NOT NULL
             OR hazardous_agents IS NOT NULL
             OR work_contexts IS NOT NULL
          GROUP BY 1, 2, 3
          HAVING COUNT(*) >= 2
        )
        SELECT at, ha, wc, srs, sr_count
        FROM sr_grp
        ORDER BY sr_count DESC
        LIMIT 200
    """)
    rows = cur.fetchall()

    # 각 조합 cluster의 SR들에 매핑된 CI 수집
    bundles: list[dict[str, Any]] = []
    for seq, (at_text, ha_text, wc_text, srs, sr_count) in enumerate(rows, start=1):
        try:
            at = json.loads(at_text) if at_text else []
            ha = json.loads(ha_text) if ha_text else []
            wc = json.loads(wc_text) if wc_text else []
        except json.JSONDecodeError:
            at, ha, wc = [], [], []
        if not (at or ha or wc):
            continue
        # 매핑된 CI도 가져옴
        cur.execute("""
            SELECT ARRAY_AGG(DISTINCT ci_id ORDER BY ci_id)
            FROM ci_sr_mapping
            WHERE sr_id = ANY(%s)
        """, (list(srs),))
        ci_row = cur.fetchone()
        ci_set = list(ci_row[0]) if ci_row and ci_row[0] else []
        bundles.append({
            "bundle_id": f"BD-FACET-{seq:04d}",
            "source": "FACETED",
            "sr_set": list(srs),
            "ci_set": ci_set,
            "guide_set": [],
            "primary_facets": {
                "accident_types": at,
                "hazardous_agents": ha,
                "work_contexts": wc,
            },
            "metadata": {"sr_count": int(sr_count), "rank_by_freq": seq},
        })
    cur.close()
    return bundles


# ────────────────────────────────────────────────────────────────────────
# Source 7: Paragraph cluster (pilot v2)
# ────────────────────────────────────────────────────────────────────────

PARA_NORM_RE = re.compile(r"^(제\d+조(?:의\d+)? 제\d+항)")


def normalize_para(title_or_para_ref: str | None) -> str | None:
    if not title_or_para_ref:
        return None
    m = PARA_NORM_RE.match(title_or_para_ref)
    return m.group(1) if m else None


def load_paragraph_bundles() -> list[dict[str, Any]]:
    """pilot v2 SR을 paragraph 단위로 cluster (4.2 SR/article 평균)."""
    para_to_srs: dict[str, list[str]] = defaultdict(list)
    sr_to_hazard: dict[str, list[str]] = {}
    sr_to_title: dict[str, str] = {}
    for f in sorted(PILOT_SR_DIR.glob("sr-batch-PILOT-*.json")):
        if f.name.endswith("-input.json"):
            continue  # input 파일 skip
        data = json.loads(f.read_text(encoding="utf-8"))
        for sr in data.get("safetyRequirements", []):
            sid = sr["identifier"]
            title = sr.get("title", "")
            sr_to_title[sid] = title
            sr_to_hazard[sid] = sr.get("addressesHazard") or []
            para_key = normalize_para(title)
            if not para_key:
                # paragraphKey field가 있으면 그것을 사용
                para_key = sr.get("paragraphKey")
            if para_key:
                para_to_srs[para_key].append(sid)

    bundles: list[dict[str, Any]] = []
    for seq, (para, srs) in enumerate(sorted(para_to_srs.items()), start=1):
        if len(srs) < 2:
            continue
        haz = sorted({h for s in srs for h in sr_to_hazard.get(s, [])})
        bundles.append({
            "bundle_id": f"BD-PARA-{seq:04d}",
            "source": "PARAGRAPH",
            "sr_set": sorted(set(srs)),
            "ci_set": [],
            "guide_set": [],
            "primary_facets": {
                "accident_types": [],
                "hazardous_agents": [],
                "work_contexts": [],
            },
            "metadata": {
                "paragraph_key": para,
                "hazards_legacy": haz,
                "sr_count": len(set(srs)),
            },
        })
    return bundles


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"[INFO] arch-bot root: {ROOT}")
    print(f"[INFO] output: {OUTPUT}")

    # Load sr-registry once
    print(f"[INFO] sr-registry.json 로딩...")
    registry_data = json.loads(SR_REGISTRY.read_text(encoding="utf-8"))
    registry = registry_data.get("registry", [])
    print(f"[INFO]   {len(registry)} SR 항목 로딩")

    # PG 연결
    import psycopg2
    print(f"[INFO] PG 연결: {PG_DSN}")
    conn = psycopg2.connect(PG_DSN)
    print(f"[INFO]   연결 OK")

    all_bundles: list[dict[str, Any]] = []

    # S1
    print("\n[S1] R-2 coApplicable...")
    b = load_r2_clusters()
    all_bundles.extend(b)
    print(f"     {len(b)} bundles")

    # S2
    print("[S2] PA-11 sr:guidedBy (linkedGuides 기반)...")
    b = load_pa11_clusters(registry)
    all_bundles.extend(b)
    print(f"     {len(b)} bundles")

    # S3
    print("[S3] sr-registry (SR 중심)...")
    b = load_sr_registry_bundles(registry)
    all_bundles.extend(b)
    print(f"     {len(b)} bundles")

    # S4
    print("[S4] ci_sr_mapping (PG)...")
    try:
        b = load_ci_mapping_bundles(conn)
        all_bundles.extend(b)
        print(f"     {len(b)} bundles")
    except Exception as e:
        print(f"     [WARN] PG ci_sr_mapping skip: {e}")

    # S5
    print("[S5] guide_inter_links...")
    b = load_guide_interlink_bundles(registry)
    all_bundles.extend(b)
    print(f"     {len(b)} bundles")

    # S6
    print("[S6] Faceted 3축 (PG)...")
    try:
        b = load_faceted_bundles(conn)
        all_bundles.extend(b)
        print(f"     {len(b)} bundles")
    except Exception as e:
        print(f"     [WARN] PG faceted skip: {e}")

    # S7
    print("[S7] Paragraph cluster (pilot v2)...")
    b = load_paragraph_bundles()
    all_bundles.extend(b)
    print(f"     {len(b)} bundles")

    conn.close()

    # 출력
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        for bundle in all_bundles:
            fh.write(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n")

    # 통계 요약
    print(f"\n[OK] catalog-v1.jsonl 생성 완료")
    print(f"     총 {len(all_bundles)} bundles")
    by_source = defaultdict(int)
    for bd in all_bundles:
        by_source[bd["source"]] += 1
    for s, c in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"     {s:18s} {c:>6d}")

    # 샘플
    print(f"\n[샘플 3건]")
    for bd in all_bundles[:3]:
        sr_n = len(bd["sr_set"])
        ci_n = len(bd["ci_set"])
        g_n = len(bd["guide_set"])
        print(f"  {bd['bundle_id']:22s}  SR={sr_n:3d}  CI={ci_n:5d}  G={g_n:2d}  src={bd['source']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
