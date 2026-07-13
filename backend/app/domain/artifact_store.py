import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ArtifactKind(StrEnum):
    LOG = "log"
    SCREENSHOT = "screenshot"
    VIDEO = "video"
    OTHER = "other"


@dataclass
class ArtifactRef:
    bucket: str
    key: str
    kind: ArtifactKind
    size_bytes: int | None = None


class ArtifactStore(Protocol):
    """Read access to a job's output artifacts (logs, screenshots, video) in S3.

    Doesn't know about jobs/workers/the queue — just "what's under this job's prefix"
    and "give me a temporary link to one object."
    """

    async def list_job_artifacts(self, job_id: uuid.UUID) -> list[ArtifactRef]: ...

    async def generate_presigned_url(
        self, bucket: str, key: str, expires_in_seconds: int
    ) -> str: ...
