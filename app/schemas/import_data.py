from datetime import datetime

from pydantic import BaseModel


class VideoIn(BaseModel):
    platform: str = "douyin"
    external_id: str
    title: str = ""
    description: str = ""
    cover_url: str | None = None
    raw: dict | None = None


class UserIn(BaseModel):
    platform: str = "douyin"
    external_id: str
    nickname: str = ""
    raw: dict | None = None


class CommentIn(BaseModel):
    platform: str = "douyin"
    external_id: str
    video_external_id: str
    user_external_id: str
    content: str
    comment_time: datetime | None = None
    raw: dict | None = None


class ImportBundle(BaseModel):
    videos: list[VideoIn] = []
    users: list[UserIn] = []
    comments: list[CommentIn] = []
    skipped_empty_comments: int = 0
