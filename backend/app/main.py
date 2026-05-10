import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as api_v1_router
from app.config import settings
from app.db.database import SessionLocal, create_tables
from app.services.article_service import article_service
from app.services.guide_service import guide_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()

    try:
        count = article_service.build_index(force=False)
        logger.info("Article index ready: %s articles", count)
    except Exception as exc:
        logger.warning("Article index startup skipped: %s", exc)

    try:
        db = SessionLocal()
        try:
            parse_result = guide_service.parse_and_store_all(db, force=False)
            if not parse_result.get("skipped"):
                mappings = guide_service.build_mappings(db)
                logger.info(
                    "KOSHA Guide parsed: %s guides, %s mappings",
                    parse_result.get("total_parsed", 0),
                    mappings,
                )
            indexed = guide_service.build_index(db, force=False)
            logger.info("KOSHA Guide index ready: %s sections", indexed)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("KOSHA Guide startup skipped: %s", exc)

    try:
        from app.integrations.sparql_client import sparql_client

        health = await sparql_client.health_check()
        if health.get("fuseki_reachable"):
            logger.info("Fuseki SPARQL reachable: %s", settings.FUSEKI_ENDPOINT)
        else:
            logger.info("Fuseki SPARQL unavailable; running with materialized PG data")
    except Exception as exc:
        logger.info("Fuseki probe skipped: %s", exc)

    yield


app = FastAPI(
    title="OHS ontology analysis API",
    description="Photo/text observation to risk features, SHE patterns, SR, guide, and penalty paths.",
    version="3.0.0",
    lifespan=lifespan,
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
    return {"message": "OHS ontology analysis API", "version": "3.0.0"}
