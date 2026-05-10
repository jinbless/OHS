import React, { useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { analysisApi } from '../api/analysisApi';
import Loading from '../components/common/Loading';
import ErrorMessage from '../components/common/ErrorMessage';
import GuideProcedurePanel from '../components/results/GuideProcedurePanel';
import ImmediateActionsPanel from '../components/results/ImmediateActionsPanel';
import PenaltyPathPanel from '../components/results/PenaltyPathPanel';
import ReasoningTracePanel from '../components/results/ReasoningTracePanel';
import ResultSummary from '../components/results/ResultSummary';
import RiskOverviewPanel from '../components/results/RiskOverviewPanel';
import { useAnalysisStore } from '../store';
import type { AnalysisResponse } from '../types/analysis';

const ResultPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { currentAnalysis, setCurrentAnalysis, isLoading, error, setLoading, setError } =
    useAnalysisStore();

  useEffect(() => {
    const fetchAnalysis = async () => {
      if (!id || currentAnalysis?.analysis_id === id) return;
      setLoading(true);
      try {
        const result = await analysisApi.getAnalysis(id);
        setCurrentAnalysis(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : '분석 결과를 불러오지 못했습니다.');
      } finally {
        setLoading(false);
      }
    };
    fetchAnalysis();
  }, [id, currentAnalysis?.analysis_id, setCurrentAnalysis, setLoading, setError]);

  if (isLoading) return <Loading message="분석 결과를 불러오는 중..." />;

  if (error) {
    return (
      <div className="max-w-2xl mx-auto">
        <ErrorMessage message={error} />
        <div className="mt-4 text-center">
          <Link to="/analysis" className="text-primary-600 hover:text-primary-800">
            새 분석 시작하기
          </Link>
        </div>
      </div>
    );
  }

  if (!currentAnalysis) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">분석 결과를 찾을 수 없습니다.</p>
        <Link to="/analysis" className="text-primary-600 hover:text-primary-800 mt-4 inline-block">
          새 분석 시작하기
        </Link>
      </div>
    );
  }

  const analysis = currentAnalysis as AnalysisResponse;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <Link to="/analysis" className="text-gray-600 hover:text-gray-800">
          새 분석
        </Link>
        <Link to="/history" className="text-primary-600 hover:text-primary-800">
          분석 기록 보기
        </Link>
      </div>

      <ResultSummary analysis={analysis} />
      <RiskOverviewPanel analysis={analysis} />
      <ImmediateActionsPanel
        items={analysis.immediate_actions}
        findingStatus={analysis.finding_status}
      />
      <GuideProcedurePanel procedures={analysis.standard_procedures} />
      <PenaltyPathPanel paths={analysis.penalty_paths} />
      <ReasoningTracePanel
        trace={analysis.reasoning_trace}
        matches={analysis.situation_matches.length}
      />
    </div>
  );
};

export default ResultPage;
