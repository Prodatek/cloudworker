import uuid
from typing import Protocol


class ProvisioningError(Exception):
    """Raised when launching a worker instance fails outright."""


class WorkerProvisioner(Protocol):
    """The AWS-facing boundary WorkerManager depends on instead of boto3 directly."""

    async def launch(self, job_id: uuid.UUID) -> str:
        """Launches a worker instance for the given job. Returns the instance id.

        Raises ProvisioningError if the launch call itself fails.
        """
        ...

    async def wait_until_ssm_ready(self, instance_id: str, timeout_seconds: float) -> bool:
        """Polls until the instance has registered with SSM, or the timeout elapses.

        Returns True if it became ready in time, False on timeout (not an exception —
        a timeout is an expected, handled outcome, not a failure to communicate with AWS).
        """
        ...

    async def terminate(self, instance_id: str) -> None:
        """Terminates the instance. Safe to call even if it's already terminated."""
        ...
