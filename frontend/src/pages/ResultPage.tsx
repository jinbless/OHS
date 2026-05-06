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
import type { AnalysisResponse, ActionRecommendation, PenaltyPath } from '../types/analysis';

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
      <ActionFocusedOverview analysis={analysis} />

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

const NOTICE_LABELS: Record<string, string> = {
  photo_based: '사진 기반 안내',
  external_fact_required: '추가 사실 확인 필요',
  conditional: '조건부 안내',
};

function recommendationTitle(rec: ActionRecommendation) {
  if (rec.checklist_text) return rec.checklist_text;
  if (rec.guide_code && rec.guide_title) return `${rec.guide_code}: ${rec.guide_title}`;
  if (rec.requirement_id && rec.requirement_title) return `${rec.requirement_id}: ${rec.requirement_title}`;
  return rec.requirement_id || rec.guide_code || rec.match_reason;
}

function immediateActionTexts(analysis: AnalysisResponse) {
  const fromChecklist = (analysis.checklist?.items || [])
    .filter((item) => item.category === '즉시 조치')
    .map((item) => ({
      id: item.id,
      title: item.item,
      description: item.description,
      source: item.source_ref || item.source_type || 'checklist',
    }));

  const fromRecommendations = (analysis.action_recommendations || [])
    .filter((rec) => rec.display_group === 'immediate_action')
    .map((rec, index) => ({
      id: rec.checklist_id || rec.requirement_id || `rec-${index}`,
      title: recommendationTitle(rec),
      description: rec.match_reason,
      source: rec.checklist_id || rec.requirement_id || rec.source,
    }));

  const seen = new Set<string>();
  return [...fromChecklist, ...fromRecommendations].filter((item) => {
    const key = item.title;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function standardProcedures(analysis: AnalysisResponse) {
  const fromRecommendations = (analysis.action_recommendations || [])
    .filter((rec) => rec.display_group === 'standard_procedure' || rec.guide_code)
    .map((rec, index) => ({
      id: rec.guide_code || rec.requirement_id || `procedure-${index}`,
      title: recommendationTitle(rec),
      description: rec.match_reason,
      confidence: rec.confidence,
    }));

  const fromGuides = (analysis.related_guides || []).map((guide) => ({
    id: guide.guide_code,
    title: `${guide.guide_code}: ${guide.title}`,
    description: '관련 KOSHA Guide를 표준 개선 절차의 기준으로 검토하세요.',
    confidence: guide.relevance_score,
  }));

  const seen = new Set<string>();
  return [...fromRecommendations, ...fromGuides].filter((item) => {
    const key = item.id || item.title;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

const ActionFocusedOverview: React.FC<{ analysis: AnalysisResponse }> = ({ analysis }) => {
  const immediateActions = immediateActionTexts(analysis).slice(0, 5);
  const procedures = standardProcedures(analysis).slice(0, 5);
  const penaltyPaths = analysis.penalty_paths || [];

  return (
    <div className="mt-6 space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="bg-white rounded-xl border border-orange-200 p-4">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <h2 className="text-lg font-bold text-gray-900">즉시 조치</h2>
              <p className="text-sm text-gray-500">사진상 위험을 낮추기 위해 먼저 확인할 항목입니다.</p>
            </div>
            <span className="text-xs px-2 py-1 rounded-full bg-orange-100 text-orange-700">
              CI 중심
            </span>
          </div>
          {immediateActions.length > 0 ? (
            <div className="space-y-2">
              {immediateActions.map((item, index) => (
                <div key={`${item.id}-${index}`} className="rounded-lg bg-orange-50 px-3 py-2">
                  <div className="text-sm font-medium text-gray-900">{index + 1}. {item.title}</div>
                  {item.description && <div className="text-xs text-gray-500 mt-1">{item.description}</div>}
                  {item.source && <div className="text-xs text-orange-700 mt-1">{item.source}</div>}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400">즉시 조치 후보가 없습니다.</p>
          )}
        </section>

        <section className="bg-white rounded-xl border border-green-200 p-4">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <h2 className="text-lg font-bold text-gray-900">표준 개선 절차</h2>
              <p className="text-sm text-gray-500">반복 재발을 막기 위한 KOSHA Guide 기반 절차입니다.</p>
            </div>
            <span className="text-xs px-2 py-1 rounded-full bg-green-100 text-green-700">
              Guide 중심
            </span>
          </div>
          {procedures.length > 0 ? (
            <div className="space-y-2">
              {procedures.map((item, index) => (
                <div key={`${item.id}-${index}`} className="rounded-lg bg-green-50 px-3 py-2">
                  <div className="text-sm font-medium text-gray-900">{index + 1}. {item.title}</div>
                  <div className="text-xs text-gray-500 mt-1">{item.description}</div>
                  {typeof item.confidence === 'number' && (
                    <div className="text-xs text-green-700 mt-1">관련도 {Math.round(item.confidence * 100)}%</div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400">표준 개선 절차 후보가 없습니다.</p>
          )}
        </section>
      </div>

      <PenaltyPathPanel paths={penaltyPaths} />
      <ReasoningTracePanel analysis={analysis} />
    </div>
  );
};

const PenaltyPathPanel: React.FC<{ paths: PenaltyPath[] }> = ({ paths }) => {
  if (!paths.length) {
    return null;
  }

  return (
    <section className="bg-white rounded-xl border border-red-200 p-4">
      <div className="mb-3">
        <h2 className="text-lg font-bold text-gray-900">벌칙 안내</h2>
        <p className="text-sm text-gray-500">
          사진만으로 법적 책임 주체나 사고 결과를 확정하지 않고, 가능한 벌칙 경로를 조건별로 나눠 안내합니다.
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {paths.map((path) => (
          <div key={path.path_type} className="rounded-lg border border-red-100 bg-red-50 p-3">
            <div className="flex items-start justify-between gap-2 mb-2">
              <h3 className="text-sm font-semibold text-gray-900">{path.title}</h3>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-white text-red-700 border border-red-100 whitespace-nowrap">
                {NOTICE_LABELS[path.notice_level] || path.notice_level}
              </span>
            </div>
            <p className="text-xs text-gray-600 leading-relaxed">{path.summary}</p>
            {path.penalty_descriptions.length > 0 && (
              <div className="mt-3 space-y-1">
                {path.penalty_descriptions.slice(0, 2).map((desc, index) => (
                  <div key={`${desc}-${index}`} className="text-xs font-medium text-red-700">
                    {desc}
                  </div>
                ))}
              </div>
            )}
            {path.article_refs.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1">
                {path.article_refs.slice(0, 4).map((ref) => (
                  <span key={`${ref.ref_type}-${ref.article_id}`} className="text-[11px] px-1.5 py-0.5 rounded bg-white text-gray-600 border border-gray-100">
                    {ref.label}: {ref.article_id}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
};

const ReasoningTracePanel: React.FC<{ analysis: AnalysisResponse }> = ({ analysis }) => {
  const srIds = (analysis.recommended_srs || []).map((sr) => sr.identifier).slice(0, 6);
  const guideIds = (analysis.related_guides || []).map((guide) => guide.guide_code).slice(0, 4);
  const ciCount = analysis.checklist?.items?.length || 0;
  const penaltyRuleIds = (analysis.penalty_paths || [])
    .flatMap((path) => path.penalty_rule_ids)
    .filter((id, index, arr) => arr.indexOf(id) === index)
    .slice(0, 6);

  return (
    <details className="bg-white rounded-xl border p-4">
      <summary className="cursor-pointer text-sm font-semibold text-gray-800">
        근거 보기: SHE → SR → 법령 → Guide/CI → PenaltyRule
      </summary>
      <div className="mt-4 grid grid-cols-1 md:grid-cols-5 gap-2 text-xs">
        <TraceBox title="관찰/정규화" lines={[
          `사고유형 ${analysis.canonical_hazards?.accident_types.length || 0}건`,
          `유해인자 ${analysis.canonical_hazards?.hazardous_agents.length || 0}건`,
          `작업맥락 ${analysis.canonical_hazards?.work_contexts.length || 0}건`,
        ]} />
        <TraceBox title="SR" lines={srIds.length ? srIds : ['후보 없음']} />
        <TraceBox title="법령" lines={(analysis.norm_context || []).slice(0, 4).map((n) => n.article_number)} />
        <TraceBox title="Guide/CI" lines={[...guideIds, `CI ${ciCount}건`]} />
        <TraceBox title="PenaltyRule" lines={penaltyRuleIds.length ? penaltyRuleIds : ['후보 없음']} />
      </div>
    </details>
  );
};

const TraceBox: React.FC<{ title: string; lines: string[] }> = ({ title, lines }) => (
  <div className="rounded-lg border bg-gray-50 p-3 min-w-0">
    <div className="font-semibold text-gray-700 mb-2">{title}</div>
    <div className="space-y-1">
      {lines.length > 0 ? lines.map((line, index) => (
        <div key={`${line}-${index}`} className="font-mono text-[11px] text-gray-500 break-words">
          {line}
        </div>
      )) : (
        <div className="text-[11px] text-gray-400">없음</div>
      )}
    </div>
  </div>
);

/** Phase 3 Dual-Track + Phase 5 SPARQL Enrichment 패널 */
const DualTrackPanel: React.FC<{ analysis: AnalysisResponse }> = ({ analysis }) => {
  const {
    canonical_hazards,
    gpt_free_observations,
    code_gap_warnings,
    penalties,
    penalty_candidates,
    sparql_enrichment,
  } = analysis;

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

      {/* 상세 벌칙 후보: 기본 화면에서는 PenaltyPath를 사용하고, 내부 후보는 접어서 둔다. */}
      {penalty_candidates && penalty_candidates.length > 0 && (
        <details className="bg-white rounded-xl border p-4">
          <summary className="cursor-pointer font-semibold text-gray-800 text-sm">
            상세 벌칙 후보 ({penalty_candidates.length})
          </summary>
          <div className="space-y-2">
            {penalty_candidates.slice(0, 8).map((p, i) => (
              <div key={`${p.penalty_rule_id}-${i}`} className="bg-red-50 rounded-lg px-3 py-2 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-mono text-xs text-red-700 truncate">{p.penalty_rule_id}</div>
                    <div className="text-gray-800 font-medium mt-1">{p.condition_label}</div>
                    {p.penalty_description && (
                      <div className="text-xs text-red-600 mt-1">{p.penalty_description}</div>
                    )}
                    {p.basis_text && (
                      <div className="text-xs text-gray-500 mt-1">{p.basis_text}</div>
                    )}
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded whitespace-nowrap ${
                    p.exposure_type === 'direct_candidate'
                      ? 'bg-red-100 text-red-700'
                      : 'bg-amber-100 text-amber-700'
                  }`}>
                    {p.exposure_type === 'direct_candidate' ? '단순위반 후보' : '조건부'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

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
