import axios from 'axios';

const defaultApiBaseUrl = () => {
  if (typeof window !== 'undefined' && ['localhost', '127.0.0.1'].includes(window.location.hostname)) {
    return 'http://localhost:8001/api/v1';
  }
  return '/api/v1';
};

const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || defaultApiBaseUrl();

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 2분 (이미지 분석 시간 고려)
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    const errorMessage =
      detail ||
      (status === 503
        ? 'AI 분석 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.'
        : '서버 오류가 발생했습니다.');
    return Promise.reject(new Error(errorMessage));
  }
);
