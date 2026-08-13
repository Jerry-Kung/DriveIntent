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
    # V1.3：账号级独立标签，综合全部历史评论与主页画像判定。
    # 无评论历史（has_value=false 空账号）时保持默认 false。
    is_car_owner: bool = False
    has_purchase_intent: bool = False
    # V1.5.1：终判调整审计字段（内部用，不进对外 API 契约）。
    # 审计链条：baseline_grade →(match_adjustment)→ 中间等级1
    #          →(profile_adjustment)→ 中间等级2
    #          →(merge_boost / purchase_downgrade)→ lead_grade
    # V1.6.2: merge_boost removed; purchase_downgrade kept for compat
    purchase_downgrade: str = "none"  # none | capped
    purchase_downgrade_reason: str | None = None
    # V1.6.2: independent review audit fields (internal only, not in external API contract)
    # audit chain: baseline_grade ->(match_adjustment)-> mid_grade1
    #              ->(profile_adjustment)-> pre_review_grade
    #              ->(review_action)-> lead_grade
    #              ->(analysis_revision)-> 对外叙述文本（V1.6.3）
    pre_review_grade: str | None = None   # preliminary grade before review
    review_action: str = "confirmed"      # confirmed | upgraded | downgraded
    review_reason: str | None = None
    # V1.6.3：复核改级后对 analysis_text 第五段的修订方式。
    # none=未修订（confirmed 或复核未给正文）；replaced=按锚点替换第五段；
    # appended=锚点缺失，退化为文末追加。appended 占比偏高说明定级模型
    # 未稳定输出段标题，格式约束需加强。
    analysis_revision: str = "none"       # none | replaced | appended
    # V1.6：无效用户过滤审计字段（内部用，不进对外 API 契约）。
    # 被前置过滤节点命中时写入；未过滤（走完整定级流水线）为 None。
    filter_category: str | None = None
    filter_reason: str | None = None
    confidence: float = 0.0


class UserLeadReviewResult(BaseModel):
    """V1.6.2 independent review node output.

    Audits the preliminary lead_grade from user_lead_analysis from a
    salesperson's perspective. fail-open: if the review call fails the
    caller keeps the preliminary grade unchanged.

    V1.6.3: 改级时一并输出修订后的对外叙述，避免 analysis_text /
    lead_summary 仍停留在初步评级的论证上。confirmed 时两字段为 None。
    """
    review_action: str = "confirmed"   # confirmed | upgraded | downgraded
    reviewed_grade: str = "C"          # H | A | B | C
    review_reason: str | None = None
    # V1.6.3：仅在 review_action != "confirmed" 时给出。
    # revised_conclusion 为“总体评价”正文，不含段标题（标题由代码补齐）。
    revised_conclusion: str | None = None
    revised_lead_summary: str | None = None
    confidence: float = 0.0


class UserFilterResult(BaseModel):
    """V1.6 无效用户前置过滤输出。

    识别"实际无购车意向但易被误判为高价值"的用户，命中者不进定级流水线。
    两个独立标签由本节点一并判定：被过滤用户不进定级，对外契约的
    is_car_owner / has_purchase_intent 由此供给；未过滤时以定级输出为准。
    """
    filtered: bool = False
    filter_category: Literal["already_purchased", "promoting_others",
                             "proxy_inquiry", "marketing_suspect",
                             "industry_professional", "other"] | None = None
    filter_reason: str | None = None
    is_car_owner: bool = False
    has_purchase_intent: bool = False
    evidence_comment_ids: list[str] = []
    profile_tags: list[str] = []
    profile_summary: str = ""
    analysis_text: str = ""
    confidence: float = 0.0
