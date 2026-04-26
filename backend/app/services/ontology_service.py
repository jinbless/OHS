"""온톨로지 기반 매핑 서비스 — PostgreSQL koshaontology DB 직접 참조.

PG 테이블: norm_statements, guide_article_mapping, kosha_guides, checklist_items, safety_requirements
기존 OHS SQLite의 SemanticMapping/RegGuideMapping은 PG 테이블로 대체.
"""
import re
import json
import logging
from typing import List, Optional, Dict

from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func, distinct

from app.utils.text_utils import extract_article_number
from app.db.models import (
    PgNormStatement,
    PgKoshaGuide,
    PgGuideArticleMapping,
    PgSafetyRequirement,
    PgChecklistItem,
    PgCiSrMapping,
    PgSrArticleMapping,
    PgArticle,
)
from app.services.article_service import article_service
from app.utils.taxonomy import get_articles_for_category, get_article_range_for_classification

logger = logging.getLogger(__name__)


class OntologyService:
    """온톨로지 기반 매핑 관리 서비스 — PG 직접 참조"""

    # ===================================================================
    #  Phase 1: 규범명제 조회 (PG norm_statements — 이미 1,229개 적재)
    # ===================================================================

    async def extract_all_norms(self, db: Session) -> dict:
        """PG에 이미 norm_statements 1,229개 존재 → 카운트만 반환."""
        existing_count = db.query(PgNormStatement).count()
        return {
            "total": existing_count,
            "new": 0,
            "skipped": existing_count,
            "message": f"PG norm_statements: {existing_count}개 (이미 적재됨)"
        }

    # ===================================================================
    #  조회 메서드
    # ===================================================================

    def get_article_norms(self, db: Session, article_number: str) -> dict:
        """특정 법조항의 규범명제 + 연결 가이드 조회

        PG norm_statements 컬럼 매핑:
        - article_code (not article_number)
        - has_modality (not legal_effect)
        - has_subject_role (not subject_role)
        - has_action (not action)
        - has_object (not object)
        - text (not full_text)
        """
        norms = (
            db.query(PgNormStatement)
            .filter(PgNormStatement.article_code == article_number)
            .all()
        )

        # guide_article_mapping에서 연결된 가이드 조회
        guides = []
        mappings = (
            db.query(PgGuideArticleMapping, PgKoshaGuide)
            .join(PgKoshaGuide, PgGuideArticleMapping.guide_code == PgKoshaGuide.guide_code)
            .filter(PgGuideArticleMapping.article_code == article_number)
            .all()
        )
        for mapping, guide in mappings:
            guides.append({
                "guide_code": guide.guide_code,
                "title": guide.title,
                "classification": guide.domain,
                "relation_type": "IMPLEMENTS",
                "confidence": 0.90,
                "discovery_method": "pg_mapping",
            })

        # 법조항 제목
        article_info = article_service._find_article_by_number(article_number)
        article_title = article_info["title"] if article_info else None

        return {
            "article_number": article_number,
            "article_title": article_title,
            "total_norms": len(norms),
            "norms": [
                {
                    "id": n.identifier,
                    "article_number": n.article_code,
                    "paragraph": n.paragraph_ref,
                    "statement_order": 0,
                    "subject_role": n.has_subject_role,
                    "action": n.has_action,
                    "object": n.has_object,
                    "condition_text": json.dumps(n.has_condition, ensure_ascii=False) if n.has_condition else None,
                    "legal_effect": n.has_modality,
                    "effect_description": None,
                    "full_text": n.text,
                    "norm_category": None,
                }
                for n in norms
            ],
            "linked_guides": guides,
        }

    async def get_mapping_stats(self, db: Session) -> dict:
        """전체 매핑 통계 (PG + optional SPARQL)"""
        total_articles = db.query(PgArticle).filter(PgArticle.deleted == False).count()
        total_guides = db.query(PgKoshaGuide).count()
        total_norms = db.query(PgNormStatement).count()
        total_sr = db.query(PgSafetyRequirement).count()
        total_ci = db.query(PgChecklistItem).count()
        ci_sr_mappings = db.query(PgCiSrMapping).count()
        guide_art_mappings = db.query(PgGuideArticleMapping).count()

        mapped_articles = db.query(distinct(PgGuideArticleMapping.article_code)).count()
        mapped_guides = db.query(distinct(PgGuideArticleMapping.guide_code)).count()

        result = {
            "total_articles": total_articles,
            "total_guides": total_guides,
            "total_norms": total_norms,
            "total_sr": total_sr,
            "total_ci": total_ci,
            "explicit_mapped_articles": mapped_articles,
            "semantic_mapped_articles": 0,
            "all_mapped_articles": mapped_articles,
            "all_mapped_guides": mapped_guides,
            "total_explicit_mappings": guide_art_mappings,
            "total_semantic_mappings": ci_sr_mappings,
            "relation_distribution": {},
            "method_distribution": {"pg_mapping": guide_art_mappings},
        }

        # SPARQL stats (optional — graceful fallback)
        try:
            from app.integrations.sparql_client import sparql_client
            from app.integrations import sparql_queries as sq
            if sparql_client.is_available():
                triple_rows = await sparql_client.query(sq.q_triple_count(), cache_ttl=600)
                if triple_rows:
                    result["sparql_triple_count"] = int(triple_rows[0].get("cnt", 0))
                result["sparql_available"] = True
            else:
                result["sparql_available"] = False
        except Exception:
            result["sparql_available"] = False

        return result

    # ===================================================================
    #  법조항 매칭 (벡터 + 카테고리)
    # ===================================================================

    def _extract_article_num(self, article_str: str) -> Optional[int]:
        m = re.search(r"제?(\d+)조?", article_str)
        return int(m.group(1)) if m else None

    def find_related_articles_for_hazards(
        self,
        db: Session,
        hazard_descriptions: List[str],
        hazard_categories: List[str],
    ) -> List[dict]:
        """위험 설명 + 카테고리로 관련 법조항 검색

        1) 벡터 검색 (ChromaDB)
        2) 카테고리 기반 범위 필터
        3) PG norm_statements 조회
        """
        vector_articles = []
        category_articles = set()

        # 1) 벡터 검색
        if article_service.collection.count() > 0:
            try:
                from openai import OpenAI
                openai_sync = OpenAI(api_key=article_service._openai.api_key)
                combined_desc = " ".join(hazard_descriptions)[:500]
                response = openai_sync.embeddings.create(
                    model="text-embedding-3-small",
                    input=[combined_desc],
                )
                query_embedding = response.data[0].embedding
                chroma_results = article_service.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=10,
                    include=["metadatas", "distances"],
                )
                if chroma_results and chroma_results["metadatas"] and chroma_results["metadatas"][0]:
                    for i, meta in enumerate(chroma_results["metadatas"][0]):
                        distance = chroma_results["distances"][0][i]
                        if (1 - distance) >= 0.55:
                            art_num = meta.get("article_number", "")
                            if art_num and art_num not in vector_articles:
                                vector_articles.append(art_num)
            except Exception as e:
                logger.warning(f"벡터 검색 실패: {e}")

        # 2) 카테고리 기반 범위 필터
        cat_ranges = []
        for cat in set(hazard_categories):
            cat_ranges.extend(get_articles_for_category(cat))

        if cat_ranges:
            all_norm_articles = set(
                row[0] for row in
                db.query(PgNormStatement.article_code).distinct().all()
            )
            for art_num_str in all_norm_articles:
                art_num = self._extract_article_num(art_num_str)
                if art_num:
                    for r_start, r_end in cat_ranges:
                        if r_start <= art_num <= r_end:
                            category_articles.add(art_num_str)
                            break

        # 합산
        ordered_articles = list(vector_articles)
        for art in sorted(category_articles):
            if art not in ordered_articles:
                ordered_articles.append(art)

        # 3) 각 법조항의 규범명제 + 연결 가이드 조회
        result = []
        for article_code in ordered_articles[:10]:
            norms = (
                db.query(PgNormStatement)
                .filter(PgNormStatement.article_code == article_code)
                .limit(5)
                .all()
            )
            if not norms:
                continue

            # guide_article_mapping에서 연결 가이드
            guides = []
            gam_list = (
                db.query(PgGuideArticleMapping, PgKoshaGuide)
                .join(PgKoshaGuide, PgGuideArticleMapping.guide_code == PgKoshaGuide.guide_code)
                .filter(PgGuideArticleMapping.article_code == article_code)
                .limit(5)
                .all()
            )
            for gam, guide in gam_list:
                guides.append({
                    "guide_code": guide.guide_code,
                    "title": guide.title,
                    "relation_type": "IMPLEMENTS",
                    "confidence": 0.90,
                })

            article_info = article_service._find_article_by_number(article_code)
            result.append({
                "article_number": article_code,
                "article_title": article_info["title"] if article_info else None,
                "norms": [
                    {
                        "article_number": n.article_code,
                        "legal_effect": n.has_modality,
                        "action": n.has_action,
                        "full_text": n.text,
                    }
                    for n in norms
                ],
                "linked_guides": guides,
            })

        return result

    def get_semantic_boost_for_guides(
        self, db: Session, guide_codes: List[str]
    ) -> Dict[str, float]:
        """가이드 코드별 매핑 부스트 점수.

        PG guide_article_mapping 존재 여부로 부스트 결정.
        """
        if not guide_codes:
            return {}

        boost_result = {}
        for code in guide_codes:
            mapping_count = (
                db.query(PgGuideArticleMapping)
                .filter(PgGuideArticleMapping.guide_code == code)
                .count()
            )
            if mapping_count > 0:
                boost_result[code] = min(0.20, mapping_count * 0.05)

        return boost_result

    # ===================================================================
    #  Gap Analysis (간소화)
    # ===================================================================

    def get_gap_analysis(self, db: Session) -> dict:
        """PG 데이터 기반 gap 분석"""
        total_articles = db.query(PgArticle).filter(PgArticle.deleted == False).count()
        mapped_articles = db.query(distinct(PgGuideArticleMapping.article_code)).count()

        return {
            "total_articles": total_articles,
            "mapped_articles": mapped_articles,
            "unmapped_count": total_articles - mapped_articles,
            "coverage_pct": round(mapped_articles * 100 / total_articles, 1) if total_articles else 0,
            "unmapped_articles": [],
        }

    # ===================================================================
    #  그래프 (간소화)
    # ===================================================================

    def get_article_graph(self, db: Session, article_number: str) -> dict:
        norms_data = self.get_article_norms(db, article_number)
        nodes = [{"id": article_number, "type": "article", "label": article_number}]
        edges = []

        for n in norms_data.get("norms", []):
            nid = n["id"]
            nodes.append({"id": nid, "type": "norm", "label": n.get("action", "")[:30]})
            edges.append({"from": article_number, "to": nid, "relation": "hasNorm"})

        for g in norms_data.get("linked_guides", []):
            gc = g["guide_code"]
            nodes.append({"id": gc, "type": "guide", "label": g.get("title", "")[:30]})
            edges.append({"from": article_number, "to": gc, "relation": "linkedGuide"})

        return {"nodes": nodes, "edges": edges}

    async def get_full_graph(self, db: Session, limit: int = 50, include_inferred: bool = False) -> dict:
        """PG articles + norm_statements + kosha_guides 에서 그래프 생성.

        RULE 조문 중 norm이 많은 순으로 limit개 article 선택 →
        각 article의 norm + linked guide를 노드/엣지로 반환.
        include_inferred=True 시 Fuseki 추론 엣지(coApplicable, exemptedBy, propertyChain) 오버레이.
        """
        # 1) norm 수가 많은 RULE 조문 상위 limit개
        top_articles = (
            db.query(
                PgNormStatement.article_code,
                sa_func.count(PgNormStatement.identifier).label("cnt"),
            )
            .filter(PgNormStatement.law_id == "RULE")
            .group_by(PgNormStatement.article_code)
            .order_by(sa_func.count(PgNormStatement.identifier).desc())
            .limit(limit)
            .all()
        )

        nodes = []
        edges = []
        seen_nodes = set()

        for art_code, norm_cnt in top_articles:
            # article 노드
            art_id = f"art_{art_code}"
            if art_id not in seen_nodes:
                nodes.append({
                    "id": art_id,
                    "label": art_code,
                    "group": "article",
                    "size": min(5 + norm_cnt, 20),
                })
                seen_nodes.add(art_id)

            # norms for this article
            norms = (
                db.query(PgNormStatement)
                .filter(
                    PgNormStatement.article_code == art_code,
                    PgNormStatement.law_id == "RULE",
                )
                .limit(5)  # 조문당 최대 5개 norm
                .all()
            )
            for ns in norms:
                ns_id = f"ns_{ns.identifier}"
                if ns_id not in seen_nodes:
                    action_label = (ns.has_action or "")[:25]
                    nodes.append({
                        "id": ns_id,
                        "label": action_label or ns.identifier,
                        "group": "norm",
                        "modality": ns.has_modality,
                    })
                    seen_nodes.add(ns_id)
                edges.append({"from": art_id, "to": ns_id, "relation": "hasNorm"})

            # linked guides via guide_article_mapping
            guides = (
                db.query(PgGuideArticleMapping, PgKoshaGuide)
                .join(PgKoshaGuide, PgGuideArticleMapping.guide_code == PgKoshaGuide.guide_code)
                .filter(PgGuideArticleMapping.article_code == art_code)
                .limit(3)
                .all()
            )
            for gam, guide in guides:
                g_id = f"guide_{gam.guide_code}"
                if g_id not in seen_nodes:
                    nodes.append({
                        "id": g_id,
                        "label": (guide.title or gam.guide_code)[:25],
                        "group": "guide",
                    })
                    seen_nodes.add(g_id)
                edges.append({"from": art_id, "to": g_id, "relation": "linkedGuide"})

        # SPARQL inferred edges overlay
        if include_inferred:
            try:
                from app.integrations.sparql_client import sparql_client
                from app.integrations import sparql_queries as sq
                if sparql_client.is_available():
                    # Get article codes present in graph
                    art_codes = [code for code, _ in top_articles]
                    for art_code in art_codes[:10]:
                        rows = await sparql_client.query(
                            sq.q7_article_inferred_graph(art_code, limit=30),
                            cache_ttl=300,
                        )
                        for row in rows:
                            # coApplicable edges
                            co_sr_id = row.get("coSrId")
                            sr_id = row.get("srId")
                            if co_sr_id and sr_id and co_sr_id != sr_id:
                                co_node_id = f"sr_{co_sr_id}"
                                sr_node_id = f"sr_{sr_id}"
                                if co_node_id not in seen_nodes:
                                    nodes.append({
                                        "id": co_node_id,
                                        "label": co_sr_id,
                                        "group": "inferred_sr",
                                    })
                                    seen_nodes.add(co_node_id)
                                if sr_node_id not in seen_nodes:
                                    nodes.append({
                                        "id": sr_node_id,
                                        "label": sr_id,
                                        "group": "inferred_sr",
                                    })
                                    seen_nodes.add(sr_node_id)
                                edges.append({
                                    "from": sr_node_id,
                                    "to": co_node_id,
                                    "relation": "coApplicable",
                                    "edge_type": "coApplicable",
                                })

                            # Exemption edges
                            exempt_ns_id = row.get("exemptNsId")
                            ns_id = row.get("nsId")
                            if exempt_ns_id and ns_id:
                                ex_node_id = f"exempt_{exempt_ns_id}"
                                ns_node_id = f"ns_{ns_id}"
                                if ex_node_id not in seen_nodes:
                                    nodes.append({
                                        "id": ex_node_id,
                                        "label": exempt_ns_id,
                                        "group": "exemption",
                                    })
                                    seen_nodes.add(ex_node_id)
                                edges.append({
                                    "from": ex_node_id,
                                    "to": ns_node_id,
                                    "relation": "exemptedBy",
                                    "edge_type": "exemptedBy",
                                })
            except Exception as e:
                logger.warning(f"SPARQL inferred graph failed: {e}")

        return {"nodes": nodes, "edges": edges}

    # ===================================================================
    #  매핑 관리 (PG 데이터 → 읽기 전용)
    # ===================================================================

    async def classify_all_mappings(self, db: Session) -> dict:
        return {"total": 0, "classified": 0, "message": "PG mappings are pre-classified"}

    async def discover_unmapped_guides(self, db: Session) -> dict:
        return {"discovered": 0, "message": "Discovery not needed — PG data is complete"}

    def get_semantic_mappings(
        self, db: Session,
        relation_type: str = None,
        discovery_method: str = None,
        min_confidence: float = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict:
        """guide_article_mapping을 SemanticMapping 형식으로 반환"""
        query = db.query(PgGuideArticleMapping, PgKoshaGuide).join(
            PgKoshaGuide, PgGuideArticleMapping.guide_code == PgKoshaGuide.guide_code
        )
        total = query.count()
        rows = query.offset(skip).limit(limit).all()

        mappings = []
        for gam, guide in rows:
            mappings.append({
                "id": f"{gam.guide_code}:{gam.article_code}",
                "source_type": "article",
                "source_id": gam.article_code,
                "target_type": "guide",
                "target_id": gam.guide_code,
                "target_title": guide.title,
                "relation_type": "IMPLEMENTS",
                "confidence": 0.90,
                "discovery_method": "pg_mapping",
            })

        return {"total": total, "mappings": mappings}


ontology_service = OntologyService()
