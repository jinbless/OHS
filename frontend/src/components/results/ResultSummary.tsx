import React from 'react';
import { format } from 'date-fns';
import { ko } from 'date-fns/locale';
import { AnalysisResponse } from '../../types/analysis';
import RiskLevelBadge from '../common/RiskLevelBadge';
import { findingStatusLabels } from './resultLabels';

interface ResultSummaryProps {
  analysis: AnalysisResponse;
}

const PENALTY_LABELS: Record<string, string> = {
  direct: '벌칙 안내 있음',
  conditional: '조건부 안내',
  no_penalty: '안내 없음',
};

const ResultSummary: React.FC<ResultSummaryProps> = ({ analysis }) => {
  return (
    <section className="card bg-gradient-to-r from-gray-50 to-gray-100">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900">분석 결과 요약</h2>
          <p className="text-sm text-gray-500 mt-1">
            {format(new Date(analysis.analyzed_at), 'yyyy년 M월 d일 HH:mm', { locale: ko })}
          </p>
        </div>
        <RiskLevelBadge level={analysis.overall_risk_level} size="lg" />
      </div>

      <p className="text-gray-700 leading-relaxed mb-4">{analysis.summary}</p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-4 border-t border-gray-200">
        <SummaryMetric label="관찰 사실" value={analysis.observations.length} />
        <SummaryMetric label="위험 특징" value={analysis.risk_features.length} />
        <SummaryMetric
          label="위험 판단"
          value={findingStatusLabels[analysis.finding_status] || analysis.finding_status}
          compact
        />
        <SummaryMetric
          label="벌칙 안내"
          value={PENALTY_LABELS[analysis.penalty_exposure_status] || analysis.penalty_exposure_status}
          compact
        />
      </div>
    </section>
  );
};

const SummaryMetric: React.FC<{ label: string; value: number | string; compact?: boolean }> = ({
  label,
  value,
  compact = false,
}) => (
  <div className="text-center min-w-0">
    <p className={`${compact ? 'text-sm' : 'text-2xl'} font-bold text-gray-900 break-words`}>
      {value}
    </p>
    <p className="text-sm text-gray-500 mt-1">{label}</p>
  </div>
);

export default ResultSummary;
