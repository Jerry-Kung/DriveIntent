# V1.9.0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户黑名单机制——精筛定级对 `account_douyin_id` 做零 LLM 的数据库匹配，命中直接输出"黑名单用户"（C / is_valid_lead=False / 契约不变），并提供管理页维护黑名单表。

**Architecture:** 新增 `blacklisted_user` 表（orm create_all 自动建，无需迁移）；API Worker 作业级经线程池一次性批量读入命中集合，`run_profile_analysis` 每账号头部短路；管理页 `/blacklist` + `POST/DELETE /api/blacklist`。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / Pydantic v2 / pytest（既有栈，无新依赖）

**Spec:** `claude_docs/versions/V1/V1.9/design.md`

## Global Constraints

- 简体中文注释/文档；写入中文后须检查无乱码（CLAUDE.md 临时要求）。
- **黑名单是零 LLM 节点**：不新增/修改任何 Prompt 文件、不升 Skill `version`/`prompt_version`、不改 `SKILL_VERSIONS`。
- **对外 API 契约零新增字段**；命中通过 `has_value=false` + `analysis_text` 表达。
- DB IO 不得进事件循环（V1.4.4/V1.4.5 纪律）：黑名单批量读经 `asyncio.to_thread`。
- 缺省行为回归安全：`blacklist=None` 时 `run_profile_analysis` 行为与现状完全一致。
- 全量回归基线：356 passed（提交前必须全绿）。

---

### Task 1: 黑名单数据模型与服务层

**Files:**
- Create: `app/models/blacklist.py`
- Modify: `app/models/__init__.py`（注册 `BlacklistedUser`）
- Create: `app/services/blacklist.py`
- Test: `tests/test_blacklist_service.py`（新建）

**Interfaces:**
- Produces: `BlacklistedUser`（id/douyin_id UNIQUE/nickname/remark/created_at）；`load_blacklist_matches(session, ids) -> set[str]`；`list_blacklist(session) -> list[BlacklistedUser]`（created_at 倒序）；`add_blacklist(session, douyin_ids, nickname=None, remark=None) -> dict`（幂等，返回 `{added, skipped, invalid}`）；`delete_blacklist(session, record_id) -> bool`
- `load_blacklist_matches`：`ids` 空 → 空集；未命中 → 空集；返回入参 id 中命中的 `douyin_id` 集合。
- 非法 ID（非纯数字/空串）在 `add_blacklist` 服务层归一化：仅收纯数字字符串，其余计入 `invalid` 且不入库。

- [ ] 先写失败测试：模型字段与唯一约束；`load_blacklist_matches` 命中/未命中/空候选；`add_blacklist` 新增/重复跳过/非法归一；`list_blacklist` 倒序；`delete_blacklist` 命中/未命中
- [ ] 实现模型 + 服务层；`app/models/__init__.py` 注册
- [ ] `pytest tests/test_blacklist_service.py -q` 通过

### Task 2: Agent2 集成与 API Worker 接线

**Files:**
- Modify: `app/api/agent2.py`（`run_profile_analysis` 加 `blacklist` 参数；per-account 头部短路）
- Modify: `app/api/worker.py`（`_execute` 透传 blacklist；`run_once` 作业级经线程池读命中集合——仅在 `job_type == "profile_analysis"` 且 payload 存在非空 `account_douyin_id` 时查询，否则为 None）
- Test: `tests/test_agent2.py`（追加）、`tests/test_api_worker.py`（追加）

**Interfaces:**
- `run_profile_analysis(..., *, blacklist: set[str] | frozenset[str] | None = None)`：`blacklist` 命中 → 该账号短路为 `UserLeadResult(lead_grade="C", is_valid_lead=False, filter_category="blacklisted", filter_reason=..., analysis_text=...)`，跳过识图/过滤/定级/复核/润色；`grade_sink` 照常补 `"C"`。
- `ApiJobWorker`：`run_once` 在认领后、`_execute` 前，若为 profile 作业则从 `payload["accounts"]` 提取非空 douyin_id，经 `asyncio.to_thread` 调 `load_blacklist_matches`；查询异常 → 记 warning 并置 None（fail-open）；结果传入 `_execute(..., blacklist=...)`。
- 命中判定用 `blacklist`（set）而非 `None`；`blacklist is None` 或空集合时行为与现状一致。

- [ ] 先写失败集成测试：命中账号零 LLM 调用（provider 未消费）、`has_value=false`、`analysis_text` 含"黑名单"、`grade_sink` 收到 C；未命中走完整流水线；`blacklist=None` 回归不变
- [ ] 实现 `run_profile_analysis` 短路分支 + worker 批读接线
- [ ] 相关 agent2 / worker 测试通过；既有 `test_profile_*` 与 `test_api_worker_session.py` 不回归

### Task 3: 黑名单管理页

**Files:**
- Create: `app/web/blacklist.py`（`blacklist_router`）
- Modify: `app/main.py`（注册 `blacklist_router`）
- Create: `app/templates/blacklist.html`
- Modify: `app/templates/base.html`（导航加"黑名单"）
- Test: `tests/test_web_blacklist.py`（新建）

**Interfaces:**
- `GET /blacklist`：页面（录入表单 + 列表）。表单字段 `douyin_ids`（逗号/换行分隔）、`nickname`、`remark`。
- `POST /api/blacklist`：`application/x-www-form-urlencoded`，解析 `douyin_ids`（正则 `/[\d]+/g` 抽取，去重），调 `add_blacklist`，返回 JSON `{added, skipped, invalid}`。
- `DELETE /api/blacklist/{id}`：调 `delete_blacklist`，`204`（命中）/`404`（未命中）。
- 页面从 `list_blacklist` 拉取并渲染（倒序）；沿用 base.html 的 `.card`/`.table-wrap` 样式。
- 安全：参数化查询；与 `/audit` 同层，不做额外鉴权。

- [ ] 先写失败测试：`GET /blacklist` 渲染 200 且含表单与列表；`POST` 新增/非法/重复；`DELETE` 204/404
- [ ] 实现路由 + 模板 + 导航；`main.py` 注册
- [ ] 测试通过

### Task 4: 文档与发版清单

**Files:**
- Modify: `claude_docs/versions/V1/OVERVIEW.md`（能力快照加黑名单机制条目 + 变更索引加 V1.9.0 行）
- Modify: `docs/DriveIntent-V1-API对接文档.md`（精筛结果表补说明：命中黑名单的账号 `has_value=false` 且 `analysis_text` 含"黑名单"字样；行为变化章节加 V1.9.0 黑名单条目）
- Modify: `docs/DriveIntent-部署文档.md`（新增表 `blacklisted_user` 由服务自动建表 + 黑名单管理页入口说明；如部署文档有表结构/迁移说明则同步）
- 已有: `claude_docs/versions/V1/V1.9/design.md`、本 plan

- [ ] 文档更新，检查中文无乱码
- [ ] VERSIONING.md 发版检查清单逐项核对

### Task 5: 全量回归与提交

- [ ] `python -m pytest -q` 全绿（356 基线经新增测试后 ≥ 356 passed）
- [ ] 单次提交 `feat(v1.9.0): 用户黑名单机制——精筛定级前置数据库匹配与黑名单管理页`（含代码+文档），推送 dev
