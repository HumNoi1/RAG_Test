import json

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.models import ExtractTextResponse, IngestRequest, IngestResponse
from app.rag_pipeline import ingest_text
from app.text_extraction import UnsupportedFileTypeError, extract_text_from_file
from app.vector_store import (
    CollectionDimensionMismatchError,
    CollectionNotFoundError,
    QdrantUnavailableError,
    delete_chunks_by_filter,
    delete_collection,
    get_collection_info,
)

router = APIRouter(prefix="/documents", tags=["Documents"])


def _raise_storage_http_error(exc: Exception) -> None:
    if isinstance(exc, CollectionDimensionMismatchError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, QdrantUnavailableError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise exc


def _extract_or_raise(content: bytes, filename: str) -> tuple[str, str]:
    try:
        return extract_text_from_file(content, filename)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"ไม่สามารถอ่านข้อความจากไฟล์ '{filename}' ได้: {exc}"
        ) from exc


def _parse_metadata(metadata: str | None) -> dict:
    if not metadata:
        return {}

    try:
        parsed = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="metadata ต้องเป็น JSON object"
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="metadata ต้องเป็น JSON object")

    normalized = {}
    for key, value in parsed.items():
        if not isinstance(value, (str, int, float, bool)):
            raise HTTPException(
                status_code=400,
                detail="metadata values ต้องเป็น string, number หรือ boolean",
            )
        normalized[str(key)] = value
    return normalized


@router.post(
    "/extract-text", response_model=ExtractTextResponse, summary="แปลงไฟล์เป็นข้อความ"
)
async def extract_text(
    file: UploadFile = File(..., description="ไฟล์ .txt, .pdf หรือ .docx"),
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="ต้องส่งไฟล์ผ่าน multipart/form-data โดยใช้ field ชื่อ 'file'",
        )

    content = await file.read()
    text, file_type = _extract_or_raise(content, file.filename)

    if not text.strip():
        raise HTTPException(status_code=400, detail="ไม่พบข้อความในไฟล์")

    return ExtractTextResponse(
        source=file.filename,
        file_type=file_type,
        text=text,
        characters=len(text),
    )


@router.post(
    "/upload-and-ingest",
    response_model=IngestResponse,
    summary="อัปโหลด .txt/.pdf/.docx แล้ว embed เข้า Qdrant",
)
async def upload_and_ingest(
    file: UploadFile | None = File(
        None, description="ไฟล์ .txt, .pdf หรือ .docx ที่ต้องการ ingest"
    ),
    collection_name: str | None = None,
    metadata: str | None = Form(
        None, description='JSON object ของ metadata เช่น {"course_id":"c1"}'
    ),
):
    if file is None or not file.filename:
        raise HTTPException(
            status_code=400,
            detail="ต้องส่งไฟล์ผ่าน multipart/form-data โดยใช้ field ชื่อ 'file'",
        )

    content = await file.read()
    text, file_type = _extract_or_raise(content, file.filename)

    if not text.strip():
        raise HTTPException(
            status_code=400, detail="ไฟล์ว่างเปล่าหรือไม่พบข้อความที่ extract ได้"
        )

    parsed_metadata = _parse_metadata(metadata)
    parsed_metadata["file_type"] = file_type
    try:
        stored, collection = ingest_text(
            text=text,
            source=file.filename,
            collection_name=collection_name,
            metadata=parsed_metadata,
        )
    except (CollectionDimensionMismatchError, QdrantUnavailableError) as exc:
        _raise_storage_http_error(exc)

    return IngestResponse(
        message=f"Ingest สำเร็จ! เก็บ {stored} chunks จากไฟล์ '{file.filename}'",
        chunks_stored=stored,
        collection=collection,
        source=file.filename,
        metadata=parsed_metadata,
    )


@router.post(
    "/ingest-text",
    response_model=IngestResponse,
    summary="ส่งข้อความตรงๆ แล้ว embed เข้า Qdrant",
)
async def ingest_raw_text(
    body: IngestRequest,
    text: str = "",
    collection_name: str | None = None,
):
    raw_text = body.text or text
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="text ว่างเปล่า")

    try:
        stored, collection = ingest_text(
            text=raw_text,
            source=body.source_name or "raw_input",
            collection_name=collection_name or body.collection_name,
            metadata=body.metadata,
        )
    except (CollectionDimensionMismatchError, QdrantUnavailableError) as exc:
        _raise_storage_http_error(exc)

    return IngestResponse(
        message=f"Ingest สำเร็จ! เก็บ {stored} chunks",
        chunks_stored=stored,
        collection=collection,
        source=body.source_name or "raw_input",
        metadata=body.metadata,
    )


@router.get("/collection/{collection_name}", summary="ดูข้อมูล collection")
async def collection_info(collection_name: str):
    try:
        info = get_collection_info(collection_name)
        return info
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/chunks", summary="ลบ chunks ใน Qdrant ของ document หนึ่งๆ")
async def delete_document_chunks(
    collection_name: str = Query(..., description="ชื่อ Qdrant collection"),
    document_id: str = Query(..., description="document_id ที่ต้องการลบ chunks"),
):
    """ลบ points ทั้งหมดใน Qdrant ที่มี document_id ตรงกัน"""
    try:
        delete_chunks_by_filter(collection_name, {"document_id": document_id})
        return {
            "message": f"ลบ chunks ของ document '{document_id}' ออกจาก '{collection_name}' สำเร็จ"
        }
    except CollectionNotFoundError:
        # collection ไม่มีอยู่ = ไม่มี chunks อยู่แล้ว ไม่ถือว่า error
        return {"message": f"Collection '{collection_name}' ไม่มีอยู่ — ข้ามการลบ"}
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/collection/{collection_name}", summary="ลบ collection")
async def remove_collection(collection_name: str):
    try:
        delete_collection(collection_name)
        return {"message": f"ลบ collection '{collection_name}' สำเร็จ"}
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
