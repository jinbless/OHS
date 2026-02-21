from pydantic import BaseModel
from typing import List, Optional


class GuideSectionInfo(BaseModel):
    section_title: str
    excerpt: str
    section_type: Optional[str] = None


class GuideMatch(BaseModel):
    guide_code: str
    title: str
    classification: str
    relevant_sections: List[GuideSectionInfo] = []
    relevance_score: float
    mapping_type: str  # "explicit" / "auto"


class GuideIndexResponse(BaseModel):
    total_parsed: int
    total_sections: int
    total_mappings: int
    message: str
