import base64
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.domain.artifact_store import ArtifactKind, ArtifactRef
from app.domain.entities import Job, JobStatus, JobType
from app.domain.job_executor import JobExecutionError
from app.infrastructure.aws.playwright_job_executor import PlaywrightJobExecutor
from tests.unit.fakes import FakeArtifactStore

# Same reasoning as test_ssm_execution_polling.py: moto doesn't simulate real SSM Run
# Command execution, so dispatch/poll logic is tested against a hand-mocked SSM client.


class _InvocationDoesNotExist(Exception):
    pass


def _make_executor(
    artifact_store: FakeArtifactStore | None = None,
    poll_interval_seconds: float = 0.01,
    execution_timeout_seconds: float = 5.0,
) -> PlaywrightJobExecutor:
    executor = PlaywrightJobExecutor(
        region="us-east-1",
        logs_bucket_name="cloudworker-test-logs",
        artifacts_bucket_name="cloudworker-test-artifacts",
        artifact_store=artifact_store or FakeArtifactStore(),
        execution_timeout_seconds=execution_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    executor._ssm = MagicMock()
    executor._ssm.exceptions.InvocationDoesNotExist = _InvocationDoesNotExist
    return executor


def _make_browser_job(script: str) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        job_type=JobType.BROWSER,
        status=JobStatus.RUNNING,
        payload={"script": script},
        created_at=now,
        updated_at=now,
    )


async def test_execute_dispatches_base64_encoded_script_to_runner() -> None:
    executor = _make_executor()
    executor._ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
    executor._ssm.get_command_invocation.return_value = {"Status": "Success", "ResponseCode": 0}
    job = _make_browser_job("page.goto('https://example.com')")

    result = await executor.execute(job, "i-abc123")

    assert result.succeeded is True
    call_kwargs = executor._ssm.send_command.call_args.kwargs
    commands = call_kwargs["Parameters"]["commands"]
    assert len(commands) == 2
    assert "base64 -d" in commands[0]
    assert "/opt/cloudworker/run_playwright.py" in commands[1]
    assert str(job.id) in commands[1]
    assert "cloudworker-test-artifacts" in commands[1]

    encoded = commands[0].split("echo ")[1].split(" | base64")[0]
    assert base64.b64decode(encoded).decode() == "page.goto('https://example.com')"


async def test_execute_reports_artifacts_from_artifact_store_on_success() -> None:
    artifact_store = FakeArtifactStore(
        artifacts=[
            ArtifactRef(
                bucket="cloudworker-test-artifacts",
                key="jobs/x/artifacts/video.webm",
                kind=ArtifactKind.VIDEO,
                size_bytes=1024,
            ),
        ]
    )
    executor = _make_executor(artifact_store=artifact_store)
    executor._ssm.send_command.return_value = {"Command": {"CommandId": "cmd-2"}}
    executor._ssm.get_command_invocation.return_value = {"Status": "Success", "ResponseCode": 0}
    job = _make_browser_job("page.goto('https://example.com')")

    result = await executor.execute(job, "i-abc123")

    assert result.succeeded is True
    assert result.result["artifacts"] == [
        {
            "bucket": "cloudworker-test-artifacts",
            "key": "jobs/x/artifacts/video.webm",
            "kind": "video",
            "size_bytes": 1024,
        }
    ]


async def test_execute_returns_failure_result_when_script_fails() -> None:
    executor = _make_executor()
    executor._ssm.send_command.return_value = {"Command": {"CommandId": "cmd-3"}}
    executor._ssm.get_command_invocation.return_value = {"Status": "Failed", "ResponseCode": 1}

    result = await executor.execute(_make_browser_job("raise Exception('boom')"), "i-abc123")

    assert result.succeeded is False
    assert result.exit_code == 1


async def test_execute_raises_job_execution_error_when_send_command_fails() -> None:
    executor = _make_executor()
    executor._ssm.send_command.side_effect = RuntimeError("boto3 error")

    with pytest.raises(JobExecutionError):
        await executor.execute(_make_browser_job("page.goto('x')"), "i-abc123")
