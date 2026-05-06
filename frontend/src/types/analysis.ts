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

export interface PenaltyCandidate {
  penalty_rule_id: string;
  exposure_type: 'direct_candidate' | 'conditional' | string;
  condition_label: string;
  subject_role?: string | null;
  accident_outcome?: string | null;
  violated_norm_id?: string | null;
  violated_article_id?: string | null;
  delegated_from_article_id?: string | null;
  penalty_article_id?: string | null;
  sanction_type?: string | null;
  penalty_description?: string | null;
  severity_score?: number | null;
  basis_text?: string | null;
  source_sr_id?: string | null;
}

export interface PenaltyPath {
  path_type: 'general_incident' | 'death' | 'serious_accident' | string;
  title: string;
  notice_level: 'photo_based' | 'external_fact_required' | 'conditional' | string;
  summary: string;
  penalty_rule_ids: string[];
  penalty_descriptions: string[];
  article_refs: { ref_type: string; label: string; article_id: string }[];
  max_severity_score?: number | null;
  source_sr_ids: string[];
}

// Phase 5: SPARQL enrichment
export interface SparqlEnrichmentSummary {
  source: 'pg_only' | 'pg+sparql' | 'sparql_inferred';
  co_applicable_srs: { sr_id: string; title: string; article_code: string; discovered_via: string }[];
  exemptions: { exempt_ns_id: string; article_code: string; condition?: string; applies_to_sr: string }[];
  high_severity_srs: { sr_id: string; severity?: string; penalty: string }[];
  fuseki_available: boolean;
}

export interface ActionRecommendation {
  rank: number;
  source: string;
  match_reason: string;
  requirement_id?: string | null;
  requirement_title?: string | null;
  guide_code?: string | null;
  guide_title?: string | null;
  checklist_id?: string | null;
  checklist_text?: string | null;
  confidence: number;
  display_group?: 'immediate_action' | 'standard_procedure' | 'legal_basis' | string;
  urgency?: 'immediate' | 'planned' | 'reference' | string;
}

export interface NormSummary {
  article_number: string;
  legal_effect: string;
  action?: string | null;
  full_text: string;
}

export interface LinkedGuideSummary {
  guide_code: string;
  title: string;
  relation_type: string;
  confidence: number;
}

export interface NormContext {
  article_number: string;
  article_title?: string | null;
  norms: NormSummary[];
  linked_guides: LinkedGuideSummary[];
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
  norm_context?: NormContext[];
  recommendations: string[];
  analyzed_at: string;
  // Phase 3: Dual-Track
  canonical_hazards?: FacetedHazardCodes | null;
  gpt_free_observations?: GptFreeObservation[];
  decision_type?: string;
  code_gap_warnings?: CodeGapWarning[];
  penalties?: PenaltyInfo[];
  penalty_candidates?: PenaltyCandidate[];
  penalty_paths?: PenaltyPath[];
  // Phase 5: SPARQL enrichment
  sparql_enrichment?: SparqlEnrichmentSummary | null;
  recommended_srs?: { identifier: string; source: string; layer: number; confidence: number; title?: string | null }[];
  finding_status?: 'confirmed' | 'suspected' | 'needs_clarification' | 'not_determined' | string;
  penalty_exposure_status?: 'direct' | 'conditional' | 'no_penalty' | string;
  action_recommendations?: ActionRecommendation[];
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
