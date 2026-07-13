from pydantic import BaseModel

from app.domain.artifact_store import ArtifactKind, ArtifactRef


class ArtifactResponse(BaseModel):
    key: str
    kind: ArtifactKind
    size_bytes: int | None
    url: str
    expires_in_seconds: int

    @classmethod
    def from_ref(cls, ref: ArtifactRef, url: str, expires_in_seconds: int) -> "ArtifactResponse":
        return cls(
            key=ref.key,
            kind=ref.kind,
            size_bytes=ref.size_bytes,
            url=url,
            expires_in_seconds=expires_in_seconds,
        )


class JobArtifactsResponse(BaseModel):
    artifacts: list[ArtifactResponse]
