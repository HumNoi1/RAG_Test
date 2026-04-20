# 🔍 RAG Demo — Thai & English

Retrieval-Augmented Generation demo ด้วย **FastAPI + Qdrant + sentence-transformers**

รองรับ **ภาษาไทย** และ **English** ในระบบเดียวกัน

---

## 🏗️ Architecture

```
.txt File
   ↓
[Chunking]  ← ตัดข้อความเป็น chunks
   ↓
[Embedding] ← paraphrase-multilingual-MiniLM-L12-v2 (384 dim, รองรับ 50+ ภาษา)
   ↓
[Qdrant]    ← เก็บ vectors + metadata
   ↓
[Query]     ← embed query → cosine similarity search
   ↓
[LLM]       ← (optional) GPT-4o-mini สร้างคำตอบจาก context
```

---

## 🚀 Quick Start

### 1. Clone และ setup

```bash
git clone https://github.com/HumNoi1/RAG_Test.git
cd RAG_Test
cp .env.example .env
# แก้ไข .env ตามต้องการ (เพิ่ม OPENAI_API_KEY ถ้าต้องการ LLM)
```

### 2. รัน Docker Compose

```bash
docker compose up --build
```

- **FastAPI**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **Qdrant Dashboard**: http://localhost:6333/dashboard

---

## 🧪 ทดสอบ

### วิธีที่ 1: ผ่าน Swagger UI (แนะนำ)

1. เปิด http://localhost:8000/docs
2. ไปที่ `POST /documents/upload-and-ingest`
3. อัปโหลดไฟล์จาก `sample_data/` (เช่น `thai_ai_knowledge.txt`)
4. ลอง query ที่ `POST /query/search` หรือ `POST /query/rag`

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

# 5. RAG (ถ้ามี OPENAI_API_KEY)
curl -X POST http://localhost:8000/query/rag \
  -H "Content-Type: application/json" \
  -d '{"query": "อธิบาย Reinforcement Learning ให้ฟังหน่อย"}'

# 6. ดูข้อมูล collection
curl http://localhost:8000/documents/collection/rag_demo
```

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
  "model_used": "gpt-4o-mini",
  "has_llm_response": true
}
```

---

## ⚙️ Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_HOST` | localhost | Qdrant host |
| `QDRANT_PORT` | 6333 | Qdrant port |
| `QDRANT_COLLECTION` | rag_demo | ชื่อ collection |
| `EMBEDDING_MODEL` | paraphrase-multilingual-MiniLM-L12-v2 | Embedding model |
| `OPENAI_API_KEY` | (empty) | OpenAI key (optional) |
| `CHUNK_SIZE` | 500 | ขนาด chunk (ตัวอักษร) |
| `CHUNK_OVERLAP` | 50 | overlap ระหว่าง chunks |
| `TOP_K` | 5 | จำนวนผลลัพธ์ default |

---

## 🗂️ Project Structure

```
RAG/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
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

# Install dependencies
pip install -r requirements.txt

# Copy และแก้ .env
cp .env.example .env

# รัน FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
