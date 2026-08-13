import logging

from app.schemas.skills import AnalysisPolishResult, UserLeadResult
from app.skills.executor import SkillExecutionError

logger = logging.getLogger(__name__)

ANALYSIS_POLISH_SKILL = "user_analysis_polish"

# 五个段标题，须与定级 Prompt（user_lead_analysis_v1.6.3.txt）逐字一致
SECTION_HEADINGS = ["一、评论行为与用户身份", "二、购车阶段评估",
                    "三、目标车型与我方车型匹配度", "四、主页画像与调整结论",
                    "五、总体评价"]

# 复核动作转译为中文，避免向润色 Prompt 输入英文枚举值
_REVIEW_ACTION_ZH = {"confirmed": "维持原级", "upgraded": "上调一级",
                     "downgraded": "下调一级"}


async def apply_polish(executor, out: UserLeadResult) -> None:
    """V1.6.4 润色节点：重写三个对外叙述字段，就地修改 out。

    fail-open：调用失败、输出为空或缺失段标题时保留原文并记 "failed"。
    只改文本不改级——lead_grade 与结构化字段一律不动。刻意不传用户
    证据包：润色是纯文本改写，给证据包会诱导模型引入新事实。
    """
    ctx = {
        "lead_grade": out.lead_grade,
        "review_action": _REVIEW_ACTION_ZH.get(out.review_action,
                                               out.review_action),
        "review_reason": out.review_reason or "（无）",
        "analysis_text": out.analysis_text,
        "lead_summary": out.lead_summary,
        "profile_summary": out.profile_summary,
    }
    try:
        res: AnalysisPolishResult = await executor.run(
            ANALYSIS_POLISH_SKILL, ctx, AnalysisPolishResult)
    except SkillExecutionError as e:
        logger.warning("analysis 润色失败，保留原文: %s", e)
        out.analysis_polish = "failed"
        return
    text = res.polished_analysis_text.strip()
    if not text or any(h not in text for h in SECTION_HEADINGS):
        logger.warning("润色输出为空或缺失段标题，保留原文")
        out.analysis_polish = "failed"
        return
    # 原子性：校验全部通过后一次性赋值；summary 单独为空时保留原值
    out.analysis_text = text
    if res.polished_lead_summary.strip():
        out.lead_summary = res.polished_lead_summary.strip()
    if res.polished_profile_summary.strip():
        out.profile_summary = res.polished_profile_summary.strip()
    out.analysis_polish = "polished"
