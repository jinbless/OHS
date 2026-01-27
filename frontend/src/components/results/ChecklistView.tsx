import React, { useState } from 'react';
import { Checklist, ChecklistItem } from '../../types/checklist';

interface ChecklistViewProps {
  checklist: Checklist;
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

  const sortedItems = [...checklist.items].sort((a, b) => a.priority - b.priority);

  const progress = checklist.items.length > 0
    ? Math.round((checkedItems.size / checklist.items.length) * 100)
    : 0;

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

      <div className="space-y-3">
        {sortedItems.map((item) => (
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
        <div className="flex items-center gap-2">
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
        {item.description && (
          <p className="text-sm text-gray-500 mt-1">{item.description}</p>
        )}
      </div>
    </label>
  );
};

export default ChecklistView;
