from pydantic import BaseModel
from typing import List, Optional
from enum import Enum


class ResourceType(str, Enum):
    LEAFLET = "leaflet"
    VIDEO = "video"
    DOCUMENT = "document"
    WEBSITE = "website"


class Resource(BaseModel):
    id: str
    type: ResourceType
    title: str
    description: str
    url: str
    source: str
    hazard_categories: List[str]
    thumbnail_url: Optional[str] = None
