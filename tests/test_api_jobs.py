from app.api.jobs import (create_job, claim_next_job, finish_job,
                          fail_or_retry, set_progress, reset_running_jobs,
                          get_job)


def test_create_and_get(session):
    job = create_job(session, "comment_screening", {"comments": []}, total=5)
    assert job.status == "pending" and job.progress_total == 5
    assert get_job(session, job.id).id == job.id


def test_claim_marks_running(session):
    job = create_job(session, "comment_screening", {}, total=1)
    claimed = claim_next_job(session)
    assert claimed.id == job.id
    assert claimed.status == "running" and claimed.attempt_count == 1
    assert claim_next_job(session) is None


def test_finish_success(session):
    job = create_job(session, "comment_screening", {}, total=1)
    claim_next_job(session)
    finish_job(session, job, result={"results": []}, status="success",
               error=None)
    assert job.status == "success" and job.finished_at is not None


def test_fail_or_retry_then_failed(session):
    job = create_job(session, "comment_screening", {}, total=1)
    job.max_attempts = 2
    session.commit()
    claim_next_job(session)      # attempt=1
    fail_or_retry(session, job, "boom")
    assert job.status == "pending"
    claim_next_job(session)      # attempt=2
    fail_or_retry(session, job, "boom")
    assert job.status == "failed" and job.error == "boom"


def test_set_progress(session):
    job = create_job(session, "comment_screening", {}, total=10)
    set_progress(session, job, 4)
    assert job.progress_done == 4


def test_reset_running(session):
    job = create_job(session, "comment_screening", {}, total=1)
    claim_next_job(session)
    assert reset_running_jobs(session) == 1
    assert get_job(session, job.id).status == "pending"
