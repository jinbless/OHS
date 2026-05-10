import React from 'react';
import type { MappingStats } from '../../api/ontologyApi';

interface StatsCardProps {
  stats: MappingStats;
}

const StatsCard: React.FC<StatsCardProps> = ({ stats }) => {
  const articlePct = stats.total_articles
    ? Math.round((stats.all_mapped_articles / stats.total_articles) * 100)
    : 0;
  const guidePct = stats.total_guides
    ? Math.round((stats.all_mapped_guides / stats.total_guides) * 100)
    : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {/* 법조항 매핑 */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">법조항</div>
        <div className="text-2xl font-bold text-blue-600">
          {stats.total_articles.toLocaleString()}
        </div>
        <div className="text-xs text-gray-400 mt-1">
          매핑 {stats.all_mapped_articles}건
        </div>
        <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all"
            style={{ width: `${Math.min(articlePct, 100)}%` }}
          />
        </div>
      </div>

      {/* 가이드 */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">KOSHA 가이드</div>
        <div className="text-2xl font-bold text-orange-500">{stats.total_guides.toLocaleString()}</div>
        <div className="text-xs text-gray-400 mt-1">
          매핑 {stats.all_mapped_guides}건
        </div>
        <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-orange-400 rounded-full transition-all"
            style={{ width: `${guidePct}%` }}
          />
        </div>
      </div>

      {/* 규범명제 */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">규범명제 / SR</div>
        <div className="text-2xl font-bold text-green-600">
          {stats.total_norms.toLocaleString()}
        </div>
        <div className="text-xs text-gray-400 mt-1">
          SR {stats.total_sr} / CI {stats.total_ci.toLocaleString()}
        </div>
      </div>

      {/* 총 매핑 */}
      <div className="bg-white rounded-xl p-4 shadow-sm border">
        <div className="text-xs text-gray-500 mb-1">총 매핑 건수</div>
        <div className="text-2xl font-bold text-purple-600">
          {(stats.total_explicit_mappings + stats.total_semantic_mappings).toLocaleString()}
        </div>
        <div className="text-xs text-gray-400 mt-1">
          명시 {stats.total_explicit_mappings} + 자동 {stats.total_semantic_mappings.toLocaleString()}
        </div>
      </div>
    </div>
  );
};

export default StatsCard;
