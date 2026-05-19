---
updated: 2026-05-19
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
| experience-evolution-system | ✅ 完成 | 95% (76/80) — 死代码已清理，管道已验证 |
| experience-evolution-v2-reflector | ✅ 完成 | LLM 反思层融入 + 可读性改进，57 tests |
| 全量测试 | ⚠️ 阻塞 | FakeProvider 缺失，测试套件无法运行 |

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
| `cleanup` `dead-code` | [debug/05-06](02-debug/2026-05-06.md) [changelog/05-06](01-changelog/2026-05-06.md) [changelog/05-15](01-changelog/2026-05-15.md) |
| `experience-evolution` `manager` `merge` `prune` `feedback` | [design/05-14](05-design/2026-05-14.md) [design/05-15](05-design/2026-05-15.md) [changelog/05-15](01-changelog/2026-05-15.md) |
| `reflector` `llm` `readability` `bullets` | [design/05-19](05-design/2026-05-19.md) [changelog/05-19](01-changelog/2026-05-19.md) [tests/05-19](03-tests/2026-05-19.md) |
| `session-management` `ttl` `resume` | [changelog/05-15](01-changelog/2026-05-15.md) |
| `review` `audit` `robustness` `gates` | [reviews/05-15](04-reviews/2026-05-15.md) [reviews/05-19](04-reviews/2026-05-19.md) |
| `gatekeeper` `full-review` `reflector` `P0` | [reviews/05-19](04-reviews/2026-05-19.md) |

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

## 已知问题 / 待办

- **P0-1**: FakeProvider 缺失（被 8ebbe74 重构删除），测试套件完全无法运行
- **P1-1**: exec_tools shell=True 注入风险（黑名单 + 审批双重防护，但 shell=True 本身是隐患）
- **P1-2**: 受保护文件列表缺少 agent/core.py、motion_tools.py 等关键文件
- **P1-3**: session_summary() success 统计 SQL 条件错误（json_extract boolean vs string）
- **P1-4**: SafetyPolicy.check_speed() 负值通过校验
- voice-stt: 3 个任务待完成（手动测试 + gatekeeper）
- monitorable-analytics: 8 个验证任务待完成
- experience-evolution: 4 个验证任务 + commit 待完成
- experience-evolution-v2: 整个 change 应归档（与 v1 重复）
- run_grasp.py: IK/通信失败不区分（增强需求，非阻塞）
- P0-4: ctypes.PyThreadState_SetAsyncExc 线程中断标记待处理
