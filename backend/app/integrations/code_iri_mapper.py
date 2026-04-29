"""Phase 0.5 — Code → OWL URI Mapping Layer (Critical)

OHS의 Track B faceted 코드 (UPPER_CASE/SNAKE_CASE)와 실제 OWL/TTL의
NamedIndividual URI (CamelCase) 사이의 결정론적 매핑.

문제 (Phase 0 baseline에서 발견):
  OHS code "SCAFFOLD" → SPARQL `context:SCAFFOLD` (잘못)
  OWL 실제 URI         → `context:Scaffold` (정답)
  → 매칭 실패 → SR Recall@10 0%의 큰 원인 중 하나

해결: 이 mapper를 통해 OHS code → 실제 IRI fragment 변환.
SHE도 이 mapper로 8 dim 코드 → IRI 변환 (Phase 3 Layer 0).

검증 출처:
  - kosha-ontology.owl L146 (hazard:AccidentType, 8개)
  - kosha-ontology.owl L160 (agent:HazardousAgent, 11개)
  - kosha-ontology.owl L177 (context:WorkContext, 13개)
"""
from __future__ import annotations

# ────────────────────────────────────────────────────────────────────────
# accident_type — hazard:AccidentType (8 NamedIndividuals)
# ────────────────────────────────────────────────────────────────────────
ACCIDENT_TYPE_CODE_TO_URI: dict[str, str] = {
    # OHS code (UPPER_CASE) → OWL fragment (CamelCase)
    "FALL":           "Fall",
    "SLIP":           "Slip",            # FALL의 sub
    "COLLISION":      "Collision",       # legacy STRUCK_BY 일부
    "FALLING_OBJECT": "FallingObject",   # legacy STRUCK_BY 일부
    "CRUSH":          "Crush",           # legacy CAUGHT_IN
    "CUT":            "Cut",             # legacy CAUGHT_IN
    "COLLAPSE":       "Collapse",
    "ERGONOMIC":      "Ergonomic",
    # Legacy fallback (3축 도입 전 1축 hazard:Hazard에 매핑)
    # 이들은 hazard:AccidentType에 없으므로 hazard:Hazard로 fallback
    "STRUCK_BY":           None,  # 사용 시 legacy_map (COLLISION 또는 FALLING_OBJECT)
    "CAUGHT_IN":           None,  # CRUSH 또는 CUT
    "FIRE_EXPLOSION":      None,  # agent:Fire로 우회
    "ELECTRIC_SHOCK":      None,  # agent:Electricity로 우회
    "CHEMICAL_EXPOSURE":   None,  # agent:Chemical로 우회
    "NOISE_VIBRATION":     None,  # agent:Noise로 우회
    "CONFINED_SPACE":      None,  # context:ConfinedSpace로 우회
}

# ────────────────────────────────────────────────────────────────────────
# hazardous_agent — agent:HazardousAgent (11 NamedIndividuals)
# ────────────────────────────────────────────────────────────────────────
HAZARDOUS_AGENT_CODE_TO_URI: dict[str, str] = {
    "CHEMICAL":     "Chemical",
    "DUST":         "Dust",
    "TOXIC":        "Toxic",
    "CORROSION":    "Corrosion",
    "RADIATION":    "Radiation",
    "FIRE":         "Fire",
    "ELECTRICITY":  "Electricity",
    "ARC_FLASH":    "ArcFlash",
    "NOISE":        "Noise",
    "HEAT_COLD":    "HeatCold",
    "BIOLOGICAL":   "Biological",
}

# ────────────────────────────────────────────────────────────────────────
# work_context — context:WorkContext (13 NamedIndividuals)
# ────────────────────────────────────────────────────────────────────────
WORK_CONTEXT_CODE_TO_URI: dict[str, str] = {
    "SCAFFOLD":           "Scaffold",
    "CONFINED_SPACE":     "ConfinedSpace",
    "EXCAVATION":         "Excavation",
    "MACHINE":            "Machine",
    "VEHICLE":            "Vehicle",
    "CRANE":              "Crane",
    "CONVEYOR":           "Conveyor",
    "ROBOT":              "Robot",
    "CONSTRUCTION_EQUIP": "ConstructionEquip",
    "RAIL":               "Rail",
    "PRESSURE_VESSEL":    "PressureVessel",
    "STEELWORK":          "Steelwork",
    "MATERIAL_HANDLING":  "MaterialHandling",
    # 추가 코드 (taxonomy v3.0에 있으나 OWL에는 없음 — fallback)
    "GENERAL_WORKPLACE":  None,           # OWL 미정의 — fallback to legacy
    "FIRE_EXPLOSION_WORK": None,          # OWL 미정의
    "FALL_PROTECTION":    None,
    "COLLAPSE_PREVENTION": None,
    "ELECTRICAL_WORK":    None,
    "CHEMICAL_WORK":      None,
    "DUST_WORK":          None,
    "NOISE_WORK":         None,
    "HEAT_COLD_WORK":     None,
    "ERGONOMIC_WORK":     None,
    "DEMOLITION":         None,
    "LOGGING":            None,
}

# ────────────────────────────────────────────────────────────────────────
# Namespace prefixes (mirror sparql_queries.PREFIXES)
# ────────────────────────────────────────────────────────────────────────
NAMESPACES = {
    "hazard":  "https://cashtoss.info/ontology/hazard#",
    "agent":   "https://cashtoss.info/ontology/agent#",
    "context": "https://cashtoss.info/ontology/context#",
}


def accident_type_to_iri(code: str) -> str | None:
    """OHS accident_type 코드를 hazard:AccidentType IRI로 변환.

    Returns None if no direct mapping (caller should fallback to legacy hazard:Hazard).
    """
    fragment = ACCIDENT_TYPE_CODE_TO_URI.get(code)
    return f"{NAMESPACES['hazard']}{fragment}" if fragment else None


def accident_type_to_prefixed(code: str) -> str | None:
    """SPARQL prefixed form (예: 'hazard:Fall')."""
    fragment = ACCIDENT_TYPE_CODE_TO_URI.get(code)
    return f"hazard:{fragment}" if fragment else None


def hazardous_agent_to_iri(code: str) -> str | None:
    fragment = HAZARDOUS_AGENT_CODE_TO_URI.get(code)
    return f"{NAMESPACES['agent']}{fragment}" if fragment else None


def hazardous_agent_to_prefixed(code: str) -> str | None:
    fragment = HAZARDOUS_AGENT_CODE_TO_URI.get(code)
    return f"agent:{fragment}" if fragment else None


def work_context_to_iri(code: str) -> str | None:
    fragment = WORK_CONTEXT_CODE_TO_URI.get(code)
    return f"{NAMESPACES['context']}{fragment}" if fragment else None


def work_context_to_prefixed(code: str) -> str | None:
    fragment = WORK_CONTEXT_CODE_TO_URI.get(code)
    return f"context:{fragment}" if fragment else None


# ────────────────────────────────────────────────────────────────────────
# Validation helpers (smoke test 용)
# ────────────────────────────────────────────────────────────────────────

def all_mapped_pairs() -> list[tuple[str, str, str]]:
    """모든 (axis, code, IRI) 매핑 반환 (None 제외).

    smoke test에서 SPARQL ASK로 각 IRI 존재 검증할 때 사용.
    """
    pairs = []
    for code, frag in ACCIDENT_TYPE_CODE_TO_URI.items():
        if frag:
            pairs.append(("accident_type", code, f"hazard:{frag}"))
    for code, frag in HAZARDOUS_AGENT_CODE_TO_URI.items():
        if frag:
            pairs.append(("hazardous_agent", code, f"agent:{frag}"))
    for code, frag in WORK_CONTEXT_CODE_TO_URI.items():
        if frag:
            pairs.append(("work_context", code, f"context:{frag}"))
    return pairs


def unmapped_codes() -> dict[str, list[str]]:
    """OWL 미정의 코드 목록 (fallback 필요)."""
    return {
        "accident_type": [k for k, v in ACCIDENT_TYPE_CODE_TO_URI.items() if v is None],
        "hazardous_agent": [k for k, v in HAZARDOUS_AGENT_CODE_TO_URI.items() if v is None],
        "work_context": [k for k, v in WORK_CONTEXT_CODE_TO_URI.items() if v is None],
    }


if __name__ == "__main__":
    # CLI 검증: 매핑 통계 출력
    pairs = all_mapped_pairs()
    print(f"Total mapped pairs: {len(pairs)}")
    by_axis = {}
    for axis, code, iri in pairs:
        by_axis.setdefault(axis, []).append((code, iri))
    for axis, items in by_axis.items():
        print(f"\n{axis} ({len(items)}):")
        for code, iri in items:
            print(f"  {code:30s} → {iri}")
    print(f"\nUnmapped codes (fallback needed):")
    for axis, codes in unmapped_codes().items():
        print(f"  {axis}: {codes}")
