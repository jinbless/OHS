import React, { useState } from 'react';
import { ArticleMatch } from '../../types/analysis';

interface RelatedArticlesProps {
  articles: ArticleMatch[];
}

const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace('/api/v1', '') || 'http://localhost:8000';

const RelatedArticles: React.FC<RelatedArticlesProps> = ({ articles }) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (!articles || articles.length === 0) {
    return (
      <div className="card">
        <h2 className="text-xl font-bold text-gray-900 mb-4">관련 법조항</h2>
        <p className="text-gray-500 text-center py-8">
          관련 법조항을 찾을 수 없습니다. 인덱싱이 완료되지 않았을 수 있습니다.
        </p>
      </div>
    );
  }

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'bg-red-100 text-red-700';
    if (score >= 0.6) return 'bg-orange-100 text-orange-700';
    return 'bg-blue-100 text-blue-700';
  };

  const getScoreLabel = (score: number) => {
    if (score >= 0.8) return '매우 관련';
    if (score >= 0.6) return '관련';
    return '참고';
  };

  const getPdfUrl = (sourceFile: string) => {
    return `${API_BASE}/articles-pdf/${encodeURIComponent(sourceFile)}`;
  };

  return (
    <div className="card">
      <h2 className="text-xl font-bold text-gray-900 mb-4">관련 법조항</h2>
      <p className="text-sm text-gray-500 mb-4">
        산업안전보건기준에 관한 규칙에서 위험요소와 관련된 조문을 자동으로 찾아 연결합니다.
      </p>
      <div className="space-y-3">
        {articles.map((article) => {
          const isExpanded = expandedId === article.article_number;
          return (
            <div
              key={article.article_number}
              className="border border-gray-200 rounded-lg overflow-hidden hover:border-primary-300 transition-colors"
            >
              <div
                className="p-4 cursor-pointer"
                onClick={() => setExpandedId(isExpanded ? null : article.article_number)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-bold text-primary-700 whitespace-nowrap">
                        {article.article_number}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${getScoreColor(article.relevance_score)}`}>
                        {getScoreLabel(article.relevance_score)} ({Math.round(article.relevance_score * 100)}%)
                      </span>
                    </div>
                    <h3 className="font-medium text-gray-900">
                      {article.title}
                    </h3>
                  </div>
                  <span className="text-gray-400 text-sm flex-shrink-0">
                    {isExpanded ? '▲' : '▼'}
                  </span>
                </div>
              </div>

              {isExpanded && (
                <div className="px-4 pb-4 border-t border-gray-100">
                  <div className="mt-3 p-3 bg-gray-50 rounded text-sm text-gray-700 whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto">
                    {article.content}
                  </div>
                  <div className="mt-3 flex items-center justify-between">
                    <span className="text-xs text-gray-400">
                      출처: {article.source_file}
                    </span>
                    <a
                      href={getPdfUrl(article.source_file)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-primary-600 hover:text-primary-800 font-medium"
                      onClick={(e) => e.stopPropagation()}
                    >
                      PDF 원문 보기 →
                    </a>
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

export default RelatedArticles;
