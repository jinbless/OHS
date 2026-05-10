import React from 'react';

interface LoadingProps {
  message?: string;
}

const Loading: React.FC<LoadingProps> = ({ message = '로딩 중...' }) => {
  return (
    <div className="flex flex-col items-center justify-center py-16 bg-white rounded-lg shadow-sm border border-gray-200">
      <div
        className="h-16 w-16 rounded-full border-4 border-gray-200"
        style={{
          borderTopColor: '#2563eb',
          animation: 'spin 1s linear infinite'
        }}
      />
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
      <p className="mt-6 text-gray-700 text-lg font-medium">{message}</p>
      <p className="mt-2 text-gray-500 text-sm">잠시만 기다려주세요</p>
    </div>
  );
};

export default Loading;
