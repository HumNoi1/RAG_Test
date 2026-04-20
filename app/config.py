from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "rag_demo"

    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"

    openai_api_key: str = ""

    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 5

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
