import { apiClient } from './index';
import type { MappingStats, ArticleNorms, GraphData } from './ontologyApi';

export const ptOntologyApi = {
  getStats: () =>
    apiClient.get<MappingStats>('/pt-ontology/stats').then(r => r.data),

  getArticleNorms: (articleNumber: string) =>
    apiClient.get<ArticleNorms>(`/pt-ontology/articles/${articleNumber}/norms`).then(r => r.data),

  getArticleGraph: (articleNumber: string) =>
    apiClient.get<GraphData>(`/pt-ontology/articles/${articleNumber}/graph`).then(r => r.data),

  getFullGraph: (limit = 50) =>
    apiClient.get<GraphData>(`/pt-ontology/graph?limit=${limit}`).then(r => r.data),
};
