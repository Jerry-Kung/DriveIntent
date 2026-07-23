from datetime import datetime

from app.schemas.import_data import CommentIn, ImportBundle, UserIn, VideoIn


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def _from_doc_comments(comments: list[dict]) -> ImportBundle:
    videos: dict[str, VideoIn] = {}
    users: dict[str, UserIn] = {}
    items: list[CommentIn] = []
    skipped = 0
    for c in comments:
        title = c.get("video_title") or ""
        # 对接文档无独立视频 ID，以标题+作者作为去重键
        video_key = f"{c.get('video_author', '')}|{title}"
        if video_key not in videos:
            videos[video_key] = VideoIn(
                external_id=video_key, title=title, description="",
                raw={"video_metrics": c.get("video_metrics"),
                     "video_author": c.get("video_author"),
                     "video_author_fans": c.get("video_author_fans")})
        uid = c.get("comment_author_uid") or ""
        if uid and uid not in users:
            users[uid] = UserIn(external_id=uid,
                                nickname=c.get("comment_author") or "",
                                raw={"douyin_id": c.get("account_douyin_id")})
        content = c.get("comment_content")
        if content is None or not str(content).strip():
            skipped += 1
            continue
        items.append(CommentIn(
            external_id=c["comment_id"], video_external_id=video_key,
            user_external_id=uid, content=str(content),
            comment_time=_parse_time(c.get("comment_time")),
            raw={"comment_like_count": c.get("comment_like_count")}))
    return ImportBundle(videos=list(videos.values()),
                        users=list(users.values()), comments=items,
                        skipped_empty_comments=skipped)


def parse_json_source(raw: dict | list) -> ImportBundle:
    if isinstance(raw, dict) and "comments" in raw and "videos" not in raw:
        return _from_doc_comments(raw["comments"])
    # V0 标准三数组格式
    data = raw if isinstance(raw, dict) else {}
    return ImportBundle(
        videos=[VideoIn.model_validate(v) for v in data.get("videos", [])],
        users=[UserIn.model_validate(u) for u in data.get("users", [])],
        comments=[CommentIn.model_validate(c) for c in data.get("comments", [])],
        skipped_empty_comments=0)
