export type ResourceType = 'leaflet' | 'video' | 'document' | 'website';

export interface Resource {
  id: string;
  type: ResourceType;
  title: string;
  description: string;
  url: string;
  source: string;
  hazard_categories: string[];
  thumbnail_url?: string;
}

export const resourceTypeLabels: Record<ResourceType, string> = {
  leaflet: '리플릿',
  video: '동영상',
  document: '문서',
  website: '웹사이트',
};

export const resourceTypeIcons: Record<ResourceType, string> = {
  leaflet: '📄',
  video: '🎬',
  document: '📋',
  website: '🌐',
};
