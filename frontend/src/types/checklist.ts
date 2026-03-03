export interface ChecklistItem {
  id: string;
  category: string;  // "즉시 조치" | "법적 의무" | "금지 사항"
  item: string;
  description?: string;
  priority: number;
  is_mandatory: boolean;
  source_type?: string;  // "gpt" | "norm_obligation" | "norm_prohibition"
  source_ref?: string;   // "제42조" 등 조항번호
}

export interface Checklist {
  title: string;
  workplace_type?: string;
  items: ChecklistItem[];
}
