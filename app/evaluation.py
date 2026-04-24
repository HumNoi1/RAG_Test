import argparse
import asyncio
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


async def rebuild_collection(collection_name: str, documents: list[Path]) -> int:
    try:
        delete_collection(collection_name)
    except CollectionNotFoundError:
        pass

    total_chunks = 0
    for document in documents:
        text