import asyncio
import uuid

import boto3
from botocore.config import Config

from app.domain.artifact_store import ArtifactKind, ArtifactRef

_SCREENSHOT_SUFFIXES = (".png", ".jpg", ".jpeg")
_VIDEO_SUFFIXES = (".webm", ".mp4")
_LOG_SUFFIXES = ("stdout", "stderr")


def _classify(key: str) -> ArtifactKind:
    lower = key.lower()
    if lower.endswith(_SCREENSHOT_SUFFIXES):
        return ArtifactKind.SCREENSHOT
    if lower.endswith(_VIDEO_SUFFIXES):
        return ArtifactKind.VIDEO
    if lower.endswith(_LOG_SUFFIXES):
        return ArtifactKind.LOG
    return ArtifactKind.OTHER


class S3ArtifactStore:
    """boto3-based ArtifactStore, spanning both the logs and artifacts buckets from
    Phase 3's storage module.
    """

    def __init__(self, region: str, logs_bucket_name: str, artifacts_bucket_name: str) -> None:
        self._logs_bucket_name = logs_bucket_name
        self._artifacts_bucket_name = artifacts_bucket_name
        # Force SigV4: botocore's default for "s3" in us-east-1 is the legacy SigV2
        # presigned URL format, which most regions don't even accept.
        self._s3 = boto3.client("s3", region_name=region, config=Config(signature_version="s3v4"))

    async def list_job_artifacts(self, job_id: uuid.UUID) -> list[ArtifactRef]:
        prefix = f"jobs/{job_id}/"
        artifacts: list[ArtifactRef] = []
        for bucket in {self._logs_bucket_name, self._artifacts_bucket_name}:
            if not bucket:
                continue
            artifacts.extend(await self._list_bucket(bucket, prefix))
        return artifacts

    async def _list_bucket(self, bucket: str, prefix: str) -> list[ArtifactRef]:
        response = await asyncio.to_thread(self._s3.list_objects_v2, Bucket=bucket, Prefix=prefix)
        return [
            ArtifactRef(
                bucket=bucket,
                key=obj["Key"],
                kind=_classify(obj["Key"]),
                size_bytes=obj.get("Size"),
            )
            for obj in response.get("Contents", [])
        ]

    async def generate_presigned_url(self, bucket: str, key: str, expires_in_seconds: int) -> str:
        # Pure local signing — no network call, so this works even without real AWS
        # connectivity as long as *some* credentials (even fake ones) are configured.
        return await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in_seconds,
        )
