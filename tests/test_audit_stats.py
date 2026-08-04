from datetime import datetime

from sqlalchemy import inspect

from app.services.audit_stats import utc_range, job_stats, llm_stats
from app.models import ApiJob, LlmCallLog


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


def _job(job_id, created, finished=None, status="pending",
         job_type="comment_screening"):
    return ApiJob(id=job_id, job_type=job_type, status=status,
                  created_at=created, finished_at=finished)


def test_job_stats_day_buckets_timezone_and_status(session):
    # UTC 15:30 → 东八区 08-01 23:30；UTC 16:30 → 东八区 08-02 00:30
    session.add_all([
        _job("j1", datetime(2026, 8, 1, 15, 30),
             finished=datetime(2026, 8, 1, 15, 40), status="success"),
        _job("j2", datetime(2026, 8, 1, 16, 30)),          # pending 只计接收
        _job("j3", datetime(2026, 8, 1, 16, 40),
             finished=datetime(2026, 8, 1, 17, 0), status="failed"),
        _job("j4", datetime(2026, 8, 1, 16, 50),
             finished=datetime(2026, 8, 1, 17, 10), status="partial",
             job_type="profile_analysis"),
    ])
    session.commit()
    rows = job_stats(session, "day",
                     datetime(2026, 7, 30, 16), datetime(2026, 8, 3, 16))
    by_key = {(r["bucket"], r["job_type"]): r for r in rows}
    r1 = by_key[("2026-08-01", "comment_screening")]
    assert r1["received"] == 1 and r1["success"] == 1 and r1["failed"] == 0
    r2 = by_key[("2026-08-02", "comment_screening")]
    assert r2["received"] == 2 and r2["failed"] == 1 and r2["success"] == 0
    r3 = by_key[("2026-08-02", "profile_analysis")]
    assert r3["received"] == 1 and r3["partial"] == 1
    # 倒序：最新桶在前
    assert rows[0]["bucket"] >= rows[-1]["bucket"]


def test_job_stats_hour_buckets(session):
    session.add(_job("j1", datetime(2026, 8, 1, 4, 10)))  # 东八区 12:10
    session.commit()
    rows = job_stats(session, "hour",
                     datetime(2026, 8, 1, 0), datetime(2026, 8, 1, 8))
    assert rows[0]["bucket"] == "2026-08-01 12:00"
    assert rows[0]["received"] == 1


def test_job_stats_empty(session):
    assert job_stats(session, "day",
                     datetime(2026, 7, 30), datetime(2026, 8, 3)) == []


def _call(created, skill="comment_lead_screening", model="m1",
          pt=100, ct=50, error=None, dur=800):
    return LlmCallLog(skill_id=skill, model_name=model, prompt_tokens=pt,
                      completion_tokens=ct, duration_ms=dur, error=error,
                      created_at=created)


def test_llm_stats_grouping_sums_and_errors(session):
    day = datetime(2026, 8, 1, 4, 0)  # 东八区 08-01 12:00
    session.add_all([
        _call(day, pt=100, ct=50, dur=600),
        _call(day, pt=200, ct=70, dur=1000, error="超时"),
        _call(day, skill="user_lead_analysis", model="m2", pt=999, ct=1),
    ])
    session.commit()
    rows = llm_stats(session, "day",
                     datetime(2026, 7, 31, 16), datetime(2026, 8, 1, 16))
    by_key = {(r["skill_id"], r["model_name"]): r for r in rows}
    r1 = by_key[("comment_lead_screening", "m1")]
    assert r1["bucket"] == "2026-08-01"
    assert r1["calls"] == 2 and r1["errors"] == 1
    assert r1["prompt_tokens"] == 300 and r1["completion_tokens"] == 120
    assert r1["avg_duration_ms"] == 800
    r2 = by_key[("user_lead_analysis", "m2")]
    assert r2["calls"] == 1 and r2["errors"] == 0
    assert r2["prompt_tokens"] == 999


def test_llm_stats_range_filter(session):
    session.add(_call(datetime(2026, 8, 1, 4, 0)))
    session.commit()
    assert llm_stats(session, "day",
                     datetime(2026, 8, 2, 16), datetime(2026, 8, 3, 16)) == []

