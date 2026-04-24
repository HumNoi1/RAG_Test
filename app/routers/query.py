from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models import RAGRequest, RAGResponse, SearchRequest, SearchResponse
from app.rag_pipeline import (
    MissingLLMApiKeyError,
    rag_with_llm,
    rag_with_llm_stream,
    retrieve,
)
from app.vector_store import (
    CollectionDimensionMismatchError,
    CollectionNotFoundError,
    QdrantUnavailableError,
)

router = APIRouter(prefix="/query", tags=["Query & RAG"])


async def _retrieve_or_raise(
    query: str,
    collection_name: str | None,
    top_k: int | None,
    score_threshold: float,
    metadata_filters: dict,
):
    try:
        return await retrieve(
            query=query,
            collection_name=collection_name,
            top_k=top_k,
            score_threshold=score_threshold,
            metadata_filters=metadata_filters,
        )
    except CollectionDimensionMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _format_retrieved_chunks(chunks) -> str:
    return "\n\n".join(
        f"[{i + 1}] Score: {chunk.score:.4f} | Source: {chunk.source} | Chunk: {chunk.chunk_index}\n{chunk.text}"
        for i, chunk in enumerate(chunks)
    )


@router.post(
    "/search", response_model=SearchResponse, summary="ค้นหา chunks ที่เกี่ยวข้องจาก Qdrant"
)
async def semantic_search(body: SearchRequest):
    chunks = await _retrieve_or_raise(
        query=body.query,
        collection_name=body.collection_name,
        top_k=body.top_k,
        score_threshold=body.score_threshold,
        metadata_filters=body.metadata_filters,
    )

    return SearchResponse(
        query=body.query,
        results=chunks,
        total_found=len(chunks),
    )


@router.post("/rag", response_model=RAGResponse, summary="RAG: ค้นหา + LLM สร้างคำตอบ")
async def rag_query(body: RAGRequest):
    chunks = await _retrieve_or_raise(
        query=body.query,
        collection_name=body.collection_name,
        top_k=body.top_k,
        score_threshold=body.score_threshold,
        metadata_filters=body.metadata_filters,
    )

    if not chunks:
        return RAGResponse(
            query=body.query,
            answer="ไม่พบข้อมูลที่เกี่ยวข้องใน vector database",
            retrieved_chunks=[],
            has_llm_response=False,
        )

    try:
        answer, model_name = await rag_with_llm(body.query, chunks)
        return RAGResponse(
            query=body.query,
            answer=answer,
            retrieved_chunks=chunks,
            model_used=model_name,
            has_llm_response=True,
        )
    except MissingLLMApiKeyError:
        return RAGResponse(
            query=body.query,
            answer=(
                "⚠️ ไม่มี GROQ_API_KEY — แสดงเฉพาะ Retrieved Chunks:\n\n"
                + _format_retrieved_chunks(chunks)
            ),
            retrieved_chunks=chunks,
            has_llm_response=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(exc)}") from exc


@router.post("/rag/stream", summary="RAG Streaming: ค้นหา + LLM streaming คำตอบ")
async def rag_query_stream(body: RAGRequest):
    chunks = await _retrieve_or_raise(
        query=body.query,
        collection_name=body.collection_name,
        top_k=body.top_k,
        score_threshold=body.score_threshold,
        metadata_filters=body.metadata_filters,
    )

    if not chunks:
        return {"error": "ไม่พบข้อมูลที่เกี่ยวข้องใน vector database"}

    async def event_generator():
        try:
            async for content, model_name in rag_with_llm_stream(body.query, chunks):
                yield f"data: {content}\n\n"
            yield f"data: [DONE]\n\n"
        except MissingLLMApiKeyError:
            yield f"data: ข้อผิดพลาด: ไม่มี GROQ_API_KEY\n\n"
        except Exception as exc:
            yield f"data: ข้อผิดพลาด: {str(exc)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
