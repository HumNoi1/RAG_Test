import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.embeddings import get_embedding_model
from app.routers import documents, grading, query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # โหลด embedding model ตอน startup เพื่อไม่ให้ช้าตอน request แรก
    logger.info("🚀 Starting RAG Demo API...")
    get_embedding_model()
    logger.info("✅ Embedding model loaded and ready!")
    yield
    logger.info("👋 Shutting down RAG Demo API")


settings = get_settings()

app = FastAPI(
    title="🔍 RAG Demo API",
    description="""
## RAG (Retrieval-Augmented Generation) Demo

รองรับ **ภาษาไทย** และ **English**

### Workflow
1. **อัปโหลดไฟล์** `.txt`, `.pdf`, `.docx` ผ่าน `/documents/upload-and-ingest`
2. **ค้นหา** ด้วย semantic search ผ่าน `/query/search`
3. **RAG** รับคำตอบจาก LLM ผ่าน `/query/rag`
4. **Grading** ตรวจงานและคืนคะแนนเสนอผ่าน `/grading/grade-submission`

### Embedding Model
`BAAI/bge-m3` — multilingual embedding model (1024 dim)

### Vector Database
Qdrant — running in Docker
    """,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(documents.router)
app.include_router(grading.router)
app.include_router(query.router)


@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "RAG Demo API is running! 🚀",
        "docs": "/docs",
        "embedding_model": settings.embedding_model,
        "llm_provider": "groq",
        "llm_model": settings.llm_model,
        "qdrant": f"{settings.qdrant_host}:{settings.qdrant_port}",
        "collection": settings.qdrant_collection,
    }


@app.get("/health", tags=["Health"])
async def health():
    from app.vector_store import get_async_qdrant_client

    try:
        client = get_async_qdrant_client()
        response = await client.get_collections()
        collections = [c.name for c in response.collections]
        return {
            "status": "healthy",
            "qdrant": "connected",
            "collections": collections,
        }
    except Exception as e:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "qdrant": f"error: {str(e)}"},
        )
