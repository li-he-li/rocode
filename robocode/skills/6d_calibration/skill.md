---
description: 6D 抓取手眼标定全流程 — 示教→采集→计算→验证
category: calibration
requires_human: true
script: src/6D/6D/6d/0.teach_mode.py
risk_level: L2
---

# 6D 抓取手眼标定

## 运行环境
- **Conda 环境**：`episode`（所有标定脚本依赖 torch、opencv、pyrealsense2 等，仅在此环境配置完整）
- Agent 通过 `script_tools.py` 调用脚本时会自动使用 `conda run -n episode`

## 目标
标定相机到机械臂末端的变换矩阵 T_camera2end，供 6D 抓取管线使用。

## 前提
- RealSense D435 相机连接
- SDK Server 运行在 localhost:12345
- 棋盘格标定板（11×8，方格 22mm）
- 机械臂末端安装相机（Eye-in-Hand）
- config.yaml 配置正确（棋盘参数、相机分辨率）

## 流程（4 步）

### Step 0: teach_mode — 示教采集点
```
python src/6D/6D/6d/0.teach_mode.py prepare
python src/6D/6D/6d/0.teach_mode.py replicate
```
人工操作：进入自由模式，手工移动机械臂到棋盘格上方不同位姿，系统自动记录稳定位置到 motors_degrees.npy。建议 15-20 个不同位姿。

### Step 1: generate_points — 采集图像
```
python src/6D/6D/6d/1.generate_points.py prepare
python src/6D/6D/6d/1.generate_points.py generate
```
自动：机器人移动到 Step 0 记录的每个位姿，采集棋盘格图像，评估图像质量。

### Step 2: generate_images_and_T — 计算变换
```
python src/6D/6D/6d/2.generate_images_and_T.py
```
自动：遍历保存的角度，移动到每个位姿，拍摄棋盘格，计算每张图的 R_list/t_list。

### Step 3: calibrate — 手眼标定
```
python src/6D/6D/6d/3.calibrate.py
```
自动：使用 OpenCV calibrateHandEye（支持 HORAUD/TSAI/PARK），输出 T_camera2end.yaml。

## 验证
```python
import yaml, numpy as np
with open("T_camera2end.yaml") as f:
    T = np.array(yaml.safe_load(f)["T_camera2end"])
assert T.shape == (4, 4), f"矩阵维度错误: {T.shape}"
print("T_camera2end:", T)
```

## 常见问题
- 图像太暗：调整光照或相机曝光
- 棋盘格检测失败：确认棋盘格完整在视野内，无遮挡
- IK 无解：调整示教位姿，确保在机械臂工作空间内
