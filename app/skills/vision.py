def _to_image_url(screenshot: str) -> str:
    s = screenshot.strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("data:"):
        return s
    return f"data:image/png;base64,{s}"


def build_image_message(text: str, screenshot: str) -> list[dict]:
    if not screenshot or not screenshot.strip():
        return [{"role": "user", "content": text}]
    return [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": _to_image_url(screenshot)}},
    ]}]
