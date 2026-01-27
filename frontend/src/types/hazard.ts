export type HazardCategory =
  | 'physical'
  | 'chemical'
  | 'biological'
  | 'ergonomic'
  | 'electrical'
  | 'environmental';

export type RiskLevel = 'critical' | 'high' | 'medium' | 'low';

export interface Hazard {
  id: string;
  category: HazardCategory;
  name: string;
  description: string;
  risk_level: RiskLevel;
  location?: string;
  potential_consequences: string[];
  preventive_measures: string[];
  legal_reference?: string;
}

export const categoryLabels: Record<HazardCategory, string> = {
  physical: '물리적 위험',
  chemical: '화학적 위험',
  biological: '생물학적 위험',
  ergonomic: '인간공학적 위험',
  electrical: '전기적 위험',
  environmental: '환경적 위험',
};

export const riskLevelLabels: Record<RiskLevel, string> = {
  critical: '즉시 조치 필요',
  high: '높음',
  medium: '중간',
  low: '낮음',
};

export const riskLevelColors: Record<RiskLevel, string> = {
  critical: 'risk-critical',
  high: 'risk-high',
  medium: 'risk-medium',
  low: 'risk-low',
};
