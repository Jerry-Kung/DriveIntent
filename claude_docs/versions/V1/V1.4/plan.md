# DriveIntent V1.4 后端审计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**文档版本：** 1.4
**日期：** 2026-08-03
**上游文档：** `claude_docs/versions/V1/V1.4/design.md`（已评审通过）

**Goal:** 新增只读审计模块：按东八区自然天/小时统计 API 任务量与 LLM tokens 消耗，内置 `/audit` 页面展示。

**Architecture:** 纯只读三层——聚合服务 `app/services/audit_stats.py`（对既有 `api_job`、`llm_call_log` 两表做 SQL 分组聚合，分桶表达式按 MySQL/SQLite 方言分派）→ 路由 `app/web/audit.py`（`GET /audit`，参数校验与时间窗换算）→ 模板 `app/templates/audit.html`（Jinja2 服务端渲染，继承 base.html）。业务写路径零改动；配套两个新索引（模型声明 + 存量库幂等迁移脚本）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Jinja2 + pytest（内存 SQLite + TestClient），生产 MySQL 8。

## Global Constraints

- 界面与注释用简体中文；代码风格与现有文件一致（4 空格缩进、双引号、中文 docstring/注释）。
- 数据库落库为 UTC 朴素时间（`datetime.utcnow`）；所有分桶/展示按东八区（+8）自然时间。
- 审计模块**纯只读**：不新增表、不改任何业务写路径；业务模块不得反向依赖审计模块。
- 不引入任何新第三方依赖；不加图表库/JS 框架。
- 页面参数上限：`granularity=day` 时 `range` 默认 7、上限 90；`granularity=hour` 时默认 48、上限 168；非法值回退默认（不返回 4xx）。
- `job_type` 取值为 `comment_screening` / `profile_analysis`（见 `app/api/routes.py:41,51`）；作业状态为 `pending/running/success/partial/failed`。
- 测试命令统一用 `python -m pytest`（Windows PowerShell 环境）。
- 无 Prompt / Skill 变更，不涉及 VERSIONING.md 第 4 节资产版本号。

---

### Task 1: 模型索引声明

**Files:**
- Modify: `app/models/analysis.py`（`LlmCallLog`，52-68 行附近）
- Modify: `app/models/api_job.py`（`ApiJob.__table_args__`，11 行）
- Test: `tests/test_audit_stats.py`（新建）

**Interfaces:**
- Produces: 索引 `ix_llm_call_created`（`llm_call_log.created_at`）、`ix_api_job_finished`（`api_job.finished_at`），`create_all` 时自动创建。后续任务的聚合查询依赖它们（生产环境性能），逻辑上无 API 依赖。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_audit_stats.py`：

```python
from sqlalchemy import inspect


def test_audit_indexes_declared(session):
    insp = inspect(session.get_bind())
    llm_names = {i["name"] for i in insp.get_indexes("llm_call_log")}
    assert "ix_llm_call_created" in llm_names
    job_names = {i["name"] for i in insp.get_indexes("api_job")}
    assert "ix_api_job_finished" in job_names
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: FAIL（`ix_llm_call_created` 不在集合中）

- [ ] **Step 3: 实现**

`app/models/analysis.py` 中 `LlmCallLog` 类（`__tablename__` 之后）加：

```python
    __table_args__ = (Index("ix_llm_call_created", "created_at"),)
```

（文件顶部 `Index` 已在 import 列表中，无需改动 import。）

`app/models/api_job.py` 的 `__table_args__` 改为：

```python
    __table_args__ = (
        Index("ix_api_job_status_order", "status", "attempt_count",
              "created_at"),
        Index("ix_api_job_finished", "finished_at"),)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_audit_stats.py tests/test_models.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add app/models/analysis.py app/models/api_job.py tests/test_audit_stats.py
git commit -m "feat: V1.4 审计聚合所需索引声明（llm_call_log.created_at / api_job.finished_at）"
```

---

### Task 2: 聚合服务基础——时间窗换算与分桶表达式

**Files:**
- Create: `app/services/audit_stats.py`
- Test: `tests/test_audit_stats.py`（追加）

**Interfaces:**
- Produces:
  - `TZ8: timezone` — 东八区时区常量
  - `utc_range(granularity: str, span: int, now_utc: datetime | None = None) -> tuple[datetime, datetime]` — 最近 span 个东八区自然天/小时（含当前所在桶）的 UTC 朴素时间边界 `[start, end)`
  - `_bucket(db, col, granularity: str)` — 模块私有：返回把 UTC 列转东八区并格式化为桶标签的 SQL 表达式（day→`"2026-08-01"`，hour→`"2026-08-01 12:00"`），按方言分派 MySQL/SQLite

- [ ] **Step 1: 写失败测试**

`tests/test_audit_stats.py` 顶部 import 区改为：

```python
from datetime import datetime

from sqlalchemy import inspect

from app.models import ApiJob, LlmCallLog
from app.services.audit_stats import (job_stats, llm_stats, today_summary,
                                      utc_range)
```

（`job_stats`/`llm_stats`/`today_summary` 在 Task 3-5 实现，本任务先只实现 `utc_range`——为避免 import 报错，Task 2 的 import 行先只写 `utc_range`，后续任务再逐个追加。）

追加测试：

```python
def test_utc_range_day_covers_local_days():
    # 东八区当前时刻 2026-08-02 01:30（= UTC 2026-08-01 17:30）
    # span=2 → 覆盖东八区 08-01、08-02 两个自然天
    start, end = utc_range("day", 2, now_utc=datetime(2026, 8, 1, 17, 30))
    assert start == datetime(2026, 7, 31, 16, 0)   # 东八区 08-01 00:00
    assert end == datetime(2026, 8, 2, 16, 0)      # 东八区 08-03 00:00


def test_utc_range_hour_covers_current_hour():
    # UTC 17:30 = 东八区 01:30，span=3 → 东八区 23:00/00:00/01:00 三个小时桶
    start, end = utc_range("hour", 3, now_utc=datetime(2026, 8, 1, 17, 30))
    assert start == datetime(2026, 8, 1, 15, 0)
    assert end == datetime(2026, 8, 1, 18, 0)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: FAIL（`ModuleNotFoundError: app.services.audit_stats`）

- [ ] **Step 3: 实现**

新建 `app/services/audit_stats.py`：

```python
"""V1.4 后端审计：只读聚合统计服务。

数据源为业务既有落库的 api_job 与 llm_call_log 两表，本模块只查询、
不写库，业务模块不依赖本模块。时间口径：库内为 UTC 朴素时间，分桶按
东八区自然天/小时（+8 小时转换）。生产 MySQL、测试 SQLite，分桶表达
式按方言分派。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text

from app.models import ApiJob, LlmCallLog

TZ8 = timezone(timedelta(hours=8))


def utc_range(granularity: str, span: int,
              now_utc: datetime | None = None) -> tuple[datetime, datetime]:
    """最近 span 个东八区自然天/小时（含当前所在桶）的 UTC 边界 [start, end)。"""
    now = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc)
    local = now.astimezone(TZ8)
    if granularity == "day":
        end_local = (local + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        start_local = end_local - timedelta(days=span)
    else:
        end_local = local.replace(
            minute=0, second=0, microsecond=0) + timedelta(hours=1)
        start_local = end_local - timedelta(hours=span)

    def to_utc(d: datetime) -> datetime:
        return d.astimezone(timezone.utc).replace(tzinfo=None)

    return to_utc(start_local), to_utc(end_local)


def _bucket(db, col, granularity: str):
    """UTC 时间列 → 东八区天/小时桶标签的 SQL 表达式（按方言分派）。"""
    fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H:00"
    if db.get_bind().dialect.name == "mysql":
        return func.date_format(
            func.date_add(col, text("INTERVAL 8 HOUR")), fmt)
    return func.strftime(fmt, func.datetime(col, "+8 hours"))
```

`tests/test_audit_stats.py` 的 import 行本任务写为：

```python
from app.services.audit_stats import utc_range
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/audit_stats.py tests/test_audit_stats.py
git commit -m "feat: V1.4 审计聚合服务基础（东八区时间窗换算与跨方言分桶表达式）"
```

---

### Task 3: 任务量聚合 `job_stats`

**Files:**
- Modify: `app/services/audit_stats.py`
- Test: `tests/test_audit_stats.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `_bucket`
- Produces: `job_stats(db, granularity: str, start_utc: datetime, end_utc: datetime) -> list[dict]`，元素形如 `{"bucket": "2026-08-01", "job_type": "comment_screening", "received": 2, "success": 1, "partial": 0, "failed": 0}`，按 `(bucket, job_type)` 倒序。接收量按 `created_at` 分桶；success/partial/failed 按 `finished_at` 分桶（仅 `finished_at` 非空记录）。

- [ ] **Step 1: 写失败测试**

`tests/test_audit_stats.py` import 追加 `job_stats` 与 `ApiJob`，并追加：

```python
def _job(job_id, created, finished=None, status="pending",
         job_type="comment_screening"):
    return ApiJob(id=job_id, job_type=job_type, status=status,
                  created_at=created, finished_at=finished)


def test_job_stats_day_buckets_timezone_and_status(session):
    # UTC 15:30 → 东八区 08-01 23:30；UTC 16:30 → 东八区 08-02 00:30
    session.add_all([
        _job("j1", datetime(2026, 8, 1, 15, 30),
             finished=datetime(2026, 8, 1, 15, 40), status="success"),
        _job("j2", datetime(2026, 8, 1, 16, 30)),          # pending 只计接收
        _job("j3", datetime(2026, 8, 1, 16, 40),
             finished=datetime(2026, 8, 1, 17, 0), status="failed"),
        _job("j4", datetime(2026, 8, 1, 16, 50),
             finished=datetime(2026, 8, 1, 17, 10), status="partial",
             job_type="profile_analysis"),
    ])
    session.commit()
    rows = job_stats(session, "day",
                     datetime(2026, 7, 30, 16), datetime(2026, 8, 3, 16))
    by_key = {(r["bucket"], r["job_type"]): r for r in rows}
    r1 = by_key[("2026-08-01", "comment_screening")]
    assert r1["received"] == 1 and r1["success"] == 1 and r1["failed"] == 0
    r2 = by_key[("2026-08-02", "comment_screening")]
    assert r2["received"] == 2 and r2["failed"] == 1 and r2["success"] == 0
    r3 = by_key[("2026-08-02", "profile_analysis")]
    assert r3["received"] == 1 and r3["partial"] == 1
    # 倒序：最新桶在前
    assert rows[0]["bucket"] >= rows[-1]["bucket"]


def test_job_stats_hour_buckets(session):
    session.add(_job("j1", datetime(2026, 8, 1, 4, 10)))  # 东八区 12:10
    session.commit()
    rows = job_stats(session, "hour",
                     datetime(2026, 8, 1, 0), datetime(2026, 8, 1, 8))
    assert rows[0]["bucket"] == "2026-08-01 12:00"
    assert rows[0]["received"] == 1


def test_job_stats_empty(session):
    assert job_stats(session, "day",
                     datetime(2026, 7, 30), datetime(2026, 8, 3)) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: FAIL（`cannot import name 'job_stats'`）

- [ ] **Step 3: 实现**

`app/services/audit_stats.py` 追加：

```python
def _empty_job_row(bucket: str, job_type: str) -> dict:
    return {"bucket": bucket, "job_type": job_type,
            "received": 0, "success": 0, "partial": 0, "failed": 0}


def job_stats(db, granularity: str,
              start_utc: datetime, end_utc: datetime) -> list[dict]:
    """任务量明细：接收量按 created_at 分桶，完成量按 finished_at 分桶。"""
    rows: dict[tuple[str, str], dict] = {}
    created = _bucket(db, ApiJob.created_at, granularity)
    for bucket, job_type, n in (
            db.query(created, ApiJob.job_type, func.count())
            .filter(ApiJob.created_at >= start_utc,
                    ApiJob.created_at < end_utc)
            .group_by(created, ApiJob.job_type)):
        rows.setdefault((bucket, job_type),
                        _empty_job_row(bucket, job_type))["received"] = n
    finished = _bucket(db, ApiJob.finished_at, granularity)
    for bucket, job_type, status, n in (
            db.query(finished, ApiJob.job_type, ApiJob.status, func.count())
            .filter(ApiJob.finished_at.isnot(None),
                    ApiJob.finished_at >= start_utc,
                    ApiJob.finished_at < end_utc)
            .group_by(finished, ApiJob.job_type, ApiJob.status)):
        row = rows.setdefault((bucket, job_type),
                              _empty_job_row(bucket, job_type))
        if status in ("success", "partial", "failed"):
            row[status] = n
    return sorted(rows.values(),
                  key=lambda r: (r["bucket"], r["job_type"]), reverse=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/audit_stats.py tests/test_audit_stats.py
git commit -m "feat: V1.4 任务量聚合 job_stats（接收/完成分列，含时区分桶）"
```

---

### Task 4: LLM 消耗聚合 `llm_stats`

**Files:**
- Modify: `app/services/audit_stats.py`
- Test: `tests/test_audit_stats.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `_bucket`
- Produces: `llm_stats(db, granularity: str, start_utc: datetime, end_utc: datetime) -> list[dict]`，元素形如 `{"bucket": ..., "skill_id": ..., "model_name": ..., "calls": 3, "errors": 1, "prompt_tokens": 300, "completion_tokens": 150, "avg_duration_ms": 800}`，按 `(bucket, skill_id, model_name)` 倒序。`calls` 含成功与失败的每次真实请求；`errors` 为 `error` 非空的条数。

- [ ] **Step 1: 写失败测试**

`tests/test_audit_stats.py` import 追加 `llm_stats` 与 `LlmCallLog`，并追加：

```python
def _call(created, skill="comment_lead_screening", model="m1",
          pt=100, ct=50, error=None, dur=800):
    return LlmCallLog(skill_id=skill, model_name=model, prompt_tokens=pt,
                      completion_tokens=ct, duration_ms=dur, error=error,
                      created_at=created)


def test_llm_stats_grouping_sums_and_errors(session):
    day = datetime(2026, 8, 1, 4, 0)  # 东八区 08-01 12:00
    session.add_all([
        _call(day, pt=100, ct=50, dur=600),
        _call(day, pt=200, ct=70, dur=1000, error="超时"),
        _call(day, skill="user_lead_analysis", model="m2", pt=999, ct=1),
    ])
    session.commit()
    rows = llm_stats(session, "day",
                     datetime(2026, 7, 31, 16), datetime(2026, 8, 1, 16))
    by_key = {(r["skill_id"], r["model_name"]): r for r in rows}
    r1 = by_key[("comment_lead_screening", "m1")]
    assert r1["bucket"] == "2026-08-01"
    assert r1["calls"] == 2 and r1["errors"] == 1
    assert r1["prompt_tokens"] == 300 and r1["completion_tokens"] == 120
    assert r1["avg_duration_ms"] == 800
    r2 = by_key[("user_lead_analysis", "m2")]
    assert r2["calls"] == 1 and r2["errors"] == 0
    assert r2["prompt_tokens"] == 999


def test_llm_stats_range_filter(session):
    session.add(_call(datetime(2026, 8, 1, 4, 0)))
    session.commit()
    assert llm_stats(session, "day",
                     datetime(2026, 8, 2, 16), datetime(2026, 8, 3, 16)) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: FAIL（`cannot import name 'llm_stats'`）

- [ ] **Step 3: 实现**

`app/services/audit_stats.py` 追加：

```python
def llm_stats(db, granularity: str,
              start_utc: datetime, end_utc: datetime) -> list[dict]:
    """LLM 消耗明细：每条 llm_call_log 为一次真实请求（含重试与失败）。"""
    bucket = _bucket(db, LlmCallLog.created_at, granularity)
    query = (
        db.query(bucket, LlmCallLog.skill_id, LlmCallLog.model_name,
                 func.count(),
                 func.count(LlmCallLog.error),  # COUNT(col) 只计非空 → 失败数
                 func.coalesce(func.sum(LlmCallLog.prompt_tokens), 0),
                 func.coalesce(func.sum(LlmCallLog.completion_tokens), 0),
                 func.avg(LlmCallLog.duration_ms))
        .filter(LlmCallLog.created_at >= start_utc,
                LlmCallLog.created_at < end_utc)
        .group_by(bucket, LlmCallLog.skill_id, LlmCallLog.model_name))
    rows = [
        {"bucket": b, "skill_id": skill, "model_name": model,
         "calls": calls, "errors": errors,
         "prompt_tokens": int(pt), "completion_tokens": int(ct),
         "avg_duration_ms": int(round(avg or 0))}
        for b, skill, model, calls, errors, pt, ct, avg in query]
    return sorted(rows, key=lambda r: (r["bucket"], r["skill_id"],
                                       r["model_name"]), reverse=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/audit_stats.py tests/test_audit_stats.py
git commit -m "feat: V1.4 LLM 消耗聚合 llm_stats（次数/失败/tokens/平均耗时）"
```

---

### Task 5: 今日汇总 `today_summary`

**Files:**
- Modify: `app/services/audit_stats.py`
- Test: `tests/test_audit_stats.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `utc_range`
- Produces: `today_summary(db, now_utc: datetime | None = None) -> dict`，形如 `{"jobs_received": 1, "jobs_finished": 1, "llm_calls": 2, "prompt_tokens": 300, "completion_tokens": 120}`（东八区今日；`now_utc` 参数供测试注入）。

- [ ] **Step 1: 写失败测试**

`tests/test_audit_stats.py` import 追加 `today_summary`，并追加：

```python
def test_today_summary(session):
    now_utc = datetime(2026, 8, 1, 10, 0)  # 东八区 08-01 18:00
    session.add_all([
        _job("j1", datetime(2026, 8, 1, 4, 0),
             finished=datetime(2026, 8, 1, 5, 0), status="success"),
        _job("j2", datetime(2026, 7, 31, 10, 0)),   # 昨天：不计
        _call(datetime(2026, 8, 1, 4, 0), pt=100, ct=50),
        _call(datetime(2026, 8, 1, 6, 0), pt=200, ct=70),
    ])
    session.commit()
    s = today_summary(session, now_utc=now_utc)
    assert s["jobs_received"] == 1
    assert s["jobs_finished"] == 1
    assert s["llm_calls"] == 2
    assert s["prompt_tokens"] == 300
    assert s["completion_tokens"] == 120


def test_today_summary_empty(session):
    s = today_summary(session)
    assert s == {"jobs_received": 0, "jobs_finished": 0, "llm_calls": 0,
                 "prompt_tokens": 0, "completion_tokens": 0}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: FAIL（`cannot import name 'today_summary'`）

- [ ] **Step 3: 实现**

`app/services/audit_stats.py` 追加：

```python
def today_summary(db, now_utc: datetime | None = None) -> dict:
    """东八区今日汇总（now_utc 供测试注入当前时刻）。"""
    start_utc, end_utc = utc_range("day", 1, now_utc=now_utc)
    jobs_received = (
        db.query(func.count()).select_from(ApiJob)
        .filter(ApiJob.created_at >= start_utc,
                ApiJob.created_at < end_utc).scalar())
    jobs_finished = (
        db.query(func.count()).select_from(ApiJob)
        .filter(ApiJob.finished_at.isnot(None),
                ApiJob.finished_at >= start_utc,
                ApiJob.finished_at < end_utc).scalar())
    llm_calls, prompt_tokens, completion_tokens = (
        db.query(func.count(),
                 func.coalesce(func.sum(LlmCallLog.prompt_tokens), 0),
                 func.coalesce(func.sum(LlmCallLog.completion_tokens), 0))
        .select_from(LlmCallLog)
        .filter(LlmCallLog.created_at >= start_utc,
                LlmCallLog.created_at < end_utc).one())
    return {"jobs_received": jobs_received, "jobs_finished": jobs_finished,
            "llm_calls": llm_calls, "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens)}
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_audit_stats.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/audit_stats.py tests/test_audit_stats.py
git commit -m "feat: V1.4 今日汇总 today_summary"
```

---

### Task 6: `/audit` 路由、模板与挂载

**Files:**
- Create: `app/web/audit.py`
- Create: `app/templates/audit.html`
- Modify: `app/main.py`（import + include_router）
- Modify: `app/templates/base.html:131-134`（导航栏）
- Test: `tests/test_v14_integration.py`（新建）

**Interfaces:**
- Consumes: Task 3-5 的 `job_stats` / `llm_stats` / `today_summary` / `utc_range`；`app/web/routes.py` 的 `get_db` 与 `templates`（复用同一依赖，测试 override `app.web.routes.get_db` 即对本路由生效）
- Produces: `GET /audit?granularity=day|hour&range=N` 页面；导航项「审计统计」（`active == 'audit'` 高亮）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_v14_integration.py`：

```python
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import ApiJob, LlmCallLog
from app.web.routes import get_db


def _client(session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return TestClient(app)          # 不用 with，避免触发 lifespan/MySQL


def test_audit_page_renders_stats(session):
    now = datetime.utcnow()
    session.add_all([
        ApiJob(id="j1", job_type="comment_screening", status="success",
               created_at=now - timedelta(minutes=10),
               finished_at=now - timedelta(minutes=5)),
        LlmCallLog(skill_id="comment_lead_screening", model_name="m1",
                   prompt_tokens=123, completion_tokens=45,
                   duration_ms=600, created_at=now - timedelta(minutes=8)),
    ])
    session.commit()
    r = _client(session).get("/audit")
    assert r.status_code == 200
    assert "审计统计" in r.text
    assert "comment_lead_screening" in r.text
    assert "123" in r.text


def test_audit_page_empty_db(session):
    r = _client(session).get("/audit")
    assert r.status_code == 200
    assert "暂无数据" in r.text
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_v14_integration.py -v`
Expected: FAIL（GET /audit 返回 404）

- [ ] **Step 3: 实现路由**

新建 `app/web/audit.py`：

```python
"""V1.4 审计页面：任务量与 LLM 消耗统计（只读展示）。"""
import logging

from fastapi import APIRouter, Depends, Query, Request

from app.services.audit_stats import (job_stats, llm_stats, today_summary,
                                      utc_range)
from app.web.routes import get_db, templates

logger = logging.getLogger(__name__)

audit_router = APIRouter()

# granularity → (默认范围, 上限)
_LIMITS = {"day": (7, 90), "hour": (48, 168)}


@audit_router.get("/audit")
def audit_page(request: Request,
               granularity: str = "day",
               range_: int | None = Query(default=None, alias="range"),
               db=Depends(get_db)):
    if granularity not in _LIMITS:
        granularity = "day"
    default, cap = _LIMITS[granularity]
    span = min(range_, cap) if range_ and range_ > 0 else default
    ctx = {"active": "audit", "granularity": granularity, "span": span,
           "error": None, "summary": None, "jobs": [], "llm": []}
    try:
        start_utc, end_utc = utc_range(granularity, span)
        ctx["summary"] = today_summary(db)
        ctx["jobs"] = job_stats(db, granularity, start_utc, end_utc)
        ctx["llm"] = llm_stats(db, granularity, start_utc, end_utc)
    except Exception:
        logger.exception("审计统计查询失败")
        ctx["error"] = "统计查询失败，请稍后重试或查看服务日志"
    return templates.TemplateResponse(request, "audit.html", ctx)
```

- [ ] **Step 4: 实现模板**

新建 `app/templates/audit.html`：

```html
{% extends "base.html" %}
{% block title %}DriveIntent - 审计统计{% endblock %}

{% block content %}
  {% if error %}
  <section class="card"><span class="bad-text">{{ error }}</span></section>
  {% endif %}

  {% if summary %}
  <section class="stats">
    <div class="card stat">
      <div class="stat-num num">{{ summary.jobs_received }}</div>
      <div class="hint">今日任务接收</div>
    </div>
    <div class="card stat">
      <div class="stat-num num">{{ summary.jobs_finished }}</div>
      <div class="hint">今日任务完成</div>
    </div>
    <div class="card stat">
      <div class="stat-num num">{{ summary.llm_calls }}</div>
      <div class="hint">今日 LLM 调用</div>
    </div>
    <div class="card stat">
      <div class="stat-num num">{{ "{:,}".format(summary.prompt_tokens) }}</div>
      <div class="hint">今日输入 tokens</div>
    </div>
    <div class="card stat">
      <div class="stat-num num">{{ "{:,}".format(summary.completion_tokens) }}</div>
      <div class="hint">今日输出 tokens</div>
    </div>
  </section>
  {% endif %}

  <section class="card">
    <form method="get" action="/audit" class="row">
      <label>粒度
        <select name="granularity">
          <option value="day" {% if granularity == 'day' %}selected{% endif %}>按天</option>
          <option value="hour" {% if granularity == 'hour' %}selected{% endif %}>按小时</option>
        </select>
      </label>
      <label>最近
        <input type="number" name="range" value="{{ span }}" min="1"
               style="width: 80px">
        <span class="hint">{% if granularity == 'day' %}天（上限 90）{% else %}小时（上限 168）{% endif %}</span>
      </label>
      <button class="primary" type="submit">查询</button>
      <span class="hint">时间均为北京时间（UTC+8）；刷新页面即为最新数据</span>
    </form>
  </section>

  {% set job_names = {'comment_screening': '评论初筛',
                      'profile_analysis': '画像分析'} %}
  <section class="card flush">
    <div class="card-head"><h2>任务量明细</h2></div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>时间</th><th>任务类型</th><th>接收</th>
          <th>成功</th><th>部分成功</th><th>失败</th>
        </tr></thead>
        <tbody>
          {% for r in jobs %}
          <tr>
            <td class="num">{{ r.bucket }}</td>
            <td>{{ job_names.get(r.job_type, r.job_type) }}</td>
            <td class="num">{{ r.received }}</td>
            <td class="num {% if r.success %}ok-text{% endif %}">{{ r.success }}</td>
            <td class="num">{{ r.partial }}</td>
            <td class="num {% if r.failed %}bad-text{% endif %}">{{ r.failed }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% if not jobs %}<div class="empty">暂无数据</div>{% endif %}
    </div>
  </section>

  <section class="card flush">
    <div class="card-head"><h2>LLM 消耗明细</h2></div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>时间</th><th>Skill</th><th>模型</th><th>调用次数</th>
          <th>失败</th><th>输入 tokens</th><th>输出 tokens</th>
          <th>平均耗时(ms)</th>
        </tr></thead>
        <tbody>
          {% for r in llm %}
          <tr>
            <td class="num">{{ r.bucket }}</td>
            <td>{{ r.skill_id }}</td>
            <td>{{ r.model_name }}</td>
            <td class="num">{{ r.calls }}</td>
            <td class="num {% if r.errors %}bad-text{% endif %}">{{ r.errors }}</td>
            <td class="num">{{ "{:,}".format(r.prompt_tokens) }}</td>
            <td class="num">{{ "{:,}".format(r.completion_tokens) }}</td>
            <td class="num">{{ r.avg_duration_ms }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% if not llm %}<div class="empty">暂无数据</div>{% endif %}
    </div>
  </section>
{% endblock %}

{% block extra_style %}
    .stats { display: grid; gap: 14px; margin-bottom: 18px;
             grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
    .stat { margin-bottom: 0; text-align: center; }
    .stat-num { font-size: 26px; font-weight: 700; }
    .row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
{% endblock %}
```

- [ ] **Step 5: 挂载与导航**

`app/main.py` import 区加一行（保持字母序，放在 `from app.web.routes import router` 之后）：

```python
from app.web.audit import audit_router
```

`app.include_router(api_router)` 之后加：

```python
app.include_router(audit_router)
```

`app/templates/base.html` 导航栏（133 行 `/leads` 链接之后）加：

```html
        <a href="/audit" class="{% if active == 'audit' %}active{% endif %}">审计统计</a>
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_v14_integration.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add app/web/audit.py app/templates/audit.html app/main.py app/templates/base.html tests/test_v14_integration.py
git commit -m "feat: V1.4 /audit 审计页面（今日汇总卡片+任务量/LLM 消耗明细表）"
```

---

### Task 7: 集成测试补全（参数边界 + 冒烟）

**Files:**
- Test: `tests/test_v14_integration.py`（追加）

**Interfaces:**
- Consumes: Task 6 的 `/audit` 路由（参数语义见 Global Constraints）

- [ ] **Step 1: 写测试**

`tests/test_v14_integration.py` 追加：

```python
def test_audit_params_fallback_and_cap(session):
    client = _client(session)
    # 非法粒度回退 day；超上限截断；非正数回退默认——都不报 4xx
    assert client.get("/audit?granularity=bogus").status_code == 200
    assert client.get("/audit?granularity=hour&range=99999").status_code == 200
    assert client.get("/audit?range=-5").status_code == 200
    # 上限截断体现在回填的 range 输入框值
    r = client.get("/audit?granularity=hour&range=99999")
    assert 'value="168"' in r.text
    r = client.get("/audit?granularity=day&range=99999")
    assert 'value="90"' in r.text


def test_audit_hour_granularity_renders(session):
    now = datetime.utcnow()
    session.add(LlmCallLog(skill_id="user_lead_analysis", model_name="m2",
                           prompt_tokens=10, completion_tokens=5,
                           duration_ms=100,
                           created_at=now - timedelta(minutes=1)))
    session.commit()
    r = _client(session).get("/audit?granularity=hour")
    assert r.status_code == 200
    assert "user_lead_analysis" in r.text


def test_nav_contains_audit_link(session):
    r = _client(session).get("/")
    assert r.status_code == 200
    assert '/audit' in r.text


def test_business_endpoints_unchanged(session):
    client = _client(session)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/leads").status_code == 200
```

- [ ] **Step 2: 运行确认通过**

Run: `python -m pytest tests/test_v14_integration.py -v`
Expected: PASS（若 `value="168"` 断言失败，检查路由 `span` 截断逻辑与模板回填）

- [ ] **Step 3: 全量回归**

Run: `python -m pytest`
Expected: 全部 PASS（确认业务测试零回归）

- [ ] **Step 4: 提交**

```bash
git add tests/test_v14_integration.py
git commit -m "test: V1.4 集成测试补全（参数边界/导航/业务冒烟）"
```

---

### Task 8: 存量库幂等补索引脚本

**Files:**
- Create: `scripts/add_audit_indexes.py`

**Interfaces:**
- Consumes: Task 1 声明的索引名（`ix_llm_call_created` / `ix_api_job_finished`，脚本与模型声明必须同名，避免存量库与新库索引名分叉）
- Produces: 部署时手动执行一次的迁移脚本（仿 `scripts/fix_api_job_index.py`；无自动化测试，依赖 MySQL 环境，上线时人工执行验证）

- [ ] **Step 1: 实现**

新建 `scripts/add_audit_indexes.py`：

```python
"""
V1.4 后端审计：为存量库补聚合查询所需索引（幂等，可重复执行）。

- llm_call_log(created_at) → ix_llm_call_created
- api_job(finished_at)     → ix_api_job_finished

数据库连接从 .env 读取（外部 MySQL）。全新部署时 app 首次启动
create_all 会按最新模型自动建出索引，无需运行本脚本。
"""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.environ["DB_NAME"]
INDEXES = [
    ("llm_call_log", "ix_llm_call_created", "(created_at)"),
    ("api_job", "ix_api_job_finished", "(finished_at)"),
]

conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", 3306)),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    database=DB_NAME,
)


def table_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name=%s LIMIT 1",
        (DB_NAME, table))
    return cur.fetchone() is not None


def index_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.statistics "
        "WHERE table_schema=%s AND table_name=%s AND index_name=%s LIMIT 1",
        (DB_NAME, table, name))
    return cur.fetchone() is not None


with conn:
    with conn.cursor() as cur:
        for table, name, cols in INDEXES:
            if not table_exists(cur, table):
                print(f"{table} 表不存在，跳过（全新库由 app 启动时自动建表建索引）")
            elif index_exists(cur, table, name):
                print(f"索引 {name} 已存在，无需处理")
            else:
                cur.execute(f"ALTER TABLE {table} ADD INDEX {name} {cols}")
                conn.commit()
                print(f"已创建索引 {table}.{name}")
```

- [ ] **Step 2: 语法自检**

Run: `python -c "import ast; ast.parse(open('scripts/add_audit_indexes.py', encoding='utf-8').read()); print('ok')"`
Expected: 输出 `ok`（脚本依赖真实 MySQL，不在 CI 执行；上线时人工运行）

- [ ] **Step 3: 提交**

```bash
git add scripts/add_audit_indexes.py
git commit -m "chore: V1.4 存量库补审计索引脚本（幂等）"
```

---

### Task 9: 发版文档与检查清单

**Files:**
- Modify: `claude_docs/versions/V1/OVERVIEW.md`

**Interfaces:**
- Consumes: 全部前序任务已完成、全量测试通过

- [ ] **Step 1: 更新 OVERVIEW.md**

1. 顶部更新时间改为：`> 最后更新：2026-08-03（随 V1.4 发布）`
2. 「能力快照」的「配套能力」条目后追加一条：

```markdown
  - **后端审计（V1.4）**：内部页 `/audit` 按东八区自然天/小时展示 API 任务量（接收/成功/部分成功/失败）与 LLM 消耗（调用次数/失败/输入输出 tokens/平均耗时，按 skill × 模型细分）；纯只读模块，数据源为既有 `api_job` / `llm_call_log` 落库。
```

3. 「变更索引」表末尾加行：

```markdown
| V1.4 | 2026-08-03 | 后端审计：任务量/LLM tokens 明细统计 + /audit 内置页面（只读，业务零改动） | [design](V1.4/design.md) / [plan](V1.4/plan.md) |
```

- [ ] **Step 2: 核对 VERSIONING.md 发版检查清单**

- design.md / plan.md 已落 `versions/V1/V1.4/`（本计划即 plan.md）✓
- 文档首部含版本与日期 ✓
- OVERVIEW.md 已更新（Step 1）
- 无 Prompt/Skill 资产变更 ✓
- 对外契约零变化，无需更新对接文档 ✓

- [ ] **Step 3: 全量回归**

Run: `python -m pytest`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add claude_docs/versions/V1/OVERVIEW.md
git commit -m "docs: V1.4 发版更新 OVERVIEW（能力快照+变更索引）"
```
