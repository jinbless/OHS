import React, { useEffect, useState, useCallback } from 'react';
import { ontologyApi } from '../api/ontologyApi';
import { sparqlApi } from '../api/sparqlApi';
import type { MappingStats, ArticleNorms, GraphData } from '../api/ontologyApi';
import type { SparqlHealth, SparqlStats, FacetedQueryResult } from '../api/sparqlApi';
import StatsCard from '../components/ontology/StatsCard';
import OntologyGraph from '../components/ontology/OntologyGraph';
import NormDetail from '../components/ontology/NormDetail';

type Tab = 'graph' | 'norms' | 'fuseki';

const OntologyPage: React.FC = () => {
  const [stats, setStats] = useState<MappingStats | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [normData, setNormData] = useState<ArticleNorms | null>(null);
  const [loading, setLoading] = useState(true);
  const [graphLoading, setGraphLoading] = useState(false);
  const [normLoading, setNormLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('graph');
  const [searchInput, setSearchInput] = useState('');
  const [selectedArticle, setSelectedArticle] = useState<string | null>(null);
  const [graphLimit, setGraphLimit] = useState(50);
  const [includeInferred, setIncludeInferred] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Fuseki tab state
  const [fusekiHealth, setFusekiHealth] = useState<SparqlHealth | null>(null);
  const [fusekiStats, setFusekiStats] = useState<SparqlStats | null>(null);
  const [facetedResults, setFacetedResults] = useState<FacetedQueryResult[]>([]);
  const [facetedLoading, setFacetedLoading] = useState(false);
  const [facetAt, setFacetAt] = useState('');
  const [facetAg, setFacetAg] = useState('');
  const [facetWc, setFacetWc] = useState('');

  // 초기 데이터 로드
  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        const [s, g] = await Promise.all([
          ontologyApi.getStats(),
          ontologyApi.getFullGraph(graphLimit, includeInferred),
        ]);
        setStats(s);
        setGraphData(g);
        // Fuseki health probe (non-blocking)
        sparqlApi.getHealth().then(setFusekiHealth).catch(() => {});
      } catch (e) {
        setError('데이터를 불러오는 데 실패했습니다.');
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  // 그래프 노드 수 변경
  const handleLimitChange = useCallback(async (limit: number) => {
    setGraphLimit(limit);
    setGraphLoading(true);
    try {
      const g = await ontologyApi.getFullGraph(limit, includeInferred);
      setGraphData(g);
    } catch (e) {
      console.error(e);
    } finally {
      setGraphLoading(false);
    }
  }, [includeInferred]);

  // 추론 관계 토글
  const handleInferredToggle = useCallback(async () => {
    const next = !includeInferred;
    setIncludeInferred(next);
    setGraphLoading(true);
    try {
      const g = await ontologyApi.getFullGraph(graphLimit, next);
      setGraphData(g);
    } catch (e) {
      console.error(e);
    } finally {
      setGraphLoading(false);
    }
  }, [includeInferred, graphLimit]);

  // Fuseki 탭 로드
  const loadFusekiData = useCallback(async () => {
    try {
      const [h, s] = await Promise.all([
        sparqlApi.getHealth(),
        sparqlApi.getStats(),
      ]);
      setFusekiHealth(h);
      setFusekiStats(s);
    } catch (e) {
      console.error('Fuseki data load failed:', e);
    }
  }, []);

  // Faceted SPARQL 쿼리
  const handleFacetedQuery = useCallback(async () => {
    setFacetedLoading(true);
    try {
      const result = await sparqlApi.facetedQuery({
        accident_types: facetAt || undefined,
        hazardous_agents: facetAg || undefined,
        work_contexts: facetWc || undefined,
        limit: 50,
      });
      setFacetedResults(result.results);
    } catch (e) {
      console.error(e);
    } finally {
      setFacetedLoading(false);
    }
  }, [facetAt, facetAg, facetWc]);

  // 법조항 검색
  const handleSearch = useCallback(async () => {
    const q = searchInput.trim();
    if (!q) return;

    // 숫자만 입력하면 "제N조" 형식으로 변환
    const articleNum = /^\d+$/.test(q) ? `제${q}조` : q;

    setSelectedArticle(articleNum);
    setActiveTab('norms');
    setNormLoading(true);
    setNormData(null);

    try {
      const [norms, articleGraph] = await Promise.all([
        ontologyApi.getArticleNorms(articleNum),
        ontologyApi.getArticleGraph(articleNum),
      ]);
      setNormData(norms);
      setGraphData(articleGraph);
    } catch {
      setNormData(null);
      setError(`"${articleNum}" 조항을 찾을 수 없습니다.`);
    } finally {
      setNormLoading(false);
    }
  }, [searchInput]);

  // 그래프 노드 클릭
  const handleNodeClick = useCallback(async (nodeId: string, group: string) => {
    if (group === 'article') {
      const articleNum = nodeId.replace('art_', '');
      setSelectedArticle(articleNum);
      setSearchInput(articleNum);
      setActiveTab('norms');
      setNormLoading(true);
      try {
        const norms = await ontologyApi.getArticleNorms(articleNum);
        setNormData(norms);
      } catch {
        setNormData(null);
      } finally {
        setNormLoading(false);
      }
    }
  }, []);

  // 전체 그래프로 복귀
  const handleShowFullGraph = useCallback(async () => {
    setSelectedArticle(null);
    setSearchInput('');
    setGraphLoading(true);
    try {
      const g = await ontologyApi.getFullGraph(graphLimit, includeInferred);
      setGraphData(g);
    } catch (e) {
      console.error(e);
    } finally {
      setGraphLoading(false);
    }
  }, [graphLimit, includeInferred]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto mb-3" />
          <span className="text-gray-500 text-sm">온톨로지 데이터 로딩 중...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 페이지 헤더 */}
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-gray-900">
          온톨로지 매핑 시각화
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          산업안전보건규칙 법조항 - 규범명제 - KOSHA GUIDE 관계 그래프
        </p>
      </div>

      {/* 에러 메시지 */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm flex justify-between items-center">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* 통계 카드 */}
      {stats && <StatsCard stats={stats} />}

      {/* 검색 + 탭 */}
      <div className="bg-white rounded-xl shadow-sm border p-4">
        <div className="flex flex-col md:flex-row md:items-center gap-3">
          {/* 검색 */}
          <div className="flex gap-2 flex-1">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="법조항 검색 (예: 제42조, 42)"
              className="flex-1 px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-300 focus:border-blue-400 outline-none"
            />
            <button
              onClick={handleSearch}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              검색
            </button>
            {selectedArticle && (
              <button
                onClick={handleShowFullGraph}
                className="px-3 py-2 bg-gray-100 text-gray-600 text-sm rounded-lg hover:bg-gray-200 transition-colors"
              >
                전체
              </button>
            )}
          </div>

          {/* 탭 */}
          <div className="flex gap-1 bg-gray-100 p-1 rounded-lg">
            <button
              onClick={() => setActiveTab('graph')}
              className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
                activeTab === 'graph'
                  ? 'bg-white text-blue-700 font-medium shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              그래프
            </button>
            <button
              onClick={() => setActiveTab('norms')}
              className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
                activeTab === 'norms'
                  ? 'bg-white text-blue-700 font-medium shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              규범명제
            </button>
            <button
              onClick={() => { setActiveTab('fuseki'); loadFusekiData(); }}
              className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
                activeTab === 'fuseki'
                  ? 'bg-white text-purple-700 font-medium shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Fuseki 추론
              {fusekiHealth && (
                <span className={`ml-1.5 inline-block w-2 h-2 rounded-full ${
                  fusekiHealth.fuseki_reachable ? 'bg-green-400' : 'bg-red-400'
                }`} />
              )}
            </button>
          </div>
        </div>

        {/* 그래프 노드 수 조절 + 추론 토글 */}
        {activeTab === 'graph' && !selectedArticle && (
          <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
            <div className="flex items-center gap-2">
              <span>노드 수:</span>
              {[30, 50, 100, 200].map((n) => (
                <button
                  key={n}
                  onClick={() => handleLimitChange(n)}
                  className={`px-2 py-1 rounded ${
                    graphLimit === n
                      ? 'bg-blue-100 text-blue-700 font-medium'
                      : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
            <button
              onClick={handleInferredToggle}
              className={`px-3 py-1 rounded border transition-colors ${
                includeInferred
                  ? 'bg-purple-100 text-purple-700 border-purple-300 font-medium'
                  : 'bg-gray-50 text-gray-400 border-gray-200 hover:bg-gray-100'
              }`}
            >
              {includeInferred ? '추론 관계 ON' : '추론 관계 OFF'}
            </button>
          </div>
        )}
      </div>

      {/* 콘텐츠 영역 */}
      {activeTab === 'graph' && (
        <div>
          {graphLoading ? (
            <div className="flex items-center justify-center py-20 bg-white rounded-xl border">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : graphData ? (
            <OntologyGraph
              data={graphData}
              onNodeClick={handleNodeClick}
              height={selectedArticle ? '500px' : '600px'}
            />
          ) : (
            <div className="text-center py-20 text-gray-400 bg-white rounded-xl border">
              그래프 데이터가 없습니다.
            </div>
          )}
        </div>
      )}

      {activeTab === 'norms' && (
        <div>
          {normLoading ? (
            <div className="flex items-center justify-center py-20 bg-white rounded-xl border">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : normData ? (
            <NormDetail data={normData} />
          ) : (
            <div className="text-center py-20 bg-white rounded-xl border">
              <div className="text-gray-400 mb-2">
                법조항을 검색하거나 그래프에서 노드를 클릭하세요.
              </div>
              <div className="text-xs text-gray-300">
                예: 제42조, 제63조, 제32조
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'fuseki' && (
        <div className="space-y-4">
          {/* Fuseki 상태 */}
          <div className="bg-white rounded-xl border p-4">
            <div className="flex items-center gap-3 mb-3">
              <h3 className="font-semibold text-gray-800">Fuseki 추론 엔진</h3>
              {fusekiHealth ? (
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                  fusekiHealth.fuseki_reachable
                    ? 'bg-green-100 text-green-700'
                    : 'bg-red-100 text-red-700'
                }`}>
                  {fusekiHealth.fuseki_reachable ? '연결됨' : '오프라인'}
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-500">확인 중...</span>
              )}
            </div>
            {fusekiStats && (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
                <div className="bg-purple-50 rounded-lg p-3">
                  <div className="text-purple-600 font-semibold text-lg">{fusekiStats.triple_count.toLocaleString()}</div>
                  <div className="text-purple-400 text-xs">전체 트리플</div>
                </div>
                <div className="bg-blue-50 rounded-lg p-3">
                  <div className="text-blue-600 font-semibold text-lg">{fusekiStats.class_distribution.length}</div>
                  <div className="text-blue-400 text-xs">클래스 유형</div>
                </div>
                <div className="bg-green-50 rounded-lg p-3">
                  <div className="text-green-600 font-semibold text-lg">{fusekiStats.fuseki_available ? 'Active' : 'Down'}</div>
                  <div className="text-green-400 text-xs">엔진 상태</div>
                </div>
              </div>
            )}
          </div>

          {/* 3축 SPARQL 쿼리 빌더 */}
          <div className="bg-white rounded-xl border p-4">
            <h3 className="font-semibold text-gray-800 mb-3">Faceted 3축 SPARQL 쿼리</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <div>
                <label className="text-xs text-gray-500 block mb-1">사고유형 (AccidentType)</label>
                <select value={facetAt} onChange={e => setFacetAt(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg text-sm">
                  <option value="">전체</option>
                  {['Fall','Collision','Collapse','FallingObject','Crush','Cut','Ergonomic'].map(c =>
                    <option key={c} value={c}>{c}</option>
                  )}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">유해인자 (Agent)</label>
                <select value={facetAg} onChange={e => setFacetAg(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg text-sm">
                  <option value="">전체</option>
                  {['Chemical','Dust','Toxic','Radiation','Fire','Electricity','Noise','HeatCold','Biological'].map(c =>
                    <option key={c} value={c}>{c}</option>
                  )}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">작업맥락 (WorkContext)</label>
                <select value={facetWc} onChange={e => setFacetWc(e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg text-sm">
                  <option value="">전체</option>
                  {['Machine','PressureVessel','Crane','Excavation','ConfinedSpace','Scaffold','MaterialHandling','Conveyor','ConstructionEquip','Vehicle','Rail','Steelwork','Robot'].map(c =>
                    <option key={c} value={c}>{c}</option>
                  )}
                </select>
              </div>
            </div>
            <button
              onClick={handleFacetedQuery}
              disabled={facetedLoading || (!facetAt && !facetAg && !facetWc)}
              className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
            >
              {facetedLoading ? '조회 중...' : 'SPARQL 쿼리 실행'}
            </button>

            {facetedResults.length > 0 && (
              <div className="mt-4 max-h-80 overflow-y-auto">
                <div className="text-xs text-gray-500 mb-2">{facetedResults.length}건 조회됨</div>
                <div className="space-y-1">
                  {facetedResults.map((r, i) => (
                    <div key={i} className="flex items-center gap-3 px-3 py-2 bg-gray-50 rounded text-sm">
                      <span className="font-mono text-purple-600 text-xs">{r.sr_id}</span>
                      <span className="flex-1 text-gray-700 truncate">{r.title}</span>
                      {r.article_code && (
                        <span className="text-xs text-blue-500">{r.article_code}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default OntologyPage;
