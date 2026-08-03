# DriveIntent V1.1 实现计划

> 版本：V1.1 | 日期：2026-07-27

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 V1.0 基础上实现 filter_type 评论分类、已购/已大定车主过滤、非我方车型意向降级与主力车型配置能力。

**Architecture:** 新增 `app/matching/` 模块（配置加载 + 纯函数降级规则），三个 Skill 升级 v2 Prompt（叠加不覆盖 v1），Agent 1 在边界映射前做规则后处理，Agent 2 通过 Prompt 注入我方车型摘要。API 作业机制（api_job/Worker/轮询）零改动。

**Tech Stack:** Python 3.11+ / FastAPI / Pydantic v2 / SQLAlchemy / pytest + pytest-asyncio / MockProvider（测试不依赖真实 LLM）

**设计文档:** `claude_docs/2026-07-27-v1.1-design.md`（本计划的唯一需求来源）

## Global Constraints

- 全部代码注释、文档、commit message 用简体中文；commit message 结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 测试命令统一为 `python -m pytest tests -q`（在仓库根目录 `D:\KLH\Projects\dfms\DriveIntent` 运行）；单测用 `python -m pytest <file>::<test> -v`
- TDD：每个任务先写失败测试，再写最小实现
- 不改动：`api_job` 表结构、`ApiJobWorker`、认证、轮询契约、V0 lead 流水线逻辑
- v1 Prompt 文件保留不动，v2 为新文件，yaml 切换 `prompt_file`
- 价格单位一律为人民币元（整数）
- 降级阶梯固定为 `high → medium → low → none`，降到 none 为止
- 信息缺失（null）的维度不计入不匹配（保守策略）
- 我方车型配置缺失/解析失败：警告日志 + 跳过降级，不使整单失败
- Pydantic v2 中字段名以 `model_` 开头会触发 protected namespace 警告，凡含 `model_id`/`model_name` 字段的模型必须加 `model_config = ConfigDict(protected_namespaces=())`

---

### Task 1: 我方车型配置结构与加载器

**Files:**
- Create: `app/matching/__init__.py`（空文件）
- Create: `app/matching/models.py`
- Create: `app/matching/loader.py`
- Create: `config/our_models.example.json`
- Modify: `app/config.py`（Settings 里 `api_worker_concurrency` 之后加两个字段）
- Modify: `.env.example`（若存在；追加两行配置）
- Modify: `.gitignore`（追加 `config/our_models.json`，真实业务配置不入库）
- Test: `tests/test_matching_loader.py`

**Interfaces:**
- Produces:
  - `app.matching.models.OurModel`（字段见下）、`OurModelsConfig(version: str, updated_at: str, models: list[OurModel])`
  - `app.matching.loader.load_our_models(path: str | None = None) -> OurModelsConfig | None`
  - `app.matching.loader.normalize(name: str) -> str`（小写去空格）
  - `app.matching.loader.build_our_models_summary(config: OurModelsConfig | None) -> str`
  - `settings.our_models_config_path: str`（默认 `"config/our_models.json"`）、`settings.intent_downgrade_enabled: bool`（默认 `True`）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_matching_loader.py`：

```python
import json

from app.matching.loader import (build_our_models_summary, load_our_models,
                                 normalize)
from app.matching.models import OurModelsConfig

_CFG = {
    "version": "1.0", "updated_at": "2026-07-27",
    "models": [{
        "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
        "aliases": ["X7", "方舟 x7"], "price_min": 350000, "price_max": 420000,
        "vehicle_category": "越野", "powertrain": "PHEV",
        "use_case": ["越野", "家用"], "key_features": ["四驱", "大空间"],
        "target_audience": "30-45岁户外爱好者"}]}


def _write(tmp_path, data) -> str:
    p = tmp_path / "our_models.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_normalize_lower_and_strip_spaces():
    assert normalize("方舟 X7") == "方舟x7"
    assert normalize("  Tank 400 ") == "tank400"
    assert normalize("") == ""


def test_load_valid_config(tmp_path):
    cfg = load_our_models(_write(tmp_path, _CFG))
    assert isinstance(cfg, OurModelsConfig)
    assert cfg.models[0].model_name == "方舟X7"
    assert cfg.models[0].price_min == 350000


def test_load_missing_file_returns_none(tmp_path):
    assert load_our_models(str(tmp_path / "nope.json")) is None


def test_load_invalid_json_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{broken", encoding="utf-8")
    assert load_our_models(str(p)) is None


def test_load_schema_mismatch_returns_none(tmp_path):
    # models 元素缺少必填 price_min
    bad = {"models": [{"model_id": "a", "brand": "b", "model_name": "c",
                       "price_max": 1, "vehicle_category": "SUV"}]}
    assert load_our_models(_write(tmp_path, bad)) is None


def test_load_uses_default_settings_path(tmp_path, monkeypatch):
    from app.config import settings
    path = _write(tmp_path, _CFG)
    monkeypatch.setattr(settings, "our_models_config_path", path)
    cfg = load_our_models()
    assert cfg is not None and cfg.models[0].brand == "方舟"


def test_summary_contains_key_info(tmp_path):
    cfg = load_our_models(_write(tmp_path, _CFG))
    text = build_our_models_summary(cfg)
    assert "方舟X7" in text and "35" in text and "越野" in text


def test_summary_none_config():
    text = build_our_models_summary(None)
    assert "未配置" in text


def test_settings_new_fields_defaults():
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.our_models_config_path == "config/our_models.json"
    assert s.intent_downgrade_enabled is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_matching_loader.py -v`
Expected: FAIL（`ModuleNotFoundError: app.matching`）

- [ ] **Step 3: 实现**

`app/config.py` 在 `api_worker_concurrency: int = 3` 之后加：

```python
    # V1.1 我方车型匹配与降级
    our_models_config_path: str = "config/our_models.json"
    intent_downgrade_enabled: bool = True
```

创建 `app/matching/__init__.py`（空文件）。

创建 `app/matching/models.py`：

```python
from pydantic import BaseModel, ConfigDict


class OurModel(BaseModel):
    # model_id/model_name 与 Pydantic 保护前缀冲突，显式放开
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    brand: str
    model_name: str
    aliases: list[str] = []
    price_min: int
    price_max: int
    vehicle_category: str
    powertrain: str = ""
    use_case: list[str] = []
    key_features: list[str] = []
    target_audience: str = ""


class OurModelsConfig(BaseModel):
    version: str = "1.0"
    updated_at: str = ""
    models: list[OurModel] = []
```

创建 `app/matching/loader.py`：

```python
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
```

创建 `config/our_models.example.json`：

```json
{
  "version": "1.0",
  "updated_at": "2026-07-27",
  "models": [
    {
      "model_id": "example-x7",
      "brand": "示例品牌",
      "model_name": "示例X7",
      "aliases": ["X7", "示例 x7"],
      "price_min": 350000,
      "price_max": 420000,
      "vehicle_category": "越野",
      "powertrain": "PHEV",
      "use_case": ["越野", "家用"],
      "key_features": ["四驱", "大空间", "智驾"],
      "target_audience": "30-45岁户外爱好者"
    }
  ]
}
```

`.gitignore` 追加一行（若尚未存在）：

```
config/our_models.json
```

`.env.example`（若仓库存在此文件）追加：

```
# V1.1 我方车型匹配与意向降级
OUR_MODELS_CONFIG_PATH=config/our_models.json
INTENT_DOWNGRADE_ENABLED=true
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_matching_loader.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 跑全量测试确认无回归，提交**

Run: `python -m pytest tests -q`

```powershell
git add app/matching app/config.py config/our_models.example.json .gitignore tests/test_matching_loader.py
git add .env.example   # 若有改动
git commit -m @'
feat(v1.1): 新增我方车型配置结构与加载器

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: 降级规则纯函数

**Files:**
- Create: `app/matching/downgrade.py`
- Test: `tests/test_matching_downgrade.py`

**Interfaces:**
- Consumes: `OurModel` / `OurModelsConfig`（Task 1）、`normalize`（Task 1）
- Produces:
  - `DowngradeDecision(is_our_model: bool = False, downgrade_levels: int = 0, reason: str | None = None)`（Pydantic BaseModel）
  - `evaluate_video_context(ctx: dict, config: OurModelsConfig | None, *, enabled: bool = True) -> DowngradeDecision` — `ctx` 为 `VideoContextResult.model_dump()` 的 dict
  - `apply_downgrade(strength: str, levels: int) -> str`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_matching_downgrade.py`：

```python
from app.matching.downgrade import (DowngradeDecision, apply_downgrade,
                                    evaluate_video_context)
from app.matching.models import OurModel, OurModelsConfig


def _config(**overrides) -> OurModelsConfig:
    base = dict(model_id="fz-x7", brand="方舟", model_name="方舟X7",
                aliases=["X7"], price_min=350000, price_max=420000,
                vehicle_category="越野", powertrain="PHEV",
                use_case=["越野", "家用"])
    base.update(overrides)
    return OurModelsConfig(models=[OurModel(**base)])


def _ctx(**overrides) -> dict:
    # 默认：10万纯电微型车 —— 与我方38万越野车双维度不匹配
    base = dict(brand="微光", model="微光mini",
                price_range_min=90000, price_range_max=110000,
                vehicle_category="微型车", use_case=["家用", "通勤"])
    base.update(overrides)
    return base


def test_apply_downgrade_ladder():
    assert apply_downgrade("high", 1) == "medium"
    assert apply_downgrade("high", 2) == "low"
    assert apply_downgrade("medium", 2) == "none"
    assert apply_downgrade("low", 1) == "none"


def test_apply_downgrade_floor_and_noop():
    assert apply_downgrade("none", 2) == "none"      # 不越界
    assert apply_downgrade("high", 0) == "high"      # 0 级不动
    assert apply_downgrade("unknown", 1) == "unknown"  # 非法值原样返回


def test_our_model_matched_by_name():
    d = evaluate_video_context(_ctx(brand="方舟", model="方舟X7"), _config())
    assert d.is_our_model is True and d.downgrade_levels == 0


def test_our_model_matched_by_alias_case_insensitive():
    d = evaluate_video_context(_ctx(brand="方舟", model="x7"), _config())
    assert d.is_our_model is True


def test_our_brand_other_model_no_downgrade():
    d = evaluate_video_context(_ctx(brand="方舟", model="方舟Z1"), _config())
    assert d.is_our_model is False and d.downgrade_levels == 0


def test_both_dimensions_mismatch_two_levels():
    d = evaluate_video_context(_ctx(), _config())
    assert d.downgrade_levels == 2
    assert d.reason and "价位" in d.reason and "品类" in d.reason


def test_price_only_mismatch_one_level():
    # 品类相同（越野），仅价格差距大
    d = evaluate_video_context(
        _ctx(vehicle_category="越野", use_case=["越野"]), _config())
    assert d.downgrade_levels == 1
    assert "价位" in d.reason


def test_category_only_mismatch_one_level():
    # 价格匹配（38万中值比 38.5万，比值≈0.99），仅品类不匹配
    d = evaluate_video_context(
        _ctx(price_range_min=360000, price_range_max=400000), _config())
    assert d.downgrade_levels == 1
    assert "品类" in d.reason


def test_price_ratio_boundaries():
    # 我方中值 385000；0.7 边界 → 269500；1.4 边界 → 539000
    ok_low = _ctx(price_range_min=269500, price_range_max=269500,
                  vehicle_category="越野", use_case=[])
    ok_high = _ctx(price_range_min=539000, price_range_max=539000,
                   vehicle_category="越野", use_case=[])
    assert evaluate_video_context(ok_low, _config()).downgrade_levels == 0
    assert evaluate_video_context(ok_high, _config()).downgrade_levels == 0


def test_suv_and_offroad_are_related():
    d = evaluate_video_context(
        _ctx(price_range_min=360000, price_range_max=400000,
             vehicle_category="SUV", use_case=[]), _config())
    assert d.downgrade_levels == 0


def test_missing_price_not_counted():
    d = evaluate_video_context(
        _ctx(price_range_min=None, price_range_max=None), _config())
    assert d.downgrade_levels == 1  # 只剩品类一个可判维度


def test_missing_category_not_counted():
    d = evaluate_video_context(
        _ctx(vehicle_category=None, use_case=[]), _config())
    assert d.downgrade_levels == 1  # 只剩价格一个可判维度


def test_all_missing_no_downgrade():
    d = evaluate_video_context(
        _ctx(price_range_min=None, price_range_max=None,
             vehicle_category=None, use_case=[]), _config())
    assert d.downgrade_levels == 0


def test_multi_models_take_most_lenient():
    cfg = OurModelsConfig(models=[
        _config().models[0],
        OurModel(model_id="fz-m1", brand="方舟", model_name="方舟M1",
                 aliases=[], price_min=90000, price_max=120000,
                 vehicle_category="微型车", use_case=["家用", "通勤"]),
    ])
    # 视频是10万微型车：与第二款车型两个维度都匹配 → 不降级
    d = evaluate_video_context(_ctx(), cfg)
    assert d.downgrade_levels == 0


def test_disabled_skips():
    d = evaluate_video_context(_ctx(), _config(), enabled=False)
    assert d == DowngradeDecision()


def test_none_config_skips():
    d = evaluate_video_context(_ctx(), None)
    assert d == DowngradeDecision()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_matching_downgrade.py -v`
Expected: FAIL（`ModuleNotFoundError: app.matching.downgrade`）

- [ ] **Step 3: 实现**

创建 `app/matching/downgrade.py`：

```python
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
    video_tokens = _category_tokens(ctx.get("vehicle_category"),
                                    ctx.get("use_case") or [])
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_matching_downgrade.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量测试 + 提交**

Run: `python -m pytest tests -q`

```powershell
git add app/matching/downgrade.py tests/test_matching_downgrade.py
git commit -m @'
feat(v1.1): 新增车型匹配度评估与意向降级纯函数

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 3: 内部 Skill Schema 扩展

**Files:**
- Modify: `app/schemas/skills.py`
- Test: `tests/test_api_skill_schema.py`（追加用例）

**Interfaces:**
- Produces:
  - `CommentScreeningItem` 新增：`owner_status: Literal["none", "existing_owner", "ordered_owner"] = "none"`、`comment_actor: Literal["genuine_user", "bot_spam", "marketing_account", "noise", "off_topic"] = "genuine_user"`
  - `VideoContextResult` 新增：`price_range_min: int | None = None`、`price_range_max: int | None = None`、`vehicle_category: str | None = None`、`powertrain: str | None = None`、`use_case: list[str] = []`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_skill_schema.py` 末尾追加：

```python
def test_screening_item_v11_new_fields_defaults():
    from app.schemas.skills import CommentScreeningItem
    item = CommentScreeningItem(comment_id="c1")
    assert item.owner_status == "none"
    assert item.comment_actor == "genuine_user"


def test_screening_item_v11_new_fields_values():
    from app.schemas.skills import CommentScreeningItem
    item = CommentScreeningItem(comment_id="c1", owner_status="ordered_owner",
                                comment_actor="marketing_account")
    assert item.owner_status == "ordered_owner"
    assert item.comment_actor == "marketing_account"


def test_screening_item_v11_illegal_value_rejected():
    import pytest
    from pydantic import ValidationError
    from app.schemas.skills import CommentScreeningItem
    with pytest.raises(ValidationError):
        CommentScreeningItem(comment_id="c1", owner_status="maybe_owner")


def test_video_context_v11_new_fields_defaults():
    from app.schemas.skills import VideoContextResult
    ctx = VideoContextResult()
    assert ctx.price_range_min is None
    assert ctx.vehicle_category is None
    assert ctx.use_case == []


def test_video_context_v11_dump_contains_new_fields():
    from app.schemas.skills import VideoContextResult
    d = VideoContextResult(price_range_min=90000, price_range_max=110000,
                           vehicle_category="微型车",
                           use_case=["家用"]).model_dump()
    assert d["price_range_min"] == 90000
    assert d["vehicle_category"] == "微型车"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_skill_schema.py -v`
Expected: 新增用例 FAIL（字段不存在）

- [ ] **Step 3: 实现**

`app/schemas/skills.py`——`VideoContextResult` 在 `analysis_notes` 之后追加：

```python
    # V1.1：车型客观属性，用于我方车型匹配与意向降级（LLM 常识估算，缺失为 None）
    price_range_min: int | None = None
    price_range_max: int | None = None
    vehicle_category: str | None = None
    powertrain: str | None = None
    use_case: list[str] = []
```

`CommentScreeningItem` 在 `confidence` 之前追加：

```python
    # V1.1：车主状态与评论主体类型（两者正交，由代码层合成 filter_type）
    owner_status: Literal["none", "existing_owner", "ordered_owner"] = "none"
    comment_actor: Literal["genuine_user", "bot_spam", "marketing_account",
                           "noise", "off_topic"] = "genuine_user"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_skill_schema.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量测试 + 提交**

Run: `python -m pytest tests -q`（旧字段全部有默认值，V0 用例应无回归）

```powershell
git add app/schemas/skills.py tests/test_api_skill_schema.py
git commit -m @'
feat(v1.1): 内部 Skill Schema 扩展车主状态/评论主体/车型属性字段

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 4: filter_type 合成与边界映射

**Files:**
- Modify: `app/api/schemas.py`（`ScreeningResult` 扩展）
- Modify: `app/api/mapping.py`（删除 `_filter_reason`，新增合成逻辑）
- Test: `tests/test_api_mapping.py`（追加用例；既有 3 个 screening 用例不改，靠兼容回退通过）

**Interfaces:**
- Consumes: `CommentScreeningItem`（Task 3 扩展后）
- Produces:
  - `app.api.mapping.resolve_filter_type(item: CommentScreeningItem) -> str` — 返回七值之一
  - `map_screening_item(item: CommentScreeningItem, processed_at: str, *, downgrade_applied: bool = False, downgrade_reason: str | None = None) -> ScreeningResult`（新增两个 keyword-only 参数，Task 6 调用）
  - `ScreeningResult` 新增：`filter_type: str = "genuine_user"`、`intent_strength: str = "none"`、`downgrade_applied: bool = False`、`downgrade_reason: str | None = None`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_mapping.py` 末尾追加：

```python
def test_resolve_filter_type_priority_actor_over_owner():
    # 营销号 + 车主特征同时命中 → 归营销号
    from app.api.mapping import resolve_filter_type
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                comment_actor="marketing_account",
                                owner_status="existing_owner")
    assert resolve_filter_type(item) == "marketing_account"


def test_resolve_filter_type_owner_values():
    from app.api.mapping import resolve_filter_type
    existing = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                    owner_status="existing_owner")
    ordered = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                   owner_status="ordered_owner")
    assert resolve_filter_type(existing) == "existing_owner"
    assert resolve_filter_type(ordered) == "ordered_owner"


def test_resolve_filter_type_legacy_fallback():
    # LLM 未输出新字段（默认值）时回退 V1.0 判定
    from app.api.mapping import resolve_filter_type
    marketing = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                     is_suspected_marketing=True)
    noise = CommentScreeningItem(comment_id="c", is_meaningful=False)
    ok = CommentScreeningItem(comment_id="c", is_meaningful=True)
    assert resolve_filter_type(marketing) == "marketing_account"
    assert resolve_filter_type(noise) == "noise"
    assert resolve_filter_type(ok) == "genuine_user"


def test_map_screening_owner_filtered_with_reason():
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                owner_status="existing_owner",
                                intent_strength="low", reason="提车三个月")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_type == "existing_owner"
    assert r.filter_reason == "已购车主评论"


def test_map_screening_ordered_owner_reason():
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                owner_status="ordered_owner")
    r = map_screening_item(item, "t")
    assert r.filter_reason == "已下定车主评论"


def test_map_screening_off_topic_reason():
    item = CommentScreeningItem(comment_id="c", comment_actor="off_topic")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_reason == "与汽车无关"


def test_map_screening_exposes_intent_and_downgrade():
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                intent_strength="medium", reason="询价")
    r = map_screening_item(item, "t", downgrade_applied=True,
                           downgrade_reason="价位不匹配")
    assert r.passed is True and r.filter_type == "genuine_user"
    assert r.intent_strength == "medium"
    assert r.downgrade_applied is True
    assert r.downgrade_reason == "价位不匹配"


def test_map_screening_defaults_no_downgrade():
    item = CommentScreeningItem(comment_id="c", is_meaningful=True)
    r = map_screening_item(item, "t")
    assert r.downgrade_applied is False and r.downgrade_reason is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_mapping.py -v`
Expected: 新增用例 FAIL（`resolve_filter_type` 不存在 / 字段缺失）；既有用例 PASS

- [ ] **Step 3: 实现**

`app/api/schemas.py`——`ScreeningResult` 改为：

```python
class ScreeningResult(BaseModel):
    comment_id: str
    passed: bool
    filter_reason: str | None = None
    # V1.1 新增：评论内容类型 + 降级后意向强度 + 降级核查信息
    filter_type: str = "genuine_user"
    intent_strength: str = "none"
    downgrade_applied: bool = False
    downgrade_reason: str | None = None
    analysis: str = ""
    processed_at: str = ""
    error: str | None = None
```

`app/api/mapping.py`——删除 `_filter_reason` 函数，新增：

```python
# filter_type → 对外 filter_reason 文案（genuine_user 无 reason）
_FILTER_REASON = {
    "existing_owner": "已购车主评论",
    "ordered_owner": "已下定车主评论",
    "bot_spam": "批量刷屏水军",
    "marketing_account": "广告/引流类评论",
    "noise": "无实质内容",
    "off_topic": "与汽车无关",
}


def resolve_filter_type(item: CommentScreeningItem) -> str:
    """合成 filter_type。优先级：actor 异常类 > 车主状态 > 兼容回退 > 真实用户。

    comment_actor 本身即按 off_topic > noise > bot_spam > marketing_account
    的语义由 LLM 五选一，代码层只需再叠加车主状态与 V1.0 旧字段回退。
    """
    if item.comment_actor != "genuine_user":
        return item.comment_actor
    if item.owner_status != "none":
        return item.owner_status
    # 兼容 LLM 未输出新字段的情况，回退 V1.0 判定
    if item.is_suspected_marketing:
        return "marketing_account"
    if not item.is_meaningful:
        return "noise"
    return "genuine_user"


def map_screening_item(item: CommentScreeningItem, processed_at: str, *,
                       downgrade_applied: bool = False,
                       downgrade_reason: str | None = None) -> ScreeningResult:
    filter_type = resolve_filter_type(item)
    passed = filter_type == "genuine_user"
    reason = None if passed else _FILTER_REASON[filter_type]
    analysis = item.reason or ("通过初筛。" if passed else "未通过初筛。")
    return ScreeningResult(comment_id=item.comment_id, passed=passed,
                           filter_reason=reason, filter_type=filter_type,
                           intent_strength=item.intent_strength,
                           downgrade_applied=downgrade_applied,
                           downgrade_reason=downgrade_reason,
                           analysis=analysis, processed_at=processed_at)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_mapping.py -v`
Expected: 全部 PASS（含既有用例——旧字段回退逻辑保证兼容）

- [ ] **Step 5: 全量测试 + 提交**

Run: `python -m pytest tests -q`

```powershell
git add app/api/schemas.py app/api/mapping.py tests/test_api_mapping.py
git commit -m @'
feat(v1.1): filter_type 七分类合成与 API 输出字段扩展

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 5: Agent 1 侧 v2 Prompt（视频语境 + 评论筛选）

**Files:**
- Create: `app/skills/prompts/video_context_analysis_v2.txt`
- Create: `app/skills/prompts/comment_lead_screening_v2.txt`
- Modify: `app/skills/configs/video_context_analysis.yaml`
- Modify: `app/skills/configs/comment_lead_screening.yaml`
- Modify: `app/workflow/pipeline.py`（`SKILL_VERSIONS` 两项 bump 到 "1.1"）
- Test: `tests/test_skill_executor.py`（追加用例）

**Interfaces:**
- Consumes: `load_skill_config` / `render_prompt`（现有）
- Produces: v2 Prompt 文件（模板变量不变：视频语境用 `$video_json`，评论筛选用 `$video_context_json` / `$comments_json` / `$comment_count`），yaml `version: "1.1"`、`prompt_version: "v2"`

**注意：** `SKILL_VERSIONS` bump 会使 V0 流水线对已有视频按新版本重新调度语境分析——这是预期行为（新 Prompt 输出新字段），在 commit message 中注明。

- [ ] **Step 1: 写失败测试**

在 `tests/test_skill_executor.py` 末尾追加：

```python
def test_v11_video_context_config_uses_v2():
    from app.skills.executor import load_skill_config
    config = load_skill_config("video_context_analysis")
    assert config.prompt_file == "video_context_analysis_v2.txt"
    assert config.prompt_version == "v2"
    assert config.version == "1.1"


def test_v11_screening_config_uses_v2():
    from app.skills.executor import load_skill_config
    config = load_skill_config("comment_lead_screening")
    assert config.prompt_file == "comment_lead_screening_v2.txt"
    assert config.prompt_version == "v2"


def test_v11_video_context_prompt_renders_with_new_fields():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("video_context_analysis")
    text = render_prompt(config, {"video_json": "{}"})
    assert "price_range_min" in text
    assert "vehicle_category" in text
    assert "use_case" in text


def test_v11_screening_prompt_renders_with_owner_fields():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("comment_lead_screening")
    text = render_prompt(config, {"video_context_json": "{}",
                                  "comments_json": "[]",
                                  "comment_count": "0"})
    assert "owner_status" in text
    assert "comment_actor" in text
    assert "existing_owner" in text and "ordered_owner" in text
    # 反例约束必须在 Prompt 中明确
    assert "准备订" in text or "想下定" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_skill_executor.py -v`
Expected: 新增用例 FAIL（config 仍指向 v1）

- [ ] **Step 3: 创建 v2 Prompt 文件与 yaml 切换**

创建 `app/skills/prompts/video_context_analysis_v2.txt`：

```
你是汽车行业短视频内容分析专家。请分析以下抖音视频信息，输出视频语境，供后续评论分析使用。

视频信息（JSON）：
$video_json

请严格输出以下 JSON 格式（不要输出任何其他内容，不要用 Markdown 代码块）：
{
  "brand": "视频主要涉及的品牌，无法判断则为 null",
  "model": "视频主要涉及的车型，无法判断则为 null",
  "content_type": "内容类型，如：新车发布/评测/对比/用车分享/营销宣传",
  "main_topics": ["主要讨论主题，如价格、动力、空间"],
  "target_audience": "目标受众描述",
  "competitor_models": ["视频中提到或暗示的竞品车型"],
  "commercial_context": "商业属性，如：车企官方宣传/汽车媒体/个人博主",
  "analysis_notes": "针对该视频评论分析的注意事项，一句话",
  "price_range_min": 该车型市场售价区间下限（人民币元整数，如 100000），无法判断为 null,
  "price_range_max": 该车型市场售价区间上限（人民币元整数），无法判断为 null,
  "vehicle_category": "车辆品类：轿车/SUV/MPV/越野/皮卡/跑车/微型车，无法判断为 null",
  "powertrain": "动力形式：燃油/纯电/插混(PHEV)/油混(HEV)/增程，无法判断为 null",
  "use_case": ["车型主要用途，如：家用/通勤/越野/商务/运营，无法判断为空数组"]
}

要求：
1. 只依据给出的信息判断，不要编造。
2. 品牌车型尽量使用规范名称（如"坦克300"而不是"坦克三百"）。
3. price_range_min/max 依据你对该车型公开市场售价的常识估算；识别不出具体车型时输出 null，不得编造。
```

创建 `app/skills/prompts/comment_lead_screening_v2.txt`：

```
你是汽车销售线索分析专家。请结合视频语境，逐条分析以下抖音评论，判断每条评论的购车线索价值、评论主体类型与车主状态。

视频语境（JSON）：
$video_context_json

评论列表（共 $comment_count 条，JSON）：
$comments_json

判断购车意向时必须区分以下四个层次：
1. 正面情绪（如"好看""厉害""good"）——不代表购车意向；
2. 产品兴趣（如"内饰不错""颜色好看"）——有兴趣但未进入决策；
3. 潜在购车需求（如"和XX比怎么样""保养贵不贵"）——开始了解或比较；
4. 明确购车意向（如"落地多少钱""哪里能试驾""置换有补贴吗"）——接近交易或行动。

评论主体类型 comment_actor（五选一）：
- genuine_user：真实普通用户（默认）；
- bot_spam：批量刷屏水军——短句复读、模板化口号、纯表情/数字灌水、与多条评论雷同；
- marketing_account：营销号/广告引流——含联系方式、导流话术、号召他人购买、软广模板化夸赞；
- noise："厉害""哈哈""排面"等无意义或纯情绪内容；
- off_topic：与视频和汽车均无关的内容。

车主状态 owner_status（三选一，与 comment_actor 独立判断）：
- existing_owner：已购车主——明确表述已提车/已在用车，如"提车三个月""我这台开了2万公里""昨天刚做完首保""车机用起来很流畅"；
- ordered_owner：已下定车主——已支付定金/锁单待提车，如"大定已下""交了定金等排产""锁单了，等提车"；
- none：以上都不是。
车主判断的反例（必须判为 none）：
- "准备订""想下定""打算买""纠结要不要下定"是购买意向，不是已购/已定；
- 咨询他人用车体验（如"车主们保养贵不贵""已提车的朋友说说油耗"）是潜在买家，不是车主；
- 证据不足、无法确定时一律填 none。

注意事项：
- 负面情绪中包含真实换车需求（如"现在这车售后太差，准备换品牌"）属于有价值线索，不得过滤；
- 疑似车主口吻但同时带引流/广告特征的，comment_actor 判为 marketing_account；
- 旧字段 is_meaningful / is_suspected_marketing / is_automotive_related 仍需按原义输出，
  并与 comment_actor 保持一致（如 comment_actor=noise 时 is_meaningful=false）。

intent_signals 可选值：price_inquiry（询价）、trade_in（置换）、test_drive（试驾）、
finance（金融政策）、store_visit（门店/交付）、comparison（竞品对比）、
config_inquiry（配置咨询）、cost_concern（用车成本）、purchase_plan（购车计划）。

请严格输出以下 JSON（不要输出任何其他内容）。items 数组必须与输入评论一一对应：
数量相同、comment_id 完全一致、不得遗漏或新增：
{
  "items": [
    {
      "comment_id": "输入中的 comment_id，原样返回",
      "is_meaningful": true,
      "is_automotive_related": true,
      "is_purchase_related": true,
      "is_suspected_marketing": false,
      "comment_actor": "genuine_user | bot_spam | marketing_account | noise | off_topic",
      "owner_status": "none | existing_owner | ordered_owner",
      "intent_signals": ["price_inquiry"],
      "target_brand": "评论指向的品牌，没有则用视频语境品牌，无法判断为 null",
      "target_model": "评论指向的车型，同上",
      "intent_strength": "none | low | medium | high",
      "reason": "判断理由，一句话",
      "confidence": 0.9
    }
  ]
}
```

`app/skills/configs/video_context_analysis.yaml` 改为：

```yaml
skill_id: video_context_analysis
version: "1.1"
description: >
  理解短视频语境：识别品牌车型、内容类型、主要话题、受众、竞品与商业属性，
  并估算车型价位/品类/动力/用途等客观属性，供我方车型匹配降级使用。
model:
  name: ""          # 空则使用 .env 的 LLM_MODEL
  temperature: 0.1
prompt_file: video_context_analysis_v2.txt
prompt_version: "v2"
```

`app/skills/configs/comment_lead_screening.yaml` 改为：

```yaml
skill_id: comment_lead_screening
version: "1.1"
description: >
  结合视频语境批量判断评论是否具有真实购车价值，
  识别无意义评论、营销内容、水军、已购/已下定车主与购车意向信号。
model:
  name: ""
  temperature: 0.1
prompt_file: comment_lead_screening_v2.txt
prompt_version: "v2"
```

`app/workflow/pipeline.py` 的 `SKILL_VERSIONS` 改为：

```python
SKILL_VERSIONS = {
    VIDEO_CONTEXT_SKILL: "1.1",
    COMMENT_SCREENING_SKILL: "1.1",
    USER_ANALYSIS_SKILL: "1.0",
}
```

（`user_lead_analysis` 在 Task 7 一并升级，此处保持 "1.0"。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_skill_executor.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量测试 + 提交**

Run: `python -m pytest tests -q`
（若有既有测试断言 `prompt_version == "v1"` 或 `SKILL_VERSIONS` 值，按新值更新断言——这是版本升级的预期变更，需在 commit message 中注明。）

```powershell
git add app/skills/prompts/video_context_analysis_v2.txt app/skills/prompts/comment_lead_screening_v2.txt app/skills/configs/video_context_analysis.yaml app/skills/configs/comment_lead_screening.yaml app/workflow/pipeline.py tests/
git commit -m @'
feat(v1.1): 视频语境/评论筛选 Skill 升级 v2 Prompt

新增车型属性估算与车主状态/评论主体识别。
注意：SKILL_VERSIONS bump 会使 V0 流水线按新版本重跑已有视频语境（预期行为）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 6: Agent 1 接入匹配判定与降级后处理

**Files:**
- Modify: `app/api/agent1.py`
- Test: `tests/test_agent1.py`（追加用例）

**Interfaces:**
- Consumes: `load_our_models`（Task 1）、`evaluate_video_context` / `apply_downgrade` / `DowngradeDecision`（Task 2）、`map_screening_item` 新签名（Task 4）、`settings.intent_downgrade_enabled`
- Produces: `run_comment_screening` 输出的每条 result dict 含 `filter_type` / `intent_strength` / `downgrade_applied` / `downgrade_reason`；失败条目这四个键分别为 `None / None / False / None`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent1.py` 末尾追加：

```python
_OUR_MODELS = {
    "version": "1.0", "updated_at": "2026-07-27",
    "models": [{
        "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
        "aliases": ["X7"], "price_min": 350000, "price_max": 420000,
        "vehicle_category": "越野", "powertrain": "PHEV",
        "use_case": ["越野", "家用"], "key_features": ["四驱"],
        "target_audience": "户外爱好者"}]}

# 视频语境：10万纯电微型车（与我方38万越野车双维度不匹配）
_CTX_MISMATCH = json.dumps({
    "brand": "微光", "model": "微光mini",
    "price_range_min": 90000, "price_range_max": 110000,
    "vehicle_category": "微型车", "use_case": ["家用", "通勤"]})

# 视频语境：我方车型
_CTX_OURS = json.dumps({"brand": "方舟", "model": "方舟X7",
                        "price_range_min": 350000,
                        "price_range_max": 420000,
                        "vehicle_category": "越野"})

_SCREEN_HIGH = json.dumps({"items": [
    {"comment_id": "cm_1", "is_meaningful": True,
     "is_purchase_related": True, "intent_strength": "high",
     "reason": "询问落地价"},
    {"comment_id": "cm_2", "is_meaningful": False, "reason": "刷屏"}]})


def _setup_config(tmp_path, monkeypatch, enabled=True):
    from app.config import settings
    p = tmp_path / "our_models.json"
    p.write_text(json.dumps(_OUR_MODELS, ensure_ascii=False),
                 encoding="utf-8")
    monkeypatch.setattr(settings, "our_models_config_path", str(p))
    monkeypatch.setattr(settings, "intent_downgrade_enabled", enabled)


@pytest.mark.asyncio
async def test_downgrade_applied_for_mismatched_video(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch)
    out = await run_comment_screening(
        _executor(_CTX_MISMATCH, _SCREEN_HIGH), _req())
    r = out["results"][0]
    assert r["intent_strength"] == "none"       # high 降两级
    assert r["downgrade_applied"] is True
    assert "价位" in r["downgrade_reason"]
    assert r["filter_type"] == "genuine_user"
    assert r["passed"] is True                  # 降级不影响 passed


@pytest.mark.asyncio
async def test_no_downgrade_for_our_model_video(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch)
    out = await run_comment_screening(
        _executor(_CTX_OURS, _SCREEN_HIGH), _req())
    r = out["results"][0]
    assert r["intent_strength"] == "high"
    assert r["downgrade_applied"] is False
    assert r["downgrade_reason"] is None


@pytest.mark.asyncio
async def test_no_downgrade_when_disabled(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch, enabled=False)
    out = await run_comment_screening(
        _executor(_CTX_MISMATCH, _SCREEN_HIGH), _req())
    assert out["results"][0]["intent_strength"] == "high"
    assert out["results"][0]["downgrade_applied"] is False


@pytest.mark.asyncio
async def test_no_downgrade_when_config_missing(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "our_models_config_path",
                        str(tmp_path / "nope.json"))
    monkeypatch.setattr(settings, "intent_downgrade_enabled", True)
    out = await run_comment_screening(
        _executor(_CTX_MISMATCH, _SCREEN_HIGH), _req())
    assert out["results"][0]["intent_strength"] == "high"


@pytest.mark.asyncio
async def test_owner_comment_filtered(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch)
    screening = json.dumps({"items": [
        {"comment_id": "cm_1", "is_meaningful": True,
         "owner_status": "ordered_owner", "intent_strength": "low",
         "reason": "大定已下等提车"},
        {"comment_id": "cm_2", "is_meaningful": False, "reason": "刷屏"}]})
    out = await run_comment_screening(
        _executor(_CTX_OURS, screening), _req())
    r = out["results"][0]
    assert r["passed"] is False
    assert r["filter_type"] == "ordered_owner"
    assert r["filter_reason"] == "已下定车主评论"


@pytest.mark.asyncio
async def test_failed_item_has_v11_keys(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch)
    # 只给语境响应，筛选批次 Mock 无响应 → 整批失败
    out = await run_comment_screening(_executor(_CTX_MISMATCH), _req())
    r = out["results"][0]
    assert r["error"]
    assert r["filter_type"] is None
    assert r["intent_strength"] is None
    assert r["downgrade_applied"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent1.py -v`
Expected: 新增用例 FAIL（输出缺新键 / 未降级）

- [ ] **Step 3: 实现**

`app/api/agent1.py` 顶部 import 增加：

```python
from app.matching.downgrade import (DowngradeDecision, apply_downgrade,
                                    evaluate_video_context)
from app.matching.loader import load_our_models
```

`run_comment_screening` 改为（完整替换函数体）：

```python
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

    # V1.1：我方车型配置整单加载一次；每个视频语境评估一次降级决策
    our_models = (load_our_models()
                  if settings.intent_downgrade_enabled else None)
    decisions: dict[str, DowngradeDecision] = {}

    size = settings.comment_batch_size
    items: dict[str, CommentScreeningItem] = {}
    errors: dict[str, str] = {}
    for title, comments in groups.items():
        if title not in ctx_cache:
            ctx_cache[title] = await _video_context(executor, comments[0])
            decisions[title] = evaluate_video_context(
                ctx_cache[title], our_models,
                enabled=settings.intent_downgrade_enabled)
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
                progress_cb(done)

    # 按输入顺序回填，保证一一对应
    ts = now_iso()
    for c in request.comments:
        item = items.get(c.comment_id)
        if item is not None:
            decision = decisions.get(c.video_title) or DowngradeDecision()
            applied = False
            if decision.downgrade_levels > 0:
                new_strength = apply_downgrade(item.intent_strength,
                                               decision.downgrade_levels)
                applied = new_strength != item.intent_strength
                item.intent_strength = new_strength
            results.append(map_screening_item(
                item, ts, downgrade_applied=applied,
                downgrade_reason=decision.reason if applied else None,
            ).model_dump())
        else:
            err = errors.get(c.comment_id, "筛选失败")
            results.append({"comment_id": c.comment_id, "passed": False,
                            "filter_reason": None, "filter_type": None,
                            "intent_strength": None,
                            "downgrade_applied": False,
                            "downgrade_reason": None, "analysis": "",
                            "processed_at": ts, "error": err})
    return {"results": results}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agent1.py -v`
Expected: 全部 PASS（含既有 `test_screening_maps_results`——注意该用例未配置 our_models 路径，默认路径 `config/our_models.json` 在仓库中不存在（被 .gitignore），`load_our_models` 返回 None 自动跳过降级）

- [ ] **Step 5: 全量测试 + 提交**

Run: `python -m pytest tests -q`

```powershell
git add app/api/agent1.py tests/test_agent1.py
git commit -m @'
feat(v1.1): Agent 1 接入我方车型匹配判定与意向降级后处理

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 7: Agent 2 与 V0 用户分析注入我方车型摘要

**Files:**
- Create: `app/skills/prompts/user_lead_analysis_v2.txt`
- Modify: `app/skills/configs/user_lead_analysis.yaml`
- Modify: `app/api/agent2.py`（`analyze_account` 的 ctx 增加变量）
- Modify: `app/workflow/pipeline.py`（`run_user_analysis` 的 context 增加变量 + `SKILL_VERSIONS` bump）
- Test: `tests/test_agent2.py`（追加用例）、`tests/test_user_analysis.py`（如断言 context 键需同步）

**Interfaces:**
- Consumes: `load_our_models` / `build_our_models_summary`（Task 1）
- Produces: `user_lead_analysis` v2 模板新增变量 `$our_models_summary`；两处调用点（`app/api/agent2.py:analyze_account`、`app/workflow/pipeline.py:run_user_analysis`）都必须传该变量，否则 `Template.substitute` 抛 KeyError

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent2.py` 末尾追加（若该文件的既有工具函数名不同，按现有命名对齐）：

```python
def test_v11_user_analysis_config_uses_v2():
    from app.skills.executor import load_skill_config
    config = load_skill_config("user_lead_analysis")
    assert config.prompt_file == "user_lead_analysis_v2.txt"
    assert config.prompt_version == "v2"
    assert config.version == "1.1"


def test_v11_user_analysis_prompt_has_our_models_var():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_analysis")
    text = render_prompt(config, {
        "user_evidence_json": "{}",
        "grading_standard": "标准",
        "our_models_summary": "- 方舟X7：售价 35-42 万元"})
    assert "方舟X7" in text
    assert "匹配度" in text  # v2 追加的评级考量要求


@pytest.mark.asyncio
async def test_v11_analyze_account_passes_summary(tmp_path, monkeypatch):
    """analyze_account 渲染 v2 模板不抛 KeyError，且 LLM 输入含我方车型摘要。"""
    import json as _json
    from app.api.agent2 import analyze_account
    from app.api.schemas import AccountObject
    from app.config import settings
    from app.llm.gateway import LLMGateway
    from app.llm.mock import MockProvider
    from app.skills.executor import SkillExecutor

    cfg = {"models": [{
        "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
        "aliases": [], "price_min": 350000, "price_max": 420000,
        "vehicle_category": "越野"}]}
    p = tmp_path / "our_models.json"
    p.write_text(_json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "our_models_config_path", str(p))

    provider = MockProvider()
    provider.queue(_json.dumps({
        "lead_grade": "A", "is_valid_lead": True,
        "evidence_comment_ids": ["u1:0"], "confidence": 0.8}))
    sent: list[list[dict]] = []
    orig = provider.chat

    async def spy(messages, **kw):
        sent.append(messages)
        return await orig(messages, **kw)
    provider.chat = spy

    account = AccountObject(
        account_uid="u1", account_name="用户",
        comment_history=[{"video_title": "对比", "comment_content": "纠结中",
                          "comment_time": "2026-07-19T14:23:00+08:00"}])
    out = await analyze_account(
        SkillExecutor(LLMGateway(provider)), account, "")
    assert out.lead_grade == "A"
    assert "方舟X7" in sent[0][0]["content"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent2.py -v`
Expected: 新增用例 FAIL

- [ ] **Step 3: 实现**

创建 `app/skills/prompts/user_lead_analysis_v2.txt`（在 v1 基础上加入我方车型段落与第 4 条要求，其余原样保留）：

```
你是汽车销售线索分析专家。以下是一位抖音用户的全部有效评论及其上下文，
请综合判断该用户的购车意向，形成销售线索。

用户证据包（JSON，包含用户信息、评论列表及各自视频语境、统计特征）：
$user_evidence_json

意向等级标准：
$grading_standard

我方在售主力车型信息：
$our_models_summary

请严格输出以下 JSON（不要输出任何其他内容）：
{
  "lead_grade": "H | A | B | C",
  "is_valid_lead": true,
  "lead_summary": "线索摘要，销售人员一眼能懂，一到两句话",
  "purchase_stage": "购车阶段，如：初步了解/主动对比/交易准备，无法判断为 null",
  "target_brands": ["关注品牌"],
  "target_models": ["关注车型"],
  "core_needs": ["核心需求，如家庭空间、越野"],
  "main_concerns": ["主要顾虑，如落地价格、售后"],
  "purchase_time": "购车时间，如：近期/半年内/未知，无法判断为 null",
  "usage_scenario": "使用场景，无法判断为 null",
  "recommended_entry_point": "推荐销售切入点，一句话",
  "verification_questions": ["销售需要向用户确认的问题"],
  "evidence_comment_ids": ["支撑结论的评论 comment_id，必须来自输入"],
  "profile_tags": ["账号画像标签，如：已购车主、智驾关注、高活跃度"],
  "profile_summary": "账号画像摘要，150-300 字，综合评论行为与主页信息",
  "analysis_text": "分析过程说明，300-500 字，分评论行为/购车阶段/主页画像/综合评分四段",
  "confidence": 0.9
}

要求：
1. 所有结论必须有评论证据支撑，evidence_comment_ids 不得为空；
2. 没有证据的字段输出 null 或空数组，严禁编造；
3. 疑似营销、水军或完全无购车相关信号的用户：is_valid_lead=false；
4. 结合"我方在售主力车型信息"考量匹配度：用户意向车型与我方车型的价位、
   品类差异显著、且无任何我方品牌相关信号时，适当下调等级（如 H→A、A→B）
   并在 analysis_text 中说明理由；用户意向直接指向我方品牌/车型时正常评定；
   我方车型信息为"未配置"时忽略本条。
```

`app/skills/configs/user_lead_analysis.yaml` 改为：

```yaml
skill_id: user_lead_analysis
version: "1.1"
description: >
  基于用户全部有效评论、视频语境与统计特征，综合判断购车意向，
  输出 H/A/B/C 等级、购车画像与销售建议；评级时考量与我方在售车型的匹配度。
model:
  name: ""
  temperature: 0.1
prompt_file: user_lead_analysis_v2.txt
prompt_version: "v2"
```

`app/api/agent2.py` 顶部 import 增加：

```python
from app.matching.loader import build_our_models_summary, load_our_models
```

`analyze_account` 的 ctx 改为：

```python
    ctx = {
        "user_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "grading_standard": GRADING_STANDARD,
        "our_models_summary": build_our_models_summary(load_our_models()),
    }
```

`app/workflow/pipeline.py`：
1. `SKILL_VERSIONS` 中 `USER_ANALYSIS_SKILL` 改为 `"1.1"`。
2. `run_user_analysis` 的 context 同样增加一行（import 放函数内已有 import 区或文件顶部均可，与现有风格一致放文件顶部）：

```python
from app.matching.loader import build_our_models_summary, load_our_models
```

```python
    context = {
        "user_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "grading_standard": GRADING_STANDARD,
        "our_models_summary": build_our_models_summary(load_our_models()),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agent2.py tests/test_user_analysis.py -v`
Expected: 全部 PASS（`test_user_analysis.py` 若因模板变量或版本号断言失败，按 v2 更新断言）

- [ ] **Step 5: 全量测试 + 提交**

Run: `python -m pytest tests -q`

```powershell
git add app/skills/prompts/user_lead_analysis_v2.txt app/skills/configs/user_lead_analysis.yaml app/api/agent2.py app/workflow/pipeline.py tests/
git commit -m @'
feat(v1.1): 用户分析 Skill 注入我方车型摘要，评级考量品牌匹配度

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 8: 车型描述转换脚本

**Files:**
- Create: `scripts/build_our_models.py`
- Test: `tests/test_build_our_models.py`

**Interfaces:**
- Consumes: `build_gateway` / `LLMGateway`（现有）、`extract_json`（现有）、`OurModelsConfig`（Task 1）
- Produces:
  - `scripts.build_our_models.extract_models(gateway: LLMGateway, text: str) -> OurModelsConfig`（async）
  - `scripts.build_our_models.write_config(config: OurModelsConfig, output: Path) -> None`（已存在则先备份 `.bak`）
  - CLI：`python scripts/build_our_models.py --input <txt> [--output config/our_models.json] [--dry-run]`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_build_our_models.py`：

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_our_models import extract_models, write_config  # noqa: E402

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.matching.models import OurModelsConfig

_LLM_OUT = json.dumps({"models": [{
    "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
    "aliases": ["X7"], "price_min": 350000, "price_max": 420000,
    "vehicle_category": "越野", "powertrain": "PHEV",
    "use_case": ["越野"], "key_features": ["四驱"],
    "target_audience": "户外爱好者"}]}, ensure_ascii=False)


def _gateway(*responses) -> LLMGateway:
    provider = MockProvider()
    provider.queue(*responses)
    return LLMGateway(provider)


@pytest.mark.asyncio
async def test_extract_models_valid():
    cfg = await extract_models(_gateway(_LLM_OUT), "方舟X7，35-42万越野车")
    assert isinstance(cfg, OurModelsConfig)
    assert cfg.models[0].model_name == "方舟X7"
    assert cfg.updated_at  # 自动补今天日期


@pytest.mark.asyncio
async def test_extract_models_invalid_output_raises():
    bad = json.dumps({"models": [{"model_id": "a"}]})  # 缺必填字段
    with pytest.raises(Exception):
        # MockProvider 三条相同响应耗尽执行器风格重试后仍失败
        await extract_models(_gateway(bad, bad, bad), "文本")


def test_write_config_creates_and_backs_up(tmp_path):
    cfg = OurModelsConfig.model_validate(json.loads(_LLM_OUT))
    out = tmp_path / "our_models.json"
    write_config(cfg, out)
    assert out.exists()
    write_config(cfg, out)  # 第二次写触发备份
    assert (tmp_path / "our_models.json.bak").exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["models"][0]["brand"] == "方舟"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_build_our_models.py -v`
Expected: FAIL（`ModuleNotFoundError: build_our_models`）

- [ ] **Step 3: 实现**

创建 `scripts/build_our_models.py`：

```python
"""把我方在售车型的文本描述转换为 config/our_models.json 结构化配置。

用法：
    python scripts/build_our_models.py --input docs/our_models.txt
    python scripts/build_our_models.py --input docs/our_models.txt --dry-run
"""
import argparse
import asyncio
import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.gateway import LLMGateway, build_gateway  # noqa: E402
from app.matching.models import OurModelsConfig  # noqa: E402
from app.skills.executor import extract_json  # noqa: E402

_MAX_ATTEMPTS = 3

PROMPT = """你是汽车产品信息结构化专家。请把以下我方在售车型的文本描述转换为结构化 JSON。
文本中可能描述一款或多款车型，每款车型输出一个对象。

车型描述：
{text}

请严格输出以下 JSON（不要输出任何其他内容）：
{{
  "models": [
    {{
      "model_id": "小写短横线标识（拼音或英文），如 fangzhou-x7",
      "brand": "品牌规范名称",
      "model_name": "车型规范名称",
      "aliases": ["常见简称、口语叫法、英文名，尽量丰富以提高评论匹配率"],
      "price_min": 售价区间下限（人民币元，整数）,
      "price_max": 售价区间上限（人民币元，整数）,
      "vehicle_category": "品类：轿车/SUV/MPV/越野/皮卡/微型车",
      "powertrain": "动力形式：燃油/纯电/插混(PHEV)/油混(HEV)/增程",
      "use_case": ["主要用途，如：家用/越野/通勤/商务"],
      "key_features": ["核心卖点，如：四驱/大空间/智驾"],
      "target_audience": "目标人群一句话"
    }}
  ]
}}
要求：只依据文本内容抽取，缺失的价格等关键信息不得编造。"""


async def extract_models(gateway: LLMGateway, text: str) -> OurModelsConfig:
    """LLM 抽取 + Pydantic 校验；解析/校验失败换新输出重试。"""
    last_error: Exception | None = None
    for _ in range(_MAX_ATTEMPTS):
        resp = await gateway.chat(
            [{"role": "user", "content": PROMPT.format(text=text)}],
            skill_id="build_our_models", skill_version="1.0",
            prompt_version="v1")
        try:
            data = extract_json(resp.text)
            data.setdefault("version", "1.0")
            data.setdefault("updated_at", date.today().isoformat())
            return OurModelsConfig.model_validate(data)
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"车型信息抽取失败: {last_error}")


def write_config(config: OurModelsConfig, output: Path) -> None:
    """写入配置；目标已存在时先备份 .bak。"""
    if output.exists():
        shutil.copy2(output, output.with_suffix(output.suffix + ".bak"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="把车型文本描述转换为 our_models.json 结构化配置")
    parser.add_argument("--input", required=True, help="车型文本描述文件路径")
    parser.add_argument("--output", default="config/our_models.json",
                        help="输出配置文件路径")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印结构不写盘")
    args = parser.parse_args()
    text = Path(args.input).read_text(encoding="utf-8")
    try:
        config = await extract_models(build_gateway(), text)
    except Exception as e:
        print(f"转换失败：{e}", file=sys.stderr)
        return 1
    print(json.dumps(config.model_dump(), ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0
    write_config(config, Path(args.output))
    print(f"已写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_build_our_models.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量测试 + 提交**

Run: `python -m pytest tests -q`

```powershell
git add scripts/build_our_models.py tests/test_build_our_models.py
git commit -m @'
feat(v1.1): 新增车型文本描述转结构化配置脚本

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 9: 端到端集成测试与对接文档更新

**Files:**
- Create: `tests/test_v11_integration.py`
- Modify: `docs/DriveIntent-V1-API对接文档.md`（新增 V1.1 字段说明）
- Test: `tests/test_v11_integration.py`

**Interfaces:**
- Consumes: 全部前序任务的成果，走 API 提交 → Worker 执行 → 轮询取结果的完整链路

- [ ] **Step 1: 写集成测试**

创建 `tests/test_v11_integration.py`（复用 `tests/test_v1_integration.py` 的 env fixture 模式）：

```python
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import api_router, get_db
from app.api.worker import ApiJobWorker
from app.db import Base
from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.skills.executor import SkillExecutor

_OUR_MODELS = {
    "version": "1.0", "updated_at": "2026-07-27",
    "models": [{
        "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
        "aliases": ["X7"], "price_min": 350000, "price_max": 420000,
        "vehicle_category": "越野", "powertrain": "PHEV",
        "use_case": ["越野", "家用"], "key_features": ["四驱"],
        "target_audience": "户外爱好者"}]}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "api_keys", "secret")
    p = tmp_path / "our_models.json"
    p.write_text(json.dumps(_OUR_MODELS, ensure_ascii=False),
                 encoding="utf-8")
    monkeypatch.setattr(settings, "our_models_config_path", str(p))
    monkeypatch.setattr(settings, "intent_downgrade_enabled", True)
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    import app.models  # noqa
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(api_router)
    app.dependency_overrides[get_db] = lambda: Session()
    return app, Session


def _payload():
    def c(cid, content):
        return {"comment_id": cid, "video_title": "微光mini测评",
                "video_author": "@测评君", "video_author_fans": 10000,
                "comment_content": content, "comment_author": "a",
                "comment_author_uid": f"u_{cid}",
                "comment_time": "2026-07-27T10:00:00+08:00",
                "comment_like_count": 1}
    return {"comments": [c("cm_1", "落地多少钱"), c("cm_2", "大定已下等提车"),
                         c("cm_3", "加V了解低息方案")]}


@pytest.mark.asyncio
async def test_v11_screening_end_to_end(env):
    app, Session = env
    client = TestClient(app)
    r = client.post("/api/v1/comment-screening", json=_payload(),
                    headers={"Authorization": "Bearer secret"})
    job_id = r.json()["job_id"]

    provider = MockProvider()
    provider.queue(
        json.dumps({"brand": "微光", "model": "微光mini",
                    "price_range_min": 90000, "price_range_max": 110000,
                    "vehicle_category": "微型车",
                    "use_case": ["家用", "通勤"]}),
        json.dumps({"items": [
            {"comment_id": "cm_1", "is_meaningful": True,
             "is_purchase_related": True, "comment_actor": "genuine_user",
             "owner_status": "none", "intent_strength": "high",
             "reason": "询问落地价"},
            {"comment_id": "cm_2", "is_meaningful": True,
             "comment_actor": "genuine_user",
             "owner_status": "ordered_owner", "intent_strength": "low",
             "reason": "已下定"},
            {"comment_id": "cm_3", "is_meaningful": True,
             "comment_actor": "marketing_account", "owner_status": "none",
             "intent_strength": "none", "reason": "引流广告"}]}))
    executor = SkillExecutor(LLMGateway(provider))
    worker = ApiJobWorker(lambda: Session(), executor, LLMGateway(provider))
    await worker.run_once()

    body = client.get(f"/api/v1/jobs/{job_id}",
                      headers={"Authorization": "Bearer secret"}).json()
    assert body["status"] == "success"
    r1, r2, r3 = body["result"]["results"]
    # cm_1：真实用户，10万微型车 vs 38万越野 → high 降两级到 none
    assert r1["passed"] is True
    assert r1["filter_type"] == "genuine_user"
    assert r1["intent_strength"] == "none"
    assert r1["downgrade_applied"] is True
    # cm_2：已下定车主 → 过滤
    assert r2["passed"] is False
    assert r2["filter_type"] == "ordered_owner"
    assert r2["filter_reason"] == "已下定车主评论"
    # cm_3：营销号 → 过滤
    assert r3["passed"] is False
    assert r3["filter_type"] == "marketing_account"
    assert r3["filter_reason"] == "广告/引流类评论"
```

- [ ] **Step 2: 运行集成测试确认通过**

Run: `python -m pytest tests/test_v11_integration.py -v`
Expected: 全部 PASS（前序任务已实现完整链路；若失败按 systematic-debugging 排查）

- [ ] **Step 3: 更新 API 对接文档**

在 `docs/DriveIntent-V1-API对接文档.md` 的 Agent 1 输出字段说明处，追加 V1.1 小节（先读原文档找到 `ScreeningResult`/输出字段章节再插入，保持原文档格式）：

```markdown
### V1.1 新增：初筛输出扩展字段

自 V1.1 起，`comment-screening` 每条结果新增以下字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `filter_type` | string | 评论内容类型，所有评论均返回。枚举见下表；处理失败的条目为 `null` |
| `intent_strength` | string | 意向强度（降级后终值）：`none` / `low` / `medium` / `high`；处理失败为 `null` |
| `downgrade_applied` | bool | 该评论的意向强度是否因"视频车型与我方在售车型不匹配"被降级 |
| `downgrade_reason` | string \| null | 降级原因说明，仅 `downgrade_applied=true` 时有值 |

`filter_type` 枚举与 `filter_reason` 对应关系：

| filter_type | 含义 | filter_reason | passed |
|---|---|---|---|
| `genuine_user` | 真实普通用户 | `null` | `true` |
| `existing_owner` | 已购车主 | `已购车主评论` | `false` |
| `ordered_owner` | 已下大定车主 | `已下定车主评论` | `false` |
| `bot_spam` | 批量刷屏水军 | `批量刷屏水军` | `false` |
| `marketing_account` | 营销号/广告引流 | `广告/引流类评论` | `false` |
| `noise` | 无实质内容 | `无实质内容` | `false` |
| `off_topic` | 与汽车无关 | `与汽车无关` | `false` |

说明：`filter_reason` 在 V1.0 四个枚举基础上新增 `已购车主评论` / `已下定车主评论` / `与汽车无关` 三个值。
```

- [ ] **Step 4: 全量测试**

Run: `python -m pytest tests -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```powershell
git add tests/test_v11_integration.py docs/DriveIntent-V1-API对接文档.md
git commit -m @'
test(v1.1): 端到端集成测试 + API 对接文档补充 V1.1 字段说明

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

## 收尾说明（实现完成后）

1. **真实模型联调**（需用户配合，不在本计划任务内）：
   - 用真实车型描述跑 `python scripts/build_our_models.py --input <文件> --dry-run`，人工核对结构后写盘；
   - 用真实评论子集跑 Agent 1，重点核查：车主识别误判率（意向被误判为已购）、降级合理性、视频语境价位估算准确度。
2. 生产部署时在 `.env` 确认 `OUR_MODELS_CONFIG_PATH` 与 `INTENT_DOWNGRADE_ENABLED`，并把 `config/our_models.json` 挂载/复制到容器内（该文件不入 git）。
3. 若下游前端尚未适配新枚举，可先设 `INTENT_DOWNGRADE_ENABLED=false` 灰度（filter_type 字段无开关，本身向后兼容——V1.0 消费方忽略未知字段即可）。
