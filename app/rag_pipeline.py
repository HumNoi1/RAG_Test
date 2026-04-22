import json
import logging
import re

from app.config import get_settings
from app.embeddings import embed_query, embed_texts
from app.models import (
    GradeEvidence,
    GradeRequest,
    GradeResponse,
    MetadataValue,
    RetrievedChunk,
    RubricCriterionScore,
)
from app.vector_store import search_similar, upsert_chunks

logger = logging.getLogger(__name__)


class MissingLLMApiKeyError(RuntimeError):
    """Raised when the configured LLM provider has no API key."""


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    แบ่งข้อความเป็น chunks โดยพยายามตัดที่ขอบประโยค/ย่อหน้า
    รองรับทั้งภาษาไทยและ ENG
    """
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            sentences = re.split(r"(?<=[.!?ๆฯ])\s+", para)
            for sentence in sentences:
                if len(current) + len(sentence) <= chunk_size:
                    current += (" " if current else "") + sentence
                else:
                    if current:
                        chunks.append(current.strip())
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
    metadata: dict[str, MetadataValue] | None = None,
) -> tuple[int, str]:
    """
    Pipeline: text → chunks → embeddings → Qdrant
    Returns (chunks_stored, collection_name)
    """
    settings = get_settings()
    collection = collection_name or settings.qdrant_collection

    chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    logger.info("Text split into %s chunks from '%s'", len(chunks), source)

    if not chunks:
        return 0, collection

    embeddings = embed_texts(chunks)
    stored = upsert_chunks(collection, chunks, embeddings, source, metadata)

    return stored, collection


def retrieve(
    query: str,
    collection_name: str | None = None,
    top_k: int | None = None,
    score_threshold: float = 0.0,
    metadata_filters: dict[str, MetadataValue] | None = None,
) -> list[RetrievedChunk]:
    """
    Pipeline: query → embedding → Qdrant search → RetrievedChunk list
    """
    settings = get_settings()
    collection = collection_name or settings.qdrant_collection
    k = top_k or settings.top_k

    query_vector = embed_query(query)
    results = search_similar(
        collection,
        query_vector,
        k,
        score_threshold,
        metadata_filters,
    )

    return [_build_retrieved_chunk(result.payload, result.score) for result in results]


def _build_retrieved_chunk(payload: dict, score: float) -> RetrievedChunk:
    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"text", "source", "chunk_index"}
        and isinstance(value, (str, int, float, bool))
    }
    return RetrievedChunk(
        text=payload["text"],
        score=round(score, 4),
        source=payload.get("source", "unknown"),
        chunk_index=payload.get("chunk_index", -1),
        metadata=metadata,
    )


def build_context(chunks: list[RetrievedChunk]) -> str:
    """รวม chunks เป็น context string สำหรับส่งให้ LLM"""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        metadata_text = ""
        if chunk.metadata:
            metadata_text = f", metadata: {json.dumps(chunk.metadata, ensure_ascii=False)}"
        parts.append(
            f"[{i}] (source: {chunk.source}, chunk_index: {chunk.chunk_index}, score: {chunk.score}{metadata_text})\n{chunk.text}"
        )
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


def grade_submission(
    request: GradeRequest,
) -> GradeResponse:
    chunks = retrieve(
        query=request.submission_text,
        collection_name=request.collection_name,
        top_k=request.top_k,
        score_threshold=request.score_threshold,
        metadata_filters=request.metadata_filters,
    )

    if not chunks:
        max_score = round(sum(item.max_score for item in request.rubric), 4)
        return GradeResponse(
            proposed_total_score=0.0,
            max_score=max_score,
            student_reason="ไม่พบเอกสารประกอบการสอนที่เกี่ยวข้องเพียงพอสำหรับใช้ตรวจงาน",
            internal_reason="No relevant knowledge chunks were retrieved for this submission.",
            rubric_breakdown=[
                RubricCriterionScore(
                    criterion_name=item.criterion_name,
                    score=0.0,
                    max_score=item.max_score,
                    reason="ไม่มีข้อมูลประกอบเพียงพอสำหรับประเมินเกณฑ์นี้",
                )
                for item in request.rubric
            ],
            evidence=[],
            retrieved_chunks=[],
            has_llm_response=False,
        )

    score_payload, model_name = grade_with_llm(request, chunks)
    max_score = round(sum(item.max_score for item in request.rubric), 4)

    rubric_breakdown = [
        RubricCriterionScore(
            criterion_name=item["criterion_name"],
            score=float(item["score"]),
            max_score=float(item["max_score"]),
            reason=item["reason"],
        )
        for item in score_payload["rubric_breakdown"]
    ]

    evidence = []
    for item in score_payload.get("evidence", []):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        evidence.append(
            GradeEvidence(
                source=item.get("source", "unknown"),
                chunk_index=int(item.get("chunk_index", -1)),
                quote=item.get("quote", ""),
                relevance_score=(
                    float(item["relevance_score"])
                    if item.get("relevance_score") is not None
                    else None
                ),
                metadata={
                    key: value
                    for key, value in metadata.items()
                    if isinstance(value, (str, int, float, bool))
                },
            )
        )

    proposed_total_score = round(float(score_payload["proposed_total_score"]), 4)
    proposed_total_score = max(0.0, min(proposed_total_score, max_score))

    return GradeResponse(
        proposed_total_score=proposed_total_score,
        max_score=max_score,
        student_reason=score_payload["student_reason"],
        internal_reason=score_payload["internal_reason"],
        rubric_breakdown=rubric_breakdown,
        evidence=evidence,
        retrieved_chunks=chunks,
        model_used=model_name,
        has_llm_response=True,
    )


def grade_with_llm(
    request: GradeRequest,
    chunks: list[RetrievedChunk],
) -> tuple[dict, str]:
    from groq import Groq

    settings = get_settings()
    if not settings.groq_api_key:
        raise MissingLLMApiKeyError("GROQ_API_KEY not set")

    client = Groq(api_key=settings.groq_api_key)
    context = build_context(chunks)
    rubric_json = json.dumps([item.model_dump() for item in request.rubric], ensure_ascii=False)
    max_score = round(sum(item.max_score for item in request.rubric), 4)

    system_prompt = (
        "You are an internal grading assistant. Grade the student submission using ONLY the provided "
        "course-material context and rubric. Output valid JSON only. Keep student_reason high-level and "
        "do not expose hidden rubric internals or retrieval mechanics."
    )

    user_prompt = (
        f"Assignment title: {request.assignment_title or 'N/A'}\n"
        f"Assignment instructions: {request.assignment_instructions or 'N/A'}\n"
        f"Maximum total score: {max_score}\n"
        f"Rubric JSON: {rubric_json}\n\n"
        f"Retrieved course-material context:\n{context}\n\n"
        f"Student submission:\n{request.submission_text}\n\n"
        "Return a JSON object with keys: proposed_total_score, student_reason, internal_reason, "
        "rubric_breakdown, evidence. rubric_breakdown must be an array of objects with "
        "criterion_name, score, max_score, reason. evidence must be an array of objects with source, "
        "chunk_index, quote, relevance_score, metadata."
    )

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    normalized = _normalize_grade_payload(parsed, request)
    model_name = response.model or settings.llm_model
    return normalized, model_name


def _normalize_grade_payload(payload: dict, request: GradeRequest) -> dict:
    rubric_by_name = {item.criterion_name: item for item in request.rubric}
    returned_breakdown: dict[str, dict] = {}

    for rubric_item in payload.get("rubric_breakdown", []):
        if not isinstance(rubric_item, dict):
            continue
        name = str(rubric_item.get("criterion_name", "")).strip()
        if name not in rubric_by_name:
            continue

        rubric = rubric_by_name[name]
        score = float(rubric_item.get("score", 0.0))
        score = max(0.0, min(score, rubric.max_score))
        returned_breakdown[name] = {
            "criterion_name": name,
            "score": round(score, 4),
            "max_score": rubric.max_score,
            "reason": str(rubric_item.get("reason", "")).strip()
            or "No reason provided.",
        }

    normalized_breakdown = []
    total_score = 0.0
    for rubric in request.rubric:
        normalized_item = returned_breakdown.get(rubric.criterion_name)
        if normalized_item is None:
            normalized_item = {
                "criterion_name": rubric.criterion_name,
                "score": 0.0,
                "max_score": rubric.max_score,
                "reason": "No score returned for this criterion.",
            }
        total_score += float(normalized_item["score"])
        normalized_breakdown.append(normalized_item)

    total_score = round(total_score, 4)
    max_score = round(sum(item.max_score for item in request.rubric), 4)
    total_score = max(0.0, min(total_score, max_score))

    normalized_evidence = []
    for item in payload.get("evidence", []):
        if not isinstance(item, dict):
            continue
        normalized_evidence.append(
            {
                "source": str(item.get("source", "unknown")),
                "chunk_index": int(item.get("chunk_index", -1)),
                "quote": str(item.get("quote", "")).strip(),
                "relevance_score": (
                    float(item["relevance_score"])
                    if item.get("relevance_score") is not None
                    else None
                ),
                "metadata": item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
            }
        )

    return {
        "proposed_total_score": total_score,
        "student_reason": str(payload.get("student_reason", "")).strip()
        or "งานชิ้นนี้ถูกประเมินจากเอกสารประกอบการสอนและเกณฑ์ที่กำหนด",
        "internal_reason": str(payload.get("internal_reason", "")).strip()
        or "Structured grading completed from retrieved course-material context.",
        "rubric_breakdown": normalized_breakdown,
        "evidence": normalized_evidence,
    }
