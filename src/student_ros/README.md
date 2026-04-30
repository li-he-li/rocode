# 机械臂控制器 (Episode Controller)

## 环境要求

1. **测试环境**: 在 Ubuntu 24.04 + ROS2 Jazzy 下通过测试

2. 无需再使用机械臂上位机软件，所有控制均通过 ROS2 节点完成

## 安装步骤

### 1. 安装 PEAK 驱动
首先需要安装 PEAK 驱动程序，安装完成后可以使用以下命令检查：
```bash
pcaninfo
```

### 2. 安装 Python 相关包
安装 wheelhouse 目录下的 Python 包：
```bash
pip install wheelhouse/*.whl
```


### 3. 编译项目
使用 colcon 编译项目：
```bash
colcon build
```

### 4. 设置环境
```bash
source install/setup.bash
```
## 使用说明

### 启动机械臂控制接口

**方法一：启动机器人（初始化模式）**
在第一个终端中运行：
```bash
ros2 run episode_controller interface --ros-args -p init_mode:=0
```

**方法二：从当前位置恢复**
在第一个终端中运行：
```bash
ros2 run episode_controller interface
```

### 测试机械臂移动

在另一个终端中运行以下命令测试移动功能：
```bash
ros2 run episode_controller client_demo --action move_xyz
```

## 示例代码

所有示例代码位于：
```
src/episode_controller/demo/client_demo.py
```

## 注意事项

- 确保在使用前已正确安装 PEAK 驱动
- 使用前务必先设置 ROS2 环境变量 (`source install/setup.bash`)
- 可以根据需要选择不同的初始化模式
## Git Hooks（本地质量门禁）

详细策略与设计说明见：`docs/development/git-hooks.md`

### 一键安装（推荐）

```bash
python scripts/setup_git_hooks.py
```

该命令会自动安装 `pre-commit` 并注册以下 hooks：
- `pre-commit`
- `pre-push`
- `commit-msg`

### 手动安装（可选）

```bash
python -m pip install --upgrade pre-commit
python -m pre_commit install --install-hooks --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
```

### Hook 内容说明

- `pre-commit`（仅检查暂存文件，保持快速）
  - 基础质量检查：冲突标记、尾随空格、EOF、YAML/JSON/TOML 格式、私钥扫描、debug 语句扫描
  - Python 代码：`ruff check --fix` + `ruff format`
- `commit-msg`
  - 强制 Conventional Commits：`type(scope): description`
  - 允许类型：`feat` `fix` `docs` `style` `refactor` `test` `chore` `perf` `ci` `build` `revert`
- `pre-push`
  - 运行测试：`pytest -q src/episode_controller/test`
  - 若检测到 mypy 配置文件，则自动运行 `mypy src`
  - 若本机缺少 ROS 的 `ament_*` Python 依赖，对应测试会被显式标记为 skip（不会在导入阶段异常中断）

### 常用命令

```bash
# 手动对全部文件执行 pre-commit 检查
python -m pre_commit run --all-files

# 手动执行 pre-push 阶段 hooks
python -m pre_commit run --hook-stage pre-push --all-files
```

### 性能与 CI 说明

- `pre-commit` 默认只处理暂存文件，典型情况下可保持在秒级
- `pre-commit` 与 `ruff` 均自带缓存机制（重复运行会更快）
- 在 `CI=true` 环境下，本仓库自定义 `pre-push` 脚本会自动跳过
- Git hooks 默认只在本地 Git 命令触发，CI 通常不会自动触发本地 hooks

### 需要跳过 hooks 时

```bash
git commit --no-verify
git push --no-verify
```

仅在紧急场景使用，后续请补跑质量检查。
