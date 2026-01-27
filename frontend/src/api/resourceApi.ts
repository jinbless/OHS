import { apiClient } from './index';
import { Resource, ResourceType } from '../types/resource';

export const resourceApi = {
  getResources: async (
    type?: ResourceType,
    category?: string
  ): Promise<Resource[]> => {
    const response = await apiClient.get<Resource[]>('/resources', {
      params: { type, category },
    });
    return response.data;
  },
};
