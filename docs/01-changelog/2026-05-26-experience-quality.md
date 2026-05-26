---
tags: [experience, quality, decay, conflict-detection, dashboard]
date: 2026-05-26
summary: 经验质量保障 — 置信度衰减 + 使用计数 + 冲突检测 + 质量仪表盘
status: done
---

## [19:50] 经验质量保障实施

- 用户要求：实现层2经验质量保障（置信度衰减、使用计数、冲突检测）
- 改动内容：
  - `experience_reader.py`：`get_tool_tips()` 记录 `used_files`，追踪哪些经验文件被使用
  - `experience_ui.py`：`_decay_and_reinforce()` 所有经验 -0.01，被使用过的 +0.02 回涨
  - `experience_ui.py`：`_merge_bullets_replace()` 三段相似度（>75%替换/55-75%标记待确认/<55%追加）
  - `experience_ui.py`：`_print_quality_dashboard()` 输出经验质量统计
  - frontmatter 新增 `pending_review` 标记
- 改动时间：2026-05-26 19:50

## 设计决策

- 不建 `reader_agent.py` 子Agent：Reflector 已在读经验文件，质量保障用纯规则层解决，省去 LLM 调用开销
- 三段冲突检测阈值：>75% 高置信替换，55-75% 保留旧 bullet 并标记 `[待确认]`，<55% 直接追加
- 衰减 -0.01 + 回涨 +0.02：被使用的经验净涨 +0.01，未使用的净跌 -0.01，自然产生区分度
