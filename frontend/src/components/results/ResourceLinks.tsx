import React from 'react';
import { Resource, resourceTypeLabels, resourceTypeIcons } from '../../types/resource';

interface ResourceLinksProps {
  resources: Resource[];
}

const HAZARD_CODE_LABELS: Record<string, string> = {
  FALL: '추락', SLIP: '미끄러짐', COLLISION: '충돌', CRUSH: '끼임',
  CUT: '절단', FALLING_OBJECT: '낙하물', CHEMICAL: '화학물질',
  FIRE_EXPLOSION: '화재·폭발', TOXIC: '중독·질식', CORROSION: '부식',
  ELECTRIC: '감전', ARC_FLASH: '아크플래시', ERGONOMIC: '인간공학',
  REPETITIVE: '반복작업', HEAVY_LIFTING: '중량물', POSTURE: '자세',
  NOISE: '소음', TEMPERATURE: '온열', LIGHTING: '조명',
  ENVIRONMENTAL: '환경위험', BIOLOGICAL: '생물학적',
};

const extractVideoId = (url: string): string | null => {
  const match = url.match(/shorts\/([a-zA-Z0-9_-]+)/);
  return match ? match[1] : null;
};

const VideoCard: React.FC<{ resource: Resource }> = ({ resource }) => {
  const videoId = extractVideoId(resource.url);
  const thumbnail = resource.thumbnail_url || (videoId ? `https://img.youtube.com/vi/${videoId}/0.jpg` : null);

  return (
    <a
      href={resource.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group block rounded-xl border border-gray-200 overflow-hidden hover:border-red-300 hover:shadow-md transition-all"
    >
      {thumbnail && (
        <div className="relative w-full h-36 bg-gray-100 overflow-hidden">
          <img
            src={thumbnail}
            alt={resource.title}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            loading="lazy"
          />
          <div className="absolute inset-0 flex items-center justify-center bg-black/20 opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="w-12 h-12 bg-red-600 rounded-full flex items-center justify-center">
              <svg className="w-5 h-5 text-white ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z" />
              </svg>
            </div>
          </div>
          <span className="absolute top-2 left-2 bg-red-600 text-white text-xs px-1.5 py-0.5 rounded font-medium">
            Shorts
          </span>
        </div>
      )}
      <div className="p-3">
        <h3 className="font-medium text-gray-900 text-sm leading-snug line-clamp-2">
          {resource.title}
        </h3>
        <p className="text-xs text-gray-500 mt-1.5 line-clamp-2">
          {resource.description}
        </p>
        {resource.hazard_categories?.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {resource.hazard_categories.slice(0, 3).map((code) => (
              <span key={code} className="text-[10px] bg-orange-50 text-orange-600 px-1.5 py-0.5 rounded border border-orange-200">
                {HAZARD_CODE_LABELS[code] || code}
              </span>
            ))}
          </div>
        )}
      </div>
    </a>
  );
};

const DefaultCard: React.FC<{ resource: Resource }> = ({ resource }) => (
  <a
    href={resource.url}
    target="_blank"
    rel="noopener noreferrer"
    className="block p-4 border border-gray-200 rounded-lg hover:border-primary-300 hover:bg-primary-50 transition-colors"
  >
    <div className="flex items-start gap-3">
      <span className="text-2xl">{resourceTypeIcons[resource.type]}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
            {resourceTypeLabels[resource.type]}
          </span>
        </div>
        <h3 className="font-medium text-gray-900 truncate">
          {resource.title}
        </h3>
        <p className="text-sm text-gray-500 mt-1 line-clamp-2">
          {resource.description}
        </p>
        <p className="text-xs text-gray-400 mt-2">출처: {resource.source}</p>
      </div>
    </div>
  </a>
);

const ResourceLinks: React.FC<ResourceLinksProps> = ({ resources }) => {
  if (resources.length === 0) {
    return null;
  }

  const videos = resources.filter(r => r.type === 'video');
  const others = resources.filter(r => r.type !== 'video');

  return (
    <div className="card">
      <h2 className="text-xl font-bold text-gray-900 mb-4">관련 교육 자료</h2>

      {videos.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
          {videos.map((resource) => (
            <VideoCard key={resource.id} resource={resource} />
          ))}
        </div>
      )}

      {others.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {others.map((resource) => (
            <DefaultCard key={resource.id} resource={resource} />
          ))}
        </div>
      )}
    </div>
  );
};

export default ResourceLinks;
