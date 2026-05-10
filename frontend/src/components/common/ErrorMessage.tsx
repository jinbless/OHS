import React from 'react';

interface ErrorMessageProps {
  message: string;
  onRetry?: () => void;
}

const ErrorMessage: React.FC<ErrorMessageProps> = ({ message, onRetry }) => {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4">
      <div className="flex items-start gap-3">
        <span className="text-red-500 text-xl">⚠️</span>
        <div className="flex-1">
          <p className="text-red-800">{message}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-2 text-red-600 hover:text-red-800 underline text-sm"
            >
              다시 시도
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default ErrorMessage;
