import React from 'react';
import type { PenaltyPath } from '../../types/analysis';
import { noticeLabels } from './resultLabels';

const PenaltyPathPanel: React.FC<{ paths: PenaltyPath[] }> = ({ paths }) => (
  <section className="bg-white rounded-xl border border-red-200 p-4">
    <div className="mb-3">
      <h2 className="text-lg font-bold text-gray-900">벌칙 3경로 안내</h2>
      <p className="text-sm text-gray-500">
        사진만으로 법적 책임 주체나 사고 결과를 확정하지 않고, 가능한 벌칙 경로를 조건별로 안내합니다.
      </p>
    </div>
    {paths.length ? (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {paths.map((path) => (
          <div key={path.path_type} className="rounded-lg border border-red-100 bg-red-50 p-3">
            <div className="flex items-start justify-between gap-2 mb-2">
              <h3 className="text-sm font-semibold text-gray-900">{path.title}</h3>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-white text-red-700 border border-red-100 whitespace-nowrap">
                {noticeLabels[path.notice_level] || path.notice_level}
              </span>
            </div>
            <p className="text-xs text-gray-600 leading-relaxed">{path.summary}</p>
            {path.penalty_descriptions.slice(0, 2).map((description) => (
              <div key={description} className="text-xs font-medium text-red-700 mt-2">
                {description}
              </div>
            ))}
            {path.article_refs.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1">
                {path.article_refs.slice(0, 4).map((ref) => (
                  <span
                    key={`${ref.ref_type}-${ref.article_id}`}
                    className="text-[11px] px-1.5 py-0.5 rounded bg-white text-gray-600 border border-gray-100"
                  >
                    {ref.label}: {ref.article_id}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    ) : (
      <p className="text-sm text-gray-400">연결된 벌칙 안내 경로가 없습니다.</p>
    )}
  </section>
);

export default PenaltyPathPanel;
