---
updated: 2026-05-27
---

# Robocode 开发索引

## 当前状态

| 模块 | 状态 | 完成度 |
|------|------|--------|
| Phase 1 — 核心 Agent 框架 | ✅ 完成 | 100% (75/75) |
| Phase 2 — 代码编辑安全 | ✅ 完成 | 100% |
| voice-stt-control | ✅ 完成 | 78% (25/32，待硬件手动测试) |
| monitorable-robust-analytics | ✅ 完成 | 88% (~57/65) |
| 6D 标定 | ✅ 可用 | 4 脚本 + skill.md |
| 6D 抓取 (run_grasp.py) | ✅ 可用 | VLM → GraspNet → IK 全链路 |
| experience-evolution-system | ✅ 完成 | 95% (76/80) → P0×4 + P1×3 修复，85 tests 全绿 |
| experience-evolution-v2-reflector | ✅ 完成 | LLM 反思层融入 + 可读性改进，57 tests |
| 经验进化 v3 — LLM 驱动合并 | ✅ 完成 | Reflector prompt 重写 + 扁平化 + 硬件注入 + sandbox 放宽 |
| 双层经验系统层1 — ToolGuard 自动注入 | ✅ 完成 | 工具调用时自动推送 @tool_name 关联经验，7个工具 × 33条标注 |
| 经验质量保障 — 衰减/冲突/仪表盘 | ✅ 完成 | 置信度衰减+使用回涨 + 三段冲突检测 + 质量仪表盘 |
| 全量测试 | ✅ 通过 | 419/419 全部通过（2026-05-26 更新） |
| VLM 感知模块 | ✅ 完成 | 24/24 tests 全绿（2026-05-27 更新） |

## 模块地图

```
robocode/
├── cli/           # prompt_toolkit REPL + slash命令 + voice语音
│   ├── app.py            # RobocodeApp 主入口，AgentLoop 集成（679行，已拆分）
│   ├── tools_setup.py    # 工具注册 + handler 映射构建（工厂函数聚合）
│   ├── experience_ui.py  # 经验管家 + 标注面板 + 置信度反馈 + bullet 合并
│   ├── slash.py          # SlashDispatcher（/help /exit /status /tools /audit /resume /backend /estop）
│   └── voice.py          # VoiceController（faster-whisper + webrtcvad）
├── agent/         # ReAct Agent
│   ├── core.py    # AgentLoop + SYSTEM_PROMPT + tool 执行
│   ├── context.py # ContextMemory（消息管理 + checkpoint 序列化）
│   ├── reflector.py         # LLM 反思器（经验 bullets 产出）
│   ├── experience_manager.py # 规则层分析（physics/annotations/call_flows）
│   ├── experience_filesystem.py # 扁平文件存储（无分类）
│   └── experience_reader.py  # 经验索引读取 → 注入 SYSTEM_PROMPT
├── llm/           # LLM Provider
│   ├── base.py    # LLMProvider 抽象 + StreamEvent
│   └── deepseek_provider.py  # DeepSeek V4 via AsyncOpenAI
├── tools/         # 工具层（LLM 可见 22+ 工具）
│   ├── registry.py      # ToolEntry + SkillEntry + ToolRegistry
│   ├── motion_tools.py  # 机械臂运动（L1/L2）
│   ├── gripper_tools.py # 夹爪控制（L1/L2）
│   ├── exec_tools.py    # execute_command（L1，受限 shell）
│   ├── codegen_tools.py # 代码沙箱生成执行（L2，write_text 已放开）
│   ├── code_tools.py    # read_file + search_code（L0 只读）
│   ├── patch_tools.py   # apply_patch + run_checks（L1）
│   ├── wrapper_tools.py # 工具模板生成（L0）
│   └── script_tools.py  # 标定/抓取脚本编排
├── orchestrator/  # 安全编排
│   ├── state_machine.py    # 8 态状态机
│   ├── safety.py           # SafetyPolicy（工作空间/速度/关节限制）
│   ├── approval.py         # ApprovalGate（L0/L1/L2 三级审批）
│   ├── tool_guard.py       # ToolGuard（桥接审批+审计+安全）
│   └── protected_files.py  # 11 个受保护文件注册表
├── backends/      # 机器人后端
│   ├── base.py         # RobotBackend ABC
│   └── sdk_backend.py  # EpisodeAPP SDK 适配器
├── persistence/   # 持久化
│   └── db.py      # AuditDB（兼容性重导出 → services/analytics/db.py）
├── services/      # 服务
│   └── analytics/ # 可监测架构（logger / metrics / db / display / resource_tracker）
├── config/
│   └── settings.py     # 全局配置（Provider/Backend/Workspace/Safety/Approval）
└── utils/
    ├── models.py  # 数据模型
    └── cleanup.py # 启动时自动清理
experience/
├── code-experience.md          # 关节耦合规律 + move_robot_xyz 陷阱
├── vlm-desktop-detection.md    # VLM 桌面检测完整成功路径
├── hardware/episode1-spec.md   # URDF 硬件参数（关节限位/零位/连杆/工作空间）
├── index.md                    # 经验索引（标题 + 前 3 条 bullets 摘要）
├── _archive/                   # 归档（合并/淘汰的旧版本）
└── _history/                   # 备份（更新前自动备份）
```

## 按标签索引

| 标签 | 相关日志 |
|------|---------|
| `phase1` | [changelog/04-28](01-changelog/2026-04-28.md) [reviews/04-28](04-reviews/2026-04-28.md) [design/04-28](05-design/2026-04-28.md) |
| `phase2` | [changelog/05-04](01-changelog/2026-05-04.md) [tests/05-04](03-tests/2026-05-04.md) [reviews/05-04](04-reviews/2026-05-04.md) [design/05-04](05-design/2026-05-04.md) |
| `voice` `stt` | [changelog/05-07](01-changelog/2026-05-07.md) [tests/05-07](03-tests/2026-05-07.md) [reviews/05-07](04-reviews/2026-05-07.md) |
| `analytics` `metrics` | [changelog/05-07](01-changelog/2026-05-07.md) [tests/05-07](03-tests/2026-05-07.md) [reviews/05-07](04-reviews/2026-05-07.md) |
| `6d` `grasp` `calibration` | [changelog/04-30](01-changelog/2026-04-30.md) [debug/05-03](02-debug/2026-05-03.md) |
| `bug` `deepseek` | [debug/04-30](02-debug/2026-04-30.md) [debug/05-03](02-debug/2026-05-03.md) |
| `cleanup` `dead-code` | [debug/05-06](02-debug/2026-05-06.md) [changelog/05-06](01-changelog/2026-05-06.md) [changelog/05-15](01-changelog/2026-05-15.md) |
| `experience-evolution` `manager` `merge` `prune` `feedback` | [design/05-14](05-design/2026-05-14.md) [design/05-15](05-design/2026-05-15.md) [changelog/05-15](01-changelog/2026-05-15.md) |
| `reflector` `llm` `readability` `bullets` | [design/05-19](05-design/2026-05-19.md) [changelog/05-19](01-changelog/2026-05-19.md) [tests/05-19](03-tests/2026-05-19.md) |
| `session-management` `ttl` `resume` | [changelog/05-15](01-changelog/2026-05-15.md) |
| `review` `audit` `robustness` `gates` | [reviews/05-15](04-reviews/2026-05-15.md) [reviews/05-19](04-reviews/2026-05-19.md) [reviews/05-21](04-reviews/2026-05-21.md) |
| `hardware` `spec` `arm-span` | [reviews/05-21](04-reviews/2026-05-21.md) |
| `gatekeeper` `full-review` `reflector` `P0` | [reviews/05-19](04-reviews/2026-05-19.md) |
| `experience-evolution` `bugfix` `data-flow` `P0` `P1` | [changelog/05-20](01-changelog/2026-05-20.md) [tests/05-20](03-tests/2026-05-20.md) |
| `resume` `cli` `test` `slash` | [debug/05-21](02-debug/2026-05-21.md) |
| `refactor` `app` `split` `tools` `regression` `cleanup` `skills` `verification` | [changelog/05-21](01-changelog/2026-05-21.md) |
| `experience` `tool-guard` `auto-inject` `@tool_name` | [changelog/05-26](01-changelog/2026-05-26.md) |
| `review` `safety` `observability` `dead-code` `P0` `P1` | [reviews/05-26](04-reviews/2026-05-26.md) |
| `harness` `7-gates` `gate-review` | [reviews/05-26-gates](04-reviews/2026-05-26-harness-gates.md) |
| `experience` `tool-guard` `reader-agent` `dual-layer` | [design/05-21](05-design/dual-layer-experience-system.md) |
| `review` `experience` `dual-layer` `quality` `verification` | [reviews/05-26](04-reviews/2026-05-26.md) |
| `vlm` `perception` `3d` `locate` | [tests/05-27](03-tests/2026-05-27.md) [changelog/05-27](01-changelog/2026-05-27.md) |
| `vlm` `hooks` `bugfix` `message-format` | [debug/05-27](02-debug/2026-05-27.md) |

## 时间线

| 日期 | 关键事件 |
|------|---------|
| 2026-04-28 | Phase 1 全 10 Section 完成，184 tests |
| 2026-04-30 | Bug 修复 + Skills 机制 + 6D 抓取入口 + GitHub 上传 |
| 2026-05-03 | 6D 抓取 11 项 Bug 修复 + ESC async 重写 |
| 2026-05-04 | Phase 2 全 7 Section 完成，228 tests |
| 2026-05-06 | 代码审查 + 死代码清理 + 运行时目录重构，230 tests |
| 2026-05-07 | voice-stt + monitorable-analytics，276 tests |
| 2026-05-11 | 日志系统重构 + / 命令 Tab 补全（SlashCompleter + complete_while_typing） |
| 2026-05-14 | 经验进化系统补齐：update/merge/prune + 置信度反馈 + 决策日志 + 启动清理接入 |
| 2026-05-15 | 最终接入检查：逐方法调用链审计 42/42 通过 + gatekeeper 审查 |
| 2026-05-15 | **QA 全面审查**：OpenSpec 完成度 74.2% + 7 门控审查 + 鲁棒性测试，发现 P0×1 / P1×4 / P2×4 |
| 2026-05-15 | **死代码清理 + 会话管理**：6d_grasp physics 双写修复、experience_pending 队列删除、会话 7 天 TTL + 空会话清理、/resume 箭头选择 |
| 2026-05-19 | **经验进化 v2 — Reflector 融入**：LLM 反思层 + 索引可读性改进 + 建议/反思合并 + P0/P1 修复，57 tests |
| 2026-05-19 | **Gatekeeper 全量审查**：feature/experience-evolution-system 分支 30+ 文件审查，发现 P0×2 / P1×5 / P2×2 |
| 2026-05-20 | **经验进化系统全链路修复**：审查发现 P0×4（analyze_conversation 缺失/解析器失效/签名崩溃/feed_text 丢失）+ P1×3，85 tests 全绿 |
| 2026-05-20 | **经验进化 v3 — LLM 驱动合并**：Reflector prompt 重写（因果优先+自由标签+多场景示例）+ 扁平化分类 + 硬件描述注入 + sandbox 放宽 write_text + LLM 决定合并目标 + confidence 只升不降 |
| 2026-05-21 | **Gatekeeper 审查**：hardware spec 路径修正 + 文档扩展 + 臂展数值修正（447→507mm），PASS 通过 |
| 2026-05-21 | **10 个失败测试修复**：ContextMemory 字段重命名 + ExperienceReader 格式变更 + Voice mock + CLI JSON 断言，396/396 全绿 |
| 2026-05-21 | **FakeEpisodeAPP 去重**：`_SandboxEpisodeAPP` 手工副本 → `_build_sandbox_header()` 从 FakeEpisodeAPP 反射生成，自动补全 2 个遗漏方法 |
| 2026-05-21 | **cli/app.py 拆分重构**：1414 行 → 679 行（-52%），提取 `tools_setup.py`（477 行）+ `experience_ui.py`（376 行） |
| 2026-05-21 | **双层经验系统设计**：主 Agent ToolGuard 自动注入 + 子 Agent index.md 读书人，解决经验不被读取的问题 |
| 2026-05-26 | **双层经验系统层1实现**：工具调用自动注入 @tool_name 关联经验（Push模型），7工具×21标注，Reflector闭环输出@tag |
| 2026-05-26 | **全量审查**：57文件审查，P0×6 / P1×16 / P2×24，安全+可监测+可进化+可驾驭+可迭代+无用代码 |
| 2026-05-26 | **审查修复**：sandbox env收紧 + run_checks边界 + reflector路径遍历 + db列名校验 |
| 2026-05-26 | **附录标注补齐**：12条关节知识bullet加@move_robot_joints，计划映射100%覆盖 |
| 2026-05-26 | **经验质量保障**：置信度衰减(-0.01)+使用回涨(+0.02) + 三段冲突检测(>75%/55-75%/<55%) + 质量仪表盘 |
| 2026-05-26 | **驭工程7-Gate门控审查**：4 PASS / 3 PARTIAL / 0 FAIL，P0×1（运动非幂等resume风险） |
| 2026-05-26 | **双层经验系统层1功能审查**：419 tests 全绿，工具索引9个工具，bullet标签覆盖完整，代码质量良好 |
| 2026-05-27 | **VLM 感知模块完成**：camera_bridge + VlmPerception + FakeVlmPerception + HookRegistry，24 tests 全绿 |
| 2026-05-27 | **Hook 消息格式修复**：tool message → user 消息注入，解决 LLM API 400 错误 |

## 已知问题 / 待办

- ~~P0-1: FakeProvider 缺失（被 8ebbe74 重构删除），测试套件完全无法运行~~ → 已修复，396/396 全绿
- ~~cli/app.py 臃肿（1414 行）~~ → 已拆分：679 行 app.py + 477 行 tools_setup.py + 376 行 experience_ui.py
- ~~FakeEpisodeAPP 重复定义（codegen_tools.py 中的 _SandboxEpisodeAPP 手工副本）~~ → 已修复：反射生成
- **P1-1**: exec_tools shell=True 注入风险（黑名单 + 审批双重防护，但 shell=True 本身是隐患）
- **P1-2**: 受保护文件列表缺少 agent/core.py、motion_tools.py 等关键文件
- **P1-3**: session_summary() success 统计 SQL 条件错误（json_extract boolean vs string）
- **P1-4**: SafetyPolicy.check_speed() 负值通过校验
- voice-stt: 3 个任务待完成（手动测试 + gatekeeper）
- monitorable-analytics: 8 个验证任务待完成
- run_grasp.py: IK/通信失败不区分（增强需求，非阻塞）
- ctypes 线程中断标记：P0-4 已标记，待处理
- **全量审查**：P0×6 / P1×16 / P2×24，详见 [reviews/05-26](04-reviews/2026-05-26.md)
- **经验质量保障**：✅ 置信度衰减 + 使用回涨 + 冲突检测 + 质量仪表盘
- **驭工程7-Gate**：4/7 PASS，P0×1（运动非幂等resume），P1×3（N+1查询+prompt硬编码）
