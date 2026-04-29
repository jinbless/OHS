"""
Parameterized SPARQL query library for KOSHA ontology.

Namespaces (from kosha-ontology.owl / kosha-instances.ttl):
  kosha:   <https://cashtoss.info/ontology#>
  law:     <https://cashtoss.info/ontology/law#>
  sr:      <https://cashtoss.info/ontology/sr#>
  pen:     <https://cashtoss.info/ontology/penalty#>
  guide:   <https://cashtoss.info/ontology/guide#>
  hazard:  <https://cashtoss.info/ontology/hazard#>
  agent:   <https://cashtoss.info/ontology/agent#>
  context: <https://cashtoss.info/ontology/context#>
"""

PREFIXES = """
PREFIX kosha:   <https://cashtoss.info/ontology#>
PREFIX law:     <https://cashtoss.info/ontology/law#>
PREFIX sr:      <https://cashtoss.info/ontology/sr#>
PREFIX pen:     <https://cashtoss.info/ontology/penalty#>
PREFIX guide:   <https://cashtoss.info/ontology/guide#>
PREFIX hazard:  <https://cashtoss.info/ontology/hazard#>
PREFIX agent:   <https://cashtoss.info/ontology/agent#>
PREFIX context: <https://cashtoss.info/ontology/context#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:     <http://www.w3.org/2001/XMLSchema#>
"""


def q1_property_chain_sr_to_article(sr_id: str) -> str:
    """Q1: Property chain SR → NS → Article (1-hop via OWL inference)."""
    return PREFIXES + f"""
SELECT ?srId ?nsId ?artCode ?artTitle WHERE {{
  ?sr kosha:identifier "{sr_id}" ;
      sr:derivedFromNS ?ns .
  ?ns kosha:identifier ?nsId ;
      law:hasSourceArticle ?art .
  ?art law:articleCode ?artCode .
  OPTIONAL {{ ?art kosha:title ?artTitle }}
}}
"""


def q2_co_applicable_srs(sr_id: str) -> str:
    """Q2: coApplicable SR discovery.

    Phase 0.5 변경: R-2 영구화된 kosha:coApplicable을 1순위로 사용.
    - 1순위: ?sr kosha:coApplicable ?coSr (R-2 SymmetricProperty 영구화 결과 직접 사용)
    - 2순위 fallback: 같은 source article 공유 기반 재계산 (영구화 누락 시)
    UNION으로 두 source 결합. R-2 영구화 결과(94 pair)를 production에서 활용.
    """
    return PREFIXES + f"""
SELECT DISTINCT ?coSrId ?coSrTitle ?artCode ?source WHERE {{
  ?sr kosha:identifier "{sr_id}" .
  {{
    # 1순위: 영구화된 kosha:coApplicable 직접 사용 (R-2 결과)
    ?sr kosha:coApplicable ?coSr .
    ?coSr kosha:identifier ?coSrId .
    OPTIONAL {{ ?coSr kosha:title ?coSrTitle }}
    OPTIONAL {{
      ?coSr sr:derivedFromNS ?coNs .
      ?coNs law:hasSourceArticle ?art .
      ?art law:articleCode ?artCode .
    }}
    BIND("materialized_r2" AS ?source)
  }} UNION {{
    # 2순위 fallback: 같은 article 공유 (영구화 누락 시)
    ?sr sr:derivedFromNS ?ns .
    ?ns law:hasSourceArticle ?art .
    ?art law:articleCode ?artCode .
    ?coNs law:hasSourceArticle ?art .
    ?coSr sr:derivedFromNS ?coNs ;
          kosha:identifier ?coSrId .
    OPTIONAL {{ ?coSr kosha:title ?coSrTitle }}
    FILTER(?coSr != ?sr)
    BIND("article_shared" AS ?source)
  }}
}}
"""


def q3_subject_role_hierarchy(role_type: str = "DutyHolder") -> str:
    """Q3: SubjectRole hierarchy inference — all subtypes of a role."""
    return PREFIXES + f"""
SELECT ?roleName ?roleType (COUNT(?ns) AS ?cnt) WHERE {{
  ?role a/rdfs:subClassOf* kosha:{role_type} ;
        a ?roleType ;
        rdfs:label ?roleName .
  ?ns law:hasSubjectRole ?role .
  FILTER(LANG(?roleName) = "ko")
}} GROUP BY ?roleName ?roleType ORDER BY DESC(?cnt)
"""


def q4_exemption_chain(sr_id: str) -> str:
    """Q4: Exemption chain (SWRL R-1) — find exemptions that release obligations.

    Phase 0.5 수정 (실제 OWL/TTL predicate 기준):
    - law:exempts (OWL 미정의) → kosha:exemptedBy (실제 사용, 방향 반대)
      triple: ?obligNs kosha:exemptedBy ?exemptNs
    - law:hasCondition (OWL 미정의) → law:conditionText (실제 사용, DatatypeProperty)
    """
    return PREFIXES + f"""
SELECT ?exemptNsId ?exemptArtCode ?condition WHERE {{
  ?sr kosha:identifier "{sr_id}" ;
      sr:derivedFromNS ?obligNs .
  ?obligNs law:hasModality kosha:Obligation ;
           kosha:exemptedBy ?exemptNs .
  ?exemptNs kosha:identifier ?exemptNsId ;
            law:hasSourceArticle ?exemptArt .
  ?exemptArt law:articleCode ?exemptArtCode .
  OPTIONAL {{ ?exemptNs law:conditionText ?condition }}
}}
"""


def q5_high_severity_srs(min_severity: int = 5) -> str:
    """Q5: High-severity penalty SRs (severity >= threshold)."""
    return PREFIXES + f"""
SELECT ?srId ?srTitle ?penaltyDesc ?severity WHERE {{
  ?sr a sr:SafetyRequirement ;
      kosha:identifier ?srId ;
      sr:derivedFromNS ?ns .
  OPTIONAL {{ ?sr kosha:title ?srTitle }}
  ?ns pen:hasSanction ?san .
  ?san pen:severityScore ?severity ;
       pen:penaltyDescription ?penaltyDesc .
  FILTER(?severity >= {min_severity})
}} ORDER BY DESC(?severity) LIMIT 50
"""


def q6_faceted_cross_query(
    accident_types: list[str] | None = None,
    hazardous_agents: list[str] | None = None,
    work_contexts: list[str] | None = None,
    limit: int = 50
) -> str:
    """Q6: Faceted 3-axis cross query with OWL inference.

    Phase 0.5 수정: code_iri_mapper로 OHS code (UPPER_CASE) → OWL URI (CamelCase).
    이전: hazard:{at} → 'hazard:FALL' (잘못, OWL은 'hazard:Fall')
    이후: code_iri_mapper.accident_type_to_prefixed("FALL") → 'hazard:Fall' (정답)
    """
    from app.integrations.code_iri_mapper import (
        accident_type_to_prefixed,
        hazardous_agent_to_prefixed,
        work_context_to_prefixed,
    )
    filters = []
    if accident_types:
        for at in accident_types:
            iri = accident_type_to_prefixed(at)
            if iri:  # OWL 미정의 코드는 skip
                filters.append(f"  ?sr sr:addressesAccidentType {iri} .")
    if hazardous_agents:
        for ag in hazardous_agents:
            iri = hazardous_agent_to_prefixed(ag)
            if iri:
                filters.append(f"  ?sr sr:addressesAgent {iri} .")
    if work_contexts:
        for wc in work_contexts:
            iri = work_context_to_prefixed(wc)
            if iri:
                filters.append(f"  ?sr sr:inWorkContext {iri} .")

    filter_block = "\n".join(filters) if filters else "  ?sr a sr:SafetyRequirement ."

    return PREFIXES + f"""
SELECT DISTINCT ?srId ?srTitle ?artCode WHERE {{
  ?sr a sr:SafetyRequirement ;
      kosha:identifier ?srId .
  OPTIONAL {{ ?sr kosha:title ?srTitle }}
{filter_block}
  OPTIONAL {{
    ?sr sr:derivedFromNS ?ns .
    ?ns law:hasSourceArticle ?art .
    ?art law:articleCode ?artCode .
  }}
}} LIMIT {limit}
"""


def q7_article_inferred_graph(article_code: str, limit: int = 100) -> str:
    """Q7: Full inference graph around a specific article.
    article_code should be in Korean format like '제38조'."""
    return PREFIXES + f"""
SELECT ?srId ?srTitle ?nsId ?modality ?penaltyDesc ?severity
       ?coSrId ?exemptNsId ?ciId ?guideCode WHERE {{
  ?art law:articleCode "{article_code}" .
  ?ns law:hasSourceArticle ?art ;
      kosha:identifier ?nsId .
  OPTIONAL {{ ?ns law:hasModality ?modality }}
  ?sr sr:derivedFromNS ?ns ;
      kosha:identifier ?srId .
  OPTIONAL {{ ?sr kosha:title ?srTitle }}
  OPTIONAL {{
    ?ns pen:hasSanction ?san .
    ?san pen:penaltyDescription ?penaltyDesc ;
         pen:severityScore ?severity .
  }}
  OPTIONAL {{
    ?coNs law:hasSourceArticle ?art .
    ?coSr sr:derivedFromNS ?coNs ;
          kosha:identifier ?coSrId .
    FILTER(?coSr != ?sr)
  }}
  OPTIONAL {{
    # Phase 0.5: law:exempts (OWL 미정의) → kosha:exemptedBy (방향 반대)
    ?ns kosha:exemptedBy ?exemptNs .
    ?exemptNs kosha:identifier ?exemptNsId .
  }}
  OPTIONAL {{
    ?ci guide:basedOnSR ?sr ;
        kosha:identifier ?ciId .
    ?g guide:hasChecklistItem ?ci ;
       guide:guideCode ?guideCode .
  }}
}} LIMIT {limit}
"""


def q_triple_count() -> str:
    """Total triple count for stats."""
    return "SELECT (COUNT(*) AS ?cnt) WHERE { ?s ?p ?o }"


def q_class_distribution() -> str:
    """Class distribution for stats."""
    return PREFIXES + """
SELECT ?type (COUNT(?s) AS ?cnt) WHERE {
  ?s a ?type
} GROUP BY ?type ORDER BY DESC(?cnt) LIMIT 20
"""
