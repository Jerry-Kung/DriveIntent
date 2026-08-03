# DriveIntent V1 实现计划

> 版本：V1.0 | 日期：2026-07-23

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DriveIntent 升级为可 docker compose 独立部署的后端微服务，对外提供两个异步 API（评论初筛 / 账号画像精筛），保留 V0 的 8000 测试链路。

**Architecture:** 同一 FastAPI 应用叠加「API 路径」：新增 `app/api/` 子包（路由 + 认证 + 作业存储 + ApiJobWorker + 两个 Agent 编排 + 边界映射），API 作业落新表 `api_job`，与 V0 的 `analysis_task`/lead 表互不干扰。两条路径共享 LLM Gateway、Skill 执行器、Prompt 模板与四个 Skill（视频语境/评论筛选/用户分析/新增识图）。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.0、Pydantic v2、MySQL(PyMySQL)、httpx、pytest + pytest-asyncio、Docker Compose。

## Global Constraints

- 使用简体中文编写注释与文档。
- 遵循 V0 分层：`api/routes → api/worker → api/agent → skills → llm`；API 路径不依赖 `services/leads`、`services/aggregation`。
- API 作业不写 V0 的 `lead` 表。
- 认证：除 `/health` 外，`/api/v1/*` 需 `Authorization: Bearer <key>`，key 命中 `.env` 的 `API_KEYS`（逗号分隔）。
- 所有自动化测试基于 MockProvider，不依赖真实 LLM。
- 时间戳统一用 ISO 8601（带时区偏移，东八区 `+08:00`）。
- 意向等级映射固定：H→高/`high`，A→中/`medium`，B→低/`low`，C→`has_value=false`。
- 输出结构严格对齐 `docs/DriveIntent服务对接文档.md` 的 `ScreeningResult` / `ProfileResult`。
- 提交信息用中文，遵循 `feat:` / `test:` / `docs:` 前缀。

## 文件结构

- `app/api/__init__.py` — 子包初始化
- `app/api/schemas.py` — 对接文档输入/输出 Pydantic 模型
- `app/api/mapping.py` — 内部 Skill 结果 → 文档结构映射
- `app/api/agent1.py` — comment-screening 编排
- `app/api/agent2.py` — profile-analysis 编排
- `app/api/jobs.py` — api_job CRUD + 状态机
- `app/api/worker.py` — ApiJobWorker
- `app/api/routes.py` — `/api/v1/*` + `/health` + 认证依赖
- `app/models/api_job.py` — api_job 表
- `app/skills/vision.py` — 多模态 messages 组装 + image_url 归一
- `app/skills/configs/image_recognition.yaml`、`app/skills/prompts/image_recognition_v1.txt` — 识图 Skill
- `Dockerfile`、`docker-compose.yml`、`.env.example` — 部署
- 修改：`app/config.py`、`app/skills/executor.py`、`app/schemas/skills.py`、`app/skills/prompts/user_lead_analysis_v1.txt`、`app/importer/*`、`app/main.py`、`app/models/__init__.py`

---

### Task 1: 配置项扩展（API_KEYS、Worker、图像超时）

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `settings.api_keys_list: list[str]`、`settings.api_worker_enabled: bool`、`settings.api_worker_concurrency: int`、`settings.image_fetch_timeout_seconds: int`

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 末尾追加：

```python
def test_api_keys_list_parsing(monkeypatch):
    from app.config import Settings
    s = Settings(api_keys="k1, k2 ,k3")
    assert s.api_keys_list == ["k1", "k2", "k3"]

def test_api_keys_list_empty():
    from app.config import Settings
    s = Settings(api_keys="")
    assert s.api_keys_list == []

def test_api_worker_defaults():
    from app.config import Settings
    s = Settings()
    assert s.api_worker_enabled is True
    assert s.api_worker_concurrency == 3
    assert s.image_fetch_timeout_seconds == 30
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL（`api_keys` 字段不存在 / AttributeError）

- [ ] **Step 3: 实现最小改动**

在 `app/config.py` 的 `Settings` 类中，`comment_batch_size` 之后新增字段与属性：

```python
    api_keys: str = ""
    api_worker_enabled: bool = True
    api_worker_concurrency: int = 3
    image_fetch_timeout_seconds: int = 30

    @property
    def api_keys_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): 新增 V1 API 认证与 Worker 配置项"
```

---

### Task 2: api_job 数据模型

**Files:**
- Create: `app/models/api_job.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_api_job_model.py`

**Interfaces:**
- Produces: `ApiJob` ORM（表 `api_job`），字段：`id:str(36)` PK、`job_type:str`、`status:str`、`request_payload:dict|None`、`result:dict|None`、`progress_total:int`、`progress_done:int`、`error:str|None`、`attempt_count:int`、`max_attempts:int`、`created_at/updated_at/finished_at:datetime|None`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api_job_model.py`：

```python
from app.models import ApiJob


def test_api_job_defaults(session):
    job = ApiJob(id="job-1", job_type="comment_screening",
                 request_payload={"comments": []})
    session.add(job)
    session.commit()
    row = session.get(ApiJob, "job-1")
    assert row.status == "pending"
    assert row.progress_total == 0
    assert row.progress_done == 0
    assert row.max_attempts == 3
    assert row.attempt_count == 0
    assert row.finished_at is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_job_model.py -v`
Expected: FAIL（`ImportError: cannot import name 'ApiJob'`）

- [ ] **Step 3: 实现模型**

创建 `app/models/api_job.py`：

```python
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ApiJob(Base):
    __tablename__ = "api_job"
    __table_args__ = (Index("ix_api_job_status", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    request_payload: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
```

在 `app/models/__init__.py` 增加导入与导出：

```python
from app.models.analysis import AnalysisResult, AnalysisTask, LlmCallLog
from app.models.api_job import ApiJob
from app.models.lead import Lead
from app.models.media import Comment, PlatformUser, Video

__all__ = ["AnalysisResult", "AnalysisTask", "LlmCallLog", "ApiJob", "Lead",
           "Comment", "PlatformUser", "Video"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_job_model.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/models/api_job.py app/models/__init__.py tests/test_api_job_model.py
git commit -m "feat(models): 新增 api_job 作业表"
```

---

### Task 3: 对接文档 Pydantic 契约模型

**Files:**
- Create: `app/api/__init__.py`（空文件）
- Create: `app/api/schemas.py`
- Test: `tests/test_api_schemas.py`

**Interfaces:**
- Produces:
  - 输入：`VideoMetrics`、`CommentObject`、`CommentScreeningRequest{comments: list[CommentObject]}`；`CommentHistoryItem`、`AccountObject`、`ProfileAnalysisRequest{accounts: list[AccountObject]}`
  - 输出：`ScreeningResult{comment_id, passed, filter_reason, analysis, processed_at, error}`、`ProfileResult{account_uid, has_value, intent_level, intent_level_code, value_score, profile_tags, profile_summary, analysis, processed_at, error}`
  - 字段严格对齐对接文档；`error` 为 V1 内部新增（partial 标注，默认 None）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api_schemas.py`：

```python
import pytest
from pydantic import ValidationError

from app.api.schemas import (CommentScreeningRequest, ProfileAnalysisRequest,
                             ScreeningResult, ProfileResult)


def test_comment_request_parses_full_object():
    req = CommentScreeningRequest(comments=[{
        "comment_id": "cm_1",
        "video_title": "试驾体验",
        "video_author": "@老王说车",
        "video_author_fans": 2865000,
        "video_metrics": {"like_count": 1, "comment_count": 2,
                          "share_count": 3, "collect_count": 4},
        "comment_content": "这车不错",
        "comment_author": "用户_7823",
        "comment_author_uid": "MS4w",
        "comment_time": "2026-07-19T14:23:00+08:00",
        "comment_like_count": 234,
    }])
    assert req.comments[0].video_metrics.like_count == 1


def test_comment_request_missing_required_field():
    with pytest.raises(ValidationError):
        CommentScreeningRequest(comments=[{"comment_id": "x"}])


def test_account_screenshot_optional_empty():
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u1",
        "account_name": "用户",
        "account_homepage_screenshot": "",
        "comment_history": [],
    }])
    assert req.accounts[0].account_homepage_screenshot == ""


def test_screening_result_serialization():
    r = ScreeningResult(comment_id="cm_1", passed=True, filter_reason=None,
                        analysis="ok", processed_at="2026-07-19T15:30:00+08:00")
    d = r.model_dump()
    assert d["passed"] is True and d["filter_reason"] is None


def test_profile_result_serialization():
    r = ProfileResult(account_uid="u1", has_value=True, intent_level="高",
                      intent_level_code="high", value_score=92,
                      profile_tags=["已购车主"], profile_summary="...",
                      analysis="...", processed_at="2026-07-19T16:00:00+08:00")
    assert r.model_dump()["intent_level_code"] == "high"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_schemas.py -v`
Expected: FAIL（`ModuleNotFoundError: app.api.schemas`）

- [ ] **Step 3: 实现 schemas**

创建空文件 `app/api/__init__.py`，再创建 `app/api/schemas.py`：

```python
from pydantic import BaseModel


class VideoMetrics(BaseModel):
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    collect_count: int = 0


class CommentObject(BaseModel):
    comment_id: str
    video_title: str
    video_author: str
    video_author_fans: int = 0
    video_metrics: VideoMetrics = VideoMetrics()
    comment_content: str
    comment_author: str
    comment_author_uid: str
    comment_time: str
    comment_like_count: int = 0


class CommentScreeningRequest(BaseModel):
    comments: list[CommentObject]


class CommentHistoryItem(BaseModel):
    video_title: str
    comment_content: str
    comment_time: str
    comment_like_count: int = 0


class AccountObject(BaseModel):
    account_uid: str
    account_name: str
    account_douyin_id: str | None = None
    account_homepage_screenshot: str = ""
    comment_history: list[CommentHistoryItem] = []


class ProfileAnalysisRequest(BaseModel):
    accounts: list[AccountObject]


class ScreeningResult(BaseModel):
    comment_id: str
    passed: bool
    filter_reason: str | None = None
    analysis: str = ""
    processed_at: str = ""
    error: str | None = None


class ProfileResult(BaseModel):
    account_uid: str
    has_value: bool
    intent_level: str | None = None
    intent_level_code: str | None = None
    value_score: int | None = None
    profile_tags: list[str] = []
    profile_summary: str = ""
    analysis: str = ""
    processed_at: str = ""
    error: str | None = None
```

注：`video_metrics` 与 `video_author_fans` 给默认值以兼容对接文档「视频热度指标缺失时用默认权重」的降级要求；对接文档标注为「必填」的核心标识字段（comment_id、video_title 等）保持无默认值，缺失即 400。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_schemas.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/__init__.py app/api/schemas.py tests/test_api_schemas.py
git commit -m "feat(api): 新增对接文档输入/输出契约模型"
```

---

### Task 4: 扩展用户分析 Skill 输出 Schema（新增画像字段）

**Files:**
- Modify: `app/schemas/skills.py`
- Modify: `app/skills/prompts/user_lead_analysis_v1.txt`
- Test: `tests/test_api_skill_schema.py`

**Interfaces:**
- Produces: `UserLeadResult` 新增字段 `profile_tags: list[str] = []`、`profile_summary: str = ""`、`analysis_text: str = ""`。这些是 Agent 2 输出 `profile_tags`/`profile_summary`/`analysis` 的来源，供 Task 5 映射消费。

说明：`profile_summary` 与 V0 已有的 `lead_summary` 不同——`lead_summary` 是给销售看的一两句话，`profile_summary` 是 150-300 字账号画像；`analysis_text` 是 300-500 字分析过程（区别于任何既有字段）。V0 流水线路径不使用新字段，默认值保证向后兼容。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api_skill_schema.py`：

```python
from app.schemas.skills import UserLeadResult


def test_user_lead_result_has_profile_fields():
    out = UserLeadResult(lead_grade="H", profile_tags=["已购车主"],
                         profile_summary="账号画像摘要", analysis_text="分析过程")
    assert out.profile_tags == ["已购车主"]
    assert out.profile_summary == "账号画像摘要"
    assert out.analysis_text == "分析过程"


def test_user_lead_result_profile_fields_default_empty():
    out = UserLeadResult(lead_grade="C")
    assert out.profile_tags == []
    assert out.profile_summary == ""
    assert out.analysis_text == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_skill_schema.py -v`
Expected: FAIL（`UserLeadResult` 无 `profile_tags` 等字段）

- [ ] **Step 3: 扩展 Schema 与 Prompt**

在 `app/schemas/skills.py` 的 `UserLeadResult` 中，`confidence` 字段前新增：

```python
    profile_tags: list[str] = []
    profile_summary: str = ""
    analysis_text: str = ""
```

在 `app/skills/prompts/user_lead_analysis_v1.txt` 的输出 JSON 中，`"evidence_comment_ids"` 行之后、`"confidence"` 行之前插入三行（保持 JSON 合法）：

```
  "profile_tags": ["账号画像标签，如：已购车主、智驾关注、高活跃度"],
  "profile_summary": "账号画像摘要，150-300 字，综合评论行为与主页信息",
  "analysis_text": "分析过程说明，300-500 字，分评论行为/购车阶段/主页画像/综合评分四段",
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_skill_schema.py tests/test_user_analysis.py -v`
Expected: PASS（新测试通过；V0 既有用户分析测试不回归）

- [ ] **Step 5: 提交**

```bash
git add app/schemas/skills.py app/skills/prompts/user_lead_analysis_v1.txt tests/test_api_skill_schema.py
git commit -m "feat(skills): 用户分析 Skill 输出新增画像标签/摘要/分析过程字段"
```

---

### Task 5: 边界映射（内部结构 → 文档结构）

**Files:**
- Create: `app/api/mapping.py`
- Test: `tests/test_api_mapping.py`

**Interfaces:**
- Consumes: 内部 `CommentScreeningItem`（`app/schemas/skills.py`）、`UserLeadResult`（Task 4 扩展后含 `profile_tags`/`profile_summary`/`analysis_text`）
- Produces:
  - `map_screening_item(item: CommentScreeningItem, processed_at: str) -> ScreeningResult`
  - `map_profile_result(out: UserLeadResult, *, screenshot_available: bool, has_comments: bool, processed_at: str) -> ProfileResult`
  - `now_iso() -> str`（东八区 ISO 8601）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api_mapping.py`：

```python
from app.api.mapping import map_screening_item, map_profile_result, now_iso
from app.schemas.skills import CommentScreeningItem, UserLeadResult


def test_now_iso_has_offset():
    assert "+08:00" in now_iso()


def test_map_screening_passed():
    item = CommentScreeningItem(comment_id="cm_1", is_meaningful=True,
                                is_suspected_marketing=False,
                                is_purchase_related=True, reason="真实车主反馈")
    r = map_screening_item(item, "2026-07-19T15:30:00+08:00")
    assert r.passed is True and r.filter_reason is None
    assert "真实车主反馈" in r.analysis


def test_map_screening_marketing_filtered():
    item = CommentScreeningItem(comment_id="cm_2", is_meaningful=True,
                                is_suspected_marketing=True, reason="含微信号引流")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_reason == "广告/引流类评论"


def test_map_screening_meaningless_filtered():
    item = CommentScreeningItem(comment_id="cm_3", is_meaningful=False,
                                reason="纯数字刷屏")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_reason == "无实质内容"


def test_map_profile_high_to_gao():
    out = UserLeadResult(lead_grade="H", is_valid_lead=True, confidence=0.9,
                         profile_tags=["已购车主"], profile_summary="s",
                         analysis_text="a")
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.has_value is True
    assert (r.intent_level, r.intent_level_code) == ("高", "high")
    assert 85 <= r.value_score <= 100


def test_map_profile_c_grade_no_value():
    out = UserLeadResult(lead_grade="C", is_valid_lead=True, confidence=0.5)
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.has_value is False
    assert r.intent_level is None and r.value_score is None


def test_map_profile_screenshot_missing_lowers_score():
    out = UserLeadResult(lead_grade="A", is_valid_lead=True, confidence=0.8)
    with_shot = map_profile_result(out, screenshot_available=True,
                                   has_comments=True, processed_at="t")
    without = map_profile_result(out, screenshot_available=False,
                                 has_comments=True, processed_at="t")
    assert without.value_score < with_shot.value_score


def test_map_profile_no_comments():
    out = UserLeadResult(lead_grade="C", is_valid_lead=False, confidence=0.0)
    r = map_profile_result(out, screenshot_available=False, has_comments=False,
                           processed_at="t")
    assert r.has_value is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_mapping.py -v`
Expected: FAIL（`ModuleNotFoundError: app.api.mapping`）

- [ ] **Step 3: 实现 mapping**

创建 `app/api/mapping.py`：

```python
from datetime import datetime, timedelta, timezone

from app.api.schemas import ProfileResult, ScreeningResult
from app.schemas.skills import CommentScreeningItem, UserLeadResult

_TZ = timezone(timedelta(hours=8))

# 内部四维判断 → 文档过滤原因枚举
_GRADE_MAP = {
    "H": ("高", "high", 92),
    "A": ("中", "medium", 77),
    "B": ("低", "low", 60),
}


def now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def _filter_reason(item: CommentScreeningItem) -> str:
    if item.is_suspected_marketing:
        return "广告/引流类评论"
    if not item.is_meaningful:
        return "无实质内容"
    return "无实质内容"


def map_screening_item(item: CommentScreeningItem,
                       processed_at: str) -> ScreeningResult:
    passed = item.is_meaningful and not item.is_suspected_marketing
    reason = None if passed else _filter_reason(item)
    analysis = item.reason or ("通过初筛。" if passed else "未通过初筛。")
    return ScreeningResult(comment_id=item.comment_id, passed=passed,
                           filter_reason=reason, analysis=analysis,
                           processed_at=processed_at)


def map_profile_result(out: UserLeadResult, *, screenshot_available: bool,
                       has_comments: bool, processed_at: str) -> ProfileResult:
    mapped = _GRADE_MAP.get(out.lead_grade)
    has_value = bool(has_comments and out.is_valid_lead and mapped is not None)
    if not has_value:
        return ProfileResult(
            account_uid="", has_value=False,
            profile_tags=list(out.profile_tags),
            profile_summary=out.profile_summary,
            analysis=out.analysis_text, processed_at=processed_at)
    level, code, base = mapped
    score = base
    if not screenshot_available:
        score = max(50, score - 13)  # 文档：截图缺失降 10-15 分
    return ProfileResult(
        account_uid="", has_value=True, intent_level=level,
        intent_level_code=code, value_score=score,
        profile_tags=list(out.profile_tags),
        profile_summary=out.profile_summary, analysis=out.analysis_text,
        processed_at=processed_at)
```

注：`account_uid` 由调用方（agent2）填入；映射函数不感知 uid。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_mapping.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/mapping.py tests/test_api_mapping.py
git commit -m "feat(api): 新增内部结构到对接文档结构的边界映射"
```

注：对接文档过滤原因枚举有「批量刷屏水军」「重复内容评论」，但内部筛选 Schema 无对应细分字段，故映射到最接近的「无实质内容」；如需精细区分，后续可在筛选 Skill 输出增加 `filter_category` 字段（本期不做，YAGNI）。

---

### Task 6: 多模态消息组装

**Files:**
- Create: `app/skills/vision.py`
- Test: `tests/test_vision.py`

**Interfaces:**
- Produces:
  - `build_image_message(text: str, screenshot: str) -> list[dict]`：返回单条 user message，content 为 `[{type:text,...}, {type:image_url, image_url:{url}}]`；`screenshot` 为 URL 直接用，为 Base64（无 `http` 前缀）时包成 `data:image/...;base64,` URL。
  - 若 `screenshot` 为空串 → 返回纯文本 message（无 image 块）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_vision.py`：

```python
from app.skills.vision import build_image_message


def test_url_screenshot():
    msgs = build_image_message("描述这张图", "https://cdn/x.png")
    content = msgs[0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"] == "https://cdn/x.png"


def test_base64_screenshot_wrapped():
    msgs = build_image_message("t", "iVBORw0KGgoAAAA")
    url = msgs[0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/") and "base64,iVBORw0KGgoAAAA" in url


def test_empty_screenshot_text_only():
    msgs = build_image_message("只有文字", "")
    assert msgs[0]["content"] == "只有文字"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_vision.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 vision**

创建 `app/skills/vision.py`：

```python
def _to_image_url(screenshot: str) -> str:
    s = screenshot.strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("data:"):
        return s
    return f"data:image/png;base64,{s}"


def build_image_message(text: str, screenshot: str) -> list[dict]:
    if not screenshot or not screenshot.strip():
        return [{"role": "user", "content": text}]
    return [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": _to_image_url(screenshot)}},
    ]}]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_vision.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/skills/vision.py tests/test_vision.py
git commit -m "feat(skills): 新增多模态图像消息组装"
```

---

### Task 7: 识图 Skill 配置与 MockProvider 图像分支

**Files:**
- Create: `app/skills/configs/image_recognition.yaml`
- Create: `app/skills/prompts/image_recognition_v1.txt`
- Modify: `app/llm/mock.py`
- Test: `tests/test_vision.py`（追加）

**Interfaces:**
- Consumes: `build_image_message`（Task 6）、`SkillExecutor`/`LLMGateway`（V0）
- Produces: skill_id `image_recognition`；MockProvider 检测到 message content 为 list（含图像）时可返回预置文字。

- [ ] **Step 1: 写失败测试**

在 `tests/test_vision.py` 追加：

```python
import pytest
from app.llm.mock import MockProvider


@pytest.mark.asyncio
async def test_mock_handles_image_content():
    p = MockProvider()
    p.queue("这是一张科技博主主页")
    from app.skills.vision import build_image_message
    msgs = build_image_message("描述", "https://cdn/x.png")
    resp = await p.chat(msgs, model="m", temperature=0.1)
    assert resp.text == "这是一张科技博主主页"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_vision.py::test_mock_handles_image_content -v`
Expected: 可能已 PASS（MockProvider 与 content 类型无关）。若 PASS 则本步骤仅确认兼容性，直接进入 Step 3 补齐配置文件。

- [ ] **Step 3: 创建 Skill 配置**

创建 `app/skills/configs/image_recognition.yaml`：

```yaml
skill_id: image_recognition
version: "1.0"
description: >
  识别抖音/TikTok 账号主页截图中的所有可见信息，
  输出结构化文字描述，供用户画像分析参考。
model:
  name: ""
  temperature: 0.1
prompt_file: image_recognition_v1.txt
prompt_version: "v1"
```

创建 `app/skills/prompts/image_recognition_v1.txt`：

```
你是图像信息识别专家。这是一张抖音（或 TikTok）用户的账号主页截图。
请客观、详尽地描述截图中所有可见信息，包括但不限于：
- 账号昵称、抖音号、简介/签名
- 头像特征、认证标识、IP 属地
- 粉丝数、关注数、获赞数
- 已发布视频的标题、封面主题、数量
- 任何与购车倾向、消费能力、兴趣爱好相关的线索

只描述你实际看到的内容，不要推测或编造。若某项信息不可见，不要提及。
以自然段文字输出，不要输出 JSON。
```

MockProvider 无需改动（其 `chat` 已与 content 类型无关）；确认 Step 1 测试通过即可。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_vision.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/skills/configs/image_recognition.yaml app/skills/prompts/image_recognition_v1.txt tests/test_vision.py
git commit -m "feat(skills): 新增账号主页截图识别 Skill"
```

---

### Task 8: api_job 存储与状态机

**Files:**
- Create: `app/api/jobs.py`
- Test: `tests/test_api_jobs.py`

**Interfaces:**
- Consumes: `ApiJob`（Task 2）
- Produces:
  - `create_job(session, job_type: str, payload: dict, total: int) -> ApiJob`（生成 uuid、status=pending）
  - `claim_next_job(session) -> ApiJob | None`（领取即置 running、attempt_count+1）
  - `finish_job(session, job, *, result: dict|None, status: str, error: str|None)`（写 result/status/finished_at）
  - `fail_or_retry(session, job, error: str)`（未达 max_attempts→pending，否则 failed）
  - `set_progress(session, job, done: int)`
  - `reset_running_jobs(session) -> int`（running→pending）
  - `get_job(session, job_id) -> ApiJob | None`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api_jobs.py`：

```python
from app.api.jobs import (create_job, claim_next_job, finish_job,
                          fail_or_retry, set_progress, reset_running_jobs,
                          get_job)


def test_create_and_get(session):
    job = create_job(session, "comment_screening", {"comments": []}, total=5)
    assert job.status == "pending" and job.progress_total == 5
    assert get_job(session, job.id).id == job.id


def test_claim_marks_running(session):
    job = create_job(session, "comment_screening", {}, total=1)
    claimed = claim_next_job(session)
    assert claimed.id == job.id
    assert claimed.status == "running" and claimed.attempt_count == 1
    assert claim_next_job(session) is None


def test_finish_success(session):
    job = create_job(session, "comment_screening", {}, total=1)
    claim_next_job(session)
    finish_job(session, job, result={"results": []}, status="success",
               error=None)
    assert job.status == "success" and job.finished_at is not None


def test_fail_or_retry_then_failed(session):
    job = create_job(session, "comment_screening", {}, total=1)
    job.max_attempts = 2
    session.commit()
    claim_next_job(session)      # attempt=1
    fail_or_retry(session, job, "boom")
    assert job.status == "pending"
    claim_next_job(session)      # attempt=2
    fail_or_retry(session, job, "boom")
    assert job.status == "failed" and job.error == "boom"


def test_set_progress(session):
    job = create_job(session, "comment_screening", {}, total=10)
    set_progress(session, job, 4)
    assert job.progress_done == 4


def test_reset_running(session):
    job = create_job(session, "comment_screening", {}, total=1)
    claim_next_job(session)
    assert reset_running_jobs(session) == 1
    assert get_job(session, job.id).status == "pending"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_jobs.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 jobs**

创建 `app/api/jobs.py`：

```python
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ApiJob


def create_job(session: Session, job_type: str, payload: dict,
               total: int) -> ApiJob:
    job = ApiJob(id=str(uuid.uuid4()), job_type=job_type,
                 request_payload=payload, progress_total=total,
                 status="pending")
    session.add(job)
    session.commit()
    return job


def get_job(session: Session, job_id: str) -> ApiJob | None:
    return session.get(ApiJob, job_id)


def claim_next_job(session: Session) -> ApiJob | None:
    job = (session.query(ApiJob).filter_by(status="pending")
           .order_by(ApiJob.attempt_count.asc(), ApiJob.created_at.asc())
           .first())
    if job is None:
        return None
    job.status = "running"
    job.attempt_count += 1
    session.commit()
    return job


def set_progress(session: Session, job: ApiJob, done: int) -> None:
    job.progress_done = done
    session.commit()


def finish_job(session: Session, job: ApiJob, *, result: dict | None,
               status: str, error: str | None) -> None:
    job.result = result
    job.status = status
    job.error = error
    job.finished_at = datetime.utcnow()
    session.commit()


def fail_or_retry(session: Session, job: ApiJob, error: str) -> None:
    if job.attempt_count < job.max_attempts:
        job.status = "pending"
        job.error = error
    else:
        job.status = "failed"
        job.error = error
        job.finished_at = datetime.utcnow()
    session.commit()


def reset_running_jobs(session: Session) -> int:
    n = (session.query(ApiJob).filter_by(status="running")
         .update({"status": "pending"}))
    session.commit()
    return n
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_jobs.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/jobs.py tests/test_api_jobs.py
git commit -m "feat(api): 新增 api_job 存储与状态机"
```

---

### Task 9: Agent 1 编排（comment-screening）

**Files:**
- Create: `app/api/agent1.py`
- Test: `tests/test_agent1.py`

**Interfaces:**
- Consumes: `CommentScreeningRequest`（Task 3）、`SkillExecutor`（V0）、`VideoContextResult`/`CommentScreeningResult`/`CommentScreeningItem`（V0）、`map_screening_item`/`now_iso`（Task 5）
- Produces: `async run_comment_screening(executor, request: CommentScreeningRequest, *, progress_cb=None) -> dict`，返回 `{"results": [ScreeningResult.model_dump(), ...]}`，条目顺序与输入 comments 一致。逐条失败记 `error` 字段（partial 由 worker 判定）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_agent1.py`：

```python
import json
import pytest

from app.api.agent1 import run_comment_screening
from app.api.schemas import CommentScreeningRequest
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor


def _req():
    return CommentScreeningRequest(comments=[
        {"comment_id": "cm_1", "video_title": "试驾体验", "video_author": "@王",
         "video_author_fans": 100, "comment_content": "刚提这款车",
         "comment_author": "a", "comment_author_uid": "u1",
         "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 10},
        {"comment_id": "cm_2", "video_title": "试驾体验", "video_author": "@王",
         "video_author_fans": 100, "comment_content": "666",
         "comment_author": "b", "comment_author_uid": "u2",
         "comment_time": "2026-07-19T09:10:00+08:00", "comment_like_count": 0},
    ])


def _executor(*responses):
    provider = MockProvider()
    provider.queue(*responses)
    return SkillExecutor(LLMGateway(provider))


@pytest.mark.asyncio
async def test_screening_maps_results():
    ctx = json.dumps({"brand": "测试", "content_type": "试驾"})
    screening = json.dumps({"items": [
        {"comment_id": "cm_1", "is_meaningful": True,
         "is_suspected_marketing": False, "is_purchase_related": True,
         "reason": "真实车主"},
        {"comment_id": "cm_2", "is_meaningful": False,
         "reason": "数字刷屏"}]})
    out = await run_comment_screening(_executor(ctx, screening), _req())
    results = out["results"]
    assert [r["comment_id"] for r in results] == ["cm_1", "cm_2"]
    assert results[0]["passed"] is True
    assert results[1]["passed"] is False
    assert results[1]["filter_reason"] == "无实质内容"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent1.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 agent1**

创建 `app/api/agent1.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agent1.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/agent1.py tests/test_agent1.py
git commit -m "feat(api): 新增 Agent 1 评论初筛编排"
```

---

### Task 10: Agent 2 编排（profile-analysis）

**Files:**
- Create: `app/api/agent2.py`
- Test: `tests/test_agent2.py`

**Interfaces:**
- Consumes: `ProfileAnalysisRequest`/`AccountObject`（Task 3）、`SkillExecutor`（V0）、`build_image_message`（Task 6）、`UserLeadResult`（Task 4）、`map_profile_result`/`now_iso`（Task 5）、`GRADING_STANDARD`（V0 `pipeline.py`）
- Produces:
  - `async recognize_screenshot(gateway, screenshot: str) -> str`（空/失败返回 ""）
  - `async analyze_account(executor, account, vision_text) -> UserLeadResult`
  - `async run_profile_analysis(executor, gateway, request, *, progress_cb=None) -> dict`，返回 `{"results": [ProfileResult.model_dump(), ...]}`，顺序与输入 accounts 一致，`account_uid` 回填。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_agent2.py`：

```python
import json
import pytest

from app.api.agent2 import run_profile_analysis
from app.api.schemas import ProfileAnalysisRequest
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor


def _executor_and_gateway(*responses):
    provider = MockProvider()
    provider.queue(*responses)
    gateway = LLMGateway(provider)
    return SkillExecutor(gateway), gateway


@pytest.mark.asyncio
async def test_profile_with_screenshot():
    lead = json.dumps({
        "lead_grade": "H", "is_valid_lead": True, "lead_summary": "已购车主",
        "evidence_comment_ids": ["x"], "confidence": 0.9,
        "profile_tags": ["已购车主"], "profile_summary": "画像",
        "analysis_text": "分析"})
    executor, gateway = _executor_and_gateway("这是科技博主主页", lead)
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u1", "account_name": "用户",
        "account_homepage_screenshot": "https://cdn/x.png",
        "comment_history": [{"video_title": "试驾", "comment_content": "刚提车",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 10}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["account_uid"] == "u1"
    assert r["has_value"] is True
    assert r["intent_level_code"] == "high"
    assert 85 <= r["value_score"] <= 100


@pytest.mark.asyncio
async def test_profile_empty_history_no_value():
    executor, gateway = _executor_and_gateway()  # 无需 LLM
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u2", "account_name": "空用户",
        "account_homepage_screenshot": "", "comment_history": []}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["account_uid"] == "u2" and r["has_value"] is False


@pytest.mark.asyncio
async def test_profile_no_screenshot_lowers_score():
    lead = json.dumps({
        "lead_grade": "A", "is_valid_lead": True, "lead_summary": "对比中",
        "evidence_comment_ids": ["x"], "confidence": 0.8,
        "profile_tags": [], "profile_summary": "p", "analysis_text": "a"})
    executor, gateway = _executor_and_gateway(lead)  # 无截图→只有一次分析调用
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u3", "account_name": "用户",
        "account_homepage_screenshot": "",
        "comment_history": [{"video_title": "对比", "comment_content": "在看这两款",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 5}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["intent_level_code"] == "medium"
    assert r["value_score"] < 77  # 基准 77 因截图缺失降分
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent2.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 agent2**

创建 `app/api/agent2.py`：

```python
import json
import logging

from app.api.mapping import map_profile_result, now_iso
from app.api.schemas import AccountObject, ProfileAnalysisRequest
from app.llm.base import LLMError
from app.llm.gateway import LLMGateway
from app.schemas.skills import UserLeadResult
from app.skills.executor import (SkillExecutionError, load_skill_config,
                                 render_prompt)
from app.skills.vision import build_image_message
from app.workflow.pipeline import GRADING_STANDARD, USER_ANALYSIS_SKILL

logger = logging.getLogger(__name__)

IMAGE_SKILL = "image_recognition"


async def recognize_screenshot(gateway: LLMGateway, screenshot: str) -> str:
    if not screenshot or not screenshot.strip():
        return ""
    config = load_skill_config(IMAGE_SKILL)
    prompt = render_prompt(config, {})
    messages = build_image_message(prompt, screenshot)
    try:
        resp = await gateway.chat(messages, skill_id=IMAGE_SKILL,
                                  skill_version=config.version,
                                  prompt_version=config.prompt_version,
                                  model=config.model_name or None,
                                  temperature=config.temperature)
        return resp.text.strip()
    except LLMError as e:
        logger.warning("主页截图识别失败，降级为无截图: %s", e)
        return ""


def _build_evidence(account: AccountObject, vision_text: str) -> dict:
    comments = [{
        "comment_id": f"{account.account_uid}:{idx}",
        "content": h.comment_content,
        "comment_time": h.comment_time,
        "video_title": h.video_title,
        "comment_like_count": h.comment_like_count,
    } for idx, h in enumerate(account.comment_history)]
    return {
        "user": {"nickname": account.account_name,
                 "douyin_id": account.account_douyin_id,
                 "homepage_description": vision_text or "（无主页截图）"},
        "comments": comments,
        "statistics": {"valid_comment_count": len(comments)},
    }


async def analyze_account(executor, account: AccountObject,
                          vision_text: str) -> UserLeadResult:
    evidence = _build_evidence(account, vision_text)
    ctx = {
        "user_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "grading_standard": GRADING_STANDARD,
    }
    return await executor.run(USER_ANALYSIS_SKILL, ctx, UserLeadResult)


async def run_profile_analysis(executor, gateway: LLMGateway,
                               request: ProfileAnalysisRequest,
                               *, progress_cb=None) -> dict:
    results: list[dict] = []
    ts = now_iso()
    done = 0
    for account in request.accounts:
        has_comments = len(account.comment_history) > 0
        try:
            if not has_comments:
                out = UserLeadResult(lead_grade="C", is_valid_lead=False)
                shot_available = False
            else:
                vision_text = await recognize_screenshot(
                    gateway, account.account_homepage_screenshot)
                shot_available = bool(vision_text)
                out = await analyze_account(executor, account, vision_text)
            mapped = map_profile_result(
                out, screenshot_available=shot_available,
                has_comments=has_comments, processed_at=ts)
            d = mapped.model_dump()
            d["account_uid"] = account.account_uid
            results.append(d)
        except (SkillExecutionError, Exception) as e:
            results.append({
                "account_uid": account.account_uid, "has_value": False,
                "intent_level": None, "intent_level_code": None,
                "value_score": None, "profile_tags": [], "profile_summary": "",
                "analysis": "", "processed_at": ts, "error": str(e)[:500]})
        done += 1
        if progress_cb:
            progress_cb(done)
    return {"results": results}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agent2.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/agent2.py tests/test_agent2.py
git commit -m "feat(api): 新增 Agent 2 账号画像精筛编排（含主页截图识别）"
```

---

### Task 11: ApiJobWorker

**Files:**
- Create: `app/api/worker.py`
- Test: `tests/test_api_worker.py`

**Interfaces:**
- Consumes: `claim_next_job`/`finish_job`/`fail_or_retry`/`set_progress`（Task 8）、`run_comment_screening`（Task 9）、`run_profile_analysis`（Task 10）、`SkillExecutor`/`LLMGateway`（V0）
- Produces: `ApiJobWorker(session_factory, executor, gateway, poll_interval=None)`，方法 `async run_once() -> bool`、`async run_forever(stop_event)`。`run_once` 领取一个作业、执行、写回结果；含 `error` 字段的条目使整单 status=`partial`（全部失败或抛异常则按 `fail_or_retry`）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api_worker.py`：

```python
import json
import pytest

from app.api.jobs import create_job, get_job
from app.api.worker import ApiJobWorker
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor


class _Factory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


@pytest.mark.asyncio
async def test_worker_runs_comment_job(session):
    ctx = json.dumps({"brand": "测试"})
    screening = json.dumps({"items": [
        {"comment_id": "cm_1", "is_meaningful": True,
         "is_suspected_marketing": False, "is_purchase_related": True,
         "reason": "真实"}]})
    provider = MockProvider()
    provider.queue(ctx, screening)
    executor = SkillExecutor(LLMGateway(provider))
    gateway = LLMGateway(provider)

    payload = {"comments": [
        {"comment_id": "cm_1", "video_title": "试驾", "video_author": "@王",
         "video_author_fans": 1, "comment_content": "刚提车",
         "comment_author": "a", "comment_author_uid": "u1",
         "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 1}]}
    job = create_job(session, "comment_screening", payload, total=1)

    worker = ApiJobWorker(_Factory(session), executor, gateway)
    worked = await worker.run_once()
    assert worked is True
    row = get_job(session, job.id)
    assert row.status == "success"
    assert row.result["results"][0]["passed"] is True


@pytest.mark.asyncio
async def test_worker_no_job(session):
    provider = MockProvider()
    worker = ApiJobWorker(_Factory(session), SkillExecutor(LLMGateway(provider)),
                          LLMGateway(provider))
    assert await worker.run_once() is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_worker.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 worker**

创建 `app/api/worker.py`：

```python
import asyncio
import logging

from app.api.agent1 import run_comment_screening
from app.api.agent2 import run_profile_analysis
from app.api.jobs import claim_next_job, fail_or_retry, finish_job, set_progress
from app.api.schemas import CommentScreeningRequest, ProfileAnalysisRequest
from app.config import settings

logger = logging.getLogger(__name__)


class ApiJobWorker:
    def __init__(self, session_factory, executor, gateway,
                 poll_interval: float | None = None):
        self.session_factory = session_factory
        self.executor = executor
        self.gateway = gateway
        self.poll_interval = poll_interval or settings.worker_poll_interval

    async def _execute(self, session, job) -> dict:
        def cb(done):
            set_progress(session, job, done)

        if job.job_type == "comment_screening":
            req = CommentScreeningRequest.model_validate(job.request_payload)
            return await run_comment_screening(self.executor, req,
                                               progress_cb=cb)
        if job.job_type == "profile_analysis":
            req = ProfileAnalysisRequest.model_validate(job.request_payload)
            return await run_profile_analysis(self.executor, self.gateway, req,
                                              progress_cb=cb)
        raise ValueError(f"未知作业类型: {job.job_type}")

    @staticmethod
    def _status_for(result: dict) -> str:
        items = result.get("results", [])
        errored = sum(1 for r in items if r.get("error"))
        if errored == 0:
            return "success"
        if errored < len(items):
            return "partial"
        return "failed"

    async def run_once(self) -> bool:
        session = self.session_factory()
        try:
            job = claim_next_job(session)
            if job is None:
                return False
            logger.info("开始 API 作业 %s type=%s (第 %d 次)", job.id,
                        job.job_type, job.attempt_count)
            try:
                result = await self._execute(session, job)
            except Exception as e:
                session.rollback()
                logger.exception("API 作业 %s 执行失败", job.id)
                fail_or_retry(session, job, str(e)[:2000])
                await asyncio.sleep(self.poll_interval)
                return True
            status = self._status_for(result)
            if status == "failed":
                fail_or_retry(session, job, "全部条目处理失败")
            else:
                finish_job(session, job, result=result, status=status,
                           error=None)
            return True
        finally:
            session.close()

    async def _loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                worked = await self.run_once()
            except Exception:
                logger.exception("API worker 循环异常")
                await asyncio.sleep(self.poll_interval)
                continue
            if not worked:
                await asyncio.sleep(self.poll_interval)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        loops = [self._loop(stop_event)
                 for _ in range(settings.api_worker_concurrency)]
        await asyncio.gather(*loops)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_worker.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/worker.py tests/test_api_worker.py
git commit -m "feat(api): 新增 ApiJobWorker 作业执行器"
```

---

### Task 12: API 路由与认证

**Files:**
- Create: `app/api/routes.py`
- Test: `tests/test_api_routes.py`

**Interfaces:**
- Consumes: `create_job`/`get_job`（Task 8）、`CommentScreeningRequest`/`ProfileAnalysisRequest`（Task 3）、`settings.api_keys_list`（Task 1）
- Produces: `api_router: APIRouter`，端点：`GET /health`、`POST /api/v1/comment-screening`、`POST /api/v1/profile-analysis`、`GET /api/v1/jobs/{job_id}`；`require_api_key` 依赖。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api_routes.py`：

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.api.routes import api_router, get_db


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("API_KEYS", "secret")
    from app.config import settings
    monkeypatch.setattr(settings, "api_keys", "secret")
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    import app.models  # noqa
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(api_router)
    app.dependency_overrides[get_db] = lambda: Session()
    return TestClient(app)


def test_health_no_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_auth_401(client):
    r = client.post("/api/v1/comment-screening", json={"comments": []})
    assert r.status_code == 401


def test_submit_returns_job_id(client):
    r = client.post("/api/v1/comment-screening", json={"comments": []},
                    headers={"Authorization": "Bearer secret"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending" and "job_id" in body


def test_get_unknown_job_404(client):
    r = client.get("/api/v1/jobs/nope",
                   headers={"Authorization": "Bearer secret"})
    assert r.status_code == 404


def test_bad_payload_422(client):
    r = client.post("/api/v1/comment-screening",
                    json={"comments": [{"comment_id": "x"}]},
                    headers={"Authorization": "Bearer secret"})
    assert r.status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api_routes.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 routes**

创建 `app/api/routes.py`：

```python
from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.jobs import create_job, get_job
from app.api.schemas import CommentScreeningRequest, ProfileAnalysisRequest
from app.config import settings
from app.db import SessionLocal

api_router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(authorization: str = Header(default="")) -> None:
    keys = settings.api_keys_list
    if not keys:
        return  # 未配置 key 时不启用认证（本地/测试）
    token = authorization.removeprefix("Bearer ").strip()
    if token not in keys:
        raise HTTPException(status_code=401, detail="无效或缺失的 API Key")


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.post("/api/v1/comment-screening", status_code=202,
                 dependencies=[Depends(require_api_key)])
def submit_comment_screening(request: CommentScreeningRequest,
                             db=Depends(get_db)):
    job = create_job(db, "comment_screening", request.model_dump(),
                     total=len(request.comments))
    return {"job_id": job.id, "status": job.status,
            "type": job.job_type}


@api_router.post("/api/v1/profile-analysis", status_code=202,
                 dependencies=[Depends(require_api_key)])
def submit_profile_analysis(request: ProfileAnalysisRequest,
                            db=Depends(get_db)):
    job = create_job(db, "profile_analysis", request.model_dump(),
                     total=len(request.accounts))
    return {"job_id": job.id, "status": job.status,
            "type": job.job_type}


@api_router.get("/api/v1/jobs/{job_id}",
                dependencies=[Depends(require_api_key)])
def get_job_status(job_id: str, db=Depends(get_db)):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="作业不存在")
    return {
        "job_id": job.id, "type": job.job_type, "status": job.status,
        "progress": {"total": job.progress_total, "done": job.progress_done},
        "result": job.result, "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": (job.finished_at.isoformat()
                        if job.finished_at else None),
    }
```

注：FastAPI 请求体校验失败返回 422（Pydantic 默认），对接文档写 400；对外文档描述与 FastAPI 默认的差异在联调阶段如需严格 400 可加异常处理器，本期保留 422（语义等价，YAGNI）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api_routes.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/routes.py tests/test_api_routes.py
git commit -m "feat(api): 新增 V1 API 路由与 Bearer 认证"
```

---

### Task 13: 接入 main.py（挂路由 + 启动 ApiJobWorker）

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_main_wiring.py`

**Interfaces:**
- Consumes: `api_router`（Task 12）、`ApiJobWorker`（Task 11）、`reset_running_jobs`（Task 8）
- Produces: 应用挂载 `api_router`；lifespan 中启动 ApiJobWorker（受 `settings.api_worker_enabled` 控制），启动时 `reset_running_jobs`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_main_wiring.py`：

```python
def test_app_has_api_routes():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/health" in paths
    assert "/api/v1/comment-screening" in paths
    assert "/api/v1/jobs/{job_id}" in paths
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_main_wiring.py -v`
Expected: FAIL（路径不存在）

- [ ] **Step 3: 修改 main.py**

在 `app/main.py` 顶部 import 区新增：

```python
from app.api.jobs import reset_running_jobs
from app.api.routes import api_router
from app.api.worker import ApiJobWorker
```

在 lifespan 中，`with SessionLocal() as s: reset_running(s)` 之后新增 API 作业重置：

```python
    with SessionLocal() as s:
        reset_running(s)
        reset_running_jobs(s)
```

在 V0 Worker 启动块之后、`yield` 之前，新增 ApiJobWorker 启动（复用同一 gateway/executor）：

```python
    api_worker_task = None
    if settings.api_worker_enabled:
        api_gateway = build_gateway(session_factory=SessionLocal)
        api_worker = ApiJobWorker(
            SessionLocal, SkillExecutor(api_gateway), api_gateway)
        api_worker_task = asyncio.create_task(
            api_worker.run_forever(stop_event))
        logger.info("API Worker 已启动: 并发=%d",
                    settings.api_worker_concurrency)
```

在 `yield` 之后的清理块中，追加 api_worker_task 取消（与 worker_task 相同处理）：

```python
    for t in (worker_task, api_worker_task):
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
```

（替换原有仅取消 worker_task 的代码块。）

最后挂载路由，在 `app.include_router(router)` 之后新增：

```python
app.include_router(api_router)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_main_wiring.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/main.py tests/test_main_wiring.py
git commit -m "feat: 接入 V1 API 路由与 ApiJobWorker"
```

---

### Task 14: 8000 测试链路支持新版 JSON 导入

**Files:**
- Create: `app/importer/json_source.py`
- Modify: `app/web/routes.py`（`/api/import` 支持 .json）
- Test: `tests/test_json_import.py`

**Interfaces:**
- Consumes: `ImportBundle`/`VideoIn`/`UserIn`/`CommentIn`（V0 `schemas/import_data.py`）、`import_bundle`（V0）
- Produces: `parse_json_source(raw: dict | list) -> ImportBundle`。接受两种结构：(a) 对接文档评论数组 `{comments:[CommentObject]}`；(b) V0 标准 `{videos,users,comments}`。缺失字段置空/默认。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_json_import.py`：

```python
from app.importer.json_source import parse_json_source


def test_parse_docformat_comments():
    raw = {"comments": [{
        "comment_id": "cm_1", "video_title": "试驾", "video_author": "@王",
        "video_author_fans": 100,
        "video_metrics": {"like_count": 1, "comment_count": 2,
                          "share_count": 3, "collect_count": 4},
        "comment_content": "刚提车", "comment_author": "用户_1",
        "comment_author_uid": "u1",
        "comment_time": "2026-07-19T14:23:00+08:00",
        "comment_like_count": 10}]}
    bundle = parse_json_source(raw)
    assert len(bundle.comments) == 1
    assert len(bundle.videos) == 1
    assert len(bundle.users) == 1
    assert bundle.comments[0].external_id == "cm_1"
    assert bundle.videos[0].title == "试驾"


def test_parse_docformat_skips_empty_content():
    raw = {"comments": [{
        "comment_id": "cm_2", "video_title": "t", "video_author": "@w",
        "comment_content": "  ", "comment_author": "u",
        "comment_author_uid": "u2",
        "comment_time": "2026-07-19T14:23:00+08:00"}]}
    bundle = parse_json_source(raw)
    assert bundle.comments == []
    assert bundle.skipped_empty_comments == 1


def test_parse_v0_standard_format():
    raw = {"videos": [{"external_id": "v1", "title": "标题"}],
           "users": [{"external_id": "u1", "nickname": "昵称"}],
           "comments": [{"external_id": "c1", "video_external_id": "v1",
                         "user_external_id": "u1", "content": "内容"}]}
    bundle = parse_json_source(raw)
    assert len(bundle.comments) == 1 and bundle.videos[0].external_id == "v1"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_json_import.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 json_source**

创建 `app/importer/json_source.py`：

```python
from datetime import datetime

from app.schemas.import_data import CommentIn, ImportBundle, UserIn, VideoIn


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def _from_doc_comments(comments: list[dict]) -> ImportBundle:
    videos: dict[str, VideoIn] = {}
    users: dict[str, UserIn] = {}
    items: list[CommentIn] = []
    skipped = 0
    for c in comments:
        title = c.get("video_title") or ""
        # 对接文档无独立视频 ID，以标题+作者作为去重键
        video_key = f"{c.get('video_author', '')}|{title}"
        if video_key not in videos:
            videos[video_key] = VideoIn(
                external_id=video_key, title=title, description="",
                raw={"video_metrics": c.get("video_metrics"),
                     "video_author": c.get("video_author"),
                     "video_author_fans": c.get("video_author_fans")})
        uid = c.get("comment_author_uid") or ""
        if uid and uid not in users:
            users[uid] = UserIn(external_id=uid,
                                nickname=c.get("comment_author") or "",
                                raw={"douyin_id": c.get("account_douyin_id")})
        content = c.get("comment_content")
        if content is None or not str(content).strip():
            skipped += 1
            continue
        items.append(CommentIn(
            external_id=c["comment_id"], video_external_id=video_key,
            user_external_id=uid, content=str(content),
            comment_time=_parse_time(c.get("comment_time")),
            raw={"comment_like_count": c.get("comment_like_count")}))
    return ImportBundle(videos=list(videos.values()),
                        users=list(users.values()), comments=items,
                        skipped_empty_comments=skipped)


def parse_json_source(raw: dict | list) -> ImportBundle:
    if isinstance(raw, dict) and "comments" in raw and "videos" not in raw:
        return _from_doc_comments(raw["comments"])
    # V0 标准三数组格式
    data = raw if isinstance(raw, dict) else {}
    return ImportBundle(
        videos=[VideoIn.model_validate(v) for v in data.get("videos", [])],
        users=[UserIn.model_validate(u) for u in data.get("users", [])],
        comments=[CommentIn.model_validate(c) for c in data.get("comments", [])],
        skipped_empty_comments=0)
```

在 `app/web/routes.py` 的 `api_import` 中，支持 `.json` 后缀：文件名以 `.json` 结尾时读取 JSON 走 `parse_json_source`，否则走现有 `parse_excel`。修改 import 区加入 `import json` 与 `from app.importer.json_source import parse_json_source`，并把解析段改为：

```python
    try:
        raw_bytes = file.file.read()
        if (file.filename or "").endswith(".json"):
            bundle = parse_json_source(json.loads(raw_bytes.decode("utf-8")))
        else:
            with tempfile.NamedTemporaryFile(suffix=".xlsx",
                                             delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(raw_bytes)
            bundle = parse_excel(tmp_path)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_json_import.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/importer/json_source.py app/web/routes.py tests/test_json_import.py
git commit -m "feat(importer): 8000 导入支持新版 JSON 文本文件"
```

---

### Task 15: 端到端集成测试（提交 → 轮询 → 结果）

**Files:**
- Create: `tests/test_v1_integration.py`

**Interfaces:**
- Consumes: `api_router`/`get_db`（Task 12）、`ApiJobWorker`（Task 11）、真实 `SkillExecutor` + `MockProvider`

- [ ] **Step 1: 写集成测试**

创建 `tests/test_v1_integration.py`：

```python
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.api.routes import api_router, get_db
from app.api.worker import ApiJobWorker
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor


@pytest.fixture()
def env(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "api_keys", "secret")
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


@pytest.mark.asyncio
async def test_comment_screening_end_to_end(env):
    app, Session = env
    client = TestClient(app)
    payload = {"comments": [
        {"comment_id": "cm_1", "video_title": "试驾", "video_author": "@王",
         "video_author_fans": 1, "comment_content": "刚提这款车",
         "comment_author": "a", "comment_author_uid": "u1",
         "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 1}]}
    r = client.post("/api/v1/comment-screening", json=payload,
                    headers={"Authorization": "Bearer secret"})
    job_id = r.json()["job_id"]

    provider = MockProvider()
    provider.queue(json.dumps({"brand": "测试"}),
                   json.dumps({"items": [
                       {"comment_id": "cm_1", "is_meaningful": True,
                        "is_suspected_marketing": False,
                        "is_purchase_related": True, "reason": "真实车主"}]}))
    executor = SkillExecutor(LLMGateway(provider))
    worker = ApiJobWorker(lambda: Session(), executor, LLMGateway(provider))
    await worker.run_once()

    poll = client.get(f"/api/v1/jobs/{job_id}",
                      headers={"Authorization": "Bearer secret"})
    body = poll.json()
    assert body["status"] == "success"
    assert body["result"]["results"][0]["passed"] is True


@pytest.mark.asyncio
async def test_profile_analysis_end_to_end_no_screenshot(env):
    app, Session = env
    client = TestClient(app)
    payload = {"accounts": [
        {"account_uid": "u1", "account_name": "用户",
         "account_homepage_screenshot": "",
         "comment_history": [
             {"video_title": "对比", "comment_content": "在纠结这两款",
              "comment_time": "2026-07-19T14:23:00+08:00",
              "comment_like_count": 5}]}]}
    r = client.post("/api/v1/profile-analysis", json=payload,
                    headers={"Authorization": "Bearer secret"})
    job_id = r.json()["job_id"]

    provider = MockProvider()
    provider.queue(json.dumps({
        "lead_grade": "A", "is_valid_lead": True, "lead_summary": "对比中",
        "evidence_comment_ids": ["u1:0"], "confidence": 0.8,
        "profile_tags": ["对比阶段"], "profile_summary": "画像",
        "analysis_text": "分析"}))
    executor = SkillExecutor(LLMGateway(provider))
    worker = ApiJobWorker(lambda: Session(), executor, LLMGateway(provider))
    await worker.run_once()

    body = client.get(f"/api/v1/jobs/{job_id}",
                      headers={"Authorization": "Bearer secret"}).json()
    assert body["status"] == "success"
    assert body["result"]["results"][0]["intent_level_code"] == "medium"
```

- [ ] **Step 2: 运行集成测试**

Run: `python -m pytest tests/test_v1_integration.py -v`
Expected: PASS

- [ ] **Step 3: 运行全量测试确认无回归**

Run: `python -m pytest -q`
Expected: 全部 PASS（V0 既有测试不回归）

- [ ] **Step 4: 提交**

```bash
git add tests/test_v1_integration.py
git commit -m "test(api): 新增 V1 API 端到端集成测试"
```

---

### Task 16: Docker Compose 部署与配置模板

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.dockerignore`
- Test: 手动 `docker compose config` 校验（无自动化测试）

**Interfaces:**
- Consumes: `settings`（Task 1）、`/health`（Task 12）

- [ ] **Step 1: 创建 Dockerfile**

创建 `Dockerfile`：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 创建 .dockerignore**

创建 `.dockerignore`：

```
__pycache__/
*.pyc
.git/
.venv/
tests/
data/
docs/
claude_docs/
.env
```

- [ ] **Step 3: 创建 docker-compose.yml**

创建 `docker-compose.yml`：

```yaml
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_PASSWORD:-driveintent}
      MYSQL_DATABASE: ${DB_NAME:-driveintent}
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-p${DB_PASSWORD:-driveintent}"]
      interval: 10s
      timeout: 5s
      retries: 10

  app:
    build: .
    depends_on:
      mysql:
        condition: service_healthy
    environment:
      DB_HOST: mysql
      DB_PORT: 3306
      DB_USER: root
      DB_PASSWORD: ${DB_PASSWORD:-driveintent}
      DB_NAME: ${DB_NAME:-driveintent}
      LLM_PROVIDER: ${LLM_PROVIDER:-mock}
      LLM_BASE_URL: ${LLM_BASE_URL:-}
      LLM_API_KEY: ${LLM_API_KEY:-}
      LLM_MODEL: ${LLM_MODEL:-mock-model}
      API_KEYS: ${API_KEYS:-}
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 15s
      timeout: 5s
      retries: 5

volumes:
  mysql_data:
```

- [ ] **Step 4: 创建 .env.example**

创建 `.env.example`：

```
# 数据库
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=driveintent
DB_NAME=driveintent

# LLM（OpenAI 兼容，需支持图像输入以启用主页截图识别）
LLM_PROVIDER=mock
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=mock-model
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RETRIES=3

# V1 API
API_KEYS=change-me-key1,change-me-key2
API_WORKER_ENABLED=true
API_WORKER_CONCURRENCY=3

# Worker
WORKER_CONCURRENCY=3
COMMENT_BATCH_SIZE=30

# 图像
IMAGE_FETCH_TIMEOUT_SECONDS=30
```

- [ ] **Step 5: 校验 compose 配置**

Run: `docker compose config`
Expected: 输出解析后的配置，无语法错误。（若环境无 docker，跳过并在提交信息注明未本地验证。）

- [ ] **Step 6: 提交**

```bash
git add Dockerfile docker-compose.yml .env.example .dockerignore
git commit -m "feat: 新增 Docker Compose 独立部署配置"
```

---

### Task 17: 更新文档

**Files:**
- Modify: `README.md`（新增 V1 API 与部署简述）
- Modify: `CLAUDE.md`（当前阶段更新为 V1）

**Interfaces:** 无代码接口。

- [ ] **Step 1: 更新 CLAUDE.md**

将「当前阶段」一行更新为 V1 正式版开发阶段（微服务化 + 对外 API）。遵守最小化更新原则。

- [ ] **Step 2: 更新 README.md**

在合适位置新增一节「V1 API 与部署」，简述两个端点、轮询方式、`docker compose up` 启动步骤。指向 `claude_docs/2026-07-23-v1-design.md` 获取完整设计。

- [ ] **Step 3: 提交**

```bash
git add README.md CLAUDE.md
git commit -m "docs: 更新 README 与 CLAUDE 说明 V1 API 与部署"
```

---

## 依赖与执行顺序

任务按编号顺序执行；关键依赖：
- Task 5（映射）依赖 Task 3（schemas）、Task 4（内部 Schema 扩展）
- Task 9/10（Agent 编排）依赖 Task 5/6/7
- Task 11（Worker）依赖 Task 8/9/10
- Task 12（路由）依赖 Task 3/8
- Task 13（接入）依赖 Task 11/12
- Task 15（集成）依赖 Task 11/12/13
- Task 16/17 可最后并行

## 备注

- `requirements.txt` 现有依赖已覆盖 V1（httpx 已在，图像用标准库 base64/urllib）。若 Task 10 需下载 URL 截图交由多模态端点处理（多数端点支持直接传 URL），本期不实现服务端下载；如端点要求 Base64，可在后续迭代补 `httpx` 下载转码。当前 `build_image_message` 直接透传 URL，满足主流多模态端点。
- 真实多模态模型联调（对接文档所述截图识别）在全部任务完成后，按 V0 联调方式配置 `.env` 进行。
- 设计 §7.2「L1 表补充对接文档字段」：`comment` 表已有 `like_count` 可空列；`video_metrics`、`video_author_fans` 等热度字段统一存入现有 `raw_data` JSON 列（不新增专用列，遵循 YAGNI），xlsx 缺失时该 JSON 键为空。故不单列建表任务。

