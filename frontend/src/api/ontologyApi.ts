import { apiClient } from './index';

export interface MappingStats {
  total_articles: number;
  mapped_articles: number;
  unmapped_articles: number;
  total_guides: number;
  mapped_guides: number;
  unmapped_guides: number;
  total_explicit_mappings: number;
  total_semantic_mappings: number;
  mapping_by_relation_type: Record<string, number>;
  mapping_by_discovery: Record<string, number>;
  coverage_improvement: { before: number; after: number };
}

export interface NormStatement {
  id: number;
  article_number: string;
  paragraph: string | null;
  statement_order: number;
  subject_role: string | null;
  action: string | null;
  object: string | null;
  condition_text: string | null;
  legal_effect: string;
  effect_description: string | null;
  full_text: string;
  norm_category: string | null;
}

export interface LinkedGuide {
  guide_code: string;
  title: string;
  classification: string;
  relation_type: string;
  confidence: number;
  discovery_method: string;
}

export interface ArticleNorms {
  article_number: string;
  article_title: string | null;
  total_norms: number;
  norms: NormStatement[];
  linked_guides: LinkedGuide[];
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphNode {
  id: string;
  label: string;
  group: string;
  shape: string;
  color: string | Record<string, unknown>;
  value?: number;
}

export interface GraphEdge {
  from: string;
  to: string;
  label: string;
  dashes?: boolean;
  color?: Record<string, unknown>;
}

export const ontologyApi = {
  getStats: () =>
    apiClient.get<MappingStats>('/ontology/stats').then(r => r.data),

  getArticleNorms: (articleNumber: string) =>
    apiClient.get<ArticleNorms>(`/ontology/articles/${articleNumber}/norms`).then(r => r.data),

  getArticleGraph: (articleNumber: string) =>
    apiClient.get<GraphData>(`/ontology/articles/${articleNumber}/graph`).then(r => r.data),

  getFullGraph: (limit = 50) =>
    apiClient.get<GraphData>(`/ontology/graph?limit=${limit}`).then(r => r.data),
};
