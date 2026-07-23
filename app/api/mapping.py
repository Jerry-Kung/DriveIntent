from datetime import datetime, timedelta, timezone

from app.api.schemas import ProfileResult, ScreeningResult
from app.schemas.skills import CommentScreeningItem, UserLeadResult

_TZ = timezone(timedelta(hours=8))

# 内部四维判断 → 文档过滤原因枚举
_GRADE_MAP = {
    "H": ("高", "high", 92),
    "A": ("中", "medium", 77),
    "B": ("低", "low", 60),
}


def now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def _filter_reason(item: CommentScreeningItem) -> str:
    if item.is_suspected_marketing:
        return "广告/引流类评论"
    if not item.is_meaningful:
        return "无实质内容"
    return "无实质内容"


def map_screening_item(item: CommentScreeningItem,
                       processed_at: str) -> ScreeningResult:
    passed = item.is_meaningful and not item.is_suspected_marketing
    reason = None if passed else _filter_reason(item)
    analysis = item.reason or ("通过初筛。" if passed else "未通过初筛。")
    return ScreeningResult(comment_id=item.comment_id, passed=passed,
                           filter_reason=reason, analysis=analysis,
                           processed_at=processed_at)


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
    level, code, base = mapped
    score = base
    if not screenshot_available:
        score = max(50, score - 13)  # 文档：截图缺失降 10-15 分
    return ProfileResult(
        account_uid="", has_value=True, intent_level=level,
        intent_level_code=code, value_score=score,
        profile_tags=list(out.profile_tags),
        profile_summary=out.profile_summary, analysis=out.analysis_text,
        processed_at=processed_at)
