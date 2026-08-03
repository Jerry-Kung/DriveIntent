from typing import Literal

from pydantic import BaseModel


class VideoContextResult(BaseModel):
    brand: str | None = None
    model: str | None = None
    content_type: str | None = None
    main_topics: list[str] = []
    target_audience: str | None = None
    competitor_models: list[str] = []
    commercial_context: str | None = None
    analysis_notes: str | None = None
    # V1.1：车型客观属性，用于我方车型匹配与意向降级（LLM 常识估算，缺失为 None）
    price_range_min: int | None = None
    price_range_max: int | None = None
    vehicle_category: str | None = None
    powertrain: str | None = None
    use_case: list[str] = []


class CommentScreeningItem(BaseModel):
    comment_id: str
    is_meaningful: bool = False
    is_automotive_related: bool = False
    is_purchase_related: bool = False
    is_suspected_marketing: bool = False
    intent_signals: list[str] = []
    target_brand: str | None = None
    target_model: str | None = None
    intent_strength: Literal["none", "low", "medium", "high"] = "none"
    reason: str = ""
    # V1.1：评论主体类型（异常类优先过滤）
    comment_actor: Literal["genuine_user", "bot_spam", "marketing_account",
                           "noise", "off_topic"] = "genuine_user"
    # V1.3：独立分析标签（不要求与我方在售车型相关）与内部积极信号。
    # is_car_owner：有明确证据大概率已购车（含已下单/下大定）；
    # has_purchase_intent：表达了任何购车相关倾向（本人意向）；
    # positive_attitude：非车主无意向但表达兴趣/赞美，仅供代码层
    # 合成 filter_type 使用，不进对外契约。
    is_car_owner: bool = False
    has_purchase_intent: bool = False
    positive_attitude: bool = False
    confidence: float = 0.0


class CommentScreeningResult(BaseModel):
    items: list[CommentScreeningItem]


class UserLeadResult(BaseModel):
    lead_grade: Literal["H", "A", "B", "C"]
    is_valid_lead: bool = True
    lead_summary: str = ""
    purchase_stage: str | None = None
    target_brands: list[str] = []
    target_models: list[str] = []
    core_needs: list[str] = []
    main_concerns: list[str] = []
    purchase_time: str | None = None
    usage_scenario: str | None = None
    recommended_entry_point: str | None = None
    verification_questions: list[str] = []
    evidence_comment_ids: list[str] = []
    profile_tags: list[str] = []
    profile_summary: str = ""
    analysis_text: str = ""
    # V1.2：画像上调审计字段（内部用，不进对外 API 契约）。
    # lead_grade 为最终等级；baseline_grade 为仅评论证据的基线等级。
    baseline_grade: str | None = None
    profile_adjustment: str = "none"  # none | upgraded
    adjustment_reason: str | None = None
    # V1.2.1：在售车型匹配度审计字段（内部用，不进对外 API 契约）。
    # 审计链条：baseline_grade →(match_adjustment)→ 中间等级
    #          →(profile_adjustment)→ lead_grade
    model_match_level: Literal["our_model", "similar", "partial",
                               "unrelated", "unknown"] = "unknown"
    match_adjustment: int = 0  # -2 ~ +1，负为降级、正为上调
    match_reason: str | None = None
    confidence: float = 0.0
