# VLM Hook 规则

## 格式
- [意图|HOOK] @工具名 pre|post:observe|locate "prompt_template"

## 规则

### 移动前观察
- [移动前观察|HOOK] @move_robot_xyz pre:observe "拍摄工作区，确认目标位置和路径无障碍物"
- [移动前观察|HOOK] @move_robot_joints pre:observe "确认当前视野清楚，能看到工作区"

### 抓取前观察
- [抓取前观察|HOOK] @servo_gripper_control pre:observe "确认摄像头对准桌面，能看到目标物体"
- [抓取前观察|HOOK] @control_suction pre:observe "确认摄像头对准桌面，能看到目标物体"

### 抓取后验证
- [抓取后验证|HOOK] @servo_gripper_control post:observe "夹爪闭合后，确认物体是否在夹爪中"
- [抓取后验证|HOOK] @control_suction post:observe "吸盘开启后，确认物体是否被吸附"

### 移动后验证
- [移动后验证|HOOK] @move_robot_xyz post:observe "移到新位置后，确认位置是否符合预期"
- [移动后验证|HOOK] @move_robot_joints post:observe "移动后，确认视野是否正确"
