"""BusinessOS background-job contracts."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    tenant_id: UUID
    job_type: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    payload: dict[str, object]
    scheduled_at: datetime | None = None
    priority: int = Field(default=0, ge=-100, le=100)
    correlation_id: str


class JobQueue(Protocol):
    async def enqueue(self, job: Job) -> None: ...
