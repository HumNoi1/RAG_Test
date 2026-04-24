from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MetadataValue = str | int | float | bool


class IngestRequest(BaseModel):
    text: str | None = Field(None, description="ข้อความที่ต้องการ ingest")
    collection_name: str | None = None
    source_name: str | None = Field(None, description="ชื่อไฟล์หรือแหล่งข้อมูล")
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    document_id: str | None = Field(
        None, description="ID ของ document ใน Supabase สำหรับใช้ลบ chunks ทีหลัง"
    )


class IngestResponse(BaseModel):
    message: str
    chunks_stored: int
    collection: str
    source: str
    document_id: str = Field(..., description="UUID ที่ใช้ระบุ document ใน Qdrant payload")
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class ExtractTextResponse(BaseModel):
    source: str
    file_type: str
    text: str
    characters: int


class SearchRequest(BaseModel):
    query: str = Field(..., description="คำถามหรือข้อความที่ต้องการค้นหา")
    top_k: int | None = Field(None, description="จำนวนผลลัพธ์ที่ต้องการ")
    collection_name: str | None = None
    score_threshold: float = Field(0.0, description="คะแนนขั้นต่ำ (0.0 - 1.0)")
    metadata_filters: dict[str, MetadataValue] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    text: str
    score: float
    source: str
    chunk_index: int
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    results: list[RetrievedChunk]
    total_found: int


class RAGRequest(BaseModel):
    query: str = Field(..., description="คำถามที่ต้องการถาม")
    top_k: int | None = None
    collection_name: str | None = None
    score_threshold: float = 0.0
    metadata_filters: dict[str, MetadataValue] = Field(default_factory=dict)


class RAGResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    query: str
    answer: str
    retrieved_chunks: list[RetrievedChunk]
    model_used: str | None = None
    has_llm_response: bool = False


class RubricCriterion(BaseModel):
    criterion_name: str
    description: str = ""
    max_score: float = Field(..., gt=0)

    @field_validator("criterion_name")
    @classmethod
    def validate_criterion_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("criterion_name must not be empty")
        return normalized


class RubricCriterionScore(BaseModel):
    criterion_name: str
    score: float
    max_score: float
    reason: str


class GradeEvidence(BaseModel):
    source: str
    chunk_index: int
    quote: str
    relevance_score: float | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class GradeRequest(BaseModel):
    submission_text: str = Field(..., description="ข้อความงานที่ต้องการให้ระบบตรวจ")
    rubric: list[RubricCriterion] = Field(..., min_length=1)
    assignment_title: str | None = None
    assignment_instructions: str | None = None
    collection_name: str | None = None
    top_k: int | None = None
    score_threshold: float = 0.0
    metadata_filters: dict[str, MetadataValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_submission_text(self):
        if not self.submission_text.strip():
            raise ValueError("submission_text must not be empty")
        return self


class GradeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    proposed_total_score: float
    max_score: float
    student_reason: str
    internal_reason: str
    rubric_breakdown: list[RubricCriterionScore]
    evidence: list[GradeEvidence]
    retrieved_chunks: list[RetrievedChunk]
    model_used: str | None = None
    has_llm_response: bool = False
