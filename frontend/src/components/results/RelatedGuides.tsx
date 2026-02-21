import React, { useState } from 'react';

interface GuideSectionInfo {
  section_title: string;
  excerpt: string;
  section_type?: string;
}

interface GuideMatch {
  guide_code: string;
  title: string;
  classification: string;
  relevant_sections: GuideSectionInfo[];
  relevance_score: number;
  mapping_type: string;
}

interface RelatedGuidesProps {
  guides: GuideMatch[];
}

const CLASSIFICATION_LABELS: Record<string, string> = {
  'G': '일반안전',
  'C': '건설안전',
  'D': '건설안전(설계)',
  'E': '전기안전',
  'M': '기계안전',
  'P': '공정안전',
  'H': '보건',
  'B': '보건(일반)',
  'A': '작업환경측정',
  'W': '작업환경',
  'T': '교육훈련',
  'X': '기타',
  'O': '산업보건',
  'F': '화재폭발',
  'K': 'KOSHA',
};

const CLASSIFICATION_COLORS: Record<string, string> = {
  'G': 'bg-green-100 text-green-700',
  'C': 'bg-orange-100 text-orange-700',
  'E': 'bg-yellow-100 text-yellow-700',
  'M': 'bg-blue-100 text-blue-700',
  'P': 'bg-red-100 text-red-700',
  'H': 'bg-purple-100 text-purple-700',
  'B': 'bg-purple-100 text-purple-700',
  'A': 'bg-indigo-100 text-indigo-700',
};

const RelatedGuides: React.FC<RelatedGuidesProps> = ({ guides }) => {
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  if (!guides || guides.length === 0) {
    return null;
  }

  const getClassLabel = (code: string) => CLASSIFICATION_LABELS[code] || code;
  const getClassColor = (code: string) => CLASSIFICATION_COLORS[code] || 'bg-gray-100 text-gray-700';

  return (
    <div className="card">
      <h2 className="text-xl font-bold text-gray-900 mb-4">관련 KOSHA GUIDE</h2>
      <p className="text-sm text-gray-500 mb-4">
        산안법 조문과 매핑된 안전보건공단 기술지침입니다. 현장 실무에 직접 활용할 수 있습니다.
      </p>
      <div className="space-y-3">
        {guides.map((guide) => {
          const isExpanded = expandedCode === guide.guide_code;
          return (
            <div
              key={guide.guide_code}
              className="border border-gray-200 rounded-lg overflow-hidden hover:border-green-300 transition-colors"
            >
              <div
                className="p-4 cursor-pointer"
                onClick={() => setExpandedCode(isExpanded ? null : guide.guide_code)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="font-bold text-green-700 whitespace-nowrap text-sm">
                        {guide.guide_code}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${getClassColor(guide.classification)}`}>
                        {getClassLabel(guide.classification)}
                      </span>
                      {guide.mapping_type === 'explicit' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                          법규 직접 연결
                        </span>
                      )}
                    </div>
                    <h3 className="font-medium text-gray-900 text-sm">
                      {guide.title}
                    </h3>
                  </div>
                  <span className="text-gray-400 text-sm flex-shrink-0">
                    {isExpanded ? '▲' : '▼'}
                  </span>
                </div>
              </div>

              {isExpanded && guide.relevant_sections.length > 0 && (
                <div className="px-4 pb-4 border-t border-gray-100">
                  <div className="mt-3 space-y-2">
                    {guide.relevant_sections.map((section, idx) => (
                      <div key={idx} className="p-3 bg-gray-50 rounded">
                        <div className="text-xs font-medium text-gray-500 mb-1">
                          {section.section_title}
                        </div>
                        {section.excerpt && (
                          <div className="text-sm text-gray-700 leading-relaxed">
                            {section.excerpt}...
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 text-xs text-gray-400">
                    관련도: {Math.round(guide.relevance_score * 100)}%
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default RelatedGuides;
