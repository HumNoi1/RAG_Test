from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "rag_demo_bge_m3"

    embedding_model: str = "BAAI/bge-m3"

    llm_model: str = "qwen/qwen3-32b"
    groq_api_key: str = ""

    chunk_size: int = 1200
    chunk_overlap: int = 150
    top_k: int = 5
    embedding_batch_size: int = 32  # จำนวน texts ที่ encode พร้อมกันใน 1 batch
    upsert_batch_size: int = 100  # จำนวน points ที่ upsert เข้า Qdrant ใน 1 batch

    cors_origins: list[str] = ["http://localhost:3000"]

    max_upload_mb: int = 20
    llm_temperature: float = 0.2
    max_context_chars: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
