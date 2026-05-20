---
type: operational
tags: [code, code-best-practices]
confidence: 0.71
data_points: 4
sources: ""
created: 2026-05-19
updated: 2026-05-20
refs: ""
success: True
---

# code 操作经验

## 概览

- 置信度: 0.65
- 数据点数: 4
- 来源会话:

## 建议

- [保持朝下|RULE] J2/J3增大（抬臂）→ J5必须减小（手腕下压）才能保持摄像头朝下，反之亦然。这是关节耦合规律，不是固定的xyz坐标
- [桌面检测|PATTERN] 确认摄像头能否看桌面：先get_robot_status读当前关节角度，根据上述RULE判断J2/J3/J5的关系是否满足朝下条件，不要盲猜xyz坐标
- [桌面检测|CAUTION] 不要硬编码xyz坐标（如300,0,280）去"桌面正上方"，机械臂当前可能已在合适位姿，先读角度再决定是否需要移动
- [关节微调|PATTERN] move_robot_joints后应立即调用get_robot_status确认角度已到位，再进行下一步操作
- [桌面检测|CAUTION] 姿态不正确时禁止直接调用VLM拍照，必须先通过关节角度确认摄像头对准桌面
- [Z轴平移|CAUTION] move_robot_xyz 会重置末端姿态（rx/ry/rz），不能用它"只改z保持朝下"，它会破坏摄像头朝向
- [Z轴平移|PATTERN] 保持朝下改高度：用 move_robot_joints 微调J2/J3来改变高度，根据RULE调整J5补偿朝向，或用SDK代码获取当前pose仅改z后整体发送
- [代码执行|PATTERN] SDK脚本须通过 conda run -n episode python3 执行
- [代码执行|CAUTION] execute_command 禁止管道/重定向符(|;>`$>&<)，需复杂操作时用 generate_and_run_sdk_code
