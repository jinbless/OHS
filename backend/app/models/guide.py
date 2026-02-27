from pydantic import BaseModel
from typing import List, Optional


class GuideSectionInfo(BaseModel):
    section_title: str
    excerpt: str
    section_type: Optional[str] = None


class GuideArticleRef(BaseModel):
    """KOSHA GUIDE에 매핑된 법조항 참조"""
    article_number: str
    title: str
    content: str = ""
    source_file: str = ""


class GuideMatch(BaseModel):
    guide_code: str
    title: str
    classification: str
    relevant_sections: List[GuideSectionInfo] = []
    relevance_score: float
    mapping_type: str  # "explicit" / "auto" / "direct"
    mapped_articles: List[GuideArticleRef] = []  # 이 가이드에 매핑된 법조항


