---
description: 手眼标定 — 示教 4 点计算 T 矩阵（相机→机器人基座）
category: calibration
requires_human: true
script: src/student_ros/src/episode_apps/calibration_scripts/4.calibrate_hand_eye_qt_ros2.py
output_files:
  - src/student_ros/src/episode_apps/calibration_scripts/hand_eye_calibration.yaml
risk_level: L1
---

# 手眼标定

## 目标
建立相机坐标系与机器人基座坐标系的变换关系（T 矩阵）

## 启动
```
python src/student_ros/src/episode_apps/calibration_scripts/4.calibrate_hand_eye_qt_ros2.py
```

## 人工操作
1. GUI 启动后，确认棋盘在相机视野内
2. 在 GUI 中点击棋盘的 4 个角点（右上、右下、左下、左上）
3. 使用机械臂示教到棋盘中 4 个已知位置
4. 点击"计算"按钮，SVD 算法生成 T 矩阵
5. 确认误差值 < 2mm 为优秀，< 5mm 可接受

## 产出
`hand_eye_calibration.yaml` — 包含：
- `T_matrix`: 4×4 齐次变换矩阵
- `table_points`: 4 个棋盘坐标
- `robot_points`: 4 个机器人示教点

## 验证
```
python -c "
import yaml
with open('hand_eye_calibration.yaml') as f:
    d = yaml.safe_load(f)
print('T_matrix 存在:', d.get('T_matrix') is not None)
"
```
