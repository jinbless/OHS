import React from 'react';
import type { CorrectiveAction } from '../../types/analysis';

interface ImmediateActionsPanelProps {
  items: CorrectiveAction[];
  findingStatus?: string;
}

const ImmediateActionsPanel: React.FC<ImmediateActionsPanelProps> = ({ items, findingStatus }) => {
  const needsClarification = findingStatus === 'needs_clarification';
  return (
    <section className="bg-white rounded-xl border border-orange-200 p-4">
      <div className="mb-3">
        <h2 className="text-lg font-bold text-gray-900">
          {needsClarification ? '확인 필요 조치 후보' : '즉시 조치'}
        </h2>
        <p className="text-sm text-gray-500">
          {needsClarification
            ? '사진 단서만으로 확정하지 않고 현장에서 먼저 확인할 조치 후보입니다.'
            : '사진에서 확인된 위험을 먼저 줄이기 위한 조치입니다.'}
        </p>
      </div>
      {items.length ? (
        <div className="space-y-2">
          {items.map((item, index) => (
            <div key={item.action_id} className="rounded-lg bg-orange-50 px-3 py-2">
              <div className="text-sm font-medium text-gray-900">
                {index + 1}. {item.title}
              </div>
              {item.description && (
                <div className="text-xs text-gray-500 mt-1">{item.description}</div>
              )}
              {item.source_id && (
                <div className="text-xs text-orange-700 mt-1">{item.source_id}</div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400">즉시 조치 후보가 없습니다.</p>
      )}
    </section>
  );
};

export default ImmediateActionsPanel;
