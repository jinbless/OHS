export interface ChecklistItem {
  id: string;
  category: string;
  item: string;
  description?: string;
  priority: number;
  is_mandatory: boolean;
}

export interface Checklist {
  title: string;
  workplace_type?: string;
  items: ChecklistItem[];
}
