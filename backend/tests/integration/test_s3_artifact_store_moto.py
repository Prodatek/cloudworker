import uuid

import boto3
from moto import mock_aws

from app.domain.artifact_store import ArtifactKind
from app.infrastructure.aws.s3_artifact_store import S3ArtifactStore

# S3 operations (unlike EC2 instance status / SSM agent check-in) are fully simulable by
# moto, so this proves real bucket behavior, not just call shapes.


async def test_list_job_artifacts_classifies_and_spans_both_buckets() -> None:
    with mock_aws():
        region = "us-east-1"
        s3 = boto3.client("s3", region_name=region)
        logs_bucket = "cloudworker-test-logs"
        artifacts_bucket = "cloudworker-test-artifacts"
        s3.create_bucket(Bucket=logs_bucket)
        s3.create_bucket(Bucket=artifacts_bucket)

        job_id = uuid.uuid4()
        prefix = f"jobs/{job_id}"
        s3.put_object(
            Bucket=logs_bucket,
            Key=f"{prefix}/cmd-1/i-abc/awsrunShellScript/0.awsrunShellScript/stdout",
            Body=b"hello",
        )
        s3.put_object(
            Bucket=logs_bucket,
            Key=f"{prefix}/cmd-1/i-abc/awsrunShellScript/0.awsrunShellScript/stderr",
            Body=b"",
        )
        s3.put_object(Bucket=artifacts_bucket, Key=f"{prefix}/artifacts/video.webm", Body=b"vid")
        s3.put_object(Bucket=artifacts_bucket, Key=f"{prefix}/artifacts/shot.png", Body=b"png")
        # Outside this job's prefix — must not show up in the result.
        s3.put_object(Bucket=artifacts_bucket, Key="jobs/other-job/artifacts/video.webm", Body=b"x")

        store = S3ArtifactStore(
            region=region, logs_bucket_name=logs_bucket, artifacts_bucket_name=artifacts_bucket
        )

        artifacts = await store.list_job_artifacts(job_id)

        assert len(artifacts) == 4
        assert all(a.key.startswith(prefix) for a in artifacts)
        kinds = {a.kind for a in artifacts}
        assert kinds == {ArtifactKind.LOG, ArtifactKind.VIDEO, ArtifactKind.SCREENSHOT}


async def test_list_job_artifacts_returns_empty_list_when_nothing_uploaded() -> None:
    with mock_aws():
        region = "us-east-1"
        s3 = boto3.client("s3", region_name=region)
        s3.create_bucket(Bucket="cloudworker-test-logs")
        s3.create_bucket(Bucket="cloudworker-test-artifacts")
        store = S3ArtifactStore(
            region=region,
            logs_bucket_name="cloudworker-test-logs",
            artifacts_bucket_name="cloudworker-test-artifacts",
        )

        artifacts = await store.list_job_artifacts(uuid.uuid4())

        assert artifacts == []
