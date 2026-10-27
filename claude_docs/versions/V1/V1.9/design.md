# V1.9.0 设计：用户黑名单机制

> 版本：V1.9.0 | 日期：2026-09-07

## 1. 背景与目标

在"用户精筛定级"（Agent2）工作流中，有一批抖音用户在系统外部被人工识别为
非潜客（如营销号等）。当前这批用户每次提交精筛仍会走完整 LLM 流水线
（识图 → 无效用户过滤 → 定级 → 复核 → 润色），既浪费调用成本，又可能在
LLM 判断下得到与人工结论相悖的高价值评级。

本版本建立并维护一张"黑名单用户表"：

1. 精筛任务对待定级用户先做一次**黑名单匹配**（数据库匹配，不调 LLM）；
2. 匹配成功 → 直接输出"黑名单用户"，**不进后续 HABC 定级流程**。

## 2. 范围决策（已与需求方确认）

| 决策点 | 结论 |
|---|---|
| 接入范围 | **仅对外 API 路径**（`POST /api/v1/profile-analysis`）。V0（8000 端口）自 2026-07-20 已停更，其账号来自 `platform_user` 表、无独立 `account_douyin_id` 列，无法可靠匹配——本期不接入，记为已知未覆盖。 |
| 命中输出口径 | 复用既有"无效用户过滤"同款模式：确定性 `lead_grade=C`、`is_valid_lead=False`，**不调任何 LLM**（识图/过滤/定级/复核/润色全部跳过）；对外 `has_value=false`；内部带标记 `filter_category="blacklisted"` 与说明文本。 |
| 对外契约 | **零新增字段**（纯增量不适用，直接不变）。下游通过 `has_value=false` + `analysis_text` 文本即可识别"黑名单用户"。 |
| 匹配主体 | `account_douyin_id`（抖音号），**全量精确匹配**。缺省/为空 → 跳过该账号匹配，照常走流水线。 |
| 管理页录入 | 文本框支持**批量粘贴**（逗号/换行分隔）入库 + 列表展示 + 逐条删除。 |

## 3. 数据模型（新表 `blacklisted_user`）

| 列 | 类型 | 说明 |
|---|---|---|
| id | INT 自增主键 | |
| douyin_id | VARCHAR(64)，UNIQUE 索引 | 匹配主体，全量精确匹配（如 `79373130119`） |
| nickname | VARCHAR(255)，可空 | 备注入库时的昵称/备注用途 |
| remark | VARCHAR(255)，可空 | 备注（可选） |
| created_at | DATETIME | 默认 `utcnow` |

**建表方式**：由 `init_db()` 的 `Base.metadata.create_all` 自动创建（与既有表同机制），
**无需迁移脚本**。模型定义在 `app/models/blacklist.py`，并在 `app/models/__init__.py` 注册。

> 说明：新表由 ORM create_all 负责，不存在"为已有库补列"的迁移需求；
> 故不新增 `scripts/` 迁移脚本。部署侧仅需重启服务即在测试库建表。

## 4. 匹配时机与实现（`app/api/agent2.py`）

### 4.1 调用方注入

`run_profile_analysis` 新增一个可选参数 `blacklist: set[str] | frozenset[str] | None = None`
（本轮黑名单命中集合，由 API Worker 在作业级一次性批量读入）。

- 缺省 `None` → 不做任何黑名单检查，行为与现状**完全一致**（回归安全）。
- 传入命中集合 → 每账号头部短路检查。

### 4.2 per-account 短路

```text
for idx, account in enumerate(request.accounts):
    douyin_id = account.account_douyin_id
    if blacklist and douyin_id and douyin_id in blacklist:
        → 直接构造 UserLeadResult(lead_grade="C", is_valid_lead=False,
             filter_category="blacklisted", analysis_text="…已列入黑名单…")
        → 跳过识图 / run_user_filter / analyze_account / apply_review / apply_polish
        → 照常走 map_profile_result → 对外 has_value=false
        → grade_sink 补 "C"（与 results 下标对齐，V1.7.3 审计）
```

- 黑名单命中**优先于** `has_comments` 判空分支：无评论/无截图的账号若命中也输出
  "黑名单用户"，保证标记可见、可解释。

### 4.3 无 LLM 的确定性构造

`UserLeadResult` 关键字段：`lead_grade="C"`、`is_valid_lead=False`、
`filter_category="blacklisted"`、`filter_reason`（说明来自黑名单）+ `analysis_text`
（对外展示文本，含"黑名单用户"字样）。`build_filtered_lead_result` 的既有模式可复用，
但黑名单是**无 LLM 的确定性节点**，与过滤节点（LLM 判定）不同——故单独构造，
不依赖 `UserFilterResult`。

### 4.4 数据库会话纪律

黑名单读是**每个作业一次**的批量 `IN` 查询，放入 `asyncio.to_thread` 执行
（V1.4.4 / V1.4.5 纪律：同步 DB IO 不得进事件循环）。worker 在 `_execute` 之前
经线程池读入命中集合，LLM 期间不持有连接。

- **fail-open**：黑名单查询异常 → 记 warning、按空命中放行，不阻断作业。
- 读入发生在作业级（整批账号一个集合），不是 per-account，避免逐账号 DB 查询。

## 5. 数据访问层（`app/services/blacklist.py` 新建）

| 函数 | 职责 |
|---|---|
| `load_blacklist_matches(session, ids: Iterable[str]) -> set[str]` | 批量命中查询（worker 作业级用；`ids` 为空返回空集） |
| `list_blacklist(session) -> list[BlacklistedUser]` | 管理页全量列表（`created_at` 倒序） |
| `add_blacklist(session, douyin_ids: list[str], nickname=None, remark=None) -> dict` | 批量入库；已存在跳过（幂等）；返回 `{added, skipped, invalid}` |
| `delete_blacklist(session, record_id: int) -> bool` | 删除 |

- 所有写入走 SQLAlchemy ORM + 参数化；非法输入（非纯数字、空串）在服务层归一/拒绝。
- 表由模型注册，无独立迁移。

## 6. 管理页（黑名单子页面）

- 路由：`app/web/blacklist.py` 新建 `blacklist_router`，在 `app/main.py` 注册。
  - `GET /blacklist`：页面（录入表单 + 列表）。
  - `POST /api/blacklist`：批量提交。表单字段 `douyin_ids`（逗号/换行分隔）、
    `nickname`、`remark`（可选）。服务端解析、去重、仅收纯数字 19 位内抖音号；
    返回 `{added, skipped, invalid}` 供页面提示。
  - `DELETE /api/blacklist/{id}`：逐条删除。
- 模板：`app/templates/blacklist.html` 新建，`app/templates/base.html` 导航加"黑名单"链接
  （`/blacklist`，active=true）。样式沿用现有页面（`.card`/`.table-wrap` 等）。
- 安全：参数化查询；内部管理页**不做额外鉴权**（与 `/audit` 同层，均为内网管理面）。

## 7. 对外行为一致性

| 场景 | 对外表现 |
|---|---|
| 命中黑名单 | `has_value=false`、`intent_level/intent_level_code/value_score=null`、`is_car_owner/has_purchase_intent=false`、`analysis_text` 含"已列入黑名单"说明、`error=null` |
| 未命中（含无 douyin_id / 黑名单未配置） | 与现状完全一致（走完整流水线） |

`map_profile_result` 既有 `has_value=false` 分支已正确产出上述形态，无需改映射逻辑。

## 8. 版本化资产

**无 Prompt / Skill 变更**（黑名单是纯代码层、零 LLM 节点）：不新增/修改 Prompt 文件、
不升 `prompt_version` / Skill `version`、不改 `SKILL_VERSIONS`。`OVERVIEW.md` 能力快照与
变更索引照规范更新。

## 9. 明确不做（YAGNI）

- 不接入 V0 流水线（8000 端口、已停更、无 `account_douyin_id`）。
- 不新增对外契约字段（命中仅通过 `has_value=false` + `analysis_text` 表达）。
- 不为黑名单做过期时间 / 禁用状态 / 分类标签。
- 不做鉴权强化（内部管理面，与 `/audit` 同层）。
- 不做批量导出 / 导入文件上传。
- 不接 LLM 判定黑名单（黑名单必须是确定性人工来源）。

## 10. 测试要点

1. **服务层**：`load_blacklist_matches`（命中/未命中/空候选）、`add_blacklist`
   （新增/重复跳过/非法 ID 归一）、`list_blacklist`（倒序）、`delete_blacklist`。
2. **集成（agent2）**：
   - 注入命中集合账号 → 断言 **零 LLM 调用**（provider 未消费任何响应）、
     `has_value=false`、`analysis_text` 含"黑名单"、`grade_sink` 含 `"C"`；
   - 未命中账号走完整流水线（调用次数与现状一致）；
   - `blacklist=None` 时行为与现状完全一致（回归）；
   - 黑名单读异常 fail-open。
3. **Web**：`GET /blacklist` 渲染、`POST /api/blacklist`（新增/非法/重复）、
   `DELETE /api/blacklist/{id}`。
4. **回归**：全量 `python -m pytest -q` 保持全绿（当前 356 passed）。
