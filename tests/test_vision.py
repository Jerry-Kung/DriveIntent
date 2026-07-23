from app.skills.vision import build_image_message


def test_url_screenshot():
    msgs = build_image_message("描述这张图", "https://cdn/x.png")
    content = msgs[0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"] == "https://cdn/x.png"


def test_base64_screenshot_wrapped():
    msgs = build_image_message("t", "iVBORw0KGgoAAAA")
    url = msgs[0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/") and "base64,iVBORw0KGgoAAAA" in url


def test_empty_screenshot_text_only():
    msgs = build_image_message("只有文字", "")
    assert msgs[0]["content"] == "只有文字"
