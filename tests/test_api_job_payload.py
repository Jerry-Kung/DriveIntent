"""连接池风暴修复：轮询不加载大字段 + 终态剥离截图 payload。"""
from sqlalchemy import event

from app.api.jobs import (claim_next_job, create_job, fail_or_retry,
                          finish_job, get_job)


def _capture_statements(session):
    statements = []
    engine = session.get_bind()

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    return statements


def profile_payload() -> dict:
    # 每次调用返回全新字典：剥离逻辑是就地修改，共享常量会跨测试污染
    return {"accounts": [
        {"account_uid": "u1", "account_name": "张三",
         "account_homepage_screenshot": "A" * 5000, "comment_history": []},
        {"account_uid": "u2", "account_name": "李四",
         "account_homepage_screenshot": "", "comment_history": []},
    ]}


def test_get_job_does_not_select_request_payload(session):
    job = create_job(session, "profile_analysis", profile_payload(), total=2)
    session.expire_all()
    statements = _capture_statements(session)
    fetched = get_job(session, job.id)
    assert fetched is not None
    polling = [s for s in statements if "api_job" in s]
    assert polling, "get_job 应发出查询"
    assert all("request_payload" not in s for s in polling), \
        "状态轮询不应搬运 request_payload 大列"


def test_claim_does_not_select_request_payload_but_loads_on_access(session):
    create_job(session, "profile_analysis", profile_payload(), total=2)
    session.expire_all()
    statements = _capture_statements(session)
    job = claim_next_job(session)
    claim_selects = [s for s in statements
                     if s.strip().upper().startswith("SELECT")
                     and "api_job" in s]
    assert all("request_payload" not in s for s in claim_selects), \
        "认领查询不应搬运 request_payload 大列"
    # worker 随后显式访问时必须仍能按需加载
    assert job.request_payload["accounts"][0]["account_uid"] == "u1"


def test_finish_job_strips_screenshots(session):
    job = create_job(session, "profile_analysis", profile_payload(), total=2)
    claim_next_job(session)
    finish_job(session, job, result={"results": []}, status="success",
               error=None)
    session.expire_all()
    saved = get_job(session, job.id).request_payload
    assert saved["accounts"][0]["account_homepage_screenshot"] == ""
    # 其余字段保持不动
    assert saved["accounts"][0]["account_uid"] == "u1"
    assert saved["accounts"][1]["account_name"] == "李四"


def test_fail_terminal_strips_but_retry_keeps(session):
    job = create_job(session, "profile_analysis", profile_payload(), total=2)
    job.max_attempts = 2
    session.commit()
    claim_next_job(session)          # attempt=1
    fail_or_retry(session, job, "boom")
    assert job.status == "pending"
    # 还会重试：payload 必须完整保留
    assert job.request_payload["accounts"][0][
        "account_homepage_screenshot"] == "A" * 5000
    claim_next_job(session)          # attempt=2 → 终态 failed
    fail_or_retry(session, job, "boom")
    assert job.status == "failed"
    assert job.request_payload["accounts"][0][
        "account_homepage_screenshot"] == ""


def test_finish_job_leaves_comment_screening_payload_untouched(session):
    payload = {"comments": [{"comment_id": "c1", "comment_content": "好车"}]}
    job = create_job(session, "comment_screening", payload, total=1)
    claim_next_job(session)
    finish_job(session, job, result={"results": []}, status="success",
               error=None)
    assert job.request_payload == payload

