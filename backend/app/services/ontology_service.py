import logging
from typing import Dict, List, Optional

from sqlalchemy import distinct, func as sa_func
from sqlalchemy.orm import Session

from app.db.models import (
    PgArticle,
    PgChecklistItem,
    PgCiSrMapping,
    PgGuideArticleMapping,
    PgKoshaGuide,
    PgNormStatement,
    PgSafetyRequirement,
)

logger = logging.getLogger(__name__)


class OntologyService:
    async def extract_all_norms(self, db: Session) -> dict:
        total = db.query(PgNormStatement).count()
        return {"total": total, "new": 0, "skipped": total, "message": "norm statements are materialized"}

    def get_article_norms(self, db: Session, article_number: str) -> dict:
        norms = (
            db.query(PgNormStatement)
            .filter(PgNormStatement.article_code == article_number)
            .all()
        )
        article = (
            db.query(PgArticle)
            .filter(PgArticle.article_code == article_number)
            .first()
        )
        guides = (
            db.query(PgGuideArticleMapping, PgKoshaGuide)
            .join(PgKoshaGuide, PgGuideArticleMapping.guide_code == PgKoshaGuide.guide_code)
            .filter(PgGuideArticleMapping.article_code == article_number)
            .limit(20)
            .all()
        )
        return {
            "article_number": article_number,
            "article_title": article.title if article else None,
            "total_norms": len(norms),
            "norms": [
                {
                    "id": norm.identifier,
                    "article_number": norm.article_code,
                    "paragraph": norm.paragraph_ref,
                    "subject_role": norm.has_subject_role,
                    "action": norm.has_action,
                    "object": norm.has_object,
                    "legal_effect": norm.has_modality,
                    "full_text": norm.text,
                }
                for norm in norms
            ],
            "linked_guides": [
                {
                    "guide_code": guide.guide_code,
                    "title": guide.title,
                    "classification": guide.domain,
                    "relation_type": "IMPLEMENTS",
                    "confidence": 0.9,
                }
                for _, guide in guides
            ],
        }

    async def get_mapping_stats(self, db: Session) -> dict:
        total_articles = db.query(PgArticle).filter(PgArticle.deleted == False).count()
        total_guides = db.query(PgKoshaGuide).count()
        total_norms = db.query(PgNormStatement).count()
        total_sr = db.query(PgSafetyRequirement).count()
        total_ci = db.query(PgChecklistItem).count()
        ci_sr_mappings = db.query(PgCiSrMapping).count()
        guide_article_mappings = db.query(PgGuideArticleMapping).count()
        mapped_articles = db.query(distinct(PgGuideArticleMapping.article_code)).count()
        mapped_guides = db.query(distinct(PgGuideArticleMapping.guide_code)).count()
        return {
            "total_articles": total_articles,
            "total_guides": total_guides,
            "total_norms": total_norms,
            "total_sr": total_sr,
            "total_ci": total_ci,
            "explicit_mapped_articles": mapped_articles,
            "semantic_mapped_articles": 0,
            "all_mapped_articles": mapped_articles,
            "all_mapped_guides": mapped_guides,
            "total_explicit_mappings": guide_article_mappings,
            "total_semantic_mappings": ci_sr_mappings,
            "relation_distribution": {},
            "method_distribution": {"materialized_pg": guide_article_mappings},
        }

    def find_related_articles_for_hazards(
        self,
        db: Session,
        hazard_descriptions: List[str],
        risk_feature_codes: Optional[List[str]] = None,
    ) -> List[dict]:
        text = " ".join(hazard_descriptions + (risk_feature_codes or [])).strip()
        if not text:
            return []
        query = (
            db.query(PgSafetyRequirement)
            .filter(
                (PgSafetyRequirement.text.ilike(f"%{text[:40]}%"))
                | (PgSafetyRequirement.title.ilike(f"%{text[:40]}%"))
            )
            .limit(10)
        )
        sr_ids = [row.identifier for row in query.all()]
        if not sr_ids:
            return []
        mappings = (
            db.query(PgSrArticleMapping, PgArticle)
            .join(
                PgArticle,
                (PgSrArticleMapping.law_type == PgArticle.law_type)
                & (PgSrArticleMapping.article_code == PgArticle.article_code),
            )
            .filter(PgSrArticleMapping.sr_id.in_(sr_ids))
            .limit(10)
            .all()
        )
        return [
            {
                "article_number": mapping.article_code,
                "article_title": article.title,
                "norms": [],
                "linked_guides": [],
            }
            for mapping, article in mappings
        ]

    def get_semantic_boost_for_guides(self, db: Session, guide_codes: List[str]) -> Dict[str, float]:
        if not guide_codes:
            return {}
        result: Dict[str, float] = {}
        for code in guide_codes:
            count = (
                db.query(PgGuideArticleMapping)
                .filter(PgGuideArticleMapping.guide_code == code)
                .count()
            )
            if count:
                result[code] = min(0.2, count * 0.05)
        return result

    def get_gap_analysis(self, db: Session) -> dict:
        total_articles = db.query(PgArticle).filter(PgArticle.deleted == False).count()
        mapped_articles = db.query(distinct(PgGuideArticleMapping.article_code)).count()
        return {
            "total_articles": total_articles,
            "mapped_articles": mapped_articles,
            "unmapped_count": total_articles - mapped_articles,
            "coverage_pct": round(mapped_articles * 100 / total_articles, 1) if total_articles else 0,
            "unmapped_articles": [],
        }

    def get_article_graph(self, db: Session, article_number: str) -> dict:
        data = self.get_article_norms(db, article_number)
        nodes = [{"id": article_number, "type": "article", "label": article_number}]
        edges = []
        for norm in data.get("norms", []):
            norm_id = norm["id"]
            nodes.append({"id": norm_id, "type": "norm", "label": (norm.get("action") or norm_id)[:30]})
            edges.append({"from": article_number, "to": norm_id, "relation": "hasNorm"})
        for guide in data.get("linked_guides", []):
            guide_code = guide["guide_code"]
            nodes.append({"id": guide_code, "type": "guide", "label": guide.get("title", guide_code)[:30]})
            edges.append({"from": article_number, "to": guide_code, "relation": "linkedGuide"})
        return {"nodes": nodes, "edges": edges}

    async def get_full_graph(self, db: Session, limit: int = 50, include_inferred: bool = False) -> dict:
        rows = (
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
        seen = set()
        for article_code, norm_count in rows:
            article_node = f"art_{article_code}"
            if article_node not in seen:
                nodes.append({"id": article_node, "label": article_code, "group": "article", "size": min(20, 5 + norm_count)})
                seen.add(article_node)
            norms = (
                db.query(PgNormStatement)
                .filter(PgNormStatement.article_code == article_code, PgNormStatement.law_id == "RULE")
                .limit(5)
                .all()
            )
            for norm in norms:
                norm_node = f"ns_{norm.identifier}"
                if norm_node not in seen:
                    nodes.append({"id": norm_node, "label": (norm.has_action or norm.identifier)[:25], "group": "norm"})
                    seen.add(norm_node)
                edges.append({"from": article_node, "to": norm_node, "relation": "hasNorm"})
        return {"nodes": nodes, "edges": edges, "include_inferred": include_inferred}

    async def classify_all_mappings(self, db: Session) -> dict:
        return {"total": 0, "classified": 0, "message": "PG mappings are pre-classified"}

    async def discover_unmapped_guides(self, db: Session) -> dict:
        return {"discovered": 0, "message": "Discovery is handled by the materialization pipeline"}

    def get_semantic_mappings(
        self,
        db: Session,
        relation_type: str = None,
        discovery_method: str = None,
        min_confidence: float = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict:
        query = db.query(PgGuideArticleMapping, PgKoshaGuide).join(
            PgKoshaGuide,
            PgGuideArticleMapping.guide_code == PgKoshaGuide.guide_code,
        )
        total = query.count()
        rows = query.offset(skip).limit(limit).all()
        return {
            "total": total,
            "mappings": [
                {
                    "id": f"{mapping.guide_code}:{mapping.article_code}",
                    "source_type": "article",
                    "source_id": mapping.article_code,
                    "target_type": "guide",
                    "target_id": mapping.guide_code,
                    "target_title": guide.title,
                    "relation_type": relation_type or "IMPLEMENTS",
                    "confidence": 0.9,
                    "discovery_method": discovery_method or "materialized_pg",
                }
                for mapping, guide in rows
            ],
        }


ontology_service = OntologyService()
