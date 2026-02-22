import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.api.v1.router import router as api_v1_router
from app.db.database import create_tables, SessionLocal
from app.services.article_service import article_service
from app.services.guide_service import guide_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_tables()
    # 법조항 인덱스 자동 생성 (이미 있으면 스킵)
    try:
        count = article_service.build_index(force=False)
        logger.info(f"법조항 인덱스 준비 완료: {count}개 조문")
    except Exception as e:
        logger.error(f"법조항 인덱싱 실패 (서비스는 계속 실행): {e}")

    # KOSHA GUIDE 파싱 및 인덱싱 (이미 있으면 스킵)
    try:
        db = SessionLocal()
        try:
            parse_result = guide_service.parse_and_store_all(db, force=False)
            if not parse_result.get("skipped"):
                logger.info(f"KOSHA GUIDE 파싱 완료: {parse_result['total_parsed']}개")
                # 매핑 생성
                mappings = guide_service.build_mappings(db)
                logger.info(f"KOSHA GUIDE 매핑 완료: {mappings}건")
            else:
                logger.info(f"KOSHA GUIDE 이미 파싱됨: {parse_result['total_parsed']}개")

            # ChromaDB 임베딩 인덱싱 (이미 있으면 스킵)
            indexed = guide_service.build_index(db, force=False)
            logger.info(f"KOSHA GUIDE 인덱스 준비 완료: {indexed}개 섹션")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"KOSHA GUIDE 초기화 실패 (서비스는 계속 실행): {e}")

    yield
    # Shutdown


app = FastAPI(
    title="OHS 위험요소 분석 API",
    description="산업안전보건 위험요소 분석 서비스 - 법조항 연계",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"message": "OHS 위험요소 분석 API", "version": "2.0.0"}
