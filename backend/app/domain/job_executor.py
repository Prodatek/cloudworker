import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


class JobExecutionError(Exception):
    """Raised when dispatching or monitoring a command fails outright (not the same as
    the command itself exiting non-zero, which is a normal JobExecutionResult)."""


@dataclass
class JobExecutionResult:
    succeeded: bool
    exit_code: int | None
    error_message: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


class JobExecutor(Protocol):
    """Runs one job's command on one already-`ready` worker instance.

    Single responsibility: dispatch + monitor + report. Doesn't know about the job
    queue, worker provisioning, or Postgres — WorkerManager/JobProcessor own that.
    """

    async def execute(
        self, job_id: uuid.UUID, command: str, instance_id: str
    ) -> JobExecutionResult: ...
