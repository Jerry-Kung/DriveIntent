from datetime import datetime, timedelta, timezone

from app.api.schemas import ProfileResult, ScreeningResult
from app.schemas.skills import CommentScreeningItem, UserLeadResult

_TZ = timezone(timedelta(hours=8))

# 内部线索等级 → 文档意向等级/基准分/区间下界
_GRADE_MAP = {
    "H": ("高", "high", 92, 85),
    "A": ("中", "medium", 77, 70),
    "B": ("低", "low", 60, 50),
}


def now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


# filter_type → 对外 filter_reason 文案（genuine_user 无 reason）
_FILTER_REASON = {
    "existing_owner": "已购车主评论",
    "ordered_owner": "已下定车主评论",
    "bot_spam": "批量刷屏水军",
    "marketing_account": "广告/引流类评论",
    "noise": "无实质内容",
    "off_topic": "与汽车无关",
}


def resolve_filter_type(item: CommentScreeningItem) -> str:
    """合成 filter_type。优先级：actor 异常类 > 车主状态 > 兼容回退 > 真实用户。

    comment_actor 本身即按 off_topic > noise > bot_spam > marketing_account
    的语义由 LLM 五选一，代码层只需再叠加车主状态与 V1.0 旧字段回退。
    """
    if item.comment_actor != "genuine_user":
        return item.comment_actor
    if item.owner_status != "none":
        return item.owner_status
    # 兼容 LLM 未输出新字段的情况，回退 V1.0 判定
    if item.is_suspected_marketing:
        return "marketing_account"
    if not item.is_meaningful:
        return "noise"
    return "genuine_user"


def map_screening_item(item: CommentScreeningItem, processed_at: str, *,
                       downgrade_applied: bool = False,
                       downgrade_reason: str | None = None) -> ScreeningResult:
    filter_type = resolve_filter_type(item)
    passed = filter_type == "genuine_user"
    reason = None if passed else _FILTER_REASON[filter_type]
    analysis = item.reason or ("通过初筛。" if passed else "未通过初筛。")
    return ScreeningResult(comment_id=item.comment_id, passed=passed,
                           filter_reason=reason, filter_type=filter_type,
                           intent_strength=item.intent_strength,
                           downgrade_applied=downgrade_applied,
                           downgrade_reason=downgrade_reason,
                           analysis=analysis, processed_at=processed_at)


def map_profile_result(out: UserLeadResult, *, screenshot_available: bool,
                       has_comments: bool, processed_at: str) -> ProfileResult:
    mapped = _GRADE_MAP.get(out.lead_grade)
    has_value = bool(has_comments and out.is_valid_lead and mapped is not None)
    if not has_value:
        return ProfileResult(
            account_uid="", has_value=False,
            profile_tags=list(out.profile_tags),
            profile_summary=out.profile_summary,
            analysis=out.analysis_text, processed_at=processed_at)
    level, code, base, floor = mapped
    score = base
    if not screenshot_available:
        score = max(floor, score - 13)  # 文档：截图缺失降 10-15 分，钳制在等级区间下界
    return ProfileResult(
        account_uid="", has_value=True, intent_level=level,
        intent_level_code=code, value_score=score,
        profile_tags=list(out.profile_tags),
        profile_summary=out.profile_summary, analysis=out.analysis_text,
        processed_at=processed_at)
