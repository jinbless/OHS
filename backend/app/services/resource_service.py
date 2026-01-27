import json
from pathlib import Path
from typing import List
from app.models.resource import Resource, ResourceType


class ResourceService:
    def __init__(self):
        self.resources: List[Resource] = []
        self._load_resources()

    def _load_resources(self):
        """정적 리소스 데이터 로드"""
        data_path = Path(__file__).parent.parent / "data" / "resources.json"
        if data_path.exists():
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("resources", []):
                    self.resources.append(Resource(
                        id=item["id"],
                        type=ResourceType(item["type"]),
                        title=item["title"],
                        description=item["description"],
                        url=item["url"],
                        source=item["source"],
                        hazard_categories=item["hazard_categories"],
                        thumbnail_url=item.get("thumbnail_url")
                    ))

    def get_all_resources(self) -> List[Resource]:
        """모든 리소스 반환"""
        return self.resources

    def get_resources_by_categories(self, categories: List[str]) -> List[Resource]:
        """카테고리에 해당하는 리소스 반환"""
        if not categories:
            return []

        matched = []
        for resource in self.resources:
            for cat in categories:
                if any(cat in rc for rc in resource.hazard_categories):
                    if resource not in matched:
                        matched.append(resource)
                    break

        return matched[:5]  # 최대 5개 반환

    def get_resources_by_type(self, resource_type: ResourceType) -> List[Resource]:
        """타입별 리소스 반환"""
        return [r for r in self.resources if r.type == resource_type]


resource_service = ResourceService()
