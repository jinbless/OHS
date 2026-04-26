"""포르투갈어 온톨로지 서비스 — PG 전환 후 ontology_service 위임.

PT 번역 테이블(norm_statements_pt, kosha_guides_pt, article_titles_pt)이
존재하면 PT 라벨을 사용하고, 없으면 한국어 원본 데이터를 그대로 반환한다.
"""
import logging
import re

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.ontology_service import ontology_service

logger = logging.getLogger(__name__)


def _convert_article_number(art_num: str) -> str:
    """제42조 → Art. 42"""
    m = re.match(r'제(\d+)조(?:의(\d+))?', art_num)
    if m:
        num, sub = m.group(1), m.group(2)
        return f"Art. {num}-{sub}" if sub else f"Art. {num}"
    return art_num


def _has_pt_tables(db: Session) -> bool:
    """PT 번역 테이블 존재 여부"""
    try:
        db.execute(text("SELECT 1 FROM norm_statements_pt LIMIT 1"))
        return True
    except Exception:
        return False


class PtOntologyService:
    """포르투갈어 온톨로지 서비스 — ontology_service 위임"""

    def get_mapping_stats(self, db: Session) -> dict:
        return ontology_service.get_mapping_stats(db)

    def get_article_norms(self, db: Session, article_number: str) -> dict:
        result = ontology_service.get_article_norms(db, article_number)
        # PT 테이블이 있으면 라벨만 변환
        if _has_pt_tables(db):
            try:
                rows = db.execute(
                    text("""
                        SELECT original_id, article_number_pt, full_text
                        FROM norm_statements_pt
                        WHERE article_number = :a
                        ORDER BY statement_order
                    """),
                    {"a": article_number}
                ).fetchall()
                if rows:
                    result["article_number"] = _convert_article_number(article_number)
                    for i, r in enumerate(rows):
                        if i < len(result.get("norms", [])):
                            result["norms"][i]["article_number"] = r[1] or _convert_article_number(article_number)
                            result["norms"][i]["full_text"] = r[2]
            except Exception as e:
                logger.warning(f"PT norm 조회 실패: {e}")
        return result

    def get_article_graph(self, db: Session, article_number: str) -> dict:
        return ontology_service.get_article_graph(db, article_number)

    def get_full_graph(self, db: Session, limit: int = 100) -> dict:
        return ontology_service.get_full_graph(db, limit=limit)


pt_ontology_service = PtOntologyService()
