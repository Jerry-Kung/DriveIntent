"""评论初筛批次的索引化输入/输出映射（V1.7.2）。

将真实 comment_id 从 LLM 视野中剥离：输入侧用批次内临时序号 index 定位评论，
输出侧按 index 还原真实 comment_id，并在代码层校验 index 集合完整性
（0..n-1 各出现且仅一次），把 ID 转录正确性从 LLM 移交给确定性代码。

两条流水线（app.workflow.pipeline 的 8000 路径、app.api.agent1 的 8100 路径）
共用本模块，保证输入/输出契约一致。

V1.8.5：空 content 评论（无可分析文本）不再进 LLM。廉价模型对 `content=""`
的条目不输出对应 item，若照原样编 index 会整批错位（如 3 条中 1 条空 → 模型只回
[0,1]，映射层 index 集合校验失败，整单 3 次重试全败）。此处将其从 LLM 批次中
剔除、仅对非空评论重新编 index，并在输出侧为被剔除者合成确定性结果，保证每条
输入评论都有落库结果。
"""
import json

from app.schemas.skills import (CommentScreeningBatchResult,
                                CommentScreeningItem, CommentScreeningResult)


def _is_no_content(content: str | None) -> bool:
    """content 是否为空/纯空白。None 与空串一律视为无可分析文本。"""
    return content is None or not str(content).strip()


def _empty_comment_kwargs(comment_id: str) -> dict:
    """被剔除的空 content 评论的确定性合成判定字段。

    comment_actor=off_topic 使其必然不过筛（可分析性为零，不该进下游线索），
    与"无可分析文本"语义一致。reason 说明跳过原因，供审计/排查。
    """
    return {
        "comment_id": comment_id,
        "is_meaningful": False,
        "is_automotive_related": False,
        "is_purchase_related": False,
        "is_suspected_marketing": False,
        "comment_actor": "off_topic",
        "is_car_owner": False,
        "has_purchase_intent": False,
        "positive_attitude": False,
        "intent_signals": [],
        "target_brand": None,
        "target_model": None,
        "intent_strength": "none",
        "reason": "评论内容为空，无可分析文本",
        "confidence": 0.0,
    }


def build_screening_input(video_context: dict,
                          comment_pairs: list[tuple[str, str]]) -> dict:
    """构造初筛 Prompt 的上下文。

    comment_pairs 为 [(comment_id, content), ...]，按批次内顺序。空 content
    评论被剔除（不喂 LLM），仅对非空评论重新编 index（0..k-1）；真实 comment_id
    不进入任何喂给 LLM 的字段。
    """
    sent = [(cid, content) for cid, content in comment_pairs
            if not _is_no_content(content)]
    return {
        "video_context_json": json.dumps(video_context, ensure_ascii=False),
        "comments_json": json.dumps(
            [{"index": i, "content": content}
             for i, (_, content) in enumerate(sent)],
            ensure_ascii=False),
        "comment_count": str(len(sent)),
    }


def map_batch_result(batch: CommentScreeningBatchResult,
                     comment_pairs: list[tuple[str, str]]) -> CommentScreeningResult:
    """把 LLM 输出（index 定位）还原为落库契约（comment_id 定位）。

    comment_pairs 须与 build_screening_input 的入参一致（含空 content 评论，
    原始顺序），用于把非空评论的 index 映射回原始位置，并为被剔除的空 content
    评论合成确定性结果，保证返回 items 与输入一一对应。

    校验 LLM 返回的 index 集合须恰好等于 {0..k-1}（k=非空评论数）：任何缺失、
    重复、越界都抛 ValueError（由 SkillExecutor 在解析/校验失败分支捕获并重试），
    而不是静默张冠李戴。
    """
    sent_indices = [i for i, (_, content) in enumerate(comment_pairs)
                    if not _is_no_content(content)]
    k = len(sent_indices)
    got = [item.index for item in batch.items]
    if len(got) != len(set(got)) or set(got) != set(range(k)):
        raise ValueError(
            f"初筛输出 index 集合不完整：期望 {sorted(range(k))}，"
            f"实际 {sorted(got)}")
    # LLM 输出 index=j 即对应第 j 个非空评论；按此重建有序列表
    by_index = {item.index: item for item in batch.items}
    sent_items = [by_index[j] for j in range(k)]
    items = []
    sent_pos = 0
    for cid, content in comment_pairs:
        if _is_no_content(content):
            items.append(CommentScreeningItem(**_empty_comment_kwargs(cid)))
        else:
            src = sent_items[sent_pos]
            sent_pos += 1
            items.append(CommentScreeningItem(
                comment_id=cid,
                **src.model_dump(exclude={"index"})))
    return CommentScreeningResult(items=items)
