from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    # OpenAI
    OPENAI_API_KEY: str = ""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # File Upload
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".webp"]

    # Database (PostgreSQL — koshaontology single source of truth)
    DATABASE_URL: str = "postgresql://kosha:1229@localhost/kosha"

    # Fuseki SPARQL (OWL DL inference engine)
    # Phase 0.5 환경 분리:
    #   docker container 내부:    http://kosha-fuseki:3030/kosha/sparql
    #   host 머신 (eval/dev):     http://localhost:3030/kosha/sparql
    # default를 localhost로 → host eval에서 즉시 동작. docker 내부에서는 환경변수로 override.
    FUSEKI_ENDPOINT: str = "http://localhost:3030/kosha/sparql"
    FUSEKI_TIMEOUT: int = 5
    FUSEKI_ENABLED: bool = True

    # Phase 3: SHE rollout feature flags (사용자 비판 #12)
    # 기본 false → Phase 3 단계적 활성화. eval 환경 먼저 true → 검증 후 prod true.
    OHS_ENABLE_SHE: bool = False
    OHS_ENABLE_HYBRID_SEARCH: bool = False
    OHS_ENABLE_SHE_SPARQL_CHAIN: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
