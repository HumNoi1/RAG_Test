from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    text: str | None = Field(None, description="ข้อความที่ต้องการ ingest")
    collection_name: str | None = None
    source_name: str | None = Field(None, description="ชื่อไฟล์หรือแหล่งข้อมูล")


class IngestResponse(BaseModel):
    message: str
    chunks_stored: int
    collection: str
    source: str


class SearchRequest(BaseModel):
    query: str = Field(..., description="คำถามหรือข้อความที่ต้องการค้นหา")
    top_k: int | None = Field(None, description="จำนวนผลลัพธ์ที่ต้องการ")
    collection_name: str | None = None
    score_threshold: float = Field(0.0, description="คะแนนขั้นต่ำ (0.0 - 1.0)")


class RetrievedChunk(BaseModel):
    text: str
    score: float
    source: str
    chunk_index: int


class SearchResponse(BaseModel):
    query: str
    results: list[RetrievedChunk]
    total_found: int


class RAGRequest(BaseModel):
    query: str = Field(..., description="คำถามที่ต้องการถาม")
    top_k: int | None = None
    collection_name: str | None = None
    score_threshold: float = 0.0


class RAGResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    query: str
    answer: str
    retrieved_chunks: list[RetrievedChunk]
    model_used: str | None = None
    has_llm_response: bool = False
