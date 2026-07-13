import asyncio
import time
import uuid
from typing import Any

import boto3

from app.domain.job_executor import JobExecutionError, JobExecutionResult

_DOCUMENT_NAME = "AWS-RunShellScript"
# SSM's own convention for where AWS-RunShellScript's default plugin writes output
# under OutputS3KeyPrefix, when OutputS3BucketName is set on SendCommand.
_PLUGIN_OUTPUT_PATH = "awsrunShellScript/0.awsrunShellScript"
_TERMINAL_STATUSES = {"Success", "Failed", "Cancelled", "TimedOut"}


class SsmJobExecutor:
    """boto3-based JobExecutor: dispatches a shell command via SSM SendCommand
    (AWS-RunShellScript), letting SSM itself write full untruncated stdout/stderr to
    S3 (OutputS3BucketName), and polls GetCommandInvocation for a terminal status.
    """

    def __init__(
        self,
        region: str,
        logs_bucket_name: str,
        execution_timeout_seconds: float,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        if not logs_bucket_name:
            raise ValueError("logs_bucket_name must be configured")
        self._logs_bucket_name = logs_bucket_name
        self._execution_timeout_seconds = execution_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._ssm = boto3.client("ssm", region_name=region)

    async def execute(
        self, job_id: uuid.UUID, command: str, instance_id: str
    ) -> JobExecutionResult:
        key_prefix = f"jobs/{job_id}"
        try:
            response = await asyncio.to_thread(
                self._ssm.send_command,
                InstanceIds=[instance_id],
                DocumentName=_DOCUMENT_NAME,
                Parameters={"commands": [command]},
                OutputS3BucketName=self._logs_bucket_name,
                OutputS3KeyPrefix=key_prefix,
                TimeoutSeconds=max(int(self._execution_timeout_seconds), 30),
            )
        except Exception as exc:
            raise JobExecutionError(f"Failed to dispatch command: {exc}") from exc

        command_id = response["Command"]["CommandId"]
        stdout_key = f"{key_prefix}/{command_id}/{instance_id}/{_PLUGIN_OUTPUT_PATH}/stdout"
        stderr_key = f"{key_prefix}/{command_id}/{instance_id}/{_PLUGIN_OUTPUT_PATH}/stderr"
        s3_refs = {
            "s3_bucket": self._logs_bucket_name,
            "stdout_key": stdout_key,
            "stderr_key": stderr_key,
        }

        # A little slack past the command's own TimeoutSeconds, so SSM has a chance to
        # report TimedOut itself before we give up polling and report our own timeout.
        deadline = time.monotonic() + self._execution_timeout_seconds + self._poll_interval_seconds
        while True:
            invocation = await self._get_invocation(command_id, instance_id)
            status = invocation.get("Status") if invocation else None

            if status in _TERMINAL_STATUSES:
                exit_code = invocation.get("ResponseCode") if invocation else None
                result = {**s3_refs, "exit_code": exit_code, "status": status}
                if status == "Success":
                    return JobExecutionResult(succeeded=True, exit_code=exit_code, result=result)
                return JobExecutionResult(
                    succeeded=False,
                    exit_code=exit_code,
                    error_message=f"Command finished with status '{status}'",
                    result=result,
                )

            if time.monotonic() >= deadline:
                return JobExecutionResult(
                    succeeded=False,
                    exit_code=None,
                    error_message=(
                        f"Command did not reach a terminal status within "
                        f"{self._execution_timeout_seconds}s"
                    ),
                    result=s3_refs,
                )

            await asyncio.sleep(self._poll_interval_seconds)

    async def _get_invocation(self, command_id: str, instance_id: str) -> dict[str, Any] | None:
        try:
            return await asyncio.to_thread(
                self._ssm.get_command_invocation, CommandId=command_id, InstanceId=instance_id
            )
        except self._ssm.exceptions.InvocationDoesNotExist:
            # SSM hasn't registered the invocation yet (race right after send_command).
            return None
