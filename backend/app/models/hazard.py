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
