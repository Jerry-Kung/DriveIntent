from datetime import datetime

from sqlalchemy import inspect

from app.services.audit_stats import utc_range


def test_audit_indexes_declared(session):
    insp = inspect(session.get_bind())
    llm_names = {i["name"] for i in insp.get_indexes("llm_call_log")}
    assert "ix_llm_call_created" in llm_names
    job_names = {i["name"] for i in insp.get_indexes("api_job")}
    assert "ix_api_job_finished" in job_names


def test_utc_range_day_covers_local_days():
    # 东八区当前时刻 2026-08-02 01:30（= UTC 2026-08-01 17:30）
    # span=2 → 覆盖东八区 08-01、08-02 两个自然天
    start, end = utc_range("day", 2, now_utc=datetime(2026, 8, 1, 17, 30))
    assert start == datetime(2026, 7, 31, 16, 0)   # 东八区 08-01 00:00
    assert end == datetime(2026, 8, 2, 16, 0)      # 东八区 08-03 00:00


def test_utc_range_hour_covers_current_hour():
    # UTC 17:30 = 东八区 01:30，span=3 → 东八区 23:00/00:00/01:00 三个小时桶
    start, end = utc_range("hour", 3, now_utc=datetime(2026, 8, 1, 17, 30))
    assert start == datetime(2026, 8, 1, 15, 0)
    assert end == datetime(2026, 8, 1, 18, 0)
