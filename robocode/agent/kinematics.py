"""Forward kinematics for Episode 6-axis arm — pure math, no SDK required.

Computes end-effector position and camera direction from 6 joint angles
using the URDF origin parameters from episode1-spec.md.
"""

import math


# URDF origin data: (x, y, z) in meters, converted to mm
# Joint axis direction: ±Z
_LINKS = [
    # (axis_sign, origin_mm_x, origin_mm_y, origin_mm_z)
    (+1, 5.5, -2.0, 166.0),  # J1: axis +Z, link to J2
    (-1, 0.0, 200.0, 0.0),  # J2: axis -Z, link 200mm to J3
    (-1, 0.0, -5.6, -2.0),  # J3→J4 (offset from J3)
    (-1, 0.0, 0.0, -192.0),  # J4→J5, link 192mm
    (-1, -5.5, 0.0, 0.0),  # J5→J6, link 55mm
    (+1, 0.0, 0.0, 0.0),  # J6: axis +Z, end flange
]


def _rot_z(angle_deg: float) -> list[list[float]]:
    """3x3 rotation matrix around Z axis by angle in degrees."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def fk(joints: list[float]) -> dict:
    """Compute forward kinematics for 6 joint angles (degrees).

    Returns dict with:
      - position: [x, y, z] in mm
      - rotation: 3x3 rotation matrix (world frame)
      - camera_dir: unit vector of camera pointing direction (end Z axis)
      - rx, ry, rz: Euler angles in degrees (ZYX order, matching SDK convention)
    """
    # Start from base — J1 origin is at (0,0,0)
    R = _rot_z(0)  # identity
    p = [0.0, 0.0, 0.0]

    for i, angle in enumerate(joints):
        sign, ox, oy, oz = _LINKS[i]

        # Apply joint rotation
        Rj = _rot_z(sign * angle)
        R = _mat_mul(R, Rj)

        # Translate along current X axis by origin offset
        # (the origin is in the parent frame after rotation)
        offset = _mat_vec_mul(R, [ox, oy, oz])
        p = [p[j] + offset[j] for j in range(3)]

    # Camera direction = end-effector Z axis = third column of rotation matrix
    camera_dir = [R[0][2], R[1][2], R[2][2]]

    # Euler ZYX
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
    """Return a human-readable camera direction from joint angles."""
    r = fk(joints)
    cd = r["camera_dir"]
    x, y, z = cd[0], cd[1], cd[2]

    # Determine primary direction
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

    # Mixed direction
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


# ── helpers ──────────────────────────────────────────────────────────


def _mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """3x3 matrix multiplication."""
    return [
        [a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] for j in range(3)]
        for i in range(3)
    ]


def _mat_vec_mul(m: list[list[float]], v: list[float]) -> list[float]:
    """3x3 matrix × 3-vector."""
    return [
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    ]


def _rot_to_euler(r: list[list[float]]) -> tuple[float, float, float]:
    """Extract ZYX Euler angles (degrees) from rotation matrix."""
    sy = math.sqrt(r[0][0] ** 2 + r[1][0] ** 2)
    singular = sy < 1e-6

    if not singular:
        rx = math.degrees(math.atan2(r[2][1], r[2][2]))
        ry = math.degrees(math.atan2(-r[2][0], sy))
        rz = math.degrees(math.atan2(r[1][0], r[0][0]))
    else:
        rx = math.degrees(math.atan2(-r[1][2], r[1][1]))
        ry = math.degrees(math.atan2(-r[2][0], sy))
        rz = 0.0

    return rx, ry, rz
