from pydantic import BaseModel


class VideoMetrics(BaseModel):
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    collect_count: int = 0


class CommentObject(BaseModel):
    comment_id: str
    video_title: str
    video_author: str
    video_author_fans: int = 0
    video_metrics: VideoMetrics = VideoMetrics()
    comment_content: str
    comment_author: str
    comment_author_uid: str
    comment_time: str
    comment_like_count: int = 0


class CommentScreeningRequest(BaseModel):
    comments: list[CommentObject]


class CommentHistoryItem(BaseModel):
    video_title: str
    comment_content: str
    comment_time: str
    comment_like_count: int = 0


class AccountObject(BaseModel):
    account_uid: str
    account_name: str
    account_douyin_id: str | None = None
    account_homepage_screenshot: str = ""
    comment_history: list[CommentHistoryItem] = []


class ProfileAnalysisRequest(BaseModel):
    accounts: list[AccountObject]


class ScreeningResult(BaseModel):
    comment_id: str
    passed: bool
    filter_reason: str | None = None
    analysis: str = ""
    processed_at: str = ""
    error: str | None = None


class ProfileResult(BaseModel):
    account_uid: str
    has_value: bool
    intent_level: str | None = None
    intent_level_code: str | None = None
    value_score: int | None = None
    profile_tags: list[str] = []
    profile_summary: str = ""
    analysis: str = ""
    processed_at: str = ""
    error: str | None = None
