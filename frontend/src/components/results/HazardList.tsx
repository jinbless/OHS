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
                <p className="text-xs text-gray-400 mt-3">
                  관련 법규: {hazard.legal_reference}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default HazardList;
