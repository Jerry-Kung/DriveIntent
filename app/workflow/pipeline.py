import json

from sqlalchemy.orm import Session

from app.config import settings
from app.matching.loader import build_our_models_summary, load_our_models
from app.models import AnalysisResult, Comment, Video
from app.schemas.skills import (CommentScreeningResult, UserLeadResult,
                                UserLeadReviewResult, VideoContextResult)
from app.services.results import get_current_result, save_result
from app.skills.executor import (PROMPT_DIR, SkillExecutionError,
                                 SkillExecutor, load_skill_config)
from app.skills.user_filter import build_filtered_lead_result, run_user_filter
from app.workflow.tasks import create_task

VIDEO_CONTEXT_SKILL = "video_context_analysis"
COMMENT_SCREENING_SKILL = "comment_lead_screening"
USER_ANALYSIS_SKILL = "user_lead_analysis"
USER_REVIEW_SKILL = "user_lead_review"

SKILL_VERSIONS = {
    VIDEO_CONTEXT_SKILL: "1.1",
    COMMENT_SCREENING_SKILL: "1.3",
    USER_ANALYSIS_SKILL: "1.6.2",
    USER_REVIEW_SKILL: "1.6.2",
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
    # 只读数据已全部取出，结束事务归还连接；否则连接会被占用整个 LLM 调用
    session.commit()
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
    # 只读数据已全部取出，结束事务归还连接；否则连接会被占用整个重试/递归
    # 期间的所有 LLM 调用
    session.commit()

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


GRADING_STANDARD = (PROMPT_DIR / "grading_standard.txt").read_text(
    encoding="utf-8").strip()


async def run_user_analysis(session: Session, executor: SkillExecutor,
                            user_id: int) -> None:
    from app.services.aggregation import build_user_evidence
    from app.services.leads import upsert_lead

    evidence = build_user_evidence(session, user_id)
    context = {
        "user_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "grading_standard": GRADING_STANDARD,
        "our_models_summary": build_our_models_summary(load_our_models()),
    }
    # 只读数据已全部取出，结束事务归还连接；否则连接会被占用整个 LLM 调用
    session.commit()
    # V1.6：定级前先过无效用户过滤（fail-open）。命中合成 C 级结果照常
    # 落 AnalysisResult（含审计字段）；is_valid_lead=False 自然跳过 upsert_lead。
    filt = await run_user_filter(executor, evidence)
    if filt.filtered:
        out: UserLeadResult = build_filtered_lead_result(filt)
    else:
        out = await executor.run(
            USER_ANALYSIS_SKILL, context, UserLeadResult)
        # V1.6.2: independent review node (fail-open — any exception keeps
        # the preliminary grade; filtered results skip review entirely).
        try:
            review_context = {
                "user_evidence_json": context["user_evidence_json"],
                "grading_standard": GRADING_STANDARD,
                "our_models_summary": context["our_models_summary"],
                "preliminary_result_json": json.dumps(
                    out.model_dump(), ensure_ascii=False),
            }
            review: UserLeadReviewResult = await executor.run(
                USER_REVIEW_SKILL, review_context, UserLeadReviewResult)
            out.pre_review_grade = out.lead_grade
            out.review_action = review.review_action
            out.review_reason = review.review_reason
            if review.review_action != "confirmed":
                out.lead_grade = review.reviewed_grade  # type: ignore[assignment]
        except Exception:
            pass  # fail-open: keep preliminary lead_grade unchanged
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
        # 若所有 evidence_comment_ids 均为幻觉（过滤后为空），该线索没有任何
        # 可验证证据支撑，不应作为有效线索入库（AnalysisResult 仍已保存）。
        if evidence_comments:
            upsert_lead(session, user_id, out, evidence_comments,
                        SKILL_VERSIONS[USER_ANALYSIS_SKILL])


def schedule_analysis(session: Session) -> int:
    created = 0
    for (vid,) in session.query(Video.id).all():
        ctx = get_current_result(
            session, target_type="video", target_id=str(vid),
            skill_id=VIDEO_CONTEXT_SKILL,
            skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
        if ctx is not None:
            continue
        if create_task(session, task_type=VIDEO_CONTEXT_SKILL,
                       target_type="video", target_id=str(vid),
                       skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL]):
            created += 1
    return created


def _upstream_done(session: Session) -> bool:
    from app.models import AnalysisTask
    open_upstream = (session.query(AnalysisTask)
                     .filter(AnalysisTask.task_type.in_(
                         [VIDEO_CONTEXT_SKILL, COMMENT_SCREENING_SKILL]),
                         AnalysisTask.status.in_(["pending", "running"]))
                     .count())
    return open_upstream == 0


def advance(session: Session) -> int:
    from app.models import AnalysisTask
    from app.services.aggregation import candidate_user_ids
    created = 0

    # 1) 语境已完成的视频 → 建评论批次任务（每视频只建一次）
    ctx_rows = (session.query(AnalysisResult)
                .filter_by(target_type="video",
                           skill_id=VIDEO_CONTEXT_SKILL,
                           skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                           status="success").all())
    for ctx in ctx_rows:
        video_id = int(ctx.target_id)
        existing_batches = (session.query(AnalysisTask)
                            .filter(AnalysisTask.task_type ==
                                    COMMENT_SCREENING_SKILL,
                                    AnalysisTask.target_id.like(
                                        f"{video_id}:%"))
                            .all())
        covered_ids: set[int] = set()
        max_idx = -1
        for t in existing_batches:
            if t.payload and t.payload.get("comment_ids"):
                covered_ids.update(t.payload["comment_ids"])
            try:
                idx = int(t.target_id.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
            max_idx = max(max_idx, idx)
        comment_ids = [cid for (cid,) in
                       session.query(Comment.id)
                       .filter(Comment.video_id == video_id)
                       .order_by(Comment.id).all()]
        # 只为尚未被任何批次任务覆盖的评论（含新导入评论）建批次，
        # 批次序号在已有最大序号之后延续，保持已存在批次的幂等性。
        uncovered_ids = [cid for cid in comment_ids if cid not in covered_ids]
        size = settings.comment_batch_size
        next_idx = max_idx + 1
        for i in range(0, len(uncovered_ids), size):
            batch = uncovered_ids[i:i + size]
            if create_task(
                    session, task_type=COMMENT_SCREENING_SKILL,
                    target_type="comment_batch",
                    target_id=f"{video_id}:{next_idx}",
                    skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL],
                    payload={"video_id": video_id, "comment_ids": batch}):
                created += 1
            next_idx += 1

    # 2) 语境+筛选全部完结 → 为候选用户建用户分析任务
    if _upstream_done(session):
        for uid in candidate_user_ids(session):
            if create_task(session, task_type=USER_ANALYSIS_SKILL,
                           target_type="user", target_id=str(uid),
                           skill_version=SKILL_VERSIONS[USER_ANALYSIS_SKILL]):
                created += 1
    return created
