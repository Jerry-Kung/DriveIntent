from app.importer.tags import extract_tags


def test_extract_tags_basic():
    text = "全新坦克300 会有8缸版本！ #小报告 #坦克300 #SUV"
    assert extract_tags(text) == ["小报告", "坦克300", "SUV"]


def test_extract_tags_dedup_and_empty():
    assert extract_tags("#a #b #a") == ["a", "b"]
    assert extract_tags("") == []
    assert extract_tags("没有标签") == []
