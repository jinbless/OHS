import React from 'react';
import { Resource, resourceTypeLabels, resourceTypeIcons } from '../../types/resource';

interface ResourceLinksProps {
  resources: Resource[];
}

const ResourceLinks: React.FC<ResourceLinksProps> = ({ resources }) => {
  if (resources.length === 0) {
    return null;
  }

  return (
    <div className="card">
      <h2 className="text-xl font-bold text-gray-900 mb-4">관련 교육 자료</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {resources.map((resource) => (
          <a
            key={resource.id}
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
        ))}
      </div>
    </div>
  );
};

export default ResourceLinks;
