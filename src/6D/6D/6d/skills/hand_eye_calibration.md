---
name: hand_eye_calibration
description: Episode 机械臂 + RealSense 相机手眼标定流程。Agent 负责启动脚本和引导，人类负责物理操作。
---

# 手眼标定 Skill

## 概述

本 skill 指导 agent 完成 Episode 机械臂与 RealSense 相机的手眼标定。标定分 4 步，agent 负责启动脚本并告诉人类需要做什么，人类负责移动机械臂和放置标定板。

**协作原则：agent 启动脚本 → 弹出 UI → 告诉人类操作什么 → 等人类确认 → 启动下一步。**

## 前置检查（agent 自动完成）

启动任何步骤前，agent 必须验证：

1. **机器人服务运行中** — 检查端口 12345：`ss -tlnp | grep 12345`
2. **conda 环境** — 使用绝对路径：`/home/li/miniconda3/envs/episode/bin/python`
3. **工作目录** — 所有脚本必须在 `/home/li/work/Robot/src/6D/6D/6d/` 下运行
4. **config.yaml 参数** — 确认棋盘格参数（`pattern_size` 和 `square_size`）与实际标定板一致

```yaml
# config.yaml 关键参数
checkerboard:
  pattern_size: [11, 8]    # 内角点 [列, 行]
  square_size: 22          # 方格尺寸(mm)
```

## 标定流程

### 第一步：示教模式 — 记录机械臂位姿

**agent 执行：**

```bash
cd /home/li/work/Robot/src/6D/6D/6d && /home/li/miniconda3/envs/episode/bin/python 0.teach_mode.py prepare
```

后台运行，监控输出直到结束。

**agent 告诉人类：**

> 弹出了 "Teach Mode" 窗口。请按以下步骤操作：
> 1. 等 10 秒，机械臂进入自由模式
> 2. 用手托着机械臂，移动到不同位置
> 3. 每到一个位置保持不动约 5 秒，系统自动记录（窗口显示 Recorded points 数量）
> 4. 尽量记录 10-15 个不同姿态，覆盖不同角度
> 5. 记完后在 OpenCV 窗口按 `q` 保存退出

**agent 等待：** 进程结束，检查输出确认保存了足够的点（建议 >= 10 个）。数据保存在 `./motors_degrees.npy`。

**已知问题：** 脚本中 `is_motor_stable` 会因 `get_motor_angles()` 返回 None 崩溃，已修复（增加了 None 检查）。如遇此问题检查 `0.teach_mode.py` 第 67 行附近的修复是否在位。

---

### 第二步：采集棋盘格标定数据

**前提：** 人类准备好棋盘格标定板（11x8 内角点，22mm 方格）。

**agent 执行：**

```bash
cd /home/li/work/Robot/src/6D/6D/6d && /home/li/miniconda3/envs/episode/bin/python 1.generate_points.py generate
```

**agent 告诉人类：**

> 弹出了 "RealSense" 窗口（彩色+深度图）。请按以下步骤操作：
> 1. 等 10 秒机械臂进入自由模式
> 2. 把棋盘格标定板放在相机视野内
> 3. 一只手托着机械臂移动到不同姿态，另一只手拿标定板（或固定在桌面）
> 4. 当画面上棋盘格角点被检测到（出现彩色线条），按 `空格键` 保存
> 5. 每次保存前换一个不同姿态，至少保存 10-15 组
> 6. 全部保存后按 `s` 键保存退出
>
> 注意：按空格时必须同时满足：
> - 棋盘格角点被检测到（画面有彩色线条）
> - 机械臂保持不动
> - 图像质量足够（否则会提示 Low Quality）

**agent 等待：** 进程结束，检查输出确认保存了足够组数据（>= 10）。数据在 `./calibration_images/degrees_list.npy`。

---

### 第三步：自动复现并计算变换矩阵

**agent 执行：**

```bash
cd /home/li/work/Robot/src/6D/6D/6d && /home/li/miniconda3/envs/episode/bin/python 2.generate_images_and_T.py
```

**agent 告诉人类：**

> 机械臂开始自动移动到之前记录的位置，每到一个位置拍照并检测棋盘格。全程自动，无需操作。请确保机械臂周围没有障碍物，并确认棋盘格标定板仍在相机视野内。

**agent 等待：** 进程结束，检查输出：
- 每行 "点 X 已捕获并保存" 表示成功
- 部分位置可能跳过（棋盘格未检测到），属于正常
- 最终输出 "采集完成"
- 数据保存在 `./calibration_images/` 下：`*.jpg` 图像 + `T_end2base.yaml` 变换矩阵

**关键验证：** 第三步完成后，agent 必须验证图像数量和 T 矩阵数量一致：

```bash
echo "图像: $(ls calibration_images/*.jpg | wc -l)" && \
echo "T矩阵: $(python -c \"import yaml; print(len(yaml.safe_load(open('calibration_images/T_end2base.yaml'))['T_end2base']))\")"
```

如果数量不一致，第四步会报 `calibrateHandEye` 断言错误。解决方法：手动删除没有对应 T 矩阵的图片（通过对比索引），或者修改 `2.generate_images_and_T.py` 只在 `get_T()` 成功时保存图片。

---

### 第四步：手眼标定

**agent 执行：**（使用管道输入自动选择方法，推荐 Tsai）

```bash
cd /home/li/work/Robot/src/6D/6D/6d && echo "2" | /home/li/miniconda3/envs/episode/bin/python 3.calibrate.py
```

方法选项：`1`=Horaud, `2`=Tsai, `3`=Park。Tsai 是最常用的方法。

**agent 检查输出：**

- "标定质量: 非常好" (误差 < 0.5 像素) → 标定成功
- "标定质量: 良好" (误差 < 1.0 像素) → 可接受
- "标定质量: 较差" → 需要重新标定

**成功后：** 标定结果保存在 `./T_camera2end.yaml`。

**agent 告诉人类：**

> 标定完成！重投影误差 XX 像素，质量评价：XX。标定矩阵已保存到 `T_camera2end.yaml`。

---

## 最终产出

标定完成后，`T_camera2end.yaml` 需要复制到 GraspNet 抓取流程的目录：

```bash
cp /home/li/work/Robot/src/6D/6D/6d/T_camera2end.yaml /home/li/work/Robot/src/6D/6D/graspnet-baseline/T_camera2end.yaml
```

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `TypeError: unsupported operand type(s) for -: 'NoneType'` | `get_motor_angles()` 返回 None | 检查 `0.teach_mode.py` 的 None 过滤修复 |
| "未检测到棋盘格角点" | 标定板不在视野或参数不对 | 确认 config.yaml 的 pattern_size 和 square_size |
| "图像质量较低" | 模糊或光照不足 | 调整角度或改善照明 |
| `calibrateHandEye` size mismatch | 图像数 != T 矩阵数 | 在第三步后验证数量一致，不一致则删除多余图片或修改代码 |
| 端口 12345 未监听 | 机器人服务未启动 | 先启动机器人服务 |
