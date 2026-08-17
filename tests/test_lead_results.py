from datetime import datetime, timedelta

from app.models import ApiJob, LlmCallLog
from app.services.lead_results import (export_lead_results_csv, grade_of,
                                       query_lead_results)


def _result(accounts):
    return {"results": accounts}


def _acct(uid, code="high", score=90, summary="摘要"):
    return {"account_uid": uid, "has_value": True,
            "intent_level_code": code, "value_score": score,
            "profile_summary": summary, "profile_tags": [],
            "analysis": "分析", "processed_at": "2026-08-14T00:00:00+08:00",
            "error": None}


def _job(session, job_id, finished_at, accounts, status="success",
         payload=None):
    job = ApiJob(id=job_id, job_type="profile_analysis", status=status,
                 result=_result(accounts), progress_total=len(accounts),
                 progress_done=len(accounts),
                 created_at=finished_at - timedelta(minutes=5),
                 finished_at=finished_at, request_payload=payload)
    session.add(job)
    session.commit()
    return job


def test_grade_of():
    assert grade_of({"intent_level_code": "high"}) == "H"
    assert grade_of({"intent_level_code": "medium"}) == "A"
    assert grade_of({"intent_level_code": "low"}) == "B"
    assert grade_of({"intent_level_code": None}) == "C"
    assert grade_of({}) == "C"


def test_flatten_and_order(session):
    t1 = datetime(2026, 8, 14, 8, 0, 0)
    t2 = datetime(2026, 8, 14, 9, 0, 0)
    _job(session, "j1", t1, [_acct("u1"), _acct("u2", code="low", score=60)])
    _job(session, "j2", t2, [_acct("u3", code="medium", score=77)])
    data = query_lead_results(session, page=1, size=20)
    assert data["total"] == 3
    # 时间倒序：j2（更晚）在前，job 内按 results 顺序
    assert [r["account_uid"] for r in data["rows"]] == ["u3", "u1", "u2"]
    assert data["rows"][0]["job_id"] == "j2"
    assert data["rows"][0]["grade"] == "A"


def test_pagination_across_jobs(session):
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct(f"u{i}") for i in range(3)])
    _job(session, "j2", t + timedelta(minutes=1),
         [_acct(f"u{i}") for i in range(3, 5)])
    data = query_lead_results(session, page=1, size=2)
    assert data["total"] == 5
    assert [r["account_uid"] for r in data["rows"]] == ["u3", "u4"]
    data2 = query_lead_results(session, page=2, size=2)
    assert [r["account_uid"] for r in data2["rows"]] == ["u0", "u1"]
    data3 = query_lead_results(session, page=3, size=2)
    assert [r["account_uid"] for r in data3["rows"]] == ["u2"]


def test_grade_filter(session):
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1"), _acct("u2", code="low"),
                            _acct("u3", code=None)])
    data = query_lead_results(session, grade="H")
    assert data["total"] == 1
    assert data["rows"][0]["account_uid"] == "u1"


def test_date_filter(session):
    # 东八区 2026-08-14 自然日 = UTC [08-13 16:00, 08-14 16:00)
    in_day = datetime(2026, 8, 14, 8, 0, 0)
    before = datetime(2026, 8, 13, 8, 0, 0)
    _job(session, "j1", in_day, [_acct("u1")])
    _job(session, "j2", before, [_acct("u2")])
    data = query_lead_results(session, date_from="2026-08-14",
                              date_to="2026-08-15")
    assert [r["account_uid"] for r in data["rows"]] == ["u1"]


def test_detail_data(session):
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1")],
         payload={"accounts": [{"account_name": "测试昵称",
                                "comment_history": [],
                                "homepage_vision_text": "识图文本"}]})
    from app.services.lead_results import lead_detail_data
    d = lead_detail_data(session, "j1", 0)
    assert d is not None
    assert d["acct"]["account_uid"] == "u1"
    assert d["input"]["account_name"] == "测试昵称"
    assert d["grade"] == "H"


def test_detail_data_llm_calls(session):
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1")])
    session.add(LlmCallLog(skill_id="user_lead_analysis",
                           skill_version="1.7.0", model_name="m",
                           created_at=t - timedelta(seconds=1)))
    session.commit()
    from app.services.lead_results import lead_detail_data
    d = lead_detail_data(session, "j1", 0)
    assert [c["skill_id"] for c in d["calls"]] == ["user_lead_analysis"]


def test_detail_data_missing(session):
    from app.services.lead_results import lead_detail_data
    assert lead_detail_data(session, "nope", 0) is None
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1")])
    assert lead_detail_data(session, "j1", 9) is None


def test_export_csv(session):
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1", code="high", score=90)])
    csv_text = export_lead_results_csv(session)
    assert "账号UID" in csv_text
    assert "u1" in csv_text


def test_export_escapes_formula(session):
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("=cmd", code="high")])
    csv_text = export_lead_results_csv(session)
    assert "'=cmd" in csv_text
