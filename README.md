# 🔍 RAG Demo — Thai & English

Retrieval-Augmented Generation demo ด้วย **FastAPI + Qdrant + sentence-transformers**

รองรับ **ภาษาไทย** และ **English** ในระบบเดียวกัน

---

## 🏗️ Architecture

```
.txt/.pdf/.docx File
   ↓
[Chunking]  ← ตัดข้อความเป็น chunks
   ↓
[Embedding] ← BAAI/bge-m3 (1024 dim, multilingual)
   ↓
[Qdrant]    ← เก็บ vectors + metadata
   ↓
[Query]     ← embed query → cosine similarity search
   ↓
[LLM]       ← (optional) Groq model สร้างคำตอบ/คะแนนจาก context
```

---

## 🚀 Quick Start

### 1. Clone และ setup

```bash
git clone https://github.com/HumNoi1/RAG_Test.git
cd RAG_Test
cp .env.example .env
# แก้ไข `.env` แล้วใส่ `GROQ_API_KEY`
```

### 2. รัน Docker Compose

```bash
docker compose up --build
```

- **FastAPI**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **Qdrant Dashboard**: http://localhost:6333/dashboard

Docker Compose จะอ่าน `QDRANT_COLLECTION`, `EMBEDDING_MODEL`, `LLM_MODEL` และ `GROQ_API_KEY` จาก `.env` และ cache model ของ Hugging Face ไว้ใน volume เพื่อไม่ต้องดาวน์โหลดใหม่ทุกครั้ง

---

## 🧪 ทดสอบ

### วิธีที่ 1: ผ่าน Swagger UI (แนะนำ)

1. เปิด http://localhost:8000/docs
2. ไปที่ `POST /documents/upload-and-ingest`
3. อัปโหลดไฟล์จาก `sample_data/` (เช่น `thai_ai_knowledge.txt`)
4. ลอง query ที่ `POST /query/search` หรือ `POST /query/rag`
5. ถ้าต้องการตรวจงาน ให้ใช้ `POST /grading/grade-submission`

### วิธีที่ 2: curl

```bash
# 1. Upload และ ingest ไฟล์ภาษาไทย
curl -X POST http://localhost:8000/documents/upload-and-ingest \
  -F "file=@sample_data/thai_ai_knowledge.txt"

# 2. Upload และ ingest ไฟล์ภาษาอังกฤษ
curl -X POST http://localhost:8000/documents/upload-and-ingest \
  -F "file=@sample_data/english_rag_guide.txt"

# 3. Semantic search (ภาษาไทย)
curl -X POST http://localhost:8000/query/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Machine Learning คืออะไร", "top_k": 3}'

# 4. Semantic search (English)
curl -X POST http://localhost:8000/query/search \
  -H "Content-Type: application/json" \
  -d '{"query": "How does RAG work?", "top_k": 3}'

# 5. RAG (ถ้ามี `GROQ_API_KEY`)
curl -X POST http://localhost:8000/query/rag \
  -H "Content-Type: application/json" \
  -d '{"query": "อธิบาย Reinforcement Learning ให้ฟังหน่อย"}'

# 6. ดูข้อมูล collection
curl http://localhost:8000/documents/collection/rag_demo_bge_m3

# 7. ตรวจงานด้วย rubric
curl -X POST http://localhost:8000/grading/grade-submission \
  -H "Content-Type: application/json" \
  -d '{
    "submission_text": "Machine Learning คือการทำให้คอมพิวเตอร์เรียนรู้จากข้อมูล...",
    "assignment_title": "อธิบาย Machine Learning",
    "rubric": [
      {"criterion_name": "ความถูกต้อง", "description": "อธิบายแนวคิดได้ถูกต้อง", "max_score": 50},
      {"criterion_name": "ความครบถ้วน", "description": "ครอบคลุมประเด็นสำคัญ", "max_score": 50}
    ]
  }'
```

---

## 📏 วัดผล RAG

โปรเจกต์นี้มี **offline evaluation runner** สำหรับวัดผลทั้ง retrieval, answer quality และ latency โดยใช้ชุดคำถามอ้างอิงแบบ JSONL

### สิ่งที่ควรวัด

| กลุ่ม | Metric | ใช้ตอบคำถามอะไร |
|------|--------|------------------|
| Retrieval | `Hit@k`, `Recall@k`, `MRR` | ดึง chunk / source ที่ควรเจอได้หรือยัง และขึ้นมาเร็วแค่ไหน |
| Answer | `answer_correct_rate`, `keyword_coverage_avg` | คำตอบตรงกับสิ่งที่คาดหวังหรือยัง |
| Grounding | `faithfulness_proxy_rate` | คำตอบที่ถูกต้องมี evidence จาก retrieved context หรือไม่ |
| Abstention | `abstention_accuracy` | ถ้าไม่มีข้อมูลพอ ระบบยอมบอกว่าไม่พอได้ถูกต้องหรือไม่ |
| Ops | `avg_retrieval_latency_ms`, `avg_rag_latency_ms` | ระบบตอบเร็วพอหรือไม่ |

> `faithfulness_proxy_rate` ในเวอร์ชันนี้เป็น **deterministic proxy** ที่ดูร่วมกันระหว่าง answer correctness และการมี supporting retrieval ยังไม่ใช่ semantic judge เต็มรูปแบบ
>
> ถ้ายังไม่ได้ตั้ง `GROQ_API_KEY` ระบบจะยังวัด retrieval, abstention, และ latency ได้ตามปกติ แต่ **answer quality ของเคสที่ต้องใช้ LLM จะถูก skip เป็นส่วนใหญ่**

### ชุดข้อมูลตัวอย่าง

- `sample_data/rag_eval_dataset.jsonl` — golden set ตัวอย่างสำหรับ 3 เอกสารใน `sample_data/`
- `sample_data/rag_test_service_handbook.txt` — เอกสารเพิ่มสำหรับลอง query เชิงธุรกิจ/FAQ

### วิธีรัน benchmark

1. รัน Qdrant ก่อน

```bash
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

2. รัน evaluation

```bash
uv run python -m app.evaluation \
  --dataset sample_data/rag_eval_dataset.jsonl \
  --documents sample_data/thai_ai_knowledge.txt sample_data/english_rag_guide.txt sample_data/rag_test_service_handbook.txt \
  --collection rag_eval_demo \
  --top-k 3 \
  --score-threshold 0.4 \
  --output sample_data/rag_eval_results.json
```

### รูปแบบ dataset

แต่ละบรรทัดใน JSONL คือ test case หนึ่งรายการ เช่น

```json
{
  "query": "แพ็กเกจ Pro ราคาเท่าไร",
  "mode": "rag",
  "expected_sources": ["rag_test_service_handbook.txt"],
  "expected_answer_keywords": ["299", "บาท", "ผู้ใช้", "เดือน"],
  "min_keyword_coverage": 0.75
}
```

### การตีความผลลัพธ์

- ถ้า `Recall@k` ต่ำ → ปัญหามักอยู่ที่ chunking, embedding model, หรือ `top_k`
- ถ้า retrieval ดีแต่ `answer_correct_rate` ต่ำ → ปัญหามักอยู่ที่ prompt, LLM behavior, หรือ context ยาวเกินไป
- ถ้า `abstention_accuracy` ต่ำ → ควรปรับ `score_threshold` หรือเพิ่ม logic ปฏิเสธคำตอบเมื่อ context ไม่พอ
- ถ้า latency สูง → แยกดูว่า retrieval หรือ LLM เป็น bottleneck

---

## 📊 ทำความเข้าใจ Response

### `/query/search` Response

```json
{
  "query": "Machine Learning คืออะไร",
  "results": [
    {
      "text": "การเรียนรู้ของเครื่อง (Machine Learning หรือ ML)...",
      "score": 0.8923,    ← cosine similarity (1.0 = เหมือนกันทุกอย่าง)
      "source": "thai_ai_knowledge.txt",
      "chunk_index": 2
    }
  ],
  "total_found": 3
}
```

**score interpretation:**
| ช่วงคะแนน | ความหมาย |
|-----------|----------|
| 0.85 – 1.0 | เกี่ยวข้องสูงมาก |
| 0.70 – 0.85 | เกี่ยวข้องดี |
| 0.50 – 0.70 | เกี่ยวข้องปานกลาง |
| < 0.50 | อาจไม่เกี่ยวข้อง |

### `/query/rag` Response

```json
{
  "query": "อธิบาย Reinforcement Learning",
  "answer": "Reinforcement Learning คือ...",  ← LLM ตอบจาก context
  "retrieved_chunks": [...],                   ← chunks ที่ดึงมา
  "model_used": "qwen/qwen3-32b",
  "has_llm_response": true
}
```

### `/grading/grade-submission` Response

```json
{
  "proposed_total_score": 82,
  "max_score": 100,
  "student_reason": "คำตอบครอบคลุมแนวคิดหลัก แต่ยังขาดรายละเอียดบางส่วน",
  "internal_reason": "Submission explains the core concept correctly but misses deeper supporting detail.",
  "rubric_breakdown": [
    {
      "criterion_name": "ความถูกต้อง",
      "score": 42,
      "max_score": 50,
      "reason": "อธิบายแนวคิดหลักได้ถูกต้อง"
    }
  ],
  "evidence": [
    {
      "source": "thai_ai_knowledge.txt",
      "chunk_index": 2,
      "quote": "...",
      "relevance_score": 0.89,
      "metadata": {"file_type": "txt"}
    }
  ],
  "retrieved_chunks": [...],
  "model_used": "qwen/qwen3-32b",
  "has_llm_response": true
}
```

---

## ⚙️ Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_HOST` | localhost | Qdrant host |
| `QDRANT_PORT` | 6333 | Qdrant port |
| `QDRANT_COLLECTION` | rag_demo_bge_m3 | ชื่อ collection |
| `EMBEDDING_MODEL` | BAAI/bge-m3 | Embedding model |
| `LLM_MODEL` | qwen/qwen3-32b | ชื่อ model ที่จะใช้ใน `/query/rag` |
| `GROQ_API_KEY` | (empty) | Groq API key (required for grading, optional for `/query/rag`) |
| `CHUNK_SIZE` | 500 | ขนาด chunk (ตัวอักษร) |
| `CHUNK_OVERLAP` | 50 | overlap ระหว่าง chunks |
| `TOP_K` | 5 | จำนวนผลลัพธ์ default |

> หากเปลี่ยน `EMBEDDING_MODEL` แล้ว vector dimension ไม่เท่าของเดิม ให้เปลี่ยน `QDRANT_COLLECTION` ใหม่หรือสั่งลบ collection เดิมก่อน ingest/search

---

## 🗂️ Project Structure

```
RAG/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml              ← uv project & dependencies
├── uv.lock                     ← lockfile (auto-generated)
├── .env.example
├── sample_data/
│   ├── thai_ai_knowledge.txt    ← ตัวอย่างภาษาไทย
│   └── english_rag_guide.txt   ← ตัวอย่างภาษาอังกฤษ
└── app/
    ├── main.py          ← FastAPI app + lifespan
    ├── config.py        ← Settings
    ├── models.py        ← Pydantic models
    ├── embeddings.py    ← sentence-transformers
    ├── vector_store.py  ← Qdrant operations
    ├── rag_pipeline.py  ← Chunking + Retrieval + LLM
    └── routers/
        ├── documents.py ← Upload/Ingest endpoints
        └── query.py     ← Search/RAG endpoints
```

---

## 🛠️ Run Locally (ไม่ใช้ Docker)

```bash
# รัน Qdrant ด้วย Docker
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant

# Copy และแก้ .env
cp .env.example .env

# Install dependencies ด้วย uv
uv sync

# รัน FastAPI
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> ติดตั้ง uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
