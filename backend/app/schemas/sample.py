from datetime import datetime

from pydantic import BaseModel


class SampleItem(BaseModel):
    title: str
    value: str


class SampleResponse(BaseModel):
    message: str
    generated_at: datetime
    sample_items: list[SampleItem]
