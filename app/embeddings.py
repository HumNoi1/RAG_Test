from sentence_transformers import SentenceTransformer
from functools import lru_cache
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    logger.info(f"Loading embedding model: {settings.embedding_model}")
    model = SentenceTransformer(settings.embedding_model)
    logger.info(f"Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}")
    return model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts into vectors."""
    model = get_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    model = get_embedding_model()
    embedding = model.encode([query], normalize_embeddings=True)
    return embedding[0].tolist()


def get_embedding_dimension() -> int:
    return get_embedding_model().get_sentence_embedding_dimension()
