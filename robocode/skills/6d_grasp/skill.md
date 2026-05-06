---
description: 6D 抓取全流程 — VLM 检测 → GraspNet 候选 → IK 执行 → 放置
category: grasp
requires_human: false
script: src/6D/6D/graspnet-baseline/run_grasp.py
risk_level: L2
---

# 6D 抓取

## 目标
通过自然语言指令控制机械臂抓取指定物体（VLM 识别 + GraspNet 6-DOF 位姿估计）。

## 运行环境
- **Conda 环境**：`episode`
- 所有 6D 抓取脚本（run_grasp.py / grasp_lib / GraspNet）依赖 torch、open3d、pyrealsense2、graspnetAPI 等，仅在 `episode` 环境中配置完整
- Agent 通过 subprocess 调用脚本时会自动使用当前环境，确保 Agent 本身运行在 `episode` 环境中

## 前提
- conda 环境 `episode` 已激活
- RealSense D435 相机连接
- SDK Server 运行在 localhost:12345
- T_camera2end.yaml 标定文件存在（`src/6D/6D/graspnet-baseline/T_camera2end.yaml`）
- GraspNet 模型检查点存在（`src/6D/6D/graspnet-baseline/checkpoint-rs.tar`）

## API Key
- 阿里云 DashScope VLM API Key：读取项目根目录 `.env` 文件中的 `DASHSCOPE_API_KEY` 变量
- VLM 模型：`qwen3-vl-plus`（阿里云 DashScope）
- LLM 模型（VLM 内部路由用）：`deepseek-v3`

## 执行方式

### 方式一：LLM 直接调用 grasp_6d 工具
Agent 调用内置 `grasp_6d` 工具，传入自然语言指令即可。工具内部通过 subprocess 执行 run_grasp.py。

### 方式二：命令行直接执行
```
conda activate episode
cd src/6D/6D/graspnet-baseline
python3 run_grasp.py "抓取桌上的海绵块"
```

## 脚本路径（相对于项目根目录）

| 脚本 | 路径 | 说明 |
|------|------|------|
| 统一抓取入口 | `src/6D/6D/graspnet-baseline/run_grasp.py` | VLM检测+GraspNet+IK执行，一站式 |
| VLM 检测库 | `src/6D/6D/graspnet-baseline/grasp_lib/vlm.py` | 阿里云 VLM 调用封装 |
| VLM 配置 | `src/6D/6D/graspnet-baseline/grasp_lib/config.py` | API Key / 模型名配置 |
| 相机采集 | `src/6D/6D/graspnet-baseline/grasp_lib/camera.py` | RealSense 采集封装 |
| 机器人接口 | `src/6D/6D/graspnet-baseline/episodeApp.py` | SDK TCP 控制 |
| 手眼标定矩阵 | `src/6D/6D/graspnet-baseline/T_camera2end.yaml` | 相机→末端变换（标定产出） |

## 流程（5 步，约 60-180 秒）

1. **VLM 解析指令**：调用阿里云 qwen3-vl-plus 解析自然语言 → 提取抓取目标和描述词
2. **采集 + VLM 检测**：RealSense 拍摄 RGB-D → VLM 检测目标 bbox
3. **连接 + 加载模型**：连接机器人 SDK → 移动到观察位姿 → 加载 GraspNet 模型
4. **推理 + 筛选**：点云处理 → GraspNet 推理 → 碰撞检测 → 竖直抓取筛选
5. **执行**：IK 迭代候选位姿 → 移动到抓取点 → 夹爪闭合 → 移动到放置点 → 释放 → 回零位

## 输出格式
```json
{"status": "ok", "message": "抓取成功: Sponge", "ik_attempts": 3, "total_candidates": 15, "class_name": "Sponge"}
```

## 常见问题
- 环境未激活：确保 `conda activate episode` 已执行（Agent 启动前）
- `DASHSCOPE_API_KEY` 未设置：检查项目根 `.env` 文件
- `T_camera2end.yaml` 不存在：需先完成 6D 手眼标定（`/6d_calibration`）
- IK 无解：调整物体位置使其在工作空间内，或减少候选筛选条件
- SDK 连接失败：确认 SDK Server 在 localhost:12345 运行
- RealSense 未连接：确认 D435 相机 USB 连接正常
