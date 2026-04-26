from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """OHS 전용 테이블만 생성 (PG 기존 테이블은 건드리지 않음)."""
    from app.db import models  # noqa: F401
    Base.metadata.create_all(
        bind=engine,
        tables=[
            models.OhsAnalysisRecord.__table__,
            models.OhsSafetyVideo.__table__,
            models.OhsHazardCodeGap.__table__,
        ],
    )
