import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Worker, WorkerStatus
from app.infrastructure.db.models import WorkerModel


def _to_entity(model: WorkerModel) -> Worker:
    return Worker(
        id=model.id,
        job_id=model.job_id,
        status=WorkerStatus(model.status),
        instance_id=model.instance_id,
        failure_reason=model.failure_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
        ready_at=model.ready_at,
        terminated_at=model.terminated_at,
    )


class SqlAlchemyWorkerRepository:
    """Every method here commits its own transaction.

    Unlike the request-scoped repositories (Phase 2's pattern, committed once at the end
    of an HTTP request by `get_db_session`), workers are primarily mutated from the
    standalone WorkerManager process loop, which has no request boundary — each state
    transition needs to be durable and visible immediately, the same reasoning behind
    JobRepository.claim_next_job() committing internally.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job_id: uuid.UUID) -> Worker:
        model = WorkerModel(job_id=job_id, status=WorkerStatus.PENDING.value)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        await self._session.commit()
        return _to_entity(model)

    async def get_by_job_id(self, job_id: uuid.UUID) -> Worker | None:
        result = await self._session.execute(
            select(WorkerModel).where(WorkerModel.job_id == job_id)
        )
        model = result.scalar_one_or_none()
        return _to_entity(model) if model else None

    async def _set_status(self, worker_id: uuid.UUID, **fields: object) -> Worker:
        model = await self._session.get(WorkerModel, worker_id)
        if model is None:
            raise ValueError(f"Worker {worker_id} not found")
        for field_name, value in fields.items():
            setattr(model, field_name, value)
        await self._session.flush()
        await self._session.refresh(model)
        await self._session.commit()
        return _to_entity(model)

    async def mark_provisioning(self, worker_id: uuid.UUID, instance_id: str) -> Worker:
        return await self._set_status(
            worker_id, status=WorkerStatus.PROVISIONING.value, instance_id=instance_id
        )

    async def mark_ready(self, worker_id: uuid.UUID) -> Worker:
        return await self._set_status(
            worker_id, status=WorkerStatus.READY.value, ready_at=datetime.now(UTC)
        )

    async def mark_terminating(self, worker_id: uuid.UUID) -> Worker:
        return await self._set_status(worker_id, status=WorkerStatus.TERMINATING.value)

    async def mark_terminated(self, worker_id: uuid.UUID) -> Worker:
        return await self._set_status(
            worker_id,
            status=WorkerStatus.TERMINATED.value,
            terminated_at=datetime.now(UTC),
        )

    async def mark_failed(self, worker_id: uuid.UUID, failure_reason: str) -> Worker:
        return await self._set_status(
            worker_id, status=WorkerStatus.FAILED.value, failure_reason=failure_reason
        )
