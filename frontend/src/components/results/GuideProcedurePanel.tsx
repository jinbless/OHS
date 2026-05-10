import React from 'react';
import type { StandardProcedure } from '../../types/analysis';

const GuideProcedurePanel: React.FC<{ procedures: StandardProcedure[] }> = ({ procedures }) => (
  <section className="bg-white rounded-xl border border-green-200 p-4">
    <div className="mb-3">
      <h2 className="text-lg font-bold text-gray-900">표준 개선 절차</h2>
      <p className="text-sm text-gray-500">
        KOSHA Guide와 작업 프로세스를 기준으로 정리한 개선 흐름입니다.
      </p>
    </div>
    {procedures.length ? (
      <div className="space-y-2">
        {procedures.map((procedure, index) => (
          <div key={procedure.procedure_id} className="rounded-lg bg-green-50 px-3 py-2">
            <div className="text-sm font-medium text-gray-900">
              {index + 1}. {procedure.title}
            </div>
            {procedure.description && (
              <div className="text-xs text-gray-500 mt-1">{procedure.description}</div>
            )}
            {procedure.steps?.length ? (
              <ol className="mt-2 space-y-1 border-l border-green-200 pl-2">
                {procedure.steps.slice(0, 5).map((step) => (
                  <li key={step.step_id} className="py-1">
                    <div className="text-xs font-medium text-gray-800">
                      {step.order}. {step.title}
                    </div>
                    {step.safety_measures && (
                      <div className="mt-0.5 text-xs text-gray-500">{step.safety_measures}</div>
                    )}
                    {step.source_section && (
                      <div className="mt-0.5 text-[11px] text-green-700">섹션 {step.source_section}</div>
                    )}
                  </li>
                ))}
              </ol>
            ) : null}
            {typeof procedure.confidence === 'number' && (
              <div className="text-xs text-green-700 mt-1">
                관련도 {Math.round(procedure.confidence * 100)}%
              </div>
            )}
          </div>
        ))}
      </div>
    ) : (
      <p className="text-sm text-gray-400">연결된 표준 개선 절차가 없습니다.</p>
    )}
  </section>
);

export default GuideProcedurePanel;
