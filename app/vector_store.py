from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    ScoredPoint,
)
from app.config import get_settings
from app.embeddings import get_embedding_dimension
from functools import lru_cache
import uuid
import logging

logger = logging.getLogger(__name__)


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    logger.info(f"Qdrant connected: {settings.qdrant_host}:{settings.qdrant_port}")
    return client


def ensure_collection(collection_name: str) -> None:
    """สร้าง collection ถ้ายังไม่มี"""
    client = get_qdrant_client()
    existing = [c.name for c in client.get_collections().collections]

    if collection_name not in existing:
        dim = get_embedding_dimension()
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        logger.info(f"Created collection '{collection_name}' with dim={dim}")
    else:
        logger.info(f"Collection '{collection_name}' already exists")


def upsert_chunks(
    collection_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
    source: str,
) -> int:
    """บันทึก chunks พร้อม vectors เข้า Qdrant"""
    client = get_qdrant_client()
    ensure_collection(collection_name)

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "text": chunk,
                "source": source,
                "chunk_index": i,
            },
        )
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]

    client.upsert(collection_name=collection_name, points=points)
    logger.info(f"Upserted {len(points)} chunks into '{collection_name}'")
    return len(points)


def search_similar(
    collection_name: str,
    query_vector: list[float],
    top_k: int = 5,
    score_threshold: float = 0.0,
) -> list[ScoredPoint]:
    """ค้นหา chunks ที่ใกล้เคียงกับ query vector"""
    client = get_qdrant_client()
    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
        with_payload=True,
    )
    return results


def delete_collection(collection_name: str) -> bool:
    """ลบ collection ออกจาก Qdrant"""
    client = get_qdrant_client()
    client.delete_collection(collection_name)
    logger.info(f"Deleted collection '{collection_name}'")
    return True


def get_collection_info(collection_name: str) -> dict:
    """ดูข้อมูลของ collection"""
    client = get_qdrant_client()
    info = client.get_collection(collection_name)
    return {
        "name": collection_name,
        "vectors_count": info.vectors_count,
        "points_count": info.points_count,
        "status": str(info.status),
    }
