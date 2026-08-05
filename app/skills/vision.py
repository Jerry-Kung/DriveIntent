"""主页截图消息构造。

截图只接受 http(s) URL（见 app/api/schemas.AccountObject）：服务端不再搬运
图片本体，URL 直接透传给多模态模型，由模型侧自行拉取。
"""


def build_image_message(text: str, screenshot: str) -> list[dict]:
    url = (screenshot or "").strip()
    if not url:
        return [{"role": "user", "content": text}]
    return [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": url}},
    ]}]
