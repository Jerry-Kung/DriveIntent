# DriveIntent V1.4 设计文档

**文档版本：** 1.4
**日期：** 2026-08-03
**状态：** 已评审通过
**主题：** 后端审计——任务量明细统计 + LLM tokens 消耗明细统计 + 内置展示页面

---

## 1. 目标与范围

V1.4 提供后端审计能力，让运营者随时掌握服务运行情况：

1. **API 任务调用量明细统计**：按东八区自然天/小时为颗粒度，统计两个异步 API（评论初筛 `comment-screening`、画像分析 `profile-analysis`）的任务接收量与处理完成量（含成功/部分成功/失败细分）。
2. **LLM 调用明细统计**：按东八区自然天/小时为颗粒度，统计 LLM 调用请求次数、失败次数、输入/输出 tokens 消耗、平均耗时，可按 skill 与模型名细分。
3. **结果展示**：新增内部 Web 页面 `/audit`（Jinja2 服务端渲染，与现有内部页同风格），打开/刷新即查实时数据。

**独立性原则（评审确认的核心约束）**：审计功能为**纯只读**模块，数据源全部来自业务流程既有落库（`api_job`、`llm_call_log` 两张表），不新增表、不改任何业务写路径、不加埋点。业务代码唯一被动到的位置是 `base.html` 导航栏新增一个链接。

### 1.1 统计口径（评审确认）

- **任务口径 = 异步任务**：只统计 `api_job` 表记录的任务提交与完成；`GET /api/v1/jobs/{id}` 轮询、`/health`、鉴权失败等 HTTP 请求不统计、不留痕。
- **LLM 口径 = 每次真实请求**：`llm_call_log` 由 gateway 在每次尝试（含重试、含失败）时各落一条，统计的是真实发生的每次 LLM 请求，即成本口径。
- **归因维度 = 时间 × skill × 模型**：不做 job 级 token 归因（`llm_call_log` 不加 `job_id` 字段）。
- **时区**：数据库落库为 UTC 朴素时间，所有天/小时分桶按**东八区**自然时间划分（聚合时 +8 小时转换），与对外 API 时间输出口径（`app/api/routes.py` 的 `_TZ8`）一致。

### 1.2 不做（YAGNI）

- 不记录 HTTP 请求明细（不加请求日志中间件/新表）。
- 不做 job 级 token 归因（不改 `gateway._log` 签名及调用方）。
- 不做预聚合汇总表与定时汇总任务——当前数据量级（日千行级）实时聚合毫秒级即可，未来量级上来再演进。
- 不引入图表库/JS 框架——汇总卡片 + 明细表格足够。
- 不接外部监控栈（Prometheus/Grafana）。
- 页面不加鉴权（与现有内部 Web 页面口径一致）。

---

## 2. 模块结构

| 文件 | 职责 |
|------|------|
| `app/services/audit_stats.py` | **新增**：聚合查询服务（纯函数，输入 Session + 参数，输出统计结构） |
| `app/web/audit.py` | **新增**：独立 APIRouter，`GET /audit` 页面路由 |
| `app/templates/audit.html` | **新增**：审计页模板，继承 `base.html` |
| `app/main.py` | 挂载 audit router（一行） |
| `app/templates/base.html` | 导航栏新增「审计统计」链接（一行） |
| `app/models/analysis.py` / `app/models/api_job.py` | 模型上声明新索引（见第 5 节） |
| `scripts/add_audit_indexes.py` | **新增**：存量库幂等补索引脚本 |

审计模块依赖方向：`audit.py` → `audit_stats.py` → models。业务模块零依赖审计模块。

---

## 3. 聚合服务（`app/services/audit_stats.py`）

### 3.1 接口

```python
def job_stats(db, granularity, start_utc, end_utc) -> list[dict]
    # 返回 [{bucket: "2026-08-01" | "2026-08-01 12:00", job_type,
    #        received, success, partial, failed}, ...]
    # received 按 created_at 分桶；success/partial/failed 按 finished_at 分桶

def llm_stats(db, granularity, start_utc, end_utc) -> list[dict]
    # 返回 [{bucket, skill_id, model_name, calls, errors,
    #        prompt_tokens, completion_tokens, avg_duration_ms}, ...]
    # calls 含全部记录；errors 为 error 非空的记录数

def today_summary(db) -> dict
    # 东八区今日：{jobs_received, jobs_finished, llm_calls,
    #             prompt_tokens, completion_tokens}
```

`granularity` 取值 `"day" | "hour"`。`start_utc`/`end_utc` 由路由层根据页面参数换算（东八区自然天/小时边界 → UTC）后传入，服务层只做过滤与分桶。

### 3.2 分桶实现（跨方言）

生产 MySQL、测试 SQLite，SQL 层分桶表达式按方言分派（服务内私有辅助函数，按 `db.get_bind().dialect.name` 判断）：

- **MySQL**：`DATE_FORMAT(DATE_ADD(col, INTERVAL 8 HOUR), '%Y-%m-%d')`（day）/ `'%Y-%m-%d %H:00'`（hour）
- **SQLite**：`strftime('%Y-%m-%d', datetime(col, '+8 hours'))`（day）/ `strftime('%Y-%m-%d %H:00', ...)`（hour）

以分桶表达式 + 维度列 `GROUP BY`，聚合用 `count/sum/avg`。任务的"接收"与"完成"两组指标分桶列不同（`created_at` vs `finished_at`），分两次查询后在 Python 侧按 (bucket, job_type) 合并。

### 3.3 边界口径

- 任务完成量只统计 `finished_at` 非空的记录；`pending/running` 中的任务计入接收量、不计入完成量（跑完后自然进入对应桶）。
- LLM 平均耗时对 `duration_ms` 取 `AVG`，无记录时为 0。
- tokens 合计对 `prompt_tokens`/`completion_tokens` 取 `SUM`（mock provider 落 0，合计自然为 0，不需特判）。

---

## 4. 页面与路由（`app/web/audit.py` + `audit.html`)

### 4.1 路由

`GET /audit`，查询参数：

| 参数 | 取值 | 默认 | 说明 |
|------|------|------|------|
| `granularity` | `day` / `hour` | `day` | 分桶粒度 |
| `range` | 正整数 | day→7，hour→48 | 展示最近 N 天 / N 小时，上限 day≤90、hour≤168（防误传大值拖垮查询），超限取上限 |

路由层将 `range` 换算为东八区自然边界对应的 UTC `[start, end)`（含当前未走完的天/小时桶），调用服务层三个函数，渲染模板。服务查询异常时捕获并渲染页内错误提示块（不影响其他页面，不抛 500 裸栈）。

### 4.2 页面结构（自上而下）

1. **今日汇总卡片行**（东八区今日）：任务接收数、任务完成数、LLM 调用次数、输入 tokens、输出 tokens。
2. **控制条**：粒度切换（按天/按小时）与范围输入，普通链接/表单 GET 提交，刷新页面即更新。
3. **任务量明细表**：时间桶 × 任务类型 → 接收 / 成功 / 部分成功 / 失败。时间倒序。
4. **LLM 消耗明细表**：时间桶 × skill × 模型 → 调用次数 / 失败次数 / 输入 tokens / 输出 tokens / 平均耗时(ms)。时间倒序。

空数据显示"暂无数据"空态行。样式沿用 `base.html` 既有内联 CSS（表格、卡片同现有页面风格），导航栏 `base.html` 新增「审计统计」项并支持 `active` 高亮。

---

## 5. 索引与迁移

`llm_call_log` 现状除主键外零索引，按时间聚合会全表扫描；`api_job.finished_at` 亦无索引。V1.4 补两个单列索引：

| 表 | 索引 | 用途 |
|------|------|------|
| `llm_call_log` | `ix_llm_call_created` (`created_at`) | LLM 按时间窗聚合 |
| `api_job` | `ix_api_job_finished` (`finished_at`) | 任务完成量按时间窗聚合 |

（任务接收量聚合的 `api_job.created_at` 暂不单独建索引：该表行数远小于 `llm_call_log`，且已有复合索引兜底，量级不构成问题。）

落地方式双轨：

1. **模型声明**：两个 model 的 `__table_args__` 加 `Index(...)`——全新部署 `create_all` 自动带上。
2. **存量库迁移**：`scripts/add_audit_indexes.py`，仿照 `scripts/fix_api_job_index.py` 的写法（pymysql + information_schema 幂等检查，索引已存在则跳过），部署时手动执行一次。

---

## 6. 错误处理

- 聚合查询异常：路由层捕获，页面渲染错误提示块，其余页面与业务流程不受影响。
- 审计为只读模块，不写库；查询占用连接池连接，页面为人工低频访问，不构成连接池压力。
- `gateway._log` 静默吞异常的既有行为不变——审计数据允许极端情况下少记（该局限在页面不体现，写入本设计文档备查即可）。

---

## 7. 测试

沿用现有 pytest + 内存 SQLite + TestClient 惯例：

- **`tests/test_audit_stats.py`**（服务层单测）：
  - 天/小时分桶正确性，含**时区边界用例**（UTC 16:00 后的记录应落入东八区次日桶）；
  - 任务接收量 vs 完成量分列（pending/running 只计接收）；success/partial/failed 细分；
  - LLM 按 skill × 模型分组、tokens 求和、错误计数、平均耗时；
  - 空表返回空列表 / 全零汇总。
- **`tests/test_v14_integration.py`**（版本集成测试）：
  - 造数后 TestClient 访问 `/audit`，页面 200 且含预期统计数字；
  - `granularity`/`range` 参数生效、超限截断、非法值回退默认；
  - 导航栏含审计入口；
  - 现有业务端点行为不变（冒烟）。
- **模型索引**：`create_all` 后新索引存在（并入现有 `test_models.py` 风格断言）。

---

## 8. 版本与文档

- 无 Prompt / Skill 变更，不涉及 VERSIONING.md 第 4 节资产版本号变动。
- 对外 API 契约零变化，`docs/DriveIntent-V1-API对接文档.md` 不更新。
- 发版时按 VERSIONING.md 检查清单更新 `claude_docs/versions/V1/OVERVIEW.md`（变更索引加行；能力快照补"后端审计"能力）。

---

## 9. 影响文件清单

| 文件 | 变更 |
|------|------|
| `app/services/audit_stats.py` | 新增：聚合查询服务 |
| `app/web/audit.py` | 新增：/audit 页面路由 |
| `app/templates/audit.html` | 新增：审计页模板 |
| `app/main.py` | 挂载 audit router |
| `app/templates/base.html` | 导航栏加「审计统计」 |
| `app/models/analysis.py` | `LlmCallLog` 加 `created_at` 索引声明 |
| `app/models/api_job.py` | `ApiJob` 加 `finished_at` 索引声明 |
| `scripts/add_audit_indexes.py` | 新增：存量库幂等补索引脚本 |
| `tests/test_audit_stats.py` | 新增：服务层单测 |
| `tests/test_v14_integration.py` | 新增：版本集成测试 |
| `claude_docs/versions/V1/OVERVIEW.md` | 发版时更新变更索引与能力快照 |
