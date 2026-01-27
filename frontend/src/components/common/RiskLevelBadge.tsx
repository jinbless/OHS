import React from 'react';
import { RiskLevel, riskLevelLabels, riskLevelColors } from '../../types/hazard';

interface RiskLevelBadgeProps {
  level: RiskLevel;
  size?: 'sm' | 'md' | 'lg';
}

const RiskLevelBadge: React.FC<RiskLevelBadgeProps> = ({ level, size = 'md' }) => {
  const sizeClasses = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-3 py-1 text-sm',
    lg: 'px-4 py-1.5 text-base',
  };

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium border ${riskLevelColors[level]} ${sizeClasses[size]}`}
    >
      {riskLevelLabels[level]}
    </span>
  );
};

export default RiskLevelBadge;
