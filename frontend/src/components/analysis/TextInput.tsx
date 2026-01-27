import React, { useState } from 'react';
import { TextAnalysisRequest } from '../../types/analysis';

interface TextInputProps {
  onSubmit: (request: TextAnalysisRequest) => void;
  isLoading: boolean;
}

const TextInput: React.FC<TextInputProps> = ({ onSubmit, isLoading }) => {
  const [description, setDescription] = useState('');
  const [workplaceType, setWorkplaceType] = useState('');
  const [industrySector, setIndustrySector] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (description.trim()) {
      onSubmit({
        description: description.trim(),
        workplace_type: workplaceType || undefined,
        industry_sector: industrySector || undefined,
      });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          작업 상황 설명 <span className="text-red-500">*</span>
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="작업 현장의 상황을 상세히 설명해주세요. 예: 5m 높이의 비계에서 외벽 도장 작업을 하고 있습니다. 작업자가 안전대를 착용하지 않았습니다."
          rows={5}
          required
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          disabled={isLoading}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            작업장 유형 (선택)
          </label>
          <select
            value={workplaceType}
            onChange={(e) => setWorkplaceType(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            disabled={isLoading}
          >
            <option value="">선택하세요</option>
            <option value="건설현장">건설현장</option>
            <option value="제조공장">제조공장</option>
            <option value="창고/물류센터">창고/물류센터</option>
            <option value="사무실">사무실</option>
            <option value="연구소">연구소</option>
            <option value="기타">기타</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            산업 분야 (선택)
          </label>
          <select
            value={industrySector}
            onChange={(e) => setIndustrySector(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            disabled={isLoading}
          >
            <option value="">선택하세요</option>
            <option value="건설업">건설업</option>
            <option value="제조업">제조업</option>
            <option value="운수/창고업">운수/창고업</option>
            <option value="전기/가스업">전기/가스업</option>
            <option value="화학/석유업">화학/석유업</option>
            <option value="서비스업">서비스업</option>
            <option value="기타">기타</option>
          </select>
        </div>
      </div>

      <button
        type="submit"
        disabled={!description.trim() || isLoading}
        className="w-full btn btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isLoading ? '분석 중...' : '위험요소 분석하기'}
      </button>
    </form>
  );
};

export default TextInput;
