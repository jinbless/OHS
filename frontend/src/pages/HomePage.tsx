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
          사진 속 관찰 사실을 위험상황 패턴과 연결해 즉시 조치와 표준 개선 절차를 안내합니다
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6 mb-8 md:mb-12">
        <div className="card hover:shadow-lg transition-shadow">
          <div className="text-3xl md:text-4xl mb-3 md:mb-4">📷</div>
          <h2 className="text-lg md:text-xl font-bold text-gray-900 mb-2">이미지 분석</h2>
          <p className="text-sm md:text-base text-gray-600 mb-3 md:mb-4">
            작업현장 사진을 업로드하면 보이는 사실과 시각 단서를 기준으로 위험상황을 분석합니다
          </p>
          <ul className="text-xs md:text-sm text-gray-500 space-y-1 mb-4">
            <li>• 관찰 사실과 시각 단서 추출</li>
            <li>• 위험 특징 정규화</li>
            <li>• SHE 패턴 기반 상황 매칭</li>
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
            작업 상황을 텍스트로 설명하면 사진 분석과 같은 판단 흐름으로 위험 후보를 정리합니다
          </p>
          <ul className="text-xs md:text-sm text-gray-500 space-y-1 mb-4">
            <li>• 작업 맥락과 위험 단서 정리</li>
            <li>• 관련 안전요구사항 후보 연결</li>
            <li>• 추가 확인이 필요한 내용 분리</li>
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
              <h4 className="font-medium text-gray-900 text-sm md:text-base">위험 요약</h4>
              <p className="text-xs md:text-sm text-gray-600">관찰 사실과 정규화된 위험 특징</p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <span className="text-xl md:text-2xl">✅</span>
            <div>
              <h4 className="font-medium text-gray-900 text-sm md:text-base">즉시 조치</h4>
              <p className="text-xs md:text-sm text-gray-600">먼저 줄여야 할 위험과 체크포인트</p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <span className="text-xl md:text-2xl">📚</span>
            <div>
              <h4 className="font-medium text-gray-900 text-sm md:text-base">표준 절차와 벌칙 안내</h4>
              <p className="text-xs md:text-sm text-gray-600">KOSHA Guide와 조건별 벌칙 경로</p>
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
