from moto import mock_aws

from app.infrastructure.aws.s3_artifact_store import S3ArtifactStore

# generate_presigned_url is a pure local HMAC-signing operation — no network call — so
# this genuinely proves the URL shape/expiry, not just that a mock was called. Wrapped
# in mock_aws() (rather than hand-set env vars) so the fake credentials it provides
# can't be shadowed by a real boto3 session another test in this run already resolved
# and cached process-globally — moto guarantees isolation here, plain env-var
# monkeypatching does not.


def _make_store() -> S3ArtifactStore:
    return S3ArtifactStore(
        region="us-east-1",
        logs_bucket_name="cloudworker-test-logs",
        artifacts_bucket_name="cloudworker-test-artifacts",
    )


async def test_generate_presigned_url_produces_a_scoped_temporary_link() -> None:
    with mock_aws():
        store = _make_store()

        url = await store.generate_presigned_url(
            "cloudworker-test-logs", "jobs/abc/stdout", expires_in_seconds=600
        )

        assert "cloudworker-test-logs" in url
        assert "jobs/abc/stdout" in url
        assert "X-Amz-Expires=600" in url
        assert "X-Amz-Signature=" in url


async def test_generate_presigned_url_differs_by_expiry() -> None:
    with mock_aws():
        store = _make_store()

        short_lived = await store.generate_presigned_url("b", "k", expires_in_seconds=60)
        long_lived = await store.generate_presigned_url("b", "k", expires_in_seconds=3600)

        assert short_lived != long_lived
        assert "X-Amz-Expires=60" in short_lived
        assert "X-Amz-Expires=3600" in long_lived


async def test_generate_presigned_url_differs_by_key() -> None:
    with mock_aws():
        store = _make_store()

        first = await store.generate_presigned_url("b", "jobs/1/stdout", expires_in_seconds=600)
        second = await store.generate_presigned_url("b", "jobs/2/stdout", expires_in_seconds=600)

        assert first != second
