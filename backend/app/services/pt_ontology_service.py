"""포르투갈어 온톨로지 서비스.

기존 OntologyService와 동일한 쿼리 인터페이스를 제공하되,
PT 번역 테이블(norm_statements_pt, kosha_guides_pt, article_titles_pt)에서
데이터를 읽어 포르투갈어로 응답한다.
"""
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text, func as sa_func, distinct

from app.db.models import (
    NormStatement, SemanticMapping,
    RegGuideMapping, KoshaGuide,
)
from app.services.article_service import article_service

logger = logging.getLogger(__name__)


def _convert_article_number(art_num: str) -> str:
    """제42조 → Art. 42"""
    m = re.match(r'제(\d+)조(?:의(\d+))?', art_num)
    if m:
        num, sub = m.group(1), m.group(2)
        return f"Art. {num}-{sub}" if sub else f"Art. {num}"
    return art_num


class PtOntologyService:
    """포르투갈어 온톨로지 서비스"""

    # ── 헬퍼: PT 테이블에서 데이터 읽기 ──

    def _get_article_title_pt(self, db: Session, article_number: str) -> Optional[str]:
        """article_titles_pt에서 포르투갈어 제목 조회"""
        row = db.execute(
            text("SELECT title_pt FROM article_titles_pt WHERE article_number = :a"),
            {"a": article_number}
        ).fetchone()
        return row[0] if row else None

    def _get_article_number_pt(self, article_number: str) -> str:
        return _convert_article_number(article_number)

    def _get_guide_title_pt(self, db: Session, guide_id: int) -> Optional[str]:
        """kosha_guides_pt에서 포르투갈어 제목 조회"""
        row = db.execute(
            text("SELECT title FROM kosha_guides_pt WHERE original_id = :id"),
            {"id": guide_id}
        ).fetchone()
        return row[0] if row else None

    # ── 공개 API 메서드 ──

    def get_mapping_stats(self, db: Session) -> dict:
        """매핑 통계 (수치는 동일, 라벨만 다름 — 프론트에서 처리)"""
        # 기존 서비스와 동일 로직
        all_articles = article_service.load_articles()
        total_articles = len(set(a.article_number for a in all_articles))

        all_mapped_articles = set(
            row[0] for row in db.query(distinct(RegGuideMapping.article_number)).all()
        )
        sm_mapped_articles = set(
            row[0] for row in
            db.query(distinct(SemanticMapping.source_id))
            .filter(SemanticMapping.source_type == "article", SemanticMapping.target_type == "guide")
            .all()
        )
        total_mapped_articles = len(all_mapped_articles | sm_mapped_articles)

        total_guides = db.query(KoshaGuide).count()
        mapped_guide_ids = set(
            row[0] for row in db.query(distinct(RegGuideMapping.guide_id)).all()
        )
        sm_guide_ids = set(
            row[0] for row in
            db.query(distinct(SemanticMapping.target_id))
            .filter(SemanticMapping.target_type == "guide")
            .all()
        )
        try:
            sm_guide_ids_int = {int(x) for x in sm_guide_ids if x.isdigit()}
        except Exception:
            sm_guide_ids_int = set()
        total_mapped_guides = len(mapped_guide_ids | sm_guide_ids_int)

        total_explicit = db.query(RegGuideMapping).count()
        total_semantic = db.query(SemanticMapping).count()

        relation_counts = dict(
            db.query(SemanticMapping.relation_type, sa_func.count())
            .group_by(SemanticMapping.relation_type)
            .all()
        )
        discovery_counts = dict(
            db.query(SemanticMapping.discovery_method, sa_func.count())
            .group_by(SemanticMapping.discovery_method)
            .all()
        )

        before_pct = round(len(all_mapped_articles) / total_articles * 100, 1) if total_articles else 0
        after_pct = round(total_mapped_articles / total_articles * 100, 1) if total_articles else 0

        return {
            "total_articles": total_articles,
            "mapped_articles": total_mapped_articles,
            "unmapped_articles": total_articles - total_mapped_articles,
            "total_guides": total_guides,
            "mapped_guides": total_mapped_guides,
            "unmapped_guides": total_guides - total_mapped_guides,
            "total_explicit_mappings": total_explicit,
            "total_semantic_mappings": total_semantic,
            "mapping_by_relation_type": relation_counts,
            "mapping_by_discovery": discovery_counts,
            "coverage_improvement": {"before": before_pct, "after": after_pct},
        }

    def get_article_norms(self, db: Session, article_number: str) -> dict:
        """특정 법조항의 PT 규범명제 + 연결 가이드"""
        # PT 규범명제 조회
        rows = db.execute(
            text("""
                SELECT original_id, article_number, article_number_pt, paragraph,
                       statement_order, subject_role, action, object, condition_text,
                       legal_effect, effect_description, full_text, norm_category
                FROM norm_statements_pt
                WHERE article_number = :a
                ORDER BY statement_order
            """),
            {"a": article_number}
        ).fetchall()

        norms = []
        for r in rows:
            norms.append({
                "id": r[0],
                "article_number": r[2] or _convert_article_number(r[1]),  # PT format
                "paragraph": r[3],
                "statement_order": r[4],
                "subject_role": r[5],
                "action": r[6],
                "object": r[7],
                "condition_text": r[8],
                "legal_effect": r[9],
                "effect_description": r[10],
                "full_text": r[11],
                "norm_category": r[12],
            })

        # 연결 가이드 (PT 제목 사용)
        sm_list = (
            db.query(SemanticMapping)
            .filter(SemanticMapping.source_id == article_number)
            .filter(SemanticMapping.target_type == "guide")
            .order_by(SemanticMapping.confidence.desc())
            .all()
        )

        guides = []
        for sm in sm_list:
            try:
                guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(sm.target_id)).first()
                if guide:
                    pt_title = self._get_guide_title_pt(db, guide.id) or guide.title
                    guides.append({
                        "guide_code": guide.guide_code,
                        "title": pt_title,
                        "classification": guide.classification,
                        "relation_type": sm.relation_type,
                        "confidence": sm.confidence,
                        "discovery_method": sm.discovery_method,
                    })
            except (ValueError, Exception):
                continue

        # 법조항 PT 제목
        title_pt = self._get_article_title_pt(db, article_number)
        if not title_pt:
            info = article_service._find_article_by_number(article_number)
            title_pt = info["title"] if info else None

        return {
            "article_number": _convert_article_number(article_number),
            "article_title": title_pt,
            "total_norms": len(norms),
            "norms": norms,
            "linked_guides": guides,
        }

    def get_article_graph(self, db: Session, article_number: str) -> dict:
        """특정 법조항 중심 그래프 (PT 라벨)"""
        nodes = []
        edges = []
        node_ids = set()

        # 중심 노드
        art_pt = _convert_article_number(article_number)
        title_pt = self._get_article_title_pt(db, article_number)
        art_label = f"{art_pt}\n{title_pt}" if title_pt else art_pt
        nodes.append({
            "id": article_number,
            "label": art_label,
            "group": "article",
            "shape": "box",
            "color": "#4FC3F7",
        })
        node_ids.add(article_number)

        # PT 규범명제 노드
        pt_rows = db.execute(
            text("""
                SELECT original_id, action, legal_effect
                FROM norm_statements_pt
                WHERE article_number = :a
            """),
            {"a": article_number}
        ).fetchall()

        for r in pt_rows:
            norm_id = f"norm_{r[0]}"
            label = f"{r[2]}\n{r[1] or ''}"
            nodes.append({
                "id": norm_id,
                "label": label,
                "group": "norm",
                "shape": "ellipse",
                "color": "#81C784" if r[2] == "OBLIGATION" else "#EF5350",
            })
            node_ids.add(norm_id)
            edges.append({
                "from": article_number,
                "to": norm_id,
                "label": "hasNorm",
                "dashes": False,
            })

        # 연결된 가이드
        sm_list = db.query(SemanticMapping).filter(
            SemanticMapping.source_id == article_number
        ).all()

        for sm in sm_list:
            target_id = sm.target_id
            if sm.target_type == "guide":
                try:
                    guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(target_id)).first()
                    if guide and guide.guide_code not in node_ids:
                        pt_title = self._get_guide_title_pt(db, guide.id) or guide.title
                        nodes.append({
                            "id": guide.guide_code,
                            "label": f"{guide.guide_code}\n{pt_title[:20]}",
                            "group": "guide",
                            "shape": "diamond",
                            "color": "#FFB74D",
                        })
                        node_ids.add(guide.guide_code)
                    target_id = guide.guide_code if guide else target_id
                except (ValueError, Exception):
                    pass
            elif sm.target_type == "article" and target_id not in node_ids:
                t_pt = _convert_article_number(target_id)
                nodes.append({
                    "id": target_id,
                    "label": t_pt,
                    "group": "article",
                    "shape": "box",
                    "color": "#4FC3F7",
                })
                node_ids.add(target_id)

            edges.append({
                "from": article_number,
                "to": target_id,
                "label": sm.relation_type,
                "dashes": sm.discovery_method == "vector",
                "color": {"opacity": sm.confidence},
            })

        return {"nodes": nodes, "edges": edges}

    def get_full_graph(self, db: Session, limit: int = 100) -> dict:
        """전체 온톨로지 그래프 (PT 라벨)"""
        nodes = []
        edges = []
        node_ids = set()

        top_articles = (
            db.query(SemanticMapping.source_id, sa_func.count().label("cnt"))
            .filter(SemanticMapping.source_type == "article")
            .group_by(SemanticMapping.source_id)
            .order_by(sa_func.count().desc())
            .limit(limit)
            .all()
        )

        for art_num, cnt in top_articles:
            if art_num not in node_ids:
                art_pt = _convert_article_number(art_num)
                title_pt = self._get_article_title_pt(db, art_num)
                if title_pt:
                    label = f"{art_pt}\n({title_pt[:15]})"
                else:
                    label = art_pt
                nodes.append({
                    "id": art_num,
                    "label": label,
                    "group": "article",
                    "shape": "box",
                    "color": "#4FC3F7",
                    "value": cnt,
                })
                node_ids.add(art_num)

            sms = db.query(SemanticMapping).filter(
                SemanticMapping.source_id == art_num
            ).limit(5).all()

            for sm in sms:
                target_label = sm.target_id
                if sm.target_type == "guide":
                    try:
                        guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(sm.target_id)).first()
                        if guide:
                            target_label = guide.guide_code
                            if target_label not in node_ids:
                                pt_title = self._get_guide_title_pt(db, guide.id) or guide.title
                                nodes.append({
                                    "id": target_label,
                                    "label": f"{guide.guide_code}\n{pt_title[:12]}",
                                    "group": "guide",
                                    "shape": "diamond",
                                    "color": "#FFB74D",
                                })
                                node_ids.add(target_label)
                    except (ValueError, Exception):
                        if sm.target_id not in node_ids:
                            nodes.append({
                                "id": sm.target_id,
                                "label": sm.target_id,
                                "group": "unknown",
                                "shape": "dot",
                            })
                            node_ids.add(sm.target_id)
                        target_label = sm.target_id
                elif sm.target_type == "article" and sm.target_id not in node_ids:
                    t_pt = _convert_article_number(sm.target_id)
                    nodes.append({
                        "id": sm.target_id,
                        "label": t_pt,
                        "group": "article",
                        "shape": "box",
                        "color": "#4FC3F7",
                    })
                    node_ids.add(sm.target_id)
                    target_label = sm.target_id

                edges.append({
                    "from": art_num,
                    "to": target_label,
                    "label": sm.relation_type,
                    "dashes": sm.discovery_method == "vector",
                })

        return {"nodes": nodes, "edges": edges}


pt_ontology_service = PtOntologyService()
