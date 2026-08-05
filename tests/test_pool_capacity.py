"""P0 修复回归测试：连接池耗尽的两个根因。

根因 1（容量）：FastAPI 同步端点跑在 anyio 默认线程池（40 槽）中，每个请求
经 get_db() 独占一条连接直到请求结束。若线程池槽位数 > 连接池容量
(pool_size + max_overflow)，超出的请求必然阻塞在 pool.connect() 上，
等满 pool_timeout 后抛 QueuePool TimeoutError——worker 的 claim_next 与
Web 请求抢同一个池，也会一并被拖垮。

根因 2（体积）：account_homepage_screenshot 传 base64 时单作业 payload 可达
25MB（实测截图占 99.9%），写入期间连接被长时间占用，放大了根因 1。
改为只接受 URL 后，DB 只存引用，单行降回 KB 级。
"""
import pytest
from pydantic import ValidationError

from app.api.schemas import ProfileAnalysisRequest
from app.config import Settings


# ---------- 根因 1：线程池槽位数必须 ≤ 连接池容量 ----------

def test_threadpool_slots_not_exceed_pool_capacity():
    """并发同步请求上限不得超过连接池容量，否则必然耗尽。"""
    s = Settings(_env_file=None)
    capacity = s.db_pool_size + s.db_max_overflow
    assert s.web_threadpool_slots <= capacity, (
        f"线程池槽位 {s.web_threadpool_slots} > 连接池容量 {capacity}，"
        "超出的并发请求会阻塞至 pool_timeout 并抛 QueuePool TimeoutError")


@pytest.mark.asyncio
async def test_runtime_threadpool_limiter_is_capped():
    """应用启动时必须把 anyio 默认线程池收敛到配置值（默认 40 太大）。"""
    import anyio.to_thread

    from app.main import _apply_threadpool_limit

    _apply_threadpool_limit()
    limiter = anyio.to_thread.current_default_thread_limiter()
    from app.config import settings
    assert limiter.total_tokens == settings.web_threadpool_slots


# ---------- 根因 2：截图只接受 URL ----------

def _account(shot: str) -> dict:
    return {"account_uid": "u1", "account_name": "张三",
            "account_homepage_screenshot": shot, "comment_history": []}


def test_screenshot_accepts_http_url():
    req = ProfileAnalysisRequest(
        accounts=[_account("https://cdn.example.com/a.png")])
    assert req.accounts[0].account_homepage_screenshot == \
        "https://cdn.example.com/a.png"


def test_screenshot_accepts_empty_string():
    """空串是文档定义的降级路径，必须继续放行。"""
    req = ProfileAnalysisRequest(accounts=[_account("")])
    assert req.accounts[0].account_homepage_screenshot == ""


def test_screenshot_rejects_data_uri_base64():
    with pytest.raises(ValidationError) as e:
        ProfileAnalysisRequest(
            accounts=[_account("data:image/png;base64,AAAA")])
    assert "URL" in str(e.value)


def test_screenshot_rejects_bare_base64():
    with pytest.raises(ValidationError) as e:
        ProfileAnalysisRequest(accounts=[_account("iVBORw0KGgoAAAANSU" * 50)])
    assert "URL" in str(e.value)


def test_vision_builds_message_from_url():
    """vision 层只应原样透传 URL，不再拼 data-URI。"""
    from app.skills.vision import build_image_message

    msgs = build_image_message("描述这张图", "https://cdn.example.com/a.png")
    assert msgs[0]["content"][1]["image_url"]["url"] == \
        "https://cdn.example.com/a.png"


def test_vision_empty_screenshot_falls_back_to_text_only():
    from app.skills.vision import build_image_message

    msgs = build_image_message("描述这张图", "")
    assert msgs == [{"role": "user", "content": "描述这张图"}]
