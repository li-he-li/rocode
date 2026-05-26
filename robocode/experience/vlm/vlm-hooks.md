---
type: hooks
tags: [vlm, hooks, perception]
confidence: 0.85
description: "VLM 感知钩子规则 — 工具调用的前置/后置自动观察"
created: 2026-05-26
updated: 2026-05-26
---

# VLM 感知钩子规则

## 挂钩规则

- [移动前观察|HOOK] @move_robot_xyz pre:observe "拍摄工作区当前状态，确认目标位置和无障碍物"
- [移动后验证|HOOK] @move_robot_xyz post:observe "移到新位置后，观察当前位置和状态是否符合预期"
- [关节移动前观察|HOOK] @move_robot_joints pre:observe "当前视野是否清楚看到工作区"
- [夹爪抓取后验证|HOOK] @servo_gripper_control post:observe "夹爪闭合后，拍一张照片确认物体是否在夹爪中"
- [吸盘抓取后验证|HOOK] @control_suction post:observe "吸盘开启后，拍一张照片确认物体是否被吸附"
