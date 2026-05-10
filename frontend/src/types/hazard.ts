export type RiskLevel = 'critical' | 'high' | 'medium' | 'low';

export const riskLevelLabels: Record<RiskLevel, string> = {
  critical: '즉시 중지 필요',
  high: '높음',
  medium: '주의',
  low: '낮음',
};

export const riskLevelColors: Record<RiskLevel, string> = {
  critical: 'risk-critical',
  high: 'risk-high',
  medium: 'risk-medium',
  low: 'risk-low',
};
