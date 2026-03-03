from pydantic import BaseModel
from typing import List, Optional


class ChecklistItem(BaseModel):
    id: str
    category: str  # "즉시 조치" | "법적 의무" | "금지 사항"
    item: str
    description: Optional[str] = None
    priority: int
    is_mandatory: bool
    source_type: Optional[str] = None  # "gpt" | "norm_obligation" | "norm_prohibition"
    source_ref: Optional[str] = None   # "제42조" 등 조항번호


class Checklist(BaseModel):
    title: str
    workplace_type: Optional[str] = None
    items: List[ChecklistItem]
