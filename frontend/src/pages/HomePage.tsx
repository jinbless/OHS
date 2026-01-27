import React from 'react';
import { Link } from 'react-router-dom';

const HomePage: React.FC = () => {
  return (
    <div className="max-w-4xl mx-auto">
      <div className="text-center mb-8 md:mb-12">
        <h1 className="text-2xl md:text-4xl font-bold text-gray-900 mb-3 md:mb-4">
          🛡️ 산업안전 위험요소 분석
        </h1>
        <p className="text-base md:text-xl text-gray-600 px-2">
          AI가 작업현장의 위험요소를 분석하고 안전한 작업을 위한 가이드를 제공합니다
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6 mb-8 md:mb-12">
        <div className="card hover:shadow-lg transition-shadow">
          <div className="text-3xl md:text-4xl mb-3 md:mb-4">📷</div>
          <h2 className="text-lg md:text-xl font-bold text-gray-900 mb-2">이미지 분석</h2>
          <p className="text-sm md:text-base text-gray-600 mb-3 md:mb-4">
            작업현장 사진을 업로드하면 AI가 이미지에서 위험요소를 식별합니다
          </p>
          <ul className="text-xs md:text-sm text-gray-500 space-y-1 mb-4">
            <li>• 시각적 위험요소 자동 인식</li>
            <li>• 위치 기반 위험 분석</li>
            <li>• 현장 상황 종합 평가</li>
          </ul>
          <Link
            to="/analysis?type=image"
            className="btn btn-primary inline-block w-full md:w-auto text-center"
          >
            이미지 분석 시작
          </Link>
        </div>

        <div className="card hover:shadow-lg transition-shadow">
          <div className="text-3xl md:text-4xl mb-3 md:mb-4">📝</div>
          <h2 className="text-lg md:text-xl font-bold text-gray-900 mb-2">텍스트 분석</h2>
          <p className="text-sm md:text-base text-gray-600 mb-3 md:mb-4">
            작업 상황을 텍스트로 설명하면 AI가 잠재적 위험요소를 분석합니다
          </p>
          <ul className="text-xs md:text-sm text-gray-500 space-y-1 mb-4">
            <li>• 작업 내용 기반 위험 평가</li>
            <li>• 상황별 맞춤 분석</li>
            <li>• 사전 위험성 검토</li>
          </ul>
          <Link
            to="/analysis?type=text"
            className="btn btn-primary inline-block w-full md:w-auto text-center"
          >
            텍스트 분석 시작
          </Link>
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 md:p-6">
        <h3 className="font-bold text-blue-900 mb-3 text-sm md:text-base">
          분석 결과에 포함되는 내용
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="flex items-start gap-3">
            <span className="text-xl md:text-2xl">⚠️</span>
            <div>
              <h4 className="font-medium text-gray-900 text-sm md:text-base">위험요소 목록</h4>
              <p className="text-xs md:text-sm text-gray-600">식별된 위험요소와 위험 수준</p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <span className="text-xl md:text-2xl">✅</span>
            <div>
              <h4 className="font-medium text-gray-900 text-sm md:text-base">점검 체크리스트</h4>
              <p className="text-xs md:text-sm text-gray-600">작업 전 확인해야 할 항목</p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <span className="text-xl md:text-2xl">📚</span>
            <div>
              <h4 className="font-medium text-gray-900 text-sm md:text-base">교육 자료</h4>
              <p className="text-xs md:text-sm text-gray-600">관련 리플릿 및 동영상 링크</p>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-6 md:mt-8 text-center">
        <Link to="/history" className="text-blue-600 hover:text-blue-800 text-sm md:text-base">
          이전 분석 기록 보기 →
        </Link>
      </div>
    </div>
  );
};

export default HomePage;
