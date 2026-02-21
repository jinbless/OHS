import { Hazard, RiskLevel } from './hazard';
import { Checklist } from './checklist';
import { Resource } from './resource';

export interface ArticleMatch {
  article_number: string;
  title: string;
  content: string;
  source_file: string;
  relevance_score: number;
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
  related_articles: ArticleMatch[];
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
