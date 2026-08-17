import json
import logging

from app.schemas.skills import UserLeadResult, UserLeadReviewResult
from app.skills.executor import PROMPT_DIR, SkillExecutionError

logger = logging.getLogger(__name__)

USER_REVIEW_SKILL = "user_lead_review"
USER_REVIEW_ADVANCED_SKILL = "user_lead_review_advanced"

GRADING_STANDARD = (PROMPT_DIR / "grading_standard.txt").read_text(
    encoding="utf-8").strip()

# V1.6.3：analysis_text 第五段的定位锚点，须与定级 Prompt
# （user_lead_analysis_v1.6.3.txt）中的第五个段标题逐字一致。
CONCLUSION_ANCHOR = "五、总体评价"


def _revise_analysis(analysis_text: str,
                     revised_conclusion: str | None) -> tuple[str, str]:
    """用复核给出的新结论替换 analysis_text 的第五段"总体评价"。

    返回 (新 analysis_text, analysis_revision)。纯函数，不抛异常。
    前四段是与等级无关的事实陈述，必须逐字保留——把"原样照抄"交给模型
    做不可靠，只有代码切分能兑现这一点。锚点缺失时退化为文末追加，
    宁可效果打折也绝不失败。
    """
    body = (revised_conclusion or "").strip()
    if not body:
        return analysis_text, "none"
    # 模型可能不听话地把段标题也写进正文，剥掉避免重复标题
    if body.startswith(CONCLUSION_ANCHOR):
        body = body[len(CONCLUSION_ANCHOR):].lstrip("：: \t\n")
    text = analysis_text or ""
    # 总体评价是末段：用最后一次出现，避开前文对该标题的引用
    idx = text.rfind(CONCLUSION_ANCHOR)
    if idx >= 0:
        return f"{text[:idx]}{CONCLUSION_ANCHOR}\n{body}", "replaced"
    sep = "\n\n" if text else ""
    return f"{text}{sep}{CONCLUSION_ANCHOR}（复核修订）\n{body}", "appended"


async def _run_review(executor, evidence_json: str, our_models_summary: str,
                      out: UserLeadResult, tier: str) -> None:
    """单次复核核心：调用指定层级的审查 Skill，就地修改 out。

    fail-open：调用失败时等级与文本双双保持当前值（原子性）。
    tier 为 "standard"（普通模型）或 "advanced"（高级模型），调用前即
    写入 out.review_tier，保证 fail-open 也留下"尝试过该层"的痕迹。
    """
    skill_id = (USER_REVIEW_ADVANCED_SKILL if tier == "advanced"
                else USER_REVIEW_SKILL)
    out.review_tier = tier
    review_context = {
        "user_evidence_json": evidence_json,
        "grading_standard": GRADING_STANDARD,
        "our_models_summary": our_models_summary,
        "preliminary_result_json": json.dumps(
            out.model_dump(), ensure_ascii=False),
    }
    try:
        review: UserLeadReviewResult = await executor.run(
            skill_id, review_context, UserLeadReviewResult)
    except SkillExecutionError as e:
        logger.warning("复核节点失败，保留初步定级与叙述: %s", e)
        return
    out.pre_review_grade = out.lead_grade
    out.review_action = review.review_action
    out.review_reason = review.review_reason
    if review.review_action != "confirmed":
        # V1.6.3：等级与对外叙述必须同进同退。先全部算完再一次性
        # 赋值，杜绝"等级已改、文本仍在论证旧等级"的中间态。
        new_text, revision = _revise_analysis(
            out.analysis_text, review.revised_conclusion)
        new_summary = (review.revised_lead_summary or "").strip()
        out.analysis_text = new_text
        out.analysis_revision = revision
        if new_summary:
            out.lead_summary = new_summary
        out.lead_grade = review.reviewed_grade  # type: ignore[assignment]


async def apply_review(executor, evidence_json: str, our_models_summary: str,
                       out: UserLeadResult) -> None:
    """V1.7.0 审查分级分流，就地修改 out。

    - 初始 C：无价值，不进审查（review_tier 保持 none）；
    - 初始 B：普通模型审查（user_lead_review，行为与 V1.6.3 一致）；
      若普通审查 upgrade 到 A/H，追加一次高级模型终审
      （user_lead_review_advanced）；
    - 初始 A/H：直接高级模型审查。

    V1.6.4 起两条路径（V0 流水线 / 对外 API）共用本函数。
    """
    grade = out.lead_grade
    if grade == "C":
        return
    if grade == "B":
        await _run_review(executor, evidence_json, our_models_summary,
                          out, "standard")
        if out.lead_grade in ("A", "H"):
            await _run_review(executor, evidence_json, our_models_summary,
                              out, "advanced")
    else:  # A / H
        await _run_review(executor, evidence_json, our_models_summary,
                          out, "advanced")
