import React, { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ImageUploader from '../components/analysis/ImageUploader';
import TextInput from '../components/analysis/TextInput';
import Loading from '../components/common/Loading';
import ErrorMessage from '../components/common/ErrorMessage';
import { useRunAnalysis } from '../hooks/useRunAnalysis';

type AnalysisType = 'image' | 'text';

const AnalysisPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialType = (searchParams.get('type') as AnalysisType) || 'image';

  const [analysisType, setAnalysisType] = useState<AnalysisType>(initialType);
  const { isLoading, error, clearError, analyzeImage, analyzeText } = useRunAnalysis();

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-xl md:text-2xl font-bold text-gray-900 mb-4 md:mb-6">
        위험요소 분석
      </h1>

      {/* 분석 유형 선택 */}
      <div className="flex gap-2 mb-4 md:mb-6">
        <button
          onClick={() => setAnalysisType('image')}
          className={`flex-1 py-3 px-3 md:px-4 rounded-lg font-medium transition-colors text-sm md:text-base ${
            analysisType === 'image'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
          disabled={isLoading}
        >
          📷 이미지 분석
        </button>
        <button
          onClick={() => setAnalysisType('text')}
          className={`flex-1 py-3 px-3 md:px-4 rounded-lg font-medium transition-colors text-sm md:text-base ${
            analysisType === 'text'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
          disabled={isLoading}
        >
          📝 텍스트 분석
        </button>
      </div>

      {/* 에러 메시지 */}
      {error && (
        <div className="mb-4 md:mb-6">
          <ErrorMessage message={error} onRetry={clearError} />
        </div>
      )}

      {/* 로딩 상태 */}
      {isLoading ? (
        <Loading message="AI가 위험요소를 분석하고 있습니다..." />
      ) : (
        <div className="card">
          {analysisType === 'image' ? (
            <ImageUploader onFileSelect={analyzeImage} isLoading={isLoading} />
          ) : (
            <TextInput onSubmit={analyzeText} isLoading={isLoading} />
          )}
        </div>
      )}

      {/* 안내 문구 */}
      <div className="mt-4 md:mt-6 p-3 md:p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <p className="text-xs md:text-sm text-blue-800">
          <span className="font-medium">💡 팁:</span>{' '}
          {analysisType === 'image'
            ? '선명하고 작업현장 전체가 보이는 사진을 업로드하면 더 정확한 분석이 가능합니다.'
            : '작업 내용, 사용 장비, 작업 환경 등을 상세히 설명하면 더 정확한 분석이 가능합니다.'}
        </p>
      </div>
    </div>
  );
};

export default AnalysisPage;
