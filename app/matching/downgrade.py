from pydantic import BaseModel

from app.matching.loader import normalize
from app.matching.models import OurModel, OurModelsConfig

# 意向强度阶梯，降级沿阶梯向下
_LADDER = ["none", "low", "medium", "high"]
# 视频车型价位中值 / 我方车型价位中值 落在此区间视为价格匹配
PRICE_RATIO_MIN = 0.7
PRICE_RATIO_MAX = 1.4
# 相近品类组：组内任意两个品类互相视为匹配
_RELATED_CATEGORIES = [{"suv", "越野", "越野车", "硬派越野"}]


class DowngradeDecision(BaseModel):
    is_our_model: bool = False
    downgrade_levels: int = 0
    reason: str | None = None


def apply_downgrade(strength: str, levels: int) -> str:
    if levels <= 0 or strength not in _LADDER:
        return strength
    return _LADDER[max(0, _LADDER.index(strength) - levels)]


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


def _category_tokens(category: str | None, use_case: list[str]) -> set[str]:
    tokens = {normalize(category)} if category else set()
    tokens |= {normalize(u) for u in (use_case or [])}
    tokens.discard("")
    for group in _RELATED_CATEGORIES:
        if tokens & group:
            tokens |= group
    return tokens


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
    # 仅使用 vehicle_category 作为视频的分类标记（不包含 use_case），
    # 确保主分类是首要判别标准
    video_tokens = _category_tokens(ctx.get("vehicle_category"), [])
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
