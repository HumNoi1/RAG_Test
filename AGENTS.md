# AGENTS.md

## Scope
- This repo is only the Python RAG backend. There is no frontend, Supabase code, or monorepo structure here.
- The repo now also contains `supabase/` design artifacts for the target system schema, but they are not wired into runtime code in this repo.

## Product Direction
- Treat these as target-system requirements, not current implementation.
- This backend is intended to support LLM-assisted grading of student assignments using course materials as the RAG knowledge base.
- The wider system the user wants is `Next.js` + TypeScript for the website, `Supabase` for general/auth data, and this Python service for RAG/grading compute.
- Keep the design lean by default; do not add student self-upload, multi-attempt submissions, or extra approval states unless the user asks.
- V1 assumption: teachers upload both course knowledge files and student submissions; students only log in to view results.
- V1 assumption: one submission per student per assignment unless the user changes that requirement.
- Student-facing output should be limited to the final total score and one overall reason. Internal rubric breakdown, retrieval evidence, and draft scores are teacher/internal only.
- LLM-generated grades are proposals and must require teacher approval before they become student-visible.
- Use course materials only as grading knowledge unless the user explicitly broadens the source set.
- The product requirement now includes `PDF`/`DOCX` inputs, but the current repo still only ingests `.txt` uploads or raw text; any `PDF`/`DOCX` support needs a text-extraction step that does not exist here yet.

## Run And Verify
- Use `uv`, not `pip`; `pyproject.toml` sets `tool.uv.package = false`, so run commands as `uv run ...` without package installation steps.
- Local dev order: start Qdrant first with `docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant`, then `cp .env.example .env`, then `uv sync`, then `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`.
- `docker compose up --build` starts both `qdrant` and `rag-api`, but the compose file does not bind-mount `app/`; source edits require rebuild/restart. Use local `uvicorn --reload` for iterative work.
- Main manual smoke test is Swagger at `http://localhost:8000/docs`.
- The only built-in regression check is the offline evaluator: `uv run python -m app.evaluation --dataset sample_data/rag_eval_dataset.jsonl --documents sample_data/thai_ai_knowledge.txt sample_data/english_rag_guide.txt sample_data/rag_test_service_handbook.txt --collection rag_eval_demo --top-k 3 --score-threshold 0.4 --output sample_data/rag_eval_results.json`.
- `app.evaluation.rebuild_collection()` deletes the target collection before re-ingesting benchmark documents. Never point evaluation at a collection you need to keep.

## Code Map
- HTTP entrypoint: `app.main:app`.
- API surface: `app/routers/documents.py` for ingest and collection management, `app/routers/query.py` for search and RAG.
- Grading API: `app/routers/grading.py` for structured grade proposals.
- Core flow: `app/rag_pipeline.py` handles chunking/retrieval/LLM orchestration, `app/vector_store.py` handles Qdrant, and `app/embeddings.py` caches the SentenceTransformer model.
- Target-system database artifacts live under `supabase/`, with the current schema in `supabase/migrations/0001_initial_grading_schema.sql` and integration notes in `supabase/README.md`.
- `app/main.py` preloads the embedding model in the FastAPI lifespan, so first startup can be slow. Docker caches Hugging Face models in the `huggingface_cache` volume.

## Easy-To-Miss Behavior
- Trust code over README for LLM details: the running implementation uses Groq via the `groq` package with default `LLM_MODEL=qwen/qwen3-32b`; the README architecture text still mentions GPT-4o-mini.
- Current ingest endpoints only support `.txt` uploads or raw text. PDF/DOCX extraction is not implemented in this repo.
- Uploaded text decodes as UTF-8 first, then falls back to `tis-620`; keep that behavior if touching Thai ingest paths.
- `.env` is loaded from repo root by `app.config.Settings`; local default `QDRANT_HOST=localhost`, while `docker-compose.yml` overrides it to `qdrant`.
- `get_settings()`, `get_embedding_model()`, and `get_qdrant_client()` are `lru_cache`d. Restart the process after changing `.env`, model settings, or Qdrant connection settings.
- Changing `EMBEDDING_MODEL` without switching `QDRANT_COLLECTION` or deleting the old collection causes a dimension-mismatch `409` from `app.vector_store`.
- `/query/rag` is intentionally resilient: if `GROQ_API_KEY` is unset, it returns retrieved chunks with `has_llm_response=false` instead of failing.
- There is no `tests/`, lint, typecheck, pre-commit, or CI workflow in this repo right now, so do not claim those checks were run.
