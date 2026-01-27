from pydantic import BaseModel
from typing import List, Optional


class ChecklistItem(BaseModel):
    id: str
    category: str
    item: str
    description: Optional[str] = None
    priority: int
    is_mandatory: bool


class Checklist(BaseModel):
    title: str
    workplace_type: Optional[str] = None
    items: List[ChecklistItem]
