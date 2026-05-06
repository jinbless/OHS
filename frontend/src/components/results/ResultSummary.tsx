import React from 'react';
import { format } from 'date-fns';
import { ko } from 'date-fns/locale';
import { AnalysisResponse, ActionRecommendation } from '../../types/analysis';
import RiskLevelBadge from '../common/RiskLevelBadge';

interface ResultSummaryProps {
  analysis: AnalysisResponse;
}

const FINDING_STATUS_LABELS: Record<string, string> = {
  confirmed: '확정',
  suspected: '의심',
  needs_clarification: '확인 필요',
  not_determined: '판단 불가',
};

const PENALTY_STATUS_LABELS: Record<string, string> = {
  direct: '벌칙 안내 있음',
  conditional: '조건부 안내',
  no_penalty: '안내 없음',
};

function recommendationTitle(rec: ActionRecommendation) {
  if (rec.requirement_id && rec.requirement_title) {
    return `${rec.requirement_id}: ${rec.requirement_title}`;
  }
  if (rec.requirement_id) {
    return rec.requirement_id;
  }
  if (rec.guide_code && rec.guide_title) {
    return `${rec.guide_code}: ${rec.guide_title}`;
  }
  if (rec.checklist_text) {
    return rec.checklist_text;
  }
  return rec.match_reason;
}

const ResultSummary: React.FC<ResultSummaryProps> = ({ analysis }) => {
  const actionRecommendations = analysis.action_recommendations || [];
  const findingStatus = analysis.finding_status || 'not_determined';
  const penaltyStatus = analysis.penalty_exposure_status || 'no_penalty';
  const structuredTitles = new Set(actionRecommendations.map(recommendationTitle));
  const plainRecommendations = analysis.recommendations.filter((rec) => !structuredTitles.has(rec));

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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-4 border-t border-gray-200">
        <div className="text-center">
          <p className="text-2xl font-bold text-gray-900">{analysis.hazards.length}</p>
          <p className="text-sm text-gray-500">탐지 위험</p>
        </div>
        <div className="text-center">
          <p className="text-2xl font-bold text-gray-900">{analysis.checklist.items.length}</p>
          <p className="text-sm text-gray-500">자가 점검</p>
        </div>
        <div className="text-center">
          <p className="text-sm font-semibold text-gray-900">
            {FINDING_STATUS_LABELS[findingStatus] || findingStatus}
          </p>
          <p className="text-sm text-gray-500">판정 상태</p>
        </div>
        <div className="text-center">
          <p className="text-sm font-semibold text-gray-900">
            {PENALTY_STATUS_LABELS[penaltyStatus] || penaltyStatus}
          </p>
          <p className="text-sm text-gray-500">벌칙 노출</p>
        </div>
      </div>

      {actionRecommendations.length > 0 && (
        <div className="mt-4 pt-4 border-t border-gray-200">
          <h3 className="font-medium text-gray-900 mb-2">우선 검토할 개선 조치</h3>
          <div className="space-y-2">
            {actionRecommendations.slice(0, 3).map((rec) => (
              <div key={`${rec.rank}-${rec.requirement_id || rec.guide_code || rec.checklist_id}`} className="rounded-lg bg-white border border-gray-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {rec.rank}. {recommendationTitle(rec)}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">{rec.match_reason}</p>
                  </div>
                  <span className="text-xs text-gray-500 whitespace-nowrap">
                    {Math.round((rec.confidence || 0) * 100)}%
                  </span>
                </div>
                {(rec.guide_code || rec.checklist_id) && (
                  <p className="text-xs text-gray-500 mt-2">
                    {rec.guide_code && `가이드 ${rec.guide_code}`}
                    {rec.guide_code && rec.checklist_id && ' · '}
                    {rec.checklist_id && `점검항목 ${rec.checklist_id}`}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {plainRecommendations.length > 0 && (
        <div className="mt-4 pt-4 border-t border-gray-200">
          <h3 className="font-medium text-gray-900 mb-2">추가 권고사항</h3>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
            {plainRecommendations.map((rec, idx) => (
              <li key={idx}>{rec}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default ResultSummary;
