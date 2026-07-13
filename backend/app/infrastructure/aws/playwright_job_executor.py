import base64

import boto3

from app.domain.artifact_store import ArtifactStore
from app.domain.entities import Job
from app.domain.job_executor import JobExecutionResult
from app.infrastructure.aws.ssm_command_dispatch import dispatch_command, poll_for_terminal_status

_DOCUMENT_NAME = "AWS-RunShellScript"
_PLUGIN_OUTPUT_PATH = "awsrunShellScript/0.awsrunShellScript"
# Baked into the AMI by infra/packer/worker-ami.pkr.hcl.
_RUNNER_PATH = "/opt/cloudworker/run_playwright.py"


class PlaywrightJobExecutor:
    """boto3-based JobExecutor for job_type=browser: writes payload.script to the
    worker (base64-embedded in the SSM command, decoded on the instance) and runs it
    via the Playwright runner harness baked into the AMI. Screenshots/video the runner
    captures are uploaded to the artifacts bucket by the runner itself (using the
    instance's own IAM role); this class lists what showed up afterward via
    ArtifactStore rather than parsing stdout for a manifest.
    """

    def __init__(
        self,
        region: str,
        logs_bucket_name: str,
        artifacts_bucket_name: str,
        artifact_store: ArtifactStore,
        execution_timeout_seconds: float,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        if not logs_bucket_name:
            raise ValueError("logs_bucket_name must be configured")
        if not artifacts_bucket_name:
            raise ValueError("artifacts_bucket_name must be configured")
        self._logs_bucket_name = logs_bucket_name
        self._artifacts_bucket_name = artifacts_bucket_name
        self._artifact_store = artifact_store
        self._execution_timeout_seconds = execution_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._ssm = boto3.client("ssm", region_name=region)

    async def execute(self, job: Job, instance_id: str) -> JobExecutionResult:
        script = str(job.payload.get("script", ""))
        key_prefix = f"jobs/{job.id}"
        script_path = f"/tmp/cloudworker-job-{job.id}.py"
        encoded_script = base64.b64encode(script.encode("utf-8")).decode("ascii")
        commands = [
            f"echo {encoded_script} | base64 -d > {script_path}",
            f"python3 {_RUNNER_PATH} {script_path} {job.id} {self._artifacts_bucket_name}",
        ]

        command_id = await dispatch_command(
            self._ssm,
            instance_id=instance_id,
            document_name=_DOCUMENT_NAME,
            parameters={"commands": commands},
            output_s3_bucket=self._logs_bucket_name,
            output_s3_key_prefix=key_prefix,
            timeout_seconds=self._execution_timeout_seconds,
        )
        stdout_key = f"{key_prefix}/{command_id}/{instance_id}/{_PLUGIN_OUTPUT_PATH}/stdout"
        stderr_key = f"{key_prefix}/{command_id}/{instance_id}/{_PLUGIN_OUTPUT_PATH}/stderr"
        s3_refs = {
            "s3_bucket": self._logs_bucket_name,
            "stdout_key": stdout_key,
            "stderr_key": stderr_key,
        }

        invocation = await poll_for_terminal_status(
            self._ssm,
            command_id=command_id,
            instance_id=instance_id,
            timeout_seconds=self._execution_timeout_seconds,
            poll_interval_seconds=self._poll_interval_seconds,
        )
        if invocation is None:
            return JobExecutionResult(
                succeeded=False,
                exit_code=None,
                error_message=(
                    f"Script did not reach a terminal status within "
                    f"{self._execution_timeout_seconds}s"
                ),
                result=s3_refs,
            )

        status = invocation["Status"]
        exit_code = invocation.get("ResponseCode")
        artifacts = await self._artifact_store.list_job_artifacts(job.id)
        result = {
            **s3_refs,
            "exit_code": exit_code,
            "status": status,
            "artifacts": [
                {
                    "bucket": artifact.bucket,
                    "key": artifact.key,
                    "kind": artifact.kind.value,
                    "size_bytes": artifact.size_bytes,
                }
                for artifact in artifacts
            ],
        }
        if status == "Success":
            return JobExecutionResult(succeeded=True, exit_code=exit_code, result=result)
        return JobExecutionResult(
            succeeded=False,
            exit_code=exit_code,
            error_message=f"Script finished with status '{status}'",
            result=result,
        )
