import { Hazard, RiskLevel } from './hazard';
import { Checklist } from './checklist';
import { Resource } from './resource';

export interface GuideArticleRef {
  article_number: string;
  title: string;
  content?: string;
  chapter?: string;
  part?: string;
}

export interface GuideSectionInfo {
  section_title: string;
  excerpt: string;
  section_type?: string;
}

export interface GuideMatch {
  guide_code: string;
  title: string;
  classification: string;
  relevant_sections: GuideSectionInfo[];
  relevance_score: number;
  mapping_type: string;
  mapped_articles: GuideArticleRef[];
}

export interface TextAnalysisRequest {
  description: string;
  workplace_type?: string;
  industry_sector?: string;
}

// Phase 3: Dual-Track types
export interface GptFreeObservation {
  label: string;
  description: string;
  confidence: number;
  visual_evidence?: string | null;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
}

export interface FacetedHazardCodes {
  accident_types: string[];
  hazardous_agents: string[];
  work_contexts: string[];
  applied_rules: string[];
  confidence: number;
}

export interface CodeGapWarning {
  gap_type: string;
  gpt_free_label?: string;
  description: string;
}

export interface PenaltyInfo {
  article_code: string;
  title: string;
  criminal_employer_penalty?: string | null;
  criminal_death_penalty?: string | null;
  admin_max_fine?: string | null;
}

// Phase 5: SPARQL enrichment
export interface SparqlEnrichmentSummary {
  source: 'pg_only' | 'pg+sparql' | 'sparql_inferred';
  co_applicable_srs: { sr_id: string; title: string; article_code: string; discovered_via: string }[];
  exemptions: { exempt_ns_id: string; article_code: string; condition?: string; applies_to_sr: string }[];
  high_severity_srs: { sr_id: string; severity?: string; penalty: string }[];
  fuseki_available: boolean;
}

export interface AnalysisResponse {
  analysis_id: string;
  analysis_type: 'image' | 'text';
  overall_risk_level: RiskLevel;
  summary: string;
  hazards: Hazard[];
  checklist: Checklist;
  resources: Resource[];
  related_guides: GuideMatch[];
  recommendations: string[];
  analyzed_at: string;
  // Phase 3: Dual-Track
  canonical_hazards?: FacetedHazardCodes | null;
  gpt_free_observations?: GptFreeObservation[];
  decision_type?: string;
  code_gap_warnings?: CodeGapWarning[];
  penalties?: PenaltyInfo[];
  // Phase 5: SPARQL enrichment
  sparql_enrichment?: SparqlEnrichmentSummary | null;
}

export interface AnalysisHistoryItem {
  analysis_id: string;
  analysis_type: 'image' | 'text';
  overall_risk_level: RiskLevel;
  summary: string;
  analyzed_at: string;
  input_preview?: string;
}

export interface AnalysisHistoryResponse {
  total: number;
  items: AnalysisHistoryItem[];
}
