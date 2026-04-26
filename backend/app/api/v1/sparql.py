"""SPARQL API endpoints — Fuseki 추론 엔진 직접 접근."""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.integrations.sparql_client import sparql_client
from app.integrations import sparql_queries as sq

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sparql", tags=["SPARQL 추론"])


@router.get("/health")
async def sparql_health():
    """Fuseki 연결 상태 확인"""
    return await sparql_client.health_check()


@router.get("/sr/{sr_id}/co-applicable")
async def get_co_applicable_srs(sr_id: str):
    """특정 SR과 같은 조문 기반 관련 SR 목록 (SPARQL 추론)"""
    rows = await sparql_client.query(sq.q2_co_applicable_srs(sr_id), cache_ttl=300)
    return {
        "sr_id": sr_id,
        "co_applicable": [
            {
                "sr_id": r.get("coSrId"),
                "title": r.get("coSrTitle", ""),
                "article_code": r.get("artCode", ""),
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/sr/{sr_id}/exemptions")
async def get_sr_exemptions(sr_id: str):
    """특정 SR의 면제 관계 탐색 (SWRL R-1)"""
    rows = await sparql_client.query(sq.q4_exemption_chain(sr_id), cache_ttl=300)
    return {
        "sr_id": sr_id,
        "exemptions": [
            {
                "exempt_ns_id": r.get("exemptNsId"),
                "article_code": r.get("exemptArtCode"),
                "condition": r.get("condition"),
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/article/{article_code}/inferred-graph")
async def get_article_inferred_graph(article_code: str, limit: int = 100):
    """조문별 전체 추론 그래프 (coApplicable, 면제, 벌칙 체인)"""
    rows = await sparql_client.query(
        sq.q7_article_inferred_graph(article_code, limit=limit),
        cache_ttl=300,
    )

    nodes = {}
    edge_set = set()  # deduplicate edges from Cartesian product of OPTIONALs

    for row in rows:
        sr_id = row.get("srId")
        ns_id = row.get("nsId")
        co_sr_id = row.get("coSrId")
        exempt_ns_id = row.get("exemptNsId")

        if sr_id:
            nodes[f"sr_{sr_id}"] = {"id": f"sr_{sr_id}", "label": sr_id, "group": "sr"}
        if ns_id:
            nodes[f"ns_{ns_id}"] = {"id": f"ns_{ns_id}", "label": ns_id, "group": "norm"}
        if sr_id and ns_id:
            edge_set.add((f"sr_{sr_id}", f"ns_{ns_id}", "derivedFromNS"))

        if co_sr_id and sr_id and co_sr_id != sr_id:
            nodes[f"sr_{co_sr_id}"] = {"id": f"sr_{co_sr_id}", "label": co_sr_id, "group": "inferred_sr"}
            edge_set.add((f"sr_{sr_id}", f"sr_{co_sr_id}", "coApplicable"))

        if exempt_ns_id and ns_id:
            nodes[f"exempt_{exempt_ns_id}"] = {"id": f"exempt_{exempt_ns_id}", "label": exempt_ns_id, "group": "exemption"}
            edge_set.add((f"exempt_{exempt_ns_id}", f"ns_{ns_id}", "exemptedBy"))

    # Article node
    nodes[f"art_{article_code}"] = {"id": f"art_{article_code}", "label": article_code, "group": "article"}

    edges = [{"from": f, "to": t, "edge_type": et} for f, t, et in edge_set]

    return {
        "article_code": article_code,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


@router.get("/faceted-query")
async def faceted_sparql_query(
    accident_types: Optional[str] = Query(None, description="콤마 구분 AccidentType 코드"),
    hazardous_agents: Optional[str] = Query(None, description="콤마 구분 Agent 코드"),
    work_contexts: Optional[str] = Query(None, description="콤마 구분 WorkContext 코드"),
    limit: int = 50,
):
    """Faceted 3축 SPARQL 교차 쿼리"""
    at_list = [x.strip() for x in accident_types.split(",")] if accident_types else None
    ag_list = [x.strip() for x in hazardous_agents.split(",")] if hazardous_agents else None
    wc_list = [x.strip() for x in work_contexts.split(",")] if work_contexts else None

    rows = await sparql_client.query(
        sq.q6_faceted_cross_query(at_list, ag_list, wc_list, limit=limit),
        cache_ttl=300,
    )
    return {
        "query_params": {
            "accident_types": at_list,
            "hazardous_agents": ag_list,
            "work_contexts": wc_list,
        },
        "results": [
            {
                "sr_id": r.get("srId"),
                "title": r.get("srTitle", ""),
                "article_code": r.get("artCode", ""),
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/stats")
async def sparql_stats():
    """Fuseki 트리플/클래스 분포 통계"""
    triple_rows = await sparql_client.query(sq.q_triple_count(), cache_ttl=600)
    class_rows = await sparql_client.query(sq.q_class_distribution(), cache_ttl=600)

    triple_count = int(triple_rows[0].get("cnt", 0)) if triple_rows else 0
    class_dist = [
        {"type": r.get("type", ""), "count": int(r.get("cnt", 0))}
        for r in class_rows
    ]

    return {
        "triple_count": triple_count,
        "class_distribution": class_dist,
        "fuseki_available": sparql_client.is_available(),
    }


@router.get("/subject-roles")
async def get_subject_roles(role_type: str = "DutyHolder"):
    """SubjectRole 계층 추론 — DutyHolder 하위 타입별 NS 수"""
    rows = await sparql_client.query(sq.q3_subject_role_hierarchy(role_type), cache_ttl=600)
    return {
        "role_type": role_type,
        "roles": [
            {
                "name": r.get("roleName"),
                "type": r.get("roleType"),
                "norm_count": int(r.get("cnt", 0)),
            }
            for r in rows
        ],
    }


@router.get("/high-severity")
async def get_high_severity_srs(min_severity: int = 5):
    """고위험 벌칙 SR 목록 (severity >= threshold)"""
    rows = await sparql_client.query(sq.q5_high_severity_srs(min_severity), cache_ttl=600)
    return {
        "min_severity": min_severity,
        "results": [
            {
                "sr_id": r.get("srId"),
                "title": r.get("srTitle", ""),
                "penalty": r.get("penaltyDesc", ""),
                "severity": r.get("severity"),
            }
            for r in rows
        ],
        "count": len(rows),
    }
