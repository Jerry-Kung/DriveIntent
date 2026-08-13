This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. 项目概述

- **项目名**：DriveIntent，AI-powered automotive social media intent and lead intelligence
- **定位**：从海量视频评论信息中挖掘高价值的，服务于车企客户销售行为的潜在线索
- **完整愿景与功能规划**：见 `README.md`
- **当前阶段**：项目 V1（1.0）正式版开发阶段：微服务化 + 对外 API，遵循“小步快跑”式开发原则。

## 2. 工作规范

- 使用简体中文回答问题、编写文档
- 【临时要求】近期claude code工具偶现中文编码异常bug，往文件中写入中文内容后请检查是否存在乱码/编码格式是否正确，出现乱码请及时修复，如修复失败可临时采用English作为写入语言，并在完成任务后向我报告；
- 新版本的需求分析、模块设计、任务规划等重量级更新，讨论明确后归档到./claude_docs/versions对应版本目录。轻量级的代码改动/bug修复可以直接执行，不写文档
- 版本目录结构、版本文档职责、代码内版本命名（Prompt/Skill 版本号跟随项目版本号）遵循./claude_docs/versions/VERSIONING.md，每次发版按其检查清单执行
- 涉及整体架构/核心数据结构/跨模块接口契约/前后端配合等重要变更行为的改动，请同步更新./claude_docs中的相关文档
- 默认不进行全量文档阅读，仅阅读与当前任务直接相关的项目文档，默认不阅读历史版本归档文件
- 如有必要更新CLAUDE.md与README.md等核心文档，遵守最小化更新原则，不得添加任务无关的冗余内容
