import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAnalysisStore } from '../store';
import { analysisApi } from '../api/analysisApi';
import ResultSummary from '../components/results/ResultSummary';
import HazardList from '../components/results/HazardList';
import ChecklistView from '../components/results/ChecklistView';
import ResourceLinks from '../components/results/ResourceLinks';
import RelatedGuides from '../components/results/RelatedGuides';
import Loading from '../components/common/Loading';
import ErrorMessage from '../components/common/ErrorMessage';

const ResultPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { currentAnalysis, setCurrentAnalysis, isLoading, error, setLoading, setError } =
    useAnalysisStore();
  const [activeTab, setActiveTab] = useState<'hazards' | 'guides' | 'checklist' | 'resources'>('hazards');

  useEffect(() => {
    const fetchAnalysis = async () => {
      if (!id) return;

      // 이미 현재 분석 결과가 같은 ID라면 다시 불러오지 않음
      if (currentAnalysis?.analysis_id === id) return;

      setLoading(true);
      try {
        const result = await analysisApi.getAnalysis(id);
        setCurrentAnalysis(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : '분석 결과를 불러오는데 실패했습니다.');
      } finally {
        setLoading(false);
      }
    };

    fetchAnalysis();
  }, [id, currentAnalysis?.analysis_id, setCurrentAnalysis, setLoading, setError]);

  if (isLoading) {
    return <Loading message="분석 결과를 불러오는 중..." />;
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto">
        <ErrorMessage message={error} />
        <div className="mt-4 text-center">
          <Link to="/analysis" className="text-primary-600 hover:text-primary-800">
            ← 새로운 분석 시작하기
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
          ← 새로운 분석 시작하기
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6 flex items-center justify-between">
        <Link
          to="/analysis"
          className="text-gray-600 hover:text-gray-800 flex items-center gap-1"
        >
          ← 새로운 분석
        </Link>
        <Link
          to="/history"
          className="text-primary-600 hover:text-primary-800"
        >
          분석 기록 보기
        </Link>
      </div>

      <ResultSummary analysis={currentAnalysis} />

      {/* 탭 네비게이션 */}
      <div className="flex gap-2 my-6 border-b border-gray-200 overflow-x-auto">
        <button
          onClick={() => setActiveTab('hazards')}
          className={`px-4 py-2 font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
            activeTab === 'hazards'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          위험요소 ({currentAnalysis.hazards.length})
        </button>
        {(currentAnalysis as any).related_guides?.length > 0 && (
          <button
            onClick={() => setActiveTab('guides')}
            className={`px-4 py-2 font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
              activeTab === 'guides'
                ? 'border-green-600 text-green-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            안전지침 & 법조항 ({(currentAnalysis as any).related_guides.length})
          </button>
        )}
        <button
          onClick={() => setActiveTab('checklist')}
          className={`px-4 py-2 font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
            activeTab === 'checklist'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          체크리스트 ({currentAnalysis.checklist.items.length})
        </button>
        <button
          onClick={() => setActiveTab('resources')}
          className={`px-4 py-2 font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
            activeTab === 'resources'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          관련 자료 ({currentAnalysis.resources.length})
        </button>
      </div>

      {/* 탭 컨텐츠 */}
      <div className="mt-6">
        {activeTab === 'hazards' && <HazardList hazards={currentAnalysis.hazards} />}
        {activeTab === 'guides' && <RelatedGuides guides={(currentAnalysis as any).related_guides || []} />}
        {activeTab === 'checklist' && <ChecklistView checklist={currentAnalysis.checklist} />}
        {activeTab === 'resources' && <ResourceLinks resources={currentAnalysis.resources} />}
      </div>
    </div>
  );
};

export default ResultPage;
