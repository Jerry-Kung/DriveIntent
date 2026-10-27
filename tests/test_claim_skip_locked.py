"""认领查询必须带 FOR UPDATE SKIP LOCKED，防止多 worker 重复认领。

claim_next / claim_next_job 此前是"普通 SELECT 再 UPDATE"：并发 worker 会
读到同一条 pending 记录并各自置为 running，导致同一任务被重复执行。
加锁后（MySQL 8.0+）：先到的事务锁住该行，其余 worker 跳过已锁行认领下一条。
测试用 MySQL 方言编译认领语句断言锁子句；SQLite 测试库会忽略 FOR UPDATE，
不影响其余用例。
"""
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Query

from app.api.jobs import claim_next_job
from app.workflow.tasks import claim_next


def _capture_claim_sql(monkeypatch, fn, session) -> str:
    """捕获 fn 内部执行的认领查询，返回其 MySQL 方言 SQL 文本。"""
    captured: list[Query] = []
    orig_first = Query.first

    def spy_first(self):
        captured.append(self)
        return orig_first(self)

    monkeypatch.setattr(Query, "first", spy_first)
    fn(session)
    assert len(captured) == 1
    return str(captured[0].statement.compile(dialect=mysql.dialect()))


def test_claim_next_uses_skip_locked(session, monkeypatch):
    sql = _capture_claim_sql(monkeypatch, claim_next, session)
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_claim_next_job_uses_skip_locked(session, monkeypatch):
    sql = _capture_claim_sql(monkeypatch, claim_next_job, session)
    assert "FOR UPDATE SKIP LOCKED" in sql
