import re

_TAG_RE = re.compile(r"#([^#\s@]+)")


def extract_tags(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _TAG_RE.finditer(text):
        tag = m.group(1).strip()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out
