from datetime import datetime

import pandas as pd

from app.importer.core import import_bundle
from app.importer.excel import parse_excel
from app.models import Comment, PlatformUser, Video
from app.schemas.import_data import CommentIn, ImportBundle, UserIn, VideoIn


def _bundle():
    return ImportBundle(
        videos=[VideoIn(external_id="v1", title="标题 #坦克300",
                        description="文案 #SUV", raw={"aweme_id": "v1"})],
        users=[UserIn(external_id="u1", nickname="用户一")],
        comments=[CommentIn(external_id="c1", video_external_id="v1",
                            user_external_id="u1", content="落地多少钱",
                            comment_time=datetime(2026, 7, 1, 12, 0, 0))],
        skipped_empty_comments=2)


def test_import_bundle_writes_rows(session):
    stats = import_bundle(session, _bundle())
    assert stats.videos_new == 1 and stats.users_new == 1
    assert stats.comments_new == 1 and stats.empty_comments == 2
    v = session.query(Video).one()
    assert v.tags == ["坦克300", "SUV"]          # title+description 中解析
    assert v.raw_data == {"aweme_id": "v1"}
    c = session.query(Comment).one()
    assert c.video_id == v.id
    assert c.user_id == session.query(PlatformUser).one().id


def test_import_bundle_idempotent(session):
    import_bundle(session, _bundle())
    stats = import_bundle(session, _bundle())
    assert stats.videos_new == 0 and stats.videos_skipped == 1
    assert stats.comments_new == 0 and stats.comments_skipped == 1
    assert session.query(Comment).count() == 1


def test_parse_excel(tmp_path):
    df = pd.DataFrame([
        {"aweme_id": "1001", "title": "标题A #SUV", "desc": "文案A",
         "cover_url": "http://x/1.jpg", "nickname": "小明",
         "sec_uid": "sec_1", "comment_id": "9001",
         "content": "落地多少钱", "create_time": 1783783725},
        {"aweme_id": "1001", "title": "标题A #SUV", "desc": "文案A",
         "cover_url": "http://x/1.jpg", "nickname": "小红",
         "sec_uid": "sec_2", "comment_id": "9002",
         "content": None, "create_time": 1783783726},
    ])
    path = tmp_path / "t.xlsx"
    df.to_excel(path, index=False)

    bundle = parse_excel(path)
    assert len(bundle.videos) == 1          # 同视频去重
    assert len(bundle.users) == 2
    assert len(bundle.comments) == 1        # 空评论被跳过
    assert bundle.skipped_empty_comments == 1
    c = bundle.comments[0]
    assert c.external_id == "9001" and c.video_external_id == "1001"
    assert c.comment_time is not None

