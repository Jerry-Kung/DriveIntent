import json
import logging
from pathlib import Path

from app.config import settings
from app.matching.models import OurModelsConfig

logger = logging.getLogger(__name__)

# 按 (路径, mtime) 缓存，文件更新后自动失效
_cache: dict[str, tuple[float, OurModelsConfig]] = {}


def normalize(name: str) -> str:
    """车型/品牌名归一化：小写 + 去所有空白，用于别名匹配。"""
    return "".join((name or "").lower().split())


def load_our_models(path: str | None = None) -> OurModelsConfig | None:
    """加载我方在售车型配置；缺失/解析失败返回 None（调用方跳过降级）。"""
    path = path or settings.our_models_config_path
    p = Path(path)
    if not p.is_file():
        logger.warning("我方车型配置不存在，跳过匹配降级: %s", path)
        return None
    mtime = p.stat().st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        config = OurModelsConfig.model_validate(
            json.loads(p.read_text(encoding="utf-8")))
    except Exception as e:
        logger.warning("我方车型配置解析失败，跳过匹配降级: %s", e)
        return None
    _cache[path] = (mtime, config)
    return config


def build_our_models_summary(config: OurModelsConfig | None) -> str:
    """生成注入用户分析 Prompt 的我方车型摘要文本。"""
    if config is None or not config.models:
        return "（未配置我方在售车型信息，该维度不作考量）"
    lines = []
    for m in config.models:
        lines.append(
            f"- {m.brand} {m.model_name}："
            f"售价 {m.price_min / 10000:.0f}-{m.price_max / 10000:.0f} 万元，"
            f"{m.powertrain} {m.vehicle_category}，"
            f"适用场景：{'/'.join(m.use_case) or '未知'}，"
            f"核心卖点：{'/'.join(m.key_features) or '未知'}，"
            f"目标人群：{m.target_audience or '未知'}")
    return "\n".join(lines)
