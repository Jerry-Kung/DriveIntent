from pydantic import BaseModel

# 字段必填性设计说明：
# 对接文档标注为「必填」的核心标识字段（如 comment_id、video_title、video_author、
# comment_content、comment_author、comment_author_uid、comment_time、account_uid、
# account_name 等）不设默认值，缺失即触发 Pydantic 校验失败，由 API 层返回错误。
# 而 video_metrics、video_author_fans、comment_like_count、
# account_homepage_screenshot、account_douyin_id、comment_history 等字段设默认值，
# 用于兼容对接文档所述的降级场景：视频热度指标缺失时走默认权重，账号主页截图/
# 评论历史缺失时走降级分析路径。
# 输出模型中的 error 字段为 V1 内部新增（对接文档未定义，partial 标注），
# 用于标记单条结果的处理错误信息，默认 None。


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
    # V1.3：恒为 null（原 model_mismatch 场景已取消），保留字段避免契约结构变动
    filter_reason: str | None = None
    filter_type: str = "genuine_user"
    # V1.3：独立分析标签；该条处理失败时为 null
    is_car_owner: bool | None = None
    has_purchase_intent: bool | None = None
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
