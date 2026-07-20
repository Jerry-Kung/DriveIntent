import json

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Comment, Video
from app.schemas.skills import (CommentScreeningResult, UserLeadResult,
                                VideoContextResult)
from app.services.results import get_current_result, save_result
from app.skills.executor import (SkillExecutionError, SkillExecutor,
                                 load_skill_config)

VIDEO_CONTEXT_SKILL = "video_context_analysis"
COMMENT_SCREENING_SKILL = "comment_lead_screening"
USER_ANALYSIS_SKILL = "user_lead_analysis"

SKILL_VERSIONS = {
    VIDEO_CONTEXT_SKILL: "1.0",
    COMMENT_SCREENING_SKILL: "1.0",
    USER_ANALYSIS_SKILL: "1.0",
}


async def run_video_context(session: Session, executor: SkillExecutor,
                            video_id: int) -> None:
    video = session.get(Video, video_id)
    if video is None:
        raise ValueError(f"视频不存在: {video_id}")
    context = {
        "video_json": json.dumps({
            "title": video.title,
            "description": video.description,
            "tags": video.tags or [],
            "account_type": video.account_type or "未知",
            "transcript": video.transcript or "",
            "preset_brand": video.preset_brand or "",
            "preset_model": video.preset_model or "",
        }, ensure_ascii=False),
    }
    out: VideoContextResult = await executor.run(
        VIDEO_CONTEXT_SKILL, context, VideoContextResult)
    config = load_skill_config(VIDEO_CONTEXT_SKILL)
    save_result(session, target_type="video", target_id=str(video_id),
                skill_id=VIDEO_CONTEXT_SKILL,
                skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                result=out.model_dump(),
                model_name=config.model_name or settings.llm_model,
                prompt_version=config.prompt_version)


async def _call_screening(executor: SkillExecutor,
                          video_context: dict,
                          comments: list[Comment]) -> CommentScreeningResult:
    context = {
        "video_context_json": json.dumps(video_context, ensure_ascii=False),
        "comments_json": json.dumps(
            [{"comment_id": str(c.id), "content": c.content}
             for c in comments], ensure_ascii=False),
        "comment_count": str(len(comments)),
    }
    return await executor.run(
        COMMENT_SCREENING_SKILL, context, CommentScreeningResult)


def _save_screening_items(session: Session,
                          result: CommentScreeningResult) -> None:
    config = load_skill_config(COMMENT_SCREENING_SKILL)
    for item in result.items:
        save_result(session, target_type="comment",
                    target_id=item.comment_id,
                    skill_id=COMMENT_SCREENING_SKILL,
                    skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL],
                    result=item.model_dump(), confidence=item.confidence,
                    model_name=config.model_name or settings.llm_model,
                    prompt_version=config.prompt_version)


async def screen_comment_batch(session: Session, executor: SkillExecutor,
                               video_id: int,
                               comment_ids: list[int]) -> None:
    ctx_row = get_current_result(
        session, target_type="video", target_id=str(video_id),
        skill_id=VIDEO_CONTEXT_SKILL,
        skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
    if ctx_row is None:
        raise SkillExecutionError(f"视频 {video_id} 缺少语境结果")
    comments = (session.query(Comment)
                .filter(Comment.id.in_(comment_ids)).all())
    if not comments:
        return
    resolved_ids = [c.id for c in comments]
    expected = {str(c.id) for c in comments}

    for _ in range(settings.llm_max_retries):
        result = await _call_screening(executor, ctx_row.result, comments)
        if (len(result.items) == len(comments)
                and {i.comment_id for i in result.items} == expected):
            _save_screening_items(session, result)
            return
    # 多次整批失败：拆半递归；单条仍失败则抛错
    if len(resolved_ids) == 1:
        raise SkillExecutionError(
            f"评论 {comment_ids} 筛选输出 ID 持续不一致")
    mid = len(resolved_ids) // 2
    await screen_comment_batch(session, executor, video_id, resolved_ids[:mid])
    await screen_comment_batch(session, executor, video_id, resolved_ids[mid:])


GRADING_STANDARD = """H级（极高意向）：出现明确交易或行动信号——询问价格/落地价、优惠、
置换补贴、金融方案、门店/库存/交付、试驾，或明确表达近期购买换车计划。
A级（较强意向）：进入主动评估对比阶段——对比竞品、讨论优缺点、深入配置差异、
关注养车成本/保值率/售后、讨论真实使用场景。
B级（中等意向）：有产品兴趣但未深度决策——讨论外观内饰、浅层配置咨询、
"有点心动"、未来可能考虑。
C级（较低意向）：与汽车相关但意向弱——普通吐槽、玩梗、浅层情绪表达。
判定以购车决策阶段和行动信号为主要标准；同时符合多级时取最高一级；
没有证据支撑的信息保持未知（null 或空数组），不得推断职业、收入、家庭情况。"""


async def run_user_analysis(session: Session, executor: SkillExecutor,
                            user_id: int) -> None:
    from app.services.aggregation import build_user_evidence
    from app.services.leads import upsert_lead

    evidence = build_user_evidence(session, user_id)
    context = {
        "user_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "grading_standard": GRADING_STANDARD,
    }
    out: UserLeadResult = await executor.run(
        USER_ANALYSIS_SKILL, context, UserLeadResult)
    config = load_skill_config(USER_ANALYSIS_SKILL)
    save_result(session, target_type="user", target_id=str(user_id),
                skill_id=USER_ANALYSIS_SKILL,
                skill_version=SKILL_VERSIONS[USER_ANALYSIS_SKILL],
                result=out.model_dump(), confidence=out.confidence,
                model_name=config.model_name or settings.llm_model,
                prompt_version=config.prompt_version)
    if out.is_valid_lead:
        content_map = {c["comment_id"]: c["content"]
                       for c in evidence["comments"]}
        evidence_comments = [
            {"comment_id": cid, "content": content_map[cid]}
            for cid in out.evidence_comment_ids if cid in content_map]
        upsert_lead(session, user_id, out, evidence_comments,
                    SKILL_VERSIONS[USER_ANALYSIS_SKILL])
