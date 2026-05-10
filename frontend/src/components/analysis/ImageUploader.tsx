import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';

interface ImageUploaderProps {
  onFileSelect: (file: File) => void;
  isLoading: boolean;
}

const ImageUploader: React.FC<ImageUploaderProps> = ({ onFileSelect, isLoading }) => {
  const [preview, setPreview] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [workplaceType, setWorkplaceType] = useState('');
  const [additionalContext, setAdditionalContext] = useState('');

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles[0]) {
      const file = acceptedFiles[0];
      setSelectedFile(file);
      setPreview(URL.createObjectURL(file));
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'image/*': ['.jpeg', '.jpg', '.png', '.webp'] },
    maxSize: 10 * 1024 * 1024,
    multiple: false,
    disabled: isLoading,
  });

  const handleAnalyze = () => {
    if (selectedFile) {
      onFileSelect(selectedFile);
    }
  };

  const clearFile = () => {
    setSelectedFile(null);
    setPreview(null);
  };

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={`dropzone ${isDragActive ? 'active' : ''} ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <input {...getInputProps()} />
        {preview ? (
          <div className="relative">
            <img
              src={preview}
              alt="미리보기"
              className="max-h-64 mx-auto rounded-lg"
            />
            {!isLoading && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  clearFile();
                }}
                className="absolute top-2 right-2 bg-white rounded-full p-1 shadow hover:bg-gray-100"
              >
                ✕
              </button>
            )}
          </div>
        ) : (
          <div className="py-8">
            <div className="text-4xl mb-4">📷</div>
            <p className="text-gray-600">
              {isDragActive
                ? '이미지를 놓으세요'
                : '작업현장 사진을 드래그하거나 클릭하여 업로드하세요'}
            </p>
            <p className="text-sm text-gray-400 mt-2">
              최대 10MB, JPG/PNG/WebP 지원
            </p>
          </div>
        )}
      </div>

      {selectedFile && (
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              작업장 유형 (선택)
            </label>
            <input
              type="text"
              value={workplaceType}
              onChange={(e) => setWorkplaceType(e.target.value)}
              placeholder="예: 건설현장, 제조공장, 창고"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              disabled={isLoading}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              추가 상황 설명 (선택)
            </label>
            <textarea
              value={additionalContext}
              onChange={(e) => setAdditionalContext(e.target.value)}
              placeholder="현장 상황에 대한 추가 정보를 입력하세요"
              rows={2}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              disabled={isLoading}
            />
          </div>
          <button
            onClick={handleAnalyze}
            disabled={isLoading}
            className="w-full btn btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? '분석 중...' : '위험요소 분석하기'}
          </button>
        </div>
      )}
    </div>
  );
};

export default ImageUploader;
