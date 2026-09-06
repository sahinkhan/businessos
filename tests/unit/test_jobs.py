from datetime import UTC, datetime
from uuid import uuid4

from businessos.jobs import BackoffStrategy, DeadLetter, Job, JobState


def test_job_defaults_define_retry_and_dead_letter_conventions() -> None:
    job = Job(
        job_id=uuid4(),
        tenant_id=uuid4(),
        job_type="proof.rebuild",
        payload={"scope": "all"},
        correlation_id="correlation-1",
        trace_id="trace-1",
    )

    assert job.policy.retry.max_attempts == 3
    assert job.policy.retry.strategy is BackoffStrategy.EXPONENTIAL
    assert job.policy.cancellable
    assert job.policy.concurrency_limit == 1

    dead_letter = DeadLetter(
        job=job,
        attempts=job.policy.retry.max_attempts,
        failed_at=datetime.now(UTC),
        failure_code="attempts_exhausted",
    )
    assert dead_letter.job.job_id == job.job_id
    assert JobState.DEAD_LETTERED.value == "dead_lettered"
