"""Episode 六轴机械臂正运动学 — 纯数学计算，不依赖 SDK 喵~

根据 6 个关节角度，用 episode1-spec.md 中的 URDF 参数
计算末端执行器位置和摄像头方向。
"""

import math


# URDF 连杆参数: (旋转轴方向, origin_x, origin_y, origin_z) 单位 mm
# 旋转轴方向: +1 表示 +Z 轴, -1 表示 -Z 轴
_LINKS = [
    # (轴方向, origin_x_mm, origin_y_mm, origin_z_mm)
    (+1, 5.5, -2.0, 166.0),  # J1: 底座旋转 (+Z), 连到 J2
    (-1, 0.0, 200.0, 0.0),  # J2: 大臂俯仰 (-Z), 连杆长 200mm
    (-1, 0.0, -5.6, -2.0),  # J3→J4 (J3 偏移)
    (-1, 0.0, 0.0, -192.0),  # J4→J5, 连杆长 192mm
    (-1, -5.5, 0.0, 0.0),  # J5→J6, 连杆长 55mm
    (+1, 0.0, 0.0, 0.0),  # J6: 末端法兰 (+Z)
]


def _rot_z(angle_deg: float) -> list[list[float]]:
    """绕 Z 轴旋转 angle_deg 度的 3x3 旋转矩阵喵~"""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def fk(joints: list[float]) -> dict:
    """Episode 6 轴正运动学喵~

    Args:
        joints: 6 个关节角度 (度)

    Returns:
        dict with:
          - position: [x, y, z] mm (末端在基坐标系中的位置)
          - rotation: 3x3 旋转矩阵 (世界坐标系下)
          - camera_dir: 摄像头指向单位向量 (末端 Z 轴方向)
          - rx, ry, rz: ZYX 欧拉角 (度, 与 SDK 一致)
    """
    # 从基座开始 — J1 原点在 (0,0,0)
    R = _rot_z(0)  # 初始化为单位矩阵
    p = [0.0, 0.0, 0.0]

    for i, angle in enumerate(joints):
        sign, ox, oy, oz = _LINKS[i]

        # 应用关节旋转
        Rj = _rot_z(sign * angle)
        R = _mat_mul(R, Rj)

        # 沿当前 X 轴平移 origin 偏移量
        offset = _mat_vec_mul(R, [ox, oy, oz])
        p = [p[j] + offset[j] for j in range(3)]

    # 摄像头方向 = 末端 Z 轴 = 旋转矩阵第三列
    camera_dir = [R[0][2], R[1][2], R[2][2]]

    # ZYX 欧拉角提取
    rx, ry, rz = _rot_to_euler(R)

    return {
        "position": [round(v, 2) for v in p],
        "rotation": R,
        "camera_dir": [round(v, 4) for v in camera_dir],
        "rx": round(rx, 1),
        "ry": round(ry, 1),
        "rz": round(rz, 1),
    }


def camera_facing(joints: list[float]) -> str:
    """从关节角度推算摄像头朝向的人类可读描述喵~"""
    r = fk(joints)
    cd = r["camera_dir"]
    x, y, z = cd[0], cd[1], cd[2]

    # 判断主方向
    if z < -0.7:
        return "朝下"
    if z > 0.7:
        return "朝上"
    if abs(y) > abs(x) and y > 0.5:
        return "朝右"
    if abs(y) > abs(x) and y < -0.5:
        return "朝左"
    if x > 0.5:
        return "朝前"
    if x < -0.5:
        return "朝后"

    # 混合方向 — 组合多个分量
    parts = []
    if x > 0.3:
        parts.append("前")
    elif x < -0.3:
        parts.append("后")
    if y > 0.3:
        parts.append("右")
    elif y < -0.3:
        parts.append("左")
    if z > 0.3:
        parts.append("上")
    elif z < -0.3:
        parts.append("下")
    return "朝" + "偏".join(parts) if parts else f"斜向(x={x:.2f},y={y:.2f},z={z:.2f})"


# ── 矩阵运算辅助函数 ────────────────────────────────────────────────


def _mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """3x3 矩阵乘法喵~"""
    return [
        [a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] for j in range(3)]
        for i in range(3)
    ]


def _mat_vec_mul(m: list[list[float]], v: list[float]) -> list[float]:
    """3x3 矩阵 × 3维向量喵~"""
    return [
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    ]


def _rot_to_euler(r: list[list[float]]) -> tuple[float, float, float]:
    """从旋转矩阵提取 ZYX 欧拉角 (度) 喵~"""
    sy = math.sqrt(r[0][0] ** 2 + r[1][0] ** 2)
    singular = sy < 1e-6  # 万向节死锁检测

    if not singular:
        rx = math.degrees(math.atan2(r[2][1], r[2][2]))
        ry = math.degrees(math.atan2(-r[2][0], sy))
        rz = math.degrees(math.atan2(r[1][0], r[0][0]))
    else:
        rx = math.degrees(math.atan2(-r[1][2], r[1][1]))
        ry = math.degrees(math.atan2(-r[2][0], sy))
        rz = 0.0

    return rx, ry, rz
