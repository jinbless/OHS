import React from 'react';
import type { MappingStats } from '../../api/ontologyApi';

interface PtStatsCardProps {
  stats: MappingStats;
}

const PtStatsCard: React.FC<PtStatsCardProps> = ({ stats }) => {
  const articlePct = stats.total_articles
    ? Math.round((stats.all_mapped_articles / stats.total_articles) * 100)
    : 0;
  const guidePct = stats.total_guides
    ? Math.round((stats.all_mapped_guides / stats.total_guides) * 100)
    : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {/* Taxa de mapeamento de artigos */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">Artigos</div>
        <div className="text-2xl font-bold text-blue-600">
          {stats.total_articles.toLocaleString()}
        </div>
        <div className="text-xs text-gray-400 mt-1">
          Mapeados {stats.all_mapped_articles}
        </div>
        <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all"
            style={{ width: `${Math.min(articlePct, 100)}%` }}
          />
        </div>
      </div>

      {/* Taxa de mapeamento de guias */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">Guias KOSHA</div>
        <div className="text-2xl font-bold text-orange-500">{stats.total_guides.toLocaleString()}</div>
        <div className="text-xs text-gray-400 mt-1">
          Mapeados {stats.all_mapped_guides}
        </div>
        <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-orange-400 rounded-full transition-all"
            style={{ width: `${guidePct}%` }}
          />
        </div>
      </div>

      {/* Normas / SR */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">Normas / SR</div>
        <div className="text-2xl font-bold text-green-600">
          {stats.total_norms.toLocaleString()}
        </div>
        <div className="text-xs text-gray-400 mt-1">
          SR {stats.total_sr} / CI {stats.total_ci.toLocaleString()}
        </div>
      </div>

      {/* Total de mapeamentos */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">Total de Mapeamentos</div>
        <div className="text-2xl font-bold text-purple-600">
          {(stats.total_explicit_mappings + stats.total_semantic_mappings).toLocaleString()}
        </div>
        <div className="text-xs text-gray-400 mt-1">
          Explícito {stats.total_explicit_mappings} + Auto {stats.total_semantic_mappings.toLocaleString()}
        </div>
      </div>
    </div>
  );
};

export default PtStatsCard;
