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
    FUSEKI_ENDPOINT: str = "http://kosha-fuseki:3030/kosha/sparql"
    FUSEKI_TIMEOUT: int = 5
    FUSEKI_ENABLED: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
