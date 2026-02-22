import { Hazard, RiskLevel } from './hazard';
import { Checklist } from './checklist';
import { Resource } from './resource';

export interface GuideArticleRef {
  article_number: string;
  title: string;
  content?: string;
  source_file?: string;
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
