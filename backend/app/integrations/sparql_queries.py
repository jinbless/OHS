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
    """Q2: coApplicable SR discovery — SRs sharing the same source article."""
    return PREFIXES + f"""
SELECT DISTINCT ?coSrId ?coSrTitle ?artCode WHERE {{
  ?sr kosha:identifier "{sr_id}" ;
      sr:derivedFromNS ?ns .
  ?ns law:hasSourceArticle ?art .
  ?art law:articleCode ?artCode .
  ?coNs law:hasSourceArticle ?art .
  ?coSr sr:derivedFromNS ?coNs ;
        kosha:identifier ?coSrId .
  OPTIONAL {{ ?coSr kosha:title ?coSrTitle }}
  FILTER(?coSr != ?sr)
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
    """Q4: Exemption chain (SWRL R-1) — find exemptions that release obligations."""
    return PREFIXES + f"""
SELECT ?exemptNsId ?exemptArtCode ?condition WHERE {{
  ?sr kosha:identifier "{sr_id}" ;
      sr:derivedFromNS ?obligNs .
  ?obligNs law:hasModality kosha:Obligation .
  ?exemptNs law:exempts ?obligNs ;
            kosha:identifier ?exemptNsId .
  ?exemptNs law:hasSourceArticle ?exemptArt .
  ?exemptArt law:articleCode ?exemptArtCode .
  OPTIONAL {{ ?exemptNs law:hasCondition ?condition }}
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
    """Q6: Faceted 3-axis cross query with OWL inference."""
    filters = []
    if accident_types:
        for at in accident_types:
            filters.append(f"  ?sr sr:addressesAccidentType hazard:{at} .")
    if hazardous_agents:
        for ag in hazardous_agents:
            filters.append(f"  ?sr sr:addressesAgent agent:{ag} .")
    if work_contexts:
        for wc in work_contexts:
            filters.append(f"  ?sr sr:inWorkContext context:{wc} .")

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
    ?exemptNs law:exempts ?ns ;
              kosha:identifier ?exemptNsId .
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
