import json

from app.api.mapping import map_screening_item, now_iso
from app.api.schemas import CommentObject, CommentScreeningRequest
from app.config import settings
from app.schemas.skills import (CommentScreeningItem, CommentScreeningResult,
                                VideoContextResult)
from app.skills.executor import SkillExecutor
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
    ctx = {
        "video_context_json": json.dumps(video_context, ensure_ascii=False),
        "comments_json": json.dumps(
            [{"comment_id": c.comment_id, "content": c.comment_content}
             for c in batch], ensure_ascii=False),
        "comment_count": str(len(batch)),
    }
    result: CommentScreeningResult = await executor.run(
        COMMENT_SCREENING_SKILL, ctx, CommentScreeningResult)
    return {i.comment_id: i for i in result.items}


async def run_comment_screening(executor: SkillExecutor,
                                request: CommentScreeningRequest,
                                *, progress_cb=None) -> dict:
    # 按视频标题分组，语境结果在本次调用内缓存复用
    ctx_cache: dict[str, dict] = {}
    results: list[dict] = []
    done = 0
    # 分组：同一 video_title 的评论聚在一起走同一语境
    groups: dict[str, list[CommentObject]] = {}
    for c in request.comments:
        groups.setdefault(c.video_title, []).append(c)

    size = settings.comment_batch_size
    scored: dict[str, CommentScreeningItem] = {}
    for title, comments in groups.items():
        if title not in ctx_cache:
            ctx_cache[title] = await _video_context(executor, comments[0])
        ctx = ctx_cache[title]
        for i in range(0, len(comments), size):
            batch = comments[i:i + size]
            try:
                items = await _screen_batch(executor, ctx, batch)
            except Exception as e:
                for c in batch:
                    scored[c.comment_id] = None  # 标记失败
                    scored[f"__err__{c.comment_id}"] = str(e)[:500]
                continue
            scored.update(items)
            done += len(batch)
            if progress_cb:
                progress_cb(done)

    # 按输入顺序回填，保证一一对应
    ts = now_iso()
    for c in request.comments:
        item = scored.get(c.comment_id)
        if isinstance(item, CommentScreeningItem):
            results.append(map_screening_item(item, ts).model_dump())
        else:
            err = scored.get(f"__err__{c.comment_id}", "筛选失败")
            results.append({"comment_id": c.comment_id, "passed": False,
                            "filter_reason": None, "analysis": "",
                            "processed_at": ts, "error": err})
    return {"results": results}
