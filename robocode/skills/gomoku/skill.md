---
description: 五子棋对弈 — 使用 YOLO 检测棋子 + AI 决策 + 机械臂落子
category: application
requires_human: true
script: src/student_ros/src/episode_apps/13.chess_demo_ros2.py
output_files: []
risk_level: L2
---

# 五子棋对弈

## 目标
人机对弈五子棋，机械臂执白子，AI 用 minimax 算法决策

## 前提
- 透视标定完成（camera_calibration.yaml）
- 手眼标定完成（hand_eye_calibration.yaml）
- YOLO 棋子检测模型（best.pt）
- ROS2 机器人控制器运行中

## 启动
```
python src/student_ros/src/episode_apps/13.chess_demo_ros2.py
```

## 人工操作
1. GUI 启动后，在棋盘上放置黑子（人先行）
2. 点击"AI 决策"
3. 机械臂自动拾取白子并放置
4. 循环直到一方胜出

## 棋盘配置
- 默认 11×13 格
- 棋盘物理尺寸 272×240mm
