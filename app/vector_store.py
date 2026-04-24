import logging
import uuid
from functools import lru_cache

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from app.config import get_settings
from app.embeddings import get_embedding_dimension
from app.models import MetadataValue

logger = logging.getLogger(__name__)

_validated_collections: set[str] = set()


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
    if collection_name in _validated_collections:
        return
    info = _get_collection_details(collection_name)
    actual_dim = _get_collection_vector_size(info)
    if actual_dim is not None and actual_dim != expected_dim:
        raise CollectionDimensionMismatchError(
            f"Collection '{collection_name}' ใช้ vector dim={actual_dim} แต่ embedding model "
            f"'{get_settings().embedding_model}' ให้ dim={expected_dim} — "
            "ให้เปลี่ยน QDRANT_COLLECTION หรือสร้าง collection ใหม่ก่อน ingest/search"
        )
    _validated_collections.add(collection_name)


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
    metadata: dict[str, MetadataValue] | None = None,
) -> int:
    """บันทึก chunks พร้อม vectors เข้า Qdrant"""
    client = get_qdrant_client()
    ensure_collection(collection_name)
    base_metadata = metadata or {}

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "text": chunk,
                "source": source,
                "chunk_index": i,
                **base_metadata,
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
    metadata_filters: dict[str, MetadataValue] | None = None,
) -> list[ScoredPoint]:
    """ค้นหา chunks ที่ใกล้เคียงกับ query vector"""
    client = get_qdrant_client()
    _validate_collection_dimension(collection_name, len(query_vector))
    query_filter = build_metadata_filter(metadata_filters)
    try:
        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
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
    _validated_collections.discard(collection_name)
    logger.info(f"Deleted collection '{collection_name}'")
    return True


def delete_chunks_by_filter(
    collection_name: str,
    metadata_filters: dict[str, MetadataValue],
) -> None:
    """ลบ points ทั้งหมดใน Qdrant ที่ตรงกับ metadata filter (เช่น document_id)"""
    if not metadata_filters:
        raise ValueError("metadata_filters ต้องระบุอย่างน้อย 1 field")
    client = get_qdrant_client()
    query_filter = build_metadata_filter(metadata_filters)
    try:
        client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(filter=query_filter),
        )
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)
    logger.info(
        "Deleted chunks by filter %s from '%s'", metadata_filters, collection_name
    )


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


def build_metadata_filter(
    metadata_filters: dict[str, MetadataValue] | None,
) -> Filter | None:
    if not metadata_filters:
        return None

    return Filter(
        must=[
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in metadata_filters.items()
        ]
    )


# ── Async Qdrant client & hot-path functions ──────────────────────────────────


@lru_cache
def get_async_qdrant_client() -> AsyncQdrantClient:
    settings = get_settings()
    client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    logger.info(
        f"Async Qdrant client created: {settings.qdrant_host}:{settings.qdrant_port}"
    )
    return client


async def _get_collection_details_async(collection_name: str):
    client = get_async_qdrant_client()
    try:
        return await client.get_collection(collection_name)
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)


async def _validate_collection_dimension_async(
    collection_name: str, expected_dim: int
) -> None:
    if collection_name in _validated_collections:
        return
    info = await _get_collection_details_async(collection_name)
    actual_dim = _get_collection_vector_size(info)
    if actual_dim is not None and actual_dim != expected_dim:
        raise CollectionDimensionMismatchError(
            f"Collection '{collection_name}' ใช้ vector dim={actual_dim} แต่ embedding model "
            f"'{get_settings().embedding_model}' ให้ dim={expected_dim} — "
            "ให้เปลี่ยน QDRANT_COLLECTION หรือสร้าง collection ใหม่ก่อน ingest/search"
        )
    _validated_collections.add(collection_name)


async def ensure_collection_async(collection_name: str) -> None:
    """Async: สร้าง collection ถ้ายังไม่มี"""
    client = get_async_qdrant_client()
    dim = get_embedding_dimension()
    try:
        collections_response = await client.get_collections()
        existing = [c.name for c in collections_response.collections]
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)

    if collection_name not in existing:
        try:
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        except (ResponseHandlingException, UnexpectedResponse) as exc:
            _raise_qdrant_error(exc)
        logger.info(f"Created collection '{collection_name}' with dim={dim}")
    else:
        await _validate_collection_dimension_async(collection_name, dim)
        logger.info(f"Collection '{collection_name}' already exists")


async def upsert_chunks_async(
    collection_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
    source: str,
    metadata: dict[str, MetadataValue] | None = None,
) -> int:
    """Async: บันทึก chunks พร้อม vectors เข้า Qdrant"""
    client = get_async_qdrant_client()
    await ensure_collection_async(collection_name)
    base_metadata = metadata or {}

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "text": chunk,
                "source": source,
                "chunk_index": i,
                **base_metadata,
            },
        )
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]

    try:
        await client.upsert(collection_name=collection_name, points=points)
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)
    logger.info(f"Upserted {len(points)} chunks into '{collection_name}'")
    return len(points)


async def search_similar_async(
    collection_name: str,
    query_vector: list[float],
    top_k: int = 5,
    score_threshold: float = 0.0,
    metadata_filters: dict[str, MetadataValue] | None = None,
) -> list[ScoredPoint]:
    """Async: ค้นหา chunks ที่ใกล้เคียงกับ query vector"""
    client = get_async_qdrant_client()
    await _validate_collection_dimension_async(collection_name, len(query_vector))
    query_filter = build_metadata_filter(metadata_filters)
    try:
        results = await client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
    except (ResponseHandlingException, UnexpectedResponse) as exc:
        _raise_qdrant_error(exc)
    return results
