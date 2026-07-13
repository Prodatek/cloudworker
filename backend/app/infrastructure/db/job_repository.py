import uuid
from typing import Any

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Job, JobStatus, JobType
from app.infrastructure.db.models import JobModel

_CLAIM_NEXT_JOB_SQL = text(
    """
    UPDATE jobs
    SET status = 'running', started_at = now(), updated_at = now()
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued'
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, user_id, job_type, status, payload, result, error_message,
              created_at, updated_at, started_at, completed_at
    """
)

_CANCEL_IF_CANCELLABLE_SQL = text(
    """
    UPDATE jobs
    SET status = 'cancelled', updated_at = now(), completed_at = now()
    WHERE id = :job_id AND user_id = :user_id AND status IN ('queued', 'running')
    RETURNING id, user_id, job_type, status, payload, result, error_message,
              created_at, updated_at, started_at, completed_at
    """
)

_FAIL_IF_RUNNING_SQL = text(
    """
    UPDATE jobs
    SET status = 'failed', error_message = :error_message, updated_at = now(), completed_at = now()
    WHERE id = :job_id AND status = 'running'
    RETURNING id, user_id, job_type, status, payload, result, error_message,
              created_at, updated_at, started_at, completed_at
    """
)

_COMPLETE_IF_RUNNING_SQL = text(
    """
    UPDATE jobs
    SET status = 'succeeded', result = :result, updated_at = now(), completed_at = now()
    WHERE id = :job_id AND status = 'running'
    RETURNING id, user_id, job_type, status, payload, result, error_message,
              created_at, updated_at, started_at, completed_at
    """
).bindparams(bindparam("result", type_=JSONB))


def _row_to_entity(row: Any) -> Job:
    return Job(
        id=row.id,
        user_id=row.user_id,
        job_type=JobType(row.job_type),
        status=JobStatus(row.status),
        payload=row.payload,
        result=row.result,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _model_to_entity(model: JobModel) -> Job:
    return Job(
        id=model.id,
        user_id=model.user_id,
        job_type=JobType(model.job_type),
        status=JobStatus(model.status),
        payload=model.payload,
        result=model.result,
        error_message=model.error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


class SqlAlchemyJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: uuid.UUID, job_type: str, payload: dict) -> Job:
        model = JobModel(
            user_id=user_id,
            job_type=job_type,
            status=JobStatus.QUEUED.value,
            payload=payload,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _model_to_entity(model)

    async def get_by_id_for_user(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job | None:
        result = await self._session.execute(
            select(JobModel).where(JobModel.id == job_id, JobModel.user_id == user_id)
        )
        model = result.scalar_one_or_none()
        return _model_to_entity(model) if model else None

    async def list_for_user(self, user_id: uuid.UUID, limit: int, offset: int) -> list[Job]:
        result = await self._session.execute(
            select(JobModel)
            .where(JobModel.user_id == user_id)
            .order_by(JobModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_model_to_entity(model) for model in result.scalars().all()]

    async def cancel(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job | None:
        result = await self._session.execute(
            _CANCEL_IF_CANCELLABLE_SQL, {"job_id": job_id, "user_id": user_id}
        )
        row = result.fetchone()
        await self._session.flush()
        return _row_to_entity(row) if row else None

    async def claim_next_job(self) -> Job | None:
        result = await self._session.execute(_CLAIM_NEXT_JOB_SQL)
        row = result.fetchone()
        await self._session.commit()
        return _row_to_entity(row) if row else None

    async def fail(self, job_id: uuid.UUID, error_message: str) -> Job | None:
        # Self-commits like claim_next_job(): only ever called from the standalone
        # WorkerManager process, which has no HTTP request boundary to commit at the end of.
        result = await self._session.execute(
            _FAIL_IF_RUNNING_SQL, {"job_id": job_id, "error_message": error_message}
        )
        row = result.fetchone()
        await self._session.commit()
        return _row_to_entity(row) if row else None

    async def complete(self, job_id: uuid.UUID, result: dict) -> Job | None:
        # Self-commits, same reasoning as fail() above.
        execution_result = await self._session.execute(
            _COMPLETE_IF_RUNNING_SQL, {"job_id": job_id, "result": result}
        )
        row = execution_result.fetchone()
        await self._session.commit()
        return _row_to_entity(row) if row else None
