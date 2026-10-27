# DriveIntent 版本/版本文档体系规范化 设计文档

> 日期：2026-08-03 | 类型：文档体系规范化（不发新版本、不改代码逻辑）

## 1. 背景与目标

项目历经 V0 → V1.3 共 8 个版本，13 份 design/plan 文档平铺在 `claude_docs/` 根目录，代码内 Prompt/Skill 版本号自成体系（v1~v5 顺延式），与项目版本号脱钩。本次任务：

1. 在 `claude_docs/versions/` 建立树形版本文档目录，迁入全部历史文档；
2. 为大版本补写上层版本文档（OVERVIEW.md）；
3. 制定代码内版本化资产（Prompt 文件、Skill 配置版本字段）的命名规则——今后跟随项目版本号；
4. 将规则固化为常驻规范文档 `VERSIONING.md`，并在 CLAUDE.md 中以最小改动引用。

**非目标**：不回溯重命名现有 Prompt 文件（v1~v5 保持不动）；不修改任何代码与测试；不更新 README.md。

## 2. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 现有 Prompt 文件是否回溯重命名 | 否，只立规则；从下一次实际修改起用新命名 |
| 上层版本文档职责 | 能力快照 + 变更索引 |
| 历史 13 份文档 | 本次全部 `git mv` 迁入 versions 树 |
| 补丁版本目录组织 | 两层目录，补丁文档以 `v1.x.y-` 前缀落入所属小版本目录 |
| 迁入后的文件名 | 统一 `design.md` / `plan.md`（目录已编码版本号） |
| 命名规则覆盖范围 | Prompt 文件名 + `prompt_version` 字段 + Skill 配置 `version` 字段 |
| 规范落点 | 方案 A：`versions/VERSIONING.md` 完整规范 + CLAUDE.md 摘要引用 |

## 3. 目录结构与迁移映射

```
claude_docs/
├── versions/
│   ├── VERSIONING.md          # 版本管理规范（新增）
│   ├── V0/
│   │   ├── OVERVIEW.md        # 新增（V0 已冻结，简短）
│   │   ├── design.md          # ← 2026-07-20-v0-design.md
│   │   └── plan.md            # ← 2026-07-20-v0-plan.md
│   └── V1/
│       ├── OVERVIEW.md        # 新增（能力快照以 V1.3 现状为准）
│       ├── V1.0/
│       │   ├── design.md      # ← 2026-07-23-v1-design.md
│       │   └── plan.md        # ← 2026-07-23-v1-plan.md
│       ├── V1.1/
│       │   ├── design.md      # ← 2026-07-27-v1.1-design.md
│       │   ├── plan.md        # ← 2026-07-27-v1.1-plan.md
│       │   └── v1.1.1-design.md   # ← 2026-07-28-v1.1.1-design.md
│       ├── V1.2/
│       │   ├── design.md      # ← 2026-07-28-v1.2-design.md
│       │   ├── plan.md        # ← 2026-07-28-v1.2-plan.md
│       │   ├── v1.2.1-design.md   # ← 2026-07-30-v1.2.1-design.md
│       │   └── v1.2.1-plan.md     # ← 2026-07-30-v1.2.1-plan.md
│       └── V1.3/
│           ├── design.md      # ← 2026-08-03-v1.3-design.md
│           └── plan.md        # ← 2026-08-03-v1.3-plan.md
└── （本设计文档；claude_docs 根目录此后只放 versions/ 与非版本类文档）
```

规则要点：
- 大版本（V0/V1/…）为第一层目录，小版本（V1.1/V1.2/…）为第二层；V1 首发版本归入 `V1.0`，与后续小版本平级。
- 补丁版本不建第三层目录，其文档以完整版本号前缀命名（`v1.1.1-design.md`）落入所属小版本目录。
- 版本目录内标准文档为 `design.md`、`plan.md`；原文件名中的日期在迁移时补入文档首部元信息行（如 `> 版本：V1.3 | 日期：2026-08-03`），文档内已有日期的不重复补。
- 迁移使用 `git mv` 保留历史。

## 4. 上层版本文档（OVERVIEW.md）

每个大版本目录下维护一份 `OVERVIEW.md`，两部分：

1. **能力快照**：该大版本当前最新状态——定位、核心功能、架构要点、对外契约现状、各 Skill/Prompt 版本对照。只描述"现在是什么"，不写演进过程。
2. **变更索引**：一行一版本——版本号、日期、一句话变更摘要、指向该版本 design/plan 的相对链接。

**更新规则**：每次小版本/补丁版落地时必须同步更新所属大版本 OVERVIEW.md（索引加行 + 快照改写受影响部分）；新开大版本时先建 OVERVIEW.md 骨架。

**本次补写**：
- `V0/OVERVIEW.md`：能力快照数句 + 索引一行（V0 已冻结）。
- `V1/OVERVIEW.md`：能力快照按 V1.3 后系统现状（微服务化、两个异步 API、Agent1/Agent2 流水线、账号级两标签体系等）；变更索引 V1.0/V1.1/V1.1.1/V1.2/V1.2.1/V1.3 共 6 行。内容从各版本 design 文档提炼，不新增事实。

## 5. 代码内版本命名规则（今后适用，不回溯）

1. **Prompt 文件名**：Prompt 内容变更时，新文件命名为 `<skill_id>_v<项目版本号>.txt`（如 `user_lead_analysis_v1.3.1.txt`）；旧文件保留不动、不再被引用。
2. **`prompt_version` 字段**：随新文件同步为 `"v<项目版本号>"`（如 `"v1.3.1"`），YAML 与落库值一致。
3. **Skill 配置 `version` 字段**：Skill 行为（Prompt、模型参数、输出契约等）变更时，直接写引入变更的项目版本号（如 `"1.3.1"`），不再自成体系。
4. **同一版本多次修改**：一个项目版本开发周期内多次调整同一 Prompt，只留该版本号命名的最终一份，不产生中间文件。
5. **语义**：版本后缀表示"该资产最后一次变更发生在哪个项目版本"；未改动的资产保持旧版本号是正常状态。
6. **适用边界**：适用于所有随项目版本演进的版本化资产（当前为 Prompt 文件与 Skill 配置版本字段；未来同类资产同样适用）。数据库历史记录中的旧 `prompt_version` 值不迁移，新旧口径并存。

**旧号 → 引入版本对照表**（写入 VERSIONING.md 供查询历史数据参考；实施时逐一从各版本 design 文档核实，下表为初步判断）：

| Skill | 当前 prompt | 旧口径序列 | 对应项目版本（初步） |
|---|---|---|---|
| comment_lead_screening | v3 | v1/v2/v3 | V1.0 / V1.1 / V1.3 |
| video_context_analysis | v2 | v1/v2 | V1.0 / V1.1 |
| user_lead_analysis | v5 | v1~v5 | V1.0 / V1.1 / V1.2 / V1.2.1 / V1.3 |
| image_recognition | v2 | v1/v2 | V1.1 / V1.2 |

## 6. VERSIONING.md 内容结构

1. 版本号体系：`V<大>.<小>.<补丁>` 三段式——大版本（架构级演进）、小版本（功能迭代）、补丁版（小修正/契约微调）；
2. 目录结构规则（第 3 节）；
3. OVERVIEW.md 职责与骨架模板（第 4 节）；
4. 代码内版本命名规则 + 旧号对照表（第 5 节）；
5. 发版检查清单：
   - [ ] `versions/V<大>/V<大>.<小>/` 下落 `design.md`（及 `plan.md`，如有）
   - [ ] 补丁版：`v<完整版本号>-design.md` 等落入所属小版本目录
   - [ ] 更新所属大版本 `OVERVIEW.md`（索引加行 + 快照改写受影响部分）
   - [ ] 代码中被修改的 Prompt/Skill 版本字段按项目版本号命名
   - [ ] 架构/契约变更同步更新 claude_docs 相关文档（既有规范）

## 7. CLAUDE.md 更新（最小化，两处）

- 原条目"……归档到./claude_docs目录"改为归档到 `./claude_docs/versions/` 对应版本目录；
- 新增一行：版本目录结构、版本文档职责、代码内版本命名遵循 `./claude_docs/versions/VERSIONING.md`，每次发版按其检查清单执行。

README.md 本次不动。

## 8. 实施产出清单

1. 建 `versions` 树，`git mv` 迁移 13 份文档，按需补文首元信息；
2. 新写 `VERSIONING.md`、`V0/OVERVIEW.md`、`V1/OVERVIEW.md`（对照表实施时核实）；
3. 更新 CLAUDE.md 两处；
4. 不改任何代码、不发新版本、不动 README.md。

## 9. 验收标准

- `claude_docs/` 根目录不再有平铺的版本 design/plan 文档；
- 任一历史版本文档可通过 `versions/V*/V*.*/` 路径直达；
- `V1/OVERVIEW.md` 能独立回答"当前 V1 是什么"并索引全部 6 个版本；
- VERSIONING.md 规则完整、检查清单可执行；
- CLAUDE.md 变更 ≤ 5 行；
- `git log --follow` 可追溯迁移文档的历史。
