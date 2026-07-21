/* DriveIntent 技术方案 PPT 生成脚本(pptxgenjs)
 * 运行:node build_ppt.js  → 输出 ../DriveIntent技术方案.pptx
 */
const pptxgen = require("pptxgenjs");

const F = "Microsoft YaHei";
const MONO = "Consolas";

const C = {
  bgDark: "161F44",
  bg: "F5F7FA",
  ink: "1F2637",
  navy: "1E2761",
  steel: "3E5C94",
  cyan: "0898C0",
  cyanDeep: "0A7FA0",
  muted: "5A6478",
  mutedLight: "AAB4CE",
  line: "DDE3EE",
  white: "FFFFFF",
  card: "FFFFFF",
  panelDark: "222D5C",
  ice: "CADCFC",
  gH: "D93848",
  gA: "E8890C",
  gB: "2A9D8F",
  gC: "8D99AE",
};

const p = new pptxgen();
p.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
p.author = "DriveIntent";
p.title = "DriveIntent 技术实现方案";

const W = 13.333;

/* ---------- 通用助手 ---------- */
function header(s, num, title, sub) {
  s.background = { color: C.bg };
  s.addText(title, { x: 0.45, y: 0.22, w: 9.5, h: 0.5, fontFace: F, fontSize: 20, bold: true, color: C.navy, margin: 0 });
  if (sub) s.addText(sub, { x: 0.45, y: 0.7, w: 11.0, h: 0.3, fontFace: F, fontSize: 10, color: C.muted, margin: 0 });
  s.addShape(p.shapes.RECTANGLE, { x: W - 0.85, y: 0.24, w: 0.42, h: 0.42, fill: { color: C.navy } });
  s.addText(String(num), { x: W - 0.85, y: 0.24, w: 0.42, h: 0.42, fontFace: F, fontSize: 13, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
}

function card(s, x, y, w, h, accent) {
  s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: C.card }, line: { color: C.line, width: 0.75 } });
  s.addShape(p.shapes.RECTANGLE, { x, y, w: 0.055, h, fill: { color: accent || C.cyan } });
}

// 多行文本:lines = [{t, opts?}] 或字符串数组
function lines(s, x, y, w, h, arr, base) {
  const runs = arr.map((it, i) => {
    const o = Object.assign({ breakLine: i < arr.length - 1 }, it.opts || {});
    return { text: typeof it === "string" ? it : it.t, options: o };
  });
  s.addText(runs, Object.assign({ x, y, w, h, fontFace: F, fontSize: 9, color: C.ink, valign: "top", margin: 0.03 }, base || {}));
}

function flowBox(s, x, y, w, h, title, color, fs) {
  s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: color || C.navy } });
  s.addText(title, { x, y, w, h, fontFace: F, fontSize: fs || 10, bold: true, color: C.white, align: "center", valign: "middle", margin: 0.02 });
}

function arrowR(s, x, y, len, color) {
  s.addShape(p.shapes.RIGHT_ARROW, { x, y, w: len || 0.24, h: 0.16, fill: { color: color || C.cyan } });
}

function chip(s, x, y, w, h, text, fill, color, fs) {
  s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill } });
  s.addText(text, { x, y, w, h, fontFace: F, fontSize: fs || 8.5, color: color || C.white, align: "center", valign: "middle", margin: 0.02 });
}

/* ================= S1 项目概览(深色) ================= */
(function s1() {
  const s = p.addSlide();
  s.background = { color: C.bgDark };

  s.addText([
    { text: "DriveIntent ", options: { color: C.white, bold: true } },
    { text: "技术实现方案", options: { color: C.ice, bold: true } },
  ], { x: 0.6, y: 0.42, w: 10.5, h: 0.65, fontFace: F, fontSize: 30, margin: 0 });
  s.addText("AI-powered automotive social-media intent & lead intelligence — MVP(V0)", {
    x: 0.62, y: 1.12, w: 11.5, h: 0.3, fontFace: F, fontSize: 10.5, color: C.ice, margin: 0 });
  s.addText("从短视频平台海量评论中识别真实购车意向,将公域用户转化为可解释、可验证、可跟进的 H/A/B/C 分级销售线索。", {
    x: 0.62, y: 1.5, w: 12.1, h: 0.34, fontFace: F, fontSize: 12.5, color: C.white, margin: 0 });

  // 统计卡
  const stats = [
    ["45", "测试集视频(抖音)"],
    ["2.38 万", "评论(单视频 2–4169 条)"],
    ["≈2 万", "评论用户(1865 人多评)"],
    ["3", "核心 LLM Skill / 1 条固定工作流"],
  ];
  stats.forEach((st, i) => {
    const x = 0.6 + i * 3.09, y = 2.06, w = 2.95, h = 1.0;
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: C.panelDark } });
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h: 0.045, fill: { color: C.cyan } });
    s.addText(st[0], { x: x + 0.14, y: y + 0.1, w: w - 0.28, h: 0.5, fontFace: F, fontSize: 26, bold: true, color: C.white, margin: 0 });
    s.addText(st[1], { x: x + 0.14, y: y + 0.62, w: w - 0.28, h: 0.3, fontFace: F, fontSize: 8.5, color: C.mutedLight, margin: 0 });
  });

  // 端到端流程条
  s.addText("端到端流程", { x: 0.62, y: 3.32, w: 3, h: 0.26, fontFace: F, fontSize: 9.5, bold: true, color: C.cyan, margin: 0 });
  const steps = ["数据导入", "视频语境分析", "评论批量筛选", "用户级聚合", "用户综合分析", "H/A/B/C 线索", "审核 / 导出"];
  const bw = 1.62, gap = 0.145, y0 = 3.62;
  steps.forEach((t, i) => {
    const x = 0.6 + i * (bw + gap);
    flowBox(s, x, y0, bw, 0.46, t, i === 5 ? C.cyanDeep : C.panelDark, 9);
    if (i < steps.length - 1) arrowR(s, x + bw + 0.005, y0 + 0.15, 0.135, C.cyan);
  });

  // 方法卡
  const methods = [
    ["确定性工作流 + 专业化 Skill", "固定工作流控制执行顺序,LLM Skill 负责语义判断:流程可预测、输入输出结构明确、问题可定位到具体 Skill,Skill 可独立升级与回归测试。"],
    ["证据驱动", "所有等级与画像结论均记录:证据评论、所在视频、判断理由、置信度、模型 / Prompt / Skill 版本,可完整回溯。"],
    ["先准确率,后召回率", "销售可处理线索有限。优先保证 H / H+A 级准确率与无效评论过滤效果,达标后再提升召回。"],
    ["逻辑分层,物理合并", "L1–L5 五层逻辑边界清晰,物理上为模块化单体(单进程 FastAPI + MySQL),保留未来拆分与平台化路径。"],
  ];
  methods.forEach((m, i) => {
    const x = 0.6 + i * 3.09, y = 4.42, w = 2.95, h = 2.06;
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: C.panelDark } });
    s.addShape(p.shapes.RECTANGLE, { x, y, w: 0.05, h, fill: { color: C.cyan } });
    s.addText(m[0], { x: x + 0.15, y: y + 0.12, w: w - 0.3, h: 0.55, fontFace: F, fontSize: 11, bold: true, color: C.white, margin: 0 });
    s.addText(m[1], { x: x + 0.15, y: y + 0.68, w: w - 0.3, h: h - 0.8, fontFace: F, fontSize: 8.5, color: C.mutedLight, valign: "top", margin: 0 });
  });

  // 技术栈
  s.addText([
    { text: "技术栈  ", options: { bold: true, color: C.cyan } },
    { text: "Python 3.11+ · FastAPI · SQLAlchemy 2.0 · Pydantic v2 · MySQL (PyMySQL) · Jinja2 服务端渲染 · pandas / openpyxl · asyncio 后台 Worker · OpenAI 兼容 LLM 接口", options: { color: C.ice } },
  ], { x: 0.62, y: 6.78, w: 12.2, h: 0.35, fontFace: F, fontSize: 10, margin: 0 });
})();

/* ================= S2 总体架构 ================= */
(function s2() {
  const s = p.addSlide();
  header(s, 2, "总体架构:五层逻辑分层 × 模块化单体", "逻辑边界保证可维护与未来可拆分,物理合并降低 MVP 建设成本");

  // 左:五层逻辑架构(L5 在顶)
  s.addText("五层逻辑架构", { x: 0.45, y: 1.05, w: 3, h: 0.28, fontFace: F, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  const layers = [
    ["L5", "业务应用层", "任务页 · 线索列表 · 线索详情 · 人工审核 · CSV 导出", C.navy],
    ["L4", "业务策略层", "线索有效性 · H/A/B/C 分级 · 购车意向画像 · 销售切入建议", "2B3A75"],
    ["L3", "AI 分析能力层", "视频语境理解 / 评论线索筛选 / 用户综合分析(3 个 LLM Skill)", C.steel],
    ["L2", "事实与特征层", "视频语境结果 · 评论意向结果 · 用户聚合与简单统计特征", "3E7BA6"],
    ["L1", "数据与证据层", "视频 · 评论 · 平台用户 · 原始 raw_data(证据可回溯)", C.cyanDeep],
  ];
  layers.forEach((L, i) => {
    const y = 1.42 + i * 1.02, x = 0.45, w = 5.75, h = 0.9;
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: C.white }, line: { color: C.line, width: 0.75 } });
    s.addShape(p.shapes.RECTANGLE, { x, y, w: 0.62, h, fill: { color: L[3] } });
    s.addText(L[0], { x, y, w: 0.62, h, fontFace: F, fontSize: 13, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(L[1], { x: x + 0.78, y: y + 0.1, w: w - 0.9, h: 0.3, fontFace: F, fontSize: 11, bold: true, color: C.ink, margin: 0 });
    s.addText(L[2], { x: x + 0.78, y: y + 0.44, w: w - 0.9, h: 0.36, fontFace: F, fontSize: 8.5, color: C.muted, margin: 0 });
  });
  s.addText("模块依赖方向:web → services / workflow → skills → llm;importer / models 被各层引用",
    { x: 0.45, y: 6.6, w: 5.9, h: 0.3, fontFace: F, fontSize: 8.5, color: C.muted, italic: true, margin: 0 });

  // 右:物理架构
  const rx = 6.7, rw = 6.2;
  s.addText("模块化单体物理架构", { x: rx, y: 1.05, w: 4, h: 0.28, fontFace: F, fontSize: 11, bold: true, color: C.navy, margin: 0 });

  // FastAPI 单进程外框
  s.addShape(p.shapes.RECTANGLE, { x: rx, y: 1.42, w: rw, h: 2.16, fill: { color: C.white }, line: { color: C.navy, width: 1.25 } });
  s.addText("FastAPI 单进程应用(lifespan 内拉起 asyncio 后台 Worker)", { x: rx + 0.12, y: 1.5, w: rw - 0.24, h: 0.26, fontFace: F, fontSize: 9.5, bold: true, color: C.navy, margin: 0 });
  const mods = [
    ["Data Importer", "Excel / 标准 JSON 幂等导入"],
    ["Workflow Runner + Worker", "固定工作流 · 任务轮询执行"],
    ["Skill Executor", "Prompt 组装 · Schema 校验重试"],
    ["LLM Gateway", "Provider 适配 · 重试 · 调用日志"],
    ["Lead Service", "用户聚合 · 线索生成 · 导出"],
    ["Web / JSON API", "Jinja2 页面 + REST 接口"],
  ];
  mods.forEach((m, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = rx + 0.14 + col * 2.0, y = 1.86 + row * 0.84, w = 1.9, h = 0.74;
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: "EEF2FA" }, line: { color: C.line, width: 0.5 } });
    s.addText(m[0], { x: x + 0.07, y: y + 0.06, w: w - 0.14, h: 0.26, fontFace: F, fontSize: 9, bold: true, color: C.navy, margin: 0 });
    s.addText(m[1], { x: x + 0.07, y: y + 0.34, w: w - 0.14, h: 0.36, fontFace: F, fontSize: 7.5, color: C.muted, margin: 0 });
  });

  // 箭头 + MySQL
  s.addShape(p.shapes.DOWN_ARROW, { x: rx + rw / 2 - 0.11, y: 3.62, w: 0.22, h: 0.3, fill: { color: C.cyan } });
  s.addShape(p.shapes.RECTANGLE, { x: rx, y: 3.96, w: rw, h: 1.62, fill: { color: C.white }, line: { color: C.cyanDeep, width: 1.25 } });
  s.addText("MySQL(7 张表,自动建表)", { x: rx + 0.12, y: 4.04, w: rw - 0.24, h: 0.26, fontFace: F, fontSize: 9.5, bold: true, color: C.cyanDeep, margin: 0 });
  const dbGroups = [
    ["原始数据 (L1)", "video · platform_user · comment"],
    ["任务与结果", "analysis_task · analysis_result"],
    ["业务与日志", "lead · llm_call_log"],
  ];
  dbGroups.forEach((g, i) => {
    const x = rx + 0.14 + i * 2.0, y = 4.4, w = 1.9, h = 1.04;
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: "E8F4F8" }, line: { color: C.line, width: 0.5 } });
    s.addText(g[0], { x: x + 0.07, y: y + 0.08, w: w - 0.14, h: 0.26, fontFace: F, fontSize: 8.5, bold: true, color: C.cyanDeep, margin: 0 });
    s.addText(g[1], { x: x + 0.07, y: y + 0.38, w: w - 0.14, h: 0.6, fontFace: MONO, fontSize: 8, color: C.ink, valign: "top", margin: 0 });
  });

  // 横向公共能力
  s.addShape(p.shapes.RECTANGLE, { x: rx, y: 5.82, w: rw, h: 0.92, fill: { color: C.navy } });
  s.addText("横向公共能力", { x: rx + 0.12, y: 5.9, w: rw - 0.24, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.white, margin: 0 });
  s.addText("Skill YAML 配置加载 · Prompt 版本管理 · JSON Schema 校验 · 任务状态管理 · 自动重试 · LLM 调用日志与 Token 统计",
    { x: rx + 0.12, y: 6.17, w: rw - 0.24, h: 0.5, fontFace: F, fontSize: 8.5, color: C.ice, margin: 0 });
})();

/* ================= S3 端到端分析流水线 ================= */
(function s3() {
  const s = p.addSlide();
  header(s, 3, "端到端分析流水线", "固定工作流:上游任务完成后由 Worker 自动创建下游任务,全程异步、可断点续跑");

  const nodes = [
    ["① 数据导入(L1)", ["Excel / 标准 JSON 双入口,同一导入管道", "幂等键 platform+external_id,重复导入跳过", "空评论跳过并计数;#话题# 标签解析", "原始行完整存入 raw_data"], C.cyanDeep],
    ["② 视频语境分析", ["Skill:video_context_analysis", "每视频仅调用 1 次,结果供全部评论复用", "输出品牌 / 车型 / 内容类型 / 主题 / 竞品 /", "商业属性 / 评论分析注意事项"], C.steel],
    ["③ 评论批量筛选", ["Skill:comment_lead_screening", "30 条/批(可配 20–50),降低调用成本", "区分情绪 / 兴趣 / 需求 / 交易四级意向", "识别无意义 / 无关 / 营销 / 水军评论"], C.steel],
    ["④ 候选用户聚合", ["纯代码,不调用 LLM", "门槛:购车相关且非营销评论 ≥ 1 条", "聚合有效评论 / 所在视频 / 品牌车型 /", "高意向评论数等简单统计特征"], "2B7A5B"],
    ["⑤ 用户综合分析", ["Skill:user_lead_analysis", "输入:全部有效评论 + 各自视频语境 +", "统计特征 + H/A/B/C 分级标准文本", "输出等级 / 画像 / 切入点 / 证据评论"], C.steel],
    ["⑥ 线索生成(L4)", ["写入 / 更新 lead 表", "每用户一条当前有效线索", "按 skill_version 可重新生成,旧结果保留", "证据评论 ID + 内容随线索存储"], C.navy],
    ["⑦ 审核与导出(L5)", ["列表按等级 / 品牌 / 车型 / 审核状态筛选", "详情页展示证据与画像,页内人工审核", "CSV 导出(UTF-8 BOM)", "审核数据沉淀为 Prompt 优化样本"], C.navy],
  ];
  const bw = 3.06, bh = 1.62, gapX = 0.16;
  // 第一行 4 个,第二行 3 个
  nodes.forEach((n, i) => {
    const row = i < 4 ? 0 : 1;
    const col = i < 4 ? i : i - 4;
    const x = 0.45 + col * (bw + gapX), y = row === 0 ? 1.15 : 3.15;
    card(s, x, y, bw, bh, n[2]);
    s.addText(n[0], { x: x + 0.16, y: y + 0.08, w: bw - 0.28, h: 0.28, fontFace: F, fontSize: 10.5, bold: true, color: C.navy, margin: 0 });
    lines(s, x + 0.16, y + 0.4, bw - 0.28, bh - 0.5, n[1], { fontSize: 8, color: C.muted });
    if (row === 0 && col < 3) arrowR(s, x + bw + 0.01, y + bh / 2 - 0.08, 0.14);
    if (row === 1 && col < 2) arrowR(s, x + bw + 0.01, y + bh / 2 - 0.08, 0.14);
  });
  // ④ → ⑤ 换行肘形连接:④底部下探 → 虚线横穿 → 箭头入⑤顶部
  const c4x = 0.45 + 3 * (bw + gapX) + bw / 2, c1x = 0.45 + bw / 2;
  s.addShape(p.shapes.LINE, { x: c4x, y: 2.77, w: 0, h: 0.19, line: { color: C.cyan, width: 1.25 } });
  s.addShape(p.shapes.LINE, { x: c1x, y: 2.96, w: c4x - c1x, h: 0, line: { color: C.cyan, width: 1.25, dashType: "dash" } });
  s.addShape(p.shapes.DOWN_ARROW, { x: c1x - 0.09, y: 2.96, w: 0.18, h: 0.19, fill: { color: C.cyan } });

  // 底部:漏斗式成本控制 + 任务链
  const y2 = 5.05;
  card(s, 0.45, y2, 6.28, 1.9, C.gA);
  s.addText("漏斗式成本控制(以测试集为例)", { x: 0.61, y: y2 + 0.1, w: 6, h: 0.28, fontFace: F, fontSize: 10.5, bold: true, color: C.navy, margin: 0 });
  const fun = [
    ["45 视频", "45 个语境任务", C.cyanDeep, 1.15],
    ["2.38 万评论", "≈800 个筛选批任务", C.steel, 1.5],
    ["候选用户", "仅购车相关进入 Skill ③", "2B7A5B", 1.5],
    ["H/A 高意向线索", "销售直接跟进", C.gH, 1.35],
  ];
  let fx = 0.61;
  fun.forEach((f2, i) => {
    chip(s, fx, y2 + 0.5, f2[3], 0.4, f2[0], f2[2], C.white, 8.5);
    s.addText(f2[1], { x: fx - 0.05, y: y2 + 0.95, w: f2[3] + 0.15, h: 0.5, fontFace: F, fontSize: 7.5, color: C.muted, align: "center", margin: 0 });
    if (i < fun.length - 1) arrowR(s, fx + f2[3] + 0.02, y2 + 0.62, 0.12);
    fx += f2[3] + 0.18;
  });
  s.addText("先准确率、后召回率:无效评论在 ③ 被过滤,仅候选用户消耗用户级分析 Token。",
    { x: 0.61, y: y2 + 1.5, w: 6.0, h: 0.3, fontFace: F, fontSize: 8, color: C.muted, italic: true, margin: 0 });

  card(s, 6.95, y2, 5.93, 1.9, C.cyan);
  s.addText("任务链驱动(数据库任务表,无消息队列)", { x: 7.11, y: y2 + 0.1, w: 5.6, h: 0.28, fontFace: F, fontSize: 10.5, bold: true, color: C.navy, margin: 0 });
  lines(s, 7.11, y2 + 0.44, 5.65, 1.4, [
    "导入完成 → 为无当前版本结果的视频创建 video_context 任务",
    "某视频语境成功 → 该视频评论按批创建 screening 任务",
    "全部筛选完成 → 代码聚合候选用户 → 创建 user_analysis 任务",
    "用户分析成功 → 写入 / 更新 lead;各阶段结果分开保存,",
    "下游失败无需重跑上游(分阶段保存)",
  ], { fontSize: 8.5, color: C.muted });
})();

/* ================= S4 数据模型 ================= */
(function s4() {
  const s = p.addSlide();
  header(s, 4, "数据模型(MySQL,7 张表)", "L1 原始数据与分析结果分离;结果多版本并存,支持升级 Skill 版本后对历史数据重新分析");

  function table(x, y, w, h, name, color, fields, note) {
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: C.white }, line: { color: C.line, width: 0.75 } });
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h: 0.3, fill: { color } });
    s.addText(name, { x: x + 0.08, y, w: w - 0.16, h: 0.3, fontFace: MONO, fontSize: 9.5, bold: true, color: C.white, valign: "middle", margin: 0 });
    lines(s, x + 0.1, y + 0.38, w - 0.2, h - 0.44, fields, { fontSize: 7.5, color: C.ink });
    if (note) s.addText(note, { x, y: y + h + 0.02, w, h: 0.2, fontFace: F, fontSize: 7, color: C.muted, margin: 0 });
  }

  // L1 分组框
  s.addShape(p.shapes.RECTANGLE, { x: 0.4, y: 1.28, w: 4.05, h: 5.0, fill: { color: "EDF3FB" }, line: { color: C.steel, width: 0.75, dashType: "dash" } });
  s.addText("L1 原始数据(raw_data 全量保留)", { x: 0.52, y: 1.34, w: 3.8, h: 0.24, fontFace: F, fontSize: 8.5, bold: true, color: C.steel, margin: 0 });

  table(0.55, 1.66, 3.75, 1.34, "video", C.cyanDeep, [
    "UK platform + external_id (aweme_id)",
    "title / description / tags(JSON,解析自话题)",
    "预留:author、account_type、publish_time、",
    "transcript、preset_brand/model(当前为空)",
  ]);
  table(1.6, 3.12, 2.7, 1.06, "platform_user", C.cyanDeep, [
    "UK platform + external_id (sec_uid)",
    "nickname;预留 avatar / bio / region",
  ]);
  table(0.55, 4.3, 3.75, 1.34, "comment", C.cyanDeep, [
    "UK platform + external_id (comment_id)",
    "FK video_id → video;FK user_id → platform_user",
    "content / comment_time(空评论导入即跳过)",
    "预留:like_count、reply_count、is_reply",
  ]);

  // 中列
  table(5.0, 1.66, 3.9, 1.5, "analysis_task", C.steel, [
    "幂等 UK task_type+target_type+target_id",
    "        +skill_version(同对象同版本不重复)",
    "status: pending/running/success/failed",
    "payload(评论批次 ID 列表)· attempt_count ≤ 3",
  ]);
  table(5.0, 3.44, 3.9, 1.5, "analysis_result", C.steel, [
    "target_type+target_id+skill_id+skill_version",
    "result(JSON)· confidence · status · error",
    "记录 model_name / prompt_version",
    "多版本并存不覆盖,业务读当前生效版本",
  ]);
  table(5.0, 5.22, 3.9, 1.06, "llm_call_log", C.gC, [
    "skill_id/version · model · prompt_version",
    "tokens · duration_ms · error · retry_count",
  ]);

  // 右列 lead
  table(9.55, 1.66, 3.35, 2.6, "lead", C.navy, [
    "FK user_id(每用户一条当前有效线索)",
    "grade(H/A/B/C)· is_valid · status",
    "target_brands / models · summary",
    "purchase_stage · core_needs · concerns",
    "purchase_time · usage_scenario",
    "entry_point · verification_questions",
    "evidence(JSON:评论 ID + 内容)",
    "confidence · skill_version",
    "review_status / review_tags / review_note",
  ]);

  // 关系线(正尺寸 + beginArrowType,避免负宽高)
  s.addShape(p.shapes.LINE, { x: 1.0, y: 3.0, w: 0, h: 1.3, line: { color: C.steel, width: 1.25, beginArrowType: "triangle" } });  // comment → video(左侧走廊)
  s.addShape(p.shapes.LINE, { x: 2.6, y: 4.18, w: 0, h: 0.12, line: { color: C.steel, width: 1.25, beginArrowType: "triangle" } }); // comment → platform_user
  s.addShape(p.shapes.LINE, { x: 4.5, y: 2.0, w: 0.5, h: 0, line: { color: C.gC, width: 1.25, dashType: "dash", beginArrowType: "triangle" } });
  s.addText("虚线:target_type + target_id 泛化引用 L1 各表", { x: 5.05, y: 1.4, w: 3.85, h: 0.2, fontFace: F, fontSize: 7.5, color: C.muted, margin: 0 });
  s.addShape(p.shapes.LINE, { x: 8.9, y: 2.4, w: 0.65, h: 0, line: { color: C.navy, width: 1.25, endArrowType: "triangle" } });
  s.addText("由 user_lead_analysis 成功结果写入 / 更新", { x: 9.55, y: 4.32, w: 3.35, h: 0.22, fontFace: F, fontSize: 7.5, color: C.navy, margin: 0 });

  // 底部原则
  const principles = [
    ["原始数据不可覆盖", "L1 三表保留完整 raw_data JSON,支持排查、核对与历史重新分析"],
    ["幂等导入", "platform+external_id 唯一键,重复导入只跳过不重写"],
    ["结果多版本并存", "Prompt / 标准变更 → 升 skill_version → 自动重分析,旧结果保留对比"],
    ["审核数据入库", "review_status / tags / note 沉淀为 Prompt 样本、Few-shot 与回归测试集"],
  ];
  principles.forEach((pr, i) => {
    const x = 0.4 + i * 3.16, y = 6.5, w = 3.02, h = 0.78;
    card(s, x, y, w, h, C.cyan);
    s.addText(pr[0], { x: x + 0.14, y: y + 0.06, w: w - 0.24, h: 0.24, fontFace: F, fontSize: 9, bold: true, color: C.navy, margin: 0 });
    s.addText(pr[1], { x: x + 0.14, y: y + 0.32, w: w - 0.24, h: 0.44, fontFace: F, fontSize: 7.5, color: C.muted, margin: 0 });
  });
})();

/* ================= S5 LLM Gateway 与 Skill 机制 ================= */
(function s5() {
  const s = p.addSlide();
  header(s, 5, "LLM Gateway 与 Skill 机制", "横向公共能力:模型可替换、Skill 可版本化独立演进,业务代码零改动");

  // 左:Gateway
  const lx = 0.45, lw = 6.0;
  card(s, lx, 1.15, lw, 5.9, C.cyan);
  s.addText("LLM Gateway(app/llm)", { x: lx + 0.18, y: 1.3, w: lw - 0.36, h: 0.3, fontFace: F, fontSize: 13, bold: true, color: C.navy, margin: 0 });

  s.addText("统一异步接口", { x: lx + 0.18, y: 1.74, w: 3, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.cyanDeep, margin: 0 });
  s.addShape(p.shapes.RECTANGLE, { x: lx + 0.18, y: 2.02, w: lw - 0.36, h: 0.78, fill: { color: "22283A" } });
  lines(s, lx + 0.32, 2.12, lw - 0.6, 0.6, [
    "async def chat(messages, *, model=None, temperature=None,",
    "               response_format=None) -> LLMResponse",
    "# LLMResponse: text · prompt/completion_tokens · duration_ms",
  ], { fontFace: MONO, fontSize: 8.5, color: "9FE8FF" });

  s.addText("Provider 适配层", { x: lx + 0.18, y: 2.98, w: 3, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.cyanDeep, margin: 0 });
  const provs = [
    ["OpenAICompatProvider", "base_url / api_key / model 全部来自 .env;可对接 Qwen(DashScope)、DeepSeek、本地 vLLM / Ollama 等任何 OpenAI 兼容端点"],
    ["MockProvider", "规则生成结构化结果;无真实模型时跑通端到端流程,支撑全部自动化测试(CI 不依赖外部服务)"],
  ];
  provs.forEach((pr, i) => {
    const y = 3.26 + i * 0.92;
    s.addShape(p.shapes.RECTANGLE, { x: lx + 0.18, y, w: lw - 0.36, h: 0.82, fill: { color: "EEF2FA" }, line: { color: C.line, width: 0.5 } });
    s.addText(pr[0], { x: lx + 0.3, y: y + 0.06, w: lw - 0.6, h: 0.24, fontFace: MONO, fontSize: 9, bold: true, color: C.navy, margin: 0 });
    s.addText(pr[1], { x: lx + 0.3, y: y + 0.32, w: lw - 0.6, h: 0.46, fontFace: F, fontSize: 8, color: C.muted, margin: 0 });
  });

  s.addText("内置能力", { x: lx + 0.18, y: 5.32, w: 3, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.cyanDeep, margin: 0 });
  const caps = ["超时控制", "网络 / 超时自动重试 2–3 次", "每次调用落 llm_call_log", "换模型 = 改 .env,业务零改动"];
  caps.forEach((cp, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    chip(s, lx + 0.18 + col * 2.88, 5.62 + row * 0.54, 2.76, 0.44, cp, C.navy, C.white, 8.5);
  });

  // 右:Skill 机制
  const rx = 6.75, rw = 6.15;
  card(s, rx, 1.15, rw, 5.9, C.steel);
  s.addText("Skill 机制(app/skills)", { x: rx + 0.18, y: 1.3, w: rw - 0.36, h: 0.3, fontFace: F, fontSize: 13, bold: true, color: C.navy, margin: 0 });

  s.addText("一个 Skill = 三要素", { x: rx + 0.18, y: 1.74, w: 4, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.cyanDeep, margin: 0 });
  const tri = [
    ["YAML 配置", "skill_id · 版本 · 模型参数 · prompt 路径", "configs/*.yaml"],
    ["Prompt 模板", "文件名带版本号,独立调优", "prompts/*_v1.txt"],
    ["Pydantic Schema", "输入 / 输出结构强校验", "schemas/skills.py"],
  ];
  tri.forEach((t, i) => {
    const x = rx + 0.18 + i * 1.98, y = 2.02, w = 1.86, h = 1.0;
    s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: "EEF2FA" }, line: { color: C.line, width: 0.5 } });
    s.addText(t[0], { x: x + 0.08, y: y + 0.06, w: w - 0.16, h: 0.24, fontFace: F, fontSize: 8.5, bold: true, color: C.navy, margin: 0 });
    s.addText(t[1], { x: x + 0.08, y: y + 0.32, w: w - 0.16, h: 0.4, fontFace: F, fontSize: 7.5, color: C.muted, margin: 0 });
    s.addText(t[2], { x: x + 0.08, y: y + 0.76, w: w - 0.16, h: 0.2, fontFace: MONO, fontSize: 7, color: C.cyanDeep, margin: 0 });
  });

  s.addText("Skill 执行器统一流程", { x: rx + 0.18, y: 3.2, w: 4, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.cyanDeep, margin: 0 });
  const steps = ["读 YAML 配置", "取上游数据", "组装 Prompt", "调用 Gateway", "解析 JSON", "Pydantic 校验", "失败修复 / 重试", "写 analysis_result"];
  steps.forEach((t, i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = rx + 0.18 + col * 1.5, y = 3.5 + row * 0.72, w = 1.34, h = 0.5;
    flowBox(s, x, y, w, h, `${i + 1}. ${t}`, C.steel, 7.5);
    if (col < 3) arrowR(s, x + w + 0.005, y + 0.17, 0.14);
  });
  // 步骤 4 → 5 换行肘形连接
  const s4x = rx + 0.18 + 3 * 1.5 + 0.67, s5x = rx + 0.18 + 0.67;
  s.addShape(p.shapes.LINE, { x: s4x, y: 4.0, w: 0, h: 0.11, line: { color: C.cyan, width: 1 } });
  s.addShape(p.shapes.LINE, { x: s5x, y: 4.11, w: s4x - s5x, h: 0, line: { color: C.cyan, width: 1, dashType: "dash" } });
  s.addShape(p.shapes.DOWN_ARROW, { x: s5x - 0.07, y: 4.11, w: 0.14, h: 0.11, fill: { color: C.cyan } });
  s.addText("每条结果记录 model_name / prompt_version / skill_version,证据链完整",
    { x: rx + 0.18, y: 4.9, w: rw - 0.36, h: 0.24, fontFace: F, fontSize: 8, color: C.muted, italic: true, margin: 0 });

  s.addShape(p.shapes.RECTANGLE, { x: rx + 0.18, y: 5.24, w: rw - 0.36, h: 0.86, fill: { color: "FDF3E7" }, line: { color: C.gA, width: 0.75 } });
  s.addText("职责边界", { x: rx + 0.3, y: 5.3, w: 2, h: 0.24, fontFace: F, fontSize: 9, bold: true, color: C.gA, margin: 0 });
  s.addText("执行器不决定业务流程,流程由工作流模块控制;新增判断原则优先改 Prompt / Few-shot 并升级 Skill 版本,不修改数据结构、不侵入其他流程。",
    { x: rx + 0.3, y: 5.56, w: rw - 0.6, h: 0.5, fontFace: F, fontSize: 8, color: C.ink, margin: 0 });
  s.addText("示例:configs/comment_lead_screening.yaml + prompts/comment_lead_screening_v1.txt + CommentScreeningResult(Pydantic)",
    { x: rx + 0.18, y: 6.28, w: rw - 0.36, h: 0.44, fontFace: MONO, fontSize: 7.5, color: C.cyanDeep, margin: 0 });
})();

/* ================= S6 三个核心 Skill 与分级标准 ================= */
(function s6() {
  const s = p.addSlide();
  header(s, 6, "三个核心 LLM Skill 与 H/A/B/C 分级标准", "全部业务语义判断集中在 3 个 Skill;分级以购车决策阶段与行动信号为主判据");

  const th = (t) => ({ text: t, options: { fill: { color: C.navy }, color: "FFFFFF", bold: true, fontSize: 8.5, valign: "middle" } });
  const td = (t, opts) => ({ text: t, options: Object.assign({ fontSize: 8, color: C.ink, valign: "top" }, opts || {}) });
  const rows = [
    [th(""), th("① video_context_analysis 视频语境理解"), th("② comment_lead_screening 评论线索筛选"), th("③ user_lead_analysis 用户综合分析")],
    [td("粒度", { bold: true }), td("每视频 1 次,结果全评论复用"), td("每批 30 条评论(可配 20–50)"), td("每候选用户 1 次")],
    [td("输入", { bold: true }), td("标题、文案、话题标签;预留转写、账号类型、预置品牌车型"), td("视频语境结果 + 评论批(带唯一 ID)+ 线索判断原则"), td("用户全部有效评论(附各自视频语境)+ 统计特征 + 分级标准文本;预留用户主页")],
    [td("输出", { bold: true }), td("品牌 / 车型 / 内容类型 / 主题 / 受众 / 竞品 / 商业属性 / 分析注意事项"), td("每条评论:有意义 · 汽车相关 · 购车相关 · 疑似营销 · 意向信号 · 品牌车型 · 强度 · 理由 · 置信度"), td("等级 · 购车阶段 · 品牌车型 · 需求 · 顾虑 · 时间 · 场景 · 切入点 · 待确认问题 · 证据 · 置信度")],
    [td("关键策略", { bold: true }), td("为评论理解提供上下文,避免逐条重复分析视频,压缩 Token 成本"), td("区分情绪 / 兴趣 / 需求 / 交易四级;负面表达含换车需求不过滤;Few-shot 覆盖典型负样本"), td("画像严格限定购车转化相关,无证据输出未知;不推断职业 / 收入 / 家庭")],
  ];
  s.addTable(rows, {
    x: 0.45, y: 1.12, w: 12.45, colW: [0.85, 3.86, 3.87, 3.87],
    border: { pt: 0.5, color: C.line }, fill: { color: C.white },
    fontFace: F, rowH: [0.3, 0.28, 0.62, 0.7, 0.62], margin: 0.04, valign: "top",
  });

  // 左下:分级标准
  s.addText("H/A/B/C 分级标准(购车决策阶段 + 行动信号)", { x: 0.45, y: 4.28, w: 6.5, h: 0.26, fontFace: F, fontSize: 10.5, bold: true, color: C.navy, margin: 0 });
  const grades = [
    ["H", "极高意向 · 交易 / 行动", "询价与落地价、优惠、置换补贴、金融方案、门店 / 库存 / 交付、试驾、明确近期购买", C.gH],
    ["A", "较强意向 · 主动评估", "竞品对比、配置差异、养车成本、保值率 / 售后 / 质量、真实使用场景评估", C.gA],
    ["B", "中等意向 · 产品兴趣", "外观内饰讨论、浅层配置咨询、空间颜色兴趣、表示有点心动、未来可能考虑", C.gB],
    ["C", "较低意向 · 弱相关", "普通吐槽、玩梗、浅层情绪表达,缺乏具体需求与购买计划", C.gC],
  ];
  grades.forEach((g, i) => {
    const y = 4.62 + i * 0.52, x = 0.45, w = 6.5;
    s.addShape(p.shapes.RECTANGLE, { x, y, w: 0.42, h: 0.42, fill: { color: g[3] } });
    s.addText(g[0], { x, y, w: 0.42, h: 0.42, fontFace: F, fontSize: 14, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addShape(p.shapes.RECTANGLE, { x: x + 0.42, y, w: w - 0.42, h: 0.42, fill: { color: C.white }, line: { color: C.line, width: 0.5 } });
    s.addText([
      { text: g[1] + "  ", options: { bold: true, fontSize: 8.5, color: C.ink } },
      { text: g[2], options: { fontSize: 7.5, color: C.muted } },
    ], { x: x + 0.52, y, w: w - 0.56, h: 0.42, fontFace: F, valign: "middle", margin: 0 });
  });
  s.addText("分级标准文本作为 Prompt 的一部分,可随 Skill 版本迭代;等级边界通过标注集与 Few-shot 固化。",
    { x: 0.45, y: 6.74, w: 6.5, h: 0.26, fontFace: F, fontSize: 8, color: C.muted, italic: true, margin: 0 });

  // 右下:内部状态 + 批次防错位
  const rx = 7.1, rw = 5.83;
  card(s, rx, 4.28, rw, 1.12, C.gC);
  s.addText("线索池保护:内部过滤状态", { x: rx + 0.14, y: 4.36, w: rw - 0.28, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.navy, margin: 0 });
  s.addText("无意义 / 与汽车无关 / 无购车意向 / 疑似营销 / 疑似水军 / 信息不足 —— 仅保存于 analysis_result,不进入 H/A/B/C 线索列表,避免污染 C 级线索池。",
    { x: rx + 0.14, y: 4.62, w: rw - 0.28, h: 0.66, fontFace: F, fontSize: 8, color: C.muted, margin: 0 });

  card(s, rx, 5.56, rw, 1.44, C.gA);
  s.addText("批量处理防错位", { x: rx + 0.14, y: 5.64, w: rw - 0.28, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.navy, margin: 0 });
  const chain = ["评论带唯一 ID", "输出条数 + ID 集合强校验", "不一致整批重试", "再失败拆半", "超长评论单独成批"];
  let cx = rx + 0.14;
  const cw = [0.95, 1.5, 1.02, 0.75, 1.02];
  chain.forEach((t, i) => {
    chip(s, cx, 6.0, cw[i], 0.56, t, C.steel, C.white, 6.5);
    if (i < chain.length - 1) arrowR(s, cx + cw[i] + 0.003, 6.24, 0.065);
    cx += cw[i] + 0.075;
  });
  s.addText("输出与输入不一致的批次不入库,保证评论结果与 ID 严格对应。",
    { x: rx + 0.14, y: 6.66, w: rw - 0.28, h: 0.26, fontFace: F, fontSize: 7.5, color: C.muted, italic: true, margin: 0 });
})();

/* ================= S7 任务调度与可靠性 ================= */
(function s7() {
  const s = p.addSlide();
  header(s, 7, "任务调度与可靠性", "数据库任务表 + 进程内 asyncio Worker:无消息队列的最小可靠执行方案");

  // 左:状态机
  const lx = 0.45, lw = 6.1;
  card(s, lx, 1.15, lw, 3.0, C.cyan);
  s.addText("任务状态机(analysis_task.status)", { x: lx + 0.16, y: 1.27, w: lw - 0.32, h: 0.28, fontFace: F, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  // 状态节点
  flowBox(s, lx + 0.3, 2.0, 1.3, 0.52, "pending", C.gC, 10);
  flowBox(s, lx + 2.4, 2.0, 1.3, 0.52, "running", C.steel, 10);
  flowBox(s, lx + 4.5, 1.62, 1.3, 0.52, "success", C.gB, 10);
  flowBox(s, lx + 4.5, 2.42, 1.3, 0.52, "failed", C.gH, 10);
  arrowR(s, lx + 1.66, 2.18, 0.68);
  s.addText("Worker 领取", { x: lx + 1.56, y: 1.86, w: 0.95, h: 0.2, fontFace: F, fontSize: 7, color: C.muted, align: "center", margin: 0 });
  s.addShape(p.shapes.LINE, { x: lx + 3.72, y: 1.95, w: 0.76, h: 0.17, flipV: true, line: { color: C.gB, width: 1.25, endArrowType: "triangle" } });
  s.addShape(p.shapes.LINE, { x: lx + 3.72, y: 2.4, w: 0.76, h: 0.17, line: { color: C.gH, width: 1.25, endArrowType: "triangle" } });
  // failed → pending 重试回路
  s.addShape(p.shapes.LINE, { x: lx + 5.15, y: 2.94, w: 0, h: 0.44, line: { color: C.gA, width: 1.25 } });
  s.addShape(p.shapes.LINE, { x: lx + 0.95, y: 3.38, w: 4.2, h: 0, line: { color: C.gA, width: 1.25 } });
  s.addShape(p.shapes.LINE, { x: lx + 0.95, y: 2.52, w: 0, h: 0.86, line: { color: C.gA, width: 1.25, beginArrowType: "triangle" } });
  s.addText("attempt_count < 3 自动重试;最终失败 → 页面人工重试", { x: lx + 1.1, y: 3.44, w: 4.6, h: 0.22, fontFace: F, fontSize: 7.5, color: C.gA, margin: 0 });
  s.addText("进程重启:遗留 running 全部重置为 pending 续跑(状态只存数据库,断点可恢复)",
    { x: lx + 0.16, y: 3.76, w: lw - 0.32, h: 0.3, fontFace: F, fontSize: 8, color: C.muted, margin: 0 });

  // 左下:幂等 + Worker + 版本化
  card(s, lx, 4.32, lw, 0.86, C.steel);
  s.addText("幂等键", { x: lx + 0.16, y: 4.4, w: 2, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.navy, margin: 0 });
  s.addText("task_type + target_type + target_id + skill_version", { x: lx + 0.16, y: 4.66, w: lw - 0.32, h: 0.24, fontFace: MONO, fontSize: 9, color: C.cyanDeep, margin: 0 });
  s.addText("同对象同版本不重复执行", { x: lx + 3.9, y: 4.4, w: 2.1, h: 0.24, fontFace: F, fontSize: 8, color: C.muted, margin: 0 });

  card(s, lx, 5.3, lw, 0.8, C.steel);
  s.addText("Worker 运行参数", { x: lx + 0.16, y: 5.38, w: 3, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.navy, margin: 0 });
  s.addText("FastAPI lifespan 内 asyncio 轮询领取(领取即置 running);LLM 并发度 WORKER_CONCURRENCY=3 可配;上游完成自动创建下游任务",
    { x: lx + 0.16, y: 5.62, w: lw - 0.32, h: 0.42, fontFace: F, fontSize: 8, color: C.muted, margin: 0 });

  card(s, lx, 6.22, lw, 0.8, C.steel);
  s.addText("版本化重分析", { x: lx + 0.16, y: 6.3, w: 3, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.navy, margin: 0 });
  s.addText("Prompt / 分级标准变更 → 升级 skill_version → 历史数据自动生成新任务重新分析;新旧结果并存,可对比评测",
    { x: lx + 0.16, y: 6.54, w: lw - 0.32, h: 0.42, fontFace: F, fontSize: 8, color: C.muted, margin: 0 });

  // 右:异常处理表
  const rx = 6.85, rw = 6.05;
  s.addText("异常处理矩阵", { x: rx, y: 1.15, w: 4, h: 0.28, fontFace: F, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  const eh = (a, b2) => [
    { text: a, options: { fontSize: 8.5, bold: true, color: C.ink, valign: "middle" } },
    { text: b2, options: { fontSize: 8.5, color: C.muted, valign: "middle" } },
  ];
  const erows = [
    [{ text: "异常场景", options: { fill: { color: C.navy }, color: "FFFFFF", bold: true, fontSize: 9, valign: "middle" } },
     { text: "处理策略", options: { fill: { color: C.navy }, color: "FFFFFF", bold: true, fontSize: 9, valign: "middle" } }],
    eh("LLM 超时 / 网络异常", "Gateway 层自动重试 2–3 次"),
    eh("JSON 解析失败 / Schema 不符 / 空返回", "执行器自动修复尝试 → 重新调用 → 多次失败标 failed"),
    eh("批次输出与输入 ID 不一致", "整批重试 → 拆半重试 → 标 failed"),
    eh("任务多次失败(≥3 次)", "记录错误原因,任务页一键人工重试"),
    eh("进程重启 / 崩溃", "running 任务重置 pending 自动续跑"),
    eh("所有 LLM 调用", "落 llm_call_log:模型、token、耗时、错误、重试次数"),
  ];
  s.addTable(erows, {
    x: rx, y: 1.5, w: rw, colW: [2.55, 3.5],
    border: { pt: 0.5, color: C.line }, fill: { color: C.white },
    fontFace: F, rowH: [0.32, 0.5, 0.62, 0.5, 0.5, 0.5, 0.62], margin: 0.05,
  });

  card(s, rx, 5.55, rw, 1.47, C.gB);
  s.addText("分阶段保存,失败影响最小化", { x: rx + 0.16, y: 5.65, w: rw - 0.32, h: 0.26, fontFace: F, fontSize: 10, bold: true, color: C.navy, margin: 0 });
  lines(s, rx + 0.16, 5.95, rw - 0.32, 1.0, [
    "视频语境 / 评论筛选 / 用户分析三阶段结果分别落库;",
    "用户分析失败时无需重跑视频与评论分析;",
    "全部输出经 Pydantic 强校验后才入库,保证下游数据质量。",
  ], { fontSize: 8.5, color: C.muted });
})();

/* ================= S8 业务应用与评测体系 ================= */
(function s8() {
  const s = p.addSlide();
  header(s, 8, "业务应用层与评测体系", "最小业务闭环:线索查看 → 人工审核 → 数据沉淀;评测脚手架支撑 Prompt 迭代与版本回归");

  // 列 1:页面与 API
  const x1 = 0.45, w1 = 4.4;
  card(s, x1, 1.15, w1, 3.4, C.navy);
  s.addText("页面与 JSON API(L5)", { x: x1 + 0.16, y: 1.27, w: w1 - 0.32, h: 0.28, fontFace: F, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  const pages = [
    ["/", "任务页:Excel 导入(新增/跳过统计)、启动分析、阶段进度轮询、失败任务重试"],
    ["/leads", "线索列表:按等级/品牌/车型/审核状态筛选,导出带 BOM 的 CSV"],
    ["/leads/{id}", "线索详情:证据评论与所在视频 · 筛选结果 · 意向画像 · 分级理由 · 页内审核"],
  ];
  pages.forEach((pg, i) => {
    const y = 1.62 + i * 0.72;
    s.addText(pg[0], { x: x1 + 0.16, y, w: 1.06, h: 0.3, fontFace: MONO, fontSize: 9, bold: true, color: C.cyanDeep, margin: 0 });
    s.addText(pg[1], { x: x1 + 1.24, y, w: w1 - 1.44, h: 0.68, fontFace: F, fontSize: 7.5, color: C.muted, margin: 0 });
  });
  s.addShape(p.shapes.LINE, { x: x1 + 0.16, y: 3.8, w: w1 - 0.32, h: 0, line: { color: C.line, width: 0.75 } });
  lines(s, x1 + 0.16, 3.9, w1 - 0.32, 0.6, [
    "POST /api/import · /api/analysis/start · /api/tasks/{id}/retry",
    "GET  /api/analysis/progress · /api/leads(筛选+分页)",
    "GET  /api/leads/{id} · /api/leads/export · POST …/review",
  ], { fontFace: MONO, fontSize: 7.5, color: C.ink });

  // 列 1 下:审核闭环
  card(s, x1, 4.7, w1, 2.32, C.cyan);
  s.addText("人工审核闭环(不自动回灌模型)", { x: x1 + 0.16, y: 4.8, w: w1 - 0.32, h: 0.26, fontFace: F, fontSize: 10.5, bold: true, color: C.navy, margin: 0 });
  lines(s, x1 + 0.16, 5.12, w1 - 0.32, 0.9, [
    "review_status:未审核 / 有效 / 无效",
    "review_tags 多选:等级偏高 · 等级偏低 · 疑似水军 · 无真实购车需求 · 画像错误 · 切入点无价值",
    "review_note:自由备注",
  ], { fontSize: 8, color: C.muted });
  const uses = ["Prompt 优化样本", "Few-shot 案例", "回归测试集"];
  uses.forEach((u, i) => {
    chip(s, x1 + 0.16 + i * 1.42, 6.42, 1.3, 0.42, u, C.navy, C.white, 7.5);
    if (i < 2) arrowR(s, x1 + 0.16 + i * 1.42 + 1.31, 6.56, 0.09);
  });

  // 列 2:评测指标
  const x2 = 5.05, w2 = 4.15;
  card(s, x2, 1.15, w2, 5.87, C.gB);
  s.addText("MVP 评测指标(四组)", { x: x2 + 0.16, y: 1.27, w: w2 - 0.32, h: 0.28, fontFace: F, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  const metricGroups = [
    ["评论筛选", ["无意义评论过滤准确率", "购车相关评论识别准确率", "疑似营销评论识别准确率", "无效评论误入率"]],
    ["用户分级", ["H 级准确率 · H/A 合并准确率", "H/A/B/C 混淆矩阵", "高意向用户召回率 · 证据引用准确率"]],
    ["画像质量", ["品牌车型 / 核心需求 / 顾虑准确率", "无证据推断率 · 切入点可用率"]],
    ["工程指标", ["JSON 输出合格率 · 任务成功率", "自动重试成功率", "平均单评论 / 单用户分析成本与耗时"]],
  ];
  let my = 1.64;
  metricGroups.forEach((g) => {
    chip(s, x2 + 0.16, my, 1.1, 0.3, g[0], C.gB, C.white, 8.5);
    const items = g[1].map((t, i) => ({ t, opts: { bullet: { code: "2022" }, breakLine: i < g[1].length - 1 } }));
    lines(s, x2 + 1.4, my - 0.01, w2 - 1.6, g[1].length * 0.21 + 0.1, items, { fontSize: 8, color: C.muted });
    my += g[1].length * 0.225 + 0.24;
  });
  s.addShape(p.shapes.LINE, { x: x2 + 0.16, y: my + 0.02, w: w2 - 0.32, h: 0, line: { color: C.line, width: 0.75 } });
  s.addText("业务验证重点(MVP 只看前三项)", { x: x2 + 0.16, y: my + 0.12, w: w2 - 0.32, h: 0.24, fontFace: F, fontSize: 9.5, bold: true, color: C.navy, margin: 0 });
  lines(s, x2 + 0.16, my + 0.4, w2 - 0.32, 0.9, [
    "① 每万条评论产出的有效线索数量",
    "② H/A 级线索人工认可率  ③ H 级线索人工认可率",
    "(不以最终成交率评价 MVP)",
  ], { fontSize: 8.5, color: C.muted });

  // 列 3:评测脚手架 + 测试
  const x3 = 9.5, w3 = 3.4;
  card(s, x3, 1.15, w3, 2.9, C.gA);
  s.addText("评测脚手架", { x: x3 + 0.16, y: 1.27, w: w3 - 0.32, h: 0.28, fontFace: F, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  const evalFlow = [
    ["make_annotation_template.py", "分析完成后生成标注模板 CSV"],
    ["业务人工标注", "是否有意义 / 购车相关 / 意向强度等"],
    ["evaluate.py", "对照标注计算全部核心指标"],
  ];
  evalFlow.forEach((e2, i) => {
    const y = 1.66 + i * 0.78;
    s.addShape(p.shapes.RECTANGLE, { x: x3 + 0.16, y, w: w3 - 0.32, h: 0.64, fill: { color: "EEF2FA" }, line: { color: C.line, width: 0.5 } });
    s.addText(e2[0], { x: x3 + 0.26, y: y + 0.05, w: w3 - 0.52, h: 0.24, fontFace: MONO, fontSize: 7.5, bold: true, color: C.navy, margin: 0 });
    s.addText(e2[1], { x: x3 + 0.26, y: y + 0.32, w: w3 - 0.52, h: 0.28, fontFace: F, fontSize: 7.5, color: C.muted, margin: 0 });
    if (i < 2) s.addShape(p.shapes.DOWN_ARROW, { x: x3 + w3 / 2 - 0.07, y: y + 0.645, w: 0.14, h: 0.12, fill: { color: C.gA } });
  });

  card(s, x3, 4.2, w3, 2.82, C.steel);
  s.addText("自动化测试", { x: x3 + 0.16, y: 4.32, w: w3 - 0.32, h: 0.26, fontFace: F, fontSize: 11, bold: true, color: C.navy, margin: 0 });
  lines(s, x3 + 0.16, 4.64, w3 - 0.32, 2.3, [
    { t: "17 个测试模块,全部基于 MockProvider,不依赖真实 LLM 与外部服务。", opts: {} },
    { t: "单元:导入幂等 · 标签解析 · 聚合统计 · Schema 校验 · 批次 ID 一致性 · 重试与断点恢复。", opts: { breakLine: true } },
    { t: "集成:小样本端到端(导入 → 3 Skill → 聚合 → lead 产出)。", opts: { breakLine: true } },
    { t: "真实模型联调:抽样 2–3 个视频跑通并初步调优 Prompt", opts: {} },
  ], { fontSize: 8, color: C.muted });
})();

p.writeFile({ fileName: "../DriveIntent技术方案.pptx" }).then(() => console.log("OK"));
