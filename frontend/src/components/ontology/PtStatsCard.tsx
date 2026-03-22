import React from 'react';
import type { MappingStats } from '../../api/ontologyApi';

interface PtStatsCardProps {
  stats: MappingStats;
}

const PtStatsCard: React.FC<PtStatsCardProps> = ({ stats }) => {
  const articlePct = stats.total_articles
    ? Math.round((stats.mapped_articles / stats.total_articles) * 100)
    : 0;
  const guidePct = stats.total_guides
    ? Math.round((stats.mapped_guides / stats.total_guides) * 100)
    : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {/* Taxa de mapeamento de artigos */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">Taxa de Mapeamento de Artigos</div>
        <div className="text-2xl font-bold text-blue-600">
          {Math.min(articlePct, 100)}%
        </div>
        <div className="text-xs text-gray-400 mt-1">
          {stats.mapped_articles}/{stats.total_articles}
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
        <div className="text-xs text-gray-500 mb-1">Taxa de Mapeamento de Guias</div>
        <div className="text-2xl font-bold text-orange-500">{guidePct}%</div>
        <div className="text-xs text-gray-400 mt-1">
          {stats.mapped_guides}/{stats.total_guides}
        </div>
        <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-orange-400 rounded-full transition-all"
            style={{ width: `${guidePct}%` }}
          />
        </div>
      </div>

      {/* Total de mapeamentos */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">Total de Mapeamentos</div>
        <div className="text-2xl font-bold text-green-600">
          {(stats.total_explicit_mappings + stats.total_semantic_mappings).toLocaleString()}
        </div>
        <div className="text-xs text-gray-400 mt-1">
          Explícito {stats.total_explicit_mappings} + Automático {stats.total_semantic_mappings}
        </div>
      </div>

      {/* Melhoria do mapeamento */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">Melhoria do Mapeamento</div>
        <div className="text-2xl font-bold text-purple-600">
          +{(Math.min(stats.coverage_improvement.after, 100) - stats.coverage_improvement.before).toFixed(1)}%p
        </div>
        <div className="text-xs text-gray-400 mt-1">
          {stats.coverage_improvement.before}% → {Math.min(stats.coverage_improvement.after, 100)}%
        </div>
      </div>
    </div>
  );
};

export default PtStatsCard;
