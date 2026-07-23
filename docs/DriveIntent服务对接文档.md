# 线索孵化 Agent 调用说明文档

## 概述

线索孵化系统包含两个核心 Agent，用于从原始评论数据中识别和筛选高价值购车线索。两个 Agent 串行工作，形成完整的线索孵化流水线。

---

## Agent 1: 评论价值初筛

### 功能说明

对原始评论进行初步价值判断，过滤掉水军刷屏、广告引流、无实质内容的评论，仅保留有潜在价值的真实用户评论。

### 输入参数

#### `comments` (Array<CommentObject>)

原始评论列表，每个评论对象包含以下字段：

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| `comment_id` | String | 是 | 评论唯一标识 | `"cm_7123456789012345678"` |
| `video_title` | String | 是 | 视频标题 | `"试驾体验｜这台车的智驾系统真的惊艳"` |
| `video_author` | String | 是 | 视频作者昵称 | `"@老王说车"` |
| `video_author_fans` | Integer | 是 | 视频作者粉丝数 | `2865000` |
| `video_metrics` | Object | 是 | 视频热度指标 | 见下方子结构 |
| `video_metrics.like_count` | Integer | 是 | 点赞数 | `125000` |
| `video_metrics.comment_count` | Integer | 是 | 评论数 | `3428` |
| `video_metrics.share_count` | Integer | 是 | 分享数 | `8900` |
| `video_metrics.collect_count` | Integer | 是 | 收藏数 | `12300` |
| `comment_content` | String | 是 | 评论文本内容 | `"这车智驾确实牛，我上个月刚提的这款..."` |
| `comment_author` | String | 是 | 评论账号昵称 | `"用户_7823"` |
| `comment_author_uid` | String | 是 | 评论账号唯一标识 | `"MS4wLjABAAAA..."` |
| `comment_time` | String | 是 | 评论发布时间（ISO 8601） | `"2026-07-19T14:23:00+08:00"` |
| `comment_like_count` | Integer | 是 | 评论获赞数 | `234` |

**请求示例：**

```json
{
  "comments": [
    {
      "comment_id": "cm_7123456789012345678",
      "video_title": "试驾体验｜这台车的智驾系统真的惊艳",
      "video_author": "@老王说车",
      "video_author_fans": 2865000,
      "video_metrics": {
        "like_count": 125000,
        "comment_count": 3428,
        "share_count": 8900,
        "collect_count": 12300
      },
      "comment_content": "这车智驾确实牛，我上个月刚提的这款，高速上基本不用管方向盘",
      "comment_author": "用户_7823",
      "comment_author_uid": "MS4wLjABAAAA...",
      "comment_time": "2026-07-19T14:23:00+08:00",
      "comment_like_count": 234
    },
    {
      "comment_id": "cm_7123456789012345679",
      "video_title": "试驾体验｜这台车的智驾系统真的惊艳",
      "video_author": "@老王说车",
      "video_author_fans": 2865000,
      "video_metrics": {
        "like_count": 125000,
        "comment_count": 3428,
        "share_count": 8900,
        "collect_count": 12300
      },
      "comment_content": "666666666",
      "comment_author": "水军_123",
      "comment_author_uid": "MS4wLjABAAAA...",
      "comment_time": "2026-07-19T09:10:00+08:00",
      "comment_like_count": 0
    }
  ]
}
```

---

### 输出参数

#### `results` (Array<ScreeningResult>)

初筛结果列表，与输入评论一一对应，每个结果对象包含：

| 参数名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| `comment_id` | String | 对应输入的评论 ID | `"cm_7123456789012345678"` |
| `passed` | Boolean | 是否通过初筛（true=通过，false=不通过） | `true` |
| `filter_reason` | String \| null | 未通过原因（仅 `passed=false` 时有值） | `"批量刷屏水军"` / `"广告/引流类评论"` / `"无实质内容"` / `null` |
| `analysis` | String | AI 分析过程说明（200-500 字） | 见下方示例 |
| `processed_at` | String | 处理时间戳（ISO 8601） | `"2026-07-19T15:30:00+08:00"` |

**响应示例：**

```json
{
  "results": [
    {
      "comment_id": "cm_7123456789012345678",
      "passed": true,
      "filter_reason": null,
      "analysis": "该评论内容具有明确的实际使用经验描述（\"我上个月刚提的这款\"），显示用户为真实车主。评论中包含具体场景细节（\"高速上基本不用管方向盘\"），属于有价值的用车反馈。评论获赞数较高（234），说明引发了其他用户共鸣。账号昵称非明显水军特征，综合判定为真实用户评论，通过初筛。",
      "processed_at": "2026-07-19T15:30:01+08:00"
    },
    {
      "comment_id": "cm_7123456789012345679",
      "passed": false,
      "filter_reason": "无实质内容（数字刷屏）",
      "analysis": "评论内容为纯数字重复（\"666666666\"），无任何实质性信息，属于典型的水军刷屏行为。账号昵称包含\"水军\"字样，评论获赞数为 0，进一步印证为无价值评论。此类评论对线索孵化无帮助，予以过滤。",
      "processed_at": "2026-07-19T15:30:01+08:00"
    }
  ]
}
```

**常见过滤原因枚举：**

- `"批量刷屏水军"`：重复发布相同或高度相似内容
- `"广告/引流类评论"`：包含微信号、电话、推广链接等
- `"无实质内容"`：如"沙发""666""关注了"等
- `"重复内容评论"`：与其他评论高度重复

---

## Agent 2: 账号画像精筛

### 功能说明

对初筛通过的评论账号进行深度画像分析，结合账号主页信息、历史评论行为，判断账号是否具有购车线索价值，并输出意向等级。

### 输入参数

#### `accounts` (Array<AccountObject>)

评论账号列表，每个账号对象包含以下字段：

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| `account_uid` | String | 是 | 账号唯一标识 | `"MS4wLjABAAAA..."` |
| `account_name` | String | 是 | 账号昵称 | `"用户_7823"` |
| `account_douyin_id` | String | 否 | 抖音号（如有） | `"user_7823"` |
| `account_homepage_screenshot` | String | 是 | 账号主页截图 URL 或 Base64 | `"https://cdn.example.com/screenshot/user7823.png"` |
| `comment_history` | Array<CommentHistoryItem> | 是 | 该账号的历史评论列表 | 见下方子结构 |

**`comment_history` 子结构：**

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| `video_title` | String | 是 | 评论所在视频标题 | `"试驾体验｜这台车的智驾系统真的惊艳"` |
| `comment_content` | String | 是 | 评论内容 | `"这车智驾确实牛..."` |
| `comment_time` | String | 是 | 评论时间（ISO 8601） | `"2026-07-19T14:23:00+08:00"` |
| `comment_like_count` | Integer | 是 | 评论获赞数 | `234` |

**请求示例：**

```json
{
  "accounts": [
    {
      "account_uid": "MS4wLjABAAAAuser7823",
      "account_name": "用户_7823",
      "account_douyin_id": "user_7823",
      "account_homepage_screenshot": "https://cdn.example.com/screenshots/user7823.png",
      "comment_history": [
        {
          "video_title": "试驾体验｜这台车的智驾系统真的惊艳",
          "comment_content": "这车智驾确实牛，我上个月刚提的这款，高速上基本不用管方向盘",
          "comment_time": "2026-07-19T14:23:00+08:00",
          "comment_like_count": 234
        },
        {
          "video_title": "新能源车充电成本实测",
          "comment_content": "家充桩装了之后确实方便，电费一公里才2毛钱",
          "comment_time": "2026-07-18T20:15:00+08:00",
          "comment_like_count": 89
        },
        {
          "video_title": "智能座舱横评对比",
          "comment_content": "语音助手响应速度很快，这个配置确实比上一代好太多",
          "comment_time": "2026-07-17T16:30:00+08:00",
          "comment_like_count": 56
        }
      ]
    }
  ]
}
```

---

### 输出参数

#### `results` (Array<ProfileResult>)

精筛结果列表，与输入账号一一对应，每个结果对象包含：

| 参数名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| `account_uid` | String | 对应输入的账号 UID | `"MS4wLjABAAAAuser7823"` |
| `has_value` | Boolean | 是否有线索价值（true=有价值，false=无价值） | `true` |
| `intent_level` | String \| null | 意向等级（仅 `has_value=true` 时有值） | `"高"` / `"中"` / `"低"` / `null` |
| `intent_level_code` | String \| null | 意向等级代码（便于系统处理） | `"high"` / `"medium"` / `"low"` / `null` |
| `value_score` | Integer \| null | 价值评分 0-100（仅 `has_value=true` 时有值） | `92` |
| `profile_tags` | Array<String> | 账号画像标签 | `["已购车主", "智驾关注", "高活跃度"]` |
| `profile_summary` | String | 账号画像摘要（150-300 字） | 见下方示例 |
| `analysis` | String | AI 分析过程说明（300-500 字） | 见下方示例 |
| `processed_at` | String | 处理时间戳（ISO 8601） | `"2026-07-19T16:00:00+08:00"` |

**响应示例：**

```json
{
  "results": [
    {
      "account_uid": "MS4wLjABAAAAuser7823",
      "has_value": true,
      "intent_level": "高",
      "intent_level_code": "high",
      "value_score": 92,
      "profile_tags": [
        "已购车主",
        "智驾关注",
        "高活跃度",
        "技术敏感"
      ],
      "profile_summary": "账号注册于 2024 年 3 月，粉丝 1.2k，近 30 天发布 12 条内容均与汽车相关，评论区多次提及\"提车\"\"用车感受\"。主页显示职业为互联网从业者（30-35岁），坐标一线城市，判定为真实车主，购车决策已完成，具有潜在换购/推荐价值。",
      "analysis": "【评论行为分析】该账号在近 30 天内发布了 3 条汽车相关评论，内容均涉及实际用车场景：智能驾驶体验、充电成本、座舱功能等，显示对车辆技术细节有深度关注。评论获赞数较高（234/89/56），说明内容质量受其他用户认可。\n\n【购车阶段判断】评论中明确提及\"我上个月刚提的这款\"，判定为已购车主，购车决策已完成。但作为技术敏感型用户，对智驾、语音助手等新功能高度关注，存在换购或影响他人购车的潜在价值。\n\n【主页画像分析】根据主页截图，账号主要发布内容为科技数码类，职业标签显示为互联网从业者，年龄段约 30-35 岁，具备较强消费能力。坐标一线城市，符合新能源车主流用户画像。\n\n【综合评分】账号真实性高，购车决策已完成，但技术敏感度强，内容影响力较大，具有高价值线索潜力，评分 92/100，意向等级定为\"高\"。",
      "processed_at": "2026-07-19T16:00:01+08:00"
    }
  ]
}
```

**意向等级定义：**

| 等级代码 | 中文描述 | 分数区间 | 典型特征 |
|---------|---------|---------|---------|
| `high` | 高 | 85-100 | 近期明确购车意向 / 已预约试驾 / 预算明确 / 决策末期 / 已购车主（换购潜力） |
| `medium` | 中 | 70-84 | 正在对比车型 / 有具体顾虑待解决 / 预算区间清晰 / 决策中期 |
| `low` | 低 | 50-69 | 初步了解阶段 / 观望态度 / 无明确购车时间表 / 决策前期 |

---

## 流水线调用流程

### 完整调用链

```
原始评论数据
    ↓
[Agent 1: 评论价值初筛]
    ↓
初筛通过的评论 (passed=true)
    ↓
提取唯一账号 UID + 爬取主页截图 + 汇总评论历史
    ↓
[Agent 2: 账号画像精筛]
    ↓
高价值线索列表 (has_value=true)
```

### 调用时序

1. **批量初筛**：一次性传入一批评论（建议 50-200 条），Agent 1 并行处理后返回筛选结果
2. **账号去重**：从初筛通过的评论中提取唯一账号列表（按 `account_uid` 去重）
3. **数据准备**：爬取账号主页截图，汇总该账号的所有历史评论
4. **批量精筛**：将账号数据传入 Agent 2（建议 20-50 个账号/批次）
5. **结果输出**：筛选 `has_value=true` 的账号作为最终高价值线索

---

## 错误处理

### 通用错误码

| 错误码 | 说明 | 处理建议 |
|--------|------|---------|
| `400` | 请求参数不合法 | 检查必填字段是否完整、数据类型是否正确 |
| `429` | 请求频率超限 | 降低调用频率，建议每批次间隔 2-5 秒 |
| `500` | Agent 内部错误 | 重试 2-3 次，若持续失败联系技术支持 |
| `503` | Agent 服务不可用 | 稍后重试或切换备用 Agent |

### 字段缺失处理

- **主页截图不可用**：Agent 2 会降级为仅依赖评论历史分析，但 `value_score` 会相应降低 10-15 分
- **评论历史为空**：Agent 2 无法进行画像分析，返回 `has_value=false`
- **视频热度指标缺失**：Agent 1 会使用默认权重进行判断，不影响核心逻辑

---

## 性能参考

| 指标 | 数值 | 备注 |
|------|------|------|
| Agent 1 处理速度 | 5-10 条/秒 | 取决于评论文本长度 |
| Agent 2 处理速度 | 2-5 个账号/秒 | 取决于主页截图大小和评论历史数量 |
| 推荐批次大小 | 初筛 100 条/批，精筛 30 个/批 | 平衡速度与资源占用 |
| 建议调用间隔 | 2-5 秒 | 避免触发频率限制 |

---

## 附录：完整调用示例

```python
import requests
import time

# 配置
AGENT1_URL = "https://api.example.com/agent/comment-screening"
AGENT2_URL = "https://api.example.com/agent/profile-screening"
API_KEY = "your_api_key_here"

# 步骤 1：调用 Agent 1 初筛评论
comments = [...]  # 原始评论列表
response1 = requests.post(
    AGENT1_URL,
    headers={"Authorization": f"Bearer {API_KEY}"},
    json={"comments": comments}
)
screening_results = response1.json()["results"]

# 步骤 2：提取通过初筛的账号
passed_comments = [r for r in screening_results if r["passed"]]
unique_accounts = {}
for comment in passed_comments:
    uid = comment["account_uid"]
    if uid not in unique_accounts:
        unique_accounts[uid] = {
            "account_uid": uid,
            "account_name": comment["account_name"],
            "account_homepage_screenshot": fetch_screenshot(uid),  # 需实现
            "comment_history": []
        }
    unique_accounts[uid]["comment_history"].append({
        "video_title": comment["video_title"],
        "comment_content": comment["comment_content"],
        "comment_time": comment["comment_time"],
        "comment_like_count": comment.get("comment_like_count", 0)
    })

# 步骤 3：调用 Agent 2 精筛账号
accounts = list(unique_accounts.values())
time.sleep(3)  # 避免频率限制
response2 = requests.post(
    AGENT2_URL,
    headers={"Authorization": f"Bearer {API_KEY}"},
    json={"accounts": accounts}
)
profile_results = response2.json()["results"]

# 步骤 4：输出高价值线索
high_value_leads = [r for r in profile_results if r["has_value"]]
for lead in high_value_leads:
    print(f"账号：{lead['account_uid']}")
    print(f"意向等级：{lead['intent_level']} ({lead['value_score']}分)")
    print(f"标签：{', '.join(lead['profile_tags'])}")
    print(f"画像：{lead['profile_summary']}")
    print("---")
```

---

## 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|---------|
| v1.0 | 2026-07-21 | 初始版本，定义两个 Agent 的输入输出规范 |

---

**文档维护者**：线索孵化系统团队  
**最后更新**：2026-07-21  
**反馈联系**：tech-support@example.com
