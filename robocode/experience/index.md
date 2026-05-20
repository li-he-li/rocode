# 机械臂经验索引

总经验数: 4
最后更新: 2026-05-20 21:07

## 最近更新
- 会话经验 (2026-05-20) | general/朝下判断.md (confidence=0.60)
  - [朝下判断] 摄像头朝下的核心标志是末端姿态 RX 接近 ±180°（翻转状态），而不是某个关节的绝对值；朝左/朝右则看 J5 和 RX 的组合，朝前的典型 RX 约为 -110°
  - [J5左右扫视] 在这台机械臂上，J5 的高角度（~187°）配合 RX~-95° 对应摄像头朝左，低角度（~16°）配合 RX~-90° 对应摄像头朝右，J5 ≈ 170° 配合 RX~-174° 对应朝下
  - [Home位姿] Home 位姿的摄像头朝向为向前，典型关节组合为 J2≈90°/J3≈83°/J4≈30°/J5≈110°，末端 RX≈-110°
- code 操作经验 | code/code-experience.md (confidence=0.86)
  - [保持朝下|RULE] J2/J3增大（抬臂）→ J5必须减小（手腕下压）才能保持摄像头朝下，反之亦然。这是关节耦合规律，不是固定的xyz坐标
  - [桌面检测|PATTERN] 确认摄像头能否看桌面：先get_robot_status读当前关节角度，根据上述RULE判断J2/J3/J5的关系是否满足朝下条件，不要盲猜xyz坐标
  - [桌面检测|CAUTION] 不要硬编码xyz坐标（如300,0,280）去"桌面正上方"，机械臂当前可能已在合适位姿，先读角度再决定是否需要移动
- VLM 桌面物体检测 — 完整成功路径 | vlm/vlm-desktop-detection.md (confidence=0.80)
  - [桌面检测|PATTERN] VLM 检测桌面物体的完整流程：search_code 找 grasp_lib → generate_and_run_sdk_code 生成脚本（不用 os/subprocess）→ execute_command 用 python3 -c write_text 写到 /tmp → execute_command env DASHSCOPE_API_KEY=sk-xxx conda run -n episode python3 /tmp/脚本
  - [桌面检测|PATTERN] 执行 VLM 脚本的正确命令：`env DASHSCOPE_API_KEY=sk-6e7e3ba45ec64824badf6d741ef6de0f conda run -n episode python3 /tmp/vlm_desktop_detect.py`
  - [桌面检测|CAUTION] generate_and_run_sdk_code 禁止使用 os. / import os / subprocess. / write_text() / write_bytes()，代码中不能包含这些
- Episode 1 六轴机械臂硬件描述 | hardware/episode1-spec.md (confidence=0.50)
