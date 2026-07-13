import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.domain.entities import Job, JobStatus, JobType
from app.domain.job_executor import JobExecutionError
from app.infrastructure.aws.ssm_job_executor import SsmJobExecutor

# Same reasoning as Phase 4's test_ssm_ready_polling.py: moto doesn't simulate real SSM
# Run Command execution results, so the dispatch/poll/status-interpretation logic here is
# tested against a hand-mocked SSM client instead.


class _InvocationDoesNotExist(Exception):
    pass


def _make_executor(
    poll_interval_seconds: float = 0.01, execution_timeout_seconds: float = 5.0
) -> SsmJobExecutor:
    executor = SsmJobExecutor(
        region="us-east-1",
        logs_bucket_name="cloudworker-test-logs",
        execution_timeout_seconds=execution_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    executor._ssm = MagicMock()
    executor._ssm.exceptions.InvocationDoesNotExist = _InvocationDoesNotExist
    return executor


def _make_shell_job(command: str) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        job_type=JobType.SHELL,
        status=JobStatus.RUNNING,
        payload={"command": command},
        created_at=now,
        updated_at=now,
    )


async def test_execute_returns_success_result_with_s3_references() -> None:
    executor = _make_executor()
    executor._ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
    executor._ssm.get_command_invocation.return_value = {"Status": "Success", "ResponseCode": 0}
    job = _make_shell_job("echo hi")

    result = await executor.execute(job, "i-abc123")

    assert result.succeeded is True
    assert result.exit_code == 0
    assert result.result["s3_bucket"] == "cloudworker-test-logs"
    assert result.result["stdout_key"].startswith(f"jobs/{job.id}/cmd-1/i-abc123/")
    call_kwargs = executor._ssm.send_command.call_args.kwargs
    assert call_kwargs["InstanceIds"] == ["i-abc123"]
    assert call_kwargs["Parameters"] == {"commands": ["echo hi"]}
    assert call_kwargs["OutputS3BucketName"] == "cloudworker-test-logs"


async def test_execute_returns_failure_result_when_command_fails() -> None:
    executor = _make_executor()
    executor._ssm.send_command.return_value = {"Command": {"CommandId": "cmd-2"}}
    executor._ssm.get_command_invocation.return_value = {"Status": "Failed", "ResponseCode": 1}

    result = await executor.execute(_make_shell_job("exit 1"), "i-abc123")

    assert result.succeeded is False
    assert result.exit_code == 1
    assert result.error_message is not None and "Failed" in result.error_message


async def test_execute_polls_through_transient_statuses_before_success() -> None:
    executor = _make_executor()
    executor._ssm.send_command.return_value = {"Command": {"CommandId": "cmd-3"}}
    executor._ssm.get_command_invocation.side_effect = [
        {"Status": "Pending"},
        {"Status": "InProgress"},
        {"Status": "Success", "ResponseCode": 0},
    ]

    result = await executor.execute(_make_shell_job("echo hi"), "i-abc123")

    assert result.succeeded is True
    assert executor._ssm.get_command_invocation.call_count == 3


async def test_execute_tolerates_invocation_not_yet_registered() -> None:
    executor = _make_executor()
    executor._ssm.send_command.return_value = {"Command": {"CommandId": "cmd-4"}}
    executor._ssm.get_command_invocation.side_effect = [
        _InvocationDoesNotExist(),
        {"Status": "Success", "ResponseCode": 0},
    ]

    result = await executor.execute(_make_shell_job("echo hi"), "i-abc123")

    assert result.succeeded is True


async def test_execute_returns_failure_on_our_own_polling_timeout() -> None:
    executor = _make_executor(execution_timeout_seconds=0.05)
    executor._ssm.send_command.return_value = {"Command": {"CommandId": "cmd-5"}}
    executor._ssm.get_command_invocation.return_value = {"Status": "InProgress"}

    result = await executor.execute(_make_shell_job("sleep 999"), "i-abc123")

    assert result.succeeded is False
    assert result.exit_code is None
    assert result.error_message is not None
    assert "did not reach a terminal status" in result.error_message


async def test_execute_raises_job_execution_error_when_send_command_fails() -> None:
    executor = _make_executor()
    executor._ssm.send_command.side_effect = RuntimeError("boto3 error")

    with pytest.raises(JobExecutionError):
        await executor.execute(_make_shell_job("echo hi"), "i-abc123")
