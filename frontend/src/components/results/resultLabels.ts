export const noticeLabels: Record<string, string> = {
  photo_based: '사진 기반 안내',
  external_fact_required: '추가 사실 확인 필요',
  conditional: '조건부 안내',
};

export const findingStatusLabels: Record<string, string> = {
  confirmed: '확정 위험',
  suspected: '의심 위험',
  needs_clarification: '확인 필요',
  not_determined: '판단 불가',
};

export const situationStatusLabels: Record<string, string> = {
  confirmed: '확정',
  candidate: '확인 필요',
  review_candidate: '검토 필요',
  context_only: '맥락 참고',
  rejected_by_normal_cue: '정상 단서',
};

export const situationStatusColors: Record<string, string> = {
  confirmed: 'bg-red-50 text-red-700 border-red-100',
  candidate: 'bg-amber-50 text-amber-700 border-amber-100',
  review_candidate: 'bg-purple-50 text-purple-700 border-purple-100',
  context_only: 'bg-gray-50 text-gray-600 border-gray-100',
  rejected_by_normal_cue: 'bg-green-50 text-green-700 border-green-100',
};

export const severityColors: Record<string, string> = {
  HIGH: 'bg-red-100 text-red-700 border-red-200',
  MEDIUM: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  LOW: 'bg-green-100 text-green-700 border-green-200',
};
