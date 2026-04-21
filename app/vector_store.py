from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    ScoredPoint,
    VectorParams,
)
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from app.config import get_settings
from app.embeddings import get_embedding_dimension
from functools import lru_cache
import uuid
import logging

logger = logging.getLogger(__name__)


class QdrantUnavailableError(RuntimeError):
    """Raised when the API cannot connect to Qdrant."""


class CollectionNotFoundError(RuntimeError):
    """Raised when the requested Qdrant collection does not exist."""


class CollectionDimensionMismatchError(RuntimeError):
    """Raised when the active embedding model does not match collection vector size."""


def _raise_qdrant_error(exc: ResponseHandlingException | UnexpectedResponse) -> None:
    if isinstance(exc, ResponseHandlingException):
        raise QdrantUnavailableError(
            "Qdrant ไม่พร้อมใช้งานหรือยังไม่ได้รันที่ปลายทางที่ตั้งค่าไว้"
        ) from exc

    if exc.status_code == 404:
        try:
            detail = exc.structured().get("status", {}).get("error")
        except Exception:
            detail = None
        raise CollectionNotFoundError(detail or "ไม่พบ collection ที่ระบุ") from exc

    raise exc


def _get_collection_vector_size(collection_info) -> int | None:
    vectors_config = getattr(collection_info.config.params, "vectors", None)
    return getattr(vectors_config, "size", None)


def _get_collection_details(collection_name: str):
    client = get_qdrant_client()
    try:
        return client.get_collection(collection_name)
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)


def _validate_collection_dimension(collection_name: str, expected_dim: int) -> None:
    info = _get_collection_details(collection_name)
    actual_dim = _get_collection_vector_size(info)
    if actual_dim is not None and actual_dim != expected_dim:
        raise CollectionDimensionMismatchError(
            f"Collection '{collection_name}' ใช้ vector dim={actual_dim} แต่ embedding model "
            f"'{get_settings().embedding_model}' ให้ dim={expected_dim} — "
            "ให้เปลี่ยน QDRANT_COLLECTION หรือสร้าง collection ใหม่ก่อน ingest/search"
        )


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    logger.info(f"Qdrant connected: {settings.qdrant_host}:{settings.qdrant_port}")
    return client


def ensure_collection(collection_name: str) -> None:
    """สร้าง collection ถ้ายังไม่มี"""
    client = get_qdrant_client()
    dim = get_embedding_dimension()
    try:
        existing = [c.name for c in client.get_collections().collections]
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)

    if collection_name not in existing:
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        except (ResponseHandlingException, UnexpectedResponse) as exc:
            _raise_qdrant_error(exc)
        logger.info(f"Created collection '{collection_name}' with dim={dim}")
    else:
        _validate_collection_dimension(collection_name, dim)
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

    try:
        client.upsert(collection_name=collection_name, points=points)
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)
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
    _validate_collection_dimension(collection_name, len(query_vector))
    try:
        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)
    return results


def delete_collection(collection_name: str) -> bool:
    """ลบ collection ออกจาก Qdrant"""
    client = get_qdrant_client()
    try:
        client.delete_collection(collection_name)
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)
    logger.info(f"Deleted collection '{collection_name}'")
    return True


def get_collection_info(collection_name: str) -> dict:
    """ดูข้อมูลของ collection"""
    info = _get_collection_details(collection_name)
    return {
        "name": collection_name,
        "vectors_count": info.vectors_count,
        "points_count": info.points_count,
        "status": str(info.status),
        "vector_size": _get_collection_vector_size(info),
    }
