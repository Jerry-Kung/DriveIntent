from datetime import datetime, timedelta, timezone

from app.api.schemas import ProfileResult, ScreeningResult
from app.schemas.skills import CommentScreeningItem, UserLeadResult

_TZ = timezone(timedelta(hours=8))

# 内部线索等级 → 对外意向等级/基准分/区间下界。
# V1.7.3：H/A→high、B→medium、C→low，各等级保留原 base/floor（C 新增）。
# 注意：前向映射从此为多对一，外部 intent_level_code 已无法唯一反推内部
# HABC——内部审计/统计改读 api_job.lead_grades 真实等级，见
# app/services/lead_results.py。
_GRADE_MAP = {
    "H": ("高", "high", 92, 85),
    "A": ("高", "high", 77, 70),
    "B": ("中", "medium", 60, 50),
    "C": ("低", "low", 45, 40),
}


def now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def resolve_filter_type(item: CommentScreeningItem) -> str:
    """合成 filter_type。优先级：actor 异常类 > 旧字段兜底 > 意向/车主规则。

    V1.3：passed 与 filter_type 严格一一对应（genuine_user 通过，其余不过）。
    有购车意向必过筛；无意向车主不过筛；无意向非车主看积极信号。
    """
    if item.comment_actor != "genuine_user":
        return item.comment_actor
    # 兼容 LLM 未输出 comment_actor 的情况，回退 V1.0 判定
    if item.is_suspected_marketing:
        return "marketing_account"
    if not item.is_meaningful:
        return "noise"
    if item.has_purchase_intent:
        return "genuine_user"
    if item.is_car_owner:
        return "no_purchase_intent"
    if item.positive_attitude:
        return "genuine_user"
    return "no_purchase_intent"


def screening_dict_passed(res: dict) -> bool:
    """对落库的初筛结果 dict 判定是否通过初筛（8000 与 8100 同口径）。

    V1.3 之前的历史结果（无 has_purchase_intent 键）回退旧口径。
    """
    if "has_purchase_intent" not in res:
        return bool(res.get("is_purchase_related")
                    and not res.get("is_suspected_marketing"))
    item = CommentScreeningItem.model_validate(res)
    return resolve_filter_type(item) == "genuine_user"


def screened_out_category(res: dict) -> str:
    """未通过评论的展示分类：marketing / no_intent / unrelated。"""
    if "has_purchase_intent" not in res:
        return ("marketing" if res.get("is_suspected_marketing")
                else "unrelated")
    item = CommentScreeningItem.model_validate(res)
    ft = resolve_filter_type(item)
    if ft in ("marketing_account", "bot_spam"):
        return "marketing"
    if ft == "no_purchase_intent":
        return "no_intent"
    return "unrelated"


def map_screening_item(item: CommentScreeningItem,
                       processed_at: str) -> ScreeningResult:
    filter_type = resolve_filter_type(item)
    passed = filter_type == "genuine_user"
    analysis = item.reason or ("通过初筛。" if passed else "未通过初筛。")
    return ScreeningResult(comment_id=item.comment_id, passed=passed,
                           filter_type=filter_type, analysis=analysis,
                           is_car_owner=item.is_car_owner,
                           has_purchase_intent=item.has_purchase_intent,
                           processed_at=processed_at)


def map_profile_result(out: UserLeadResult, *, screenshot_available: bool,
                       has_comments: bool, processed_at: str) -> ProfileResult:
    mapped = _GRADE_MAP.get(out.lead_grade)
    has_value = bool(has_comments and out.is_valid_lead and mapped is not None)
    if not has_value:
        return ProfileResult(
            account_uid="", has_value=False,
            is_car_owner=out.is_car_owner,
            has_purchase_intent=out.has_purchase_intent,
            intent_models=list(out.intent_models),
            intent_model_category=out.intent_model_category,
            recommended_entry_point=out.recommended_entry_point,
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
        is_car_owner=out.is_car_owner,
        has_purchase_intent=out.has_purchase_intent,
        intent_models=list(out.intent_models),
        intent_model_category=out.intent_model_category,
        recommended_entry_point=out.recommended_entry_point,
        profile_tags=list(out.profile_tags),
        profile_summary=out.profile_summary, analysis=out.analysis_text,
        processed_at=processed_at)
