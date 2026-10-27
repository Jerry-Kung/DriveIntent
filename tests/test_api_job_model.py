from app.models import ApiJob


def test_api_job_defaults(session):
    job = ApiJob(id="job-1", job_type="comment_screening",
                 request_payload={"comments": []})
    session.add(job)
    session.commit()
    row = session.get(ApiJob, "job-1")
    assert row.status == "pending"
    assert row.progress_total == 0
    assert row.progress_done == 0
    assert row.max_attempts == 3
    assert row.attempt_count == 0
    assert row.finished_at is None
