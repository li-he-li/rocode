---
type: operational
tags: [code, code-best-practices, motion, desktop-detection, vlm]
confidence: 0.95
description: "关节耦合规律、桌面检测流程、Z轴陷阱、J4/J5方向控制、臂展回收、速度上限、VLM脚本写入等 27 条核心规则"
data_points: 57
sources: ""
created: 2026-05-19
updated: 2026-05-21
refs: ""
success: True
---

# code 操作经验

## 概览

- 置信度: 0.65
- 数据点数: 4
- 来源会话:

## 建议

- [保持朝下|RULE] @move_robot_xyz @move_robot_joints J2/J3增大（抬臂）→ J5必须减小（手腕下压）才能保持摄像头朝下，反之亦然。这是关节耦合规律，不是固定的xyz坐标
- [桌面检测|PATTERN] @get_robot_status 确认摄像头能否看桌面：先get_robot_status读当前关节角度，根据上述RULE判断J2/J3/J5的关系是否满足朝下条件，不要盲猜xyz坐标
- [桌面检测|CAUTION] @move_robot_xyz 不要硬编码xyz坐标（如300,0,280）去"桌面正上方"，机械臂当前可能已在合适位姿，先读角度再决定是否需要移动
- [关节微调|PATTERN] @move_robot_joints @get_robot_status move_robot_joints后应立即调用get_robot_status确认角度已到位，再进行下一步操作
- [桌面检测|CAUTION] 姿态不正确时禁止直接调用VLM拍照，必须先通过关节角度确认摄像头对准桌面
- [Z轴平移|CAUTION] @move_robot_xyz move_robot_xyz 会重置末端姿态（rx/ry/rz），不能用它"只改z保持朝下"，它会破坏摄像头朝向
- [Z轴平移|PATTERN] @move_robot_joints 保持朝下改高度：用 move_robot_joints 微调J2/J3来改变高度，根据RULE调整J5补偿朝向，或用SDK代码获取当前pose仅改z后整体发送
- [代码执行|PATTERN] @execute_command SDK脚本须通过 conda run -n episode python3 执行
- [代码执行|CAUTION] @execute_command @generate_and_run_sdk_code execute_command 禁止管道/重定向符(|;>`$>&<)，需复杂操作时用 generate_and_run_sdk_code
- [保持朝下|RULE] @move_robot_joints J1=180（正前方）时，J2≈105、J3≈70、J5≈105.63 组合可实现桌面朝下，J5需随J2/J3增大而减小的补偿规律仍适用
- [桌面检测|PATTERN] @get_robot_status @search_code @generate_and_run_sdk_code @execute_command 流程：get_robot_status → search_code(/read_file)经验 → generate_and_run_sdk_code写入脚本 → execute_command运行（conda run -n episode python3），不可用execute_command直接写或运行
- [桌面检测|PARAM] 已验证桌面朝下姿态范围：J1≈180，J2∈[105,108]，J3∈[68,71]，J5∈[100,110]
- [代码执行|PARAM] VLM检测环境变量必须显式传入：`env=('DASHSCOPE_API_KEY=sk-...'`，否则api调用失败
- [运动控制|CAUTION] @move_robot_joints move_robot_joints speed_ratio上限0.6，超过会报错但不会提示准确上限值（必须从经验中记住）
- [桌面检测|CAUTION] @get_robot_status 用户手动调姿后必须调用get_robot_status记录最终关节值——这是唯一可靠的位姿记忆来源
- [经验读取|PATTERN] 经验文件位于 robocode/experience/ 下，需先确认文件名（.md后缀），路径不完整或搜索范围越界会报错
- [桌面检测|RULE] @execute_command @generate_and_run_sdk_code VLM检测脚本需写入/tmp目录后通过execute_command执行，不能直接在generate_and_run_sdk_code中运行——因为SDK环境可能缺少依赖
- [J5激进朝下] @move_robot_joints J5可以超出180°到220°范围来补偿降臂时的朝下需求，J5∈[145,220]比之前记录的[100,197]更激进更大，降臂时优先让J5逼近220°
- [臂展回收规律] @move_robot_joints 缩短臂展同时保持朝下：减小J2（大臂回收）、增大J3（小臂收回），J5需显著增大（往220°靠）来补偿
- [靠近桌面经验] @move_robot_joints 降低末端高度接近桌面时，减小J2并增大J3（手臂往下探），J5随之增大保持朝下，已验证动作安全顺畅
- [收缩J3] @move_robot_joints 用户反馈的"收缩J3"指增大J3（如从55°→70°），使小臂收回，配合J5补偿保持朝下
- [VLM脚本写入] @generate_and_run_sdk_code @execute_command 写脚本到/tmp的正确做法：generate_and_run_sdk_code中直接用`Path.write_text()`写入，execute_command仅用于运行脚本，不要尝试用echo/base64等shell写法
- [左右切换] @move_robot_joints 向左看用 J4≈122°，向右看用 J4≈301°，J5 保持约192°朝下；J4 始终逆时针旋转，向左看角度小、向右看角度大
- [上下切换] @move_robot_joints 向上看用 J5≈6°（仰天），向下看用 J5≈188°（朝下），J4 保持约37°不变；J5 绕手腕中心摆动约182°
- [J4与左右方向] @move_robot_joints J4 控制水平方向（左右看），限位 [0,335]°，逆时针旋转；J1=180°正前方时，调整J4实现左/右，不影响朝下姿态
- [J5与俯仰方向] @move_robot_joints J5 绕手腕固定点做俯仰转动，不改变末端位置：110°水平→130°微下→192°朝下→6°朝上
- [J2/J3与高度前后] @move_robot_joints J2（肩关节，限位[0,180]°，90°水平）控制大臂抬起/放下，决定高度和前后大范围；J3（肘关节）连杆200mm，配合J2调节末端前后距离
- [朝下看基准姿态] @move_robot_joints 已验证朝下组合：J2≈139°, J5≈85° 或 J2≈90°, J5≈192°；J1≈180°（正前），J3≈70~83°
- [学习方式] @get_robot_status 先执行动作（左右/上下看），再用 get_robot_status 确认角度，对比前后数据提炼规律，不要只记死值
