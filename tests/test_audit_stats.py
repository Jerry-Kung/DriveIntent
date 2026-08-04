from sqlalchemy import inspect


def test_audit_indexes_declared(session):
    insp = inspect(session.get_bind())
    llm_names = {i["name"] for i in insp.get_indexes("llm_call_log")}
    assert "ix_llm_call_created" in llm_names
    job_names = {i["name"] for i in insp.get_indexes("api_job")}
    assert "ix_api_job_finished" in job_names
