# 机械臂经验目录

总经验数: 5
最后更新: 2026-05-21 21:16

## 目录

| # | 经验 | 置信度 | 文件路径 |
|---|------|:------:|----------|
| 1 | ⭐ **code 操作经验** — 关节耦合规律、桌面检测流程、Z轴陷阱、J4/J5方向控制、臂展回收、速度上限、VLM脚本写入等 27 条核心规则 | 0.95 | code/code-experience.md |
| 2 | ⭐ **VLM 桌面物体检测 — 完整成功路径** — RealSense拍照→VLM识别物体的完整流程、API Key管理、conda环境、脚本写入方式 | 0.83 | vlm/vlm-desktop-detection.md |
| 3 | ⚠ **会话经验 (2026-05-20)** — 用末端RX角度判断摄像头朝下/朝前/朝侧方、J4/J5左右扫视映射、Home位姿参考 | 0.63 | general/朝下判断.md |
| 4 | ⚠ **会话经验 (2026-05-21)** — 经验文件路径错误时的fallback策略（用search_code替代硬编码路径） | 0.60 | general/状态检查.md |
| 5 | ⚠ **Episode 1 六轴机械臂硬件描述** — 关节限位/零位/连杆长度/工作空间/正方向定义/因果链（已注入system prompt作为硬件手册） | 0.50 | hardware/episode1-spec.md |

> **使用方式**：先看目录找到相关的经验，然后用 `read_file` 工具读取经验文件全文。执行任何运动/抓取/夹爪操作前，必须查阅相关经验。

## 按主题索引

| 主题 | 相关经验 |
|------|---------|
| **J4** | 会话经验 (2026-05-20) |
| **J5** | 会话经验 (2026-05-20) |
| **RX** | 会话经验 (2026-05-20) |
| **camera-orientation** | 会话经验 (2026-05-20) |
| **code** | code 操作经验、VLM 桌面物体检测 — 完整成功路径 |
| **code-best-practices** | code 操作经验 |
| **desktop-detection** | code 操作经验、VLM 桌面物体检测 — 完整成功路径 |
| **error-handling** | 会话经验 (2026-05-21) |
| **file-path** | 会话经验 (2026-05-21) |
| **hardware** | Episode 1 六轴机械臂硬件描述 |
| **joint-limits** | Episode 1 六轴机械臂硬件描述 |
| **kinematics** | Episode 1 六轴机械臂硬件描述 |
| **motion** | code 操作经验 |
| **vlm** | code 操作经验、VLM 桌面物体检测 — 完整成功路径 |
| **workspace** | Episode 1 六轴机械臂硬件描述 |
