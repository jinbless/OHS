import React from 'react';
import type { ReasoningTrace } from '../../types/analysis';

interface ReasoningTracePanelProps {
  trace: ReasoningTrace;
  matches: number;
}

const ReasoningTracePanel: React.FC<ReasoningTracePanelProps> = ({ trace, matches }) => (
  <details className="bg-white rounded-xl border p-4">
    <summary className="cursor-pointer text-sm font-semibold text-gray-800">
      근거 보기: SHE → SR → 법령 → Guide/CI → PenaltyPath
    </summary>
    <div className="mt-4 grid grid-cols-1 md:grid-cols-5 gap-2 text-xs">
      <TraceBox title="관찰/특징" lines={[...trace.observations, ...trace.risk_features].slice(0, 8)} />
      <TraceBox title={`SHE (${matches})`} lines={trace.situation_patterns.slice(0, 8)} />
      <TraceBox title="SR/법령" lines={[...trace.safety_requirements, ...trace.articles].slice(0, 8)} />
      <TraceBox title="Guide/CI" lines={[...trace.guides, ...trace.checklist_items].slice(0, 8)} />
      <TraceBox title="PenaltyRule" lines={trace.penalty_rules.slice(0, 8)} />
    </div>
  </details>
);

const TraceBox: React.FC<{ title: string; lines: string[] }> = ({ title, lines }) => (
  <div className="rounded-lg border bg-gray-50 p-3 min-w-0">
    <div className="font-semibold text-gray-700 mb-2">{title}</div>
    <div className="space-y-1">
      {lines.length ? (
        lines.map((line, index) => (
          <div key={`${line}-${index}`} className="font-mono text-[11px] text-gray-500 break-words">
            {line}
          </div>
        ))
      ) : (
        <div className="text-[11px] text-gray-400">없음</div>
      )}
    </div>
  </div>
);

export default ReasoningTracePanel;
