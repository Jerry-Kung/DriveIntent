from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.schemas.import_data import CommentIn, ImportBundle, UserIn, VideoIn


def _clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def parse_excel(path: str | Path) -> ImportBundle:
    df = pd.read_excel(path, sheet_name=0,
                       dtype={"aweme_id": str, "comment_id": str,
                              "sec_uid": str})
    videos: dict[str, VideoIn] = {}
    users: dict[str, UserIn] = {}
    comments: list[CommentIn] = []
    skipped = 0

    for _, row in df.iterrows():
        d = {k: _clean(v) for k, v in row.to_dict().items()}
        aweme_id = str(d["aweme_id"])
        sec_uid = str(d["sec_uid"])

        if aweme_id not in videos:
            videos[aweme_id] = VideoIn(
                external_id=aweme_id,
                title=str(d.get("title") or ""),
                description=str(d.get("desc") or ""),
                cover_url=d.get("cover_url"),
                raw={"aweme_id": aweme_id, "title": d.get("title"),
                     "desc": d.get("desc"), "cover_url": d.get("cover_url")})
        if sec_uid not in users:
            users[sec_uid] = UserIn(
                external_id=sec_uid,
                nickname=str(d.get("nickname") or ""),
                raw={"sec_uid": sec_uid, "nickname": d.get("nickname")})

        content = d.get("content")
        if content is None or not str(content).strip():
            skipped += 1
            continue
        ts = d.get("create_time")
        comment_time = None
        if ts is not None:
            comment_time = datetime.fromtimestamp(
                int(ts), tz=timezone.utc).replace(tzinfo=None)
        comments.append(CommentIn(
            external_id=str(d["comment_id"]),
            video_external_id=aweme_id,
            user_external_id=sec_uid,
            content=str(content),
            comment_time=comment_time,
            raw={"comment_id": str(d["comment_id"]),
                 "content": str(content), "create_time": ts}))

    return ImportBundle(videos=list(videos.values()),
                        users=list(users.values()),
                        comments=comments,
                        skipped_empty_comments=skipped)
