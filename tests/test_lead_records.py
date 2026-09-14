"""V1.10.1 线索汇总表（lead_record）读写、就绪判据与回退路径测试。"""
from datetime import datetime, timedelta

from app.api.jobs import finish_job, fail_or_retry
from app.config import settings
from app.models import ApiJob, LeadRecord
from app.services.lead_records import replace_records
from app.services.lead_results import (ensure_marker_for_fresh_db,
                                       _summary_ready, query_lead_results,
                                       write_ready_marker)
from tests.test_lead_results import _acct, _job


def test_records_written_by_finish_job(session):
    """终态落库时同事务物化汇总行（真实写入路径）。"""
    job = ApiJob(id="j1", job_type="profile_analysis", status="running",
                 progress_total=2, progress_done=2,
                 created_at=datetime(2026, 8, 14, 7, 0, 0))
    session.add(job)
    session.commit()
    finish_job(session, job, result={"results": [_acct("u1"), _acct("u2")]},
               status="success", error=None, lead_grades=["H", "C"])
    recs = session.query(LeadRecord).order_by(LeadRecord.idx).all()
    assert [(r.job_id, r.idx, r.account_uid, r.grade) for r in recs] == [
        ("j1", 0, "u1", "H"), ("j1", 1, "u2", "C")]
    # finished_at 与作业一致，列表排序才与旧实现对齐
    assert all(r.finished_at == job.finished_at for r in recs)


def test_records_not_written_for_other_job_types(session):
    """非 profile 作业不落汇总行。"""
    job = ApiJob(id="c1", job_type="comment_screening", status="running",
                 progress_total=1, progress_done=1,
                 created_at=datetime(2026, 8, 14, 7, 0, 0))
    session.add(job)
    session.commit()
    finish_job(session, job, result={"results": [{"comment_id": "c"}]},
               status="success", error=None)
    assert session.query(LeadRecord).count() == 0


def test_records_cleared_on_terminal_failure(session):
    """终态失败清掉旧汇总行，避免列表里留下已废数据。"""
    job = _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
               [_acct("u1"), _acct("u2")])
    assert session.query(LeadRecord).count() == 2
    job.attempt_count = job.max_attempts
    fail_or_retry(session, job, "全部条目处理失败")
    assert session.query(LeadRecord).count() == 0


def test_replace_records_idempotent(session):
    """重跑同一作业不产生重复行（主键为 job_id+idx）。"""
    t = datetime(2026, 8, 14, 8, 0, 0)
    result = {"results": [_acct("u1"), _acct("u2")]}
    replace_records(session, "j1", result, ["H", "A"], t, "success")
    session.commit()
    replace_records(session, "j1", result, ["B", "C"], t, "success")
    session.commit()
    recs = session.query(LeadRecord).order_by(LeadRecord.idx).all()
    assert len(recs) == 2
    assert [r.grade for r in recs] == ["B", "C"]      # 后写覆盖先写


def test_records_skip_non_dict_accounts(session):
    """结果数组里的非字典元素直接跳过，不写汇总行。"""
    replace_records(session, "j1", {"results": [_acct("u1"), "bad", None]},
                    None, datetime(2026, 8, 14, 8, 0, 0), "success")
    session.commit()
    assert [r.account_uid for r in session.query(LeadRecord).all()] == ["u1"]


def test_pagination_split_matches_old_json_order(session):
    """跨作业分页切分点与旧 JSON 展开顺序一致。

    同一 finished_at 的两个作业按作业 id 倒序，单作业内按账号下标升序，
    与旧实现的逐作业展开完全对应。
    """
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "jA", t, [_acct("a0"), _acct("a1"), _acct("a2")])
    _job(session, "jB", t, [_acct("b0"), _acct("b1")])   # 同时间、id 更大
    p1 = query_lead_results(session, page=1, size=2)
    assert p1["total"] == 5
    assert [r["account_uid"] for r in p1["rows"]] == ["b0", "b1"]
    p2 = query_lead_results(session, page=2, size=2)
    assert [r["account_uid"] for r in p2["rows"]] == ["a0", "a1"]
    p3 = query_lead_results(session, page=3, size=2)
    assert [r["account_uid"] for r in p3["rows"]] == ["a2"]


def test_falls_back_when_records_empty(session):
    """汇总表为空（未回填的旧库）时回退 JSON 展开路径，功能不缺失。"""
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="high"), _acct("u2", code="low")], sync=False)
    assert session.query(LeadRecord).count() == 0
    data = query_lead_results(session, page=1, size=20)
    assert [r["account_uid"] for r in data["rows"]] == ["u1", "u2"]
    assert [r["grade"] for r in data["rows"]] == ["H", "B"]
    assert data["total"] == 2


def test_partial_backfill_still_uses_fallback(session, tmp_path, monkeypatch):
    """回填中途（汇总表有数据但就绪标记未写）必须走回退路径。

    否则列表会**静默地**只显示已回填的那部分旧作业——回填按时间升序写入，
    中途失败时汇总表里只有最旧的作业，而列表按时间倒序看的是最新作业，
    结果恰好是最该看到的那批不见了。
    """
    monkeypatch.setattr(settings, "lead_record_ready_marker",
                        str(tmp_path / "not_yet"))
    t_old = datetime(2026, 8, 13, 8, 0, 0)
    t_new = datetime(2026, 8, 14, 8, 0, 0)
    # 旧作业已回填，新作业只存在于 api_job（模拟回填中途）
    _job(session, "j_old", t_old, [_acct("u_old")])
    _job(session, "j_new", t_new, [_acct("u_new")], sync=False)
    assert session.query(LeadRecord).count() == 1        # 汇总表不完整

    data = query_lead_results(session, page=1, size=20)
    assert data["total"] == 2                            # 未被不完整汇总表截断
    assert [r["account_uid"] for r in data["rows"]] == ["u_new", "u_old"]


def test_ready_marker_switches_to_summary_table(session, tmp_path,
                                                monkeypatch):
    """就绪标记存在时切到汇总表路径（这是回填完成后的正式路径）。"""
    marker = tmp_path / "lead_record_ready"
    marker.write_text("2026-09-10", encoding="utf-8")
    monkeypatch.setattr(settings, "lead_record_ready_marker", str(marker))

    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1", code="high"), _acct("u2", code="low")])
    data = query_lead_results(session, page=1, size=20)
    assert data["total"] == 2
    assert [r["grade"] for r in data["rows"]] == ["H", "B"]


def test_fresh_db_gets_marker_so_new_deploy_uses_fast_path(session, tmp_path,
                                                           monkeypatch):
    """全新库（无任何历史作业）启动即标记就绪，不必等"回填"这个空操作。

    否则新部署会一直停在慢路径上——而它没有任何历史数据可回填。
    """
    marker = tmp_path / "lead_record_ready"
    monkeypatch.setattr(settings, "lead_record_ready_marker", str(marker))
    assert ensure_marker_for_fresh_db(session) is True
    assert marker.exists()
    assert _summary_ready(session) is True


def test_historical_jobs_block_fresh_db_marker(session, tmp_path, monkeypatch):
    """有历史作业时不得自动标记就绪，否则回填中途会读到不完整汇总表。"""
    marker = tmp_path / "lead_record_ready"
    monkeypatch.setattr(settings, "lead_record_ready_marker", str(marker))
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0), [_acct("u1")],
         sync=False)
    assert ensure_marker_for_fresh_db(session) is False
    assert not marker.exists()
    assert _summary_ready(session) is False


def test_marker_is_idempotent(session, tmp_path, monkeypatch):
    """重复调用不就绪判定不改写已有标记。"""
    marker = tmp_path / "lead_record_ready"
    monkeypatch.setattr(settings, "lead_record_ready_marker", str(marker))
    marker.write_text("original\n", encoding="utf-8")
    assert ensure_marker_for_fresh_db(session) is True
    assert marker.read_text(encoding="utf-8") == "original\n"


def test_backfill_self_check_writes_marker(session, tmp_path, monkeypatch):
    """回填脚本自检通过后写标记，服务随即切到快路径。"""
    marker = tmp_path / "data" / "lead_record_ready"
    monkeypatch.setattr(settings, "lead_record_ready_marker", str(marker))
    assert _summary_ready(session) is False
    write_ready_marker()
    assert marker.exists()
    assert _summary_ready(session) is True


def test_grade_filter_uses_records(session):
    """等级筛选走汇总表普通列索引，且不读取 api_job.result 大列。"""
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1", code="high"), _acct("u2", code="low"),
                            _acct("u3", code="high")])
    data = query_lead_results(session, grade="H")
    assert data["total"] == 2
    assert [r["account_uid"] for r in data["rows"]] == ["u1", "u3"]


def test_date_filter_uses_records(session):
    """日期筛选按汇总表 finished_at 过滤，口径仍为东八区自然日。"""
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0), [_acct("u1")])
    _job(session, "j2", datetime(2026, 8, 13, 8, 0, 0), [_acct("u2")])
    data = query_lead_results(session, date_from="2026-08-14",
                             date_to="2026-08-15")
    assert [r["account_uid"] for r in data["rows"]] == ["u1"]


def test_records_carry_bool_none_distinct_from_false(session):
    """bool 与 None 不得混淆：False 落库仍须是 False，缺键才是 None。"""
    acct = _acct("u1")
    acct["is_car_owner"] = False
    acct["has_purchase_intent"] = None
    replace_records(session, "j1", {"results": [acct]}, None,
                    datetime(2026, 8, 14, 8, 0, 0), "success")
    session.commit()
    rec = session.query(LeadRecord).one()
    assert rec.is_car_owner is False
    assert rec.has_purchase_intent is None


def test_processed_at_kept_as_string(session):
    """processed_at 为文本时间戳，按原值透出，不做时区再转换。"""
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1")])
    row = query_lead_results(session, page=1, size=20)["rows"][0]
    assert row["processed_at"] == "2026-08-14T00:00:00+08:00"
    # finished_at 由作业补齐（UTC → 东八区 ISO）
    assert row["finished_at"].startswith("2026-08-14T16:00:00")


def test_export_csv_reads_records(session):
    """CSV 导出走汇总表，字段与旧实现一致。"""
    from app.services.lead_results import export_lead_results_csv
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0), [_acct("u1")])
    csv_text = export_lead_results_csv(session)
    assert "账号UID" in csv_text and "u1" in csv_text
    assert "分析" in csv_text          # analysis 仍在导出列中


def test_keep_analysis_for_export_only(session):
    """analysis 仅供导出与详情，列表接口不返回给页面渲染成本无关。"""
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1")])
    rec = session.query(LeadRecord).one()
    assert rec.analysis == "分析"


def test_sync_ignores_extra_job_columns(session):
    """汇总行写入不依赖 lead_grades 存在（历史数据为 NULL）。"""
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="medium")], lead_grades=None)
    rec = session.query(LeadRecord).one()
    assert rec.grade == "A"            # medium → A（code 反推）


def test_finished_at_ordering_is_stable_across_pages(session):
    """翻页不重不漏：同一作业的账号不会被拆到不同页的重复位置。"""
    base = datetime(2026, 8, 14, 8, 0, 0)
    for i in range(3):
        _job(session, f"j{i}", base + timedelta(minutes=i),
             [_acct(f"u{i}_{k}") for k in range(4)])
    seen = []
    for page in (1, 2, 3):
        seen += [r["account_uid"]
                 for r in query_lead_results(session, page=page, size=4)["rows"]]
    assert len(seen) == 12 and len(set(seen)) == 12
