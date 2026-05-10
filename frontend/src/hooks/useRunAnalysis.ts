import { useNavigate } from 'react-router-dom';
import { analysisApi } from '../api/analysisApi';
import { useAnalysisStore } from '../store';
import type { AnalysisResponse, TextAnalysisRequest } from '../types/analysis';

export const useRunAnalysis = () => {
  const navigate = useNavigate();
  const { isLoading, error, setLoading, setError, setCurrentAnalysis } = useAnalysisStore();

  const run = async (request: () => Promise<AnalysisResponse>) => {
    setLoading(true);
    setError(null);
    try {
      const result = await request();
      setCurrentAnalysis(result);
      navigate(`/result/${result.analysis_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '분석 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return {
    isLoading,
    error,
    clearError: () => setError(null),
    analyzeImage: (file: File) => run(() => analysisApi.analyzeImage(file)),
    analyzeText: (request: TextAnalysisRequest) => run(() => analysisApi.analyzeText(request)),
  };
};
