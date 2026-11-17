# -*- coding: utf-8 -*-
r"""把 CS 脚本的**运行态影响**做进转换器（离线复刻，不依赖录 Unity 的数据）。

为什么要这一步：`static_prefab_spine` 只读磁盘资源，运行态由脚本产生的形变
（Puppet2D 的样条/IK 解算、DynamicBone 的逐帧弹簧）不在产物里。
之前是靠"在 Unity 里录 A/B、再合并差值"补的 —— 能验，但把 Unity 变成了必需依赖。
这里按反编译出来的 C# **逐行复刻**，让转换器自己就能算出脚本效果。

当前进度（2026-10-09）：
  ✅ parse_cs_components  —— 从 prefab 离线读出 DynamicBone / Puppet2D_GlobalControl /
                            Puppet2D_SplineControl / Puppet2D_IKHandle / ParentControl
  ✅ Puppet2D_SplineControl.Run —— Catmull-Rom 样条（尾巴那条链就是它驱动的）
  ⏳ Puppet2D_IKHandle.CalculateIK    —— 待移植
  ⏳ DynamicBone 逐帧弹簧              —— 待移植（公式已读完，见 DynamicBone.cs）

值得注意（踩过的坑）：
  * 运行时脚本只写 **world** 的 position/rotation，所以复刻时也是直接改 world 矩阵；
  * 没有曲线的 transform 不会被 clip 覆盖——所以转换器里也必须"每帧先把它们
    复位到预制体初始姿态"，否则上一帧脚本写进去的值会残留。
"""

import io
import math
import os
import re
import struct

# 末粒子要用到"世界点 → 骨骼局部空间"的逆变换（游戏源码用的就是
# `transform.InverseTransformPoint`），这里直接复用矩阵工具；
# 奇异矩阵（零缩放退化 rig）走容错版。
from ..unity.unity_mesh import mat4_invert_tolerant, mat4_vec  # noqa: E402

# 是否把 DynamicBone 的推进搬进"Uniform 度量"（按子树世界尺度 D 缩放）。
#
# 2026-10-10 定案：**默认关闭**。用 Unity 自己录的 481 帧逐粒子真值实测：
#   · 不切换（转换器度量的世界矩阵）：单步与 Unity 差 1e-8（float 精度）—— 完全等价；
#   · 切换：单步差 1.87e-4，481 帧累积到 2.6e-3 世界单位（≈2.1px）。
# 原因是这个 rig 的子树世界尺度是 (0.1224, 0.1257, 0.0034) —— **非均匀**，
# 而 DynamicBone 的更新式（`|Δ|`、投影、`FromToRotation`）在非均匀缩放下不协变；
# 且转换器 `_world_matrices` 给出的本来就是 Unity 世界度量（骨位/骨长与 Unity 差 1e-7），
# 不需要任何换算。环境变量 `U2S_CS_STEP_METRIC=1` 可以切回旧行为做对照。
STEP_IN_METRIC = os.environ.get("U2S_CS_STEP_METRIC", "0") == "1"

#: ★ Unity 全程 float32，转换器是 Python float64。弹簧链是**确定性**系统，
#: 两种精度在几百步后会累积出**亚帧级相位差** —— 表现为"平时 0.5px、在某些
#: 最快摆动的几帧到 10~50px"。`U2S_CS_F32=1` 时把粒子状态每步落到 float32，
#: 逼近 Unity 的精度行为（A/B 用）。
STEP_F32 = os.environ.get("U2S_CS_F32", "0") == "1"


def _f32(x):
    """把标量/元组落到 float32（用 struct 做一次往返，不引 numpy）。"""
    if isinstance(x, (tuple, list)):
        return type(x)(_f32(v) for v in x)
    try:
        return struct.unpack("f", struct.pack("f", float(x)))[0]
    except (OverflowError, ValueError):
        return float(x)

# 是否把 GlobalControl（spline/IK）搬进"Uniform 度量"。同样默认关闭：
#   · Catmull-Rom 样条是**仿射协变**的（控制点线性组合）→ 换不换度量结果一样；
#   · IK 用 `LookRotation`/`AngleAxis`/`acos`/距离 → **不协变**，非均匀缩放下会偏；
#   · 转换器的 world 矩阵本来就是 Unity 世界度量（实测骨位差 1e-7）→ 不需要换算。
GC_IN_METRIC = os.environ.get("U2S_CS_GC_METRIC", "0") == "1"

# ★ 2026-10-12：DynamicBone 的"逐 clip 脚本字段曲线"**什么时候刷**。
#   `frame`（默认，= 已验收的旧口径）：每步前按曲线当前值刷；
#   `event`：只在 clip 的 `EventDynamicBone` 事件时刻刷（`RefreshParam` 全 false ⇒
#            理论上这才是 Unity 的语义，因为 `UpdateParameters()` 只可能由事件触发）；
#   `off`：从不刷（参数停在建链那一刻）。
DB_REFRESH = os.environ.get("U2S_CS_DB_REFRESH", "frame").strip().lower()

# ---------------------------------------------------------------- 基础数学


def q_mul(a, b):
    """(x,y,z,w) 四元数乘法。"""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def q_axis_angle(axis, deg):
    n = math.sqrt(sum(c * c for c in axis))
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    s = math.sin(math.radians(deg) * 0.5)
    return (axis[0] / n * s, axis[1] / n * s, axis[2] / n * s,
            math.cos(math.radians(deg) * 0.5))


def q_from_to(a, b):
    """Quaternion.FromToRotation(a, b)。"""
    ax, ay, az = a
    bx, by, bz = b
    na = math.sqrt(ax * ax + ay * ay + az * az)
    nb = math.sqrt(bx * bx + by * by + bz * bz)
    if na < 1e-12 or nb < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    ax, ay, az = ax / na, ay / na, az / na
    bx, by, bz = bx / nb, by / nb, bz / nb
    d = ax * bx + ay * by + az * bz
    if d >= 1.0 - 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    if d <= -1.0 + 1e-9:
        axis = (1.0, 0.0, 0.0) if abs(ax) < 0.9 else (0.0, 1.0, 0.0)
        ax2 = (axis[1] * az - axis[2] * ay,
               axis[2] * ax - axis[0] * az,
               axis[0] * ay - axis[1] * ax)
        return q_axis_angle(ax2, 180.0)
    cx = ay * bz - az * by
    cy = az * bx - ax * bz
    cz = ax * by - ay * bx
    w = 1.0 + d
    n = math.sqrt(cx * cx + cy * cy + cz * cz + w * w)
    return (cx / n, cy / n, cz / n, w / n)


def q_look_rotation(forward, up):
    """Unity Quaternion.LookRotation(forward, up)：+Z 指向 forward，+Y 贴 up。"""
    fx, fy, fz = forward
    nf = math.sqrt(fx * fx + fy * fy + fz * fz)
    if nf < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    fx, fy, fz = fx / nf, fy / nf, fz / nf
    ux, uy, uz = up
    # x = normalize(cross(up, forward))；y = cross(forward, x)
    xx = uy * fz - uz * fy
    xy = uz * fx - ux * fz
    xz = ux * fy - uy * fx
    nx = math.sqrt(xx * xx + xy * xy + xz * xz)
    if nx < 1e-9:                       # up 与 forward 平行：Unity 会退回
        return (0.0, 0.0, 0.0, 1.0)
    xx, xy, xz = xx / nx, xy / nx, xz / nx
    yx = fy * xz - fz * xy
    yy = fz * xx - fx * xz
    yz = fx * xy - fy * xx
    m = [[xx, yx, fx], [xy, yy, fy], [xz, yz, fz]]        # 列: x, y, z
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        qw = 0.25 * s
        qx = (m[2][1] - m[1][2]) / s
        qy = (m[0][2] - m[2][0]) / s
        qz = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        qw = (m[2][1] - m[1][2]) / s
        qx = 0.25 * s
        qy = (m[0][1] + m[1][0]) / s
        qz = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        qw = (m[0][2] - m[2][0]) / s
        qx = (m[0][1] + m[1][0]) / s
        qy = 0.25 * s
        qz = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        qw = (m[1][0] - m[0][1]) / s
        qx = (m[0][2] + m[2][0]) / s
        qy = (m[1][2] + m[2][1]) / s
        qz = 0.25 * s
    return (qx, qy, qz, qw)


def q_rotate(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (vx + w * tx + y * tz - z * ty,
            vy + w * ty + z * tx - x * tz,
            vz + w * tz + x * ty - y * tx)


def euler_y_to_quat(deg):
    return q_axis_angle((0.0, 1.0, 0.0), deg)


def _qnorm(q):
    """四元数归一化（`world_rot` 里按链连乘后会漂，最后归一一次）。"""
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def q_conj(q):
    """单位四元数的逆 = 共轭。"""
    return (-q[0], -q[1], -q[2], q[3])


# ---------------------------------------------------------------- 读组件

_GUID_RE = re.compile(r"guid:\s*([0-9a-fA-F]{32})")


def _script_guids(assets):
    idx = {}
    for dirpath, _d, files in os.walk(assets):
        for fn in files:
            if not fn.endswith(".cs.meta"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                head = io.open(p, encoding="utf-8", errors="replace").read(400)
            except OSError:
                continue
            m = _GUID_RE.search(head)
            if m:
                idx[m.group(1).lower()] = os.path.basename(p[:-5])
    return idx


def _field(text, key):
    m = re.search(r"^\s*%s:\s*(.*)$" % re.escape(key), text, re.M)
    return m.group(1).strip() if m else None


def _refs(text, key):
    """取 key 下（或同一行）的 fileID 列表。"""
    out = []
    m = re.search(r"^\s*%s:\s*(\[.*?\])\s*$" % re.escape(key), text, re.M)
    if m:
        return [x for x in re.findall(r"fileID:\s*(-?\d+)", m.group(1)) if x != "0"]
    m = re.search(r"^\s*%s:\s*$" % re.escape(key), text, re.M)
    if not m:
        return out
    for line in text[m.end():].splitlines():
        s = line.strip()
        if not s.startswith("- "):
            if s == "":
                continue
            break
        r = re.search(r"fileID:\s*(-?\d+)", s)
        if r and r.group(1) != "0":
            out.append(r.group(1))
        else:
            break
    return out


def _ref(text, key):
    """取单个 {fileID: N} 引用。"""
    m = re.search(r"^\s*%s:\s*\{fileID:\s*(-?\d+)\}" % re.escape(key), text, re.M)
    return m.group(1) if m and m.group(1) != "0" else None


def _vec3(text, key):
    """取 {x: .., y: .., z: ..}。"""
    m = re.search(r"^\s*%s:\s*\{([^}]*)\}" % re.escape(key), text, re.M)
    if not m:
        return None
    d = dict(re.findall(r"([xyz]):\s*(-?[\d.eE+-]+)", m.group(1)))
    if not d:
        return None
    return tuple(float(d.get(k, 0.0)) for k in ("x", "y", "z"))


def _quat(text, key):
    """取 {x: .., y: .., z: .., w: ..}。"""
    m = re.search(r"^\s*%s:\s*\{([^}]*)\}" % re.escape(key), text, re.M)
    if not m:
        return None
    d = dict(re.findall(r"([xyzw]):\s*(-?[\d.eE+-]+)", m.group(1)))
    if len(d) < 4:
        return None
    return tuple(float(d[k]) for k in ("x", "y", "z", "w"))


def _vec3_list(text, key):
    """取 Vector3[]（YAML 块序列）。"""
    m = re.search(r"^\s*%s:\s*$" % re.escape(key), text, re.M)
    if not m:
        return []
    out = []
    for line in text[m.end():].splitlines():
        s = line.strip()
        if not s.startswith("- "):
            if s:
                break
            continue
        d = dict(re.findall(r"([xyz]):\s*(-?[\d.eE+-]+)", s))
        if d:
            out.append(tuple(float(d.get(k, 0.0)) for k in ("x", "y", "z")))
        else:
            break
    return out


def parse_cs_components(prefab, assets):
    """离线读出 prefab 上的 CS 组件（按脚本名分类）。

    返回 {"DynamicBone": [ {...}, ... ], "Puppet2D_SplineControl": [...], ...}
    每个 dict 带 "fid"（组件 fileID）、"go"（宿主 GameObject fileID）和原始字段。
    """
    sidx = _script_guids(assets)
    out = {}
    raw = io.open(prefab, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"^--- !u!114 &(\d+)\s*$", raw, re.M):
        fid = m.group(1)
        end = raw.find("\n--- ", m.end())
        text = raw[m.end(): end if end > 0 else len(raw)]
        m = re.search(r"m_Script:\s*\{fileID:\s*11500000,\s*guid:\s*([0-9a-fA-F]{32})",
                      text)
        if not m:
            continue
        name = sidx.get(m.group(1).lower())
        if not name or not name.startswith(("DynamicBone", "Puppet2D_", "Actor")):
            continue
        go = re.search(r"m_GameObject:\s*\{fileID:\s*(-?\d+)", text)
        rec = {"fid": fid, "go": go.group(1) if go else None, "text": text}
        rec["enabled"] = (_field(text, "m_Enabled") or "1") == "1"
        for key in ("m_Weight", "m_Damping", "m_Elasticity",
                    "m_Stiffness", "m_Inert",
                    "m_UpdateRate", "m_UpdateMode", "m_EndLength",
                    "m_FreezeAxis", "IsTransFormCalculate", "numberBones",
                    "boneToAimAt", "startRotationY", "_flipCorrection"):
            v = _field(text, key)
            if v is not None:
                rec[key] = v
        # 单个引用 / 向量要单独解析：_field 会把 "{fileID: 123}" 整串存下来，
        # 后面 int() 会失败（这就是 DynamicBone 一开始解析不出根节点的原因）。
        for key in ("m_Root",):
            r = _ref(text, key)
            if r:
                rec[key] = r
        for key in ("m_Gravity", "m_Force", "m_EndOffset"):
            v = _vec3(text, key)
            if v:
                rec[key] = v
        for key in ("m_Bones", "m_Colliders", "m_Exclusions", "_splineCTRLS",
                    "bones", "_Ikhandles", "_SplineControls"):
            rec[key] = _refs(text, key)
        # Puppet2D_IKHandle 用的字段
        for key in ("poleVector", "topJointTransform", "middleJointTransform",
                    "bottomJointTransform", "IKControl", "endTransform",
                    "startTransform"):
            r = _ref(text, key)
            if r:
                rec[key] = r
        for key in ("UpDirection", "OffsetScale", "AimDirection"):
            v = _vec3(text, key)
            if v:
                rec[key] = v
        q = _quat(text, "Offset")
        if q:
            rec["Offset"] = q
        vl = _vec3_list(text, "scaleStart")
        if vl:
            rec["scaleStart"] = vl
        for key in ("Flip", "SquashAndStretch", "Scale", "limitBones"):
            v = _field(text, key)
            if v is not None:
                rec[key] = (v == "1")
        for key in ("numberIkBonesIndex", "iterations", "numberOfBones"):
            v = _field(text, key)
            if v is not None:
                rec[key] = v
        out.setdefault(name, []).append(rec)
    return out


def parse_transform_child_order(prefab):
    """读 prefab 里每个 Transform 的 `m_Children` **顺序**（= Unity 的子节点顺序）。

    为什么要它：`DynamicBone.AppendParticles` 是按 `GetChild(i)` 顺序递归建粒子链的，
    而 `ApplyParticlesToTransforms` 是**顺序相关**的（它写进去的 rotation/position
    会被后面的迭代读到）。按 dict 顺序建链会让粒子顺序和 Unity 不一致 → 结果对不上
    （实测坐标系仿射拟合残差 0.27，远超粒子尺度 0.35，就是这个原因）。
    """
    raw = io.open(prefab, encoding="utf-8", errors="replace").read()
    order = {}
    for m in re.finditer(r"^--- !u!4 &(\d+)\s*$", raw, re.M):
        fid = int(m.group(1))
        end = raw.find("\n--- ", m.end())
        text = raw[m.end(): end if end > 0 else len(raw)]
        ch = []
        mm = re.search(r"^\s*m_Children:\s*$", text, re.M)
        if mm:
            for line in text[mm.end():].splitlines():
                s = line.strip()
                if not s.startswith("- "):
                    if s:
                        break
                    continue
                r = re.search(r"fileID:\s*(-?\d+)", s)
                if not r:
                    break
                ch.append(int(r.group(1)))
        order[fid] = ch
    return order


# ---------------------------------------------------------------- 样条复刻


def point_on_curve(p0, p1, p2, p3, t):
    n1 = ((-t + 2.0) * t - 1.0) * t * 0.5
    n2 = ((3.0 * t - 5.0) * t * t + 2.0) * 0.5
    n3 = ((-3.0 * t + 4.0) * t + 1.0) * t * 0.5
    n4 = (t - 1.0) * t * t * 0.5
    return tuple(p0[i] * n1 + p1[i] * n2 + p2[i] * n3 + p3[i] * n4
                 for i in range(3))


def catmull_rom(points, samples):
    """对应 C# Puppet2D_SplineControl.CatmullRom（points = 控制点世界坐标）。"""
    if len(points) < 4:
        return None
    out = []
    for i in range(1, len(points) - 2):
        for j in range(samples):
            out.append(point_on_curve(points[i - 1], points[i],
                                      points[i + 1], points[i + 2],
                                      j / float(samples)))
    out.append(points[len(points) - 2])
    return out


# ---------------------------------------------------------------- 4x4 工具


def mat4_from_trs(pos, quat, scale=(1.0, 1.0, 1.0)):
    x, y, z, w = quat
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    sx, sy, sz = scale
    return [
        (1 - 2 * (yy + zz)) * sx, (2 * (xy - wz)) * sy, (2 * (xz + wy)) * sz, pos[0],
        (2 * (xy + wz)) * sx, (1 - 2 * (xx + zz)) * sy, (2 * (yz - wx)) * sz, pos[1],
        (2 * (xz - wy)) * sx, (2 * (yz + wx)) * sy, (1 - 2 * (xx + yy)) * sz, pos[2],
        0.0, 0.0, 0.0, 1.0,
    ]


def mat4_pos(m):
    return (m[3], m[7], m[11])


def mat4_scale(m):
    """取缩放。

    ★ 必须用**列**范数：`mat4_from_trs` 建的是 M = R·S（缩放落在列上，与转换器的
      `mat4_mul`/`mat4_vec` 同一套列向量约定）。用行范数只在"均匀缩放"或"90° 换轴"
      时才碰巧相等 —— 尾巴/腿正好是后者，所以一开始没暴露；胸骨链有任意旋转，
      行范数 ≠ 列范数 → `mat4_quat` 拿到非正交矩阵 → 返回非单位四元数 →
      `mat4_from_trs` 把缩放平方放大（实测炸到 1e7）。
    """
    return (math.sqrt(m[0] ** 2 + m[4] ** 2 + m[8] ** 2),
            math.sqrt(m[1] ** 2 + m[5] ** 2 + m[9] ** 2),
            math.sqrt(m[2] ** 2 + m[6] ** 2 + m[10] ** 2))


def mat4_quat(m):
    """从矩阵取旋转四元数（**先正交化**再提取）。

    ★ 不能只按列长归一化就提取：这个 rig 的 world 矩阵**带剪切**
      （`Size_root` 的 Z 缩放是 0.001，再叠上旋转就会出现剪切），
      列不正交时 trace 公式给出的四元数既不单位也不正确 —— 写回父骨旋转
      与求 local 都会用到它，于是整条链偏掉。这里用 Gram-Schmidt 取
      正交基（= Unity 的 rotation），再走标准提取。
    """
    c0 = (m[0], m[4], m[8])
    c1 = (m[1], m[5], m[9])
    n0 = math.sqrt(sum(c * c for c in c0))
    if n0 < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    x = tuple(c / n0 for c in c0)
    d = sum(c1[i] * x[i] for i in range(3))
    t = tuple(c1[i] - d * x[i] for i in range(3))
    n1 = math.sqrt(sum(c * c for c in t))
    if n1 < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    y = tuple(c / n1 for c in t)
    z = (x[1] * y[2] - x[2] * y[1],
         x[2] * y[0] - x[0] * y[2],
         x[0] * y[1] - x[1] * y[0])
    if sum(z * z for z in z) < 0.25:      # 镜像/退化：退回单位阵
        return (0.0, 0.0, 0.0, 1.0)
    r = [[x[0], y[0], z[0]],
         [x[1], y[1], z[1]],
         [x[2], y[2], z[2]]]
    tr = r[0][0] + r[1][1] + r[2][2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        return ((r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s,
                (r[1][0] - r[0][1]) / s, 0.25 * s)
    if r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2.0
        return (0.25 * s, (r[0][1] + r[1][0]) / s,
                (r[0][2] + r[2][0]) / s, (r[2][1] - r[1][2]) / s)
    if r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2.0
        return ((r[0][1] + r[1][0]) / s, 0.25 * s,
                (r[1][2] + r[2][1]) / s, (r[0][2] - r[2][0]) / s)
    s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2.0
    return ((r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s,
            0.25 * s, (r[1][0] - r[0][1]) / s)


def euler_y(m):
    """Unity Quaternion.eulerAngles.y（ZXY 序）——只取 Y 分量。"""
    q = mat4_quat(m)
    x, y, z, w = q
    # ZXY: sinY = 2*(w*y + x*z)
    s = 2.0 * (w * y + x * z)
    s = max(-1.0, min(1.0, s))
    return math.degrees(math.asin(s))


# ---------------------------------------------------------------- 运行时


class Runtime(object):
    """拿着"每帧的 world 矩阵 + 每帧的 local 矩阵"，复刻脚本对 transform 的写入。

    Unity 脚本写的是 **world** 的 position/rotation（`transform.position/rotation`），
    所以这里也提供 `set_world`：算出 local 再重算子树，语义与层级一致。
    """

    def __init__(self, mdl, local_values, world):
        self.mdl = mdl
        self.local = local_values
        self.world = world
        self._children = {}
        # Unity 的 `Transform.childCount`（**不加过滤**，含渲染件等非粒子子节点）
        order = getattr(mdl, "cs_child_order", None)
        if order:
            for tfid, ch in order.items():
                if tfid in mdl.transforms:
                    self._children[tfid] = [c for c in ch if c in mdl.transforms]
        else:
            for tfid, td in mdl.transforms.items():
                self._children.setdefault(td.get("father"), []).append(tfid)

    # --- 度量切换：把整棵树搬到"Uniform 度量"（= Unity 度量）再搬回来
    def begin_metric(self, ref_tfid):
        """左乘 diag(D)（D = 参考节点的世界尺度），使度量与 Unity 一致。"""
        if ref_tfid is None or ref_tfid not in self.world:
            self._metric = None
            return None
        D = mat4_scale(self.world[ref_tfid])
        if min(abs(D[0]), abs(D[1]), abs(D[2])) < 1e-12:
            self._metric = None
            return None
        self._metric = D
        for t in list(self.world):
            self.world[t] = _scale_rows(self.world[t], D)
        return D

    def end_metric(self):
        D = getattr(self, "_metric", None)
        if not D:
            return
        for t in list(self.world):
            self.world[t] = _unscale_rows(self.world[t], D)
        self._metric = None

    # --- 读
    def pos(self, tfid):
        return mat4_pos(self.world[tfid])

    def quat(self, tfid):
        return self.world_rot(tfid)

    def world_rot(self, tfid):
        r"""Unity 的 `Transform.rotation` = **四元数链**（parent.rotation × localRotation）。

        ★ 2026-10-11 实测（`_scratch\_csbake\probe_quat_from_matrix.cs`）：
        同一个 `parRot` 下换四组非均匀缩放（含 Size_root 的 `(0.1285,0.1285,0.00127)`
        和 Breast_R 的 `(0.00477,0.125,0.12849)`），`transform.rotation` **逐位相同**；
        而 `Matrix4x4.rotation`（从世界矩阵分解）在这些缩放上明显不同。
        CS 脚本读的全是 `transform.rotation` / `TransformDirection`，所以这里**必须**用链，
        不能用 `mat4_quat(world)` —— 旧实现在非均匀缩放 rig 上偏差可达 **85°**
        （PXSilky 的 DynamicBone 旋转差就是这个）。
        """
        chain = []
        cur = tfid
        while cur is not None and cur in self.local:
            chain.append(cur)
            cur = self.mdl.transforms.get(cur, {}).get("father")
        q = (0.0, 0.0, 0.0, 1.0)
        for tid in reversed(chain):
            q = q_mul(q, mat4_quat(self.local[tid]))
        return _qnorm(q)

    def scale(self, tfid):
        return mat4_scale(self.world[tfid])

    def parent_matrix(self, tfid):
        f = self.mdl.transforms[tfid].get("father")
        if f in self.world:
            return self.world[f]
        return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    # --- 写
    def set_world(self, tfid, pos=None, quat=None, local_scale=None):
        """★ 语义要照 Unity：`transform.position/rotation = ...` 改的是 **local**，
        再由父级合成 world。

        不能"用 (pos,quat,scale) 直接重建 world 矩阵" —— 父级非均匀缩放 + 旋转
        会让 world 矩阵带**剪切**（这个 rig 的 Size_root 有 0.001 的 Z 缩放，
        一旋转就出现剪切），重建会把剪切丢掉，实测在 t=0 就凭空偏 0.039 世界单位。
        """
        from ..unity.unity_mesh import (mat4_invert, mat4_invert_tolerant,
                                        mat4_vec)
        pm = self.parent_matrix(tfid)
        loc = self.local.get(tfid)
        if loc is None:
            return
        if quat is not None:
            # 父级的**世界旋转**要用四元数链（见 `world_rot`），不能从父矩阵分解
            _par = self.mdl.transforms.get(tfid, {}).get("father")
            _pq = self.world_rot(_par) if _par in self.local else (0.0, 0.0, 0.0, 1.0)
            lq = q_mul(q_conj(_pq), quat)
        else:
            lq = mat4_quat(loc)
        if pos is not None:
            try:
                lp = mat4_vec(mat4_invert(pm), pos)
            except ValueError:
                # 父矩阵奇异（rig 里有 0/极小缩放的退化节点，实测
                # `2DModel_BR_RoyalArsenal_NS1` 会在写 poleVector 时撞上）。
                # Unity 只是丢掉不可恢复的那个轴，这里用容错伪逆，别让整条转换崩掉。
                lp = mat4_vec(mat4_invert_tolerant(pm), pos)
        else:
            lp = mat4_pos(loc)
        ls = mat4_scale(loc) if local_scale is None else local_scale
        self.local[tfid] = mat4_from_trs(lp, lq, ls)
        self._recompute(tfid)

    def set_local(self, tfid, pos=None, quat=None, scale=None):
        """对应 C# 的 transform.localPosition / localRotation / localScale。"""
        cur_local = self.local.get(tfid)
        if cur_local is None:
            return
        p = mat4_pos(cur_local) if pos is None else pos
        q = mat4_quat(cur_local) if quat is None else quat
        s = mat4_scale(cur_local) if scale is None else scale
        self.local[tfid] = mat4_from_trs(p, q, s)
        self._recompute(tfid)

    def _recompute(self, tfid):
        from ..unity.unity_mesh import mat4_mul
        stack = [tfid]
        while stack:
            cur = stack.pop()
            pm = self.world.get(self.mdl.transforms[cur].get("father"))
            loc = self.local.get(cur)
            if loc is not None:
                self.world[cur] = mat4_mul(pm, loc) if pm else loc
            for ch in self._children.get(cur, ()):
                stack.append(ch)


# ---------------------------------------------------------------- 组件封装


def _as_tfid(mdl, fid):
    """YAML 里取出来的 fileID 是字符串，mdl.transforms 的键是 int —— 统一一下。"""
    if fid is None:
        return None
    try:
        i = int(fid)
    except (TypeError, ValueError):
        return None
    return i if i in mdl.transforms else None


def _mat_pt(m, v):
    """4x4 * 点（带平移）。"""
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7],
            m[8] * v[0] + m[9] * v[1] + m[10] * v[2] + m[11])


def _mat_lin(m, v):
    """`Matrix4x4.MultiplyVector`：**线性部分**（含缩放/剪切）乘向量，不带平移。

    ⚠️ 和 `_mat_dir`（= `Transform.TransformDirection`，只取旋转、长度不变）不是一回事：
    DynamicBone 算 end 粒子的骨长用的是 `localToWorldMatrix.MultiplyVector(m_EndOffset)`
    ⇒ **必须含缩放**。2026-10-10 实测：用 `_mat_dir` 会让 `n` 大 1/缩放≈7.5 倍，
    末粒子的长度约束把它推到 150~650px 外（真实骨头却是 0~1px）。
    """
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2],
            m[8] * v[0] + m[9] * v[1] + m[10] * v[2])


def _scale_rows(m, D):
    """左乘 diag(D)：把点从"转换器度量"搬到"Uniform 度量"。

    为什么需要：转换器坐标 = Unity 坐标 / 该子树世界尺度，而这个 rig 的
    `Size_root` 局部 Z 缩放是 0.001 ⇒ 度量**非均匀**。非均匀度量下
    "Unity 的那个旋转"在转换器坐标系里无法用四元数表示（`D⁻¹·R·D` 不正交），
    于是 `FromToRotation` 那一类运算必然偏。
    左乘 diag(D) 后度量与 Unity 一致，旋转可表示；
    而 `local = inv(parent)·child` 在这个共轭下**不变**，所以 set_world 不用改。
    """
    return [m[0] * D[0], m[1] * D[0], m[2] * D[0], m[3] * D[0],
            m[4] * D[1], m[5] * D[1], m[6] * D[1], m[7] * D[1],
            m[8] * D[2], m[9] * D[2], m[10] * D[2], m[11] * D[2],
            m[12], m[13], m[14], m[15]]


def _unscale_rows(m, D):
    return [m[0] / D[0], m[1] / D[0], m[2] / D[0], m[3] / D[0],
            m[4] / D[1], m[5] / D[1], m[6] / D[1], m[7] / D[1],
            m[8] / D[2], m[9] / D[2], m[10] / D[2], m[11] / D[2],
            m[12], m[13], m[14], m[15]]


def _mat_dir(m, v):
    """`Transform.TransformDirection` —— **只用旋转，不受缩放/剪切影响**。

    ★ 不能直接拿线性部分乘：Unity 文档明确"该操作不受 scale 影响，返回向量与原向量等长"。
    这个 rig 的 `Size_root` Z 缩放是 0.001（比 X/Y 小 1000 倍），直接乘会把方向扭掉，
    DynamicBone 的 `ApplyParticlesToTransforms` 于是把父骨旋转写成另一个值 ——
    实测就是"每帧偏一点、慢慢累积"的那个误差。
    这里用 Gram-Schmidt 从线性部分正交化出旋转再作用。
    """
    c0 = (m[0], m[4], m[8])
    c1 = (m[1], m[5], m[9])
    n0 = math.sqrt(sum(c * c for c in c0))
    if n0 < 1e-12:
        return (0.0, 0.0, 0.0)
    x = tuple(c / n0 for c in c0)
    d = sum(c1[i] * x[i] for i in range(3))
    t = tuple(c1[i] - d * x[i] for i in range(3))
    nt = math.sqrt(sum(c * c for c in t))
    if nt < 1e-12:
        return x
    y = tuple(c / nt for c in t)
    z = (x[1] * y[2] - x[2] * y[1],
         x[2] * y[0] - x[0] * y[2],
         x[0] * y[1] - x[1] * y[0])
    return (x[0] * v[0] + y[0] * v[1] + z[0] * v[2],
            x[1] * v[0] + y[1] * v[1] + z[1] * v[2],
            x[2] * v[0] + y[2] * v[1] + z[2] * v[2])


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return n if n > 1e-12 else 1e-12


def _normalized(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return tuple(c / n for c in v)


def _inverse_dir(m, v):
    """InverseTransformDirection：旋转的转置作用（同样忽略缩放）。"""
    ux = _mat_dir(m, (1.0, 0.0, 0.0))
    uy = _mat_dir(m, (0.0, 1.0, 0.0))
    uz = _mat_dir(m, (0.0, 0.0, 1.0))
    return (ux[0] * v[0] + uy[0] * v[1] + uz[0] * v[2],
            ux[1] * v[0] + uy[1] * v[1] + uz[1] * v[2],
            ux[2] * v[0] + uy[2] * v[1] + uz[2] * v[2])


class SplineControl(object):
    """Puppet2D_SplineControl 的离线复刻（尾巴那条链就是它驱动的）。"""

    def __init__(self, mdl, rec, tf_by_go):
        self.mdl = mdl
        self.tf = tf_by_go.get(rec["go"])           # 组件挂在哪
        # _splineCTRLS 是 List<Transform>（YAML 里就是 Transform 的 fileID = tfid）；
        # bones 是 List<GameObject>（要经 go -> tfid 换算）。两个不一样，别混。
        # ★ mdl.transforms 的键是 int，而 YAML 取出来的是 str —— 必须转回 int，
        #   否则 str in dict 永远 False（这就是第一版一个控制点都没解析到的原因）。
        self.ctrls = [_as_tfid(mdl, f) for f in (rec.get("_splineCTRLS") or [])]
        self.bones = [tf_by_go.get(f) for f in (rec.get("bones") or [])]
        self.samples = int(rec.get("numberBones") or 4)

    def valid(self):
        return (self.tf is not None and len(self.ctrls) >= 4
                and all(c is not None for c in self.ctrls)
                and len(self.bones) > 0 and all(b is not None for b in self.bones))

    def metric_ref(self):
        return self.tf

    def run(self, rt):
        q_y = euler_y(rt.world[self.tf])
        rot_y = euler_y_to_quat(q_y)
        pts = [rt.pos(c) for c in self.ctrls]
        out = catmull_rom(pts, self.samples)
        if not out:
            return
        n = min(len(out), len(self.bones))
        for i in range(n):
            if i < n - 1:
                if i == 0 and n > 2:
                    q = rt.quat(self.ctrls[1])
                else:
                    d = tuple(out[i][k] - out[i + 1][k] for k in range(3))
                    q = q_mul(q_mul(q_look_rotation(d, (0.0, 0.0, 1.0)),
                                    q_axis_angle((-1.0, 0.0, 0.0), 90.0)), rot_y)
            else:
                q = rt.quat(self.ctrls[len(self.ctrls) - 2])
            rt.set_world(self.bones[i], out[i], q)


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


class IKHandle(object):
    """Puppet2D_IKHandle.CalculateIK 的离线复刻（两骨 IK；多骨那支先不支持）。

    源码要点（Puppet2D_IKHandle.cs）：
      · num = Flip ? 1 : -1；quaternion2 = AngleAxis(GetAngle()*num, forward)
      · topJoint.rotation = LookRotation(IK_CTRL.pos - top.pos, AimDirection)
                            * AngleAxis(90, UpDirection) * quaternion2
      · middleJoint.rotation 用**已经转过的 top**算出来的 middle 位置（层级会带着走）
      · bottomJoint.rotation = IK_CTRL.rotation * Offset
      · poleVector 只被写位置，不参与后续计算
    """

    def __init__(self, mdl, rec, tf_of):
        self.mdl = mdl
        self.tf = tf_of(rec["go"])
        self.top = tf_of(rec.get("topJointTransform"))
        self.mid = tf_of(rec.get("middleJointTransform"))
        self.bot = tf_of(rec.get("bottomJointTransform"))
        self.pole = tf_of(rec.get("poleVector"))
        self.flip = bool(rec.get("Flip"))
        self.squash = bool(rec.get("SquashAndStretch"))
        self.do_scale = bool(rec.get("Scale"))
        self.up = rec.get("UpDirection") or (0.0, 0.0, 0.0)
        self.offset = rec.get("Offset") or (0.0, 0.0, 0.0, 1.0)
        self.offset_scale = rec.get("OffsetScale") or (1.0, 1.0, 1.0)
        self.scale_start = rec.get("scaleStart") or []
        self.nik = int(rec.get("numberIkBonesIndex") or 0)
        self.aim = (0.0, 0.0, 0.0)

    def valid(self):
        return (self.tf is not None and self.top is not None
                and self.mid is not None and self.bot is not None
                and self.nik != 1)

    def metric_ref(self):
        return self.top

    def set_aim(self, aim):
        self.aim = aim

    def _get_angle(self, rt):
        if self.squash and self.scale_start:
            rt.set_local(self.top, scale=self.scale_start[0])
        n1 = _dist(rt.pos(self.top), rt.pos(self.mid))
        n2 = _dist(rt.pos(self.mid), rt.pos(self.bot))
        n3 = n1 + n2
        n4 = _dist(rt.pos(self.top), rt.pos(self.tf))
        larger = n2 > n1
        if self.squash and self.scale_start and n4 > n3 and n3 > 1e-9:
            s0 = self.scale_start[0]
            rt.set_local(self.top, scale=(s0[0], n4 / n3 * s0[1], s0[2]))
        n4 = min(n4, n3 - 0.0001)
        if n4 < 1e-9 or n1 < 1e-9:
            return None, larger
        c = (n1 * n1 - n2 * n2 + n4 * n4) / (2.0 * n4) / n1
        c = max(-1.0, min(1.0, c))
        return math.degrees(math.acos(c)), larger

    def calculate(self, rt):
        num = 1.0 if self.flip else -1.0
        pos_top = rt.pos(self.top)
        pos_ctrl = rt.pos(self.tf)
        vector = tuple(pos_ctrl[i] - pos_top[i] for i in range(3))
        root2ik = tuple((pos_top[i] + pos_ctrl[i]) * 0.5 for i in range(3))
        q90 = q_axis_angle((0.0, 0.0, 1.0), num * 90.0)
        v2 = q_rotate(q90, vector)
        if self.pole is not None:
            rt.set_world(self.pole, tuple(root2ik[i] - v2[i] for i in range(3)))
        ang, larger = self._get_angle(rt)
        fwd = tuple(pos_ctrl[i] - pos_top[i] for i in range(3))
        base = q_look_rotation(fwd, self.aim)
        if ang is not None:
            q2 = q_axis_angle((0.0, 0.0, 1.0), ang * num)
            q = q_mul(q_mul(base, q_axis_angle(self.up, 90.0)), q2)
        else:
            q = q_mul(base, q_axis_angle(self.up, -90.0 if larger else 90.0))
        rt.set_world(self.top, quat=q)
        # middle 的位置要"带着刚转过的 top"重算（set_world 已经重算了子树）
        fwd2 = tuple(pos_ctrl[i] - rt.pos(self.mid)[i] for i in range(3))
        qm = q_mul(q_look_rotation(fwd2, self.aim), q_axis_angle(self.up, 90.0))
        rt.set_world(self.mid, quat=qm)
        rt.set_world(self.bot, quat=q_mul(rt.quat(self.tf), self.offset))
        if self.do_scale:
            s = rt.scale(self.tf)
            rt.set_local(self.bot, scale=tuple(s[i] * self.offset_scale[i]
                                               for i in range(3)))


def build_runtime(mdl, components, local_values, world, prefab=None):
    """把解析出来的组件变成可调用的运行时对象列表（按 GlobalControl.Run 的顺序）。"""
    # 子节点顺序：Unity 的 m_Children 顺序（粒子链/写回顺序都依赖它）
    if not getattr(mdl, "cs_child_order", None):
        p = prefab or getattr(mdl, "prefab_path", None)
        if p and os.path.isfile(p):
            mdl.cs_child_order = parse_transform_child_order(p)
    tf_of_fid = {}
    for tfid, td in mdl.transforms.items():
        go = td.get("go")
        if go is not None:
            tf_of_fid[str(go)] = tfid
    rt = Runtime(mdl, local_values, world)

    def tf_of(fid):
        if fid is None:
            return None
        i = _as_tfid(mdl, fid)
        return i if i is not None else tf_of_fid.get(str(fid))

    splines = [SplineControl(mdl, r, tf_of_fid)
               for r in components.get("Puppet2D_SplineControl.cs", [])
               if r.get("enabled")]
    iks = [IKHandle(mdl, r, tf_of)
           for r in components.get("Puppet2D_IKHandle.cs", [])
           if r.get("enabled")]
    bones = [DynamicBone(mdl, r, tf_of)
             for r in components.get("DynamicBone.cs", [])
             if r.get("enabled")]
    gcs = components.get("Puppet2D_GlobalControl.cs", []) or []
    gc_tf = tf_of(gcs[0]["go"]) if gcs else None
    flip_corr = 1.0
    if gcs:
        try:
            flip_corr = float(gcs[0].get("_flipCorrection") or 1)
        except (TypeError, ValueError):
            flip_corr = 1.0
    return rt, {"spline": splines, "ik": iks, "bones": bones, "gc": gc_tf,
                "flipCorrection": flip_corr}


def setup_dynamics(rt, drv, t=None):
    """每个 clip 开始时调一次（对应 DynamicBone.Start / OnEnable）。

    注意：**不要**放进 Uniform 度量里 —— 粒子状态统一约定存在"转换器空间"，
    只有 `step` 期间才切到 Uniform 度量（切进去时把粒子一起缩放、出来再缩回）。
    第一版把 setup 也包进去了，于是粒子被存成共轭空间的坐标、step 又缩一次 →
    双重缩放（实测 t=0 就偏 0.083）。
    """
    for b in drv.get("bones", []):
        if b.valid():
            if t is not None:
                b.apply_animated(t)
            b.setup(rt)


def pre_dynamics(rt, drv):
    """采样前：把 DynamicBone 管辖的骨头复位到起始姿态（PreUpdate）。"""
    for b in drv.get("bones", []):
        if b.valid():
            b.pre(rt)


def step_dynamics(rt, drv, dt, t=None):
    for b in drv.get("bones", []):
        if not b.valid():
            continue
        if not STEP_IN_METRIC:
            # 直接在 world 矩阵已有的度量里推进（= Unity 世界度量），见文件头注释。
            b.step(rt, dt, t)
            continue
        D = rt.begin_metric(b.metric_ref())
        if D:
            b.scale_state(D)
        b.step(rt, dt, t)
        if D:
            b.unscale_state(D)
        rt.end_metric()


def snapshot_dynamics(drv):
    r"""给 DynamicBone 链的**状态**拍快照（粒子 pos/prev + object_* + 时间累加器）。

    ★ 2026-10-11：弹簧链是**有状态**的，而游戏里"点击动作"（`Tep_1`/`breast`）
    是从 idle 切过去的 —— 那时链已经在 idle 上跑到了**稳态**。
    转换器原来对每条动画都从 rest 重新建链（而且复用同一个 runtime，
    上一条动画的末态还会残留到下一条 ✗）。实测（`2DModel_3P_Alexandra_NS1`
    的 `Tep_1`，Unity 侧先播 `lobby` 2s 再切过去）：头发骨 **60.3px → 0.009px**。
    做法：先按 setup clip 预跑几秒，拍这份快照；每条动画开始前恢复它。
    """
    snap = []
    for b in drv.get("bones", []):
        snap.append({"valid": b.valid(),
                     "parts": [(p.pos, p.prev) for p in b.particles],
                     "object_prev": b.object_prev,
                     "object_move": b.object_move,
                     "object_scale": b.object_scale,
                     "time_acc": b.time_acc,
                     "was_enabled": b.was_enabled})
    return snap


def restore_dynamics(drv, snap):
    """把链状态恢复到 `snapshot_dynamics` 拍下的那一刻。"""
    if not snap:
        return
    for b, s in zip(drv.get("bones", []), snap):
        if not s.get("valid") or not b.valid():
            continue
        for p, (pos, prev) in zip(b.particles, s["parts"]):
            p.pos, p.prev = pos, prev
        b.object_prev = s["object_prev"]
        b.object_move = s["object_move"]
        b.object_scale = s["object_scale"]
        b.time_acc = s["time_acc"]
        b.was_enabled = s.get("was_enabled", True)


def run_global_control(rt, drv):
    """复刻 Puppet2D_GlobalControl.Run 的顺序：
    SplineControls -> ParentControls(暂无) -> FaceCamera -> IKHandles -> FFD(暂无)。
    """
    # ★ 整段都在"Uniform 度量"（= Unity 度量）里跑：把世界矩阵按该子树世界尺度
    #   左乘对角阵搬过去，跑完再搬回来（局部矩阵是共轭不变量，set_world 不用改）。
    ref = drv.get("gc")
    if ref is None:
        for s in drv["spline"]:
            if s.valid():
                ref = s.metric_ref()
                break
    D = rt.begin_metric(ref) if GC_IN_METRIC else None
    for s in drv["spline"]:
        if s.valid():
            s.run(rt)
    if drv.get("gc") is not None:
        # 源码（Puppet2D_GlobalControl.cs L442）：`AimDirection = myTransform.forward.normalized * _flipCorrection`
        # `Transform.forward` = 世界旋转 × (0,0,1)，**单位向量、与缩放无关**
        # （旧实现取的"世界矩阵 Z 列"含非均匀缩放，方向会被扭 —— 与约束 32 同一类错）。
        z = q_rotate(rt.world_rot(drv["gc"]), (0.0, 0.0, 1.0))
        aim = tuple(c * drv.get("flipCorrection", 1.0) for c in z)
        for h in drv["ik"]:
            h.set_aim(aim)
    for h in drv["ik"]:
        if h.valid():
            h.calculate(rt)
    if D:
        rt.end_metric()


# ---------------------------------------------------------------- DynamicBone


class _Particle(object):
    __slots__ = ("tf", "parent", "damping", "elasticity", "stiffness", "inert",
                 "radius", "bone_len", "pos", "prev", "end_offset",
                 "init_lp", "init_lr", "pchild")

    def __init__(self):
        self.tf = None
        self.parent = -1
        self.damping = 0.0
        self.elasticity = 0.0
        self.stiffness = 0.0
        self.inert = 0.0
        self.radius = 0.0
        self.bone_len = 0.0
        self.pos = (0.0, 0.0, 0.0)
        self.prev = (0.0, 0.0, 0.0)
        self.end_offset = (0.0, 0.0, 0.0)
        self.init_lp = (0.0, 0.0, 0.0)
        self.init_lr = (0.0, 0.0, 0.0, 1.0)
        # 粒子链上的子节点数（= Unity 的 Particle.m_ChildCount）。**不能**用
        # Transform 的全部子节点数：骨头上常还挂着渲染件（sprite/mesh），
        # 那样会被算成"多叉"，于是 ApplyParticlesToTransforms 跳过旋转更新
        # （实测让乳房那段偏 3~20px）。2026-10-09 修。
        self.pchild = 0


def _fnum(rec, key, default=0.0):
    try:
        return float(rec.get(key, default))
    except (TypeError, ValueError):
        return default


def _parse_curve(text, key):
    """从组件 YAML 文本里取 AnimationCurve：[(time, value, inSlope, outSlope)]。"""
    m = re.search(r"^\s*%s:\s*$" % re.escape(key), text or "", re.M)
    if not m:
        return []
    seg = (text or "")[m.end():]
    # 截到**下一个同级字段**（缩进恰好 2 个空格）；不能用 `^\s*m_...:`
    # —— 那会先撞上曲线自己的 `m_Curve:`，把整段键都截掉（之前误判"曲线为空"）。
    nxt = re.search(r"^  m_[A-Za-z0-9_]+:", seg, re.M)
    if nxt:
        seg = seg[:nxt.start()]
    out = []
    # 注意：`re.split` 的第 3 个参数是 **maxsplit**，不是 flags！
    # 之前写成 `re.split(p, seg, re.M)` ⇒ maxsplit=8、flags=0（没有 MULTILINE），
    # `^`/`$` 只按整串锚定，一段都切不出来，曲线永远是空。2026-10-10 修。
    for blk in re.split(r"^\s+- serializedVersion: \d+\s*$", seg, flags=re.M)[1:]:
        tm = re.search(r"^\s*time:\s*([-\d.eE+]+)\s*$", blk, re.M)
        vm = re.search(r"^\s*value:\s*([-\d.eE+]+)\s*$", blk, re.M)
        if not (tm and vm):
            continue

        def _s(k):
            mm = re.search(r"^\s*%s:\s*(\S+)\s*$" % k, blk, re.M)
            if not mm:
                return 0.0
            s = mm.group(1)
            if "Infinity" in s or "inf" in s.lower():
                return float("inf")
            try:
                return float(s)
            except ValueError:
                return 0.0
        out.append((float(tm.group(1)), float(vm.group(1)),
                    _s("inSlope"), _s("outSlope")))
    out.sort()
    return out


def _curve_eval(keys, t):
    """Unity `AnimationCurve.Evaluate`（三次 Hermite，用两侧斜率）。

    空曲线 → 返回 1.0（= 不覆盖组件上的平值，保持旧行为）。
    """
    if not keys:
        return 1.0
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    for i in range(len(keys) - 1):
        t0, v0, _in0, out0 = keys[i]
        t1, v1, in1, _out1 = keys[i + 1]
        if t0 <= t <= t1:
            dt = t1 - t0
            if dt <= 1e-9:
                return v1
            u = (t - t0) / dt
            if math.isinf(out0) or math.isinf(in1):
                return v0 if u < 1.0 else v1     # 常量段（编辑器 Constant）
            h00 = 2.0 * u ** 3 - 3.0 * u ** 2 + 1.0
            h10 = u ** 3 - 2.0 * u ** 2 + u
            h01 = -2.0 * u ** 3 + 3.0 * u ** 2
            h11 = u ** 3 - u ** 2
            return h00 * v0 + h10 * dt * out0 + h01 * v1 + h11 * dt * in1
    return keys[-1][1]


class DynamicBone(object):
    """DynamicBone（逐帧弹簧）的离线复刻。字段语义照抄 DynamicBone.cs。

    我们这两个角色的参数都很"软"（gravity/force/inert/colliders 全 0、
    distribution 曲线为空），但公式按通用情形写，免得换角色又不对。
    """

    # 兜底：曲线没解析出来时 `_curve_eval(None, r)` 返回 1.0，退化成"不平值缩放"
    curves = {}

    def __init__(self, mdl, rec, tf_of):
        self.mdl = mdl
        # DynamicBone.UpdateParameters() 的 Distribution 曲线：逐粒子按
        # `骨长/总长` 求值后**乘**组件上的平值覆盖（实测乳房 DB 的 damping 是
        # 0.035…0.07，不是恒 0.07 —— 这是移植版一直漏掉的一环）。
        # 2026-10-10：这块之前被误放进 IKHandle.__init__，DynamicBone 根本没有
        # self.curves，`_update_params` 直接 AttributeError ⇒ 移植版其实一直在
        # 用平值。已挪回本类。
        _t = rec.get("text") or ""
        self.curves = {
            "damping": _parse_curve(_t, "m_DampingDistrib"),
            "elasticity": _parse_curve(_t, "m_ElasticityDistrib"),
            "stiffness": _parse_curve(_t, "m_StiffnessDistrib"),
            "inert": _parse_curve(_t, "m_InertDistrib"),
            "radius": _parse_curve(_t, "m_RadiusDistrib"),
        }
        self.tf = tf_of(rec["go"])
        self.root = tf_of(rec.get("m_Root"))
        self.weight = _fnum(rec, "m_Weight", 1.0)
        self.damping = _fnum(rec, "m_Damping", 0.1)
        self.elasticity = _fnum(rec, "m_Elasticity", 0.1)
        self.stiffness = _fnum(rec, "m_Stiffness", 0.1)
        self.inert = _fnum(rec, "m_Inert", 0.0)
        self.radius = _fnum(rec, "m_Radius", 0.0)
        self.update_rate = _fnum(rec, "m_UpdateRate", 60.0)
        self.end_length = _fnum(rec, "m_EndLength", 0.0)
        self.end_offset = rec.get("m_EndOffset") or (0.0, 0.0, 0.0)
        self.gravity = rec.get("m_Gravity") or (0.0, 0.0, 0.0)
        self.force = rec.get("m_Force") or (0.0, 0.0, 0.0)
        self.exclusions = [tf_of(f) for f in (rec.get("m_Exclusions") or [])]
        self.transform_calc = (rec.get("IsTransFormCalculate", "1") == "1")
        # ★ 2026-10-11：**逐 clip 动画的脚本字段**（m_Damping/m_Elasticity/…）。
        #   这些在 Unity 里是 AnimationClip 直接写在组件字段上的曲线（路径形如
        #   `.../CTRL_Dynamic/Bone_Hair`，attribute 是哈希 `script_0x...`），
        #   运行时会**每帧覆盖**组件上的平值 ⇒ 头发/胸/裙摆的"软硬"整段是变化的。
        #   我们原来只读预制体平值 ⇒ 动画一动就跟不上/过冲（2026-10-11 定位）。
        #   这里放 {字段名: t -> 值} 的可调用表，由调用方（static_prefab_spine）接。
        self.anim_fields = {}
        # ★ 2026-10-12：**参数什么时候刷**。本工程所有 DynamicBone 的 `RefreshParam`
        #   都是 false（87 个 prefab / 228 个组件实测全 0），所以"逐帧刷"其实只是近似；
        #   真正决定时刻的是 clip 里的 `EventDynamicBone` 动画事件（`data` = DB 物件名）。
        #   `U2S_CS_DB_REFRESH=frame|event|off`（默认 frame = 老行为，产物不变）；
        #   `event` 档用 `anim_events`（该 DB 的事件时刻，clip 局部时间，升序）。
        self.refresh_mode = DB_REFRESH
        self.anim_events = []
        self._ev_i = 0
        self._ev_last_t = -1e30
        # ★ 2026-10-12：**组件自己的启用位**（clip 里绑在 DynamicBone 上的 `m_Enabled`）。
        #   `enabled_fn(t)` 返回该时刻组件是否启用（None = 始终启用）。
        #   禁用 ⇒ `Update/LateUpdate` 不跑 ⇒ **弹簧不推进、骨头跟着动画走**；
        #   0→1 重新启用 ⇒ `OnEnable()→ResetParticlesPosition()`
        #   ⇒ **整条粒子链重置成那一刻的骨头位置**（`was_enabled` 用来检测这个跳变）。
        #   全工程 327 条这样的曲线：62 条恒 0、119 条会切换。
        self.enabled_fn = None
        self.was_enabled = True
        self.particles = []
        self.object_scale = 1.0
        self.object_move = (0.0, 0.0, 0.0)
        self.object_prev = (0.0, 0.0, 0.0)
        self.bone_total = 0.0
        self.local_gravity = (0.0, 0.0, 0.0)
        self.time_acc = 0.0
        self._children = {}
        # Unity 的 `Transform.childCount`（不加过滤，含渲染件等非粒子子节点）
        order = getattr(mdl, "cs_child_order", None)
        if order:
            for tfid, ch in order.items():
                if tfid in mdl.transforms:
                    self._children[tfid] = [c for c in ch if c in mdl.transforms]
        else:
            for tfid, td in mdl.transforms.items():
                self._children.setdefault(td.get("father"), []).append(tfid)

    def valid(self):
        return (self.tf is not None and self.root is not None
                and self.transform_calc and self.weight > 0.0)

    def metric_ref(self):
        return self.root

    def scale_state(self, D):
        """粒子位置是"点"，度量切换时要一起缩放（速度/prev 同样）。"""
        for p in self.particles:
            p.pos = tuple(p.pos[i] * D[i] for i in range(3))
            p.prev = tuple(p.prev[i] * D[i] for i in range(3))
        self.object_prev = tuple(self.object_prev[i] * D[i] for i in range(3))
        self.object_move = tuple(self.object_move[i] * D[i] for i in range(3))

    def unscale_state(self, D):
        for p in self.particles:
            p.pos = tuple(p.pos[i] / D[i] for i in range(3))
            p.prev = tuple(p.prev[i] / D[i] for i in range(3))
        self.object_prev = tuple(self.object_prev[i] / D[i] for i in range(3))
        self.object_move = tuple(self.object_move[i] / D[i] for i in range(3))

    # --- 结构
    def _append(self, rt, tfid, parent_index, bone_len):
        p = _Particle()
        p.tf = tfid
        p.parent = parent_index
        if tfid is not None:
            p.pos = p.prev = rt.pos(tfid)
            loc = rt.local[tfid]
            p.init_lp = mat4_pos(loc)
            p.init_lr = mat4_quat(loc)
        else:
            ptf = self.particles[parent_index].tf
            # 末粒子（游戏源码 DynamicBone.AppendParticles，L262~278）：
            #   m_EndLength > 0：
            #       m_EndOffset = transform.InverseTransformPoint(transform.position*2 - parent.position)
            #                     * m_EndLength
            #     ⇒ 方向是"沿链继续往外"（pos*2−parentPos 那个镜像点），长度 = endLength × 骨长；
            #   m_EndLength == 0：
            #       m_EndOffset = transform.InverseTransformPoint(
            #                        base.transform.TransformDirection(m_EndOffset) + transform.position)
            #     ⇒ 方向由 **DB 组件自己的 transform**（不是骨头）旋转，再折回骨头局部空间。
            #   m_Position = transform.TransformPoint(m_EndOffset)
            # ⚠️ 早先这里写成"骨头局部 +X × endLength" —— 对 +X 朝上的 rig 会把末粒子
            #    甩到骨头上方 100~400px（PXSilky 头发/外套、`Bone_Hair_BRR_02` 566px 就是这个）。
            M = rt.world[ptf]
            pos_ptf = rt.pos(ptf)
            if self.end_length > 0.0:
                par_tf = (self.mdl.transforms.get(ptf) or {}).get("father")
                par_tf = par_tf if par_tf in self.mdl.transforms else None
                if par_tf is not None:
                    par_pos = rt.pos(par_tf)
                    wp = tuple(pos_ptf[k] * 2.0 - par_pos[k] for k in range(3))
                    lp = mat4_vec(mat4_invert_tolerant(M), wp)
                    p.end_offset = tuple(lp[k] * self.end_length for k in range(3))
                else:
                    p.end_offset = (self.end_length, 0.0, 0.0)
            else:
                dirw = q_rotate(rt.quat(self.tf), self.end_offset)   # base.transform
                wp = tuple(pos_ptf[k] + dirw[k] for k in range(3))
                p.end_offset = mat4_vec(mat4_invert_tolerant(M), wp)
            p.pos = p.prev = _mat_pt(M, p.end_offset)
        if parent_index >= 0:
            bone_len += _dist(rt.pos(self.particles[parent_index].tf), p.pos)
            p.bone_len = bone_len
            self.bone_total = max(self.bone_total, bone_len)
            # 记到父粒子上：ApplyParticlesToTransforms 只看**粒子链**的子节点数
            self.particles[parent_index].pchild += 1
        idx = len(self.particles)
        self.particles.append(p)
        if tfid is not None:
            for ch in self._children.get(tfid, ()):
                if ch in self.exclusions:
                    if self.end_length > 0.0 or self.end_offset != (0, 0, 0):
                        self._append(rt, None, idx, bone_len)
                    continue
                self._append(rt, ch, idx, bone_len)
            if not self._children.get(tfid) and \
                    (self.end_length > 0.0 or self.end_offset != (0, 0, 0)):
                self._append(rt, None, idx, bone_len)

    def setup(self, rt):
        self.particles = []
        self.bone_total = 0.0
        self.object_scale = abs(rt.scale(self.tf)[0])
        self.object_prev = rt.pos(self.tf)
        self.object_move = (0.0, 0.0, 0.0)
        self.time_acc = 0.0
        self.local_gravity = _inverse_dir(rt.world[self.root], self.gravity)
        self._append(rt, self.root, -1, 0.0)
        self._update_params()

    def _update_params(self):
        cv = self.curves
        for p in self.particles:
            r = (p.bone_len / self.bone_total) if self.bone_total > 1e-12 else 0.0
            p.damping = min(1.0, max(0.0, self.damping
                                     * _curve_eval(cv.get("damping"), r)))
            p.elasticity = min(1.0, max(0.0, self.elasticity
                                        * _curve_eval(cv.get("elasticity"), r)))
            p.stiffness = min(1.0, max(0.0, self.stiffness
                                       * _curve_eval(cv.get("stiffness"), r)))
            p.inert = min(1.0, max(0.0, self.inert
                                   * _curve_eval(cv.get("inert"), r)))
            p.radius = max(0.0, self.radius
                           * _curve_eval(cv.get("radius"), r))

    def apply_animated(self, t):
        """把该 clip 的脚本字段曲线在 t 时刻的值写到组件字段上（Unity 运行时语义）。

        只有值真的变了才重算逐粒子参数（`_update_params`），省时间。

        `refresh_mode`：
          * `frame`（默认）：按当前时刻求值（= "逐帧刷"，已验收的旧口径）；
          * `event`：**只在 `EventDynamicBone` 事件的时刻刷**（Unity 里唯一会调
            `UpdateParameters()` 的入口，因为 `RefreshParam` 全 false）；
          * `off`：不刷（参数停在建链那一刻）。
        """
        if not self.anim_fields:
            return
        if self.refresh_mode == "off":
            return
        ev_t = None
        if self.refresh_mode == "event":
            if t < self._ev_last_t:            # 当前动画绕回了（循环）⇒ 事件指针复位
                self._ev_i = 0
            self._ev_last_t = t
            while (self._ev_i < len(self.anim_events)
                   and self.anim_events[self._ev_i] <= t + 1e-9):
                ev_t = self.anim_events[self._ev_i]
                self._ev_i += 1
            if ev_t is None:
                return                          # 还没到任何事件时刻 ⇒ 不刷
            t = ev_t                            # 用**事件时刻**的曲线值
        changed = False
        for field, ev in self.anim_fields.items():
            try:
                v = ev(t)
            except Exception as ex:                               # noqa: BLE001
                # 不静默：曲线求值失败必须看得见（否则会"看着接上了、其实没生效"）
                if not getattr(self, "_anim_warned", False):
                    self._anim_warned = True
                    print("[cs] ⚠ 脚本字段曲线求值失败（该字段退化为平值）：%s: %s"
                          % (field, ex))
                continue
            if v is None:
                continue
            v = max(0.0, min(1.0, float(v)))
            if abs(v - getattr(self, field, 0.0)) > 1e-9:
                setattr(self, field, v)
                changed = True
        if changed:
            self._update_params()

    # --- 每帧
    def reset_particles(self, rt):
        """复刻 `OnEnable()→ResetParticlesPosition()`：粒子回到**当前**骨头位置。

        只在"组件被动画从 0 打开到 1"的那一刻调用（`step()` 里检测跳变）。
        `m_Time`（子步累加器）**不复位** —— 源码里 `ResetParticlesPosition` 也没碰它。
        """
        for p in self.particles:
            if p.tf is not None:
                p.pos = p.prev = rt.pos(p.tf)
            else:
                ptf = self.particles[p.parent].tf
                p.pos = p.prev = _mat_pt(rt.world[ptf], p.end_offset)
        self.object_prev = rt.pos(self.tf)
        self.object_move = (0.0, 0.0, 0.0)

    def pre(self, rt):
        """对应 DynamicBone.Update -> PreUpdate -> InitTransforms（复位到起始姿态）。"""
        for p in self.particles:
            if p.tf is not None:
                rt.set_local(p.tf, pos=p.init_lp, quat=p.init_lr)

    def step(self, rt, dt, t=None):
        if not self.valid():
            return
        # ★ 组件被 clip 关掉/打开（`m_Enabled` 曲线）：关掉就**什么都不做**
        #   （骨头保持动画姿态），重新打开的那一刻按 `OnEnable` 重置粒子链。
        if self.enabled_fn is not None:
            try:
                _en = bool(self.enabled_fn(t if t is not None else 0.0))
            except Exception as ex:                                # noqa: BLE001
                if not getattr(self, "_en_warned", False):
                    self._en_warned = True
                    print("[cs] ⚠ DynamicBone 的 m_Enabled 曲线求值失败（当作启用）：%s" % ex)
                _en = True
            if not _en:
                self.was_enabled = False
                return
            if not self.was_enabled:
                self.reset_particles(rt)
                self.was_enabled = True
        if t is not None:
            self.apply_animated(t)
        self.object_scale = abs(rt.scale(self.tf)[0])
        now = rt.pos(self.tf)
        self.object_move = tuple(now[i] - self.object_prev[i] for i in range(3))
        self.object_prev = now
        num = 1
        if self.update_rate > 0.0:
            step = 1.0 / self.update_rate
            self.time_acc += dt
            num = 0
            while self.time_acc >= step:
                self.time_acc -= step
                num += 1
                if num >= 3:
                    self.time_acc = 0.0
                    break
        if num > 0:
            for _ in range(num):
                self._update1(rt)
                self._update2(rt)
                self.object_move = (0.0, 0.0, 0.0)
        else:
            self._skip(rt)
        self._apply(rt)
        if STEP_F32:
            # 把粒子状态落到 float32（Unity 的精度）：见文件里 STEP_F32 的说明
            for _p in self.particles:
                _p.pos = _f32(_p.pos)
                _p.prev = _f32(_p.prev)
            self.object_prev = _f32(self.object_prev)
            self.object_move = _f32(self.object_move)
            self.time_acc = _f32(self.time_acc)

    def _update1(self, rt):
        g = self.gravity
        gn = _normalized(g)
        # `TransformDirection(m_LocalGravity)` —— 用四元数链（见 `world_rot`）
        d = q_rotate(rt.world_rot(self.root), self.local_gravity)
        dot = sum(d[i] * gn[i] for i in range(3))
        sub = tuple(gn[i] * max(dot, 0.0) for i in range(3))
        vec = tuple((g[i] - sub[i] + self.force[i]) * self.object_scale
                    for i in range(3))
        for p in self.particles:
            if p.parent >= 0:
                v = tuple(p.pos[i] - p.prev[i] for i in range(3))
                v5 = tuple(self.object_move[i] * p.inert for i in range(3))
                p.prev = tuple(p.pos[i] + v5[i] for i in range(3))
                p.pos = tuple(p.pos[i] + v[i] * (1.0 - p.damping) + vec[i] + v5[i]
                              for i in range(3))
            else:
                p.prev = p.pos
                p.pos = rt.pos(p.tf)

    def _update2(self, rt):
        for i in range(1, len(self.particles)):
            p = self.particles[i]
            p2 = self.particles[p.parent]
            if p.tf is not None:
                n = _dist(rt.pos(p2.tf), rt.pos(p.tf))
            else:
                # 源码：`p2.m_Transform.localToWorldMatrix.MultiplyVector(m_EndOffset).magnitude`
                # ⇒ 含缩放的线性部分（见 `_mat_lin` 的注释）
                n = _norm(_mat_lin(rt.world[p2.tf], p.end_offset))
            num2 = 1.0 + (p.stiffness - 1.0) * self.weight
            if num2 > 0.0 or p.elasticity > 0.0:
                m = list(rt.world[p2.tf])
                m[3], m[7], m[11] = p2.pos
                localv = (mat4_pos(rt.local[p.tf]) if p.tf is not None
                          else p.end_offset)
                vec = _mat_pt(m, localv)
                v2 = tuple(vec[k] - p.pos[k] for k in range(3))
                p.pos = tuple(p.pos[k] + v2[k] * p.elasticity for k in range(3))
                if num2 > 0.0:
                    v2 = tuple(vec[k] - p.pos[k] for k in range(3))
                    mag = _norm(v2)
                    num3 = n * (1.0 - num2) * 2.0
                    if mag > num3 and mag > 1e-12:
                        p.pos = tuple(p.pos[k] + v2[k] * ((mag - num3) / mag)
                                      for k in range(3))
            v3 = tuple(p2.pos[k] - p.pos[k] for k in range(3))
            mag2 = _norm(v3)
            if mag2 > 1e-12:
                p.pos = tuple(p.pos[k] + v3[k] * ((mag2 - n) / mag2)
                              for k in range(3))

    def _skip(self, rt):
        for i, p in enumerate(self.particles):
            if p.parent >= 0:
                p.prev = tuple(p.prev[k] + self.object_move[k] for k in range(3))
                p.pos = tuple(p.pos[k] + self.object_move[k] for k in range(3))
                p2 = self.particles[p.parent]
                if p.tf is not None:
                    n = _dist(rt.pos(p2.tf), rt.pos(p.tf))
                else:
                    n = _norm(_mat_lin(rt.world[p2.tf], p.end_offset))
                num2 = 1.0 + (p.stiffness - 1.0) * self.weight
                if num2 > 0.0:
                    m = list(rt.world[p2.tf])
                    m[3], m[7], m[11] = p2.pos
                    localv = (mat4_pos(rt.local[p.tf]) if p.tf is not None
                              else p.end_offset)
                    vec = _mat_pt(m, localv)
                    v2 = tuple(vec[k] - p.pos[k] for k in range(3))
                    mag = _norm(v2)
                    num3 = n * (1.0 - num2) * 2.0
                    if mag > num3 and mag > 1e-12:
                        p.pos = tuple(p.pos[k] + v2[k] * ((mag - num3) / mag)
                                      for k in range(3))
                v3 = tuple(p2.pos[k] - p.pos[k] for k in range(3))
                mag2 = _norm(v3)
                if mag2 > 1e-12:
                    p.pos = tuple(p.pos[k] + v3[k] * ((mag2 - n) / mag2)
                                  for k in range(3))
            else:
                p.prev = p.pos
                p.pos = rt.pos(p.tf)

    def _apply(self, rt):
        for i in range(1, len(self.particles)):
            p = self.particles[i]
            p2 = self.particles[p.parent]
            # ⚠️2026-10-10 修正：源码（Assets\Raw\Scripts\DynamicBone.cs L579）判的是
            #   `particle2.m_Transform.childCount <= 1` —— **Transform 的子节点数**，
            #   包含渲染件等**非粒子**子节点；不是"粒子链里的子粒子数"。
            #   单链 rig 两种口径恰好都是 1（所以 Alice/Alexandra 没暴露），
            #   而分叉链 + 骨头下挂渲染件时两边相反 ⇒ 整条分支歪掉
            #   （PXSilky 头发/外套 100~560px 就是这个）。
            _cc = len(self._children.get(p2.tf, ())) if p2.tf is not None else 0
            if _cc <= 1:
                vec = (mat4_pos(rt.local[p.tf]) if p.tf is not None
                       else p.end_offset)
                v2 = tuple(p.pos[k] - p2.pos[k] for k in range(3))
                # `particle2.m_Transform.TransformDirection(vector)` —— 同样要用四元数链
                q = q_from_to(q_rotate(rt.world_rot(p2.tf), vec), v2)
                rt.set_world(p2.tf, quat=q_mul(q, rt.quat(p2.tf)))
            if p.tf is not None:
                rt.set_world(p.tf, pos=p.pos)
