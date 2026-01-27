from fastapi import APIRouter, Query
from typing import List, Optional

from app.models.resource import Resource, ResourceType
from app.services.resource_service import resource_service

router = APIRouter()


@router.get("", response_model=List[Resource])
async def get_resources(
    type: Optional[ResourceType] = Query(None, description="리소스 타입 필터"),
    category: Optional[str] = Query(None, description="위험요소 카테고리 필터")
):
    """
    리소스 목록 조회

    산업안전 관련 교육 자료(리플릿, 동영상, 문서)를 조회합니다.
    """
    if type:
        return resource_service.get_resources_by_type(type)

    if category:
        return resource_service.get_resources_by_categories([category])

    return resource_service.get_all_resources()
