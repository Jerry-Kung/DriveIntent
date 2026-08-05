"""截图暂存区与识图文本化落库（V1.4.4）。

覆盖：
  - POST 提交后库中不得留存 base64（根因：单行 12.98MB 冻结事件循环）
  - worker 认领时从暂存区读回截图，识图文本写回 payload
  - 存量作业（payload 内联 base64）仍能正常识图
  - 终态删暂存文件；重试期间保留
  - 暂存文件缺失时降级为无截图继续，作业不失败
"""
import json
import os

import pytest

from app.api import staging
from app.api.jobs import create_job, get_job
from app.api.worker import ApiJobWorker
from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.skills.executor import SkillExecutor

LEAD_JSON = ('{"lead_grade": "H", "is_valid_lead": true,'
             ' "lead_summary": "s", "evidence_comment_ids": ["u1:0"],'
             ' "analysis_text": "a", "profile_summary": "p"}')
VISION_JSON = '{"content_theme": "汽车"}'
BASE64 = "A" * 5000

ACCOUNT = {"account_uid": "u1", "account_name": "昵称",
           "account_homepage_screenshot": BASE64,
           "comment_history": [
               {"video_title": "试驾", "comment_content": "这车多少钱",
                "comment_time": "2026-07-19T14:23:00+08:00",
                "comment_like_count": 1}]}


@pytest.fixture(autouse=True)
def staging_dir(tmp_path, monkeypatch):
    """把暂存目录指向临时路径，避免污染真实 data/staging。"""
    d = tmp_path / "staging"
    monkeypatch.setattr(staging.settings, "screenshot_staging_dir", str(d))
    return d


class _Factory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


def _worker(session, *responses):
    provider = MockProvider()
    provider.queue(*responses)
    gateway = LLMGateway(provider)
    return ApiJobWorker(_Factory(session), SkillExecutor(gateway), gateway,
                        poll_interval=0.0)


# --- 提交阶段：base64 不入库 ------------------------------------------

def test_extract_screenshots_empties_payload():
    payload = {"accounts": [dict(ACCOUNT), dict(ACCOUNT, account_uid="u2",
                                                account_homepage_screenshot="")]}
    shots = staging.extract_screenshots(payload)

    assert shots == {"0": BASE64}
    assert payload["accounts"][0]["account_homepage_screenshot"] == ""
    # 其余字段不受影响
    assert payload["accounts"][0]["account_uid"] == "u1"


def test_save_and_load_roundtrip(staging_dir):
    staging.save("job-1", {"0": BASE64})
    assert staging.load("job-1") == {"0": BASE64}
    assert (staging_dir / "job-1.json").exists()


def test_load_missing_file_returns_empty():
    """暂存文件缺失时返回空 dict（降级为无截图，不抛错）。"""
    assert staging.load("no-such-job") == {}


def test_load_corrupt_file_returns_empty(staging_dir):
    staging.ensure_dir()
    (staging_dir / "bad.json").write_text("{not json", encoding="utf-8")
    assert staging.load("bad") == {}


def test_discard_removes_file(staging_dir):
    staging.save("job-2", {"0": BASE64})
    staging.discard("job-2")
    assert not (staging_dir / "job-2.json").exists()
    staging.discard("job-2")   # 幂等：已删除再删不报错


def test_reap_orphans_keeps_active(staging_dir):
    staging.save("active", {"0": BASE64})
    staging.save("orphan", {"0": BASE64})

    removed = staging.reap_orphans({"active"})

    assert removed == 1
    assert (staging_dir / "active.json").exists()
    assert not (staging_dir / "orphan.json").exists()


# --- 执行阶段：识图 → 文本落库 ----------------------------------------

@pytest.mark.asyncio
async def test_worker_reads_staged_screenshot_and_stores_text(session):
    """认领时从暂存区取回截图识图，终态写回纯文本、不留 base64。"""
    payload = {"accounts": [dict(ACCOUNT, account_homepage_screenshot="")]}
    job = create_job(session, "profile_analysis", payload, total=1)
    staging.save(job.id, {"0": BASE64})

    assert await _worker(session, VISION_JSON, LEAD_JSON).run_once() is True

    session.expire_all()
    saved = get_job(session, job.id)
    acc = saved.request_payload["accounts"][0]
    assert saved.status in ("success", "partial")
    assert acc["account_homepage_screenshot"] == ""
    assert acc["homepage_vision_text"] == VISION_JSON
    assert staging.load(job.id) == {}, "终态后暂存文件应已删除"


@pytest.mark.asyncio
async def test_legacy_inline_screenshot_still_works(session):
    """存量作业 payload 内联 base64（V1.4.4 前提交），无暂存文件也须识图。"""
    payload = {"accounts": [dict(ACCOUNT)]}          # 截图仍内联
    job = create_job(session, "profile_analysis", payload, total=1)

    assert await _worker(session, VISION_JSON, LEAD_JSON).run_once() is True

    session.expire_all()
    acc = get_job(session, job.id).request_payload["accounts"][0]
    assert acc["account_homepage_screenshot"] == "", "存量 base64 须被清空"
    assert acc["homepage_vision_text"] == VISION_JSON


@pytest.mark.asyncio
async def test_missing_staging_degrades_to_no_screenshot(session):
    """暂存文件丢失时降级为无截图继续，作业不失败（既定决策）。"""
    payload = {"accounts": [dict(ACCOUNT, account_homepage_screenshot="")]}
    job = create_job(session, "profile_analysis", payload, total=1)
    # 不写暂存文件，模拟人工清理/磁盘故障

    assert await _worker(session, LEAD_JSON).run_once() is True

    session.expire_all()
    saved = get_job(session, job.id)
    assert saved.status == "success"
    assert saved.result["results"][0]["error"] is None


@pytest.mark.asyncio
async def test_staging_kept_while_retrying(session):
    """失败重试期间暂存截图必须保留，否则重试将无图可识。"""
    class _Boom:
        async def run(self, *a, **kw):
            raise RuntimeError("boom")

    payload = {"accounts": [dict(ACCOUNT, account_homepage_screenshot="")]}
    job = create_job(session, "profile_analysis", payload, total=1)
    staging.save(job.id, {"0": BASE64})

    gateway = LLMGateway(MockProvider())
    worker = ApiJobWorker(_Factory(session), _Boom(), gateway,
                          poll_interval=0.0)
    assert await worker.run_once() is True

    session.expire_all()
    assert get_job(session, job.id).status == "pending"
    assert staging.load(job.id) == {"0": BASE64}, "重试期间暂存不得删除"


# --- 端到端：提交接口不落 base64 --------------------------------------

def test_submit_endpoint_does_not_persist_base64(session, monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.routes as routes
    from app.main import app

    monkeypatch.setattr(routes, "SessionLocal", _Factory(session))
    monkeypatch.setattr(routes.settings, "api_keys", "")

    client = TestClient(app)
    resp = client.post("/api/v1/profile-analysis",
                       json={"accounts": [dict(ACCOUNT)]})

    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    session.expire_all()
    saved = get_job(session, job_id)
    assert saved.request_payload["accounts"][0][
        "account_homepage_screenshot"] == "", "base64 不得入库"
    assert staging.load(job_id) == {"0": BASE64}, "截图应落入暂存区"


def test_staging_file_is_valid_json(staging_dir):
    """暂存文件为普通 JSON，便于运维排查与人工清理。"""
    staging.save("j", {"0": "abc"})
    with open(staging_dir / "j.json", encoding="utf-8") as f:
        assert json.load(f) == {"0": "abc"}
    assert not os.path.exists(staging_dir / "j.json.tmp"), "临时文件应已改名"
