import json
import logging

from app.schemas.skills import UserFilterResult, UserLeadResult
from app.skills.executor import SkillExecutionError

logger = logging.getLogger(__name__)

USER_FILTER_SKILL = "user_lead_filter"


async def run_user_filter(executor, evidence: dict) -> UserFilterResult:
    """V1.6 无效用户前置过滤。

    fail-open：LLM 调用/校验失败，或 filtered=true 却缺 filter_category
    （输出非法），或 is_blacklisted=true 却缺 blacklist_type（黑名单判定
    非法，V1.9.2）时，一律放行进入定级流水线，不阻断主流程。
    """
    ctx = {"user_evidence_json": json.dumps(evidence, ensure_ascii=False)}
    try:
        out: UserFilterResult = await executor.run(
            USER_FILTER_SKILL, ctx, UserFilterResult)
    except SkillExecutionError as e:
        logger.warning("无效用户过滤失败，放行进入定级: %s", e)
        return UserFilterResult()
    if out.filtered and out.filter_category is None:
        logger.warning("过滤输出缺少 filter_category，放行进入定级")
        return UserFilterResult()
    if out.is_blacklisted and out.blacklist_type is None:
        logger.warning("黑名单判定缺少 blacklist_type，放行进入定级")
        return UserFilterResult()
    return out


def build_filtered_lead_result(f: UserFilterResult) -> UserLeadResult:
    """把过滤命中结果合成为 C 级 UserLeadResult，走既有映射与落库路径。

    V1.9.2：疑似黑名单命中（f.is_blacklisted=true）与六类过滤命中共用本函数：
    均合成 C / is_valid_lead=False；黑名单命中把内部 filter_category 记为
    "blacklist_suspect"（区别于 V1.9.0 确认黑名单的 "blacklisted"），对外三字段
    is_blacklisted/blacklist_type/blacklist_reason 透传。analysis_text 缺省时
    优先回退 blacklist_reason（避免黑名单命中无说明文本）。
    """
    if f.is_blacklisted:
        category = "blacklist_suspect"
        reason = f.blacklist_reason or f.filter_reason
    else:
        category = f.filter_category
        reason = f.filter_reason
    return UserLeadResult(
        lead_grade="C", is_valid_lead=False,
        filter_category=category, filter_reason=reason,
        is_car_owner=f.is_car_owner,
        has_purchase_intent=f.has_purchase_intent,
        evidence_comment_ids=list(f.evidence_comment_ids),
        profile_tags=list(f.profile_tags),
        profile_summary=f.profile_summary,
        analysis_text=f.analysis_text or (reason or ""),
        is_blacklisted=f.is_blacklisted,
        blacklist_type=f.blacklist_type,
        blacklist_reason=f.blacklist_reason,
        confidence=f.confidence)
