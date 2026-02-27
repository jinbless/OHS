import { create } from 'zustand';
import { AnalysisResponse } from '../types/analysis';

interface AnalysisState {
  currentAnalysis: AnalysisResponse | null;
  isLoading: boolean;
  error: string | null;

  setCurrentAnalysis: (analysis: AnalysisResponse | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  currentAnalysis: null,
  isLoading: false,
  error: null,

  setCurrentAnalysis: (analysis) => set({ currentAnalysis: analysis, error: null }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}));
