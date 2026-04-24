import asyncio
import logging
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_CONCURRENT_EMBEDDINGS = 4
_embedding_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EMBEDDINGS)


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    logger.info(f"Loading embedding model: {settings.embedding_model}")
    model = SentenceTransformer(settings.embedding_model)
    logger.info(
        f"Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}"
    )
    return model


def _encode_texts(texts: list[str]) -> list[list[float]]:
    """CPU-bound: encode texts synchronously. Call only via to_thread or sync helpers."""
    model = get_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Async: run encoding in thread pool with concurrency limiting."""
    async with _embedding_semaphore:
        return await asyncio.to_thread(_encode_texts, texts)


async def embed_query(query: str) -> list[float]:
    """Async: embed a single query string with concurrency limiting."""
    async with _embedding_semaphore:
        result = await asyncio.to_thread(_encode_texts, [query])
        return result[0]


# ── Sync aliases for CLI / evaluation.py ──────────────────────────────────────


def embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """Sync wrapper — use only from CLI tools, never from async FastAPI handlers."""
    return _encode_texts(texts)


def embed_query_sync(query: str) -> list[float]:
    """Sync wrapper — use only from CLI tools, never from async FastAPI handlers."""
    return _encode_texts([query])[0]


def get_embedding_dimension() -> int:
    return get_embedding_model().get_sentence_embedding_dimension()
