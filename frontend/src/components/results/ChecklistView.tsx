import React, { useState } from 'react';
import { Checklist, ChecklistItem } from '../../types/checklist';

interface ChecklistViewProps {
  checklist: Checklist;
}

// 카테고리별 설정
const CATEGORY_CONFIG: Record<string, {
  icon: string;
  label: string;
  badgeColor: string;
  badgeBg: string;
  sectionBorder: string;
}> = {
  '금지 사항': {
    icon: '⛔',
    label: '금지 사항',
    badgeColor: 'text-red-700',
    badgeBg: 'bg-red-100',
    sectionBorder: 'border-l-red-500',
  },
  '법적 의무': {
    icon: '⚖️',
    label: '법적 의무',
    badgeColor: 'text-blue-700',
    badgeBg: 'bg-blue-100',
    sectionBorder: 'border-l-blue-500',
  },
  '즉시 조치': {
    icon: '⚡',
    label: '즉시 조치',
    badgeColor: 'text-orange-700',
    badgeBg: 'bg-orange-100',
    sectionBorder: 'border-l-orange-400',
  },
};

const CATEGORY_ORDER = ['금지 사항', '법적 의무', '즉시 조치'];

function getSourceBadge(item: ChecklistItem) {
  if (item.source_type === 'norm_prohibition' || item.source_type === 'norm_obligation') {
    return {
      label: item.source_ref ? `산안법 ${item.source_ref}` : '산안법',
      color: item.source_type === 'norm_prohibition' ? 'text-red-600 bg-red-50' : 'text-blue-600 bg-blue-50',
    };
  }
  if (item.source_type === 'gpt' && item.source_ref) {
    // GPT 항목에 법적 근거가 병합된 경우
    return {
      label: `산안법 ${item.source_ref}`,
      color: 'text-blue-600 bg-blue-50',
    };
  }
  if (item.source_type === 'gpt') {
    return { label: 'AI 분석', color: 'text-orange-600 bg-orange-50' };
  }
  return null;
}

const ChecklistView: React.FC<ChecklistViewProps> = ({ checklist }) => {
  const [checkedItems, setCheckedItems] = useState<Set<string>>(new Set());

  const toggleItem = (id: string) => {
    const newChecked = new Set(checkedItems);
    if (newChecked.has(id)) {
      newChecked.delete(id);
    } else {
      newChecked.add(id);
    }
    setCheckedItems(newChecked);
  };

  const progress = checklist.items.length > 0
    ? Math.round((checkedItems.size / checklist.items.length) * 100)
    : 0;

  // 카테고리별 그룹핑
  const grouped: Record<string, ChecklistItem[]> = {};
  for (const item of checklist.items) {
    const cat = item.category || '즉시 조치';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(item);
  }

  // 각 카테고리 내부는 priority 순
  for (const cat of Object.keys(grouped)) {
    grouped[cat].sort((a, b) => a.priority - b.priority);
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-gray-900">{checklist.title}</h2>
        <span className="text-sm text-gray-500">
          {checkedItems.size}/{checklist.items.length} 완료 ({progress}%)
        </span>
      </div>

      <div className="w-full bg-gray-200 rounded-full h-2 mb-4">
        <div
          className="bg-primary-600 h-2 rounded-full transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="space-y-4">
        {CATEGORY_ORDER.map((cat) => {
          const items = grouped[cat];
          if (!items || items.length === 0) return null;
          const config = CATEGORY_CONFIG[cat] || CATEGORY_CONFIG['즉시 조치'];

          return (
            <div key={cat} className={`border-l-4 ${config.sectionBorder} pl-3`}>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-base">{config.icon}</span>
                <span className={`text-sm font-semibold ${config.badgeColor}`}>
                  {config.label}
                </span>
                <span className="text-xs text-gray-400">({items.length})</span>
              </div>
              <div className="space-y-2">
                {items.map((item) => (
                  <ChecklistItemRow
                    key={item.id}
                    item={item}
                    isChecked={checkedItems.has(item.id)}
                    onToggle={() => toggleItem(item.id)}
                  />
                ))}
              </div>
            </div>
          );
        })}

        {/* 기타 카테고리 (예상 외 카테고리가 있을 경우) */}
        {Object.keys(grouped)
          .filter((cat) => !CATEGORY_ORDER.includes(cat))
          .map((cat) => (
            <div key={cat} className="border-l-4 border-l-gray-300 pl-3">
              <div className="text-sm font-semibold text-gray-600 mb-2">{cat}</div>
              <div className="space-y-2">
                {grouped[cat].map((item) => (
                  <ChecklistItemRow
                    key={item.id}
                    item={item}
                    isChecked={checkedItems.has(item.id)}
                    onToggle={() => toggleItem(item.id)}
                  />
                ))}
              </div>
            </div>
          ))}
      </div>
    </div>
  );
};

interface ChecklistItemRowProps {
  item: ChecklistItem;
  isChecked: boolean;
  onToggle: () => void;
}

const ChecklistItemRow: React.FC<ChecklistItemRowProps> = ({
  item,
  isChecked,
  onToggle,
}) => {
  const sourceBadge = getSourceBadge(item);

  return (
    <label
      className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
        isChecked ? 'bg-green-50' : 'bg-gray-50 hover:bg-gray-100'
      }`}
    >
      <input
        type="checkbox"
        checked={isChecked}
        onChange={onToggle}
        className="mt-1 w-5 h-5 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
      />
      <div className="flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={`font-medium ${
              isChecked ? 'text-green-700 line-through' : 'text-gray-900'
            }`}
          >
            {item.item}
          </span>
          {item.is_mandatory && (
            <span className="text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded">
              필수
            </span>
          )}
        </div>
        {sourceBadge && (
          <span className={`inline-block text-xs px-1.5 py-0.5 rounded mt-1 ${sourceBadge.color}`}>
            {sourceBadge.label}
          </span>
        )}
        {item.description && (
          <p className="text-sm text-gray-500 mt-1">{item.description}</p>
        )}
      </div>
    </label>
  );
};

export default ChecklistView;
