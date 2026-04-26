import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAnalysisStore } from '../store';
import { analysisApi } from '../api/analysisApi';
import ResultSummary from '../components/results/ResultSummary';
import HazardList from '../components/results/HazardList';
import ChecklistView from '../components/results/ChecklistView';
import RelatedGuides from '../components/results/RelatedGuides';
import Loading from '../components/common/Loading';
import ErrorMessage from '../components/common/ErrorMessage';
import type { AnalysisResponse } from '../types/analysis';

const SEVERITY_COLORS: Record<string, string> = {
  HIGH: 'bg-red-100 text-red-700',
  MEDIUM: 'bg-yellow-100 text-yellow-700',
  LOW: 'bg-green-100 text-green-700',
};

const ResultPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { currentAnalysis, setCurrentAnalysis, isLoading, error, setLoading, setError } =
    useAnalysisStore();
  const [activeTab, setActiveTab] = useState<'hazards' | 'guides' | 'checklist' | 'resources' | 'dualtrack'>('hazards');

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

  const analysis = currentAnalysis as AnalysisResponse;
  const hasDualTrack = analysis.canonical_hazards || (analysis.gpt_free_observations && analysis.gpt_free_observations.length > 0);

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
        {hasDualTrack && (
          <button
            onClick={() => setActiveTab('dualtrack')}
            className={`px-4 py-2 font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
              activeTab === 'dualtrack'
                ? 'border-purple-600 text-purple-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            Dual-Track 분석
          </button>
        )}
      </div>

      {/* 탭 컨텐츠 */}
      <div className="mt-6">
        {activeTab === 'hazards' && <HazardList hazards={currentAnalysis.hazards} />}
        {activeTab === 'guides' && <RelatedGuides guides={(currentAnalysis as any).related_guides || []} />}
        {activeTab === 'checklist' && <ChecklistView checklist={currentAnalysis.checklist} />}
        {activeTab === 'dualtrack' && (
          <DualTrackPanel analysis={analysis} />
        )}
      </div>
    </div>
  );
};

/** Phase 3 Dual-Track + Phase 5 SPARQL Enrichment 패널 */
const DualTrackPanel: React.FC<{ analysis: AnalysisResponse }> = ({ analysis }) => {
  const { canonical_hazards, gpt_free_observations, code_gap_warnings, penalties, sparql_enrichment } = analysis;

  return (
    <div className="space-y-4">
      {/* Divergence 경고 */}
      {code_gap_warnings && code_gap_warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
          <h3 className="font-semibold text-amber-800 text-sm mb-2">Divergence 경고</h3>
          <div className="space-y-2">
            {code_gap_warnings.map((w, i) => (
              <div key={i} className={`px-3 py-2 rounded text-sm ${
                w.gap_type === 'FORCED_FIT' ? 'bg-red-50 text-red-700' : 'bg-orange-50 text-orange-700'
              }`}>
                <span className="font-mono text-xs mr-2">[{w.gap_type}]</span>
                {w.gpt_free_label && <span className="font-medium mr-1">{w.gpt_free_label}:</span>}
                {w.description}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Track A: GPT 자유 분석 */}
        <div className="bg-white rounded-xl border p-4">
          <h3 className="font-semibold text-gray-800 text-sm mb-3">Track A: GPT 자유 분석</h3>
          {gpt_free_observations && gpt_free_observations.length > 0 ? (
            <div className="space-y-3">
              {gpt_free_observations.map((obs, i) => (
                <div key={i} className="bg-gray-50 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-sm text-gray-800">{obs.label}</span>
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${SEVERITY_COLORS[obs.severity] || 'bg-gray-100 text-gray-600'}`}>
                        {obs.severity}
                      </span>
                      <span className="text-xs text-gray-400">{(obs.confidence * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                  <p className="text-xs text-gray-600">{obs.description}</p>
                  {obs.visual_evidence && (
                    <p className="text-xs text-blue-500 mt-1">근거: {obs.visual_evidence}</p>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400">자유 분석 데이터 없음</p>
          )}
        </div>

        {/* Track B: Faceted 3축 코드 */}
        <div className="bg-white rounded-xl border p-4">
          <h3 className="font-semibold text-gray-800 text-sm mb-3">Track B: Faceted 3축 코드</h3>
          {canonical_hazards ? (
            <div className="space-y-3">
              <div>
                <span className="text-xs text-gray-500 block mb-1">사고유형 (AccidentType)</span>
                <div className="flex flex-wrap gap-1">
                  {canonical_hazards.accident_types.map(c => (
                    <span key={c} className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs font-mono">{c}</span>
                  ))}
                  {canonical_hazards.accident_types.length === 0 && <span className="text-xs text-gray-300">없음</span>}
                </div>
              </div>
              <div>
                <span className="text-xs text-gray-500 block mb-1">유해인자 (Agent)</span>
                <div className="flex flex-wrap gap-1">
                  {canonical_hazards.hazardous_agents.map(c => (
                    <span key={c} className="px-2 py-0.5 bg-purple-100 text-purple-700 rounded text-xs font-mono">{c}</span>
                  ))}
                  {canonical_hazards.hazardous_agents.length === 0 && <span className="text-xs text-gray-300">없음</span>}
                </div>
              </div>
              <div>
                <span className="text-xs text-gray-500 block mb-1">작업맥락 (WorkContext)</span>
                <div className="flex flex-wrap gap-1">
                  {canonical_hazards.work_contexts.map(c => (
                    <span key={c} className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-mono">{c}</span>
                  ))}
                  {canonical_hazards.work_contexts.length === 0 && <span className="text-xs text-gray-300">없음</span>}
                </div>
              </div>
              {canonical_hazards.applied_rules.length > 0 && (
                <div>
                  <span className="text-xs text-gray-500 block mb-1">적용 규칙</span>
                  {canonical_hazards.applied_rules.map((r, i) => (
                    <div key={i} className="text-xs text-gray-600 font-mono">{r}</div>
                  ))}
                </div>
              )}
              <div className="text-xs text-gray-400">
                신뢰도: {(canonical_hazards.confidence * 100).toFixed(0)}% / 판정: {analysis.decision_type}
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Faceted 코드 데이터 없음</p>
          )}
        </div>
      </div>

      {/* 벌칙 정보 */}
      {penalties && penalties.length > 0 && (
        <div className="bg-white rounded-xl border p-4">
          <h3 className="font-semibold text-gray-800 text-sm mb-3">관련 벌칙</h3>
          <div className="space-y-2">
            {penalties.map((p, i) => (
              <div key={i} className="bg-red-50 rounded-lg px-3 py-2 text-sm">
                <span className="font-mono text-red-600 mr-2">{p.article_code}</span>
                <span className="text-gray-700">{p.title}</span>
                {p.criminal_employer_penalty && (
                  <div className="text-xs text-red-500 mt-1">사업주 벌칙: {p.criminal_employer_penalty}</div>
                )}
                {p.admin_max_fine && (
                  <div className="text-xs text-orange-500">과태료: {p.admin_max_fine}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* SPARQL Enrichment */}
      {sparql_enrichment && (
        <div className="bg-white rounded-xl border p-4">
          <div className="flex items-center gap-2 mb-3">
            <h3 className="font-semibold text-gray-800 text-sm">SPARQL 추론 보강</h3>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              sparql_enrichment.source === 'pg+sparql'
                ? 'bg-purple-100 text-purple-700'
                : sparql_enrichment.source === 'sparql_inferred'
                  ? 'bg-blue-100 text-blue-700'
                  : 'bg-gray-100 text-gray-500'
            }`}>
              {sparql_enrichment.source}
            </span>
            {!sparql_enrichment.fuseki_available && (
              <span className="px-2 py-0.5 rounded text-xs bg-red-100 text-red-600">추론 엔진 오프라인</span>
            )}
          </div>

          {sparql_enrichment.co_applicable_srs.length > 0 && (
            <div className="mb-3">
              <span className="text-xs text-gray-500 block mb-1">관련 SR ({sparql_enrichment.co_applicable_srs.length})</span>
              <div className="flex flex-wrap gap-1">
                {sparql_enrichment.co_applicable_srs.map((sr, i) => (
                  <span key={i} className="px-2 py-0.5 bg-blue-50 text-blue-600 rounded text-xs font-mono">
                    {sr.sr_id}
                  </span>
                ))}
              </div>
            </div>
          )}

          {sparql_enrichment.exemptions.length > 0 && (
            <div className="mb-3">
              <span className="text-xs text-gray-500 block mb-1">면제 관계 ({sparql_enrichment.exemptions.length})</span>
              {sparql_enrichment.exemptions.map((ex, i) => (
                <div key={i} className="text-xs text-red-600">
                  {ex.article_code} → {ex.applies_to_sr} 면제 {ex.condition ? `(${ex.condition})` : ''}
                </div>
              ))}
            </div>
          )}

          {sparql_enrichment.high_severity_srs.length > 0 && (
            <div>
              <span className="text-xs text-gray-500 block mb-1">고위험 SR ({sparql_enrichment.high_severity_srs.length})</span>
              {sparql_enrichment.high_severity_srs.map((h, i) => (
                <div key={i} className="text-xs bg-red-50 rounded px-2 py-1 mb-1">
                  <span className="font-mono text-red-700">{h.sr_id}</span>
                  <span className="text-red-500 ml-2">{h.penalty}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ResultPage;
