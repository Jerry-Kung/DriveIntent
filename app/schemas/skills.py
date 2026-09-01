from typing import Literal

from pydantic import BaseModel, field_validator


class VideoContextResult(BaseModel):
    # V1.8.3：brand/model/vehicle_category/powertrain 由单值改为数组——
    # 跨品牌对比类视频本就涉及多款车，强约束单值曾致 LLM 输出数组时
    # 整单作业校验失败。键名不变，下游均整段 JSON 透传无结构化取值。
    brand: list[str] = []
    model: list[str] = []
    content_type: str | None = None
    main_topics: list[str] = []
    target_audience: str | None = None
    competitor_models: list[str] = []
    commercial_context: str | None = None
    analysis_notes: str | None = None
    # V1.1：车型客观属性，用于我方车型匹配与意向降级（LLM 常识估算，缺失为 None）
    price_range_min: int | None = None
    price_range_max: int | None = None
    vehicle_category: list[str] = []
    powertrain: list[str] = []
    use_case: list[str] = []

    @field_validator("brand", "model", "vehicle_category", "powertrain",
                     mode="before")
    @classmethod
    def _coerce_to_str_list(cls, v):
        """V1.8.3 四字段数组化的兼容归一：历史单值输出/落库数据包成
        单元素数组，None 与空白串归一为空数组；list 透传交 Pydantic
        逐元素校验；其余类型原样返回交由 Pydantic 报错。"""
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v

    @field_validator("price_range_min", "price_range_max", mode="before")
    @classmethod
    def _coerce_price_to_int(cls, v):
        """LLM 偶尔输出带小数的价格（如 57.99），int 字段会触发
        int_from_float 校验错误进而使整单作业失败。此处将数值型输入
        归一为整数；无法判定的输入原样返回交由 Pydantic 报错。"""
        if v is None or isinstance(v, bool):
            return v
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return round(v)
        if isinstance(v, str):
            try:
                return round(float(v))
            except ValueError:
                return v
        return v


class _ScreeningFields(BaseModel):
    """评论初筛的判定字段（不含任何标识键）。

    V1.7.2 起拆出：LLM 面向对象用 `index`（批次内临时序号）定位评论，
    落库与下游面向对象用 `comment_id`（真实主键）。两者共用本类字段，
    避免两套 schema 字段漂移。
    """
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


class CommentScreeningItem(_ScreeningFields):
    """落库与下游消费的初筛结果条目，标识键为真实 comment_id。"""
    comment_id: str


class CommentScreeningResult(BaseModel):
    items: list[CommentScreeningItem]


class CommentScreeningBatchItem(_ScreeningFields):
    """V1.7.2：LLM 面向的输出条目，标识键为批次内临时序号 index。

    LLM 不读不写真实 comment_id（廉价模型抄写 19 位 ID 出错率高）。
    代码层按 index 还原真实 ID，见 app.skills.screening_batch。
    """
    index: int


class CommentScreeningBatchResult(BaseModel):
    """V1.7.2：LLM 面向的评论初筛输出契约。"""
    items: list[CommentScreeningBatchItem]


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
    # V1.8.0：阶段二重构为"意向车型识别与分类"，不再调整评级。
    # 审计链条：baseline_grade →(profile_adjustment)→ 中间等级 → 复核 → lead_grade
    # intent_models：有购买意向的车型列表，空数组=无意向车型（进对外 API 契约）；
    # intent_model_category：按可配置标准归档（A/B/C/D），未配置标准或
    # 历史数据为 None（进对外 API 契约）；
    # match_reason 自 V1.8.0 起语义为阶段二识别与分类依据。
    intent_models: list[str] = []
    intent_model_category: Literal["A", "B", "C", "D"] | None = None
    # V1.2.1 引入的匹配调级审计字段。V1.8.0 起阶段二不再调级，LLM 不再输出
    # 下两字段，仅为历史落库数据的读取兼容而保留默认值。
    model_match_level: Literal["our_model", "similar", "partial",
                               "unrelated", "unknown"] = "unknown"
    match_adjustment: int = 0  # V1.8.0 起恒为 0（历史数据可为 -2 ~ +1）
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
    #              ->(analysis_revision)-> 锚点修订后叙述（V1.6.3）
    #              ->(analysis_polish)-> 对外叙述文本（V1.6.4）
    pre_review_grade: str | None = None   # preliminary grade before review
    review_action: str = "confirmed"      # confirmed | upgraded | downgraded
    review_reason: str | None = None
    # V1.7.0：审查层级审计字段。none=未审查（被过滤或初始定级 C）；
    # standard=普通模型审查；advanced=高级模型审查（最终生效层级）。
    review_tier: str = "none"             # none | standard | advanced
    # V1.6.3：复核改级后对 analysis_text 第五段的修订方式。
    # none=未修订（confirmed 或复核未给正文）；replaced=按锚点替换第五段；
    # appended=锚点缺失，退化为文末追加。appended 占比偏高说明定级模型
    # 未稳定输出段标题，格式约束需加强。
    analysis_revision: str = "none"       # none | replaced | appended
    # V1.6.4：润色节点审计字段。none=未走润色（被过滤账号或最终定级 C）；
    # polished=已应用（含 summary 单字段为空、部分应用）；
    # failed=调用失败或输出非法（为空/缺段标题），保留原文。
    # failed 占比偏高说明润色 Prompt 输出格式不稳，需加强约束。
    analysis_polish: str = "none"         # none | polished | failed
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


class AnalysisPolishResult(BaseModel):
    """V1.6.4 润色节点输出。

    对定级+复核后的三个对外叙述字段做一次专门润色。调用方校验
    polished_analysis_text 非空且五段标题齐全后才应用（fail-open）。
    """
    polished_analysis_text: str = ""
    polished_lead_summary: str = ""
    polished_profile_summary: str = ""
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
