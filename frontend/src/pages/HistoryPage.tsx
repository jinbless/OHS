import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { analysisApi } from '../api/analysisApi';
import { AnalysisHistoryItem } from '../types/analysis';
import RiskLevelBadge from '../components/common/RiskLevelBadge';
import Loading from '../components/common/Loading';
import ErrorMessage from '../components/common/ErrorMessage';
import { format } from 'date-fns';
import { ko } from 'date-fns/locale';

const HistoryPage: React.FC = () => {
  const [history, setHistory] = useState<AnalysisHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await analysisApi.getHistory();
      setHistory(response.items);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '분석 기록을 불러오는데 실패했습니다.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const handleDelete = async (analysisId: string) => {
    if (!confirm('이 분석 기록을 삭제하시겠습니까?')) return;

    try {
      await analysisApi.deleteAnalysis(analysisId);
      setHistory(history.filter((item) => item.analysis_id !== analysisId));
      setTotal(total - 1);
    } catch (err) {
      alert(err instanceof Error ? err.message : '삭제에 실패했습니다.');
    }
  };

  if (isLoading) {
    return <Loading message="분석 기록을 불러오는 중..." />;
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto">
        <ErrorMessage message={error} onRetry={fetchHistory} />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4 md:mb-6">
        <h1 className="text-xl md:text-2xl font-bold text-gray-900">분석 기록</h1>
        <p className="text-sm md:text-base text-gray-500">총 {total}건</p>
      </div>

      {history.length === 0 ? (
        <div className="text-center py-8 md:py-12 bg-gray-50 rounded-lg">
          <p className="text-gray-500 mb-4 text-sm md:text-base">분석 기록이 없습니다.</p>
          <Link to="/analysis" className="btn btn-primary inline-block">
            새로운 분석 시작하기
          </Link>
        </div>
      ) : (
        <div className="space-y-3 md:space-y-4">
          {history.map((item) => (
            <div key={item.analysis_id} className="card hover:shadow-md transition-shadow">
              {/* 모바일: 세로 레이아웃, 데스크톱: 가로 레이아웃 */}
              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                <div className="flex-1">
                  <div className="flex flex-wrap items-center gap-2 md:gap-3 mb-2">
                    <span className="text-base md:text-lg">
                      {item.analysis_type === 'image' ? '📷' : '📝'}
                    </span>
                    <RiskLevelBadge level={item.overall_risk_level} size="sm" />
                    <span className="text-xs md:text-sm text-gray-500">
                      {format(new Date(item.analyzed_at), 'yyyy.MM.dd HH:mm', { locale: ko })}
                    </span>
                  </div>
                  <p className="text-sm md:text-base text-gray-700 line-clamp-2">{item.summary}</p>
                  {item.input_preview && (
                    <p className="text-xs md:text-sm text-gray-400 mt-2 truncate">
                      입력: {item.input_preview}
                    </p>
                  )}
                </div>

                {/* 버튼 영역 */}
                <div className="flex items-center gap-2 pt-2 md:pt-0 md:ml-4 border-t md:border-t-0 border-gray-100">
                  <Link
                    to={`/result/${item.analysis_id}`}
                    className="btn btn-secondary text-xs md:text-sm flex-1 md:flex-none text-center"
                  >
                    상세보기
                  </Link>
                  <button
                    onClick={() => handleDelete(item.analysis_id)}
                    className="p-2 text-gray-400 hover:text-red-500 transition-colors"
                    title="삭제"
                  >
                    🗑️
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default HistoryPage;
