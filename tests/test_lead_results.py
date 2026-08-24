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
         payload=None, lead_grades=None):
    job = ApiJob(id=job_id, job_type="profile_analysis", status=status,
                 result=_result(accounts), progress_total=len(accounts),
                 progress_done=len(accounts),
                 created_at=finished_at - timedelta(minutes=5),
                 finished_at=finished_at, request_payload=payload,
                 lead_grades=lead_grades)
    session.add(job)
    session.commit()
    return job


def test_grade_of():
    assert grade_of({"intent_level_code": "high"}) == "H"
    assert grade_of({"intent_level_code": "medium"}) == "A"
    assert grade_of({"intent_level_code": "low"}) == "B"
    assert grade_of({"intent_level_code": None}) == "C"
    assert grade_of({}) == "C"


def test_grade_of_internal_grade_wins():
    # V1.7.3：lead_grades 提供的真实 HABC 优先于 code 反推
    # （对外已多对一：A 与 H 均映射 high、B 与 C 均映射 low）
    assert grade_of({"intent_level_code": "high"}, "A") == "A"
    assert grade_of({"intent_level_code": "high"}, "H") == "H"
    assert grade_of({"intent_level_code": "low"}, "C") == "C"
    assert grade_of({"intent_level_code": "low"}, "B") == "B"


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


def test_grades_read_from_lead_grades_by_index(session):
    # V1.7.3: lead_grades provides the true HABC by index, takes priority
    # over code-based reversal. Use accounts whose code differs from the
    # internal grade to prove the read comes from lead_grades.
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t,
         [_acct("u1", code="high"), _acct("u2", code="low"),
          _acct("u3", code="medium")],
         lead_grades=["A", "C", "B"])
    data = query_lead_results(session, page=1, size=20)
    assert [r["grade"] for r in data["rows"]] == ["A", "C", "B"]


def test_grades_fallback_when_lead_grades_null(session):
    # Old data (lead_grades NULL) falls back to code reversal:
    # high->H, low->B, medium->A
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t,
         [_acct("u1", code="high"), _acct("u2", code="low"),
          _acct("u3", code="medium")])
    data = query_lead_results(session, page=1, size=20)
    assert [r["grade"] for r in data["rows"]] == ["H", "B", "A"]


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
                           job_id="j1", account_uid="u1",
                           created_at=t - timedelta(seconds=1)))
    session.commit()
    from app.services.lead_results import lead_detail_data
    d = lead_detail_data(session, "j1", 0)
    assert [c["skill_id"] for c in d["calls"]] == ["user_lead_analysis"]


def test_detail_llm_precise_matching_no_cross_job_leak(session):
    """V1.7.1：精确匹配：j1 和 j2 时间窗重叠，详情只返回 j1 自己的调用。"""
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1")])
    _job(session, "j2", t + timedelta(seconds=30), [_acct("u2")])
    session.add(LlmCallLog(skill_id="s1", job_id="j1", account_uid="u1",
                           created_at=t))
    session.add(LlmCallLog(skill_id="s2", job_id="j2", account_uid="u2",
                           created_at=t + timedelta(seconds=10)))
    session.commit()
    from app.services.lead_results import lead_detail_data
    d = lead_detail_data(session, "j1", 0)
    assert len(d["calls"]) == 1
    assert d["calls"][0]["skill_id"] == "s1"


def test_detail_llm_no_cross_account_leak(session):
    """V1.7.1：同作业多账号，详情只展示该账号自身的调用，不串其他账号。"""
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1"), _acct("u2")])
    session.add(LlmCallLog(skill_id="s1_for_u1", job_id="j1",
                           account_uid="u1", created_at=t))
    session.add(LlmCallLog(skill_id="s2_for_u2", job_id="j1",
                           account_uid="u2", created_at=t))
    session.commit()
    from app.services.lead_results import lead_detail_data
    d = lead_detail_data(session, "j1", 0)
    assert len(d["calls"]) == 1
    assert d["calls"][0]["skill_id"] == "s1_for_u1"


def test_detail_llm_fallback_when_no_job_id(session):
    """V1.7.1 回退：旧数据 job_id 为 NULL，回退时间窗近似。"""
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1")])
    session.add(LlmCallLog(skill_id="s1", job_id=None, account_uid=None,
                           created_at=t - timedelta(seconds=1)))
    session.commit()
    from app.services.lead_results import lead_detail_data
    d = lead_detail_data(session, "j1", 0)
    assert [c["skill_id"] for c in d["calls"]] == ["s1"]


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
