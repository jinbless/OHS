import { apiClient } from './index';

export interface SparqlHealth {
  fuseki_enabled: boolean;
  fuseki_reachable: boolean;
  circuit_breaker_open: boolean;
  failure_count: number;
  endpoint: string;
}

export interface CoApplicableSr {
  sr_id: string;
  title: string;
  article_code: string;
}

export interface FacetedQueryResult {
  sr_id: string;
  title: string;
  article_code: string;
}

export interface SparqlStats {
  triple_count: number;
  class_distribution: { type: string; count: number }[];
  fuseki_available: boolean;
}

export interface InferredGraph {
  article_code: string;
  nodes: { id: string; label: string; group: string }[];
  edges: { from: string; to: string; edge_type: string }[];
}

export const sparqlApi = {
  getHealth: () =>
    apiClient.get<SparqlHealth>('/sparql/health').then(r => r.data),

  getCoApplicable: (srId: string) =>
    apiClient.get<{ sr_id: string; co_applicable: CoApplicableSr[]; count: number }>(
      `/sparql/sr/${srId}/co-applicable`
    ).then(r => r.data),

  getExemptions: (srId: string) =>
    apiClient.get(`/sparql/sr/${srId}/exemptions`).then(r => r.data),

  getArticleInferredGraph: (articleCode: string, limit = 100) =>
    apiClient.get<InferredGraph>(
      `/sparql/article/${articleCode}/inferred-graph?limit=${limit}`
    ).then(r => r.data),

  facetedQuery: (params: {
    accident_types?: string;
    hazardous_agents?: string;
    work_contexts?: string;
    limit?: number;
  }) =>
    apiClient.get<{ results: FacetedQueryResult[]; count: number }>(
      '/sparql/faceted-query',
      { params }
    ).then(r => r.data),

  getStats: () =>
    apiClient.get<SparqlStats>('/sparql/stats').then(r => r.data),

  getHighSeverity: (minSeverity = 5) =>
    apiClient.get(`/sparql/high-severity?min_severity=${minSeverity}`).then(r => r.data),

  getSubjectRoles: (roleType = 'DutyHolder') =>
    apiClient.get(`/sparql/subject-roles?role_type=${roleType}`).then(r => r.data),
};
