import React from 'react';
import { AnalysisResponse } from '../../types/analysis';
import RiskLevelBadge from '../common/RiskLevelBadge';
import { format } from 'date-fns';
import { ko } from 'date-fns/locale';

interface ResultSummaryProps {
  analysis: AnalysisResponse;
}

const ResultSummary: React.FC<ResultSummaryProps> = ({ analysis }) => {
  return (
    <div className="card bg-gradient-to-r from-gray-50 to-gray-100">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900">분석 결과 요약</h2>
          <p className="text-sm text-gray-500 mt-1">
            {format(new Date(analysis.analyzed_at), 'yyyy년 M월 d일 HH:mm', { locale: ko })}
          </p>
        </div>
        <RiskLevelBadge level={analysis.overall_risk_level} size="lg" />
      </div>

      <p className="text-gray-700 mb-4">{analysis.summary}</p>

      <div className="grid grid-cols-3 gap-4 pt-4 border-t border-gray-200">
        <div className="text-center">
          <p className="text-2xl font-bold text-gray-900">{analysis.hazards.length}</p>
          <p className="text-sm text-gray-500">식별된 위험요소</p>
        </div>
        <div className="text-center">
          <p className="text-2xl font-bold text-gray-900">
            {analysis.checklist.items.length}
          </p>
          <p className="text-sm text-gray-500">점검 항목</p>
        </div>
        <div className="text-center">
          <p className="text-2xl font-bold text-gray-900">{analysis.resources.length}</p>
          <p className="text-sm text-gray-500">관련 자료</p>
        </div>
      </div>

      {analysis.recommendations.length > 0 && (
        <div className="mt-4 pt-4 border-t border-gray-200">
          <h3 className="font-medium text-gray-900 mb-2">추가 권고사항</h3>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
            {analysis.recommendations.map((rec, idx) => (
              <li key={idx}>{rec}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default ResultSummary;
