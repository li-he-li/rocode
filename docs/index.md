---
updated: 2026-05-11
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
| 全量测试 | 276 passed | 0 failed |

## 模块地图

```
robocode/
├── cli/           # prompt_toolkit REPL + slash命令 + voice语音
│   ├── app.py     # RobocodeApp 主入口，AgentLoop 集成
│   ├── slash.py   # SlashDispatcher（/help /exit /status /tools /audit /resume /backend /estop）
│   └── voice.py   # VoiceController（faster-whisper + webrtcvad）
├── agent/         # ReAct Agent
│   ├── core.py    # AgentLoop + SYSTEM_PROMPT + tool 执行
│   └── context.py # ContextMemory（消息管理 + checkpoint 序列化）
├── llm/           # LLM Provider
│   ├── base.py    # LLMProvider 抽象 + StreamEvent
│   └── deepseek_provider.py  # DeepSeek V4 via AsyncOpenAI
├── tools/         # 工具层（LLM 可见 22+ 工具）
│   ├── registry.py      # ToolEntry + SkillEntry + ToolRegistry
│   ├── motion_tools.py  # 机械臂运动（L1/L2）
│   ├── gripper_tools.py # 夹爪控制（L1/L2）
│   ├── exec_tools.py    # execute_command（L1，受限 shell）
│   ├── codegen_tools.py # 代码沙箱生成执行（L2）
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
| `cleanup` `dead-code` | [debug/05-06](02-debug/2026-05-06.md) [changelog/05-06](01-changelog/2026-05-06.md) |

## 时间线

| 日期 | 关键事件 |
|------|---------|
| 2026-04-28 | Phase 1 全 10 Section 完成，184 tests |
| 2026-04-30 | Bug 修复 + Skills 机制 + 6D 抓取入口 + GitHub 上传 |
| 2026-05-03 | 6D 抓取 11 项 Bug 修复 + ESC async 重写 |
| 2026-05-04 | Phase 2 全 7 Section 完成，228 tests |
| 2026-05-06 | 代码审查 + 死代码清理 + 运行时目录重构，230 tests |
| 2026-05-07 | voice-stt + monitorable-analytics，276 tests |
| 2026-05-11 | 日志系统重构：log/ → docs/ 分类目录 + frontmatter + index.md |

## 已知问题 / 待办

- voice-stt: 7 个任务待完成（硬件手动测试 + 全流程集成 + 最终 gatekeeper）
- monitorable-analytics: ~8 个任务待完成（Section 10 测试+审查 + 验证任务）
- run_grasp.py: IK/通信失败不区分（增强需求，非阻塞）
- P0-4: ctypes.PyThreadState_SetAsyncExc 线程中断标记待处理
