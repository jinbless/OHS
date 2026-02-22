from pydantic import BaseModel
from enum import Enum
from typing import List, Optional


class HazardCategory(str, Enum):
    PHYSICAL = "physical"
    CHEMICAL = "chemical"
    BIOLOGICAL = "biological"
    ERGONOMIC = "ergonomic"
    ELECTRICAL = "electrical"
    ENVIRONMENTAL = "environmental"


class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class NormSummary(BaseModel):
    """위험요소에 연결된 규범명제 요약"""
    article_number: str
    legal_effect: str
    action: Optional[str] = None
    full_text: str


class Hazard(BaseModel):
    id: str
    category: HazardCategory
    name: str
    description: str
    risk_level: RiskLevel
    location: Optional[str] = None
    potential_consequences: List[str]
    preventive_measures: List[str]
    legal_reference: Optional[str] = None
    related_norms: List[NormSummary] = []
