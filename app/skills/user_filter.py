import json
import logging

from app.schemas.skills import UserFilterResult, UserLeadResult
from app.skills.executor import SkillExecutionError

logger = logging.getLogger(__name__)

USER_FILTER_SKILL = "user_lead_filter"


async def run_user_filter(executor, evidence: dict) -> UserFilterResult:
    """V1.6 无效用户前置过滤。

    fail-open：LLM 调用/校验失败，或 filtered=true 却缺 filter_category
    （输出非法）时，一律放行进入定级流水线，不阻断主流程。
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
    return out


def build_filtered_lead_result(f: UserFilterResult) -> UserLeadResult:
    """把过滤命中结果合成为 C 级 UserLeadResult，走既有映射与落库路径。"""
    return UserLeadResult(
        lead_grade="C", is_valid_lead=False,
        filter_category=f.filter_category, filter_reason=f.filter_reason,
        is_car_owner=f.is_car_owner,
        has_purchase_intent=f.has_purchase_intent,
        evidence_comment_ids=list(f.evidence_comment_ids),
        profile_tags=list(f.profile_tags),
        profile_summary=f.profile_summary,
        analysis_text=f.analysis_text or (f.filter_reason or ""),
        confidence=f.confidence)
