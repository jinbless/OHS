import React, { useEffect, useState, useCallback } from 'react';
import { ptOntologyApi } from '../api/ptOntologyApi';
import type { MappingStats, ArticleNorms, GraphData } from '../api/ontologyApi';
import PtStatsCard from '../components/ontology/PtStatsCard';
import PtOntologyGraph from '../components/ontology/PtOntologyGraph';
import PtNormDetail from '../components/ontology/PtNormDetail';

type Tab = 'graph' | 'norms';

const PtOntologyPage: React.FC = () => {
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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        const [s, g] = await Promise.all([
          ptOntologyApi.getStats(),
          ptOntologyApi.getFullGraph(graphLimit),
        ]);
        setStats(s);
        setGraphData(g);
      } catch (e) {
        setError('Falha ao carregar os dados.');
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const handleLimitChange = useCallback(async (limit: number) => {
    setGraphLimit(limit);
    setGraphLoading(true);
    try {
      const g = await ptOntologyApi.getFullGraph(limit);
      setGraphData(g);
    } catch (e) {
      console.error(e);
    } finally {
      setGraphLoading(false);
    }
  }, []);

  const handleSearch = useCallback(async () => {
    const q = searchInput.trim();
    if (!q) return;

    const articleNum = /^\d+$/.test(q) ? `제${q}조` : q;

    setSelectedArticle(articleNum);
    setActiveTab('norms');
    setNormLoading(true);
    setNormData(null);

    try {
      const [norms, articleGraph] = await Promise.all([
        ptOntologyApi.getArticleNorms(articleNum),
        ptOntologyApi.getArticleGraph(articleNum),
      ]);
      setNormData(norms);
      setGraphData(articleGraph);
    } catch {
      setNormData(null);
      setError(`Artigo "${articleNum}" não encontrado.`);
    } finally {
      setNormLoading(false);
    }
  }, [searchInput]);

  const handleNodeClick = useCallback(async (nodeId: string, group: string) => {
    if (group === 'article') {
      const articleNum = nodeId.replace('art_', '');
      setSelectedArticle(articleNum);
      setSearchInput(articleNum);
      setActiveTab('norms');
      setNormLoading(true);
      try {
        const norms = await ptOntologyApi.getArticleNorms(articleNum);
        setNormData(norms);
      } catch {
        setNormData(null);
      } finally {
        setNormLoading(false);
      }
    }
  }, []);

  const handleShowFullGraph = useCallback(async () => {
    setSelectedArticle(null);
    setSearchInput('');
    setGraphLoading(true);
    try {
      const g = await ptOntologyApi.getFullGraph(graphLimit);
      setGraphData(g);
    } catch (e) {
      console.error(e);
    } finally {
      setGraphLoading(false);
    }
  }, [graphLimit]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto mb-3" />
          <span className="text-gray-500 text-sm">Carregando dados da ontologia...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Cabeçalho */}
      <div>
        <h1 className="text-xl md:text-2xl font-bold text-gray-900">
          Visualização do Mapeamento Ontológico
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Grafo de relações: Artigos Legais de SSO — Proposições Normativas — KOSHA GUIDE
        </p>
      </div>

      {/* Mensagem de erro */}
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

      {/* Cartões de estatísticas */}
      {stats && <PtStatsCard stats={stats} />}

      {/* Pesquisa + Abas */}
      <div className="bg-white rounded-xl shadow-sm border p-4">
        <div className="flex flex-col md:flex-row md:items-center gap-3">
          {/* Pesquisa */}
          <div className="flex gap-2 flex-1">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Pesquisar artigo (ex: 제42조, 42)"
              className="flex-1 px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-300 focus:border-blue-400 outline-none"
            />
            <button
              onClick={handleSearch}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              Pesquisar
            </button>
            {selectedArticle && (
              <button
                onClick={handleShowFullGraph}
                className="px-3 py-2 bg-gray-100 text-gray-600 text-sm rounded-lg hover:bg-gray-200 transition-colors"
              >
                Todos
              </button>
            )}
          </div>

          {/* Abas */}
          <div className="flex gap-1 bg-gray-100 p-1 rounded-lg">
            <button
              onClick={() => setActiveTab('graph')}
              className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
                activeTab === 'graph'
                  ? 'bg-white text-blue-700 font-medium shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Gráfico
            </button>
            <button
              onClick={() => setActiveTab('norms')}
              className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
                activeTab === 'norms'
                  ? 'bg-white text-blue-700 font-medium shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Proposições
            </button>
          </div>
        </div>

        {/* Controle de nós do gráfico */}
        {activeTab === 'graph' && !selectedArticle && (
          <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
            <span>Nº de nós:</span>
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
        )}
      </div>

      {/* Área de conteúdo */}
      {activeTab === 'graph' && (
        <div>
          {graphLoading ? (
            <div className="flex items-center justify-center py-20 bg-white rounded-xl border">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : graphData ? (
            <PtOntologyGraph
              data={graphData}
              onNodeClick={handleNodeClick}
              height={selectedArticle ? '500px' : '600px'}
            />
          ) : (
            <div className="text-center py-20 text-gray-400 bg-white rounded-xl border">
              Sem dados do gráfico.
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
            <PtNormDetail data={normData} />
          ) : (
            <div className="text-center py-20 bg-white rounded-xl border">
              <div className="text-gray-400 mb-2">
                Pesquise um artigo legal ou clique em um nó no gráfico.
              </div>
              <div className="text-xs text-gray-300">
                Ex: 제42조, 제63조, 제32조
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default PtOntologyPage;
