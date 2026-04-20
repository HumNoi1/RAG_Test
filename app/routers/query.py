from fastapi import APIRouter, HTTPException
from app.models import SearchRequest, SearchResponse, RAGRequest, RAGResponse
from app.rag_pipeline import retrieve, rag_with_llm
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query & RAG"])


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
    try:
        chunks = retrieve(
            query=body.query,
            collection_name=body.collection_name,
            top_k=body.top_k,
            score_threshold=body.score_threshold,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")

    return SearchResponse(
        query=body.query,
        results=chunks,
        total_found=len(chunks),
    )


@router.post("/rag", response_model=RAGResponse, summary="RAG: ค้นหา + LLM สร้างคำตอบ")
async def rag_query(body: RAGRequest):
    """
    **RAG Pipeline**: ค้นหา relevant chunks แล้วส่งให้ LLM สร้างคำตอบ

    - ถ้ามี `OPENAI_API_KEY` → ใช้ GPT-4o-mini ตอบ
    - ถ้าไม่มี key → return เฉพาะ retrieved chunks (no LLM)

    ดูได้ว่า:
    1. Embedding ดึงข้อมูลอะไรออกมา (retrieved_chunks)
    2. LLM สร้างคำตอบจาก context อย่างไร (answer)
    """
    try:
        chunks = retrieve(
            query=body.query,
            collection_name=body.collection_name,
            top_k=body.top_k,
            score_threshold=body.score_threshold,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval error: {str(e)}")

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
    except ValueError:
        # ไม่มี OpenAI key — return แค่ retrieved chunks
        context_summary = "\n\n".join(
            f"[{i+1}] Score: {c.score:.4f} | Source: {c.source}\n{c.text}"
            for i, c in enumerate(chunks)
        )
        return RAGResponse(
            query=body.query,
            answer=(
                "⚠️ ไม่มี OPENAI_API_KEY — แสดงเฉพาะ Retrieved Chunks:\n\n"
                + context_summary
            ),
            retrieved_chunks=chunks,
            has_llm_response=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")
