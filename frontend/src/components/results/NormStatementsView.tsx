import React from 'react';

interface NormSummary {
  article_number: string;
  legal_effect: string;
  action: string | null;
  full_text: string;
}

interface LinkedGuideSummary {
  guide_code: string;
  title: string;
  relation_type: string;
  confidence: number;
}

interface NormContext {
  article_number: string;
  article_title: string | null;
  norms: NormSummary[];
  linked_guides: LinkedGuideSummary[];
}

interface NormStatementsViewProps {
  norms: NormContext[];
}

const EFFECT_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  OBLIGATION: { bg: 'bg-blue-100', text: 'text-blue-700', label: '의무' },
  PROHIBITION: { bg: 'bg-red-100', text: 'text-red-700', label: '금지' },
  PERMISSION: { bg: 'bg-green-100', text: 'text-green-700', label: '허용' },
  EXCEPTION: { bg: 'bg-yellow-100', text: 'text-yellow-700', label: '예외' },
};

const RELATION_LABEL: Record<string, string> = {
  IMPLEMENTS: '이행',
  SPECIFIES_CRITERIA: '기준',
  SPECIFIES_METHOD: '방법',
  SUPPLEMENTS: '보충',
  CROSS_REFERENCES: '참조',
};

const NormStatementsView: React.FC<NormStatementsViewProps> = ({ norms }) => {
  if (!norms || norms.length === 0) {
    return (
      <div className="text-center py-12 text-gray-400">
        관련 법적 근거가 없습니다.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="text-sm text-gray-500 mb-2">
        위험요소와 관련된 산업안전보건규칙 법조항 및 규범명제입니다.
      </div>

      {norms.map((nc, idx) => (
        <div key={idx} className="bg-white rounded-xl border shadow-sm overflow-hidden">
          {/* 법조항 헤더 */}
          <div className="bg-blue-50 px-4 py-3 border-b">
            <div className="font-semibold text-blue-800">
              {nc.article_number}
              {nc.article_title && (
                <span className="font-normal text-blue-600 ml-2">
                  ({nc.article_title})
                </span>
              )}
            </div>
          </div>

          {/* 규범명제 리스트 */}
          <div className="px-4 py-3 space-y-2">
            {nc.norms.map((norm, ni) => {
              const style = EFFECT_STYLE[norm.legal_effect] || EFFECT_STYLE.OBLIGATION;
              return (
                <div key={ni} className="flex gap-2 items-start">
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${style.bg} ${style.text} shrink-0 mt-0.5`}
                  >
                    {style.label}
                  </span>
                  <span className="text-sm text-gray-700 leading-relaxed">
                    {norm.full_text.length > 200
                      ? norm.full_text.slice(0, 200) + '...'
                      : norm.full_text}
                  </span>
                </div>
              );
            })}
          </div>

          {/* 연결 가이드 */}
          {nc.linked_guides.length > 0 && (
            <div className="px-4 py-3 border-t bg-gray-50">
              <div className="text-xs text-gray-500 mb-1.5 font-medium">연결 가이드</div>
              <div className="space-y-1">
                {nc.linked_guides.slice(0, 3).map((g, gi) => (
                  <div key={gi} className="flex items-center gap-2 text-xs">
                    <span className="text-orange-600 font-mono">{g.guide_code}</span>
                    <span className="text-gray-600 truncate">{g.title}</span>
                    <span className="ml-auto shrink-0 text-gray-400">
                      {RELATION_LABEL[g.relation_type] || g.relation_type}
                      {' '}
                      {Math.round(g.confidence * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default NormStatementsView;
