from pydantic import BaseModel

from app.matching.loader import normalize
from app.matching.models import OurModel, OurModelsConfig

# 视频车型价位中值 / 我方车型价位中值 落在此区间视为价格匹配
PRICE_RATIO_MIN = 0.7
PRICE_RATIO_MAX = 1.4
# 相近品类组：组内任意两个品类互相视为匹配
_RELATED_CATEGORIES = [{"suv", "越野", "越野车", "硬派越野"}]


class DowngradeDecision(BaseModel):
    is_our_model: bool = False
    downgrade_levels: int = 0
    reason: str | None = None


def _match_names(brand: str | None, model: str | None,
                 config: OurModelsConfig) -> str:
    """三级匹配：our_model（跳过后处理）/ our_brand（不降级）/ none。"""
    b, m = normalize(brand or ""), normalize(model or "")
    for om in config.models:
        names = {normalize(om.model_name)} | {normalize(a) for a in om.aliases}
        names.discard("")
        if m and m in names:
            return "our_model"
    if b and any(b == normalize(om.brand) for om in config.models):
        return "our_brand"
    return "none"


def _expand_related(tokens: set[str]) -> set[str]:
    """将 tokens 中的品类根据相近品类组扩展（例如 SUV 与越野互相视为匹配）。"""
    for group in _RELATED_CATEGORIES:
        if tokens & group:
            tokens |= group
    return tokens


def _category_tokens(category: str | None, use_case: list[str]) -> set[str]:
    """构造品类 tokens：主类别 + 用途列表，两者都经相近品类组扩展。"""
    tokens = {normalize(category)} if category else set()
    tokens |= {normalize(u) for u in (use_case or [])}
    tokens.discard("")
    return _expand_related(tokens)


def _video_category_tokens(ctx: dict) -> set[str]:
    """视频侧品类取词：主类别优先，缺失时回退 use_case（用户裁决的规则）。

    取词规则（用户需求）：
    1. vehicle_category 非空 → 仅取 vehicle_category（主类别优先）
    2. vehicle_category 为空且 use_case 非空 → 回退取 use_case（兜底）
    3. 两者都空 → 返回空集（该维度不计入不匹配）
    """
    cat = ctx.get("vehicle_category")
    if cat:
        return _expand_related({normalize(cat)})
    use_case = ctx.get("use_case") or []
    tokens = {normalize(u) for u in use_case if u}
    tokens.discard("")
    return _expand_related(tokens)


def _price_matches(video_mid: float, om: OurModel) -> bool:
    our_mid = (om.price_min + om.price_max) / 2
    if our_mid <= 0:
        return True
    return PRICE_RATIO_MIN <= video_mid / our_mid <= PRICE_RATIO_MAX


def evaluate_video_context(ctx: dict, config: OurModelsConfig | None,
                           *, enabled: bool = True) -> DowngradeDecision:
    """按视频语境评估降级决策。ctx 为 VideoContextResult.model_dump()。

    保守策略：任一维度信息缺失（null）则该维度不计入不匹配；
    多款我方车型按维度取最宽松结果（任一款匹配即算匹配）。
    """
    if not enabled or config is None or not config.models:
        return DowngradeDecision()
    match = _match_names(ctx.get("brand"), ctx.get("model"), config)
    if match == "our_model":
        return DowngradeDecision(is_our_model=True)
    if match == "our_brand":
        return DowngradeDecision()

    mismatches: list[str] = []
    pmin, pmax = ctx.get("price_range_min"), ctx.get("price_range_max")
    if pmin is not None and pmax is not None and pmax > 0:
        video_mid = (pmin + pmax) / 2
        if not any(_price_matches(video_mid, om) for om in config.models):
            mismatches.append(
                f"价位不匹配（视频车型约 {video_mid / 10000:.0f} 万元，"
                f"与我方在售车型价位差距过大）")
    video_tokens = _video_category_tokens(ctx)
    if video_tokens:
        matched = any(
            video_tokens & _category_tokens(om.vehicle_category, om.use_case)
            for om in config.models)
        if not matched:
            desc = ctx.get("vehicle_category") or "/".join(
                ctx.get("use_case") or [])
            mismatches.append(f"品类/用途不匹配（视频车型为 {desc}）")

    if not mismatches:
        return DowngradeDecision()
    return DowngradeDecision(downgrade_levels=len(mismatches),
                             reason="；".join(mismatches))
