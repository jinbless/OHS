import React, { useEffect, useRef } from 'react';

interface ArticleModalProps {
  article: {
    article_number: string;
    title: string;
    content: string;
    chapter?: string;
    part?: string;
  };
  isOpen: boolean;
  onClose: () => void;
}

const LAW_URL = 'https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=280187&ancYnChk=0#0000';

const ArticleModal: React.FC<ArticleModalProps> = ({ article, isOpen, onClose }) => {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  // 항 번호(①②③...) 기준으로 단락 분리
  const formatContent = (text: string) => {
    if (!text) return null;
    const parts = text.split(/(①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩)/);
    if (parts.length <= 1) {
      return <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{text}</p>;
    }
    const paragraphs: { marker: string; text: string }[] = [];
    let i = 0;
    if (parts[0].trim()) {
      paragraphs.push({ marker: '', text: parts[0].trim() });
    }
    i = parts[0].trim() ? 1 : 1;
    for (; i < parts.length; i += 2) {
      const marker = parts[i] || '';
      const body = (parts[i + 1] || '').trim();
      if (marker && body) {
        paragraphs.push({ marker, text: body });
      }
    }
    return (
      <div className="space-y-3">
        {paragraphs.map((p, idx) => (
          <div key={idx} className="flex gap-2">
            {p.marker && (
              <span className="text-blue-600 font-bold flex-shrink-0 mt-0.5">{p.marker}</span>
            )}
            <p className="text-sm text-gray-800 leading-relaxed">{p.text}</p>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={handleOverlayClick}
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col">
        {/* 헤더 */}
        <div className="flex items-start justify-between p-5 border-b border-gray-100">
          <div className="min-w-0">
            <h3 className="text-lg font-bold text-gray-900">
              {article.article_number}
            </h3>
            <p className="text-sm text-gray-600 mt-0.5">{article.title}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 p-1 -mr-1 -mt-1 flex-shrink-0"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 메타데이터 */}
        {(article.part || article.chapter) && (
          <div className="px-5 pt-3 flex flex-wrap gap-2">
            {article.part && (
              <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-600">
                {article.part}
              </span>
            )}
            {article.chapter && (
              <span className="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700">
                {article.chapter}
              </span>
            )}
          </div>
        )}

        {/* 본문 */}
        <div className="flex-1 overflow-y-auto p-5">
          {article.content ? (
            formatContent(article.content)
          ) : (
            <p className="text-sm text-gray-400 italic">조문 내용을 불러올 수 없습니다.</p>
          )}
        </div>

        {/* 하단 */}
        <div className="px-5 py-3 border-t border-gray-100 flex justify-between items-center">
          <a
            href={LAW_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-gray-500 hover:text-blue-600 flex items-center gap-1"
          >
            법령정보센터 원문
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>
          <button
            onClick={onClose}
            className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
};

export default ArticleModal;
