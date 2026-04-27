import asyncio
import json
import logging
import statistics
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.rag_pipeline import ingest_text, rag_with_llm, retrieve
from app.vector_store import (
    CollectionNotFoundError,
    delete_collection,
)

logger = logging.getLogger(__name__)


class EvaluationCase(BaseModel):
    query: str = Field(..., description="คำถามที่ใช้ benchmark")
    mode: Literal["search", "rag"] = "rag"
    expected_sources: list[str] = Field(default_factory=list)
    expected_chunk_indexes: list[int] = Field(default_factory=list)
    expected_answer_keywords: list[str] = Field(default_factory=list)
    min_keyword_coverage: float = 0.6
    should_abstain: bool = False
    top_k: int | None = None
    score_threshold: float | None = None
    notes: str | None = None


class EvaluationCaseResult(BaseModel):
    query: str
    mode: Literal["search", "rag"]
    retrieved_sources: list[str]
    retrieved_chunks: list[dict]
    answer: str | None = None
    llm_model: str | None = None
    answer_skipped_reason: str | None = None
    retrieval_hit: bool | None = None
    recall_at_k: float | None = None
    reciprocal_rank: float | None = None
    keyword_coverage: float | None = None
    answer_correct: bool | None = None
    faithfulness_proxy: bool | None = None
    abstention_correct: bool | None = None
    retrieval_latency_ms: float
    rag_latency_ms: float | None = None


class EvaluationSummary(BaseModel):
    total_cases: int
    retrieval_cases: int
    rag_cases: int
    rag_cases_scored: int
    rag_cases_skipped: int
    hit_at_k: float | None = None
    recall_at_k: float | None = None
    mrr: float | None = None
    answer_correct_rate: float | None = None
    keyword_coverage_avg: float | None = None
    faithfulness_proxy_rate: float | None = None
    abstention_accuracy: float | None = None
    avg_retrieval_latency_ms: float | None = None
    avg_rag_latency_ms: float | None = None


def normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.fmean(values), 4)


def load_dataset(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    with path.open("r", encoding="utf-8") as dataset_file:
        for raw_line in dataset_file:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            cases.append(EvaluationCase.model_validate(payload))

    if not cases:
        raise ValueError(f"Dataset ว่างเปล่า: {path}")

    return cases


def read_text_file(path: Path) -> str:
    raw_bytes = path.read_bytes()
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("tis-620", errors="replace")


async def rebuild_collection(collection_name: str, documents: list[Path]) -> int:
    """ลบ collection เดิมแล้ว re-ingest เอกสารทั้งหมดใหม่ — ใช้กับ evaluation เท่านั้น"""
    try:
        delete_collection(collection_name)
    except CollectionNotFoundError:
        pass

    total_chunks = 0
    for document in documents:
        text = read_text_file(document)
        stored, _ = await ingest_text(
            text=text,
            source=document.name,
            collection_name=collection_name,
        )
        total_chunks += stored
        logger.info("Ingested '%s': %d chunks", document.name, stored)

    return total_chunks


async def run_evaluation_case(
    case: EvaluationCase,
    collection_name: str,
    top_k: int | None,
    score_threshold: float,
) -> EvaluationCaseResult:
    """รัน 1 test case และคืน EvaluationCaseResult พร้อม metrics ครบ"""
    effective_top_k = case.top_k if case.top_k is not None else top_k
    effective_threshold = (
        case.score_threshold if case.score_threshold is not None else score_threshold
    )

    # --- Retrieval ---
    t0 = time.perf_counter()
    chunks = await retrieve(
        query=case.query,
        collection_name=collection_name,
        top_k=effective_top_k,
        score_threshold=effective_threshold,
    )
    retrieval_latency_ms = (time.perf_counter() - t0) * 1000

    retrieved_sources = [chunk.source for chunk in chunks]
    norm_expected = [normalize_text(s) for s in case.expected_sources]

    # --- Retrieval metrics ---
    retrieval_hit: bool | None = None
    recall_at_k: float | None = None
    reciprocal_rank: float | None = None

    if case.expected_sources:
        retrieval_hit = any(
            normalize_text(src) in norm_expected for src in retrieved_sources
        )

        if case.expected_chunk_indexes:
            expected_pairs = set(
                zip(
                    [normalize_text(s) for s in case.expected_sources],
                    case.expected_chunk_indexes,
                )
            )
            matched = sum(
                1
                for chunk in chunks
                if (normalize_text(chunk.source), chunk.chunk_index) in expected_pairs
            )
            recall_at_k = matched / len(expected_pairs) if expected_pairs else 0.0
        else:
            matched_sources = sum(
                1 for src in retrieved_sources if normalize_text(src) in norm_expected
            )
            recall_at_k = matched_sources / len(case.expected_sources)

        reciprocal_rank = 0.0
        for rank, src in enumerate(retrieved_sources, start=1):
            if normalize_text(src) in norm_expected:
                reciprocal_rank = 1.0 / rank
                break

    # --- RAG path ---
    answer: str | None = None
    llm_model: str | None = None
    answer_skipped_reason: str | None = None
    keyword_coverage: float | None = None
    answer_correct: bool | None = None
    faithfulness_proxy: bool | None = None
    abstention_correct: bool | None = None
    rag_latency_ms: float | None = None

    if case.mode == "rag":
        t1 = time.perf_counter()
        try:
            answer, llm_model = await rag_with_llm(case.query, chunks)
            rag_latency_ms = (time.perf_counter() - t1) * 1000

            answer_lower = answer.lower()

            if case.expected_answer_keywords:
                hits = sum(
                    1
                    for kw in case.expected_answer_keywords
                    if kw.lower() in answer_lower
                )
                keyword_coverage = hits / len(case.expected_answer_keywords)
                answer_correct = keyword_coverage >= case.min_keyword_coverage

            faithfulness_proxy = any(
                normalize_text(src) in answer_lower for src in retrieved_sources if src
            )

            if case.should_abstain:
                abstain_markers = ["ไม่มีข้อมูล", "insufficient", "not found"]
                abstention_correct = any(
                    marker in answer_lower for marker in abstain_markers
                )

        except Exception as exc:  # noqa: BLE001
            rag_latency_ms = (time.perf_counter() - t1) * 1000
            answer_skipped_reason = str(exc)
            logger.warning("LLM error for query %r: %s", case.query, exc)

    return EvaluationCaseResult(
        query=case.query,
        mode=case.mode,
        retrieved_sources=retrieved_sources,
        retrieved_chunks=[chunk.model_dump() for chunk in chunks],
        answer=answer,
        llm_model=llm_model,
        answer_skipped_reason=answer_skipped_reason,
        retrieval_hit=retrieval_hit,
        recall_at_k=recall_at_k,
        reciprocal_rank=reciprocal_rank,
        keyword_coverage=keyword_coverage,
        answer_correct=answer_correct,
        faithfulness_proxy=faithfulness_proxy,
        abstention_correct=abstention_correct,
        retrieval_latency_ms=round(retrieval_latency_ms, 2),
        rag_latency_ms=round(rag_latency_ms, 2) if rag_latency_ms is not None else None,
    )


async def run_evaluation(
    cases: list[EvaluationCase],
    collection_name: str,
    top_k: int | None,
    score_threshold: float,
) -> tuple[list[EvaluationCaseResult], EvaluationSummary]:
    """รัน cases ทั้งหมด sequentially และคืน (results, summary)"""
    results: list[EvaluationCaseResult] = []

    for i, case in enumerate(cases, start=1):
        logger.info("Running case %d/%d: %r", i, len(cases), case.query[:60])
        result = await run_evaluation_case(
            case, collection_name, top_k, score_threshold
        )
        results.append(result)

    rag_results = [r for r in results if r.mode == "rag"]
    rag_cases_scored = sum(1 for r in rag_results if r.answer_skipped_reason is None)
    rag_cases_skipped = sum(
        1 for r in rag_results if r.answer_skipped_reason is not None
    )

    summary = EvaluationSummary(
        total_cases=len(results),
        retrieval_cases=len(results),
        rag_cases=len(rag_results),
        rag_cases_scored=rag_cases_scored,
        rag_cases_skipped=rag_cases_skipped,
        hit_at_k=mean_or_none(
            [float(r.retrieval_hit) for r in results if r.retrieval_hit is not None]
        ),
        recall_at_k=mean_or_none(
            [r.recall_at_k for r in results if r.recall_at_k is not None]
        ),
        mrr=mean_or_none(
            [r.reciprocal_rank for r in results if r.reciprocal_rank is not None]
        ),
        answer_correct_rate=mean_or_none(
            [
                float(r.answer_correct)
                for r in rag_results
                if r.answer_correct is not None
            ]
        ),
        keyword_coverage_avg=mean_or_none(
            [r.keyword_coverage for r in rag_results if r.keyword_coverage is not None]
        ),
        faithfulness_proxy_rate=mean_or_none(
            [
                float(r.faithfulness_proxy)
                for r in rag_results
                if r.faithfulness_proxy is not None
            ]
        ),
        abstention_accuracy=mean_or_none(
            [
                float(r.abstention_correct)
                for r in rag_results
                if r.abstention_correct is not None
            ]
        ),
        avg_retrieval_latency_ms=mean_or_none(
            [r.retrieval_latency_ms for r in results]
        ),
        avg_rag_latency_ms=mean_or_none(
            [r.rag_latency_ms for r in rag_results if r.rag_latency_ms is not None]
        ),
    )

    return results, summary


if __name__ == "__main__":
    import argparse

    from app.config import get_settings

    parser = argparse.ArgumentParser(description="RAG offline evaluator")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--documents", nargs="+", type=Path, default=[])
    parser.add_argument("--collection", type=str, default=None)
    parser.add_argument("--top-k", type=int, default=None, dest="top_k")
    parser.add_argument(
        "--score-threshold", type=float, default=0.0, dest="score_threshold"
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    collection_name = args.collection or settings.qdrant_collection

    async def main() -> None:
        if args.documents:
            logger.info(
                "Rebuilding collection '%s' with %d documents...",
                collection_name,
                len(args.documents),
            )
            total = await rebuild_collection(collection_name, args.documents)
            logger.info("Ingested %d total chunks", total)

        cases = load_dataset(args.dataset)
        logger.info("Loaded %d evaluation cases from %s", len(cases), args.dataset)

        results, summary = await run_evaluation(
            cases=cases,
            collection_name=collection_name,
            top_k=args.top_k,
            score_threshold=args.score_threshold,
        )

        print("\n=== Evaluation Summary ===")
        print(summary.model_dump_json(indent=2))

        if args.output:
            output_data = {
                "summary": summary.model_dump(),
                "results": [r.model_dump() for r in results],
            }
            args.output.write_text(
                json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("Results saved to %s", args.output)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(main())
