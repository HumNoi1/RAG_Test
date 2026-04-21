from fastapi import APIRouter, HTTPException
from app.models import SearchRequest, SearchResponse, RAGRequest, RAGResponse
from app.rag_pipeline import MissingLLMApiKeyError, rag_with_llm, retrieve
from app.vector_store import (
    CollectionDimensionMismatchError,
    CollectionNotFoundError,
    QdrantUnavailableError,
)

router = APIRouter(prefix="/query", tags=["Query & RAG"])


def _retrieve_or_raise(
    query: str,
    collection_name: str | None,
    top_k: int | None,
    score_threshold: float,
):
    try:
        return retrieve(
            query=query,
            collection_name=collection_name,
            top_k=top_k,
            score_threshold=score_threshold,
        )
    except CollectionDimensionMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _format_retrieved_chunks(chunks) -> str:
    return "\n\n".join(
        f"[{i+1}] Score: {chunk.score:.4f} | Source: {chunk.source}\n{chunk.text}"
        for i, chunk in enumerate(chunks)
    )


@router.post("/search", response_model=SearchResponse, summary="ค้นหา chunks ที่เกี่ยวข้องจาก Qdrant")
async def semantic_search(body: SearchRequest):
    """
    **Semantic Search**: embed query แล้วค้นหา chunks ที่ใกล้เคียงที่สุดใน Qdrant

    Response ประกอบด้วย:
    - **text**: เนื้อหาของ chunk
    - **score**: คะแนน cosine similarity (0.0 – 1.0, สูง = ใกล้เคียงมาก)
    - **source**: ชื่อไฟล์ต้นทาง
    - **chunk_index**: ลำดับของ chunk ในเอกสาร
    """
    chunks = _retrieve_or_raise(
        query=body.query,
        collection_name=body.collection_name,
        top_k=body.top_k,
        score_threshold=body.score_threshold,
    )

    return SearchResponse(
        query=body.query,
        results=chunks,
        total_found=len(chunks),
    )


@router.post("/rag", response_model=RAGResponse, summary="RAG: ค้นหา + LLM สร้างคำตอบ")
async def rag_query(body: RAGRequest):
    """
    **RAG Pipeline**: ค้นหา relevant chunks แล้วส่งให้ LLM สร้างคำตอบ

    - ถ้ามี `GROQ_API_KEY` → ใช้ Groq ตอบ
    - ถ้าไม่มี key → return เฉพาะ retrieved chunks (no LLM)

    ดูได้ว่า:
    1. Embedding ดึงข้อมูลอะไรออกมา (retrieved_chunks)
    2. LLM สร้างคำตอบจาก context อย่างไร (answer)
    """
    chunks = _retrieve_or_raise(
        query=body.query,
        collection_name=body.collection_name,
        top_k=body.top_k,
        score_threshold=body.score_threshold,
    )

    if not chunks:
        return RAGResponse(
            query=body.query,
            answer="ไม่พบข้อมูลที่เกี่ยวข้องใน vector database",
            retrieved_chunks=[],
            has_llm_response=False,
        )

    # ลอง LLM ถ้ามี key
    try:
        answer, model_name = rag_with_llm(body.query, chunks)
        return RAGResponse(
            query=body.query,
            answer=answer,
            retrieved_chunks=chunks,
            model_used=model_name,
            has_llm_response=True,
        )
    except MissingLLMApiKeyError:
        # ไม่มี Groq API key — return แค่ retrieved chunks
        return RAGResponse(
            query=body.query,
            answer=(
                "⚠️ ไม่มี GROQ_API_KEY — แสดงเฉพาะ Retrieved Chunks:\n\n"
                + _format_retrieved_chunks(chunks)
            ),
            retrieved_chunks=chunks,
            has_llm_response=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")
