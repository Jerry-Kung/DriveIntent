from app.importer.json_source import parse_json_source


def test_parse_docformat_comments():
    raw = {"comments": [{
        "comment_id": "cm_1", "video_title": "试驾", "video_author": "@王",
        "video_author_fans": 100,
        "video_metrics": {"like_count": 1, "comment_count": 2,
                          "share_count": 3, "collect_count": 4},
        "comment_content": "刚提车", "comment_author": "用户_1",
        "comment_author_uid": "u1",
        "comment_time": "2026-07-19T14:23:00+08:00",
        "comment_like_count": 10}]}
    bundle = parse_json_source(raw)
    assert len(bundle.comments) == 1
    assert len(bundle.videos) == 1
    assert len(bundle.users) == 1
    assert bundle.comments[0].external_id == "cm_1"
    assert bundle.videos[0].title == "试驾"


def test_parse_docformat_skips_empty_content():
    raw = {"comments": [{
        "comment_id": "cm_2", "video_title": "t", "video_author": "@w",
        "comment_content": "  ", "comment_author": "u",
        "comment_author_uid": "u2",
        "comment_time": "2026-07-19T14:23:00+08:00"}]}
    bundle = parse_json_source(raw)
    assert bundle.comments == []
    assert bundle.skipped_empty_comments == 1


def test_parse_v0_standard_format():
    raw = {"videos": [{"external_id": "v1", "title": "标题"}],
           "users": [{"external_id": "u1", "nickname": "昵称"}],
           "comments": [{"external_id": "c1", "video_external_id": "v1",
                         "user_external_id": "u1", "content": "内容"}]}
    bundle = parse_json_source(raw)
    assert len(bundle.comments) == 1 and bundle.videos[0].external_id == "v1"
