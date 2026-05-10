import React from 'react';
import type { AnalysisResponse } from '../../types/analysis';
import { severityColors, situationStatusColors, situationStatusLabels } from './resultLabels';

const RiskOverviewPanel: React.FC<{ analysis: AnalysisResponse }> = ({ analysis }) => (
  <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
    <div className="bg-white rounded-xl border p-4">
      <h2 className="text-lg font-bold text-gray-900 mb-3">발견된 위험 요약</h2>
      {analysis.observations.length ? (
        <div className="space-y-3">
          {analysis.observations.map((observation) => (
            <div key={observation.observation_id} className="rounded-lg bg-gray-50 p-3">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium text-gray-900">{observation.text}</p>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full border ${
                    severityColors[observation.severity] ||
                    'bg-gray-100 text-gray-600 border-gray-200'
                  }`}
                >
                  {observation.severity}
                </span>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                신뢰도 {Math.round(observation.confidence * 100)}%
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400">확인된 관찰 사실이 없습니다.</p>
      )}
    </div>

    <div className="bg-white rounded-xl border p-4">
      <h2 className="text-lg font-bold text-gray-900 mb-3">정규화된 위험 특징</h2>
      {analysis.risk_features.length ? (
        <div className="flex flex-wrap gap-2">
          {analysis.risk_features.map((feature) => (
            <span
              key={`${feature.axis}-${feature.code}`}
              className="px-2 py-1 rounded-lg bg-blue-50 text-blue-700 text-xs border border-blue-100"
            >
              {feature.label || feature.code}
              <span className="ml-1 text-blue-400">({feature.axis})</span>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400">정규화된 위험 특징이 없습니다.</p>
      )}
      <div className="mt-4 border-t border-gray-100 pt-3">
        <h3 className="text-sm font-semibold text-gray-800 mb-2">위험상황 패턴</h3>
        {analysis.situation_matches.length ? (
          <div className="space-y-2">
            {analysis.situation_matches.slice(0, 4).map((match) => (
              <div key={match.pattern_id} className="rounded-lg border border-gray-100 bg-gray-50 p-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs font-medium text-gray-800 break-words">
                    {match.title || match.pattern_id}
                  </p>
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full border whitespace-nowrap ${
                      situationStatusColors[match.status] ||
                      'bg-gray-50 text-gray-600 border-gray-100'
                    }`}
                  >
                    {situationStatusLabels[match.status] || match.status}
                  </span>
                </div>
                {match.visual_trigger_hits.length > 0 && (
                  <p className="text-[11px] text-gray-500 mt-1 break-words">
                    {match.visual_trigger_hits.slice(0, 3).join(', ')}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400">연결된 위험상황 패턴이 없습니다.</p>
        )}
      </div>
    </div>
  </section>
);

export default RiskOverviewPanel;
