"""评论初筛批次的索引化输入/输出映射（V1.7.2）。

将真实 comment_id 从 LLM 视野中剥离：输入侧用批次内临时序号 index 定位评论，
输出侧按 index 还原真实 comment_id，并在代码层校验 index 集合完整性
（0..n-1 各出现且仅一次），把 ID 转录正确性从 LLM 移交给确定性代码。

两条流水线（app.workflow.pipeline 的 8000 路径、app.api.agent1 的 8100 路径）
共用本模块，保证输入/输出契约一致。
"""
import json

from app.schemas.skills import (CommentScreeningBatchResult,
                                CommentScreeningItem, CommentScreeningResult)


def build_screening_input(video_context: dict,
                          comment_pairs: list[tuple[str, str]]) -> dict:
    """构造初筛 Prompt 的上下文。

    comment_pairs 为 [(comment_id, content), ...]，按批次内顺序；函数为其编
    index（0..n-1），真实 comment_id 不进入任何喂给 LLM 的字段。
    """
    return {
        "video_context_json": json.dumps(video_context, ensure_ascii=False),
        "comments_json": json.dumps(
            [{"index": i, "content": content}
             for i, (_, content) in enumerate(comment_pairs)],
            ensure_ascii=False),
        "comment_count": str(len(comment_pairs)),
    }


def map_batch_result(batch: CommentScreeningBatchResult,
                     comment_ids: list[str]) -> CommentScreeningResult:
    """把 LLM 输出（index 定位）还原为落库契约（comment_id 定位）。

    校验返回的 index 集合须恰好等于 {0..n-1}：任何缺失、重复、越界都抛
    ValueError（由 SkillExecutor 在解析/校验失败分支捕获并重试），而不是
    静默张冠李戴。
    """
    n = len(comment_ids)
    expected = set(range(n))
    got = [item.index for item in batch.items]
    if len(got) != len(set(got)) or set(got) != expected:
        raise ValueError(
            f"初筛输出 index 集合不完整：期望 {sorted(expected)}，"
            f"实际 {sorted(got)}")
    by_index = {item.index: item for item in batch.items}
    items = []
    for i, cid in enumerate(comment_ids):
        src = by_index[i]
        items.append(CommentScreeningItem(
            comment_id=cid,
            **src.model_dump(exclude={"index"})))
    return CommentScreeningResult(items=items)
