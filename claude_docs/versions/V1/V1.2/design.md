# DriveIntent V1.2 设计文档

**文档版本：** 1.2
**日期：** 2026-07-28
**状态：** 已评审通过
**上游文档：** `claude_docs/2026-07-23-v1-design.md`（V1 设计）、`claude_docs/2026-07-27-v1.1-design.md`（V1.1 设计）、`docs/DriveIntent-V1-API对接文档.md`（对接契约 v1.1.1）

---

## 1. 目标与范围

把 Agent2（账号画像精筛）输入中预留但未正式使用的 `account_homepage_screenshot`（用户抖音主页截图）**正式纳入分析流程**：

1. **识图阶段**：调用多模态 LLM 识别主页截图，建立**结构化用户画像**（主题、消费能力、兴趣标签、年龄、性别、IP 属地等）。
2. **评级阶段**：把画像数据注入评级流程，依据画像对高质量线索做**有限上调**，使评级更精准。

**对外 API 契约不变**——对接方无需改动解析逻辑。

### 1.1 不做

- 不改 Agent1（评论初筛）链路。
- 不改对外输出字段结构（`intent_level` / `value_score` / `profile_tags` 等不变）。
- 不做画像的独立存储/查询接口（画像随分析结果落 `AnalysisResult`）。

---

## 2. 识图阶段：结构化画像

### 2.1 输出格式变更

`image_recognition` skill 从"输出自然段描述"升级为"输出结构化画像 JSON"。

结构化画像字段（示例基于 `data/douyin_screenshot_example.png`）：

```json
{
  "nickname": "应许",
  "douyin_id": "23095593766",
  "signature": "阴晴圆缺 沉浮眷恋",
  "age": null,
  "gender": "男",
  "ip_location": "北京",
  "follow_count": 402,
  "fans_count": 103,
  "likes_count": 608,
  "verification": null,
  "content_themes": ["游戏/电竞", "英雄联盟", "宠物"],
  "consumption_signals": [],
  "interest_tags": ["游戏发烧友", "LOL玩家"],
  "auto_relevance": "无明显汽车/自驾相关内容",
  "raw_description": "自然段完整描述，兜底"
}
```

### 2.2 关键设计点

- **`auto_relevance`**：显式判断"是否有汽车/自驾/消费能力相关线索"。这是评级上调的**直接证据来源**，评级 prompt 主要依据此字段决定是否上调。
- **`raw_description`**：保留完整自然段描述，防止结构化字段遗漏截图中的信息，作为兜底。
- **字段缺失处理**：截图中不可见的信息输出 `null` 或空数组，严禁编造（如示例中 111 岁明显异常，应识别为 `null` 或标注疑似虚设）。
- **降级路径**：识图失败或空截图 → 返回空画像（`recognize_screenshot` 返回空串或空 JSON），走现有降级逻辑（`screenshot_available=False`，`value_score` 降 10-15 分）。

### 2.3 实现

- 新增 prompt 模板 `app/skills/prompts/image_recognition_v2.txt`，要求模型输出上述结构化 JSON。
- `app/skills/configs/image_recognition.yaml`：`version` 升至 `2.0`，`prompt_file` 指向 v2，`prompt_version` 升至 `v2`。
- `recognize_screenshot()`（`app/api/agent2.py`）：返回值从"自然段文字"改为"结构化画像 JSON 字符串"（或空串表示无画像）。解析失败时回退到原始文本，保证鲁棒性。
- **迭代优化**：用 `data/douyin_screenshot_example.png` 实际调用 LLM 验证输出完整性，据结果调整 prompt。

---

## 3. 评级阶段：画像驱动的有限上调

### 3.1 规则（写入 `user_lead_analysis` prompt）

评级采用**单阶段**（画像 + 评级合并在一次 LLM 调用），通过 prompt 表达"先评论定基线、再画像有限上调"的思维链：

1. **先用评论证据定基线等级**（`baseline_grade`），画像**不参与**基线判定。
2. 基线为 **C 或以下** → 忽略画像，最终等级 = 基线（C 级及以下评论内容本身参考意义弱）。
3. 基线为 **B 或 A** → 检查画像是否有**直接证据**支持上调：
   - 有直接证据（如"自驾爱好者""汽车发烧友""明确高消费信号"）→ 上调一级（B→A 或 A→H），**最多一级**。
   - 无直接证据 → 保持基线。
4. **画像只上调、不下调**：不得因画像证据弱而对已判定的高等级线索降级。
5. 上调必须能**指名具体画像证据**，不得因"感觉"或弱关联上调。

> 等级从高到低：H > A > B > C。H 已是最高级，不再上调。

### 3.2 内部审计字段

`UserLeadResult` schema 新增三个字段（可选，默认值），写入 `AnalysisResult` 便于调试与审计，**不改对外契约**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `baseline_grade` | `str \| None` | 仅基于评论证据的基线等级（H/A/B/C） |
| `profile_adjustment` | `str` | 画像调整结果：`none` / `upgraded`，默认 `none` |
| `adjustment_reason` | `str \| None` | 上调依据（直接画像证据），未上调为 null |

`lead_grade` 仍为**最终等级**（画像上调后）。

### 3.3 prompt 升级

- 新增 `app/skills/prompts/user_lead_analysis_v3.txt`：注入结构化画像 JSON，输出新增审计字段。
- `app/skills/configs/user_lead_analysis.yaml`：`version` 升至 `1.2`，`prompt_file` 指向 v3，`prompt_version` 升至 `v3`。
- `SKILL_VERSIONS[USER_ANALYSIS_SKILL]` 升至 `"1.2"`。

---

## 4. 数据流与契约

```
account → recognize_screenshot() → 结构化画像 JSON（或空串降级）
                                         ↓
       _build_evidence() 注入画像 → user_lead_analysis (v3)
                                         ↓
      输出 lead_grade(最终) + baseline_grade / profile_adjustment / adjustment_reason
                                         ↓
       map_profile_result() → 对外 intent_level/value_score/... (契约不变)
```

- `_build_evidence()`（`app/api/agent2.py`）：`homepage_description` 字段改为注入结构化画像（键名调整为 `homepage_profile`，值为解析后的画像对象或"（无主页截图）"）。
- `map_profile_result()` 映射逻辑不变，新增审计字段不进入对外输出。
- 8000 流水线链路（`app/workflow/pipeline.py::run_user_analysis`）：该路径无主页截图输入，画像为空，行为与现有一致（`homepage_profile` 为空时评级不上调）。

---

## 5. 测试

- **识图 prompt 验证**：用 `data/douyin_screenshot_example.png` 实际调用 LLM，验证结构化画像输出完整、字段准确、异常值（如 111 岁）正确处理。
- **单元测试**（复用 `tests/test_agent2.py` 结构，mock LLM）：
  - 画像注入：结构化画像正确进入 `user_lead_analysis` context。
  - 空画像降级：无截图/识图失败时走降级路径，评级不上调。
  - 基线 C 不上调：mock 基线为 C + 强画像证据，验证最终等级仍为 C。
  - 基线 B/A 上调：mock 基线为 B + 汽车相关画像证据，验证上调至 A 且审计字段正确。
  - 画像不下调：mock 基线为 A + 弱画像，验证最终等级不低于 A。
- **契约回归**：`map_profile_result` 输出字段不变，现有 API schema 测试通过。

---

## 6. 影响文件清单

| 文件 | 变更 |
|------|------|
| `app/skills/prompts/image_recognition_v2.txt` | 新增：结构化画像 prompt |
| `app/skills/configs/image_recognition.yaml` | version→2.0，指向 v2 |
| `app/skills/prompts/user_lead_analysis_v3.txt` | 新增：注入画像 + 审计字段 |
| `app/skills/configs/user_lead_analysis.yaml` | version→1.2，指向 v3 |
| `app/schemas/skills.py` | `UserLeadResult` 新增 3 个审计字段 |
| `app/api/agent2.py` | `recognize_screenshot` 返回结构化；`_build_evidence` 注入画像 |
| `app/workflow/pipeline.py` | `SKILL_VERSIONS` 升 1.2 |
| `docs/DriveIntent-V1-API对接文档.md` | 补充 V1.2 行为说明（画像正式纳入，契约不变） |
| `tests/test_agent2.py` | 新增画像相关测试用例 |
