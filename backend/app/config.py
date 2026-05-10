from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    OPENAI_API_KEY: str = ""

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".webp"]

    DATABASE_URL: str = "postgresql://kosha:1229@localhost/kosha"

    FUSEKI_ENDPOINT: str = "http://localhost:3030/kosha/sparql"
    FUSEKI_TIMEOUT: int = 5
    FUSEKI_ENABLED: bool = True

    OHS_ENABLE_HYBRID_SEARCH: bool = False


settings = Settings()
