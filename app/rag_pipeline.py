from app.config import get_settings
from app.embeddings import embed_texts, embed_query
from app.vector_store import upsert_chunks, search_similar
from app.models import RetrievedChunk
import re
import logging

logger = logging.getLogger(__name__)


class MissingLLMApiKeyError(RuntimeError):
    """Raised when the configured LLM provider has no API key."""


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    แบ่งข้อความเป็น chunks โดยพยายามตัดที่ขอบประโยค/ย่อหน้า
    รองรับทั้งภาษาไทยและ ENG
    """
    # ล้างช่องว่างซ้ำและ normalize line endings
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # แบ่งที่ย่อหน้าก่อน
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        # ถ้าย่อหน้าเดียวยาวกว่า chunk_size ให้ตัดอีกครั้ง
        if len(para) > chunk_size:
            # ตัดที่ประโยค (. ! ? ฯ ๆ)
            sentences = re.split(r"(?<=[.!?ๆฯ])\s+", para)
            for sentence in sentences:
                if len(current) + len(sentence) <= chunk_size:
                    current += (" " if current else "") + sentence
                else:
                    if current:
                        chunks.append(current.strip())
                    # overlap: เอา N ตัวอักษรสุดท้ายมาต่อ
                    overlap_text = current[-chunk_overlap:] if chunk_overlap > 0 else ""
                    current = overlap_text + sentence
        else:
            if len(current) + len(para) + 2 <= chunk_size:
                current += ("\n\n" if current else "") + para
            else:
                if current:
                    chunks.append(current.strip())
                overlap_text = current[-chunk_overlap:] if chunk_overlap > 0 else ""
                current = overlap_text + para

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c]


def ingest_text(
    text: str,
    source: str,
    collection_name: str | None = None,
) -> tuple[int, str]:
    """
    Pipeline: text → chunks → embeddings → Qdrant
    Returns (chunks_stored, collection_name)
    """
    settings = get_settings()
    collection = collection_name or settings.qdrant_collection

    chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    logger.info(f"Text split into {len(chunks)} chunks from '{source}'")

    if not chunks:
        return 0, collection

    embeddings = embed_texts(chunks)
    stored = upsert_chunks(collection, chunks, embeddings, source)

    return stored, collection


def retrieve(
    query: str,
    collection_name: str | None = None,
    top_k: int | None = None,
    score_threshold: float = 0.0,
) -> list[RetrievedChunk]:
    """
    Pipeline: query → embedding → Qdrant search → RetrievedChunk list
    """
    settings = get_settings()
    collection = collection_name or settings.qdrant_collection
    k = top_k or settings.top_k

    query_vector = embed_query(query)
    results = search_similar(collection, query_vector, k, score_threshold)

    return [
        RetrievedChunk(
            text=r.payload["text"],
            score=round(r.score, 4),
            source=r.payload.get("source", "unknown"),
            chunk_index=r.payload.get("chunk_index", -1),
        )
        for r in results
    ]


def build_context(chunks: list[RetrievedChunk]) -> str:
    """รวม chunks เป็น context string สำหรับส่งให้ LLM"""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        parts.append(f"[{i}] (source: {chunk.source}, score: {chunk.score})\n{chunk.text}")
    return "\n\n---\n\n".join(parts)


def rag_with_llm(
    query: str,
    chunks: list[RetrievedChunk],
) -> tuple[str, str]:
    """
    ส่ง retrieved chunks + query ไปให้ Groq แล้ว return (answer, model_name)
    """
    from groq import Groq

    settings = get_settings()
    if not settings.groq_api_key:
        raise MissingLLMApiKeyError("GROQ_API_KEY not set")

    client = Groq(api_key=settings.groq_api_key)
    context = build_context(chunks)

    system_prompt = (
        "คุณเป็นผู้ช่วยที่ฉลาดและตอบคำถามโดยอิงจากข้อมูลที่ให้มาเท่านั้น "
        "ตอบเป็นภาษาเดียวกับคำถาม หากข้อมูลไม่เพียงพอให้บอกว่าไม่มีข้อมูลเพียงพอ\n\n"
        "You are a smart assistant that answers questions based ONLY on the provided context. "
        "Reply in the same language as the question. If the context is insufficient, say so."
    )

    user_prompt = f"Context:\n{context}\n\nQuestion: {query}"

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    answer = response.choices[0].message.content
    model_name = response.model or settings.llm_model
    return answer, model_name
