"""SQLite → PostgreSQL 데이터 이관 스크립트.

이관 대상:
  1. analysis_records → ohs_analysis_records
  2. safety_videos   → ohs_safety_videos

이관 불필요 (PG에 더 풍부한 데이터 존재):
  - kosha_guides, guide_sections, norm_statements, semantic_mappings, reg_guide_mapping
"""
import sys
import os
import json
import sqlite3
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.config import settings


def get_sqlite_conn(sqlite_path: str):
    if not os.path.exists(sqlite_path):
        print(f"[SKIP] SQLite DB 파일 없음: {sqlite_path}")
        return None
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_analysis_records(sqlite_conn, pg_session):
    """analysis_records → ohs_analysis_records"""
    cursor = sqlite_conn.execute("SELECT * FROM analysis_records")
    rows = cursor.fetchall()
    if not rows:
        print("[SKIP] analysis_records: 0건")
        return 0

    count = 0
    for row in rows:
        row_dict = dict(row)
        analysis_id = row_dict.get("id")

        # 중복 확인
        existing = pg_session.execute(
            text("SELECT 1 FROM ohs_analysis_records WHERE id = :id"),
            {"id": analysis_id}
        ).fetchone()
        if existing:
            continue

        # result_json 파싱
        result_json = row_dict.get("result_json")
        if isinstance(result_json, str):
            try:
                result_json = json.loads(result_json)
            except (json.JSONDecodeError, TypeError):
                result_json = {}

        pg_session.execute(
            text("""
                INSERT INTO ohs_analysis_records
                    (id, analysis_type, overall_risk_level, summary, input_preview, result_json, created_at)
                VALUES
                    (:id, :analysis_type, :overall_risk_level, :summary, :input_preview, :result_json::jsonb, :created_at)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": analysis_id,
                "analysis_type": row_dict.get("analysis_type", "text"),
                "overall_risk_level": row_dict.get("overall_risk_level", "medium"),
                "summary": row_dict.get("summary", ""),
                "input_preview": row_dict.get("input_preview"),
                "result_json": json.dumps(result_json, ensure_ascii=False) if result_json else "{}",
                "created_at": row_dict.get("created_at"),
            }
        )
        count += 1

    pg_session.commit()
    print(f"[OK] analysis_records: {count}건 이관")
    return count


def migrate_safety_videos(sqlite_conn, pg_session):
    """safety_videos → ohs_safety_videos"""
    try:
        cursor = sqlite_conn.execute("SELECT * FROM safety_videos")
    except sqlite3.OperationalError:
        print("[SKIP] safety_videos: 테이블 없음")
        return 0

    rows = cursor.fetchall()
    if not rows:
        print("[SKIP] safety_videos: 0건")
        return 0

    count = 0
    for row in rows:
        row_dict = dict(row)
        url = row_dict.get("url")

        # URL 기반 중복 확인
        existing = pg_session.execute(
            text("SELECT 1 FROM ohs_safety_videos WHERE url = :url"),
            {"url": url}
        ).fetchone()
        if existing:
            continue

        pg_session.execute(
            text("""
                INSERT INTO ohs_safety_videos
                    (title, url, category, tags, hazard_categories, hazard_codes,
                     description, series, is_korean, thumbnail_url, video_type, duration, playlist)
                VALUES
                    (:title, :url, :category, :tags, :hazard_categories, :hazard_codes,
                     :description, :series, :is_korean, :thumbnail_url, :video_type, :duration, :playlist)
                ON CONFLICT (url) DO NOTHING
            """),
            {
                "title": row_dict.get("title", ""),
                "url": url,
                "category": row_dict.get("category", ""),
                "tags": row_dict.get("tags"),
                "hazard_categories": row_dict.get("hazard_categories", "[]"),
                "hazard_codes": row_dict.get("hazard_codes"),
                "description": row_dict.get("description"),
                "series": row_dict.get("series"),
                "is_korean": row_dict.get("is_korean", 1),
                "thumbnail_url": row_dict.get("thumbnail_url"),
                "video_type": row_dict.get("video_type", "short"),
                "duration": row_dict.get("duration"),
                "playlist": row_dict.get("playlist"),
            }
        )
        count += 1

    pg_session.commit()
    print(f"[OK] safety_videos: {count}건 이관")
    return count


def main():
    # SQLite DB 경로
    sqlite_path = str(Path(__file__).resolve().parent.parent / "ohs.db")

    sqlite_conn = get_sqlite_conn(sqlite_path)
    if not sqlite_conn:
        print("SQLite DB 없음 — 이관할 데이터 없음. 종료.")
        return

    # PostgreSQL 세션
    pg_engine = create_engine(settings.DATABASE_URL)
    PgSession = sessionmaker(bind=pg_engine)
    pg_session = PgSession()

    try:
        # OHS 전용 테이블 생성 (없으면)
        from app.db.database import create_tables
        create_tables()
        print("[OK] OHS 전용 테이블 준비 완료")

        # 이관 실행
        migrate_analysis_records(sqlite_conn, pg_session)
        migrate_safety_videos(sqlite_conn, pg_session)

        print("\n이관 완료.")
    except Exception as e:
        pg_session.rollback()
        print(f"[ERROR] 이관 실패: {e}")
        raise
    finally:
        pg_session.close()
        sqlite_conn.close()


if __name__ == "__main__":
    main()
