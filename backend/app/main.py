import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path

from app.config import settings
from app.api.v1.router import router as api_v1_router
from app.db.database import create_tables
from app.services.article_service import article_service

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

# PDF 파일 직접 제공 (프론트엔드에서 PDF 뷰어로 열기 위함)
articles_path = Path("/home/blessjin/cashtoss/ohs/ohs_articles")
if articles_path.exists():
    app.mount("/articles-pdf", StaticFiles(directory=str(articles_path)), name="articles-pdf")


@app.get("/")
async def root():
    return {"message": "OHS 위험요소 분석 API", "version": "2.0.0"}
