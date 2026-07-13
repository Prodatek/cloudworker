import asyncio
import time
from typing import Any

from app.domain.job_executor import JobExecutionError

# Shared by SsmJobExecutor and PlaywrightJobExecutor: both dispatch an SSM command and
# poll GetCommandInvocation for a terminal status — genuinely identical mechanics, only
# what command gets sent and how the result is interpreted differs per executor.
TERMINAL_STATUSES = {"Success", "Failed", "Cancelled", "TimedOut"}


async def dispatch_command(
    ssm_client: Any,
    *,
    instance_id: str,
    document_name: str,
    parameters: dict[str, list[str]],
    output_s3_bucket: str,
    output_s3_key_prefix: str,
    timeout_seconds: float,
) -> str:
    """Sends an SSM command, returns its CommandId. Raises JobExecutionError on failure."""
    try:
        response = await asyncio.to_thread(
            ssm_client.send_command,
            InstanceIds=[instance_id],
            DocumentName=document_name,
            Parameters=parameters,
            OutputS3BucketName=output_s3_bucket,
            OutputS3KeyPrefix=output_s3_key_prefix,
            TimeoutSeconds=max(int(timeout_seconds), 30),
        )
    except Exception as exc:
        raise JobExecutionError(f"Failed to dispatch command: {exc}") from exc

    return str(response["Command"]["CommandId"])


async def poll_for_terminal_status(
    ssm_client: Any,
    *,
    command_id: str,
    instance_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any] | None:
    """Polls GetCommandInvocation until a terminal status or the deadline.

    Returns the final invocation dict, or None if the deadline passed without one
    (the command itself has its own TimeoutSeconds — this is a slightly longer outer
    deadline so SSM has a chance to report TimedOut itself first).
    """
    deadline = time.monotonic() + timeout_seconds + poll_interval_seconds
    while True:
        invocation = await _get_invocation(ssm_client, command_id, instance_id)
        status = invocation.get("Status") if invocation else None
        if status in TERMINAL_STATUSES:
            return invocation
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(poll_interval_seconds)


async def _get_invocation(
    ssm_client: Any, command_id: str, instance_id: str
) -> dict[str, Any] | None:
    try:
        return await asyncio.to_thread(
            ssm_client.get_command_invocation, CommandId=command_id, InstanceId=instance_id
        )
    except ssm_client.exceptions.InvocationDoesNotExist:
        # SSM hasn't registered the invocation yet (race right after send_command).
        return None
