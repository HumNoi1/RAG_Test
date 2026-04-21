from fastapi import APIRouter, UploadFile, File, HTTPException
from app.models import IngestRequest, IngestResponse
from app.rag_pipeline import ingest_text
from app.vector_store import (
    CollectionDimensionMismatchError,
    CollectionNotFoundError,
    QdrantUnavailableError,
    delete_collection,
    get_collection_info,
)

router = APIRouter(prefix="/documents", tags=["Documents"])


def _decode_text_content(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("tis-620", errors="replace")


def _raise_storage_http_error(exc: Exception) -> None:
    if isinstance(exc, CollectionDimensionMismatchError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, QdrantUnavailableError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise exc


@router.post("/upload-and-ingest", response_model=IngestResponse, summary="อัปโหลด .txt แล้ว embed เข้า Qdrant")
async def upload_and_ingest(
    file: UploadFile | None = File(None, description="ไฟล์ .txt ที่ต้องการ ingest"),
    collection_name: str | None = None,
):
    """
    อัปโหลดไฟล์ .txt → ตัด chunks → embed → บันทึกเข้า Qdrant

    - **file**: ไฟล์ .txt (รองรับ UTF-8)
    - **collection_name**: ชื่อ collection (optional, ใช้ค่า default จาก config ถ้าไม่ระบุ)
    """
    if file is None or not file.filename:
        raise HTTPException(
            status_code=400,
            detail="ต้องส่งไฟล์ผ่าน multipart/form-data โดยใช้ field ชื่อ 'file'",
        )

    if not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="รองรับเฉพาะไฟล์ .txt เท่านั้น")

    content = await file.read()
    text = _decode_text_content(content)

    if not text.strip():
        raise HTTPException(status_code=400, detail="ไฟล์ว่างเปล่า")

    try:
        stored, collection = ingest_text(
            text=text,
            source=file.filename,
            collection_name=collection_name,
        )
    except (CollectionDimensionMismatchError, QdrantUnavailableError) as exc:
        _raise_storage_http_error(exc)

    return IngestResponse(
        message=f"Ingest สำเร็จ! เก็บ {stored} chunks จากไฟล์ '{file.filename}'",
        chunks_stored=stored,
        collection=collection,
        source=file.filename,
    )


@router.post("/ingest-text", response_model=IngestResponse, summary="ส่งข้อความตรงๆ แล้ว embed เข้า Qdrant")
async def ingest_raw_text(
    body: IngestRequest,
    text: str = "",
    collection_name: str | None = None,
):
    """ส่ง raw text ผ่าน body แล้ว ingest เข้า Qdrant"""
    raw_text = body.text or text
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="text ว่างเปล่า")

    try:
        stored, collection = ingest_text(
            text=raw_text,
            source=body.source_name or "raw_input",
            collection_name=collection_name or body.collection_name,
        )
    except (CollectionDimensionMismatchError, QdrantUnavailableError) as exc:
        _raise_storage_http_error(exc)

    return IngestResponse(
        message=f"Ingest สำเร็จ! เก็บ {stored} chunks",
        chunks_stored=stored,
        collection=collection,
        source=body.source_name or "raw_input",
    )


@router.get("/collection/{collection_name}", summary="ดูข้อมูล collection")
async def collection_info(collection_name: str):
    """ดูสถิติของ collection ใน Qdrant"""
    try:
        info = get_collection_info(collection_name)
        return info
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/collection/{collection_name}", summary="ลบ collection")
async def remove_collection(collection_name: str):
    """ลบ collection และข้อมูลทั้งหมดออกจาก Qdrant"""
    try:
        delete_collection(collection_name)
        return {"message": f"ลบ collection '{collection_name}' สำเร็จ"}
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
