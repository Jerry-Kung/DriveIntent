"""端到端：Excel 导入 → API 启动分析 → Worker 跑完 → 线索可查可导出。"""
import json

import pandas as pd
from fastapi.testclient import TestClient

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.main import app
from app.skills.executor import SkillExecutor
from app.web.routes import get_db
from app.workflow.worker import Worker
from tests.test_analysis_polish import POLISH_OK_JSON
from tests.test_comment_screening import _item
from tests.test_user_analysis import LEAD_JSON, REVIEW_CONFIRMED_JSON
from tests.test_user_filter import NOT_FILTERED_JSON


def _xlsx(tmp_path):
    rows = [
        {"aweme_id": "1001", "title": "全新坦克300 #SUV", "desc": "8缸",
         "cover_url": "", "nickname": "买家", "sec_uid": "sec_1",
         "comment_id": "9001", "content": "上海落地多少钱",
         "create_time": 1783783725},
        {"aweme_id": "1001", "title": "全新坦克300 #SUV", "desc": "8缸",
         "cover_url": "", "nickname": "路人", "sec_uid": "sec_2",
         "comment_id": "9002", "content": "厉害",
         "create_time": 1783783726},
    ]
    path = tmp_path / "e2e.xlsx"
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


async def test_e2e_pipeline(tmp_path, session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    client = TestClient(app)

    # 1. 导入
    with open(_xlsx(tmp_path), "rb") as f:
        r = client.post("/api/import", files={"file": ("e2e.xlsx", f)})
    assert r.json()["comments_new"] == 2

    # 2. 启动分析
    assert client.post("/api/analysis/start").json()["created"] == 1

    # 3. Mock LLM + Worker 跑完全部任务
    from app.models import Comment
    ids = {c.external_id: c.id for c in session.query(Comment).all()}
    provider = MockProvider()
    provider.queue(
        json.dumps({"brand": "坦克", "model": "坦克300",
                    "analysis_notes": ""}, ensure_ascii=False),
        json.dumps({"items": [_item(ids["9001"]),
                              _item(ids["9002"], purchase=False)]},
                   ensure_ascii=False),
        NOT_FILTERED_JSON,
        LEAD_JSON.replace("__CID__", str(ids["9001"])),
        REVIEW_CONFIRMED_JSON, POLISH_OK_JSON)
    worker = Worker(lambda: session, SkillExecutor(LLMGateway(provider)))
    while await worker.run_once():
        pass

    # 4. 线索可查：只有 sec_1 成为线索
    leads = client.get("/api/leads").json()
    assert len(leads) == 1
    assert leads[0]["nickname"] == "买家" and leads[0]["grade"] == "H"

    # 5. 导出 CSV
    assert "买家" in client.get("/api/leads/export").text

    # 6. 进度接口无失败任务
    progress = client.get("/api/analysis/progress").json()
    for counts in progress.values():
        assert counts.get("failed", 0) == 0
