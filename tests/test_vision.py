from app.skills.vision import build_image_message


def test_url_screenshot():
    msgs = build_image_message("描述这张图", "https://cdn/x.png")
    content = msgs[0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"] == "https://cdn/x.png"


def test_base64_no_longer_wrapped_passed_through_as_is():
    """截图改为只接受 URL 后，vision 层不再拼 data-URI。

    base64 已在 schema 层（AccountObject）被拒，正常流程走不到这里；
    此处只锁定"不再做 data: 包装"这一行为，避免回退。
    """
    msgs = build_image_message("t", "iVBORw0KGgoAAAA")
    url = msgs[0]["content"][1]["image_url"]["url"]
    assert url == "iVBORw0KGgoAAAA"
    assert not url.startswith("data:")


def test_empty_screenshot_text_only():
    msgs = build_image_message("只有文字", "")
    assert msgs[0]["content"] == "只有文字"


import pytest
from app.llm.mock import MockProvider


@pytest.mark.asyncio
async def test_mock_handles_image_content():
    p = MockProvider()
    p.queue("这是一张科技博主主页")
    from app.skills.vision import build_image_message
    msgs = build_image_message("描述", "https://cdn/x.png")
    resp = await p.chat(msgs, model="m", temperature=0.1)
    assert resp.text == "这是一张科技博主主页"
