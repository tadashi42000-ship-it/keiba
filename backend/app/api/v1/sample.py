from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas.sample import SampleItem, SampleResponse

router = APIRouter()


@router.get("/sample", response_model=SampleResponse)
def api_sample() -> SampleResponse:
    return SampleResponse(
        message="Sample response from FastAPI",
        generated_at=datetime.now(timezone.utc),
        sample_items=[
            SampleItem(title="platform", value="nextjs-fastapi"),
            SampleItem(title="status", value="connected"),
            SampleItem(title="phase", value="v1-minimum"),
        ],
    )
