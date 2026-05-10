import { apiClient } from './index';
import {
  TextAnalysisRequest,
  AnalysisResponse,
  AnalysisHistoryResponse,
} from '../types/analysis';

export const analysisApi = {
  analyzeImage: async (
    file: File,
    workplaceType?: string,
    additionalContext?: string
  ): Promise<AnalysisResponse> => {
    const formData = new FormData();
    formData.append('image', file);
    if (workplaceType) formData.append('workplace_type', workplaceType);
    if (additionalContext) formData.append('additional_context', additionalContext);

    const response = await apiClient.post<AnalysisResponse>(
      '/analysis/image',
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
      }
    );
    return response.data;
  },

  analyzeText: async (request: TextAnalysisRequest): Promise<AnalysisResponse> => {
    const response = await apiClient.post<AnalysisResponse>(
      '/analysis/text',
      request
    );
    return response.data;
  },

  getHistory: async (skip = 0, limit = 20): Promise<AnalysisHistoryResponse> => {
    const response = await apiClient.get<AnalysisHistoryResponse>(
      '/analysis/history',
      { params: { skip, limit } }
    );
    return response.data;
  },

  getAnalysis: async (analysisId: string): Promise<AnalysisResponse> => {
    const response = await apiClient.get<AnalysisResponse>(
      `/analysis/${analysisId}`
    );
    return response.data;
  },

  deleteAnalysis: async (analysisId: string): Promise<void> => {
    await apiClient.delete(`/analysis/${analysisId}`);
  },
};
