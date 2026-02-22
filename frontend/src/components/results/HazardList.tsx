import React from 'react';
import { Hazard, categoryLabels } from '../../types/hazard';
import RiskLevelBadge from '../common/RiskLevelBadge';

interface HazardListProps {
  hazards: Hazard[];
}

const HazardList: React.FC<HazardListProps> = ({ hazards }) => {
  const sortedHazards = [...hazards].sort((a, b) => {
    const priority = { critical: 0, high: 1, medium: 2, low: 3 };
    return priority[a.risk_level] - priority[b.risk_level];
  });

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold text-gray-900">식별된 위험요소</h2>
      {sortedHazards.length === 0 ? (
        <p className="text-gray-500">식별된 위험요소가 없습니다.</p>
      ) : (
        <div className="space-y-4">
          {sortedHazards.map((hazard) => (
            <div key={hazard.id} className="card">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <RiskLevelBadge level={hazard.risk_level} />
                  <span className="text-sm text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
                    {categoryLabels[hazard.category]}
                  </span>
                </div>
              </div>

              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                {hazard.name}
              </h3>
              <p className="text-gray-600 mb-4">{hazard.description}</p>

              {hazard.location && (
                <p className="text-sm text-gray-500 mb-3">
                  <span className="font-medium">위치:</span> {hazard.location}
                </p>
              )}

              {hazard.potential_consequences.length > 0 && (
                <div className="mb-4">
                  <h4 className="text-sm font-medium text-gray-700 mb-2">
                    발생 가능한 결과
                  </h4>
                  <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
                    {hazard.potential_consequences.map((consequence, idx) => (
                      <li key={idx}>{consequence}</li>
                    ))}
                  </ul>
                </div>
              )}

              {hazard.preventive_measures.length > 0 && (
                <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                  <h4 className="text-sm font-medium text-green-800 mb-2">
                    예방 조치
                  </h4>
                  <ul className="list-disc list-inside text-sm text-green-700 space-y-1">
                    {hazard.preventive_measures.map((measure, idx) => (
                      <li key={idx}>{measure}</li>
                    ))}
                  </ul>
                </div>
              )}

              {hazard.legal_reference && (
                <div className="mt-3 flex items-center gap-1.5 text-xs text-blue-600 bg-blue-50 px-3 py-1.5 rounded-lg border border-blue-100">
                  <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                  </svg>
                  <span className="font-medium">법적 근거:</span> {hazard.legal_reference}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default HazardList;
