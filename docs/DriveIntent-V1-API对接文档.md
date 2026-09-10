# DriveIntent V1 API 对接文档

**版本**：1.4　**更新日期**：2026-09-08　**服务默认端口**：8000

DriveIntent 提供两个异步分析接口：**评论价值初筛**（Agent 1）与**账号画像精筛**（Agent 2）。两者均采用「提交任务 → 轮询结果」模式，适配长耗时的 LLM 分析场景。此外 V1.9.1 起提供**用户黑名单管理 API**（`/api/v1/blacklist`），供外部前端对接黑名单机制。

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


| 状态        | 含义                                                  | 终态  |
| --------- | --------------------------------------------------- | --- |
| `pending` | 已入队，等待执行                                            |     |
| `running` | 执行中（`progress` 反映进度）                                |     |
| `success` | 全部条目处理成功                                            | ✅   |
| `partial` | 部分条目失败（失败条目在 `result.results[]` 中带 `error` 字段），其余可用 | ✅   |
| `failed`  | 整单失败（`error` 有值，`result` 为 null）；服务端自动重试耗尽后进入此状态    | ✅   |




### 错误码


| HTTP 码 | 含义         | 处理建议                         |
| ------ | ---------- | ---------------------------- |
| `401`  | 认证失败       | 检查 API Key                   |
| `404`  | job_id 不存在 | 检查提交时返回的 job_id              |
| `422`  | 请求参数不合法    | 响应体含 Pydantic 校验明细，检查必填字段与类型 |
| `500`  | 服务内部错误     | 重试 2-3 次，持续失败联系服务方           |




### 建议批次大小

评论初筛 50-200 条/批，账号精筛 20-50 个/批。

---



## 4. Agent 1：评论价值初筛

过滤水军刷屏、广告引流、无实质内容的评论，保留有潜在价值的真实用户评论。

### 提交

`POST /api/v1/comment-screening`

请求体 `comments` 数组，每个元素：


| 字段                   | 类型      | 必填  | 说明                                                                          |
| -------------------- | ------- | --- | --------------------------------------------------------------------------- |
| `comment_id`         | String  | 是   | 评论唯一标识                                                                      |
| `video_title`        | String  | 是   | 视频标题                                                                        |
| `video_author`       | String  | 是   | 视频作者昵称                                                                      |
| `video_author_fans`  | Integer | 否   | 作者粉丝数（缺省 0）                                                                 |
| `video_metrics`      | Object  | 否   | 视频热度：`like_count` / `comment_count` / `share_count` / `collect_count`（缺省 0） |
| `comment_content`    | String  | 是   | 评论文本                                                                        |
| `comment_author`     | String  | 是   | 评论账号昵称                                                                      |
| `comment_author_uid` | String  | 是   | 评论账号唯一标识                                                                    |
| `comment_time`       | String  | 是   | 评论时间（ISO 8601）                                                              |
| `comment_like_count` | Integer | 否   | 评论获赞数（缺省 0）                                                                 |


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


| 字段                    | 类型             | 说明                                                                 |
| --------------------- | -------------- | ------------------------------------------------------------------ |
| `comment_id`          | String         | 对应输入的评论 ID                                                         |
| `passed`              | Boolean        | 是否通过初筛                                                             |
| `filter_type`         | String | null  | 评论分类结果（枚举见下表）；该条处理失败时为 `null`                                      |
| `is_car_owner`        | Boolean | null | 是否车主：有明确证据表明发布者大概率已购车（已下单/下大定也算），**不要求**是我方在售车型；该条处理失败时为 `null`    |
| `has_purchase_intent` | Boolean | null | 购车意向：是否表达了任何买车相关倾向（本人意向，**不要求**指向我方在售车型）；该条处理失败时为 `null`           |
| `filter_reason`       | String | null  | filter_type 的纯文本补充说明，V1.3 起恒为 null（保留字段，对接方无需解析）                   |
| `analysis`            | String         | AI 分析说明                                                            |
| `processed_at`        | String         | 处理时间戳                                                              |
| `error`               | String | null  | 该条处理失败时的错误信息（正常为 null；有值时 `passed` 恒为 false，整单 status 为 `partial`） |


`filter_type` 枚举与 `passed` 对应关系（V1.3 起严格一一对应）：


| filter_type          | 含义       | passed  |
| -------------------- | -------- | ------- |
| `genuine_user`       | 潜在客户     | `true`  |
| `no_purchase_intent` | 无购车意向    | `false` |
| `bot_spam`           | 批量刷屏水军   | `false` |
| `marketing_account`  | 营销号/广告引流 | `false` |
| `noise`              | 无实质内容    | `false` |
| `off_topic`          | 与汽车无关    | `false` |


**V1.3 契约变更说明**（相对 V1.2.1）：

- 每条结果新增 `is_car_owner`、`has_purchase_intent` 两个独立布尔字段，Agent 2 账号结果同步新增（见 Agent 2 节）。
- **移除** `model_mismatch` / `existing_owner` / `ordered_owner` 三个枚举值：初筛不再考虑车型匹配；车主状态改由独立字段 `is_car_owner` 表达。
- `passed` 与 `filter_type` 恢复严格一一对应，不再有 `model_mismatch` 这种 `passed=true` 的标记型例外。
- 车主评论不再一刀切过滤：车主若表达增换购/处置意向则 `has_purchase_intent=true` 并通过初筛。
- 无购车意向的非车主若表达兴趣/赞美可通过初筛（`genuine_user` + `has_purchase_intent=false`），对接方可据两布尔字段将其识别为 B 级弱线索。
- 初筛与画像分析均会识别"非本人意向"（替他人问询、怂恿他人购买、营销推广口吻），不作为本人购车信号或予以降级。
- 请求侧（入参）无变化。

---



## 5. Agent 2：账号画像精筛

对账号做深度画像分析（结合主页截图与历史评论），判断线索价值并输出意向等级。

### 提交

`POST /api/v1/profile-analysis`

请求体 `accounts` 数组，每个元素：


| 字段                            | 类型     | 必填  | 说明                            |
| ----------------------------- | ------ | --- | ----------------------------- |
| `account_uid`                 | String | 是   | 账号唯一标识                        |
| `account_name`                | String | 是   | 账号昵称                          |
| `account_douyin_id`           | String | 否   | 抖音号                           |
| `account_homepage_screenshot` | String | 否   | 主页截图，**URL 或 Base64** 均可；可传空串 |
| `comment_history`             | Array  | 否   | 历史评论列表，元素见下                   |


`comment_history` 元素：


| 字段                   | 类型      | 必填  | 说明             |
| -------------------- | ------- | --- | -------------- |
| `video_title`        | String  | 是   | 评论所在视频标题       |
| `comment_content`    | String  | 是   | 评论内容           |
| `comment_time`       | String  | 是   | 评论时间（ISO 8601） |
| `comment_like_count` | Integer | 否   | 评论获赞数（缺省 0）    |


**降级规则**：

- `account_homepage_screenshot` 为空或识别失败 → 仅依赖评论历史分析，`value_score` 降 10-15 分（不低于等级区间下界）。
- `comment_history` 为空 → 无法画像，直接返回 `has_value=false`。



### 结果（轮询响应中的 `result.results[]`）

与输入 accounts **一一对应、顺序一致**，每个元素：


| 字段                    | 类型             | 说明                                                   |
| --------------------- | -------------- | ---------------------------------------------------- |
| `account_uid`         | String         | 对应输入的账号 UID                                          |
| `has_value`           | Boolean        | 是否有线索价值                                              |
| `intent_level`        | String | null  | 意向等级：`"高"` / `"中"` / `"低"`（仅 `has_value=true`）       |
| `intent_level_code`   | String | null  | 等级代码：`"high"` / `"medium"` / `"low"`                 |
| `value_score`         | Integer | null | 价值评分 0-100（仅 `has_value=true`）                       |
| `is_car_owner`        | Boolean | null | 是否车主（综合该账号全部历史评论与主页画像判定，口径同 Agent 1）；该条处理失败时为 `null` |
| `has_purchase_intent` | Boolean | null | 购车意向（综合判定，口径同 Agent 1）；该条处理失败时为 `null`               |
| `intent_models`       | ArrayString    | **V1.8.0** 意向车型：该账号**有购买意向**的车型列表（如 `["坦克300"]`）；空数组=无意向车型；该条处理失败时为 `[]` |
| `intent_model_category` | String \| null | **V1.8.0** 意向车型分类，返回**中文正式内容**：`"东风猛士系列"` / `"越野车"` / `"25-30万SUV"` / `"其他"`（分类标准与对应中文在服务端 `config/intent_categories.json` 可配，默认 A=东风猛士系列、B=越野车、C=25-30万SUV、D=其他或无意向车型）；未配置标准/处理失败时为 `null`。库内仍存码值 A/B/C/D 供内部统计，本字段仅在对外返回时映射 |
| `recommended_entry_point` | String \| null | **V1.8.1** 销售开场白建议：一句可直接使用的开场话术，利用我方车型与用户意向车型的对比或关联作为切入点，辅助下游制定销售策略；模型未输出/处理失败时为 `null` |
| `our_model_intent_level` | String \| null | **V1.10.0** 用户**对我方在售车型**的购车意向：`"高"` / `"中"` / `"低"`（在"对意向车型的意向强度"基准上，按意向车型与我方在售车型的类别/价位对比做只降不升的调整：直指我方车型不降、同类竞品降一级、不匹配降两级）；被过滤/无评论/处理失败/历史数据时为 `null` |
| `recommend_our_model` | String \| null | **V1.10.0** 最适合推荐给该用户的**我方在售车型名称**（如 `"猛士M817"`，取自服务端 `config/our_models.json`）；无意向车型/无适配车型/处理失败时为 `null` |
| `is_blacklisted`       | Boolean        | **V1.9.2** 是否被判定为黑名单用户（含确认/疑似）；非黑名单、处理失败时为 `false` |
| `blacklist_type`       | String \| null | **V1.9.2** 黑名单类型：`"confirmed"`（服务端黑名单库命中）/ `"营销号"`（疑似营销账号）/ `"虚假账号"`（疑似虚假账号）；非黑名单、处理失败时为 `null` |
| `blacklist_reason`     | String \| null | **V1.9.2** 黑名单判断理由（中文，引用具体证据）；非黑名单、处理失败时为 `null` |
| `profile_tags`        | ArrayString    | 账号画像标签，如 `["已购车主", "智驾关注"]`                          |
| `profile_summary`     | String         | 账号画像摘要（150-300 字）                                    |
| `analysis`            | String         | AI 分析过程说明（400-600 字）                                 |
| `processed_at`        | String         | 处理时间戳                                                |
| `error`               | String | null  | 该条处理失败时的错误信息（正常为 null）                               |


**意向等级与分数区间**：


| 等级代码     | 中文  | 分数区间   | 说明                       |
| -------- | --- | ------ | -------------------------- |
| `high`   | 高   | 70-92  | 含内部 H（85-92）与 A（70-77）两级   |
| `medium` | 中   | 50-60  | 对应内部 B 级                |
| `low`    | 低   | 40-45  | 对应内部 C 级（V1.7.3 起对外）      |

> V1.7.3 起，内部 H/A/B/C 四档与对外 high/medium/low 三档为多对一映射：
> H、A → 高，B → 中，C → 低。各内部等级的价值分基准/区间下界未变，
> 故上表分数区间为各档实际可输出的分数范围。

> **V1.9.0 黑名单说明**：命中服务端黑名单的账号（`account_douyin_id` 已列入
> `blacklisted_user` 表）在精筛处理前即被零 LLM 短路，直接输出"黑名单用户"——
> `has_value=false`，`intent_level` / `intent_level_code` / `value_score` 为 `null`，
> `is_car_owner` / `has_purchase_intent` 为 `false`，`analysis` 文本含
> "该账号…已列入黑名单…"字样，`error` 为 `null`。其余字段与内容同未命中时一致
> （该账号不参与后续 LLM 流水线，故无定级/复核/润色叙述）。黑名单经管理页
> `/blacklist` 维护。
>
> **V1.9.2 疑似黑名单说明**：精筛的"无效用户过滤"节点（Agent2 定级前一次独立 LLM
> 调用）同时识别**疑似营销号** / **疑似虚假账号**两类疑似黑名单账号——综合该账号
> 主页截图画像（昵称/简介/认证/粉丝数/获赞数/作品数等）与全部评论内容判断（规则见
> `claude_docs/versions/V1/V1.9/v1.9.2-design.md`），命中即直接输出、不进后续
> 定级流程：`is_blacklisted=true`，`blacklist_type` 分别取 `"营销号"` / `"虚假账号"`，
> `blacklist_reason` 给出中文理由，`has_value=false`。**对接方如需在拉黑异常账号前
> 参考自动识别结果，可依这三字段判断；`is_blacklisted=true` 时建议以人工复核后再
> 正式拉黑**（该判定基于 LLM，误判时宁放过勿误杀）。确认黑名单与疑似黑名单字段
> 口径一致：均 `is_blacklisted=true`，确认命中的 `blacklist_type` 为 `"confirmed"`。




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

调整过程体现在返回的 `analysis` 中，其分析过程包含"意向车型与在售车型匹配度"段落。**接口字段结构不变**，对接方无需改动解析逻辑。

### V1.8.0 行为变化：撤销匹配调级，新增意向车型识别与分类字段

自 V1.8.0 起：

1. **撤销 V1.2.1 引入的"在售车型匹配度调整"**：车型匹配阶段保留（识别+分类），
   但匹配结果**不再参与评级升降**——评级仅由"评论基线 → 主页画像有限上调 →
   独立复核"决定。如何依据意向车型调整线索优先级由下游应用节点自行决定。
2. **新增两个输出字段**（纯增量，既有字段与结构不变）：
   - `intent_models`：该账号有购买意向的车型列表（严格基于评论证据综合判定，
     提及≠意向；空数组=无意向车型）；
   - `intent_model_category`：意向车型四档分类，对外返回**中文正式内容**
     `"东风猛士系列"`/`"越野车"`/`"25-30万SUV"`/`"其他"`（多款意向车型取最优档；
     分类标准与对应中文在服务端 `config/intent_categories.json` 可配，默认
     A=东风猛士系列、B=越野车、C=25-30万SUV、D=其他或无意向车型；
     未配置标准时为 `null`）。库内仍以码值 A/B/C/D 落库，本字段仅在对外
     返回时按配置映射，供内部审计与统计使用。

对接方如不消费新字段可忽略，无需改动既有解析逻辑（注意：本字段值为中文而非
码值，如需按档位过滤请直接匹配中文文本）。

### V1.8.1 变化：新增销售开场白建议字段

自 V1.8.1 起，账号画像精筛结果新增输出字段 `recommended_entry_point`
（纯增量，既有字段与结构不变）：定级分析节点生成的一句销售开场白建议，
基于该用户的意向车型、关注点与我方车型的关联点拟写，供下游应用辅助制定
销售策略。模型未输出、历史数据或该条处理失败时为 `null`。
对接方如不消费该字段可忽略，无需改动既有解析逻辑。

### V1.9.0 行为变化：黑名单机制

自 V1.9.0 起，Agent 2（账号画像精筛）在处理每账号前，先对 `account_douyin_id`
（抖音号）做一次**零 LLM** 的黑名单匹配：

- 命中服务端 `blacklisted_user` 表 → 直接输出"黑名单用户"（`has_value=false`，
  其余等级/评分字段为 `null`，`analysis` 含"已列入黑名单"字样，见上文结果字段
  说明），**不调用识图 / 无效用户过滤 / 定级 / 复核 / 润色任何 LLM 节点**；
- 未命中（或 `account_douyin_id` 缺省/为空）→ 照常走完整画像流水线。

黑名单由服务方通过管理页 `/blacklist` 维护（批量录入 / 列表 / 逐条删除）。
**对外契约零新增字段**：下游仅凭 `has_value=false` + `analysis` 文本即识别
"黑名单用户"，无需改动既有解析逻辑。

### V1.10.0 行为变化：新增对我方在售车型购车意向两字段

自 V1.10.0 起，账号画像精筛（Agent2）在分析该用户对其**意向车型**的意向强度之外，
额外分析该用户**对我方在售车型**的购车意向，新增两个输出字段（纯增量，既有字段与
结构不变）：

- `our_model_intent_level`：`"高"` / `"中"` / `"低"`。以该用户对意向车型的意向强度
  为基准，按"意向车型与我方在售车型"的对比做只降不升的调整——意向车型即我方在售
  车型则不降级；为同类且价位接近的竞品则降一级；类别或价位不匹配则降两级（默认
  低意向）；识别不出意向车型则为低意向。该字段**不参与等级（intent_level）调整**，
  仅供销售人员判断"该用户买我们车的可能性"。
- `recommend_our_model`：最适合推荐给该用户的我方在售车型名称（如 `"猛士M817"`），
  取自服务端 `config/our_models.json` 车型清单；服务端会校验模型输出，不在清单内
  的车型名一律输出 `null`。

分析过程体现在返回的 `analysis` 第三段"目标车型与我方车型匹配度"中（含对我方车型
购车意向与推荐车型的结论）。对接方如不消费新字段可忽略，无需改动既有解析逻辑。

---

## 5.5 用户黑名单管理 API（V1.9.1 新增）

自 V1.9.1 起，黑名单机制对外提供一套增删查接口（`/api/v1/blacklist`），供外部前端
对接黑名单的录入、查询与删除。与既有 Agent API 同层：JSON、UTF-8、`Authorization: Bearer`。

**与 Agent API 的区别**：黑名单接口为**同步**（非「提交→轮询」模式），直接返回结果。

### 5.5.1 查询黑名单（分页列表）

`GET /api/v1/blacklist`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `page` | int | 1 | 页码，从 1 起；<1 按 1 处理 |
| `page_size` | int | 20 | 每页条数；上限 100（超限截断） |
| `q` | string | 空 | 可选；对 `douyin_id` / `nickname` / `remark` 做子串匹配（不区分大小写） |

**响应 `200`**：

```json
{
  "items": [
    { "blacklist_id": 1, "douyin_id": "79373130119",
      "nickname": "张三", "remark": "广告号",
      "created_at": "2026-09-08T10:00:00+08:00" }
  ],
  "total": 1, "page": 1, "page_size": 20
}
```

- `items` 按 `created_at` 倒序（新在前）。
- `total` 为满足条件的**总条数**（不是本页条数）。
- `nickname` / `remark` 可空（`null`）；`blacklist_id` 为删除接口所需的记录标识。

### 5.5.2 批量加入黑名单

`POST /api/v1/blacklist`

请求体：

```json
{ "douyin_ids": ["79373130119", "79373130120"],
  "nickname": "批量昵称", "remark": "批量备注" }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `douyin_ids` | `array<string>` | 是 | 至少 1 条；每项为纯数字字符串（合法抖音号）。空数组返回 `422`。 |
| `nickname` | string | 否 | 应用到本批入库的每条记录 |
| `remark` | string | 否 | 同上 |

**响应 `200`**：

```json
{ "added": 2, "skipped": 0, "invalid": 0 }
```

- `added`：新增入库条数；`skipped`：库内已存在（幂等跳过）；`invalid`：非法（非纯数字/空串）未入库。
- 请求体含非法项时**不整体拒绝**：合法项照常入库，非法项计数返回，由调用方决策。
- 同批重复出现的合法 ID 只首次入库、其余计 `skipped`。

### 5.5.3 删除黑名单

`DELETE /api/v1/blacklist/{blacklist_id}`

- 命中 → `204`（无响应体）。
- 未命中 → `404` `{"detail": "黑名单记录不存在"}`。

`blacklist_id` 取「查询接口」返回的 `blacklist_id`（表 id），不直接用 `douyin_id` 作删除键。

### 5.5.4 错误码

沿用公共错误码（`401` 鉴权、`422` 参数不合法、`500` 服务内部错误）；`404` 仅出现于
删除未命中。

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