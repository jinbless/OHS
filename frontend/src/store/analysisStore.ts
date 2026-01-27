import { create } from 'zustand';
import { AnalysisResponse, AnalysisHistoryItem } from '../types/analysis';

interface AnalysisState {
  currentAnalysis: AnalysisResponse | null;
  history: AnalysisHistoryItem[];
  totalHistory: number;
  isLoading: boolean;
  error: string | null;

  setCurrentAnalysis: (analysis: AnalysisResponse | null) => void;
  setHistory: (items: AnalysisHistoryItem[], total: number) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearAnalysis: () => void;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  currentAnalysis: null,
  history: [],
  totalHistory: 0,
  isLoading: false,
  error: null,

  setCurrentAnalysis: (analysis) => set({ currentAnalysis: analysis, error: null }),
  setHistory: (items, total) => set({ history: items, totalHistory: total }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  clearAnalysis: () => set({ currentAnalysis: null, error: null }),
}));
