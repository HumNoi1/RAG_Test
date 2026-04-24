from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models import GradeRequest, GradeResponse
from app.rag_pipeline import MissingLLMApiKeyError, grade_submission
from app.vector_store import (
    CollectionDimensionMismatchError,
    CollectionNotFoundError,
    QdrantUnavailableError,
)

router = APIRouter(prefix="/grading", tags=["Grading"])


@router.post(
    "/grade-submission",
    response_model=GradeResponse,
    summary="ตรวจงานและคืนคะแนนเสนอเพื่อรออาจารย์อนุมัติ",
)
async def grade_submission_endpoint(body: GradeRequest):
    try:
        return await grade_submission(body)
    except MissingLLMApiKeyError as exc:
        raise HTTPException(
            status_code=503,
            detail="การตรวจงานต้องใช้ GROQ_API_KEY เพื่อสร้างคะแนนเสนอ",
        ) from exc
    except CollectionDimensionMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QdrantUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Grading error: {str(exc)}"
        ) from exc
