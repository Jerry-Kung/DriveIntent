import json

from app.api.mapping import map_screening_item, now_iso
from app.api.schemas import CommentObject, CommentScreeningRequest
from app.config import settings
from app.schemas.skills import (CommentScreeningBatchResult,
                                CommentScreeningItem, VideoContextResult)
from app.skills.executor import SkillExecutor
from app.skills.screening_batch import (build_screening_input,
                                        map_batch_result)
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL,
                                   VIDEO_CONTEXT_SKILL)


async def _video_context(executor: SkillExecutor,
                         comment: CommentObject) -> dict:
    ctx = {"video_json": json.dumps({
        "title": comment.video_title,
        "description": "",
        "tags": [],
        "account_type": "未知",
        "video_author": comment.video_author,
        "video_author_fans": comment.video_author_fans,
        "video_metrics": comment.video_metrics.model_dump(),
    }, ensure_ascii=False)}
    out: VideoContextResult = await executor.run(
        VIDEO_CONTEXT_SKILL, ctx, VideoContextResult)
    return out.model_dump()


async def _screen_batch(executor: SkillExecutor, video_context: dict,
                        batch: list[CommentObject]) -> dict[str, CommentScreeningItem]:
    pairs = [(c.comment_id, c.comment_content) for c in batch]
    context = build_screening_input(video_context, pairs)
    out: CommentScreeningBatchResult = await executor.run(
        COMMENT_SCREENING_SKILL, context, CommentScreeningBatchResult)
    # LLM 只回传 index，代码层按输入顺序还原真实 comment_id（含完整性校验）
    result = map_batch_result(out, pairs)
    return {i.comment_id: i for i in result.items}


async def run_comment_screening(executor: SkillExecutor,
                                request: CommentScreeningRequest,
                                *, progress_cb=None) -> dict:
    """progress_cb 为 async 可调用（V1.4.4：进度落库经线程池执行）。"""
    # 按视频标题分组，语境结果在本次调用内缓存复用
    ctx_cache: dict[str, dict] = {}
    results: list[dict] = []
    done = 0
    # 分组：同一 video_title 的评论聚在一起走同一语境
    groups: dict[str, list[CommentObject]] = {}
    for c in request.comments:
        groups.setdefault(c.video_title, []).append(c)

    size = settings.comment_batch_size
    items: dict[str, CommentScreeningItem] = {}
    errors: dict[str, str] = {}
    for title, comments in groups.items():
        if title not in ctx_cache:
            ctx_cache[title] = await _video_context(executor, comments[0])
        ctx = ctx_cache[title]
        for i in range(0, len(comments), size):
            batch = comments[i:i + size]
            try:
                batch_items = await _screen_batch(executor, ctx, batch)
            except Exception as e:
                err = str(e)[:500]
                for c in batch:
                    errors[c.comment_id] = err
                continue
            items.update(batch_items)
            done += len(batch)
            if progress_cb:
                await progress_cb(done)

    # 按输入顺序回填，保证一一对应
    ts = now_iso()
    for c in request.comments:
        item = items.get(c.comment_id)
        if item is not None:
            results.append(map_screening_item(item, ts).model_dump())
        else:
            err = errors.get(c.comment_id, "筛选失败")
            results.append({"comment_id": c.comment_id, "passed": False,
                            "filter_reason": None, "filter_type": None,
                            "is_car_owner": None, "has_purchase_intent": None,
                            "analysis": "", "processed_at": ts, "error": err})
    return {"results": results}
