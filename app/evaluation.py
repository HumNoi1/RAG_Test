import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.rag_pipeline import MissingLLMApiKeyError, ingest_text, rag_with_llm, retrieve
from app.vector_store import (
    CollectionNotFoundError,
    QdrantUnavailableError,
    delete_collection,
)


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


def rebuild_collection(collection_name: str, documents: list[Path]) -> int:
    try:
        delete_collection(collection_name)
    except CollectionNotFoundError:
        pass

    total_chunks = 0
    for document in documents:
        text = read_text_file(document)
        stored, _ = ingest_text(
            text=text,
            source=document.name,
            collection_name=collection_name,
        )
        total_chunks += stored
    return total_chunks


def find_relevant_positions(case: EvaluationCase, retrieved_chunks: list[dict]) -> list[int]:
    positions: list[int] = []
    for index, chunk in enumerate(retrieved_chunks, 1):
        source_match = (
            not case.expected_sources or chunk["source"] in case.expected_sources
        )
        chunk_match = (
            not case.expected_chunk_indexes
            or chunk["chunk_index"] in case.expected_chunk_indexes
        )
        if source_match and chunk_match:
            positions.append(index)
    return positions


def calculate_retrieval_metrics(
    case: EvaluationCase,
    retrieved_chunks: list[dict],
) -> tuple[bool | None, float | None, float | None]:
    if case.should_abstain and not case.expected_sources and not case.expected_chunk_indexes:
        return None, None, None

    relevant_positions = find_relevant_positions(case, retrieved_chunks)
    if not relevant_positions:
        return False, 0.0, 0.0

    if case.expected_chunk_indexes:
        found_targets = {
            chunk["chunk_index"]
            for chunk in retrieved_chunks
            if chunk["chunk_index"] in case.expected_chunk_indexes
            and (
                not case.expected_sources or chunk["source"] in case.expected_sources
            )
        }
        total_targets = len(set(case.expected_chunk_indexes))
    else:
        found_targets = {
            chunk["source"]
            for chunk in retrieved_chunks
            if chunk["source"] in case.expected_sources
        }
        total_targets = len(set(case.expected_sources))

    recall_at_k = len(found_targets) / total_targets if total_targets else None
    reciprocal_rank = 1 / min(relevant_positions)

    return True, round(recall_at_k, 4), round(reciprocal_rank, 4)


def contains_abstention_signal(answer: str) -> bool:
    normalized = normalize_text(answer)
    phrases = [
        "ไม่มีข้อมูลเพียงพอ",
        "ไม่พบข้อมูลที่เกี่ยวข้อง",
        "ข้อมูลไม่เพียงพอ",
        "insufficient",
        "not enough information",
        "i don't have enough information",
    ]
    return any(phrase in normalized for phrase in phrases)


def calculate_answer_metrics(
    case: EvaluationCase,
    answer: str | None,
    retrieval_hit: bool | None,
) -> tuple[float | None, bool | None, bool | None, bool | None]:
    if case.mode != "rag":
        return None, None, None, None

    if case.should_abstain:
        abstention_correct = contains_abstention_signal(answer or "")
        return None, None, abstention_correct, None

    if answer is None or not case.expected_answer_keywords:
        return None, None, None, None

    normalized_answer = normalize_text(answer)
    matched_keywords = [
        keyword
        for keyword in case.expected_answer_keywords
        if normalize_text(keyword) in normalized_answer
    ]
    keyword_coverage = len(matched_keywords) / len(case.expected_answer_keywords)
    answer_correct = keyword_coverage >= case.min_keyword_coverage
    faithfulness_proxy = bool(answer_correct and retrieval_hit)

    return (
        round(keyword_coverage, 4),
        answer_correct,
        None,
        faithfulness_proxy,
    )


def run_case(
    case: EvaluationCase,
    collection_name: str,
    default_top_k: int,
    default_score_threshold: float,
) -> EvaluationCaseResult:
    top_k = case.top_k or default_top_k
    score_threshold = (
        case.score_threshold
        if case.score_threshold is not None
        else default_score_threshold
    )

    retrieval_started = time.perf_counter()
    chunks = retrieve(
        query=case.query,
        collection_name=collection_name,
        top_k=top_k,
        score_threshold=score_threshold,
    )
    retrieval_latency_ms = round((time.perf_counter() - retrieval_started) * 1000, 2)

    retrieved_chunks = [chunk.model_dump() for chunk in chunks]
    retrieval_hit, recall_at_k, reciprocal_rank = calculate_retrieval_metrics(
        case,
        retrieved_chunks,
    )

    answer: str | None = None
    llm_model: str | None = None
    answer_skipped_reason: str | None = None
    rag_latency_ms: float | None = None

    if case.mode == "rag":
        rag_started = time.perf_counter()
        if not chunks:
            answer = "ไม่พบข้อมูลที่เกี่ยวข้องใน vector database"
        else:
            try:
                answer, llm_model = rag_with_llm(case.query, chunks)
            except MissingLLMApiKeyError as exc:
                answer_skipped_reason = str(exc)
        rag_latency_ms = round((time.perf_counter() - rag_started) * 1000, 2)

    (
        keyword_coverage,
        answer_correct,
        abstention_correct,
        faithfulness_proxy,
    ) = calculate_answer_metrics(case, answer, retrieval_hit)

    return EvaluationCaseResult(
        query=case.query,
        mode=case.mode,
        retrieved_sources=[chunk["source"] for chunk in retrieved_chunks],
        retrieved_chunks=retrieved_chunks,
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
        retrieval_latency_ms=retrieval_latency_ms,
        rag_latency_ms=rag_latency_ms,
    )


def build_summary(results: list[EvaluationCaseResult]) -> EvaluationSummary:
    retrieval_hits = [
        1.0 for result in results if result.retrieval_hit is True
    ] + [
        0.0 for result in results if result.retrieval_hit is False
    ]
    recall_values = [
        result.recall_at_k for result in results if result.recall_at_k is not None
    ]
    reciprocal_ranks = [
        result.reciprocal_rank
        for result in results
        if result.reciprocal_rank is not None
    ]
    answer_scores = [
        1.0 for result in results if result.answer_correct is True
    ] + [
        0.0 for result in results if result.answer_correct is False
    ]
    keyword_coverages = [
        result.keyword_coverage
        for result in results
        if result.keyword_coverage is not None
    ]
    faithfulness_scores = [
        1.0 for result in results if result.faithfulness_proxy is True
    ] + [
        0.0 for result in results if result.faithfulness_proxy is False
    ]
    abstention_scores = [
        1.0 for result in results if result.abstention_correct is True
    ] + [
        0.0 for result in results if result.abstention_correct is False
    ]
    retrieval_latencies = [result.retrieval_latency_ms for result in results]
    rag_latencies = [
        result.rag_latency_ms for result in results if result.rag_latency_ms is not None
    ]
    rag_results = [result for result in results if result.mode == "rag"]
    rag_scored = [
        result
        for result in rag_results
        if result.answer_correct is not None or result.abstention_correct is not None
    ]
    rag_skipped = [
        result for result in rag_results if result.answer_skipped_reason is not None
    ]

    return EvaluationSummary(
        total_cases=len(results),
        retrieval_cases=len(results),
        rag_cases=len(rag_results),
        rag_cases_scored=len(rag_scored),
        rag_cases_skipped=len(rag_skipped),
        hit_at_k=mean_or_none(retrieval_hits),
        recall_at_k=mean_or_none(recall_values),
        mrr=mean_or_none(reciprocal_ranks),
        answer_correct_rate=mean_or_none(answer_scores),
        keyword_coverage_avg=mean_or_none(keyword_coverages),
        faithfulness_proxy_rate=mean_or_none(faithfulness_scores),
        abstention_accuracy=mean_or_none(abstention_scores),
        avg_retrieval_latency_ms=mean_or_none(retrieval_latencies),
        avg_rag_latency_ms=mean_or_none(rag_latencies),
    )


def print_summary(summary: EvaluationSummary) -> None:
    print(f"Cases: {summary.total_cases}")
    print(f"Hit@k: {summary.hit_at_k}")
    print(f"Recall@k: {summary.recall_at_k}")
    print(f"MRR: {summary.mrr}")
    print(f"Answer correctness: {summary.answer_correct_rate}")
    print(f"Faithfulness proxy: {summary.faithfulness_proxy_rate}")
    print(f"Abstention accuracy: {summary.abstention_accuracy}")
    print(f"Avg retrieval latency (ms): {summary.avg_retrieval_latency_ms}")
    print(f"Avg rag latency (ms): {summary.avg_rag_latency_ms}")
    if summary.rag_cases_skipped:
        print(f"RAG cases skipped: {summary.rag_cases_skipped}")


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Offline evaluator for retrieval and RAG quality.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to JSONL evaluation dataset.",
    )
    parser.add_argument(
        "--documents",
        type=Path,
        nargs="+",
        required=True,
        help="One or more .txt files to ingest before evaluation.",
    )
    parser.add_argument(
        "--collection",
        default="rag_eval_demo",
        help="Qdrant collection used for the benchmark run.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=settings.top_k,
        help="Default top-k to use when a case does not override it.",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.0,
        help="Default score threshold to use when a case does not override it.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the evaluation result JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = load_dataset(args.dataset)

    missing_documents = [path for path in args.documents if not path.exists()]
    if missing_documents:
        missing = ", ".join(str(path) for path in missing_documents)
        raise FileNotFoundError(f"ไม่พบไฟล์เอกสาร: {missing}")

    try:
        total_chunks = rebuild_collection(args.collection, args.documents)
        results = [
            run_case(
                case=case,
                collection_name=args.collection,
                default_top_k=args.top_k,
                default_score_threshold=args.score_threshold,
            )
            for case in cases
        ]
    except QdrantUnavailableError as exc:
        raise RuntimeError(
            "Qdrant ไม่พร้อมใช้งาน กรุณารัน Qdrant ก่อนเริ่ม benchmark"
        ) from exc

    summary = build_summary(results)
    payload = {
        "dataset": str(args.dataset),
        "documents": [str(path) for path in args.documents],
        "collection": args.collection,
        "chunks_ingested": total_chunks,
        "summary": summary.model_dump(),
        "cases": [result.model_dump() for result in results],
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print_summary(summary)


if __name__ == "__main__":
    main()
