from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain.entities import Job


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
    """Runs one job on one already-`ready` worker instance.

    Single responsibility: dispatch + monitor + report. Doesn't know about the job
    queue, worker provisioning, or Postgres — WorkerManager/JobProcessor own that.
    Takes the whole Job (not just a "command" string) so each implementation extracts
    whatever it needs from job.payload itself — a shell executor reads payload.command,
    a browser executor reads payload.script — rather than the caller (JobProcessor)
    needing to know every job type's payload shape.
    """

    async def execute(self, job: Job, instance_id: str) -> JobExecutionResult: ...
