import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.api.v1.schemas.job import JobCreateRequest, JobResponse
from app.domain.entities import Job, JobStatus, JobType


def test_job_create_request_accepts_known_job_type() -> None:
    request = JobCreateRequest(job_type="shell", payload={"command": "echo hi"})

    assert request.job_type == JobType.SHELL
    assert request.payload == {"command": "echo hi"}


def test_job_create_request_defaults_payload_to_empty_dict() -> None:
    with pytest.raises(ValidationError):
        # Defaults to {}, which then fails browser's payload.script requirement —
        # confirms the default-factory and the validator both actually run.
        JobCreateRequest(job_type="browser")


def test_job_create_request_rejects_unknown_job_type() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(job_type="not-a-real-type", payload={})


def test_job_create_request_rejects_shell_job_missing_command() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(job_type="shell", payload={})


def test_job_create_request_rejects_shell_job_with_blank_command() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(job_type="shell", payload={"command": "   "})


def test_job_create_request_rejects_shell_job_with_non_string_command() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(job_type="shell", payload={"command": 123})


def test_job_create_request_rejects_browser_job_missing_script() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(job_type="browser", payload={})


def test_job_create_request_rejects_browser_job_with_blank_script() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(job_type="browser", payload={"script": "   "})


def test_job_create_request_accepts_browser_job_with_script() -> None:
    request = JobCreateRequest(
        job_type="browser", payload={"script": "page.goto('https://example.com')"}
    )

    assert request.payload == {"script": "page.goto('https://example.com')"}


def test_job_response_from_entity_round_trips_fields() -> None:
    now = datetime.now(UTC)
    job = Job(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        job_type=JobType.SHELL,
        status=JobStatus.QUEUED,
        payload={"command": "echo hi"},
        created_at=now,
        updated_at=now,
    )

    response = JobResponse.from_entity(job)

    assert response.id == job.id
    assert response.job_type == JobType.SHELL
    assert response.status == JobStatus.QUEUED
    assert response.result is None
