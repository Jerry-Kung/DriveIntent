# DriveIntent V1 API 对接文档

**版本**：1.2　**更新日期**：2026-07-28　**服务默认端口**：8000

DriveIntent 提供两个异步分析接口：**评论价值初筛**（Agent 1）与**账号画像精筛**（Agent 2）。两者均采用「提交任务 → 轮询结果」模式，适配长耗时的 LLM 分析场景。

---

## 1. 快速开始

```
1. POST /api/v1/comment-screening      提交评论批次，得到 job_id
2. GET  /api/v1/jobs/{job_id}          轮询（建议间隔 2-5 秒），直到 status 为终态
3. 从响应的 result.results[] 读取每条结果
```

## 2. 认证

除 `/health` 外，所有接口需携带请求头：

```
Authorization: Bearer <API_KEY>
```

API Key 由服务方分配。认证失败返回 `401`。

## 3. 通用约定

- 请求与响应均为 `application/json`，UTF-8 编码。
- 时间戳统一为 ISO 8601 带时区偏移（东八区），如 `"2026-07-23T15:30:00+08:00"`。
- 提交接口成功返回 `202`，响应体：

```json
{ "job_id": "b3f1c2d4-...", "status": "pending", "type": "comment_screening" }
```

### 任务状态（status）

| 状态 | 含义 | 终态 |
|------|------|:---:|
| `pending` | 已入队，等待执行 | |
| `running` | 执行中（`progress` 反映进度） | |
| `success` | 全部条目处理成功 | ✅ |
| `partial` | 部分条目失败（失败条目在 `result.results[]` 中带 `error` 字段），其余可用 | ✅ |
| `failed` | 整单失败（`error` 有值，`result` 为 null）；服务端自动重试耗尽后进入此状态 | ✅ |

### 错误码

| HTTP 码 | 含义 | 处理建议 |
|--------|------|---------|
| `401` | 认证失败 | 检查 API Key |
| `404` | job_id 不存在 | 检查提交时返回的 job_id |
| `422` | 请求参数不合法 | 响应体含 Pydantic 校验明细，检查必填字段与类型 |
| `500` | 服务内部错误 | 重试 2-3 次，持续失败联系服务方 |

### 建议批次大小

评论初筛 50-200 条/批，账号精筛 20-50 个/批。

---

## 4. Agent 1：评论价值初筛

过滤水军刷屏、广告引流、无实质内容的评论，保留有潜在价值的真实用户评论。

### 提交

`POST /api/v1/comment-screening`

请求体 `comments` 数组，每个元素：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `comment_id` | String | 是 | 评论唯一标识 |
| `video_title` | String | 是 | 视频标题 |
| `video_author` | String | 是 | 视频作者昵称 |
| `video_author_fans` | Integer | 否 | 作者粉丝数（缺省 0） |
| `video_metrics` | Object | 否 | 视频热度：`like_count` / `comment_count` / `share_count` / `collect_count`（缺省 0） |
| `comment_content` | String | 是 | 评论文本 |
| `comment_author` | String | 是 | 评论账号昵称 |
| `comment_author_uid` | String | 是 | 评论账号唯一标识 |
| `comment_time` | String | 是 | 评论时间（ISO 8601） |
| `comment_like_count` | Integer | 否 | 评论获赞数（缺省 0） |

**请求示例**：

```json
{
  "comments": [
    {
      "comment_id": "cm_7123456789012345678",
      "video_title": "试驾体验｜这台车的智驾系统真的惊艳",
      "video_author": "@老王说车",
      "video_author_fans": 2865000,
      "video_metrics": { "like_count": 125000, "comment_count": 3428,
                         "share_count": 8900, "collect_count": 12300 },
      "comment_content": "这车智驾确实牛，我上个月刚提的这款",
      "comment_author": "用户_7823",
      "comment_author_uid": "MS4wLjABAAAA...",
      "comment_time": "2026-07-19T14:23:00+08:00",
      "comment_like_count": 234
    }
  ]
}
```

### 结果（轮询响应中的 `result.results[]`）

与输入 comments **一一对应、顺序一致**，每个元素：

| 字段 | 类型 | 说明 |
|------|------|------|
| `comment_id` | String | 对应输入的评论 ID |
| `passed` | Boolean | 是否通过初筛 |
| `filter_type` | String \| null | 评论分类结果（枚举见下表）；该条处理失败时为 `null` |
| `filter_reason` | String \| null | `filter_type` 的**纯文本补充说明**，仅在枚举本身不足以说明时有值（当前仅 `model_mismatch` 时携带具体不匹配原因） |
| `analysis` | String | AI 分析说明 |
| `processed_at` | String | 处理时间戳 |
| `error` | String \| null | 该条处理失败时的错误信息（正常为 null；有值时 `passed` 恒为 false，整单 status 为 `partial`） |

`filter_type` 枚举与 `passed` 对应关系：

| filter_type | 含义 | passed | filter_reason |
|---|---|---|---|
| `genuine_user` | 真实普通用户 | `true` | `null` |
| `model_mismatch` | 意向车型与我方在售车型严重不匹配 | `true` | 具体不匹配原因文本，如"价位不匹配（视频车型约 10 万元，与我方在售车型价位差距过大）" |
| `existing_owner` | 已购车主 | `false` | `null` |
| `ordered_owner` | 已下大定车主 | `false` | `null` |
| `bot_spam` | 批量刷屏水军 | `false` | `null` |
| `marketing_account` | 营销号/广告引流 | `false` | `null` |
| `noise` | 无实质内容 | `false` | `null` |
| `off_topic` | 与汽车无关 | `false` | `null` |

**V1.1.1 契约变更说明**（相对 V1.1）：
- `filter_reason` 不再是 `filter_type` 的固定枚举文案，改为纯文本补充说明；做分支判断请依据 `filter_type`。
- 移除 `intent_strength` / `downgrade_applied` / `downgrade_reason` 三个字段：降级事实由 `filter_type = "model_mismatch"` 标识，降级原因并入 `filter_reason`。
- `model_mismatch` 的评论 `passed` 仍为 `true`——降级是提示性标记而非过滤，是否降权由对接方决定。

**降级功能的服务端前提**：意向降级依赖服务端配置的"我方在售车型"清单（`config/our_models.json`，由服务方维护，见部署文档）。服务端未配置该文件或关闭降级开关时，不会产生 `model_mismatch` 分类——对接方无需感知配置状态，字段契约不变。

---

## 5. Agent 2：账号画像精筛

对账号做深度画像分析（结合主页截图与历史评论），判断线索价值并输出意向等级。

### 提交

`POST /api/v1/profile-analysis`

请求体 `accounts` 数组，每个元素：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `account_uid` | String | 是 | 账号唯一标识 |
| `account_name` | String | 是 | 账号昵称 |
| `account_douyin_id` | String | 否 | 抖音号 |
| `account_homepage_screenshot` | String | 否 | 主页截图，**URL 或 Base64** 均可；可传空串 |
| `comment_history` | Array | 否 | 历史评论列表，元素见下 |

`comment_history` 元素：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `video_title` | String | 是 | 评论所在视频标题 |
| `comment_content` | String | 是 | 评论内容 |
| `comment_time` | String | 是 | 评论时间（ISO 8601） |
| `comment_like_count` | Integer | 否 | 评论获赞数（缺省 0） |

**降级规则**：

- `account_homepage_screenshot` 为空或识别失败 → 仅依赖评论历史分析，`value_score` 降 10-15 分（不低于等级区间下界）。
- `comment_history` 为空 → 无法画像，直接返回 `has_value=false`。

### 结果（轮询响应中的 `result.results[]`）

与输入 accounts **一一对应、顺序一致**，每个元素：

| 字段 | 类型 | 说明 |
|------|------|------|
| `account_uid` | String | 对应输入的账号 UID |
| `has_value` | Boolean | 是否有线索价值 |
| `intent_level` | String \| null | 意向等级：`"高"` / `"中"` / `"低"`（仅 `has_value=true`） |
| `intent_level_code` | String \| null | 等级代码：`"high"` / `"medium"` / `"low"` |
| `value_score` | Integer \| null | 价值评分 0-100（仅 `has_value=true`） |
| `profile_tags` | Array\<String\> | 账号画像标签，如 `["已购车主", "智驾关注"]` |
| `profile_summary` | String | 账号画像摘要（150-300 字） |
| `analysis` | String | AI 分析过程说明（300-500 字） |
| `processed_at` | String | 处理时间戳 |
| `error` | String \| null | 该条处理失败时的错误信息（正常为 null） |

**意向等级与分数区间**：

| 等级代码 | 中文 | 分数区间 | 典型特征 |
|---------|------|---------|---------|
| `high` | 高 | 85-100 | 明确购车意向 / 决策末期 / 已购车主（换购潜力） |
| `medium` | 中 | 70-84 | 正在对比车型 / 决策中期 |
| `low` | 低 | 50-69 | 初步了解 / 观望 / 决策前期 |

### V1.1 行为变化：评级考量我方车型匹配度

自 V1.1 起，账号画像分析会注入服务端配置的"我方在售车型"摘要（品牌、车型、价位、品类、目标人群），模型评定意向等级与价值分数时，会把**该用户与我方车型的匹配度**作为考量维度之一，并体现在 `analysis` / `profile_summary` 文本中。**输出字段结构不变**，对接方无需改动解析逻辑；服务端未配置车型清单时行为与 V1.0 一致。

### V1.2 行为变化：主页截图正式纳入评级

自 V1.2 起，`account_homepage_screenshot` 正式参与分析：服务端先对截图做识别，
归纳出结构化用户画像（内容主题、消费能力、兴趣标签、年龄性别、IP 属地、汽车相关性等），
再据此对**高质量线索**做有限上调——仅当基线为中/低（B/A 内部等级）且画像有直接证据
（如自驾爱好者、汽车发烧友、明确高消费信号）时，最多上调一级；画像只上调不下调，
低质量线索（C 及以下）不受画像影响。**输出字段结构不变**，对接方无需改动解析逻辑；
截图为空或识别失败时行为与 V1.1 一致（走降级路径、`value_score` 降 10-15 分）。

### V1.2.1 行为变化：评级考虑意向车型与在售车型匹配度

自 V1.2.1 起，账号画像精筛（Agent2）评级在"评论基线 → 主页画像有限上调"之间
增加**在售车型匹配度调整**环节：

- 用户意向车型直指我方在售车型且有明确购车意向 → 评级可上调一级；
- 意向车型为同类/竞品（品类与价位接近）→ 不调整；
- 意向车型部分相关（品类或价位仅一项接近）→ 降一级；
- 意向车型完全无关（如低价微面 vs 中高端越野）→ 降两级；
- 识别不出意向车型 → 不调整。

调整过程体现在返回的 `analysis`（分析过程含"意向车型与在售车型匹配度"段落）
与 `profile_summary` 中。**接口字段结构不变**，对接方无需改动解析逻辑。

---

## 6. 轮询接口

`GET /api/v1/jobs/{job_id}`

**响应示例**：

```json
{
  "job_id": "b3f1c2d4-...",
  "type": "comment_screening",
  "status": "success",
  "progress": { "total": 100, "done": 100 },
  "result": { "results": [ ... ] },
  "error": null,
  "created_at": "2026-07-23T15:30:00+08:00",
  "finished_at": "2026-07-23T15:33:20+08:00"
}
```

`result` 仅在 `status` 为 `success` / `partial` 时有值，结构见各 Agent 的「结果」章节。

## 7. 健康检查

`GET /health`（无需认证）→ `{ "status": "ok" }`

---

## 8. 完整调用示例（Python）

```python
import time
import requests

BASE = "http://<host>:8000"
HEADERS = {"Authorization": "Bearer your_api_key"}

# 1. 提交
resp = requests.post(f"{BASE}/api/v1/comment-screening",
                     headers=HEADERS, json={"comments": comments})
job_id = resp.json()["job_id"]

# 2. 轮询
while True:
    job = requests.get(f"{BASE}/api/v1/jobs/{job_id}", headers=HEADERS).json()
    if job["status"] in ("success", "partial", "failed"):
        break
    time.sleep(3)

# 3. 处理结果
if job["status"] == "failed":
    raise RuntimeError(job["error"])
for r in job["result"]["results"]:
    if r.get("error"):
        print(f"{r['comment_id']} 处理失败: {r['error']}")   # partial 场景
    elif r["passed"]:
        print(f"{r['comment_id']} 通过初筛")
```

---

**反馈联系**：DriveIntent 服务团队
