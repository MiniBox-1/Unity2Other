# -*- coding: utf-8 -*-
"""静态磁盘资源(prefab/场景实例 + Mesh/材质/Sprite/动画) -> Spine 3.8

原则（见 docs/静态prefab路线.md）：
- 导出只读磁盘静态资源；Unity 编辑器/运行态导出的 PoseFrames/SceneT0 等
  只用于逐帧校准，不参与成品导出；
- setup 姿态 = 所选动画 clip 的 t=0 采样；后续帧用同一 clip 采样骨骼局部
  T/R/S，重建世界矩阵后蒙皮，写 mesh deform；
- 部件的朝向/镜像一律由 Unity 世界矩阵决定，不做按名字的硬编码翻转。

与旧实现相比修掉的三处根因（都能在校准里量出来）：
1. `trs_mat` 缩放顺序：Unity 是 M = T·R·S（按列缩放），旧实现写成 M = T·S·R。
   仅在“非均匀/带负号缩放 + 有旋转”的节点上出问题，正是 ch_root
   ([-1,1,0.15])、面罩 parts_head ([-1,1,1])、腿部骨骼 ([-0.9,0.9,0.14])，
   表现为面罩朝向/镜像反复错、运动中部件分离。
2. Mesh blend 索引：同一 format(10) 在不同资源里既可能是原始整数，也可能是
   float 位模式；旧实现写死后者，遇到前者时所有顶点绑到第 0 根骨骼。
3. 动画曲线 path 换行：Unity 序列化超长路径会换行续写，旧实现只取第一行，
   曲线被套到“少了 (n) 后缀”的同名节点上。

用法：
  python -m ngui2spine.static_prefab_spine <prefab> <out_dir>
      [--scene <save.unity>] [--clip lobby] [--dt 0.05] [--flip-x]
      [--calib] [--secondary-anim] [--no-face-check]
"""

import argparse
import binascii
import json
import math
import os
import re
import shutil
import subprocess
import sys
import copy

from ..convert.convert_2dmodel import (_asset_path, _skin_mesh, _world_matrices,
                              build_character_model, sprite_part_mesh)
from ..spine.spine_out import atlas_text, fnum, write_viewer_config
from ..unity.unity_2dmodel import (TwoDModel, _dfs_transforms,
                            parse_animator_controller,
                            parse_animator_layers, pick_main_animator,
                            rel_path_in)
from ..unity.unity_anim2d import (AnimSampler, euler_to_quat, parse_clip,
                           quat_to_euler, trs_mat)
from ..unity.unity_mesh import mat4_vec, parse_sprite

# 内置 shader fileID → 混合模式。名字是**用 Unity 引擎实测**出来的
# （`_scratch\_csbake\probe_shader_names.cs`：加载材质问 `mat.shader.name`），
# 不再靠猜。2026-10-10 补齐：以前只认 200/205，`202 Additive (Soft)`、
# `206 Multiply (Double)`、`10720 Mobile/Particles/Additive` 全被当普通透明。
SHADER_ADDITIVE = {
    200,    # Legacy Shaders/Particles/Additive
    202,    # Legacy Shaders/Particles/Additive (Soft)
    10720,  # Mobile/Particles/Additive   ← 实测 `3P_Ran_NS1` 的 fx_gas_hit_01 用它
}
SHADER_SCREEN = set()          # 内建里没有 screen
#: 默认视作普通透明的内建（登记出来只为报告清楚，语义本来就是 normal）
SHADER_NORMAL = {46, 103, 104, 201, 203, 10750, 10751, 10753, 10754}
#: 内建 "Legacy Shaders/Particles/Multiply"（fileID 205）。影子用这种材质：
#: 片元是 `col = 2 * i.color * _TintColor * tex`，混合 `Blend Zero SrcColor`
#: ⇒ **把背景乘暗**。当作普通 alpha 导出就会变成"贴图原色半透明"（实测 Alice
#: 的两个影子渲染成浅粉半透明，用户一眼就看出来）。
#: 默认怎么导？见下面的 `MULTIPLY_BLEND`：**烘进图集**（槽位仍写 normal）。
SHADER_MULTIPLY = {
    205,    # Legacy Shaders/Particles/Multiply
    206,    # Legacy Shaders/Particles/Multiply (Double)
}

#: 乘法件的导出策略（2026-10-10 用户指令：**默认"直接对图集处理"**，
#: 其它非默认的导出设定一律归档为"实验性方法"，默认路径不用它们）
#:
#: * `False`（**默认口径**）：把乘法**烘进图集**。Unity 是 `out = dst × m`
#:   （`m = 2·i.color·_TintColor·tex.rgb`），而普通 alpha 混合在 `src.rgb = 黑`
#:   时是 `out = dst×(1−src.a)`，所以令 `tex.a = 1 − m`、槽位颜色取"黑 + 原 alpha"
#:   就与乘法**逐像素等价**（因子为灰时完全等价；贴图白底 → 乘 1 → α=0 自然不可见，
#: α 掩码贴图也自动正确）。好处：产物**不依赖运行时的 multiply 混合支持**，
#: 查看器/编辑器/任意引擎直接看就对。
#: * `True`（**实验**，命令行 `--multiply-blend` 或环境变量
#:   `U2S_MULTIPLY_BLEND=1`）：保留 `blend=multiply`，贴图直通 + 区域 α=1，
#:   交给 Spine 的 multiply 混合（PMA Multiply = `DstColor OneMinusSrcAlpha`）。
MULTIPLY_BLEND = os.environ.get("U2S_MULTIPLY_BLEND", "") == "1"


def apply_multiply_policy(e, assets=None):
    r"""按 `MULTIPLY_BLEND` 改写一个"乘法件"条目（就地；返回同一个条目）。

    默认口径下把"乘法因子"从槽位颜色搬到 `mult_factor`（图集阶段按它烘 texel），
    槽位改成"黑 + 原 alpha"、`blend=normal`。

    **2026-10-10 修正（Unity 实测，`_scratch\_csbake\probe_shader_blend.cs`）**：
    `Legacy Shaders/Particles/Multiply` 的真实合成是
        out.rgb = dst.rgb × (1 − src.a·(1 − m0))
        m0    = 2·i.color.rgb·_TintColor.rgb·tex.rgb   （逐通道）
        src.a = 2·i.color.a·_TintColor.a·tex.a
    也就是说 **alpha 是"乘暗强度"的调制**：alpha=0 → 什么都不改，alpha 越小影子越淡
    （这就是"略透明的影子"的由来）。所以烘 texel 时 α 必须 = `2·_TintColor.a·tex.a·(1−m0)`，
    而渲染器自己的 alpha（`i.color.a`）留在**槽位颜色**里（含它的动画）。
    早先只烘 `1−m0` ⇒ 贴图透明区也被画成实心暗块（用户看到的"胸/脸变黑、多边形淡影"）。
    """
    if e.get("blend") != "multiply" or MULTIPLY_BLEND:
        return e
    col = e["color"]
    e["mult_factor"] = [float(col[0]), float(col[1]), float(col[2])]
    # `_TintColor` 没写在 .mat 里时用 shader 内建默认 (0.5,0.5,0.5,0.5)
    # ⇒ α 倍率 2·tint.a = 1；写在 .mat 里就用它自己的 a。
    ta = float(PARTICLE_TINT_DEFAULT[3])
    if assets is not None:
        mats = getattr(e["part"], "materials", None) or []
        info = read_material(assets, mats[0]) if mats else None
        if info and info.get("tintSaved"):
            ta = float(info["tint"][3])
    e["mult_alpha"] = 2.0 * ta          # 贴图 alpha 的倍率（口径见 docstring）
    e["bake_multiply"] = True
    e["blend"] = "normal"
    e["color"] = [0.0, 0.0, 0.0, float(col[3])]
    return e


_CUSTOM_SHADER_CACHE = {}


def _custom_shader_blend(assets, guid):
    """自定义 shader：读它的 `.shader` 源码里的 `Blend` 指令判断混合模式。

    返回 `(名字, blend, premultiply)`；blend ∈ normal/additive/multiply/screen。

    为什么要"看源码"而不是白名单：用户要求"转换器能自动识别不同部件的 shader"，
    而工程里（这是个用了 Spine 的游戏）光自定义 shader 就有 132 个 —— 按
    `Blend` 指令判语义比维护白名单稳；名字里带 Multiply/Screen/Additive 的
    作为兜底（源码缺失时用）。
    """
    if guid in _CUSTOM_SHADER_CACHE:
        return _CUSTOM_SHADER_CACHE[guid]
    name, blend, premul = "", "normal", False
    p = _asset_path(assets, guid)
    if p and os.path.isfile(p):
        t = open(p, encoding="utf-8", errors="replace").read()
        m = re.search(r'Shader\s+"([^"]+)"', t)
        name = m.group(1) if m else os.path.basename(p)
        bl = re.findall(r"^\s*Blend\s+(.+?)\s*$", t, re.M)
        if bl:
            parts = re.split(r"[,\s]+", bl[0].strip())
            src, dst = (parts[0], parts[1]) if len(parts) >= 2 else ("", "")
            if dst == "OneMinusSrcColor":
                blend = "screen"          # 例：Spine PMA Screen
            elif dst.startswith("DstColor"):
                blend = "multiply"        # 例：Spine PMA Multiply
            elif (src in ("SrcAlpha", "SrcAlphaSaturate") and dst == "One") \
                    or (src == "One" and dst == "One"):
                blend = "additive"        # 例：Spine PMA Additive
            elif src == "One" and dst == "OneMinusSrcAlpha":
                premul = True             # 预乘 alpha 的普通混合
        else:
            low = name.lower()
            if "multiply" in low:
                blend = "multiply"
            elif "screen" in low:
                blend = "screen"
            elif "additive" in low:
                blend = "additive"
    _CUSTOM_SHADER_CACHE[guid] = (name, blend, premul)
    return _CUSTOM_SHADER_CACHE[guid]
PARTICLE_TINT_DEFAULT = (0.5, 0.5, 0.5, 0.5)     # 内建粒子系 shader 的 _TintColor 默认值

#: 显隐求值口径：**按 Unity 运行时语义**（关键帧之间按切线插值 + `|v|>1e-3` 即"开"，
#: 依据 `Unity运行时逆向报告.md` 的反汇编 + 同版本实测）。
#: `--active-step` 可切到"阶跃 + v>=0.5"（只用于 A/B 对拍）。
#:
#: 2026-09-17 用 Play 模式参考帧（`Assets/Editor/PlayRefShot.cs`，7 个角色 ×
#: 数十帧，含 `activeSelf/activeInHierarchy/enabled`）**实测确认**：运行时就是这一套。
#: 反例（当时一度改成阶跃，被这份真值打回来）：
#:   · `draculina_skin1` `Part_Heart_L` 的父节点曲线在 t=0.15/0.5/1.0 只有
#:     **0.001 / 0.009 / 0.034**，Unity 真值是**显示**；阶跃口径（v>=0.5）会把它藏掉 ⇒
#:     心形特效/腮红/手臂阴影等一批件"整段消失"（实测 draculina 181 处、banshee 57 处不一致）。
#:   · 反过来，"多口/多眼"那种 0<v<1 的重叠在**运行时确实存在**（Play 真值里
#:     draculina 四个口 `activeInHierarchy` 全 True），但画面上是干净的 ——
#:     靠的是 **m_Color 的 alpha 时间轴**（3.33 已修）。所以正确组合是
#:     "**运行时口径 + 正确的 alpha**"，不是"把显隐改成阶跃"。
USE_RUNTIME_ACTIVE = True

#: **运行时没绑上的祖先 m_IsActive**（实测例外表；路径相对 Animator 根）。
#: 判据：Play 真值里那条曲线明明是 0，它的子件 `activeInHierarchy` 却还是 1
#: ⇒ Unity 根本没应用这条 SetActive。我们如果按"父链 AND"照算，就会把子件误藏。
#:   · `bheur_skin1` Lobby t=0：`Bone_Close_Eye` 曲线值 0，但 `Part_Eye_Close_L`
#:     真值 activeInHierarchy=1（且 t=0 时该件自己的曲线是 1）⇒ 这条不生效。
#: 只放**有真值证据**的条目，宁少勿多。
ACTIVE_DEAD_BY_ROLE = {
    "bheur_skin1": (
        "Bone_COM/Bone_Pelvis/Bone_Spine/Bone_Head/Bone_Close_Eye",
    ),
}


def dead_active_paths(mdl):
    """当前角色那些"运行时没绑上"的 m_IsActive 路径集合。"""
    root = (getattr(mdl, "anim_root_path", "") or "")
    role = root.split("/")[0].split("\\")[0]
    return set(ACTIVE_DEAD_BY_ROLE.get(role, ()))


# ------------------------------------------------------------------ 基础解析

def _flip_v(uvs):
    """Unity mesh UV（v=0 在贴图底行）-> 本渲染链路的 v（=0 在顶行）。"""
    return [(u, 1.0 - v) for u, v in uvs]


def _tex_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def _num_or(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _rgba_from(text_block, key):
    m = re.search(re.escape(key) + r":\s*\{r:\s*([-0-9.eE]+),\s*g:\s*([-0-9.eE]+),"
                                     r"\s*b:\s*([-0-9.eE]+),\s*a:\s*([-0-9.eE]+)\}",
                  text_block)
    if not m:
        return None
    return tuple(max(0.0, min(1.0, float(x))) for x in m.groups())


_MAT_CACHE = {}


def read_material(assets, guid):
    """读 .mat：是否加色、_TintColor、_Color。"""
    if not guid:
        return None
    if guid in _MAT_CACHE:
        return _MAT_CACHE[guid]
    path = _asset_path(assets, guid)
    info = {"path": path, "additive": False, "tint": (1.0, 1.0, 1.0, 1.0),
            "multiply": False, "screen": False, "premultiply": False,
            "shaderName": None,
            "color": (1.0, 1.0, 1.0, 1.0)}
    if path and os.path.isfile(path):
        text = open(path, encoding="utf-8", errors="replace").read()
        sm = re.search(r"m_Shader:\s*\{fileID:\s*(\d+),\s*guid:\s*([0-9a-f]+)",
                       text)
        if sm:
            fid = int(sm.group(1))
            sg = sm.group(2)
            builtin = sg.startswith("0000000000000000")
            info["shaderFileID"] = fid
            info["shaderGuid"] = sg
            if builtin:
                info["additive"] = fid in SHADER_ADDITIVE
                info["multiply"] = fid in SHADER_MULTIPLY
                info["screen"] = fid in SHADER_SCREEN
            else:
                # 自定义 shader：按源码里的 Blend 指令自动识别（见 §shader 清点）
                nm, bl, pm = _custom_shader_blend(assets, sg)
                info["shaderName"] = nm
                info["additive"] = (bl == "additive")
                info["multiply"] = (bl == "multiply")
                info["screen"] = (bl == "screen")
                info["premultiply"] = pm
        tint = _rgba_from(text, "_TintColor")
        if tint:
            info["tint"] = tint
            info["tintSaved"] = True
        col = _rgba_from(text, "_Color")
        if col:
            info["color"] = col
    _MAT_CACHE[guid] = info
    return info


def _sprite_color(part):
    """SpriteRenderer 的最终顶点色（含材质 tint / 加色 shader 的 2x）。

    Legacy Particles/Additive 的片元是 col = 2 * i.color * _TintColor * tex，
    混合是 SrcAlpha One；本链路里加色 slot 用 (ONE, ONE)，贴图按 alpha 预乘，
    因此要把它折进 slot 颜色：
        S.rgb = 4 * _TintColor.rgb * _TintColor.a * i.color.rgb * i.color.a
    对 T=(0.5,0.5,0.5,0.5)、i.color.a=1 就恰好等于 i.color.rgb（与 Unity 一致）。
    """
    c = part.color or {}
    r = _num_or(c.get("r", 1), 1.0)
    g = _num_or(c.get("g", 1), 1.0)
    b = _num_or(c.get("b", 1), 1.0)
    a = _num_or(c.get("a", 1), 1.0)
    return [r, g, b, a]


def sprite_style(assets, part):
    """返回 (color[r,g,b,a], blend, premultiply)。

    blend 为 'normal' / 'additive' / 'multiply'（后者对应 Unity 的
    `Particles/Multiply`，影子部件就用它把背景乘暗）。
    """
    col = _sprite_color(part)
    mats = getattr(part, "materials", None) or []
    info = read_material(assets, mats[0]) if mats else None
    if info and info.get("additive"):
        t = info["tint"]
        f = [4.0 * t[0] * t[3], 4.0 * t[1] * t[3], 4.0 * t[2] * t[3]]
        # Unity：`out = dst + src.rgb·src.a`，src.rgb=2·i.color.rgb·_TintColor.rgb·tex.rgb、
        #        src.a = 2·i.color.a·_TintColor.a·tex.a。
        # 我们：图集把该区域按 tex.a 预乘、`blend=additive`(ONE/ONE)。
        # ⚠️ 运行时不把颜色 alpha 乘进 rgb（查看器 `shader_type=1` 非 PMA）⇒
        #    `i.color.a` 必须**折进槽位 rgb**，否则加色件亮 ~1/i.color.a 倍。
        #    对应地把"alpha 淡入淡出"搬到 rgb 通道（见 color_timeline 的 fade_rgb_alpha）。
        a = col[3]
        return ([col[0] * f[0] * a, col[1] * f[1] * a, col[2] * f[2] * a, 1.0],
                "additive", True)
    if info and info.get("multiply"):
        # 乘法 shader：`col.rgb = 2 * i.color.rgb * _TintColor.rgb * tex.rgb`
        # （不乘 _TintColor.a；材质里没存 _TintColor 时用内建默认的 0.5 灰 ⇒ 系数 1）
        t = info["tint"] if info.get("tintSaved") else PARTICLE_TINT_DEFAULT
        f = [2.0 * t[0], 2.0 * t[1], 2.0 * t[2]]
        return ([min(1.0, col[0] * f[0]), min(1.0, col[1] * f[1]),
                 min(1.0, col[2] * f[2]), col[3]],
                "multiply", False)
    if info and info.get("screen"):
        return (col, "screen", False)
    # Sprites/Default 一类的普通 alpha 混合：颜色 = 顶点色 * 材质 _Color
    if info:
        c = info["color"]
        col = [col[0] * c[0], col[1] * c[1], col[2] * c[2], col[3] * c[3]]
    return (col, "normal", bool(info and info.get("premultiply")))


def mesh_style(assets, part):
    """静态/蒙皮 mesh 的顶点色 + 混合（**与 `sprite_style` 同口径**）。

    ★ 2026-10-10 修的真 bug：以前这里**永远返回 normal**，于是"蒙皮/静态网格"材质的
    加色件与乘法件全被当普通透明。用户报的 `2DModel_BR_May_NS3` 的
    `parts_Breast_Shadow_Multiple_015_Skinned`（乘法阴影）就是这么错的；
    同类还有 `PECS_Babariana_NS1` 的 `..._shadow`、`BR_DrM_NS1` 的 `R_Thigh_Multiply`、
    `PECS_DarkElf_*` 的 `*_Multiply`、`ST_Tiamat` 的 `parts Multiply` 等。
    """
    col = [1.0, 1.0, 1.0, 1.0]
    mats = getattr(part, "materials", None) or []
    info = read_material(assets, mats[0]) if mats else None
    if not info:
        return col, "normal", False
    c = info["color"]
    col = [col[i] * c[i] for i in range(4)]
    if info.get("additive"):
        # 与 sprite_style 一致：Legacy Particles/Additive 是
        # `col = 2 * i.color * _TintColor * tex` + `SrcAlpha One`，
        # 折成加色 slot 的 (ONE, ONE) 颜色；`i.color.a` 必须折进 rgb（非 PMA 运行时
        # 不会把颜色 alpha 乘进 rgb），alpha 固定 1（淡入淡出走 rgb 通道）
        t = info["tint"]
        f = [4.0 * t[0] * t[3], 4.0 * t[1] * t[3], 4.0 * t[2] * t[3]]
        a = col[3]
        return ([col[0] * f[0] * a, col[1] * f[1] * a, col[2] * f[2] * a, 1.0],
                "additive", True)
    if info.get("multiply"):
        t = info["tint"] if info.get("tintSaved") else PARTICLE_TINT_DEFAULT
        f = [2.0 * t[0], 2.0 * t[1], 2.0 * t[2]]
        return ([min(1.0, col[0] * f[0]), min(1.0, col[1] * f[1]),
                 min(1.0, col[2] * f[2]), col[3]],
                "multiply", False)
    if info.get("screen"):
        return (col, "screen", False)
    return (col, "normal", bool(info.get("premultiply")))


def _hex_color(col):
    vals = [max(0, min(255, int(round(float(v) * 255)))) for v in col[:4]]
    return "%02x%02x%02x%02x" % tuple(vals)


def _mcolor(part):
    """SpriteRenderer 的原始 m_Color（动画 m_Color.* 曲线的静态基准）。"""
    c = getattr(part, "color", None) or {}
    return [_num_or(c.get(k, 1), 1.0) for k in ("r", "g", "b", "a")]


def _sample_float_keys(keys, t):
    """浮点曲线线性插值（颜色曲线用；值变化平缓，与 Unity 的差别可忽略）。"""
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    for i in range(1, len(keys)):
        if t <= keys[i][0]:
            t0, v0 = keys[i - 1]
            t1, v1 = keys[i]
            if t1 - t0 <= 1e-9:
                return v1
            k = (t - t0) / (t1 - t0)
            return v0 + (v1 - v0) * k
    return keys[-1][1]


# ------------------------------------------------------------------ 部件/几何

def load_character(prefab, assets, scene=None, animated_only=True):
    """返回 (mdl, parts)；parts 带 full_path，anim_path 按本角色 Animator 归一。

    多角色共用 save.unity 时，`TwoDModel.build` 会取到场景里**第一个**
    Animator（可能是别的角色），导致拿错控制器/裁剪路径；这里在筛出本角色
    子树后重新选 Animator 并重算 anim_path。

    animated_only=True（默认）时，只保留**挂在 Animator 子树下**的部件：
    audrey 这类"静态立绘 + 动态立绘"双根角色，静态立绘（整张 Fullbody
    sprite）会带来一张与动画无关的大图，按此规则排除。
    """
    src = scene or prefab
    mdl, parts = build_character_model(src, assets)
    if scene:
        root_name = os.path.splitext(os.path.basename(prefab))[0]

        def _in_subtree(path):
            """场景里同名实例会被 Unity 命名成 "xxx (1)"，也要算作本角色。"""
            head = (path or "").split("/")[0]
            return (head == root_name
                    or head.startswith(root_name + " (")
                    or head.startswith(root_name + "("))

        # 只保留当前角色子树，避免多个动画根 anim_path='' 互相覆盖
        kept = {tfid: t for tfid, t in mdl.transforms.items()
                if _in_subtree(t["path"])}
        if not kept:
            # 场景里没有这个角色（场景被换过、或这个角色没放进去）：
            # 退回按 prefab 解析，否则会导出 0 个部件。
            # 注意：**不能直接 return**——后面还有“只保留 Animator 子树 +
            # 记录 excluded_parts”的公共收尾。提前 return 会让 audrey 那种
            # “静态立绘 + 动态立绘”双根角色把整张立绘也导出去，
            # 也会因为少了 excluded_parts 直接抛 AttributeError。
            print("[warn] 场景里找不到 %s，回退到 prefab 解析" % root_name)
            mdl, parts = build_character_model(prefab, assets)
            mdl.char_animators = list(mdl.animators or [])
        else:
            mdl.transforms = kept
            keep = []
            for p in parts:
                fp = mdl.transforms.get(p.tfid, {}).get("path", "")
                if _in_subtree(fp):
                    keep.append(p)
            parts = keep
            # 重新挑选属于本角色子树的 Animator
            keep_gos = {t["go"] for t in mdl.transforms.values()}
            cand = [a for a in (mdl.animators or []) if a.get("go") in keep_gos]
            # 与 Unity 的 GetComponentInChildren<Animator>(true) 对齐：按层级
            # 深度优先取第一个（场景里组件文档顺序和 prefab 不同，取
            # animators[0] 会选错）
            tops = [tfid for tfid, t in mdl.transforms.items()
                    if t.get("father") not in mdl.transforms]
            pick = pick_main_animator(mdl.transforms, cand, tops)
            if pick is not None:
                mdl.animator_controller_guid = pick.get("controllerGuid")
                mdl.anim_root_name = mdl.gameobjects.get(
                    pick.get("go"), {}).get("name", "")
                mdl.anim_root_path = next(
                    (t["path"] for t in mdl.transforms.values()
                     if t["go"] == pick.get("go")), "")
                _assign_anim_paths(mdl, mdl.anim_root_path)
                dedupe_anim_paths(mdl, log=lambda m: print(m))
            # 记录本角色子树内的全部 Animator（可能不止主控制器）
            mdl.char_animators = [a for a in (mdl.animators or [])
                                  if a.get("go") in keep_gos]
    else:
        mdl.char_animators = list(mdl.animators or [])
        # 没带 --scene（按 prefab 解析）时也要做同名孪生的解绑
        dedupe_anim_paths(mdl, log=lambda m: print(m))
    for p in parts:
        p.full_path = mdl.transforms.get(p.tfid, {}).get("path", "")
    # 只保留 Animator 子树（含 Animator 所在物体自身）
    mdl.excluded_parts = []
    if animated_only:
        anim_gos = {a.get("go") for a in (getattr(mdl, "char_animators", None)
                                          or [])}
        if anim_gos:
            keep = []
            for p in parts:
                tfid = p.tfid
                ok = False
                hops = 0
                while tfid is not None and hops < 500:
                    td = mdl.transforms.get(tfid)
                    if td is None:
                        break
                    if td.get("go") in anim_gos:
                        ok = True
                        break
                    tfid = td.get("father")
                    hops += 1
                if ok:
                    keep.append(p)
                else:
                    mdl.excluded_parts.append(
                        {"path": p.full_path, "kind": p.kind,
                         "reason": "不在任何 Animator 子树下（静态立绘/装饰）"})
            parts = keep
    return mdl, parts


def _assign_anim_paths(mdl, anim_root_path):
    """动画曲线路径是相对 Animator 所在物体的，这里按该物体的**全路径**重算。

    按全路径分段截断，不能用名字 find/rfind：节点重名、或宿主名互为前缀时
    （babariana 的 `Char_X` / `Char_X_Bg_Only`）会截到错误位置。
    """
    for td in mdl.transforms.values():
        rel = rel_path_in(anim_root_path, td.get("path") or "")
        td["anim_path"] = (td.get("path") or "") if rel is None else rel


def dedupe_anim_paths(mdl, log=None):
    """**同名孪生节点：只有第一个吃曲线**（对齐 Unity 的绑定算法）。

    Unity 的 `Animator` 绑定键是「路径 + 同名序号」：同一条路径下的第 2、3… 个节点
    **不会**被绑上，它们保持 prefab 姿态。我们原来按"路径字符串"一对多绑定，
    于是一套曲线被套给所有同名节点 ⇒ 多画一件（位置错的那件）：banshee 手腕
    "多一块 + 硬黑线"、`brownie_skin1` 左手"丢件"就是这个。

    做法：按 **DFS 序**（= Unity 找节点的顺序：逐层按 `m_Children` 顺序）走一遍，
    同一 `anim_path` 第二次出现就把它的 `anim_path` 置 `None` —— 之后所有
    `_curve_lookup` 都查不到曲线（`td.get("anim_path") or ""` → 空 → 直接返回 None），
    该节点就用 rest/prefab 姿态。

    返回被解绑的节点数（0 = 没有同名孪生）。
    """
    seen = set()
    n = 0
    for tfid in _dfs_transforms(mdl.transforms, getattr(mdl, "roots", None) or []):
        td = mdl.transforms.get(tfid)
        if td is None:
            continue
        ap = td.get("anim_path")
        if ap is None or ap == "":
            continue
        if ap in seen:
            td["anim_path"] = None
            n += 1
        else:
            seen.add(ap)
    if n and log:
        log("[anim] 同名孪生节点：%d 个节点按 Unity 规则**不绑曲线**（保持 prefab 姿态）" % n)
    return n


#: Unity 的 AnimationClip 有一部分曲线把节点路径**换成了哈希**，序列化成
#: `path: path_0x<8位HEX>_<7字符>`（游戏里打包过的资源大量如此）。哈希就是
#: **CRC32(路径字符串)** —— 实测 alice_skin2 的 4 条全部唯一命中（见
#: docs/静态prefab路线.md 3.36）。不还原的话这些曲线绑不到任何节点：
#: `m_IsActive` 丢了 → 该显示的表情/手一直不显示；位姿曲线丢了 → 骨骼不动。
HASHED_PATH_RE = re.compile(r"^path_0x([0-9A-Fa-f]+)")


def path_hash(text):
    """Unity 的曲线路径哈希：CRC32（IEEE，标准反射式，UTF-8 字节）。"""
    return binascii.crc32(text.encode("utf-8")) & 0xFFFFFFFF


def hashed_path_table(mdl, host_go=None):
    """{CRC32(相对路径): 相对路径}；相对基 = 宿主全路径（缺省主 Animator 根）。"""
    # 缓存挂在模型对象上：用 id(mdl) 做 key 会在对象释放后撞上复用的 id
    cache = getattr(mdl, "_hashed_path_tables", None)
    if cache is None:
        cache = {}
        try:
            mdl._hashed_path_tables = cache
        except Exception:                          # 只读对象：退回每次重算
            cache = {}
    hit = cache.get(host_go)
    if hit is not None:
        return hit
    base = ""
    if host_go is not None:
        for td in mdl.transforms.values():
            if td.get("go") == host_go:
                base = td.get("path") or ""
                break
    if not base:
        base = getattr(mdl, "anim_root_path", "") or ""
    table = {}
    for td in mdl.transforms.values():
        full = td.get("path") or ""
        rel = full if not base else rel_path_in(base, full)
        if rel is None:
            continue
        table.setdefault(path_hash(rel), rel)
    cache[host_go] = table
    return table


def remap_hashed_paths(clip, table):
    """把 clip 里 `path_0x...` 的曲线键换成真实路径（就地改）。

    返回没解出来的哈希清单（调用方可以记进产物 meta 里对账）。
    """
    if not table or not isinstance(clip, dict):
        return []
    miss = []

    def fix(d):
        for k in [k for k in d if k.startswith("path_0x")]:
            m = HASHED_PATH_RE.match(k)
            real = table.get(int(m.group(1), 16)) if m else None
            if real is None:
                miss.append(k)
                continue
            if real not in d:
                d[real] = d[k]
            d.pop(k)

    for name in ("active", "active_tan", "enabled", "enabled_tan", "sorting",
                 "sorting_tan", "color", "material", "morph", "morph_tan",
                 "pptr"):
        d = clip.get(name)
        if isinstance(d, dict) and d:
            fix(d)
    for cu in clip.get("curves") or []:
        p = getattr(cu, "path", "") or ""
        if not p.startswith("path_0x"):
            continue
        m = HASHED_PATH_RE.match(p)
        real = table.get(int(m.group(1), 16)) if m else None
        if real is None:
            miss.append(p)
        else:
            cu.path = real
    if miss:
        clip["_unresolved_paths"] = sorted(set(
            list(clip.get("_unresolved_paths") or []) + miss))
    return miss


def resolve_clip_paths(mdl, host_go, clip):
    """按宿主把 clip 里的哈希路径还原成真实路径。"""
    remap_hashed_paths(clip, hashed_path_table(mdl, host_go))
    return clip


def _main_animator_go(mdl):
    """主 Animator 所在物体（曲线哈希表的相对基）。"""
    for a in (getattr(mdl, "char_animators", None) or []):
        if a.get("controllerGuid") == mdl.animator_controller_guid:
            return a.get("go")
    for a in (mdl.animators or []):
        if a.get("controllerGuid") == mdl.animator_controller_guid:
            return a.get("go")
    return None


def _choose_clip(mdl, assets, clip_hint):
    """
    选"主 clip"。规则要和 Unity 侧 TwoDModelCalibExport.MainClip 一致：
   按 **clip 资源名**（不是 Animator state 名）判断——很多项目的 state 叫
    lobby，但引用的动画文件其实叫 idle/xxx，用 state 名会选错动画。
    """
    if not mdl.animator_controller_guid:
        return None, None
    cp = _asset_path(assets, mdl.animator_controller_guid)
    if not cp or not os.path.isfile(cp):
        return None, None
    host = _main_animator_go(mdl)
    states = parse_animator_controller(cp)
    cands = []
    for st in states:
        cl = _asset_path(assets, st.get("clipGuid") or "")
        if not cl or not os.path.isfile(cl):
            continue
        cands.append((st["name"],
                      resolve_clip_paths(mdl, host, parse_clip(cl))))
    if not cands:
        return None, None
    if clip_hint:
        for name, parsed in cands:
            if clip_hint.lower() in name.lower():
                return name, parsed
    # 1) clip 名含 lobby、且不含 start / tep / breast
    for name, parsed in cands:
        low = (parsed.get("name") or name).lower()
        if ("lobby" in low and "start" not in low
                and "tep" not in low and "breast" not in low):
            return name, parsed
    # 2) 退一步：任何含 lobby 的非 start
    for name, parsed in cands:
        low = (parsed.get("name") or name).lower()
        if "lobby" in low and "start" not in low:
            return name, parsed
    return cands[0]


def _all_clips(mdl, assets, clip_hint, secondary=False):
    """返回 [(animator_go, clip_name, clip)]；secondary=True 时含副 Animator。"""
    out = []
    seen = set()
    for ani in (mdl.animators or []):
        ctrl = ani.get("controllerGuid")
        go = ani.get("go")
        # 同一个 Controller 挂在两个 Animator 上是两个采样器（曲线 path 各相对
        # 自己的宿主），去重 key 必须带宿主，否则第二个会被整条丢掉。
        if not ctrl or (ctrl, go) in seen:
            continue
        main = (ctrl == mdl.animator_controller_guid)
        if not main and not secondary:
            continue
        cp = _asset_path(assets, ctrl)
        if not cp or not os.path.isfile(cp):
            continue
        states = parse_animator_controller(cp)
        cands = [(st["name"],
                  resolve_clip_paths(mdl, go,
                                     parse_clip(_asset_path(assets,
                                                            st["clipGuid"]))))
                 for st in states
                 if _asset_path(assets, st["clipGuid"])
                 and os.path.isfile(_asset_path(assets, st["clipGuid"]))]
        if not cands:
            continue
        if clip_hint:
            pick = next((c for c in cands if clip_hint.lower() in c[0].lower()),
                        cands[0])
        else:
            pick = next((c for c in cands if "lobby" in c[0].lower()
                         and "teq" not in c[0].lower()), cands[0])
        seen.add((ctrl, go))
        out.append((go, pick[0], pick[1]))
    return out


def _active_at(keys, t, tans=None):
    """m_IsActive / m_Enabled 曲线在 t 时刻的值（Unity 运行时语义）。

    `tans is None`：老行为 —— 一律当阶跃（取最后一个 time <= t 的关键帧值）。
    带切线时按 Unity 求值：斜率是 ±Infinity 的段是常值段，其余是 Hermite 插值。

    为什么不能一律当阶跃：Unity 只在**编辑器 Constant 切线**下才是阶跃；
    实测工程里的 m_IsActive 有 6191 条是平滑插值（slope=0）、314 条才是
    Constant。插值段里曲线值会处在 0~1 之间，而运行时的显隐判据是
    `|v| > 0.001`（不是 `v >= 0.5`，见 docs/Unity运行时逆向报告），
    于是"刚离开 0"就算显示 —— 只看关键帧值会把这段可见窗整段丢掉。
    """
    if not keys:
        return None
    if tans is None:
        val = keys[0][1]
        for kt, kv in keys:
            if kt <= t + 1e-9:
                val = kv
            else:
                break
        return val
    return unity_curve_eval(keys, tans, t)


#: Unity 判 m_IsActive / m_Enabled 的阈值：`|v| > 1e-3` 即"开"。
#: 见 `Animation::SetBoundCurveFloatValue` 的 case 7（SetActive）/ case 6（bool）。
ACTIVE_EPS = 1e-3

#: clip 里"写在脚本字段上"的曲线 → DynamicBone 字段名。
#: 这些曲线在 Unity 运行时**每帧覆盖**组件平值（头发/胸/裙摆的软硬是逐 clip 变的）。
#: 映射怎么定的：拿"曲线终值 = 预制体上的字段值"交叉验证，三只角色逐条对上
#: （HongRyun `Bone_Hair` = 0.07/0.02/0.01/0.01、`Bone_Breast` = 0.12/0.05/0.01/0.05；
#:   Tomoe `hair_set` 0.035/0.01；Alexandra `Hair` 0.05/0.01；Cerberus `Hair` 0.1/0.08）。
#: 还可由 `Tools/U2S/导出 clip 绑定清单`（工程内菜单）打印人类可读字段名复核。
SCRIPT_FIELD = {
    "script_0xD1FC4FBF_kjIuPVN": "damping",
    "script_0x2DE5D16F_VWimMWJ": "elasticity",
    "script_0x5517B11B_UvNsJTL": "stiffness",
    "script_0xB255EB_NMQLlTJ": "inert",
}


def unity_curve_eval(keys, tans, t):
    """按 Unity 的方式求一条曲线在 t 的值（weightedMode=None 的 Hermite）。

    与 `AnimationCurve.Evaluate` 等价：

        h(u) = (2u³-3u²+1)·v0 + (u³-2u²+u)·m0·dt
             + (-2u³+3u²)·v1 + (u³-u²)·m1·dt

    任一端斜率是 ±Infinity ⇒ 该段是常值段，取 v0（编辑器 Constant 的语义）。
    """
    if not keys:
        return 0.0
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    for i in range(len(keys) - 1):
        t0, v0 = keys[i]
        t1, v1 = keys[i + 1]
        if not (t0 <= t <= t1):
            continue
        if t1 <= t0:
            return v1
        m0 = tans[i][1] if i < len(tans) else 0.0
        m1 = tans[i + 1][0] if i + 1 < len(tans) else 0.0
        if math.isinf(m0) or math.isinf(m1):
            return v0
        dt = t1 - t0
        u = (t - t0) / dt
        h00 = 2 * u ** 3 - 3 * u ** 2 + 1
        h10 = u ** 3 - 2 * u ** 2 + u
        h01 = -2 * u ** 3 + 3 * u ** 2
        h11 = u ** 3 - u ** 2
        return h00 * v0 + h10 * m0 * dt + h01 * v1 + h11 * m1 * dt
    return keys[-1][1]


def active_is_on(v):
    """运行时判据：`|v| > 1e-3` 就是"显示"。"""
    return v is not None and abs(v) > ACTIVE_EPS


def active_flip_times(keys, tans, sub=16):
    """曲线在"开/关"之间翻转的时刻（用于保证短可见窗也被采样到）。

    段内会按 `sub` 等分粗扫，再对相邻状态不同的区间二分 —— 这样 0.005 秒
    的可见窗也不会被 0.05 的采样步长整个跳过。
    """
    if not keys or not tans or len(keys) < 2:
        return []
    out = []
    for i in range(len(keys) - 1):
        t0 = keys[i][0]
        t1 = keys[i + 1][0]
        if t1 <= t0:
            continue
        ts = [t0 + (t1 - t0) * k / float(sub) for k in range(sub + 1)]
        prev_t = ts[0]
        prev_on = active_is_on(unity_curve_eval(keys, tans, prev_t))
        for ct in ts[1:]:
            cur_on = active_is_on(unity_curve_eval(keys, tans, ct))
            if cur_on != prev_on:
                lo, hi = prev_t, ct
                for _ in range(40):
                    mid = (lo + hi) * 0.5
                    if active_is_on(unity_curve_eval(keys, tans, mid)) == prev_on:
                        lo = mid
                    else:
                        hi = mid
                # 必须**向上**取到 1e-6：`hi` 是"刚好等于阈值"的边界，
                # round() 可能把它舍回边界之前，采样时又变回"关"（1 帧假差异）。
                out.append(math.ceil(hi * 1e6) / 1e6)
            prev_t, prev_on = ct, cur_on
    return out


def pptr_value_at(keys, t):
    """PPtr 曲线（`m_PPtrCurves`）求值：**阶跃**，取最后一个 `time <= t` 的值。

    `keys` = [(time, guid, fileID), ...]。换贴图/换资源都是这种语义：
    到关键帧时刻才切换，中间不插值。
    """
    if not keys:
        return None
    val = None
    for k in keys:
        kt = k[0]
        if kt <= t + 1e-9:
            val = k[1]
        else:
            break
    return val if val is not None else keys[0][1]


#: ★ 叠加层（非 Base 层）的**循环相位**（秒）。默认 0 = "叠加层与 base clip 的 t=0 对齐"。
#:
#: 为什么要这个开关：Unity 里**非 Base 层的状态是"一直在跑、跨 base 状态不变"的**
#: （切 `lobby`→`Tep_1` 只重播 Base 层，Dress 层照跑）。所以录制/游戏里那一刻
#: 叠加层的相位 = "角色实例化后过了多久 mod 层 clip 时长" —— 离线转换器**原理上
#: 不可能知道**。实测 Echidna：真值里灯光"亮"从 **0.521s** 起（层 clip 1.5s），
#: 我们默认从 0 起 ⇒ 差 0.521s。
#: 用法：`U2S_LAYER_PHASE=0.521` 把叠加层整体**推迟** 0.521 秒采样
#: （等价于"叠加层比 base 早跑了 0.521s"），用于① 与某条真值逐帧对齐验收；
#: ② 需要"同步版"产物时。
LAYER_PHASE = float(os.environ.get("U2S_LAYER_PHASE", "0") or 0.0)


def _rotate_curve(keys, slopes, duration, phase):
    """把周期曲线整体**推迟** `phase` 秒（在 [0, duration) 内环形平移）。

    重复关键帧（= Unity 的瞬时切换）平移后仍**同刻相邻**，顺序不变
    （排序用 `(时间, 原下标)`，稳定）⇒ 阶跃语义不丢。
    """
    if not phase or not keys or not duration or duration <= 0:
        return list(keys), dict(slopes or {})
    tmp = []
    for i, (t, v) in enumerate(keys):
        tmp.append(((float(t) + phase) % duration, v, i))
    tmp.sort(key=lambda x: (x[0], x[2]))
    nk = [(t, v) for t, v, _i in tmp]
    ns = {}
    for j, (_t, _v, i) in enumerate(tmp):
        for side in ("in", "out"):
            if (i, side) in (slopes or {}):
                ns[(j, side)] = slopes[(i, side)]
    return nk, ns


def _loop_curve(keys, slopes, duration, until):
    """把一条曲线**按自身时长循环**复制到 `until` 秒（层 clip 比主 clip 短时用）。

    末尾补一个"回到首值"的关键帧，让循环接缝处平滑过渡（我们的采样器是
    钳制语义，不补的话接缝会保持末值）。

    `slopes` 是 UnityAnimCurve 的**字典**形式 `{(关键帧下标,'in'|'out'): 值}`；
    复制关键帧时下标要跟着重排。
    """
    sl_in = dict(slopes or {})
    if not keys or not duration or duration <= 0 or until <= duration:
        return list(keys), sl_in
    ks = list(keys)
    sl = dict(sl_in)
    if ks[-1][0] < duration - 1e-9:
        ks.append((duration, ks[0][1]))
        sl[(len(ks) - 1, "in")] = 0.0
        sl[(len(ks) - 1, "out")] = 0.0
    out_k = list(ks)
    out_s = dict(sl)
    k = 1
    while duration * k <= until + 1e-9:
        for i, (t, v) in enumerate(ks):
            nt = t + duration * k
            if nt <= until + 1e-9:
                j = len(out_k)
                out_k.append((nt, v))
                for side in ("in", "out"):
                    if (i, side) in sl:
                        out_s[(j, side)] = sl[(i, side)]
        k += 1
    return out_k, out_s


def _add_vec(a, b):
    """把两条曲线值（dict 或数值）按 Unity 的加性语义相加。"""
    if isinstance(a, dict) or isinstance(b, dict):
        a = a if isinstance(a, dict) else {}
        b = b if isinstance(b, dict) else {}
        return {k: float(a.get(k, 0.0)) + float(b.get(k, 0.0))
                for k in set(a) | set(b)}
    return float(a) + float(b)


def _sub_vec(a, b):
    if isinstance(a, dict) or isinstance(b, dict):
        a = a if isinstance(a, dict) else {}
        b = b if isinstance(b, dict) else {}
        return {k: float(a.get(k, 0.0)) - float(b.get(k, 0.0))
                for k in set(a) | set(b)}
    return float(a) - float(b)


def compose_layers(base, overlays, rest):
    """把其它 Animator 层合成进 base clip（返回新的 clip dict）。

    `overlays` = [(层名, clip, blend)]，blend 0=Override、1=Additive。

    * Override：同 path+kind 的曲线直接换掉；morph/显隐/排序/换图等表按 path 合并。
    * Additive：`v(t) = base(t) + (over(t) − over(0))`，在**关键帧并集**上重采样成
      新曲线；over 的 clip 比 base 短时按自身时长循环（实测 Unity 行为）。
      'rot'（四元数）曲线不做加性（本项目数据里没出现），保持 Override。
    """
    from ..unity.unity_anim2d import UnityAnimCurve
    out = dict(base)
    curves = {}
    for c in (base.get("curves") or []):
        curves[(c.path, c.kind)] = c
    morph = {p: dict(d) for p, d in (base.get("morph") or {}).items()}
    morph_tan = {p: dict(d) for p, d in (base.get("morph_tan") or {}).items()}
    dur_base = float(base.get("duration") or 0.0)
    for _lname, over, blend in overlays:
        dur_over = float(over.get("duration") or 0.0)
        # ★ 叠加层循环相位（见 LAYER_PHASE）。只对非 Base 层生效（`overlays` 就是它们）。
        _rot = (lambda ks, sl: _rotate_curve(ks, sl, dur_over, LAYER_PHASE))
        if int(blend) != 1:
            # ---- Override ----
            for c in (over.get("curves") or []):
                if LAYER_PHASE:
                    _k, _s = _rot(list(c.keys or []), c.slopes)
                    curves[(c.path, c.kind)] = UnityAnimCurve(
                        c.path, c.kind, _k, _s, getattr(c, "attribute", None))
                else:
                    curves[(c.path, c.kind)] = c
            for key in ("active", "active_tan", "enabled", "enabled_tan",
                        "sorting", "sorting_tan", "pptr", "color", "material"):
                if not over.get(key):
                    continue
                d = {p: dict(v) if isinstance(v, dict) else v
                     for p, v in (out.get(key) or {}).items()}
                for p, v in over[key].items():
                    if isinstance(v, dict) and isinstance(d.get(p), dict):
                        d[p].update(v)
                    else:
                        d[p] = v
                out[key] = d
            for p, d in (over.get("morph") or {}).items():
                morph.setdefault(p, {}).update(d)
            for p, d in (over.get("morph_tan") or {}).items():
                morph_tan.setdefault(p, {}).update(d)
            continue
        # ---- Additive ----
        tmp = AnimSampler({"curves": list(curves.values())}, rest=rest)
        for c in (over.get("curves") or []):
            if c.kind == "rot":
                curves[(c.path, c.kind)] = c        # 四元数不做加性，按覆盖处理
                continue
            # ★ 叠加层循环相位：先在 [0,dur) 内环形平移，再按自身时长循环铺满
            _rk, _rs = _rot(list(c.keys or []), c.slopes)
            ks, sl = _loop_curve(_rk, _rs, dur_over,
                                 max(dur_base, dur_over))
            if not ks:
                continue
            # 注意：要用**循环后**的曲线求值（原曲线超过自身时长的部分会被钳制，
            # 那样 t>dur_over 的叠加量就变成 0 了 —— 实测过这个坑）
            cl = UnityAnimCurve(c.path, c.kind, ks, sl)
            # ★ 加性参考值必须取**未平移**曲线的首值：Unity 的 additive 层是
            #   `out = base + (layer − layer 的状态起点值)`，而"状态起点"在
            #   我们的相位平移下对应的正是**未平移**的 t=0（平移只是让它在时间轴上
            #   提前/推迟，不改变它相对状态起点的偏差）。
            if LAYER_PHASE:
                _rk0, _rs0 = _loop_curve(list(c.keys or []), c.slopes, dur_over,
                                         max(dur_base, dur_over))
                ref = UnityAnimCurve(c.path, c.kind, _rk0, _rs0).value_at(0.0)
            else:
                ref = cl.value_at(0.0)
            b = curves.get((c.path, c.kind))
            times = sorted({0.0} |
                           {float(t) for t, _v in ks} |
                           ({float(t) for t, _v in (b.keys if b else [])}))
            new_keys = []
            for t in times:
                bv = (b.value_at(t) if b is not None
                      else _rest_value(rest, c.path, c.kind, tmp, t))
                new_keys.append((t, _add_vec(bv, _sub_vec(cl.value_at(t), ref))))
            curves[(c.path, c.kind)] = UnityAnimCurve(c.path, c.kind, new_keys, {})
        # 加性层的 morph 权重：同样按"减自身 0 点"叠加
        for p, d in (over.get("morph") or {}).items():
            for name, keys in d.items():
                if not keys:
                    continue
                ks, _sl = _loop_curve(list(keys), None, dur_over,
                                      max(dur_base, dur_over))
                w0 = float(keys[0][1])
                dst = morph.setdefault(p, {})
                base_keys = dst.get(name) or []
                b0 = float(base_keys[0][1]) if base_keys else 0.0
                times = sorted({float(t) for t, _v in ks} |
                               {float(t) for t, _v in base_keys})
                new = [(t, _lerp_keys(base_keys, t, b0) + (float(_val_at(ks, t)) - w0))
                       for t in times]
                dst[name] = new
                morph_tan.setdefault(p, {})[name] = [(0.0, 0.0)] * len(new)
    out["curves"] = list(curves.values())
    out["morph"] = morph
    out["morph_tan"] = morph_tan
    return out


def _val_at(keys, t):
    """阶跃取值（给 morph 这类逐帧关键帧用）。"""
    v = keys[0][1] if keys else 0.0
    for kt, kv in keys:
        if kt <= t + 1e-9:
            v = kv
        else:
            break
    return v


def _lerp_keys(keys, t, default=0.0):
    """在关键帧之间线性插值（morph 权重曲线用）。"""
    if not keys:
        return default
    if t <= keys[0][0]:
        return float(keys[0][1])
    if t >= keys[-1][0]:
        return float(keys[-1][1])
    for i in range(len(keys) - 1):
        t0, v0 = keys[i]
        t1, v1 = keys[i + 1]
        if t0 <= t <= t1:
            if t1 <= t0:
                return float(v1)
            f = (t - t0) / (t1 - t0)
            return float(v0) + (float(v1) - float(v0)) * f
    return default


def color_timeline(part, clip, anim_path, prefix, fnum, base_hex,
                   bake_dark=False, fade_rgb_alpha=None):
    """`m_Color.*` / `material._Color.*` → Spine 的 **slot 颜色时间轴**。

    Unity 里 SpriteRenderer 的 `m_Color`（含 alpha）和材质的 `_Color` 都会随动画
    变（csperrault 有 76 条 alpha 曲线），转换器原来完全不导 —— 部件该淡入淡出
    的地方一直是全不透明。Spine 3.8 原生支持 slot 颜色关键帧（写出器/读回器都已
    实现），这里按"静态颜色 + 曲线分量"生成，关键帧取各分量关键时刻的并集。

    只处理 classID 212（SpriteRenderer 自身颜色）与 137（SMR 的材质色）；
    `material._AdditionalAlpha` 是自定义 shader 属性、语义依赖 shader，
    不做（由 info.unsupportedChannels 报告）。

    `bake_dark=True` 用于**乘法件**（默认口径把乘法烘进图集，见 `MULTIPLY_BLEND`）：
    此时槽位颜色只能是"黑 + alpha"（乘法因子已经写死在贴图 texel 里，rgb 再怎么
    变都是 0），所以 rgb 强制 0、只让 alpha 曲线继续淡入淡出。

    `fade_rgb_alpha=a0` 用于**加色件**：Unity 的加色是 `out = dst + src.rgb·src.a`
    （`src.a` 里含渲染器色 alpha），但**很多运行时不把颜色 alpha 乘进 rgb**
    （v4 查看器就是：`shader_type=1` 不是 PMA）⇒ 那里的 alpha 动画不生效。
    所以把 `a(t)/a0` 折到 **rgb** 上、alpha 固定 1（PMA / 非 PMA 两种运行时都对）。
    """
    cols = (clip or {}).get("color") or {}
    keys = _curve_lookup(cols, anim_path, prefix)
    if not keys:
        return None
    cls = ((clip or {}).get("color_cls") or {}).get(anim_path)
    if cls not in (212, 137):
        return None
    base = list(_hex_rgba(base_hex))
    times = sorted({0.0} | {float(t) for comp in keys.values()
                            for t, _v in comp})
    pts = []
    for t in times:
        rgba = list(base)
        for i, comp in enumerate(("r", "g", "b", "a")):
            ks = keys.get(comp)
            if ks:
                rgba[i] = max(0.0, min(1.0, _lerp_keys(ks, t, rgba[i])))
        if bake_dark:
            rgba[0] = rgba[1] = rgba[2] = 0.0
        pts.append((t, rgba))
    if fade_rgb_alpha is not None:
        den = float(fade_rgb_alpha)
        if den <= 1e-3:
            den = max([p[1][3] for p in pts] + [1.0])
        pts = [(t, [min(1.0, rgba[0] * (rgba[3] / den)),
                    min(1.0, rgba[1] * (rgba[3] / den)),
                    min(1.0, rgba[2] * (rgba[3] / den)), 1.0])
               for t, rgba in pts]
    # 去重口径：**只能丢"与前后线性插值共线"的点**。
    #
    # 旧实现是"值等于上一个有效值就丢"，它会吃掉 Unity 的**保持段**：
    # 例如 bloodypanther 的 `parts_Thigh_L_Weter_01` 在 breast 里是
    # `(0,1) (0.117,0) (16.42,0) (16.75,0) (17,1)` —— 中间三个 0 只留第一个，
    # 于是 0.117→17 变成一条**慢慢浮上来**的斜坡：该部件本该整段不可见，
    # 却一直以半透明"水痕"叠在角色上（16 个点名角色里 179 条颜色曲线有 129 条
    # 命中这一类，最大偏差 0.98）。共线判掉就只剩真正冗余的点。
    keep = []
    for i, (t, rgba) in enumerate(pts):
        if not keep or i == len(pts) - 1:
            keep.append((t, rgba))
            continue
        t0, p0 = keep[-1]
        t2, p2 = pts[i + 1]
        if t2 - t0 <= 1e-9:
            continue
        f = (t - t0) / (t2 - t0)
        dev = max(abs(rgba[k] - (p0[k] + (p2[k] - p0[k]) * f))
                  for k in range(4))
        if dev > 0.5 / 255.0:          # 量化到 8 位后本来就看不出差
            keep.append((t, rgba))
    out = [{"time": fnum(t),
            "color": "%02x%02x%02x%02x" % tuple(int(round(x * 255))
                                                for x in rgba)}
           for t, rgba in keep]
    return out if len(out) > 1 else None


def _hex_rgba(s):
    """'rrggbbaa' -> (r,g,b,a) 0~1；非法值退化为不透明白。"""
    s = (s or "ffffffff").lstrip("#")
    if len(s) == 6:
        s += "ff"
    if len(s) != 8:
        s = "ffffffff"
    try:
        return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4, 6))
    except ValueError:
        return (1.0, 1.0, 1.0, 1.0)


def _rest_value(rest, path, kind, sampler, t):
    """base clip 没动画这个属性时，取 rest（prefab 姿态）值。"""
    p = (rest or {}).get(path) or {}
    if kind == "pos":
        return {"x": p.get("px", 0.0), "y": p.get("py", 0.0), "z": p.get("pz", 0.0)}
    if kind == "scale":
        return {"x": p.get("sx", 1.0), "y": p.get("sy", 1.0), "z": p.get("sz", 1.0)}
    if kind == "euler":
        # prefab 里旋转是**四元数**（没有 rx/ry/rz）时，必须转成 Unity 的欧拉，
        # 否则加性层会拿 0 当基准（实测 bheur 的 drone 尾骨就栽在这里：
        # 真值 = rest(248.43°) + 曲线增量(4.52°)，我们当初算成 4.52°）。
        if p.get("qx") is not None and (p.get("rx") is None
                                        and p.get("ry") is None
                                        and p.get("rz") is None):
            e = quat_to_euler((p.get("qx", 0.0), p.get("qy", 0.0),
                               p.get("qz", 0.0), p.get("qw", 1.0)))
            return {"x": e[0], "y": e[1], "z": e[2]}
        return {"x": p.get("rx", 0.0), "y": p.get("ry", 0.0), "z": p.get("rz", 0.0)}
    return 0.0


def unity_int_round(v):
    """Unity 把 float 曲线写进 int 属性时的取整（`SetBoundCurveFloatValue` case 10）。

        v = v + 0.5;  if (v < 0) v -= 0.99999994;  *(int*)ptr = (int)v;

    —— 即"四舍五入 + 负数向零截断"，和 Python 的 `round()`（银行家舍入）不同。
    """
    x = v + 0.5
    if x < 0.0:
        x -= 0.99999994
    return int(x)          # C 的 (int) 是向零截断，Python int() 语义一致


def sorting_change_times(keys, tans, sub=16):
    """`m_SortingOrder` 的**生效值**（取整后）变化时刻。

    曲线是插值的、属性是 int，所以"值变整数"发生在斜坡中段，不在关键帧上。
    """
    if not keys or len(keys) < 2:
        return []
    if not tans or len(tans) != len(keys):
        tans = [(0.0, 0.0)] * len(keys)
    out = []
    for i in range(len(keys) - 1):
        t0 = keys[i][0]
        t1 = keys[i + 1][0]
        if t1 <= t0:
            continue
        ts = [t0 + (t1 - t0) * k / float(sub) for k in range(sub + 1)]
        prev_t = ts[0]
        prev_v = unity_int_round(unity_curve_eval(keys, tans, prev_t))
        for ct in ts[1:]:
            cur_v = unity_int_round(unity_curve_eval(keys, tans, ct))
            if cur_v != prev_v:
                lo, hi = prev_t, ct
                for _ in range(40):
                    mid = (lo + hi) * 0.5
                    if unity_int_round(unity_curve_eval(keys, tans, mid)) == prev_v:
                        lo = mid
                    else:
                        hi = mid
                out.append(math.ceil(hi * 1e6) / 1e6)
            prev_t, prev_v = ct, cur_v
    return out


def probe_times_for(entry, dt=0.05):
    """某条动画的"探测时刻"（近似转换器内层的 probe_times）。

    均匀采样网格 + 各类关键帧时刻（变换/显隐/形变/换图/排序），
    用于"相对层级"的统计与 drawable 分配。
    """
    cl = entry.get("clip") or {}
    dur = float(entry.get("duration") or cl.get("duration") or 0.0)
    ts = set()
    if dur > 0:
        for i in range(int(math.floor(dur / dt + 1e-6)) + 1):
            ts.add(round(i * dt, 6))
    for key in ("active", "enabled", "sorting"):
        for keys in (cl.get(key) or {}).values():
            for kt, _v in keys:
                ts.add(round(kt, 6))
    for d in (cl.get("morph") or {}).values():
        for keys in d.values():
            for kt, _v in keys:
                ts.add(round(kt, 6))
    for d in (cl.get("pptr") or {}).values():
        for keys in d.values():
            for k in keys:
                ts.add(round(k[0], 6))
    for cu in (cl.get("curves") or []):
        for kt, _v in (getattr(cu, "keys", None) or []):
            ts.add(round(kt, 6))
    return sorted(t for t in ts if -1e-9 <= t <= dur + 1e-6)


def sorting_value_of(mdl, entry, part, t):
    """部件在该动画 t 时刻的**排序值**（int；没有曲线就用 prefab 静态值）。

    与 Unity 一致：曲线求值后按 `unity_int_round` 取整
    （`SetBoundCurveFloatValue` case 10）。
    """
    v = int(getattr(part, "sorting_order", 0) or 0)
    cl = entry.get("clip") or {}
    srt = cl.get("sorting") or {}
    if not srt:
        return v
    td = mdl.transforms.get(getattr(part, "tfid", None)) or {}
    ap = td.get("anim_path") or ""
    pfx = cl.get("_prefix") or ""
    keys = _curve_lookup(srt, ap, pfx)
    if not keys:
        return v
    tans = _curve_lookup(cl.get("sorting_tan") or {}, ap, pfx)
    if not tans or len(tans) != len(keys):
        tans = [(0.0, 0.0)] * len(keys)
    return unity_int_round(unity_curve_eval(keys, tans, t))


def order_at(mdl, entry, parts, t):
    """该时刻的绘制顺序（返回 parts 的下标列表）。

    排序键 = (排序值, **静态顺序**)；静态顺序就是传进来的 `parts` 顺序
    （转换器里是 `kept`，已按 `(sortingOrder, 层级 DFS 序)` 排好，
    见 `hierarchy_ranks()`）。
    """
    vals = [(sorting_value_of(mdl, entry, p, t), i) for i, p in enumerate(parts)]
    return [i for _v, i in sorted(vals)]


LAYER_SEP = "#"          # 多 drawable 的槽位名后缀分隔符：`<原名>#<相对层级>`

#: "还没写过关键帧"的哨兵（用 None 当哨兵会把连续 None 重复写出去）
_UNSET = object()


def base_slot_name(nm):
    """去掉多 drawable 后缀，拿回部件原名（校验/校准工具用）。"""
    return (nm or "").split(LAYER_SEP, 1)[0]


def relative_layers(mdl, entries, kept, aabb_of, sample_times=9,
                    times_of=None):
    """算**相对层级**并决定每个部件需要几个 drawable。

    为什么要"相对"：Unity 里透明渲染的排序键是
    `(sortingLayer, m_SortingOrder, 到相机的距离)`；两个部件的先后只对
    **在画面上重叠**的部件有意义。所以这里：

      1. 用每个部件在若干采样时刻的世界包围盒求"空间重叠"关系；
      2. 时刻 t 的**相对层级** = 它的重叠邻居里排在自己前面的个数；
      3. 一个部件在不同时刻取到多少个不同层级 ⇒ 就给它几个 drawable；
      4. 槽位顺序 = 按 `(相对层级, 静态下标)` 排 —— 这样任意时刻
         "谁挡谁"都与运行时一致，**不需要 drawOrder 切换**。

    `aabb_of(entry_name, t, part_index)` 返回该部件在该时刻的世界 AABB
    （`(minx,miny,maxx,maxy)`）或 None。
    """
    tl = times_of or (lambda e: probe_times_for(e))
    n = len(kept)
    # `kept` 在转换器里是 `[{"part": Part, ...}, …]`；`order_at()` 要的是
    # **Part 对象**列表（它按 `sorting_order` 属性排序）。这里统一取一层，
    # 否则 getattr 到 dict 上恒为 0 —— 排序全等、相对层级永远不变（假 0）。
    pl = [e["part"] if isinstance(e, dict) else e for e in kept]
    # 1) 空间范围（各动画采样时刻的并集，留 20% 余量）
    boxes = [None] * n
    for e in entries:
        ts = tl(e)
        if len(ts) > sample_times:
            step = max(1, len(ts) // sample_times)
            ts = ts[::step]
        for t in ts:
            for i in range(n):
                b = aabb_of(e["name"], t, i)
                if not b:
                    continue
                cur = boxes[i]
                if cur is None:
                    boxes[i] = list(b)
                else:
                    cur[0] = min(cur[0], b[0]); cur[1] = min(cur[1], b[1])
                    cur[2] = max(cur[2], b[2]); cur[3] = max(cur[3], b[3])
    for b in boxes:
        if b is None:
            continue
        w = max(1e-6, (b[2] - b[0]) * 0.2)
        h = max(1e-6, (b[3] - b[1]) * 0.2)
        b[0] -= w; b[1] -= h; b[2] += w; b[3] += h

    def overlap(i, j):
        a, b = boxes[i], boxes[j]
        if a is None or b is None:
            return False
        return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

    nbr = {i: [j for j in range(n) if j != i and overlap(i, j)] for i in range(n)}
    # 2) 逐时刻算相对层级
    depths = {i: set() for i in range(n)}
    depth_at = {}
    for e in entries:
        seq = []
        for t in tl(e):
            order = order_at(mdl, e, pl, t)
            pos = {idx: r for r, idx in enumerate(order)}
            row = [0] * n
            for i in range(n):
                row[i] = sum(1 for j in nbr[i]
                             if (pos[j], j) < (pos[i], i))
                depths[i].add(row[i])
            seq.append((t, row))
        depth_at[e["name"]] = seq
    return {i: sorted(v) for i, v in depths.items()}, depth_at


def expand_layers(kept, depths):
    """按"每个部件 × 它需要的相对层级"展开成 drawable 列表。

    `layer_id` = 该 drawable 代表的相对层级；`base_index` = 原始部件下标
    （时间轴用它查"当前该亮哪个层级"）。名字：最低层级沿用原名，
    其余加 `#<层级>` 后缀（校验工具用 `base_slot_name()` 还原）。
    """
    out = []
    for i, e in enumerate(kept):
        ds = depths.get(i) or [0]
        for k, d in enumerate(ds):
            ne = dict(e)
            ne["layer_id"] = int(d)
            ne["base_index"] = i
            ne["_base_entry"] = e
            if k > 0:
                ne["_name_hint"] = "%s%s%d" % (e["part"].name, LAYER_SEP, d)
            out.append(ne)
    out.sort(key=lambda x: (x["layer_id"], x["base_index"]))
    return out


def rank_sets(mdl, entries, parts):
    """每个部件的 **rank 集合**（它在不同动画/时刻处在第几个被画）。

    返回 `(ranks, per_entry)`：

      · `ranks[tfid] = {rank, …}`：集合大小 > 1 说明这个部件"相对层级会变"，
        要按用户要求**分配多个 drawable**（多开槽位），用显隐选择当前层级；
      · `per_entry[动画名] = [(t, [按绘制顺序排列的 parts 下标]), …]`：
        逐时刻顺序，导出时决定"哪一个 drawable 该亮"。
    """
    ranks = {}
    per_entry = {}
    for e in entries:
        cl = e.get("clip") or {}
        ts = set(probe_times_for(e))
        for keys in (cl.get("sorting") or {}).values():
            for kt, _v in keys:
                ts.add(round(kt, 6))
            ts.update(sorting_change_times(keys, None))
        seq = []
        for t in sorted(ts):
            order = order_at(mdl, e, parts, t)
            seq.append((t, order))
            for r, i in enumerate(order):
                ranks.setdefault(parts[i].tfid, set()).add(r)
        per_entry[e["name"]] = seq
    return ranks, per_entry


def draw_order_offsets(target, n):
    """把"目标绘制顺序"编成 Spine 3.8 的 `offsets`（slot 序号 + 非负偏移）。

    Spine 的 drawOrder 关键帧语义（见 `spine-cpp/src/spine/SkeletonJson.cpp`
    与 `SkeletonBinary.cpp`）：

        · 按 setup 序号**升序**遍历 offsets，每条把该槽放到 `setupIndex + offset`；
        · 没列出的槽按 setup 顺序填满剩下的位置；
        · **偏移不能为负**（二进制里是 unsigned varint）。

    所以：把"往后挪"的槽都列出来（偏移 = 目标位置 − setup 序号），其余不列。
    只有"未被列出的槽在目标顺序里保持 setup 升序"时才可行；不可行就返回 None
    （调用方退回上一帧顺序并告警，不会写出非法数据）。

    `target[i]` = 第 i 个被绘制的槽的 setup 序号。

    ★ 2026-10-13 重写（用户报 Eternity 冰淇淋 `parts_Ice_World_s50` 层级不对）：
    原实现只列"往后挪"的槽（`pos ≥ setup`），并要求"往前挪"的那批**恰好**按 setup
    升序 ⇒ 一旦有槽被移到**它自己 setup 序号之前**（冰淇淋 `50 → 32`），后续每一帧
    都编不出来（实测 `3P_Eternity_NS2_SpecialTouch`：254 帧只写出 1 键、**127 帧被跳过**）。
    新实现**按 Unity/Spine 的真实语义做模拟**：

      · 被列出的槽占领位置 `setupIndex + offset`（offset ≥ 0）；
      · **没列出的槽按 setup 升序填进剩下的空位**。

    于是"把某槽往前挪"可以改写成"把挡在它前面的那些槽往后挪一格"，这条以前没被利用。
    做法：先试"不列出 = 所有往前挪的槽"，不成立就再逐个把别的槽也塞进"不列出"集合
    （最多 n 次尝试，n = 槽数，成本可忽略）。返回 None 仍是"这一帧编不出来"，
    调用方跳过该帧（绝不写非法数据）。
    """
    n = int(n)
    if sorted(target) != list(range(n)):
        return None
    pos_of = {s: i for i, s in enumerate(target)}
    target = list(target)

    def _encode(unlisted):
        """按 Spine 语义模拟一次：返回最终顺序（= target 才合法）或 None。"""
        claimed = {}
        for s in range(n):
            if s in unlisted:
                continue
            p = pos_of[s]
            if p < s or p in claimed:      # 负偏移 / 两个槽抢同一个位置
                return None
            claimed[p] = s
        free = [p for p in range(n) if p not in claimed]
        un = sorted(unlisted)
        if len(un) != len(free):
            return None
        res = [None] * n
        for p, s in claimed.items():
            res[p] = s
        for p, s in zip(free, un):
            res[p] = s
        return res

    base = {s for s in target if pos_of[s] < s}          # 往前挪的：只能"不列出"
    cand = sorted(set(range(n)) - base)
    tries = [frozenset()]                     # 最省：只不列出"往前挪"的
    tries += [frozenset((c,)) for c in cand]  # 再逐个把别的槽也塞进"不列出"
    if n <= 40:
        from itertools import combinations
        tries += [frozenset(p) for p in combinations(cand, 2)]
    for extra in tries:
        un = base | set(extra)
        if _encode(un) == target:
            listed = sorted(set(range(n)) - un)
            return [{"slotIndex": s, "offset": pos_of[s] - s} for s in listed]
    return None


def draw_order_timeline(entry, kept, times, mdl, fnum):
    """按 `m_SortingOrder` 曲线生成 Spine 3.8 的 `drawOrder` 关键帧。

    返回 `[{"time": t, "offsets": [{"slot": 槽名, "offset": int}, ...]}, ...]`；
    没有排序曲线、或该帧的顺序无法用"非负偏移"表达时**跳过该帧**
    （跳过 = 运行时沿用上一帧顺序），并返回 [] 表示整条动画不需要 drawOrder。

    对照 Unity：`m_SortingOrder` 是 int 属性，运行时按
    `SetBoundCurveFloatValue` case 10 取整写入（见 `unity_int_round`），
    渲染顺序 = 先按排序值、同值再按**转换器既有的 setup 顺序**（静态排序值，
    已通过图像级校验）。
    """
    clip = entry.get("clip") or {}
    srt = clip.get("sorting") or {}
    if not srt or not kept:
        return [], 0
    srt_tan = clip.get("sorting_tan") or {}
    prefix = clip.get("_prefix") or ""
    names = [e["name"] for e in kept]
    curves = {}
    ts = set(times)
    for e in kept:
        td = mdl.transforms.get(getattr(e["part"], "tfid", None)) or {}
        ap = td.get("anim_path") or ""
        keys = _curve_lookup(srt, ap, prefix)
        if not keys:
            continue
        tans = _curve_lookup(srt_tan, ap, prefix)
        if not tans or len(tans) != len(keys):
            tans = [(0.0, 0.0)] * len(keys)
        curves[e["name"]] = (keys, tans)
        for kt, _v in keys:
            ts.add(round(kt, 6))
        ts.update(sorting_change_times(keys, tans))
    if not curves:
        return [], 0
    dur = float(entry.get("duration") or 0.0)
    out = []
    skipped = 0
    prev = list(range(len(kept)))          # setup 顺序
    for tm in sorted(ts):
        if tm < -1e-9 or (dur and tm > dur + 1e-6):
            continue
        vals = []
        for i, e in enumerate(kept):
            v = int(getattr(e["part"], "sorting_order", 0) or 0)
            c = curves.get(e["name"])
            if c is not None:
                v = unity_int_round(unity_curve_eval(c[0], c[1], tm))
            vals.append((v, i))
        order = [i for _v, i in sorted(vals)]
        if order == prev:
            continue
        offs = draw_order_offsets(order, len(kept))
        if offs is None:
            skipped += 1
            continue
        out.append({"time": fnum(tm),
                    "offsets": [{"slot": names[o["slotIndex"]],
                                 "offset": int(o["offset"])} for o in offs]})
        prev = order
    # 逐帧产出、逐帧取舍（2026-09-18 晚改）：Spine 3.8 的 drawOrder 只允许"槽位
    # **往前挪**"（偏移非负 varint），凡是"有槽要往后挪、且这些槽在目标顺序里不是
    # 升序"的帧就没法精确表达。旧实现是"只要有一帧不行就整条不导" ⇒ draculina
    # `Tep_1` 26 条排序曲线、**一帧都没写出来**（实测）。
    # 现在改成：**能表达的帧照写、表达不了的帧跳过**（跳过 = 运行时沿用上一帧顺序），
    # 并把"跳过几帧"报给调用方。这样哪怕只有一部分帧能精确表达，也比整体冻结在
    # 静态顺序更接近 Unity（真值：手指/手在 7~10 s 段整段换层级）。
    return out, skipped


def _curve_lookup(curves, anim_path, prefix=""):
    """按 anim_path 找曲线；副 Animator 的 clip 再按"该 Animator 的相对路径"找一次。

    副 Animator（daphne 的左右翅膀、aeda 的 star_deco 等）的 clip，曲线 path 是
    相对**那个 Animator 自己**的，例如：

        bone_wing_fx (21)/parts_wing_fx1

    而 anim_path 是相对**主 Animator** 的：

        Bone_pelvis/Bone_spine1/Bone_spine2/bone_L_wing/bone_L_wing/bone_wing_fx (21)/parts_wing_fx1

    所以要把 anim_path 去掉 prefix（= 该 Animator 相对主根的路径）再查。

    注意：**不要**用全局后缀扫描兜底。曾经那样做过，结果链上本来不该命中曲线的
    祖先节点也命中了，`node_visible` 的"整条链都 inactive 就当成场景摆放"逃生口
    被误触发，显隐直接反掉（daphne 的 wing_fx 就是这个问题）。
    """
    if not curves or not anim_path:
        return None
    v = curves.get(anim_path)
    if v is not None:
        return v
    if prefix:
        rel = rel_path_in(prefix, anim_path)
        if rel is not None:
            v = curves.get(rel)
            if v is not None:
                return v
    return None


def _active_value(clip, anim_path, prefix, t):
    """在 t 时刻求该节点的 m_IsActive 曲线值（带切线时按 Unity 求值）。

    返回 None 表示这条路径没有曲线（要回落到 prefab 的静态 m_IsActive）。
    """
    keys = _curve_lookup((clip or {}).get("active") or {}, anim_path, prefix)
    if keys is None:
        return None
    tans = None
    if USE_RUNTIME_ACTIVE:
        tans = _curve_lookup((clip or {}).get("active_tan") or {},
                             anim_path, prefix)
        if tans is None or len(tans) != len(keys):
            tans = None          # 没有切线信息 → 退回老行为
    return _active_at(keys, t, tans)


def _enabled_value(clip, anim_path, prefix, t):
    """同 `_active_value`，查 m_Enabled 曲线。"""
    keys = _curve_lookup((clip or {}).get("enabled") or {}, anim_path, prefix)
    if keys is None:
        return None
    tans = None
    if USE_RUNTIME_ACTIVE:
        tans = _curve_lookup((clip or {}).get("enabled_tan") or {},
                             anim_path, prefix)
        if tans is None or len(tans) != len(keys):
            tans = None
    return _active_at(keys, t, tans)


#: ★ 2026-10-13：`U2S_FORCE_INACTIVE="<动画名子串>:<部件名前缀>[;…]"`
#: 用于"状态机不可达 / 只能靠脚本 `Play(state, layer)` 切 / Unity 里从未切进去"的状态
#: （典型：Ignis `Bresat_Layer` 的 `Chain_*_NoChain`）：那些 clip 里的
#: `m_IsActive = 1` 从未生效 ⇒ 产物按**预制体默认（关）**处理，否则会多出
#: "一块不动、悬在画面上"的部件（用户 2026-10-12 报的 BP_028 就是它）。
_FORCE_INACTIVE_CACHE = None
_FORCE_INACTIVE_HIT = set()


def _forced_off_names(clip):
    """本 clip 里要被强制当"预制体默认(关)"的部件名前缀集合。"""
    global _FORCE_INACTIVE_CACHE
    if _FORCE_INACTIVE_CACHE is None:
        _FORCE_INACTIVE_CACHE = []
        for ent in (os.environ.get("U2S_FORCE_INACTIVE") or "").split(";"):
            if ":" in ent:
                a, b = ent.split(":", 1)
                _FORCE_INACTIVE_CACHE.append((a.strip(), b.strip()))
    anm = "%s|%s" % ((clip or {}).get("name") or "",
                     (clip or {}).get("_prefix") or "")
    out = set()
    for a, b in _FORCE_INACTIVE_CACHE:
        # `*`（或空）= 所有动画都生效：用于"预制体默认关、且 clip 曲线在运行时
        # **根本没绑上**"的部件（Ignis `parts_BP_028_*`：它们在 Animator 绑定子树
        # 之外 —— 预制体路径是双根 `…/2DModel_PECS_Ignis_NS1/parts_BP_028_1_Skinned`，
        # 而 clip 里写的是单根 `parts_BP_028_1_Skinned` ⇒ 曲线在运行时是死的，
        # 编辑模式实测：把 Bresat_Layer 切到 `Chain_Breast_NoChain` / `Fall_Down`
        # 后这 5 件仍然 activeSelf=0/activeInHierarchy=0，而 AnimationMode 采样却把它们
        # 置 1 —— 说明是"绑定不上"，不是"该显示"）。
        if b and (a == "*" or (a and a.lower() in anm.lower())):
            out.add(b)
    if out and (anm, tuple(sorted(out))) not in _FORCE_INACTIVE_HIT:
        _FORCE_INACTIVE_HIT.add((anm, tuple(sorted(out))))
        print("[anim] U2S_FORCE_INACTIVE 命中 %s ⇒ 强制按预制体默认(关)：%s"
              % (anm, "，".join(sorted(out))))
    return out


def _node_short(td):
    """节点的短名（路径末段）。"""
    return (td.get("path") or "").replace("\\", "/").split("/")[-1]


def node_visible(mdl, clip, t, tfid):
    """节点（含祖先链）在 clip 的 t 时刻是否 activeInHierarchy。

    Unity 用 SetActive 切换表情部件（同一时刻只启用一组眼/眉/嘴），
    曲线在 AnimationClip 的 m_FloatCurves 里（attribute: m_IsActive）。
    没有曲线的节点回落到 prefab 自己的 m_IsActive。
    """
    _fi = _forced_off_names(clip)
    # 沿父链收集节点（叶 -> 根），再反过来从根往下判断。
    chain = []
    cur, hops = tfid, 0
    while cur is not None and hops < 500:
        td = mdl.transforms.get(cur)
        if td is None:
            break
        chain.append(td)
        cur = td.get("father")
        hops += 1
    _pfx = (clip or {}).get("_prefix") or ""
    # 从根开始的连续 inactive 视为"场景摆放状态"（多个角色一起放进场景时
    # 整条被 disable），不算角色内部的隐藏；只有"祖先可见、自己却关上"
    # 才是真正的部件开关（如 blacklilith 的表情备选件）。
    seen_active = False
    dead = dead_active_paths(mdl)
    for td in reversed(chain):
        if (td.get("anim_path") or "") in dead:
            continue      # 实测：这条 m_IsActive 运行时没绑上，不参与判定
        # ★ 2026-10-13：`scale ≈ 0` = Unity 的"把这一套缩到看不见"惯用法（#6 Cerberus_NS2
        #   的 Idle/Tep 两套腿互换）⇒ 该段不画（attachment 时间轴上给 null）。
        if _scale_collapsed(clip, td, t):
            return False
        v = _active_value(clip, td.get("anim_path") or "", _pfx, t)
        if _fi and any(_node_short(td).startswith(_p) for _p in _fi):
            # ★ 2026-10-13 `U2S_FORCE_INACTIVE`：状态机不可达、只能靠脚本 `Play` 切、
            #   而 Unity 里从未被切进去的状态（Ignis 的 `Chain_*_NoChain`），其 clip 的
            #   `m_IsActive=1` 从未生效 ⇒ 按**预制体默认（关）**处理，避免产物里多出
            #   "一块不动、悬在画面上"的部件。
            v = 0.0
        if v is not None:
            # Unity 判据是 |v| > 1e-3（不是 v >= 0.5）：插值曲线一离开 0 就显示
            vis = active_is_on(v) if USE_RUNTIME_ACTIVE else (v >= 0.5)
        else:
            vis = bool(mdl.gameobjects.get(td.get("go"), {})
                       .get("active", True))
        if vis:
            seen_active = True
        elif seen_active:
            return False
    return True


def part_visible(mdl, clip, t, tfid):
    """部件在 clip 的 t 时刻是否可见。

    两层：
      · GameObject.SetActive（m_IsActive）—— 影响整棵子树，沿父链检查；
      · Renderer.enabled（m_Enabled）—— 只影响该节点自身的渲染器。
    """
    if not node_visible(mdl, clip, t, tfid):
        return False
    td = mdl.transforms.get(tfid) or {}
    v = _enabled_value(clip, td.get("anim_path") or "",
                       (clip or {}).get("_prefix") or "", t)
    if v is not None:
        # Renderer.m_Enabled 走的是同一个 ±1e-3 判据（SetBoundCurveFloatValue case 6）
        if USE_RUNTIME_ACTIVE and not active_is_on(v):
            return False
        if not USE_RUNTIME_ACTIVE and v < 0.5:
            return False
        return True
    # 没有 m_Enabled 曲线时，必须回落到 prefab 里的**静态 m_Enabled**。
    # Unity 的 2D Animation 会把骨骼/IK/样条控制点做成 `m_Enabled=0` 的
    # SpriteRenderer（只在 Scene 视图当 gizmo 显示），不回落的后果是
    # viewer 里出现“圆环 / 针 / 关节标记”（tq.txt 第 1 类问题）。
    return _renderer_enabled(mdl, tfid)


def _renderer_enabled(mdl, tfid):
    """该节点渲染器自身的静态 m_Enabled（同 GO 多个渲染器取“或”）。"""
    cache = getattr(mdl, "_renderer_enabled_cache", None)
    if cache is None:
        cache = {}
        for r in (mdl.renderers or []):
            t = r.get("tfid")
            if t is None:
                continue
            cache[t] = cache.get(t, False) or bool(r.get("enabled", True))
        mdl._renderer_enabled_cache = cache
    return cache.get(tfid, True)


# Unity 编辑器助手贴图（骨骼 / IK / 样条控制点 / 编辑器图标）。
# 正常工程里它们是 m_Enabled=0 的 SpriteRenderer，只在 Scene 视图显示；
# 万一某个工程把它们设成启用，也要靠这张表兜住（tq.txt 第 1 类的“屏蔽选项”）。
DEFAULT_SKIP_TEXTURES = (
    "BoneJoint", "BoneNoJoint", "BoneScaled",
    "IKControl", "splineControl", "splineMiddleControl",
    "icon-bone", "icon-boneNib", "icon-poseBones", "icon-constraintIK",
)


def skip_texture_patterns(extra=None):
    """默认屏蔽表 + 用户追加（`--skip-texture` / `--skip-texture-file`）。"""
    pats = {n.lower() for n in DEFAULT_SKIP_TEXTURES}
    for e in (extra or []):
        for n in str(e).split(","):
            n = n.strip().lower()
            if n:
                pats.add(n)
    return pats


def texture_skipped(texture_path, patterns):
    """命中屏蔽表则返回命中的模式，否则 None。按贴图文件名（不含扩展名）匹配。"""
    if not texture_path or not patterns:
        return None
    base = os.path.splitext(os.path.basename(texture_path))[0].lower()
    for pat in patterns:
        if pat == base or (len(pat) >= 4 and pat in base):
            return pat
    return None


def rest_by_anim_path(mdl):
    rest = {}
    for td in mdl.transforms.values():
        q = td["quat"]
        rest[td.get("anim_path", td["path"])] = {
            "px": td["pos"][0], "py": td["pos"][1], "pz": td["pos"][2],
            "qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3],
            "sx": td["scale"][0], "sy": td["scale"][1], "sz": td["scale"][2]}
    return rest


def rest_by_animator(mdl):
    """{Animator 所在物体: {相对该物体的路径: rest TRS}}。

    曲线 path 是相对各自 Animator 宿主的，rest 也必须按同一口径建表；
    否则副 Animator 的宿主节点（相对路径为空串 ""）会误取主控制器的 rest，
    典型症状是球体光晕被压成一条线。
    """
    out = {}
    for ani in (getattr(mdl, "char_animators", None) or []):
        go = ani.get("go")
        if go is None:
            continue
        host_path = ""
        for td in mdl.transforms.values():
            if td.get("go") == go:
                host_path = td.get("path", "")
                break
        if not host_path:
            continue
        table = {}
        for td in mdl.transforms.values():
            # 相对路径 = 节点全路径去掉宿主全路径的前缀。
            # 不能用 path.rfind(宿主名)：节点重名时会串台（carolina 有四个
            # 都叫 GameObject 的节点，会把宿主自己的 rest 缩放盖掉）。
            full = td.get("path", "")
            if full == host_path:
                rel = ""
            elif full.startswith(host_path + "/"):
                rel = full[len(host_path) + 1:]
            else:
                continue                       # 不在该 Animator 的子树里
            q = td["quat"]
            table[rel] = {
                "px": td["pos"][0], "py": td["pos"][1], "pz": td["pos"][2],
                "qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3],
                "sx": td["scale"][0], "sy": td["scale"][1],
                "sz": td["scale"][2]}
        out[go] = table
    return out


def make_samplers(mdl, entries):
    """按 (Animator, state) 建采样器，rest 表按各自宿主建。"""
    rests = rest_by_animator(mdl)
    out = {}
    for e in entries:
        table = rests.get(e["go"]) or rest_by_anim_path(mdl)
        out[(e["go"], e["state"])] = AnimSampler(e["clip"], rest=table)
    return out


def _sample_world(mdl, sampler, t):
    local_values = {}
    for tfid, td in mdl.transforms.items():
        sp = sampler.sample(td.get("anim_path", td["path"]), t)
        q = sp["quat"]
        if q is None:
            q = euler_to_quat(sp["euler"])
        local_values[tfid] = trs_mat(sp["pos"], q, sp["scale"])
    return _world_matrices(mdl, local_values)


def build_anim_assignments(mdl, assets, clip_hint=None, secondary=True):
    """给每个 Transform 指定"由哪个 Animator 的哪个 clip 驱动"。

    一个角色可能有多个 Animator（aeda 的 `aeda_ball_glow` + `star_deco` 就是
    专门驱动球体光晕的第二套动画）。曲线 path 是相对各自 Animator 所在物体的，
    所以必须逐 Animator 建采样器，再按"最近的 Animator 祖先"分配给节点。

    返回 (assignments, clips)：
      assignments[tfid] = {"sampler": AnimSampler, "duration": float,
                           "clip": 名称, "root": animator_go}
      clips = [(animator_go, clip_name, clip, 是否主控制器)]
    """
    char_anims = getattr(mdl, "char_animators", None)
    if not char_anims:
        # 没记录过本角色 Animator 列表时，退回"只主控制器"
        char_anims = [a for a in (mdl.animators or [])
                      if a.get("controllerGuid") == mdl.animator_controller_guid]
    rest = rest_by_anim_path(mdl)
    infos = []          # (go, clip_name, clip, is_main)
    seen = set()        # (controller, Animator 所在物体)：同一个 Controller 挂在两个
                        # Animator 上时是两个不同的采样器（曲线 path 各相对自己的宿主）
    for ani in char_anims:
        ctrl = ani.get("controllerGuid")
        go = ani.get("go")
        if not ctrl or (ctrl, go) in seen:
            continue
        is_main = (ctrl == mdl.animator_controller_guid)
        if not is_main and not secondary:
            continue
        cp = _asset_path(assets, ctrl)
        if not cp or not os.path.isfile(cp):
            continue
        cands = []
        for st in parse_animator_controller(cp):
            cl_path = _asset_path(assets, st.get("clipGuid") or "")
            if cl_path and os.path.isfile(cl_path):
                cands.append((st["name"],
                              resolve_clip_paths(mdl, go, parse_clip(cl_path))))
        if not cands:
            continue
        if is_main:
            name, clip = _choose_clip(mdl, assets, clip_hint)
            if clip is None:
                name, clip = cands[0]
        else:
            name, clip = next(
                (c for c in cands if "start" not in c[0].lower()), cands[0])
        seen.add((ctrl, go))
        infos.append((go, name, clip, is_main))

    # Animator 所在物体 -> 采样器（曲线 path 与 rest 都相对该物体）
    rests = rest_by_animator(mdl)
    samplers = {}
    for go, name, clip, _main in infos:
        samplers[go] = AnimSampler(clip, rest=rests.get(go) or rest)

    def owner_animator(tfid):
        """向上找到最近的（本角色内）Animator 所在物体。"""
        cur = tfid
        hops = 0
        while cur is not None and hops < 200:
            td = mdl.transforms.get(cur)
            if td is None:
                return None
            if td.get("go") in samplers:
                return td["go"]
            cur = td.get("father")
            hops += 1
        return None

    path_by_go = {t["go"]: t.get("path", "") for t in mdl.transforms.values()}
    assignments = {}
    for tfid in mdl.transforms:
        go = owner_animator(tfid)
        if go is None:
            # 不在任何 Animator 子树内：用主控制器（保持旧行为）
            main = next((i for i in infos if i[3]), None)
            if main is None:
                continue
            go = main[0]
        info = next((i for i in infos if i[0] == go), None)
        if info is None:
            continue
        # 曲线 path 是相对"该 Animator 所在物体"的：这里按宿主重算，
        # 否则副动画（如 star_deco）的位移曲线永远匹配不上。
        full = mdl.transforms[tfid].get("path", "")
        rel = rel_path_in(path_by_go.get(go, ""), full)
        if rel is None:
            rel = full
        assignments[tfid] = {"sampler": samplers[go],
                             "duration": float(info[2].get("duration") or 0.0),
                             "clip": info[1], "root": go, "anim_path": rel}
    return assignments, [(i[0], i[1], i[2], i[3]) for i in infos]


def _sample_world_multi(mdl, assignments, t, loop=True):
    """按各自的 Animator clip 采样（副动画按自身时长循环）。"""
    local_values = {}
    for tfid, td in mdl.transforms.items():
        a = assignments.get(tfid)
        if a is None:
            q = td["quat"]
            local_values[tfid] = trs_mat(td["pos"], q, td["scale"])
            continue
        dur = a["duration"]
        tt = t + float(a.get("time_offset", 0.0) or 0.0)
        if dur > 1e-6:
            if a.get("loop", loop):
                tt = t % dur
            else:
                tt = min(t, dur)
        sp = a["sampler"].sample(a.get("anim_path", td["anim_path"]), tt)
        q = sp["quat"]
        if q is None:
            q = euler_to_quat(sp["euler"])
        local_values[tfid] = trs_mat(sp["pos"], q, sp["scale"])
    return _world_matrices(mdl, local_values)


def _subtree_size(path_by_go, go):
    """该 Animator 宿主子树里有多少个节点（用来判断哪个宿主是"主 rig"）。"""
    p = path_by_go.get(go) or ""
    if not p:
        return 0
    pre = p + "/"
    return sum(1 for q in path_by_go.values() if q.startswith(pre))


def enumerate_clips(mdl, assets):
    """列出本角色子树里**所有 Animator 的所有 state/clip**。

    返回 [{go, animator, state, clip, duration, is_main, path}, ...]
    （同名 state 会加 Animator 前缀，保证最终动画名唯一）。
    """
    out = []
    seen = set()
    path_by_go_e = {t["go"]: t.get("path", "")
                    for t in mdl.transforms.values()}
    for ani in (getattr(mdl, "char_animators", None) or []):
        ctrl = ani.get("controllerGuid")
        cp = _asset_path(assets, ctrl)
        if not cp or not os.path.isfile(cp):
            continue
        go = ani.get("go")
        aname = mdl.gameobjects.get(go, {}).get("name", "")
        is_main = (ctrl == mdl.animator_controller_guid)
        for st in parse_animator_controller(cp):
            if (go, st["name"]) in seen:
                continue
            cl = _asset_path(assets, st.get("clipGuid") or "")
            if not cl or not os.path.isfile(cl):
                continue
            seen.add((go, st["name"]))
            clip = resolve_clip_paths(mdl, go, parse_clip(cl))
            # 副 Animator 的 clip 曲线 path 是相对它自己的；记下"该 Animator 相对
            # 主根的路径"，part_visible/node_visible 查表时用它换算。
            _pfx = rel_path_in(mdl.anim_root_path,
                               path_by_go_e.get(go, "")) or ""
            if clip.get("_prefix_set"):
                clip = dict(clip)          # 同一个 clip 被多个 Animator 引用时别互相覆盖
            clip["_prefix"] = _pfx
            clip["_prefix_set"] = True
            out.append({"go": go, "animator": aname, "state": st["name"],
                        "clip": clip,
                        "duration": float(clip.get("duration") or 0.0),
                        "is_main": is_main, "path": cl,
                        # 同一个 controller 可能挂在多个 Animator 上
                        # （babariana：`..._Bg_Only` 与主 rig 共用一个 controller）。
                        # Unity 里它们是两个各自播放的状态机，但对"用户看到的动作"
                        # 来说就是一个 state —— 按宿主各导一份会让每个动作出现两份、
                        # 且每份只驱动一部分部件（用户报的"所有动作几乎一模一样"）。
                        # 下面按 (controller, state) 去重，只留部件树的那个宿主；
                        # 另一个宿主由 `assignments_for_entry` 按"播自己的默认 state"
                        # 驱动，行为与 Unity 一致。
                        "ctrl": ctrl,
                        "desc": _subtree_size(path_by_go_e, go)})
    # 动画名去重（同名用 Animator 名做前缀）
    best = {}
    for e in out:
        k = (e["ctrl"], e["state"])
        if k not in best or e["desc"] > best[k]["desc"]:
            best[k] = e
    # 记下"被去重掉的 Animator 该跟随哪个宿主"。
    # 为什么必须记：`assignments_for_entry` 原来对"没有 entries 的 Animator"
    # （= 被去重掉的那个）会 `default_entry(...) -> None`，于是**整棵子树分不到
    # 任何曲线、停在 prefab 姿态** —— 这正是 `beasthunter_skin1` 用户报的
    # "还是动不了、动画无响应"：角色子树 `size_root/BR_BeastHunter_NS1/…`
    # 一根骨都没绑上，而真值（`PoseFrames.transforms`）里两份子树都在动。
    if getattr(mdl, "dedupe_host", None) is None:
        mdl.dedupe_host = {}
    for e in out:
        kept = best.get((e["ctrl"], e["state"]))
        if kept is not None and kept is not e:
            mdl.dedupe_host.setdefault(e["go"], kept["go"])
    out = [e for e in out if best[(e["ctrl"], e["state"])] is e]
    names = {}
    for e in out:
        n = e["state"]
        if n in names:
            n = "%s_%s" % (e["animator"], e["state"])
        names[e["state"]] = n
        e["name"] = n
    dup = {}
    for e in out:
        k = e["name"]
        if k in dup:
            e["name"] = "%s_%d" % (k, dup[k] + 1)
        dup[k] = dup.get(k, 0) + 1
    return out


def default_entry(entries, go):
    """某个 Animator 的"默认播放"state：优先非 *_start，其次 lobby。"""
    cands = [e for e in entries if e["go"] == go]
    if not cands:
        return None
    for c in cands:
        low = c["state"].lower()
        if "lobby" in low and "start" not in low and "tep" not in low:
            return c
    for c in cands:
        if "start" not in c["state"].lower():
            return c
    return cands[0]


_COLLAPSE_EPS = 0.001


def _scale_map_of(clip):
    """`clip['curves']` 里的 scale 曲线 → {path: cu}（按 clip 缓存一次）。"""
    m = (clip or {}).get("_scale_map")
    if m is None:
        m = {}
        for cu in (clip or {}).get("curves") or []:
            if getattr(cu, "kind", "") == "scale":
                m[cu.path] = cu
        try:
            clip["_scale_map"] = m
        except Exception:                                        # noqa: BLE001
            pass
    return m


def _scale_collapsed(clip, td, t):
    """该节点在 t 时刻是否被"缩到看不见"（Unity 惯用法 `scale = 0.0001`）。

    ★ 2026-10-13（#6 Cerberus_NS2 `Tep_1` 腿闪）：`Bone_R_Thigh/Calf_Idle` 与 `_Tep`
    两套腿在 0.5s / 3.1s 互换（scale `1 ↔ 0.0001`）。Unity 里被缩小的那套**根本不画**
    （连皮肤都不再更新，录制器只能抓到冻结的旧顶点），而我们把"塌缩姿态"照原样烘成了
    顶点形变 ⇒ 3.1s 复位那一下变成"从一个点弹回"，抖出 320px 的假跳变。
    这里把"有效缩放 ≤ 0.001"当作**不可见**：走 `node_visible` 的隐藏分支 ⇒ 该段该 slot
    不带 attachment（不画），与 Unity 的显示结果一致。
    """
    cu = _scale_map_of(clip).get(td.get("anim_path") or "")
    if cu is None:
        return False
    pts = []
    for kt, kv in cu.keys:
        try:
            v = ((float(kv["x"]), float(kv["y"]), float(kv["z"]))
                 if isinstance(kv, dict) else tuple(float(x) for x in kv))
        except Exception:                                        # noqa: BLE001
            continue
        if pts and abs(pts[-1][0] - kt) < 1e-9:
            pts[-1] = (kt, v)          # 同刻重复键：后一个值生效（阶跃）
        else:
            pts.append((kt, v))
    if not pts:
        return False
    v = pts[0][1]
    for i, (kt, kv) in enumerate(pts):
        if kt <= t + 1e-9:
            v = kv
            continue
        pt, pv = pts[i - 1]
        u = 0.0 if kt <= pt else (t - pt) / (kt - pt)
        v = tuple(pv[k] + (kv[k] - pv[k]) * u for k in range(3))
        break
    return min(abs(x) for x in v) <= _COLLAPSE_EPS


def _key_vals_differ(a, b):
    """同一时刻的两个重复键，**值是不是真换了**。

    只有"同一时刻两个键、值不同"才是 Unity 的**瞬时切换**惯用法（audrey 眨眼把
    `Bone_Eye_*` 的 scale 在 1↔0.0001 之间瞬切、Echidna 灯光 0.0001↔1380 的方波）。
    值相同只是"再打一次点/打标记"，Unity 不产生任何跳变。

    ★ 2026-10-13（#6 Cerberus_NS2 `Tep_1` 腿闪）：原来不分青红皂白地给重复键补
    `kt − 1e-3` 保持帧 + `kt + 1e-3` 新值帧，结果那对 1ms 键把**正常运动的一个 1/60s**
    变成了"瞬时跳" —— 实测 `Bone_R_Thigh_Idle` / `Bone_R_Calf_Idle` 等在 t=3.1s 有
    "同刻重复键但值相同"，于是产物在 3.1s 冒出一记 **320px 的假跳**，而 Unity 真值
    （376 帧、无状态切换）那里根本没有跳（真值次大跳只有 17~100px）。
    """
    try:
        if hasattr(a, "__len__") and hasattr(b, "__len__"):
            return any(abs(float(x) - float(y)) > 1e-6 for x, y in zip(a, b))
        return abs(float(a) - float(b)) > 1e-6
    except Exception:                                            # noqa: BLE001
        return True


def _subtree_curves_in(entries, go, path_by_go, mdl):
    """被去重宿主的这棵子树，能不能在保留宿主的 clip 里查到自己节点的曲线？

    粗判几个常见容器（`active/enabled/sorting/pptr` + `curves` 列表）。查不到 ⇒
    跟随与否效果一样（跟随等于把它硬绑到不相干的曲线上），就别动它。
    """
    host_path = path_by_go.get(go, "")
    rels = set()
    for td in mdl.transforms.values():
        full = td.get("path") or ""
        if not full.startswith(host_path):
            continue
        rel = rel_path_in(host_path, full)
        if rel:
            rels.add(rel)
    if not rels:
        return False
    for e in entries:
        clip = e.get("clip") or {}
        for key in ("active", "enabled", "sorting", "pptr"):
            d = clip.get(key) or {}
            if any(r in d for r in rels):
                return True
        for cu in (clip.get("curves") or []):
            p = getattr(cu, "path", None)
            if p is None and isinstance(cu, dict):
                p = cu.get("path") or cu.get("name")
            if p in rels:
                return True
    return False


def assignments_for_entry(mdl, samplers, entries, driving,
                          deduped_default=False, secondary_phase=0.0):
    """让 `driving` 这个 clip 驱动它自己的 Animator；其它 Animator 播各自默认
    clip（循环），与 Unity 里"多 Animator 同时播放"的情况一致。

    ``deduped_default`` 保留给多骨骼分支：被 ``enumerate_clips`` 去重掉的
    Animator 在 Unity 中仍保留自己的默认状态，只驱动当前 state 的是用户
    指定的那台 Animator。默认 False 保持主转换器的既有行为。
    """
    anim_go = {e["go"] for e in entries}
    all_anim_go = {a.get("go") for a in
                   (getattr(mdl, "char_animators", None) or [])} or set(anim_go)
    follow = getattr(mdl, "dedupe_host", None)
    if follow is None:
        follow = {}
        mdl.dedupe_host = follow

    def owner_go(tfid):
        cur, hops = tfid, 0
        while cur is not None and hops < 200:
            td = mdl.transforms.get(cur)
            if td is None:
                return None
            if td.get("go") in all_anim_go:
                return td["go"]
            cur = td.get("father")
            hops += 1
        return None

    path_by_go = {t["go"]: t.get("path", "") for t in mdl.transforms.values()}
    assign = {}
    for tfid, td in mdl.transforms.items():
        go = owner_go(tfid)
        if go is None:
            continue
        # 被去重掉的宿主 → 跟随保留的那个（曲线/状态都用它的）。
        # **判据**：只有当这棵子树的相对路径**在保留 clip 里确实查得到曲线**时才跟随
        # （= 保留 clip 真的在驱这棵子树，跟过去就是把同一份曲线按各自的相对路径绑上）；
        # 查不到曲线的子树，跟随只会被绑到不相干的曲线上，不如保持 prefab 姿态。
        # 2026-09-19 复核（两个多 Animator 角色都成立）：
        #   · `beasthunter_skin1`：被去重的是**主 rig**（`BR_BeastHunter_NS1`，保留的是
        #     部件树更大的 `…_BG_Only`），主 rig 的路径在保留 clip 里查得到 ⇒ 跟随
        #     ⇒ 角色真的动（用户报的"动不了"修好）；
        #   · `babariana_skin1`：被去重的是 `Char_PECS_Babariana_NS1_Bg_Only` 副本，
        #     同样查得到 ⇒ 跟随 ⇒ 与主 rig 同步（**observe 模式真值证实游戏里两份子树
        #     同步在动**：同名部件位移 0.01695 vs 0.01698、姿态差 <1e-4）。
        # ⚠️ 2026-09-18 记的"babariana 2→4 回归"是**假警报**：那是拿 `PoseFrames`
        # 比的，而 `PlayModeSamplerRunner` 每次只驱动一台 Animator、另一台不 Update
        # ⇒ 那份真值里副本必然静止。
        host = follow.get(go, go)
        if host != go and not _subtree_curves_in(entries, go, path_by_go, mdl):
            host = go      # 子树在保留 clip 里没有曲线 ⇒ 不跟随（保持 prefab 姿态）
        if deduped_default and go != driving["go"]:
            # The secondary Animator in Unity is not switched by
            # Animator.Play on the driving root; it keeps its default clip.
            e = default_entry(entries, host)
            if e is None:
                e = default_entry(entries, go)
        else:
            e = driving if host == driving["go"] else default_entry(entries, host)
        if e is None:
            continue
        full = td.get("path", "")
        # 相对路径按宿主**全路径**分段截断（宿主名互为前缀时 rfind 会串台）
        rel = rel_path_in(path_by_go.get(go, ""), full)
        if rel is None:
            rel = full
        assign[tfid] = {"sampler": samplers[(e["go"], e["state"])],
                        "duration": e["duration"],
                        "loop": not (e is driving and go == driving["go"]),
                        "time_offset": (0.0 if e is driving
                                        else float(secondary_phase)),
                        "clip": e["state"], "root": e["go"], "anim_path": rel}
    return assign


def morph_positions(part, clip, t, anim_path=None, prefix=""):
    """按 blendShape 曲线给该部件的**局部顶点**加形变，返回新的 positions 列表。

    Unity 的顺序是「先 apply blendShape，再蒙皮」：

        v_local = v0 + Σ_channels  delta(channel, weight/100)
        v_world = skin(v_local)

    所以这里在 `_skin_mesh` 之前把增量加进 `positions`。没有 blendShape 或
    没有对应曲线时返回 None（调用方沿用原始 positions）。

    数据来源：Mesh 资源的 `m_Shapes`（`unity_mesh._parse_blend_shapes`）
    + 动画里 attribute 为 `blendShape.<通道名>` 的百分比曲线。
    """
    mesh = getattr(part, "mesh", None) or {}
    shapes = mesh.get("blendShapes")
    if not shapes:
        return None
    curves = (clip or {}).get("morph") or {}
    if not curves:
        return None
    path = anim_path if anim_path is not None else (getattr(part, "anim_path", "") or "")
    wts = _curve_lookup(curves, path, prefix)
    if not wts:
        return None
    tans_all = ((clip or {}).get("morph_tan") or {})
    tans = _curve_lookup(tans_all, path, prefix) or {}
    pos = [tuple(v) for v in (mesh.get("positions") or [])]
    if not pos:
        return None
    touched = False
    for sh in shapes:
        keys = wts.get(sh["name"])
        if not keys:
            continue
        kt = tans.get(sh["name"])
        if kt is None or len(kt) != len(keys):
            kt = [(0.0, 0.0)] * len(keys)
        w = unity_curve_eval(keys, kt, t)          # 百分比
        if not w:
            continue
        frames = sh["frames"]
        fw = list(sh.get("frameWeights") or [])
        if len(fw) != len(frames):
            fw = [float(sh.get("fullWeight") or 100.0)] * len(frames)
        if len(frames) == 1 or w <= float(fw[0]):
            # 单帧、或权重没到第一帧阈值：factor = weight / thr[0]，作用在**第一帧**
            w0 = float(fw[0]) or 100.0
            pairs = [(frames[0], max(0.0, min(1.0, w / w0)))]
        else:
            # 多帧：在**权重空间**里按相邻两帧的阈值插值（阈值 = 每帧 fullWeight）
            # 与 `CalculateBlendShapeWeights` 的循环一致：从 0 起，遇到
            # `w <= thr[i]` 就停（阈值可能非单调，例如 [100,50,100]）
            k = 0
            i = 1
            while i < len(fw) - 1:
                if w <= float(fw[i]):
                    break
                k = i
                i += 1
            a, b = float(fw[k]), float(fw[k + 1])
            v = 0.0 if b <= a else (w - a) / (b - a)
            pairs = [(frames[k], 1.0 - v), (frames[k + 1], min(1.0, v))]
        for fr_delta, fac in pairs:
            if fac <= 0.0:
                continue
            for idx, dx, dy, dz in fr_delta:
                if 0 <= idx < len(pos):
                    p0 = pos[idx]
                    pos[idx] = (p0[0] + dx * fac,
                                p0[1] + dy * fac,
                                p0[2] + dz * fac)
                    touched = True
    return pos if touched else None


def _part_points(part, world, morph=None):
    """部件当前世界顶点（Unity 世界坐标，YZ 仍带 z 分量）。"""
    if morph is not None and part.kind == "skinned" and getattr(part, "mesh", None):
        mesh = dict(part.mesh)
        mesh["positions"] = morph
        return _skin_mesh(part, mesh, world)
    if part.kind == "sprite":
        # 走 Unity 的 Tight 网格（多边形）时，直接用它自己的局部顶点；
        # 只有回落四边形的部件才在这里按 rect/pivot 现拼。
        if getattr(part, "outline", False) and (part.mesh or {}).get("positions"):
            local = [(v[0], v[1], 0.0) if len(v) == 2 else tuple(v)
                     for v in part.mesh["positions"]]
            m = world.get(part.tfid)
            return [mat4_vec(m, v) for v in local] if m is not None else []
        sp = part.sprite or {}
        rect = sp.get("rect") or [0, 0, 0, 0]
        pivot = sp.get("pivot") or [0.5, 0.5]
        ppu = _num_or(sp.get("pixelsToUnits"), 100.0) or 100.0
        ww = rect[2] / ppu
        hh = rect[3] / ppu
        # Unity Sprite 局部四角：-pivot*rectSize/ppu（pivot 在磁盘资源里是归一化值）
        lx = -rect[2] * pivot[0] / ppu
        by = -rect[3] * pivot[1] / ppu
        local = [(lx, by, 0.0), (lx + ww, by, 0.0),
                 (lx + ww, by + hh, 0.0), (lx, by + hh, 0.0)]
        # m_FlipX / m_FlipY：Unity 把四边形**绕 pivot 镜像**（几何也动，UV 不动），
        # 不是"只换 UV"。pivot 不居中时两者差别就是"精灵落在 pivot 的哪一侧"
        # （alice_skin2 的伞，见 已知问题.md 1.5）。
        if getattr(part, "flip_x", False):
            local = [(-x, y, z) for x, y, z in local]
        if getattr(part, "flip_y", False):
            local = [(x, -y, z) for x, y, z in local]
        m = world.get(part.tfid)
        return [mat4_vec(m, v) for v in local] if m is not None else []
    if part.kind == "skinned":
        return _skin_mesh(part, part.mesh, world)
    m = world.get(part.tfid)
    if m is None:
        return []
    return [mat4_vec(m, (v[0], v[1], v[2]))
            for v in part.mesh.get("positions", [])]


def _part_uvs(part):
    """部件 UV。所有 sprite 用同一条规则，不按名字特判。

    本渲染链路的 v 以贴图顶行为 0（见 tools/spine_raster.py 的说明），
    Unity 的 Sprite.rect.y 自贴图底边算起，于是：
        v(区域底边) = 1 - rect.y / th
        v(区域顶边) = 1 - (rect.y + rect.h) / th
    顶点顺序 = Unity Sprite 局部四角顺序 [BL, BR, TR, TL]，
    因此 uv[i] 与顶点一一对应；朝向（含负缩放造成的镜像/旋转）完全由
    世界矩阵决定，转换多少次都一致。
    """
    if part.kind == "sprite":
        if getattr(part, "outline", False) and (part.mesh or {}).get("uvs"):
            return list(tuple(u) for u in part.mesh["uvs"])
        sp = part.sprite or {}
        rect = sp.get("rect") or [0, 0, 0, 0]
        tw, th = _tex_size(part.texture_path)
        u0 = rect[0] / tw
        u1 = (rect[0] + rect[2]) / tw
        v_bottom = 1.0 - rect[1] / th
        v_top = 1.0 - (rect[1] + rect[3]) / th
        # SpriteRenderer 的 m_FlipX / m_FlipY **不在这里翻 UV**：
        # Unity 是把四边形**绕 pivot 镜像**（几何也动），UV 保持原样；
        # 对 pivot 不居中的精灵，"只换 UV"会让它落在 pivot 的另一侧
        # （alice_skin2 的伞就是这一条，见 已知问题.md 1.5）。
        # 镜像已经在 convert_2dmodel 建四边形时做掉了，这里给原始 UV。
        return [(u0, v_bottom), (u1, v_bottom), (u1, v_top), (u0, v_top)]
    return _flip_v(part.mesh.get("uvs", []))


def _part_tris(part):
    if part.kind == "sprite":
        # 建四边形时若只翻了一个轴，绕序已跟着反过（见 convert_2dmodel），
        # 这里用四边形自带的那份，别写死。
        return list((part.mesh or {}).get("triangles") or [0, 1, 2, 0, 2, 3])
    return list(part.mesh.get("triangles", []))


def hierarchy_ranks(mdl):
    """层级 DFS 序（`transform` 的深度优先展开序）→ 部件在 Unity
    **渲染器列表**里的先后。

    为什么需要它：Unity 的透明件排序键是
    `(sortingLayer, m_SortingOrder, 到相机的深度)`。2D 角色所有部件的 z 几乎
    完全相同（实测 `_refshot_cerberus_skin3` 103 个渲染器里 101 个 camDepth
    都是 10.000、2 个 10.002，来自网格自身的 z 厚度），所以**同
    `m_SortingOrder` 内的先后完全由这个"列表先后"决定** —— 即
    `Renderer` 被枚举/剔除的顺序，也就是从角色根开始、按 `m_Children`
    顺序深度优先展开的顺序。

    证据（2026-09-17 复核）：`info/Data/PlayFrames/*.json` 里
    `renderers` 数组（`GetComponentsInChildren<Renderer>(true)` 的产物）
    的 **SpriteRenderer 段** 与 prefab 的层级 DFS 序**逐项相同**
    （cerberus_skin1：`eye_1` 在 `eye_star1` **之前** ⇒ 星形瞳孔后画、压在
    普通眼之上，与 Unity 截图一致；我们旧实现按 prefab 文件序恰好反过来）。
    注意 PlayFrames 的 `renderers` 数组是"SMR 段 + Sprite 段"两段拼接
    （旧 dumper 分两趟写），所以只有**同一段内**的相对顺序有意义。
    """
    tops = [tf for tf, t in mdl.transforms.items()
            if t.get("father") not in mdl.transforms]
    return {tf: i for i, tf in enumerate(_dfs_transforms(mdl.transforms, tops))}


def slot_key_with_rank(rank):
    """排序键 = `(sortingOrder 取整, **同值内层级 DFS 序的倒序**)`。

    同值内为什么是**倒序**（枚举序小的画在上面）——2026-09-17 晚用 Unity 实测定案：

    * `ExportDrawOrder.cs` 成对隔离渲染 + 反射读到的 `Renderer.sortingKey`：
      **5,012 条非并列关系 100% 由 (sortingKey, 深度) 解释**（0 条违反）；
      剩下 43 条"键+深度完全相同"的真并列里，**36 条**是"枚举/DFS 序**小**的在上面"。
    * 决定性案例 `cerberus_skin1` 的 `parts_eye_1 / eye_star1 / eye_sleep`
      （同 order=17、同深度）：Unity 画面是**睁眼**（`eye_1` 盖住 `eye_sleep`），
      按"DFS 倒序"排就能复现（旧实现两种排法都是闭眼）。

    反汇编侧也对得上：比较键第一顺位是 `GlobalLayeringData`（层+顺序），
    之后才是深度、`CompareSortingGroupData` 和稳定化字段（见
    `docs/渲染顺序_反汇编研究.md`）。

    不再按部件名字特殊排序（旧实现把名字含 body 的强压到最底），
    也不再用 prefab/场景文件里的出现顺序（与 Unity 的渲染器枚举序无关）。
    """
    def key(entry):
        p = entry["part"]
        return (int(getattr(p, "sorting_order", 0) or 0),
                -rank.get(getattr(p, "tfid", None), 1 << 30))
    return key


def _slot_key(entry):
    """旧口径（只看 sortingOrder，同值按传入顺序稳定排序）。

    保留给不需要层级的调用方；转换器已改用 `slot_key_with_rank()`。
    """
    p = entry["part"]
    return (int(getattr(p, "sorting_order", 0) or 0),)


_UNUSED_MARKER = None


def _min_rank_of_slots(entries, kept, mdl, ranks):
    """每个槽位在**整条动画集**里的最小绘制名次（没有排序曲线的角色返回 None）。

    用途见 `kept.sort(...)` 后面那段注释（#2 的完整解）：把 setup 顺序设成 min-rank 顺序，
    Spine 的"非负偏移"就够表达任意帧了。
    """
    n = len(kept)
    if n == 0:
        return None
    key_of = slot_key_with_rank(ranks)
    best = [n] * n
    any_curve = False
    for e in entries:
        cl = e.get("clip") or {}
        srt = cl.get("sorting") or {}
        if not srt:
            continue
        srt_tan = cl.get("sorting_tan") or {}
        prefix = cl.get("_prefix") or ""
        ts = set()
        for ent in kept:
            td = mdl.transforms.get(getattr(ent["part"], "tfid", None)) or {}
            ap = td.get("anim_path") or ""
            keys = _curve_lookup(srt, ap, prefix)
            if not keys:
                continue
            any_curve = True
            tans = _curve_lookup(srt_tan, ap, prefix)
            if not tans or len(tans) != len(keys):
                tans = [(0.0, 0.0)] * len(keys)
            ts.add(0.0)
            for kt, _v in keys:
                ts.add(round(kt, 6))
            ts.update(sorting_change_times(keys, tans))
        for tm in sorted(ts):
            order = sorted(
                range(n),
                key=lambda i: (sorting_value_of(mdl, e, kept[i]["part"], tm),
                               key_of(kept[i])))
            for pos, i in enumerate(order):
                if pos < best[i]:
                    best[i] = pos
    if not any_curve:
        return None
    return best


def _is_degenerate(entry, world, eps=1e-6):
    pts = _part_points(entry["part"], world)
    if not pts:
        return True
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (max(xs) - min(xs)) < eps and (max(ys) - min(ys)) < eps


def _part_size(part, world):
    """部件当前在世界里的包围盒尺寸（用于判断可见性/退化）。"""
    pts = _part_points(part, world)
    if not pts:
        return 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def pixels_per_unit(mdl, parts, world):
    """估算"1 世界单位 = 多少源图像素"。

    做法：对**网格部件**（蒙皮/静态）比较"UV 张成的像素范围"与"世界张成范围"。
    网格的 UV 直接对应贴图像素，世界坐标又只受骨架链缩放影响，二者之比就是
    该角色真实的 px/unit（精灵部件自带局部缩放，会污染这个比值，故不用）。
    取所有网格部件、两个轴的中位数。

    用途：把导出坐标改成**像素单位**（1 单位 = 1 源图像素），这样按图片原尺寸
    渲染就是 1:1，不会因为不同角色的 Unity 缩放差异（aeda 18.5 单位 vs
    黑莉莉丝 2.44 单位）而显得大小不一或被下采样。
    """
    vals = []
    loose = []          # 放宽条件后的候选（比例差得多的也留着）
    for p in parts:
        if p.kind == "sprite" or not p.mesh or not p.texture_path:
            continue
        pts = _part_points(p, world)
        uvs = p.mesh.get("uvs") or []
        if not pts or not uvs:
            continue
        tw, th = _tex_size(p.texture_path)
        ux = [u[0] * tw for u in uvs]
        uy = [u[1] * th for u in uvs]
        wx = [q[0] for q in pts]
        wy = [q[1] for q in pts]
        rx = ((max(ux) - min(ux)) / (max(wx) - min(wx))
              if (max(wx) - min(wx)) > 1e-6 else None)
        ry = ((max(uy) - min(uy)) / (max(wy) - min(wy))
              if (max(wy) - min(wy)) > 1e-6 else None)
        if rx and ry and 1.0 < rx < 100000.0 and 1.0 < ry < 100000.0:
            mid = (rx + ry) / 2.0
            loose.append(mid)
            # 优先"两轴比例接近"的部件：扁平/退化的网格会给出偏离的比例
            if abs(rx - ry) / max(rx, ry) < 0.25:
                vals.append(mid)
    if not vals:
        # 没有部件满足严格条件时（角色由很多细长部件组成，例如 carolina），
        # 退而用全部部件的 中位数 —— 否则会掉到 100 的兜底值，
        # 整份导出的坐标尺度都是错的。
        vals = loose
    if not vals:
        for p in parts:                       # 回退：用精灵自带的 pixelsToUnits
            if p.kind == "sprite" and p.sprite:
                return _num_or(p.sprite.get("pixelsToUnits"), 100.0) or 100.0
        return 100.0
    vals.sort()
    return vals[len(vals) // 2]


# ------------------------------------------------------------------ 主流程

# deform 关键帧裁剪阈值（世界单位）与输出精度。
# 0.001 世界单位 ≈ 0.7 源图像素（三个主力角色约 700~950 px/单位），比验收阈值
# 0.05 低 50 倍；精度 3 位小数在像素单位下误差 ≤0.0005px。
# 作用：把“几乎不动”的帧合并，draculina 这类大角色的 JSON 能降一半以上。
# 关键帧裁剪阈值（**世界单位**）：只有"相对上一个已写关键帧"的变化超过
# `DEFORM_TOL_WORLD × unit_k` 像素时才写新帧。默认 0.001 世界单位 ≈ 0.8px（Alice）。
# ⚠️ 这个阈值是**按像素**给的，而各部件"px / 世界单位"的系数最多差 8 倍，
# 于是对系数大的部件保留得过密、对系数小的部件其实放得很松；而且消费端（查看器 /
# `verify_merge`）在没写帧的地方是**线性插值**，所以中间时刻最多会偏到接近阈值。
# 2026-10-10 用 `U2S_DEFORM_TOL_WORLD=0` 做实验（产物更大但逐帧精确）。
# 2026-10-10 把默认从 0.001 收到 0.00012（≈0.096px）：0.001 那档其实比验收阈值
# 0.05px **大 16 倍**，消费端线性插值后实测能偏到 0.43px（p90）/0.60px（max）；
# 收到 0.00012 后 Alice `breast t=1.5` 的对账从 0.4272 → **0.0014px(p90)**，
# 产物只大 23%。要旧的粗裁剪：`U2S_DEFORM_TOL_WORLD=0.001`（或 0 表示逐帧不裁剪）。
DEFORM_TOL_WORLD = float(os.environ.get("U2S_DEFORM_TOL_WORLD", "0.00012"))
DEFORM_PRECISION = 3

def _apply_place(mdl, place):
    """把整棵角色子树按 (dx, dy) 平移（对齐参考帧用）。"""
    if not place:
        return
    dx, dy = float(place[0]), float(place[1])
    for tfid, t in mdl.transforms.items():
        if t.get("father") not in mdl.transforms and \
                len(t.get("path", "").split("/")) == 1:
            t["pos"][0] += dx
            t["pos"][1] += dy


def convert_static(prefab, assets, out_dir, dt=0.05, clip_hint=None,
                   scene=None, flip_x=False, secondary_anim=True,
                   max_dim=8192, pma=False, units="px", animated_only=True,
                   want_skel=True, want_json=False, skip_textures=None, place=None,
                   multi_drawable=False, cs_runtime=False):
    mdl, parts = load_character(prefab, assets, scene,
                                animated_only=animated_only)
    skip_pats = skip_texture_patterns(skip_textures)
    if place:
        # 把整棵角色子树平移 (dx, dy)：用于"角色不在场景里、但要让产物与
        # 参考帧（Unity 侧按场景摆位导的真值/参考图）同框"的情况。
        # 平移放在角色根节点的 localPos 上，子节点与动画全部随之整体移动。
        _apply_place(mdl, place)
        print("[place] 角色整体平移 (%g, %g) 世界单位，用于对齐参考帧"
              % (float(place[0]), float(place[1])))
    if not parts:
        raise ValueError("没有可解析部件: " + prefab)
    if getattr(mdl, "excluded_parts", None):
        print("[anim] 排除 %d 个非 Animator 子树部件: %s"
              % (len(mdl.excluded_parts),
                 "，".join(e["path"].split("/")[-1]
                           for e in mdl.excluded_parts[:6])))
    clip_name, clip = _choose_clip(mdl, assets, clip_hint)
    if clip is None:
        g = getattr(mdl, "animator_controller_guid", None)
        if not g:
            why = "prefab 里没有 Animator 组件"
        else:
            cp = _asset_path(assets, g)
            if not cp or not os.path.isfile(cp):
                why = ("AnimatorController 资源缺失（guid=%s…，"
                       "工程里找不到该文件）" % g[:8])
            else:
                why = "AnimatorController 里没有可用的 AnimationClip（静态变体？）"
        raise ValueError("没有可用 AnimatorClip（%s）: %s" % (why, prefab))
    rest = rest_by_anim_path(mdl)
    sampler = AnimSampler(clip, rest=rest)
    # ---- 多 Animator 层：把**其它层**（各自的默认状态 clip）合成进来 ----
    # 运行时所有层同时求值：层 0 之外还有带 motion 的层时（bheur 的 Drone 层），
    # 只按"当前状态 clip"采样会丢掉那些层的骨骼/morph/显隐。
    #   · blend=Override → 高层覆盖同 path+kind 的曲线；
    #   · blend=Additive → `value(t) = base(t) + (over(t) − over(0))`（实测语义，
    #     见 docs 第 9.5），且 over 的 clip 短于主 clip 时**按自己的时长循环**；
    #   · 层权重不是 1 或结构不认识 → 不动，只报告。
    layer_report = []
    _layers = []
    _cp = _asset_path(assets, getattr(mdl, "animator_controller_guid", None) or "")
    if _cp and os.path.isfile(_cp):
        try:
            _layers = parse_animator_layers(_cp)
        except Exception as _ex:                     # noqa: BLE001
            print("[warn] AnimatorController 层解析失败：%r" % (_ex,))
    # ---- 动画清单：所有 Animator 的所有 clip（一次全转）----
    # 主控 clip 决定 setup（默认 lobby 一类）；其它 Animator（如 aeda 的
    # aeda_ball_glow -> star_deco，驱动球体光晕的位移/缩放）在同一时间轴上循环。
    entries = enumerate_clips(mdl, assets) or [
        {"go": None, "animator": "", "state": clip_name, "name": clip_name,
         "clip": clip, "duration": float(clip["duration"]), "is_main": True,
         "path": None}]
    if clip_hint:
        picked = [e for e in entries
                  if clip_hint.lower() in e["state"].lower()]
        if picked:
            entries = picked

    # 其它层的默认状态 clip（每条 entry 都要叠上"不是它自己那层"的层）
    _overlays = []          # [(层名, clip, blend, entry_name)]
    for _li, _L in enumerate(_layers):
        if not _L.get("defaultClipGuid"):
            continue
        _op = _asset_path(assets, _L["defaultClipGuid"])
        if not _op or not os.path.isfile(_op):
            continue
        _ok = (abs(float(_L.get("weight") or 1.0) - 1.0) < 1e-6)
        layer_report.append({"name": _L.get("name"), "blend": _L.get("blend"),
                             "weight": _L.get("weight"), "applied": bool(_ok),
                             "reason": "" if _ok else "层权重不是 1，未合并"})
        if _ok:
            _overlays.append((_L.get("name") or ("layer%d" % _li),
                              resolve_clip_paths(mdl, _main_animator_go(mdl),
                                                 parse_clip(_op)),
                              int(_L.get("blend") or 0), _li))
    if _overlays:
        # entry 属于哪一层：按"状态名 -> 层"反查（同名状态以先出现的层为准）
        _state2layer = {}
        for _li, _L in enumerate(_layers):
            for _nm, _g in (_L.get("states") or []):
                _state2layer.setdefault(_nm, _li)
        # ★ 2026-10-11：**按名字配对**选叠层 clip，而不是一律用"层的默认 clip"。
        #   反例（`2DModel_PECS_Ignis_NS1`，用户报"像多 Clip 挤在一个状态"）：
        #   `Base Layer` 的状态 `Ignis_Breast_Touch_FaceOff` 叠的是
        #   `Bresat_Layer` 的**默认** clip `Chain_Lobby_2Side` ⇒ 摸胸动画里胸链还在播
        #   lobby 的链动作；反过来 `Chain_*` 那 12 条又拿不到主体动作。两边都"动作分离"。
        #   现在按共享词元配对（lobby↔lobby、breast↔breast、normal↔normal），
        #   同分时优先取与本层默认同档的变体（2Side / 1Side / NoChain / Break / Fall）。
        def _vtok(s):
            return set(t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t)

        def _variant(nm):
            low = (nm or "").lower()
            for v in ("2side", "1side", "nochain", "break", "fall"):
                if v in low:
                    return v
            return ""

        _lstates = []
        for _li, _L in enumerate(_layers):
            _sts = []
            for _nm, _g in (_L.get("states") or []):
                _p = _asset_path(assets, _g)
                if _p and os.path.isfile(_p):
                    _sts.append((_nm, _p))
            _dflt = ""
            _dc = _asset_path(assets, _L.get("defaultClipGuid") or "")
            for _nm, _p in _sts:
                if _dc and os.path.abspath(_p) == os.path.abspath(_dc):
                    _dflt = _nm
            _lstates.append((_li, _sts, _variant(_dflt or (_sts[0][0] if _sts else ""))))
        _pair_log = {}
        for e in entries:
            mine = _state2layer.get(e["state"])
            # 认不出这条 entry 属于哪一层时**不叠**：宁可少叠（保持原行为），
            # 也不要拿别的层的 clip 去覆盖它（aeda 只有一个 Base Layer，
            # 一旦误叠自己那层，整条动画会被覆盖成 Lobby）。
            if mine is None:
                continue
            _et = _vtok(e["state"])
            outs = []
            for _li, _L in enumerate(_layers):
                if _li == mine:
                    continue
                _sts = next((s for (li, s, _v) in _lstates if li == _li), [])
                _dvar = next((v for (li, _s, v) in _lstates if li == _li), "")
                if not _sts:
                    continue
                best, best_score = None, -1
                for _nm, _p in _sts:
                    sc = len(_et & _vtok(_nm))
                    if sc > best_score or (sc == best_score and best is not None
                                           and _variant(_nm) == _dvar
                                           and _variant(best[0]) != _dvar):
                        best, best_score = (_nm, _p), sc
                if best is None or best_score <= 0:
                    # 没有共享词元 → 回退到"**本层的默认状态 clip**"。
                    # ★ 2026-10-11：这层回退对**所有**层生效（不再只对 weight=1 的层）。
                    #   这正是**约束 15** 的口径（"非 Base Layer 的状态要带其它层的默认状态"）：
                    #   例 `2DModel_BR_RoyalArsenal_NS1` 的 `BG_start` 与主体状态不共享词元，
                    #   于是叠 `Base Layer` 的默认 `Lobby`；`2DModel_3P_Alice_NS1` 的
                    #   `3P_Alice_NS1_curtain` 叠 `Start` —— 与录制路线验收时的 layers= 口径一致。
                    #   （这些层的 authoring weight 常是 0，运行时由 Actor 脚本设回 1。）
                    _dc2 = _asset_path(assets, _L.get("defaultClipGuid") or "")
                    if not (_dc2 and os.path.isfile(_dc2)):
                        continue
                    best = (next((nm for nm, p in _sts
                                  if os.path.abspath(p) == os.path.abspath(_dc2)),
                                 _sts[0][0]), _dc2)
                _pair_log.setdefault(e["state"], []).append(
                    "%s:%s" % (_L.get("name"), best[0]))
                outs.append((_L.get("name") or "layer", 
                             resolve_clip_paths(mdl, _main_animator_go(mdl),
                                                parse_clip(best[1])),
                             int(_L.get("blend") or 0)))
            if outs:
                # 注意：只要高层动画了同样的属性就覆盖/叠加，和 Unity 一致
                e["clip"] = compose_layers(e["clip"], outs, rest)
        if _pair_log:
            print("[anim] 层配对（前 6 条）：%s" % "；".join(
                "%s→%s" % (k, "/".join(v)) for k, v in list(_pair_log.items())[:6]))
        print("[anim] 叠加 Animator 层 %d 个：%s" % (
            len(_overlays),
            "，".join("%s(%s)" % (nm, "add" if bl else "override")
                      for nm, _c, bl, _li in _overlays)))
    def _clip_name(e):
        # 用 clip **资源名**判断（state 名常与 clip 名不一致，见 _choose_clip）
        return ((e.get("clip") or {}).get("name")
                or e.get("state") or "").lower()

    setup_entry = next(
        (e for e in entries
         if e["is_main"] and "lobby" in _clip_name(e)
         and "start" not in _clip_name(e)
         and "tep" not in _clip_name(e)
         and "breast" not in _clip_name(e)), None)
    if setup_entry is None:
        setup_entry = next(
            (e for e in entries
             if e["is_main"] and "lobby" in _clip_name(e)
             and "start" not in _clip_name(e)), None)
    if setup_entry is None:
        setup_entry = next((e for e in entries if e["is_main"]), entries[0])
    samplers = make_samplers(mdl, entries)
    assign_of = {e["name"]: assignments_for_entry(mdl, samplers, entries, e)
                 for e in entries}
    if secondary_anim is False and len(entries) > 1:
        entries = [setup_entry]
        assign_of = {setup_entry["name"]: assign_of[setup_entry["name"]]}
    print("[anim] Animator %d 个，导出动画 %d 条：%s"
          % (len({e["go"] for e in entries}), len(entries),
             "，".join("%s(%s,%.2fs)" % (e["state"], e["animator"] or "-",
                                        e["duration"]) for e in entries)))

    def sample_for(entry, tm):
        return _sample_world_multi(mdl, assign_of[entry["name"]], tm)

    # 采样时刻：每条动画各按自己的 clip 时长铺关键帧
    # （个别部件在 setup 那一帧尺寸为 0 时，参考帧会挪到它最大的时刻，
    #   见下面的 ref_time —— 否则“动画中才出现的光晕”会被整个丢掉）
    # ⚠ 2026-10-11 试过"有 CS 的角色把网格加密到 60fps"：**没用**（Cerberus 头发
    #   per-vertex 最大 52.7px → 50.3px，只降 5%，体积 +29%）⇒ 已撤。
    #   实测弹簧件 1/20s 能走 ~100px，但加密网格**不是**那几十像素误差的来源：
    #   把产物位移一帧（±1）也不改善 ⇒ 是真·**逐骨动力学**的小相位差（每步约
    #   0.1~0.5°，沿链累积到末端），只在最快摆动那几帧显形（中位误差其实 0.46px）。
    times_of = {}
    force_of = {}
    for e in entries:
        dur_e = e["duration"]
        tl = []
        t = 0.0
        while t <= dur_e + 1e-6:
            tl.append(round(t, 6))
            t += dt
        if not tl or tl[-1] != round(dur_e, 6):
            tl.append(round(dur_e, 6))
        # ① Unity 曲线的关键帧时刻必须落在我们的关键帧上，否则固定步长会
        #    漏掉峰值；② 同一时刻的重复关键帧是 Unity 的"瞬时切换"
        #    （audrey 眨眼就是把 Bone_Eye_* 的 scale 在 1↔0.0001 之间瞬切），
        #    要在切换前再采一个点，否则线性插值会把瞬切拉成一小段渐变，
        #    看起来就是"过渡僵硬 / 闪烁"。
        # ★ 2026-10-12：**切换前、切换后都要采**！只采 `kt − 1e-3` 的话，
        #   时间轴上就变成"(kt−1e-3, 旧值) → 下一个变化点"，中间那 0.7 秒被
        #   **线性插值**填满 —— 实测 Echidna 的"灯光闪烁"（叠加层把灯光骨缩到
        #   0.0001 的方波）就是这样被渲染成"三角波"：跨度 0.14 → 1380 → 2 →
        #   1379 来回**缓慢膨胀/收缩**，而 Unity 是瞬间亮灭（真值里只有
        #   0.00021 / 2.10851 两个取值）。
        #   补 `kt + 1e-3`（切换后的新值）之后，插值窗口变成 1/1000 秒 ≈ 硬跳变。
        cl = e.get("clip") or {}
        extra = set()
        # ★ "切换前/后补的点"必须**强制落键**（不能被 `deform_tol` 裁掉）：
        #   切换前那一点的值与前一个键相同（本来就是"保持帧"），按"变化才写"的
        #   规则会被整段跳过 ⇒ 时间轴上只剩切换后的键 ⇒ 跳变又被插值铺满。
        #   实测 Echidna 灯光就是这样：0.749（亮）被裁掉后，0.05(亮) → 0.75(塌)
        #   直接线性插值 0.7 秒 = 三角波。
        force = set()
        for cu in cl.get("curves") or []:
            prev = None
            pv = None
            for kt, _v in cu.keys:
                if not (0.0 <= kt <= dur_e + 1e-6):
                    continue
                extra.add(round(kt, 6))
                # ★ 2026-10-13：**只有值真的变了**才补"保持帧"（见 _key_vals_differ）
                if (prev is not None and abs(kt - prev) < 1e-4 and kt > 1e-3
                        and _key_vals_differ(pv, _v)):
                    extra.add(round(kt - 1e-3, 6))
                    force.add(round(kt - 1e-3, 6))
                prev, pv = kt, _v
            # 同一时刻的重复关键帧 = 瞬时切换 ⇒ 切换后也补一个点
            seen = {}
            for kt, _v in cu.keys:
                seen[round(kt, 6)] = seen.get(round(kt, 6), 0) + 1
            for kt, cnt in seen.items():
                vals = [v for t2, v in cu.keys if abs(t2 - kt) < 1e-6]
                real_step = (len(vals) > 1
                             and any(_key_vals_differ(vals[0], v)
                                     for v in vals[1:]))
                if cnt > 1 and real_step and 0.0 <= kt <= dur_e - 1e-3:
                    extra.add(round(kt + 1e-3, 6))
                    force.add(round(kt + 1e-3, 6))
        force_of[e["name"]] = force
        for keys in (cl.get("active") or {}).values():
            for kt, _v in keys:
                if 0.0 <= kt <= dur_e + 1e-6:
                    extra.add(round(kt, 6))
        times_of[e["name"]] = sorted(set(tl) | extra)
    times = times_of[setup_entry["name"]]
    _world_cache = {}

    def world_of(entry_name, tm):
        key = (entry_name, tm)
        w = _world_cache.get(key)
        if w is None:
            entry = next(e for e in entries if e["name"] == entry_name)
            w = sample_for(entry, tm)
            _world_cache[key] = w
        return w

    # ---- CS 脚本的运行态影响（--cs）：**在转换器里离线算出来**，不依赖 Unity ----
    #   DynamicBone 是**有状态弹簧**，不能各时刻独立采样，必须按固定步长顺序推进；
    #   所以对每条动画先按 1/60 顺序跑一遍（采样 -> GlobalControl.Run -> DynamicBone），
    #   把 times_of 网格上的世界矩阵**填进 _world_cache** —— 下游 world_of 直接命中缓存，
    #   转换器其余代码一行都不用改。
    if cs_runtime:
        from .cs_runtime import (parse_cs_components, build_runtime,
                                 setup_dynamics, run_global_control,
                                 step_dynamics, snapshot_dynamics,
                                 restore_dynamics, DB_REFRESH)
        _comps = parse_cs_components(prefab, assets)
        _cs = {k: v for k, v in _comps.items() if v}
        if _cs:
            print("[cs] 脚本组件: %s" % "，".join(
                "%s×%d" % (k.split(".")[0], len(v)) for k, v in sorted(_cs.items())))
            _dt = 1.0 / 60.0
            # ★ DynamicBone 粒子链的**建链姿态**（= Unity `Start()→SetupParticles()` 那一刻的姿势）：
            #   `clip`（默认）：该 clip 第 0 帧的姿态（= "角色从这条 clip 开头起播"）
            #   `rest`        ：预制体静态姿态 —— 正是两个"真值生成器"用的口径
            #                   （`verify_cs.cs` 在实例化后立刻 SetupParticles；
            #                    `dump_db_particles.cs` 同），而且 `t_db_frames.py` 已证明
            #                    按这个口径移植版与 Unity **逐帧逐粒子一致到 0.004px**。
            #   两种口径对收敛慢的链（Alexandra 后发 28 粒子）前几秒能差 5~7px，
            #   用 `U2S_CS_DB_SETUP=rest` 做 A/B（见进展文档 §16/§21）。
            _db_setup = os.environ.get("U2S_CS_DB_SETUP", "clip").lower()
            # ★ 2026-10-11：**弹簧链预跑**。游戏里"点击动作"（`Tep_1`/`breast`）是从
            #   idle 切过去的，那时链已在 idle 上跑到稳态；转换器原来对每条动画都从
            #   rest 重新建链（且复用同一 runtime，上一条的末态还会残留 ✗）。
            #   实测（Alexandra `Tep_1`，Unity 先播 lobby 2s 再切）：头发骨 **60.3px → 0.009px**。
            #   做法：先按 setup clip 预跑 `U2S_CS_PREROLL` 秒（默认 2s，0 = 关），
            #   拍链状态快照；每条动画开始前恢复快照。
            #   ★ 默认口径（2026-10-11 实测定稿）：**预跑 6s**。
            #   Cerberus（弹性 0.08/阻尼 0.1，收敛快）2s 就够（2s:21.9px / 6s:52.7px max），
            #   但 Tomoe（弹性 0.01，极软）2s 完全没稳（**平均 65.9px**，6s 后 4.4px）、
            #   LRL_N 2s 190px→6s 14px。取 6s 时四只（Cerberus/Tomoe/LRL_N/Alexandra）
            #   头发**平均**误差 2.7/4.4/5.5/3.7px ⇒ 统一按 6s 走，个别帧尖峰是切换瞬态。
            #   `U2S_CS_PREROLL=2` 可回退旧口径。
            _preroll_sec = float(os.environ.get("U2S_CS_PREROLL", "6.0"))
            # ★ 收敛判据式预跑（2026-10-11 第三轮）：弹簧链的"稳态"在软硬不同的角色上
            #   到的时刻差很多（实测 Cerberus 2s 已稳、Tomoe 要 6s 才稳：同一条 Play 真值下
            #   头发平均误差 2s→65.9px、6s→4.4px；而 Cerberus 反过来 2s 更好 21.9 vs 52.7px
            #   ——因为它 2s 就收敛了，跑更久只是让混沌放大）。所以默认：
            #   **至少跑 `U2S_CS_PREROLL`（默认 2s），之后每 `_PREROLL_CHK` 帧比一次粒子位置，
            #   变化 < `U2S_CS_PREROLL_EPS`（默认 1e-4 世界单位）就认为到稳态**，上限
            #   `U2S_CS_PREROLL_MAX`（默认 10s）。
            _preroll_max = float(os.environ.get("U2S_CS_PREROLL_MAX", "6.0"))
            _preroll_eps = float(os.environ.get("U2S_CS_PREROLL_EPS", "1e-4"))
            _preroll_chk = int(os.environ.get("U2S_CS_PREROLL_CHK", "10"))
            _preroll_snap = None
            _lv_rest = _world_rest = None
            _wired_names = set()
            # ★ 2026-10-13：**按动画可配预跑**。弹簧链是"有历史"的：Unity 里 `lobby`
            #   是从 `Start`（入场）切进去的，链带着 Start 的余摆；我们原口径对所有动画
            #   都用"setup clip 跑到收敛"的快照 ⇒ 这类动画开头相位不对（用户报
            #   Brownie "lobby 开始头发乱摇"，实测两条 Unity 真值第 0 帧就差 44.6px）。
            #   写法：`U2S_CS_PREROLL_<动画名>=<预跑状态>[:<秒>]`，例如
            #   `U2S_CS_PREROLL_lobby=Start:3.0`（秒缺省 = `U2S_CS_PREROLL`）。
            #   同一个 (状态,秒) 只算一次并缓存；算的时候先把链重置回"建链初态"。
            _preroll_ovr = {}
            for _k, _v in os.environ.items():
                if _k.startswith("U2S_CS_PREROLL_") and _v.strip():
                    # Windows 环境变量名大小写会被系统改写 ⇒ 统一按小写存/查
                    _preroll_ovr[_k[len("U2S_CS_PREROLL_"):].lower()] = _v.strip()
            # ★ 组件启停（`m_Enabled`）默认接上；`U2S_CS_DB_ENABLED=0` 退回旧行为。
            _DB_ENABLED = os.environ.get("U2S_CS_DB_ENABLED", "1") != "0"

            def _wire_script(entry):
                """把该 clip 的"脚本字段曲线"接到 DynamicBone 上（逐帧改弹簧参数）。

                Unity 里这些是 AnimationClip 直接写在组件字段上的曲线
                （路径如 `.../CTRL_Dynamic/Bone_Hair`，attribute 是哈希 `script_0x...`），
                运行时会每帧覆盖组件平值 ⇒ 不接的话头发/胸的软硬整段是错的。
                """
                sc = (entry.get("clip") or {}).get("script") or {}
                hit = 0
                for _b in _drv.get("bones", []):
                    _td = mdl.transforms.get(getattr(_b, "tf", None)) or {}
                    _dbp = (_td.get("path") or "").replace("\\", "/")
                    fields = {}
                    for cpath, attrs in sc.items():
                        cp = cpath.replace("\\", "/")
                        if not (_dbp.endswith(cp) or cp.endswith(_dbp)):
                            continue
                        for attr, (ks, tn) in attrs.items():
                            fld = SCRIPT_FIELD.get(attr)
                            if fld:
                                fields[fld] = (ks, tn)
                    _b.anim_fields = {
                        f: (lambda t, k=ks2, n=tn2: unity_curve_eval(k, n, t))
                        for f, (ks2, tn2) in fields.items()}
                    # ★ 2026-10-12：把该 clip 的 `EventDynamicBone` 事件按 **DB 物件名**
                    #   配到这条链上（事件的 `data` 就是物件名；空 data = 全都刷）。
                    #   `U2S_CS_DB_REFRESH=event` 时只在这些时刻刷参数 —— 本工程所有
                    #   DynamicBone 的 `RefreshParam` 都是 false，逐帧不会自动刷，
                    #   事件是唯一会让 `UpdateParameters()` 跑起来的入口。
                    #   注意：**每个动画开始时必须复位事件指针**（这里就是每条的入口）。
                    _gon = _dbp.split("/")[-1]
                    _evs = []
                    for _e in ((entry.get("clip") or {}).get("events") or []):
                        _fn = _e.get("function") or ""
                        if not (_fn.startswith("EventDynamicBone")
                                or _fn.startswith("EventReset")):
                            continue
                        _d = (_e.get("data") or "").strip()
                        if _d and _d != _gon:
                            continue
                        _evs.append(float(_e["time"]))
                    _b.anim_events = sorted(_evs)
                    _b._ev_i = 0
                    _b._ev_last_t = -1e30
                    _b.refresh_mode = DB_REFRESH
                    hit += len(_b.anim_fields)
                if hit and entry["name"] not in _wired_names:
                    _wired_names.add(entry["name"])
                    print("[cs] %-12s 脚本字段曲线（逐帧改弹簧参数）：%d 条"
                          % (entry["name"], hit))

            def _wire_enabled(entry):
                """把 clip 里**绑在 DynamicBone 组件上的 `m_Enabled`** 接到链上。

                ★ 2026-10-12 定位：这类曲线不是"渲染器显隐"，而是**开关弹簧组件本身**：
                  关掉 ⇒ Update/LateUpdate 不跑 ⇒ 弹簧不推进、骨头跟着动画走；
                  0→1 重新打开 ⇒ `OnEnable()→ResetParticlesPosition()`
                  ⇒ 整条粒子链重置成那一刻的骨头位置。
                全工程 327 条这样的曲线（62 条恒 0、119 条会 0/1 切换）——
                不处理就会"给一条 Unity 里根本没在跑的链算物理"（典型：Cerberus 的
                `Skirt_L` 在这个 clip 里恒 0、Alexandra 的 `Hair`/`Breast` 在 lobby 的
                  第 0 帧是 0、0.0167 才打开 ⇒ 建链/重置时刻都不同）。
                开关 `U2S_CS_DB_ENABLED=0` 可退回旧行为做 A/B。
                """
                ev = (entry.get("clip") or {}).get("enabled_db") or {}
                n = 0
                for _b in _drv.get("bones", []):
                    _td = mdl.transforms.get(getattr(_b, "tf", None)) or {}
                    _dbp = (_td.get("path") or "").replace("\\", "/")
                    ks = tn = None
                    for cp, v in ev.items():
                        cp2 = cp.replace("\\", "/")
                        if cp2 == _dbp or _dbp.endswith(cp2) or cp2.endswith(_dbp):
                            ks, tn = v
                            break
                    if not _DB_ENABLED or ks is None:
                        _b.enabled_fn = None
                    else:
                        _b.enabled_fn = (lambda t, k=ks, n2=tn:
                                         abs(unity_curve_eval(k, n2, t)) > 0.001)
                        n += 1
                    _b.was_enabled = True
                if n and entry["name"] not in _en_names:
                    _en_names.add(entry["name"])
                    print("[cs] %-12s DynamicBone 的 m_Enabled 曲线：%d 条链"
                          % (entry["name"], n))

            _en_names = set()
            if _db_setup == "rest":
                _lv_rest = {}
                for _tfid, _td in mdl.transforms.items():
                    _lv_rest[_tfid] = trs_mat(_td["pos"], _td["quat"], _td["scale"])
                _world_rest = _world_matrices(mdl, _lv_rest)
            _rt_ready = False
            for _e in entries:
                _name = _e["name"]
                _assign = assign_of[_name]
                _want = sorted(times_of[_name])
                _dur = float(_e["duration"] or 0.0)
                _nf = int(round(_dur / _dt)) + 1
                _rt = None
                _wi = 0
                _prev_world = None
                if _rt_ready:                           # 换动画：先按本条 clip 重新接曲线
                    _wire_script(_e)
                    _wire_enabled(_e)
                for _f in range(_nf):
                    _t = _f * _dt
                    _tc = (_t % _dur) if (_dur > 1e-6 and _e.get("loop", True)) \
                        else min(_t, _dur)
                    _lv = {}
                    for _tfid, _td in mdl.transforms.items():
                        _a = _assign.get(_tfid)
                        if _a is None:
                            _lv[_tfid] = trs_mat(_td["pos"], _td["quat"],
                                                 _td["scale"])
                            continue
                        _d = _a["duration"]
                        _tt = _t
                        if _d > 1e-6:
                            _tt = (_t % _d) if _a.get("loop", True) else min(_t, _d)
                        _sp = _a["sampler"].sample(
                            _a.get("anim_path", _td.get("anim_path")), _tt)
                        _q = _sp["quat"] or euler_to_quat(_sp["euler"])
                        _lv[_tfid] = trs_mat(_sp["pos"], _q, _sp["scale"])
                    _world = _world_matrices(mdl, _lv)
                    if _rt is None:
                        if _db_setup == "rest":
                            _rt, _drv = build_runtime(mdl, _comps, _lv_rest,
                                                      _world_rest, prefab)
                            setup_dynamics(_rt, _drv)
                            _rt.local = _lv
                            _rt.world = _world
                        else:
                            _rt, _drv = build_runtime(mdl, _comps, _lv, _world,
                                                      prefab)
                            _wire_script(setup_entry)
                            _wire_enabled(setup_entry)
                            setup_dynamics(_rt, _drv, 0.0)
                        if _preroll_sec > 0.0:
                            # 预跑：按 setup clip（通常就是 idle）推进链到稳态
                            _sassign = assign_of[setup_entry["name"]]
                            _sdur = float(setup_entry["duration"] or 0.0)
                            _pre_loop = setup_entry.get("loop", True)
                            _pre_state = setup_entry["state"]
                            _pn = int(round(_preroll_max / _dt))
                            _pmin = int(round(_preroll_sec / _dt))
                            # ★ 2026-10-13：命中 `U2S_CS_PREROLL_<动画名>=<状态>[:<秒>]`
                            #   就把"预跑用哪条动画/跑多久"改掉。弹簧链是有历史的：
                            #   Unity 里 `lobby` 是从 `Start`（入场）切进去的，链带着
                            #   Start 的余摆；统一用 setup clip 跑到收敛会让这类动画
                            #   开头相位不对（用户报 Brownie"lobby 开始头发乱摇"）。
                            _ovr = _preroll_ovr.get((_e["name"] or "").lower())
                            if _ovr:
                                _ost, _osep, _osec = _ovr.partition(":")
                                _ope = next((x for x in entries
                                             if x["state"] == _ost), None)
                                if _ope is None:
                                    print("[cs] %s：找不到预跑状态 %s ⇒ 用默认 %s"
                                          % (_e["name"], _ost,
                                             setup_entry["state"]))
                                else:
                                    _sassign = assign_of[_ope["name"]]
                                    _sdur = float(_ope["duration"] or 0.0)
                                    _pre_loop = _ope.get("loop", True)
                                    _pre_state = _ope["state"]
                                    if _osec.strip():
                                        _preroll_sec = float(_osec)
                                        _pmin = int(round(_preroll_sec / _dt))
                                    print("[cs] %s：预跑改用 %s %.2fs"
                                          "（U2S_CS_PREROLL_%s）"
                                          % (_e["name"], _ost, _preroll_sec,
                                             _e["name"]))
                            _prev_snap = None
                            _pf = 0
                            while _pf < _pn:
                                _pt = _pf * _dt
                                _lvp = {}
                                for _tfid, _td in mdl.transforms.items():
                                    _a2 = _sassign.get(_tfid)
                                    if _a2 is None:
                                        _lvp[_tfid] = trs_mat(_td["pos"], _td["quat"],
                                                              _td["scale"])
                                        continue
                                    _d2 = _a2["duration"]
                                    _tt2 = _pt
                                    if _d2 > 1e-6:
                                        _tt2 = ((_pt % _d2) if _a2.get("loop", True)
                                                else min(_pt, _d2))
                                    _sp2 = _a2["sampler"].sample(
                                        _a2.get("anim_path", _td.get("anim_path")), _tt2)
                                    _lvp[_tfid] = trs_mat(
                                        _sp2["pos"],
                                        _sp2["quat"] or euler_to_quat(_sp2["euler"]),
                                        _sp2["scale"])
                                _rt.local = _lvp
                                _rt.world = _world_matrices(mdl, _lvp)
                                run_global_control(_rt, _drv)
                                _ptc = (_pt % _sdur) if (_sdur > 1e-6
                                                         and _pre_loop) \
                                    else min(_pt, _sdur)
                                step_dynamics(_rt, _drv, _dt, _ptc)
                                _pf += 1
                                # 收敛判据：过了最小预跑后，每 _preroll_chk 帧比粒子位置
                                if _pf >= _pmin and _pf % _preroll_chk == 0:
                                    _now_snap = snapshot_dynamics(_drv)
                                    if _prev_snap is not None:
                                        _dmax = 0.0
                                        for _b1, _b2 in zip(_prev_snap, _now_snap):
                                            for (_p1, _q1), (_p2, _q2) in zip(
                                                    _b1.get("parts", ()),
                                                    _b2.get("parts", ())):
                                                _d = max(abs(_p1[_i] - _p2[_i])
                                                         for _i in range(3))
                                                if _d > _dmax:
                                                    _dmax = _d
                                        if _dmax < _preroll_eps:
                                            print("[cs] 预跑收敛：%.2fs 时粒子最大位移 %.2e"
                                                  " < %.0e，停止预跑"
                                                  % (_pf * _dt, _dmax, _preroll_eps))
                                            break
                                    _prev_snap = _now_snap
                            _preroll_snap = snapshot_dynamics(_drv)
                            print("[cs] 预跑 %s %.2fs（%d 帧，上限 %.0fs）→ 弹簧链稳态快照"
                                  % (_pre_state, _pf * _dt, _pf, _preroll_max))
                        _wire_script(_e)
                        _wire_enabled(_e)
                        _rt_ready = True
                    else:
                        _rt.local = _lv
                        _rt.world = _world
                        if _f == 0 and _preroll_snap is not None and \
                                _e is not entries[0]:
                            restore_dynamics(_drv, _preroll_snap)
                    run_global_control(_rt, _drv)
                    step_dynamics(_rt, _drv, _dt, _tc)
                    # ★ 2026-10-12：缓存要**向下取整到"上一步"**，不能向上取整。
                    #   这个循环原来只写 `_want[_wi] <= _t`（= 把落在两步之间的请求
                    #   时刻也赋成"当前这一步"的世界）。而 `times_of` 里那些
                    #   `kt - 1e-3`（切换前补的"保持帧"，见上面 extra 的注释）正好
                    #   落在两步之间 ⇒ 拿到的是**切换之后**的世界，"保持帧"形同不存在
                    #   ⇒ 瞬时切换被线性插值铺满整段。
                    #   实测 Echidna 的"灯光闪烁"（叠加层把灯光骨缩到 0.0001 的方波）
                    #   因此被渲染成三角波：跨度 0.14→1380→2→1379 来回缓慢胀缩，
                    #   而 Unity 真值只有 0.00021 / 2.10851 两个取值。
                    if _prev_world is None:
                        _prev_world = dict(_rt.world)
                    while _wi < len(_want) and _want[_wi] < _t - 1e-9:
                        # 只有"切换前的保持帧"（force 集合）才用上一步的世界；
                        # 其余落在两步之间的采样点维持原口径（用当前步），
                        # 这样**没有瞬时切换的角色产物逐字节不变**。
                        _world_cache[(_name, _want[_wi])] = (
                            dict(_prev_world)
                            if _want[_wi] in (force_of.get(_name) or ())
                            else dict(_rt.world))
                        _wi += 1
                    while _wi < len(_want) and _want[_wi] <= _t + 1e-9:
                        _world_cache[(_name, _want[_wi])] = dict(_rt.world)
                        _wi += 1
                    _prev_world = dict(_rt.world)
                print("[cs] %-12s 顺序跑 %d 帧，缓存 %d 个采样点"
                      % (_name, _nf, _wi))
        else:
            print("[cs] 这个 prefab 上没有可驱动的 CS 组件")

    world0 = world_of(setup_entry["name"], 0.0)

    def probe_times(e):
        """采样点 + m_IsActive 关键帧时刻（可见窗口可能短于 dt）。"""
        ts = set(times_of[e["name"]])
        cl = e["clip"] or {}
        tans_all = cl.get("active_tan") or {}
        for path, keys in (cl.get("active") or {}).items():
            for kt, _v in keys:
                ts.add(round(kt, 6))
            # 插值曲线（slope=0）的可见窗从"离开 0"那一刻开始，不在关键帧上：
            # 不补这些翻转时刻，短可见窗会被采样步长整个跳过（老行为漏画面）。
            if USE_RUNTIME_ACTIVE:
                tans = tans_all.get(path)
                if tans and len(tans) == len(keys):
                    ts.update(active_flip_times(keys, tans))
        # m_SortingOrder 曲线：**相对层级**只在"排序值（取整后）变化"的时刻翻转，
        # 而这些时刻落在斜坡中段、不在关键帧上。必须把它们补进探测网格：
        #   ① 统计层级集合时不能漏；
        #   ② 生成 attachment 时间轴时，"换 drawable"的切换必须正好落在这些时刻。
        for keys in (cl.get("sorting") or {}).values():
            for kt, _v in keys:
                ts.add(round(kt, 6))
            ts.update(sorting_change_times(keys, None))
        # blendShape 曲线的关键时刻也要采：形变可能发生在采样网格之间
        for per_name in (cl.get("morph") or {}).values():
            for keys in per_name.values():
                for kt, _v in keys:
                    ts.add(round(kt, 6))
        # Sprite 交换的关键时刻（换图是瞬时的，必须正好采到切换点）
        for per_attr in (cl.get("pptr") or {}).values():
            for keys in per_attr.values():
                for k in keys:
                    ts.add(round(k[0], 6))
        return sorted(ts)

    def visible_anywhere(tfid):
        for e in entries:
            for tm in probe_times(e):
                if part_visible(mdl, e["clip"], tm, tfid):
                    return True
        return False

    entries_by_name = {e["name"]: e for e in entries}

    # ---- 还没支持的动画通道：**显式报告**，不要静默丢 ----
    # ① m_PPtrCurves 的 `m_Sprite`：SpriteRenderer 换贴图（换表情）。
    #    转换器只导出 prefab 的静态 sprite，所以这些时段的表情是错的。
    # ② 多 Animator 层（controller 里 Base Layer 之外还有带 motion 的层）：
    #    运行时所有层同时求值，我们按"单条状态 clip"采样，其它层的
    #    变换/blendShape 不会进产物。
    sprite_swap = []
    draw_order_anims = []
    draw_order_skipped = 0
    for e in entries:
        for pth, attrs in ((e["clip"] or {}).get("pptr") or {}).items():
            if "m_Sprite" not in attrs:
                continue
            sprites = []
            for t, g, _fid in attrs["m_Sprite"]:
                if g not in sprites:
                    sprites.append(g)
            sprite_swap.append({"animation": e["name"], "path": pth,
                                "sprites": sprites,
                                "keys": [[round(t, 4), g] for t, g, _f in attrs["m_Sprite"]]})
    if sprite_swap:
        print("[anim] 检测到 Sprite 交换动画（换贴图/换表情）：导出为"
              "「同一 slot 多 attachment + attachment 时间轴」，共 %d 条动画"
              % len({s["animation"] for s in sprite_swap}))
        for s in sprite_swap[:3]:
            print("       %s %s 用 %d 张 sprite" % (s["animation"],
                                                  s["path"].split("/")[-1],
                                                  len(s["sprites"])))
    def morph_of(part, entry_name, tm):
        """该部件在 (entry, tm) 这一帧的 blendShape 形变顶点（没有则 None）。

        必须和取世界矩阵时用的是**同一个 entry 的同一时刻**，否则 setup 与
        deform 参考的姿态会来自两条不同的动画（部件会被算成"一直在形变"）。
        """
        e = entries_by_name.get(entry_name)
        if e is None:
            return None
        td = mdl.transforms.get(getattr(part, "tfid", None)) or {}
        return morph_positions(part, e["clip"], tm,
                               td.get("anim_path") or "",
                               (e["clip"] or {}).get("_prefix") or "")

    # 收集可见部件（含全部光晕 sprite；Unity 里全黑/零缩放的它们加色后不可见）
    kept = []
    for p in parts:
        if not p.mesh and p.kind != "sprite":
            continue
        if p.kind == "sprite" and not p.sprite:
            continue
        # 屏蔽贴图（默认含 Unity 编辑器助手贴图）：不进图集也不渲染，
        # 否则 viewer 里会看到骨骼/IK 控制点的圆环、针、关节标记。
        hit = texture_skipped(getattr(p, "texture_path", None), skip_pats)
        if hit:
            mdl.excluded_parts.append(
                {"path": p.full_path, "kind": p.kind,
                 "reason": "屏蔽：%s（Unity 编辑器助手贴图，Unity 里不渲染）"
                           % os.path.basename(getattr(p, "texture_path", "") or hit)})
            continue
        # m_Bones 非空但**全是空引用**的 SkinnedMeshRenderer：Unity 求蒙皮矩阵时
        # 拿到的骨骼是空的 → 顶点全塌到一点，**一个像素都画不出来**；但渲染器
        # 自己仍算 `isVisible`、bounds 也照报（`ExportDrawOrder` 里那件的
        # screenBox 还在），所以四层校验都发现不了。
        # 2026-09-18 用参考帧定案：constantias2_{normal,skin1S} 的
        # `CS_parts_hair_3`(order=-3) 二十帧全 0 墨迹（我们却画出一缕飘在
        # 空白处的头发）；cerberus_skin3 的 `Part_Eye_Close/Smile_{L,R}_26`
        # (order=26) 让"闭眼/笑眼"两层叠在睁眼上（用户报的"表情重叠严重"）。
        # 判据：m_Bones 里 fileID 0 被解析成 None/0，都是假值。
        if p.kind == "skinned" and p.bones and not any(p.bones):
            mdl.excluded_parts.append(
                {"path": p.full_path, "kind": p.kind,
                 "reason": "SkinnedMeshRenderer 的 m_Bones 全是空引用"
                           "（Unity 蒙皮塌陷、不渲染）"})
            continue
        pts = _part_points(p, world0,
                           morph_of(p, setup_entry["name"], 0.0))
        uvs = _part_uvs(p)
        tris = _part_tris(p)
        if not pts or len(pts) != len(uvs) or not tris:
            continue
        col, blend, premul = (sprite_style(assets, p) if p.kind == "sprite"
                              else mesh_style(assets, p))
        # 加色件：记下渲染器自己的 alpha（`i.color.a`）—— 它已经被折进槽位 rgb
        # （见 sprite_style/mesh_style 的 additive 分支），这里留着给颜色时间轴
        # 把"淡入淡出"从 alpha 通道换到 rgb 通道用。
        _a0 = (_sprite_color(p)[3] if p.kind == "sprite" else None)
        if blend == "additive" and _a0 is None:
            _mi = read_material(assets, (getattr(p, "materials", None) or [None])[0])
            _a0 = _mi["color"][3] if _mi else 1.0
        # 逐帧量尺寸（所有动画一起看）：只在“整段动画里始终不可见”时才丢弃
        size0 = _part_size(p, world0)
        best_size, best_ref = size0, (setup_entry["name"], 0.0)
        for e in entries:
            for tm in times_of[e["name"]]:
                sz = _part_size(p, world_of(e["name"], tm))
                if sz > best_size:
                    best_size, best_ref = sz, (e["name"], tm)
        if best_size < 1e-5:
            continue
        # Unity 里用 SetActive 切换表情部件：整个动画里始终禁用的不要导出，
        # 否则会叠出"两个眉毛""眼睛中间多一道"
        if not visible_anywhere(p.tfid):
            mdl.excluded_parts.append(
                {"path": p.full_path, "kind": p.kind,
                 "reason": "Unity 里始终禁用（SetActive=0）"})
            continue
        _entry = {"part": p, "uvs": [list(u) for u in uvs], "tris": tris,
                  "color": col, "blend": blend, "premultiply": premul,
                  "mcolor": _mcolor(p),
                  "ref": (setup_entry["name"], 0.0) if size0 > 1e-5
                  else best_ref}
        if blend == "additive" and _a0 is not None:
            _entry["add_fade"] = float(_a0)
        kept.append(apply_multiply_policy(_entry, assets))

    xs, ys = [], []
    for e in kept:
        for q in _part_points(e["part"], world_of(*e["ref"]),
                              morph_of(e["part"], *e["ref"])):
            xs.append(q[0])
            ys.append(q[1])
    ox = (min(xs) + max(xs)) / 2.0 if xs else 0.0
    oy = (min(ys) + max(ys)) / 2.0 if ys else 0.0
    fx = -1.0 if flip_x else 1.0
    # 像素单位：把世界单位换算成源图像素（1 单位 = 1 px），保证 1:1 渲染
    unit_k = 1.0
    if units == "px":
        unit_k = pixels_per_unit(mdl, parts, world0)
        print("[units] 1 世界单位 = %.2f 源图像素（导出按像素单位）" % unit_k)
    elif units != "world":
        raise ValueError("units 只能是 'px' 或 'world'")
    # deform 关键帧：以**世界单位**给阈值（0.001 ≈ 0.7 源图像素），再换算到输出单位。
    deform_tol = DEFORM_TOL_WORLD * unit_k

    for e in kept:
        pts = _part_points(e["part"], world_of(*e["ref"]),
                           morph_of(e["part"], *e["ref"]))
        e["setup"] = [(fx * (q[0] - ox) * unit_k, (q[1] - oy) * unit_k)
                      for q in pts]
    # 同 sortingOrder 内的次序 = 层级 DFS 序（Unity 渲染器枚举序），
    # 见 `hierarchy_ranks()` 的证据说明。
    kept.sort(key=slot_key_with_rank(hierarchy_ranks(mdl)))
    # ★ 2026-10-13（#2 Eternity 冰淇淋层级的**完整解**）：Spine 3.8 的 drawOrder
    #   `offsets` 只能**非负** ⇒ "某件在某一帧跑到自己 setup 名次**之前**"的帧编不出来
    #   （实测 `3P_Eternity_NS2_SpecialTouch`：254 帧只写出 1 键、**127 帧被跳过**）。
    #   解法：把 **setup 顺序**改成"每件在**整条动画集**里的**最小名次**"（min-rank order），
    #   于是任意时刻都满足 `rank_t(s) ≥ setup(s)` ⇒ 所有帧都能用非负偏移表达。
    #   代价：这些角色**没有排序曲线的动画**也要在 t=0 落一个 drawOrder 键（= 它自己的顺序），
    #   否则 t<0/setup 姿态会显示成 min-rank 顺序（见下面 `_min_rank_of_slots` 的注释）。
    try:
        _ranks = hierarchy_ranks(mdl)
        _mr = _min_rank_of_slots(entries, kept, mdl, _ranks)
        _MINRANK_DONE = False
        _MINRANK_RANKS = _ranks
        if _mr is not None:
            _ord = sorted(range(len(kept)), key=lambda i: (_mr[i], i))
            if _ord != list(range(len(kept))):
                kept[:] = [kept[i] for i in _ord]
                print("[drawOrder] setup 顺序按 min-rank 重排（%d 个槽位）"
                      "⇒ 任意帧都可用非负偏移表达" % len(kept))
            _MINRANK_RANKS = _ranks
            _MINRANK_DONE = True
    except Exception as _ex:                                         # noqa: BLE001
        print("[drawOrder] min-rank 重排失败（忽略，退回原顺序）：%s" % _ex)

    # ---- m_Sprite 交换（换贴图/换表情）：给同一个 slot 备多份 attachment ----
    # Unity 里 `m_Sprite` 是 PPtr 曲线（阶跃：到点就换），运行时换的是渲染器的
    # sprite 资源，几何（rect/pivot/pixelsToUnit）也跟着换。Spine 侧的表达方式是
    # **一个 slot 挂多个 attachment + attachment 时间轴**，所以这里为每张被换到的
    # sprite 复制一份"变体部件"，并把 guid -> attachment 名记下来给时间轴用。
    _sprite_guid_of_tfid = {}
    for r in (getattr(mdl, "renderers", None) or []):
        if r.get("kind") == "sprite" and r.get("spriteGuid"):
            _sprite_guid_of_tfid[r.get("tfid")] = r["spriteGuid"]
    variant_entries = []
    variants_of_tfid = {}
    swap_schedule = {}
    swap_report = []
    for e in kept:
        p = e["part"]
        if p.kind != "sprite":
            continue
        td = mdl.transforms.get(p.tfid) or {}
        ap = td.get("anim_path") or ""
        per_entry = {}
        guids = set()
        for en in entries:
            cl = en["clip"] or {}
            d = _curve_lookup(cl.get("pptr") or {}, ap, cl.get("_prefix") or "")
            ks = (d or {}).get("m_Sprite")
            if not ks:
                continue
            per_entry[en["name"]] = ks
            guids.update(g for _t, g, _f in ks)
        if not per_entry:
            continue
        static_g = _sprite_guid_of_tfid.get(p.tfid)
        guids.discard(static_g)
        if not guids:
            continue
        att_of = {static_g: None}          # None = 用基础 attachment
        variants = []
        for i, g in enumerate(sorted(guids), start=2):
            sp_path = _asset_path(assets, g)
            if not sp_path or not os.path.isfile(sp_path):
                print("[warn] Sprite 交换：找不到 sprite %s（%s）" % (g[:8], p.name))
                continue
            sp = parse_sprite(sp_path)
            tex = _asset_path(assets, sp.get("textureGuid"))
            if not tex or not os.path.isfile(tex):
                print("[warn] Sprite 交换：找不到贴图（%s）" % p.name)
                continue
            vp = copy.copy(p)
            vp.name = "%s__%d" % (p.name, i)
            vp.sprite = sp
            vp.texture_path = tex
            # 变体的 sprite 资源不同 ⇒ 不能共用基础部件的网格。
            # 先按**这个变体自己的精灵资产**取 Unity 生成的网格，取不到再回落
            # 按 alpha 复刻的轮廓；都没有才现拼四边形（_part_points 会照它自己的
            # sprite rect/pivot 拼）——与基础部件同一套优先级。
            vp.mesh, vp.mesh_source = sprite_part_mesh(
                sp, tex, flip_x=getattr(vp, "flip_x", False),
                flip_y=getattr(vp, "flip_y", False))
            vp.outline = bool(vp.mesh)
            if not vp.mesh:
                vp.mesh_source = "quad"
            ve = {"part": vp, "ref": e["ref"], "spriteGuid": g}
            uvs = _part_uvs(vp)
            tris = _part_tris(vp)
            if not uvs or not tris:
                continue
            ve["uvs"] = [list(u) for u in uvs]
            ve["tris"] = tris
            col, blend, premul = sprite_style(assets, vp)
            ve["color"], ve["blend"], ve["premultiply"] = col, blend, premul
            ve["mcolor"] = _mcolor(vp)
            if blend == "additive":
                ve["add_fade"] = _sprite_color(vp)[3]
            apply_multiply_policy(ve, assets)
            variants.append(ve)
            variant_entries.append(ve)
            att_of[g] = vp.name
        if variants:
            variants_of_tfid[p.tfid] = variants
            swap_schedule[p.tfid] = {"per_entry": per_entry, "att_of": att_of}
            swap_report.append({"path": p.full_path, "part": p.name,
                                "variants": [v["part"].name for v in variants],
                                "sprites": sorted(guids)})

    # 变体的 setup 顶点：和基础部件用**同一个参考帧**，只是 sprite 的 rect/pivot/ppu
    # 不同，所以几何可能整体不同（这正是要单独做 attachment 的原因）。
    for ve in variant_entries:
        pts = _part_points(ve["part"], world_of(*ve["ref"]))
        if not pts:
            continue
        ve["setup"] = [(fx * (q[0] - ox) * unit_k, (q[1] - oy) * unit_k)
                       for q in pts]

    base = os.path.splitext(os.path.basename(prefab))[0]
    os.makedirs(out_dir, exist_ok=True)

    # ---- 相对层级 + 多 drawable（按用户要求：不再靠 drawOrder 切换）----
    # 每个部件按"它在**重叠邻居**里排第几"分层；层级会变的部件就多开几个
    # drawable（槽位），动画里只让"当前层级"那个可见 —— 谁挡谁永远正确，
    # 而且不需要 drawOrder 时间轴（Spine 的 drawOrder 只能往前挪，表达不了重排）。
    _kept_base = list(kept)

    def _aabb_of(entry_name, tm, i):
        w = world_of(entry_name, tm)
        pts = _part_points(_kept_base[i]["part"], w)
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    _depths, _depth_at = relative_layers(mdl, entries, _kept_base, _aabb_of,
                                         times_of=lambda e: probe_times(e))
    _multi = [i for i, d in _depths.items() if len(d) > 1]
    # **多 drawable 目前默认关闭**（2026-09-15 用户决定）：先把"相对层级"只当
    # 诊断量用，正常导出仍是一部件一槽位、顺序按静态 sortingOrder。
    # 为什么先不用：一个部件要 N 层就得把同一份**逐帧形变**写 N 遍（Spine 的
    # deform 路径是 `slot/attachment`），draculina 这类角色会膨胀到 GB 级
    # （见 docs/已知问题.md 第 4 条）。要开用 `--multi-drawable`。
    if multi_drawable:
        kept = expand_layers(_kept_base, _depths)
    else:
        kept = _kept_base
    if _multi:
        print("[layer] %d/%d 个部件相对层级会变%s"
              % (len(_multi), len(_kept_base),
                 ("-> 多 drawable，槽位 %d → %d"
                  % (len(_kept_base), len(kept))) if multi_drawable
                 else "（当前未启用多 drawable，顺序仍按静态 sortingOrder）"))
    # `_depth_at[动画][t] = 行`（每行 = 每个部件的相对层级）。这里把它转成
    # "阶梯函数"并按部件切分，导出时间轴时用 `layer_at()` 查"这一刻该亮哪个
    # drawable"。切换点只可能出现在 probe_times 上（排序值变化时刻已补进去），
    # 所以二分查找取"最后一个 t ≤ 查询时刻"就是精确值。
    _layer_series = {}
    for _en, _seq in _depth_at.items():
        _per = {}
        for _i in range(len(_kept_base)):
            _steps = []
            for _t, _row in _seq:
                _d = _row[_i]
                if not _steps or _steps[-1][1] != _d:
                    _steps.append((_t, _d))
            _per[_i] = _steps
        _layer_series[_en] = _per

    def layer_at(entry_name, base_index, tm):
        """该部件在 (动画, 时刻) 的**相对层级** = 当前该亮哪个 drawable。"""
        sp = (_layer_series.get(entry_name) or {}).get(base_index)
        if not sp:
            return 0
        lo, hi = 0, len(sp)
        while lo < hi:                      # 第一个 t > tm 的位置
            mid = (lo + hi) // 2
            if sp[mid][0] <= tm + 1e-9:
                lo = mid + 1
            else:
                hi = mid
        return sp[max(0, lo - 1)][1]

    _layer_report = [{"index": int(i), "part": _kept_base[i]["part"].name,
                      "path": _kept_base[i]["part"].full_path,
                      "layers": [int(v) for v in _depths[i]]}
                     for i in _multi]

    # ---- 图集页：尽量只用一张 ----
    # 加色混合（blend: additive）在 Spine 里是 (ONE, ONE)，与 Unity 的
    # "Legacy Particles/Additive（Blend SrcAlpha One）"等价的前提是贴图按 alpha
    # 预乘。所以需要对加色部件用到的像素做预乘处理。两种做法：
    #   A. 这些像素**没有被普通混合部件采样** -> 直接在同一张图上就地预乘，
    #      仍然只输出一张 PNG（默认，优先）；
    #   B. 被普通部件共用（同一片像素既要预乘又要保持直通 alpha）-> 才另出
    #      一张**裁剪到实际用到区域**的小图，并把加色部件的 UV 重映射过去。
    from PIL import Image
    import numpy as np
    used = set()

    def uniq(n):
        nn = n
        k = 1
        while nn in used:
            nn = "%s_%02d" % (n, k)
            k += 1
        used.add(nn)
        return nn

    pages = []          # [{file, size, regions:[(name, meta)]}]
    region_of = {}      # texture_path -> region name（直通页）
    premul_of = {}      # texture_path -> region name（预乘页，可能裁剪）
    uv_remap = {}       # part id -> (x0, y0, page_w, page_h)  裁剪页重映射

    def _uv_px(part, uvs):
        tw, th = _tex_size(part.texture_path)
        xs = [u[0] * tw for u in uvs]
        ys = [u[1] * th for u in uvs]
        return xs, ys

    def _touches(uvs, tris, rect, tw, th):
        """普通部件的三角形是否覆盖到 rect（像素坐标，闭区间）。"""
        x0, y0, x1, y1 = rect
        for i in range(0, len(tris), 3):
            try:
                ia, ib, ic = int(tris[i]), int(tris[i + 1]), int(tris[i + 2])
                pts = [(uvs[ia][0] * tw, uvs[ia][1] * th),
                       (uvs[ib][0] * tw, uvs[ib][1] * th),
                       (uvs[ic][0] * tw, uvs[ic][1] * th)]
            except (IndexError, ValueError):
                continue
            bx0 = max(x0, min(p[0] for p in pts))
            bx1 = min(x1, max(p[0] for p in pts))
            by0 = max(y0, min(p[1] for p in pts))
            by1 = min(y1, max(p[1] for p in pts))
            if bx1 <= bx0 or by1 <= by0:
                continue
            cxm, cym = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            (ax, ay), (bx, by), (cx, cy) = pts
            d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(d) < 1e-9:
                continue
            w0 = ((by - cy) * (cxm - cx) + (cx - bx) * (cym - cy)) / d
            w1 = ((cy - ay) * (cxm - cx) + (ax - cx) * (cym - cy)) / d
            if w0 >= -1e-6 and w1 >= -1e-6 and (1 - w0 - w1) >= -1e-6:
                return True
        return False

    # 每张源贴图：分出"需要预乘（加色）"与"不需要"的部件
    tex_parts = {}
    for e in _kept_base + [v for v in variant_entries if v.get("setup")]:
        tex_parts.setdefault(e["part"].texture_path, []).append(e)

    def _new_page(img, tw, th, suffix=""):
        idx = len(pages)
        fname = "%s_static_%d%s.png" % (base, idx, suffix)
        img.save(os.path.join(out_dir, fname))
        name = "tex%d" % idx
        pages.append({"file": fname, "size": (tw, th),
                      "regions": [(name, {"x": 0, "y": 0,
                                          "width": tw, "height": th})]})
        return name

    def _uv_rects(group):
        """一组部件的 UV 像素矩形（外扩 1px，再合并相邻区域，少改点像素）。"""
        rects = []
        for e in group:
            xs, ys = _uv_px(e["part"], e["uvs"])
            rects.append((int(math.floor(min(xs))) - 1,
                          int(math.floor(min(ys))) - 1,
                          int(math.ceil(max(xs))) + 1,
                          int(math.ceil(max(ys))) + 1))
        rects.sort()
        merged = []
        for r in rects:
            if merged and r[0] <= merged[-1][2] + 2 and \
                    r[1] <= merged[-1][3] + 2:
                m = merged[-1]
                merged[-1] = (min(m[0], r[0]), min(m[1], r[1]),
                              max(m[2], r[2]), max(m[3], r[3]))
            else:
                merged.append(r)
        return merged

    def _bake_px(sub, op, sig=None, alpha_scale=None):
        """就地改一块像素（`sub` 既可以是整页数组的视图，也可以是裁出来的小块）。

        op="add"：加色件按 alpha 预乘（配 PMA Additive 的 ONE/ONE）；
        op="mul"：乘法件烘成"黑 + α = 2·_TintColor.a·tex.a·(1−m0)"（配普通混合）；
        op="mulopaque"：实验口径留 `blend=multiply` 时把该区域 α 置 1
        （Spine 的 multiply = `DstColor OneMinusSrcAlpha`，只有 α=1 才退化成
        纯乘法 `out = dst×src.rgb`，也就是 Unity `Particles/Multiply` 的语义）。
        """
        if op == "add":
            sub[..., :3] = (sub[..., :3] * sub[..., 3:4]) // 255
            return
        if op == "mulopaque":
            sub[..., 3] = 255
            return
        # op="mul"：实测语义 out = dst×(1 − src.a·(1−m0))
        #   m0    = 2·i.color.rgb·_TintColor.rgb·tex.rgb（逐通道 ⇒ 灰化取均值）
        #   src.a = (2·_TintColor.a·tex.a) × i.color.a（i.color.a 在槽位颜色里）
        # 所以 texel 烘成： rgb=0、α = clip(2·_TintColor.a·tex.a·(1−m0))
        f = np.array(sig or (1.0, 1.0, 1.0), dtype=np.float64)
        m = (sub[..., :3].astype(np.float64) / 255.0) * f
        m = m.mean(axis=2)
        tex_a = sub[..., 3].astype(np.float64) / 255.0
        a = (alpha_scale or 1.0) * tex_a * (1.0 - np.clip(m, 0.0, 1.0))
        sub[..., 3] = np.rint(np.clip(a, 0.0, 1.0) * 255.0).astype(np.uint16)
        sub[..., :3] = 0

    def _bake_rects(arr_, merged, op, sig=None, alpha_scale=None):
        r"""按**闭区间**矩形改像素（与 `_uv_rects`/冲突判定的口径一致）。

        早先这里写成 `arr[y0:y1, x0:x1]`（右/下开区间），会比账本里的矩形
        少烘 1 行 1 列 —— 对加色件无感，但乘法件会留一条"原贴图"的 1px 边
        （`tools\check_multiply_bake.py` 抓到的就是这个）。2026-10-10 改成闭区间。
        """
        for (x0, y0, x1, y1) in merged:
            x0 = max(0, min(tw, x0)); y0 = max(0, min(th, y0))
            x1 = max(0, min(tw - 1, x1)); y1 = max(0, min(th - 1, y1))
            if x1 <= x0 or y1 <= y0:
                continue
            _bake_px(arr_[y0:y1 + 1, x0:x1 + 1], op, sig, alpha_scale)

    def _crop_page(group, op, sig=None, suffix="", alpha_scale=None):
        """把一组的 UV 区域裁出来单独成页（这片像素还有别的部件要用时必须这样）。

        返回 `(region 名, uv_map)`；`uv_map = (x0−pad, y0−pad, 页宽, 页高,
        原宽, 原高)`，槽位/附件用它把 UV 重映射到裁出来的小页上。
        """
        merged = _uv_rects(group)
        pad = 2
        x0 = max(0, min(r[0] for r in merged))
        y0 = max(0, min(r[1] for r in merged))
        x1 = min(tw, max(r[2] for r in merged))
        y1 = min(th, max(r[3] for r in merged))
        crop = np.array(base_img.crop((x0, y0, x1, y1)), dtype=np.uint16)
        _bake_px(crop, op, sig, alpha_scale)
        cimg = Image.fromarray(crop.astype("uint8"), "RGBA")
        cw, ch = cimg.size
        padded = Image.new("RGBA", (cw + pad * 2, ch + pad * 2),
                           (0, 0, 0, 0))
        padded.paste(cimg, (pad, pad))
        nm = _new_page(padded, cw + pad * 2, ch + pad * 2, suffix)
        return nm, (x0 - pad, y0 - pad, cw + pad * 2, ch + pad * 2, tw, th)

    def _straight_page(baked):
        """直通页：本张图有就地烘焙（乘法）就用烘过的数组，否则原图复制过去。"""
        if baked:
            img = Image.fromarray(arr.astype("uint8"), "RGBA")
            region_of[tp] = _new_page(img, tw, th)
            return region_of[tp]
        idx = len(pages)
        fname = "%s_static_%d.png" % (base, idx)
        shutil.copy2(tp, os.path.join(out_dir, fname))
        pages.append({"file": fname, "size": (tw, th), "regions": [
            ("tex%d" % idx, {"x": 0, "y": 0, "width": tw, "height": th})]})
        region_of[tp] = "tex%d" % idx
        return region_of[tp]

    def _finish_rows(pend, region, dst):
        """把"就地改"的账本条目补上页名（裁剪页的条目在生成时就写好了）。"""
        for r in pend:
            if not r.get("cropped"):
                r["page"] = region
        dst.extend(pend)

    mul_report = []         # 乘法件清点（烘进图集 / 保留 blend=multiply）
    add_report = []         # 加色件"按 alpha 预乘"改了哪片像素（校验器要用）
    for tp in tex_parts:
        tex_entries = tex_parts[tp]
        mults = [e for e in tex_entries if e.get("bake_multiply")]
        adds = [e for e in tex_entries if e["premultiply"]]
        tw, th = _tex_size(tp)
        base_img = Image.open(tp).convert("RGBA")
        arr = np.array(base_img, dtype=np.uint16)   # 就地烘焙用的工作副本
        dirty = False

        # ---- 乘法件：默认"直接对图集处理"（烘成 黑 + α，槽位普通混合）----
        # 合成法则（Unity 实测，见 `apply_multiply_policy` 的 docstring）：
        #   out = dst × (1 − src.a·(1 − m0))，src.a = 2·_TintColor.a·tex.a·i.color.a
        # ⇒ texel 烘成 rgb=0、α = 2·_TintColor.a·tex.a·(1−m0)；i.color.a 留在槽位。
        # 因子(含 alpha 倍率)相同的乘法件合起来处理（同一张图上多个影子时一次改一片）。
        _groups = {}
        for e in mults:
            _key = (tuple(round(v, 4) for v in e["mult_factor"]),
                    round(float(e.get("mult_alpha", 1.0)), 4))
            _groups.setdefault(_key, []).append(e)
        _op = "mulopaque" if MULTIPLY_BLEND else "mul"
        pend = []
        add_pend = []
        for sig, grp in sorted(_groups.items()):
            fac, ascale = sig
            merged = _uv_rects(grp)
            ids = {id(x) for x in grp}
            clash = any(_touches(o["uvs"], o["tris"], r, tw, th)
                        for o in tex_entries if id(o) not in ids
                        for r in merged)
            if clash and not pma:
                nm, uvmap = _crop_page(grp, _op, fac, "_mul", ascale)
                for e in grp:
                    e["region_override"] = nm
                    e["uv_map"] = uvmap
                    pend.append({"part": e["part"].name,
                                 "factor": list(fac),
                                 "alphaScale": ascale,
                                 "page": nm, "cropped": True,
                                 "rects": [list(r) for r in merged],
                                 "uvMap": list(uvmap),
                                 "pageSize": [tw, th]})
                print("[mul] 乘法区域与其它部件共用像素 ⇒ 改到裁剪页 %s（%s）"
                      % (nm, "，".join(e["part"].name for e in grp)))
            else:
                _bake_rects(arr, merged, _op, fac, ascale)
                dirty = True
                for e in grp:
                    pend.append({"part": e["part"].name,
                                 "factor": list(fac),
                                 "alphaScale": ascale,
                                 "page": None, "cropped": False,
                                 "rects": [list(r) for r in merged],
                                 "pageSize": [tw, th]})
        if mults:
            facs = sorted({tuple(round(v, 3) for v in e["mult_factor"])
                           for e in mults})
            print("[mul] %s：%d 个乘法件%s（因子 %s；%d×%d）"
                  % (os.path.basename(tp), len(mults),
                     "保留 blend=multiply（实验口径）" if MULTIPLY_BLEND
                     else "烘进图集、槽位写 normal",
                     " / ".join(",".join("%.3f" % v for v in f) for f in facs),
                     tw, th))

        if pma:
            # 全局预乘模式：整页预乘，交给 spine-unity 的 PMA shader
            # （Spine/Skeleton = Blend One OneMinusSrcAlpha）与
            # Spine/Blend Modes/Skeleton PMA Additive（Blend One One）。
            # 乘法件烘出来的 (0,0,0,α) 预乘后不变，所以"先烘后乘"没问题。
            arr[..., :3] = (arr[..., :3] * arr[..., 3:4]) // 255
            img = Image.fromarray(arr.astype("uint8"), "RGBA")
            region_of[tp] = _new_page(img, tw, th)
            _finish_rows(pend, region_of[tp], mul_report)
            continue
        if not adds:
            _finish_rows(pend, _straight_page(dirty), mul_report)
            continue

        # 加色（需要预乘）部件的像素矩形：同样先看能不能就地改
        merged = _uv_rects(adds)
        add_pend.append({"texture": os.path.basename(tp), "page": None,
                         "cropped": False,
                         "parts": [e["part"].name for e in adds],
                         "rects": [list(r) for r in merged],
                         "pageSize": [tw, th]})
        ids = {id(x) for x in adds}
        conflict = any(_touches(o["uvs"], o["tris"], r, tw, th)
                       for o in tex_entries if id(o) not in ids
                       for r in merged)

        if not conflict:
            # A. 就地预乘：仍然只有一张图
            _bake_rects(arr, merged, "add")
            img = Image.fromarray(arr.astype("uint8"), "RGBA")
            region_of[tp] = _new_page(img, tw, th)
            _finish_rows(pend, region_of[tp], mul_report)
            _finish_rows(add_pend, region_of[tp], add_report)
            continue

        # B. 需要两张：直通页（含乘法烘焙结果）+ 裁剪后的预乘页
        _finish_rows(pend, _straight_page(dirty), mul_report)
        _finish_rows(add_pend, region_of[tp], add_report)
        nm, uvmap = _crop_page(adds, "add", None, "_add")
        premul_of[tp] = nm
        add_pend[-1]["page"] = nm
        add_pend[-1]["cropped"] = True
        add_pend[-1]["uvMap"] = list(uvmap)
        for e in adds:
            e["region_override"] = nm
            e["uv_map"] = uvmap

    slots = []
    skin = {}
    meta_parts = []
    # 每个 slot 的"Sprite 交换变体"附件名。Spine 的 deform 时间线只在
    # **当前挂的附件 == 时间线绑定的附件**时生效，所以变体附件必须各写一份
    # 同样的形变；否则部件在切到变体期间会冻在初始姿势（现象：一张脸跟着动、
    # 另一张脸/嘴不动，看起来像"两张脸 / 两个嘴 / 两个上眼框"）。
    variants_by_slot = {}
    def _region_for(ent):
        """条目该用哪张页：裁剪页（`region_override`）> 预乘页 > 直通页。"""
        tp_ = ent["part"].texture_path
        if ent.get("region_override"):
            return ent["region_override"]
        if ent["premultiply"]:
            return premul_of.get(tp_) or region_of.get(tp_)
        return region_of.get(tp_) or premul_of.get(tp_)

    def _remap_uv(ent):
        """条目若落在裁剪页上，把 UV 重映射过去（否则原样返回）。"""
        if not ent.get("uv_map"):
            return ent["uvs"]
        x0, y0, pw, ph, w0, h0 = ent["uv_map"]
        return [((u * w0 - x0) / pw, (v * h0 - y0) / ph)
                for u, v in ent["uvs"]]

    for e in kept:
        nm = uniq(e.get("_name_hint") or e["part"].name)
        e["name"] = nm
        tp = e["part"].texture_path
        region = _region_for(e)
        uvs = _remap_uv(e)
        att = {
            "type": "mesh",
            "uvs": [fnum(x) for uv in uvs for x in uv],
            "triangles": list(e["tris"]),
            "vertices": [fnum(x) for v in e["setup"] for x in v],
            "hull": len(e["setup"]),
            "width": 1, "height": 1,
            "path": region,
        }
        slot = {"name": nm, "bone": "Root",
                "color": _hex_color(e["color"]),
                "attachment": nm}
        if e["blend"] != "normal":
            slot["blend"] = e["blend"]
        slots.append(slot)
        skin[nm] = {nm: att}
        # 该 slot 的 Sprite 交换变体：同一 slot 的额外 attachment
        slot_variants = []
        for ve in variants_of_tfid.get(e["part"].tfid, []):
            if not ve.get("setup"):
                continue
            tpv = ve["part"].texture_path
            regionv = _region_for(ve)
            uvsv = _remap_uv(ve)
            skin[nm][ve["part"].name] = {
                "type": "mesh",
                "uvs": [fnum(x) for uv in uvsv for x in uv],
                "triangles": list(ve["tris"]),
                "vertices": [fnum(x) for v in ve["setup"] for x in v],
                "hull": len(ve["setup"]),
                "width": 1, "height": 1,
                "path": regionv,
            }
            # 顶点数一致时才能复用同一份 deform 偏移
            if len(ve["setup"]) == len(e["setup"]):
                slot_variants.append(ve["part"].name)
        if slot_variants:
            variants_by_slot[nm] = slot_variants
        meta_parts.append({
            "name": nm, "kind": e["part"].kind, "path": e["part"].full_path,
            # 这个部件所在的节点**有没有被 Unity 绑上曲线**（2026-09-18）：
            # 同一路径下有多个同名节点时，Unity 只绑第一个，其余保持 prefab 姿态
            # （转换器的 `dedupe_anim_paths` 按同一规则把它们解绑）。
            # 校验器（`check_clip_visibility`）看到 `bound=false` 就跳过 —— 
            # 这类部件本来就不该跟 clip 的显隐曲线一致。
            "bound": (mdl.transforms.get(getattr(e["part"], "tfid", None), {})
                      .get("anim_path") is not None),
            # 多 drawable：同一部件可能占多个槽位（`<原名>` 与 `<原名>#<层级>`）。
            # `baseName` = 部件原名、`layerId` = 该槽位代表的相对层级，
            # 校验/校准工具用 `base_slot_name()` 还原后按部件聚合。
            "baseName": e["part"].name,
            "layerId": int(e.get("layer_id", 0)),
            "sortingOrder": int(getattr(e["part"], "sorting_order", 0) or 0),
            "color": _hex_color(e["color"]), "blend": e["blend"],
            "premultiply": bool(e["premultiply"]),
            # 乘法件：默认口径下已经烘进图集（`blend` 记的是**实际输出**的 normal）
            **({"multiplyBaked": True,
                "multiplyFactor": [round(v, 4) for v in e["mult_factor"]]}
               if e.get("bake_multiply") else {}),
            "texture": os.path.basename(e["part"].texture_path or ""),
            "vertices": len(e["setup"]),
            # sprite 部件的网格来源（2026-09-16）：asset = 精灵资产里 Unity 自己
            # 生成的网格；outline = 按 alpha 复刻的轮廓；quad = 四边形兜底。
            "meshSource": getattr(e["part"], "mesh_source", None),
            **({"variants": [
                {"name": ve["part"].name, "sprite": ve["spriteGuid"],
                 "texture": os.path.basename(ve["part"].texture_path or "")}
                for ve in variants_of_tfid.get(e["part"].tfid, [])
                if ve.get("setup")]}
               if variants_of_tfid.get(e["part"].tfid) else {}),
        })

    # ---- 动画：逐帧写 mesh deform（相对 setup）----
    # 关键：只有当某帧相对"上一个已写关键帧"确有变化时才写关键帧。
    # 旧实现用"偏移是否接近 0"来决定是否写，一旦 setup 不是 t=0（例如某部件
    # 在 t=0 尺寸为 0、把参考帧挪到了动画中段），"回到参考姿态"的那一帧会被
    # 错误跳过，导致插值把部件一直压在收缩状态。
    animations = {}
    for entry in entries:
        deform = {}
        # 换图变体的形变帧：键 = (槽位名, 附件名)。**不能**塞进 `deform`（那里的键是
        # 槽位名），否则会被当成新槽位、并且被下面 `dd` 组装时的"复用基础件偏移"
        # 覆盖掉（2026-09-19 在 constantias2_skin1 的 face_ani 上踩到）。
        variant_frames = {}
        last_written = {}
        # 同一部件的多个 drawable 共用一份形变关键帧（几何完全一样），
        # 只是要分别写进各自的 slot/attachment 路径。
        _names_of_base = {}
        for _i, e in enumerate(kept):
            # 没有多 drawable 时没有 base_index，按下标当"基础部件"即可
            # （那时一个部件只有一个槽位）。
            _names_of_base.setdefault(e.get("base_index", _i), []).append(
                e["name"])
        # ---- 可见性时间轴：Unity 的 SetActive -> Spine 的 slot attachment ----
        # 不可见的时刻写成"无附件"，这样运行时不会把备选眼/眉/嘴一起显示。
        # 多 drawable 的部件还要叠加**相对层级**：只有"当前该用那一层"的
        # drawable 才挂附件，其余留空 —— 这样任意时刻的画面顺序都与
        # Unity 的 (sortingOrder, 距离) 一致，且不需要 drawOrder 时间轴。
        slot_anim = {}
        pts_e = probe_times(entry)
        for e in kept:
            bi = e.get("base_index")
            lid = int(e.get("layer_id", 0))
            vf = []
            # 用哨兵而不是 None 表示"还没写过"：否则连续不可见的时段会被
            # 每个探测时刻重复写一遍 `name: null`（实测一条 85 键的废时间轴，
            # Start 里 14 个槽位全是这种）。见 2026-10-09 影子显隐修复。
            prev = _UNSET
            sw = swap_schedule.get(e["part"].tfid)
            sw_keys = (sw["per_entry"].get(entry["name"]) if sw else None)
            for tm in pts_e:
                v = part_visible(mdl, entry["clip"], tm, e["part"].tfid)
                if v and bi is not None:
                    v = (layer_at(entry["name"], bi, tm) == lid)
                nm_at = e["name"]
                if v and sw_keys:
                    g = pptr_value_at(sw_keys, tm)
                    nm_at = sw["att_of"].get(g) or e["name"]
                key = nm_at if v else None
                if prev is _UNSET or key != prev:
                    vf.append({"time": fnum(tm), "name": key})
                    prev = key
            if vf and (len(vf) > 1 or vf[0].get("name") is None):
                slot_anim[e["name"]] = {"attachment": vf}
            # 颜色/透明度时间轴（SpriteRenderer.m_Color / material._Color）
            td_c = mdl.transforms.get(e["part"].tfid) or {}
            ct = color_timeline(e["part"], entry["clip"],
                                td_c.get("anim_path") or "",
                                (entry["clip"] or {}).get("_prefix") or "",
                                fnum, _hex_color(e["color"]),
                                bake_dark=bool(e.get("bake_multiply")),
                                fade_rgb_alpha=e.get("add_fade"))
            if ct:
                slot_anim.setdefault(e["name"], {})["color"] = ct
        # 注：clip 里可能有 typetree_<crc32("m_Color.x")> 形式的颜色曲线，
        # 但实测它们在 Unity 里**并未生效**（aeda 的发光星曲线恒为 0，
        # 而 Unity 参考图里该部件正常显示）——直接套用会把部件刷黑，
        # 光晕层 IoU 从 0.935 掉到 0.837。因此这里不导出颜色时间轴，
        # 需要时由检测器 `tools/check_clip_attributes.py` 单独报告。

        # Sprite 交换变体（同一 slot 的 `<名>__2`/`__3`… 附件）**不能复用**基础件的
        # 逐顶点偏移：三个精灵常常顶点数相同（都是 10 点）但**网格形状不同**
        # （Smile / Surprised / Embarrass 就是），复用会把换图那几帧拉变形。
        # 2026-09-19 实测：`constantias2_skin1` 的 `face_ani` 换到 Surprised 时
        # 归一化形状差 **7%**、世界尺度差 0.4%（`geom_vs_refshot.py` +
        # `_refshot_constantias2_skin1` 的 `spriteVertsAabb/lossyScale` 定的案）。
        _variant_by_name = {}
        for _ves in (variants_of_tfid or {}).values():
            for _ve in _ves:
                if _ve.get("setup"):
                    _variant_by_name[_ve["part"].name] = _ve

        def _variant_offsets(alt, world):
            """变体附件自己的 deform 偏移（相对它自己的 setup）。"""
            ve = _variant_by_name.get(alt)
            if ve is None:
                return None
            vpts = _part_points(ve["part"], world, None)
            if len(vpts) != len(ve["setup"]):
                return None
            out = []
            for a, b in zip(vpts, ve["setup"]):
                out.extend([(fx * (a[0] - ox) * unit_k - b[0]),
                            (a[1] - oy) * unit_k - b[1]])
            return out

        for tm in times_of[entry["name"]]:
            world = world_of(entry["name"], tm)
            _forced = tm in (force_of.get(entry["name"]) or ())
            for bi, be in enumerate(_kept_base):
                pts = _part_points(be["part"], world,
                                   morph_of(be["part"], entry["name"], tm))
                cur = []
                for a, b in zip(pts, be["setup"]):
                    cur.extend([(fx * (a[0] - ox) * unit_k - b[0]),
                                (a[1] - oy) * unit_k - b[1]])
                prev = last_written.get(bi)
                # 关键帧裁剪：只有"相对上一个已写关键帧"的偏差超过阈值才写。
                # 阈值取 0.001 世界单位（≈0.7 源图像素），比验收阈值 0.05 低 50 倍，
                # 却能砍掉大量"几乎不动"的帧——draculina 这类大角色 JSON 降一半以上。
                # 旧实现用 1e-6（等于每帧都写），文件大、加载慢。
                # ★ 但"切换前/后补的点"（`force_of`）必须**强制落键**：
                #   切换前那一点的值与前一个键相同（本来就是"保持帧"），按
                #   "变化才写"会被整段跳过 ⇒ 时间轴上只剩切换后的键 ⇒
                #   跳变又被线性插值铺满（Echidna 灯光就是这样变成三角波的）。
                if _forced or prev is None or len(prev) != len(cur) or not all(
                        abs(x - y) <= deform_tol for x, y in zip(cur, prev)):
                    last_written[bi] = cur
                    frame = {"time": fnum(tm),
                             "vertices": [fnum(v, DEFORM_PRECISION)
                                          for v in cur]}
                    for nm in _names_of_base.get(bi, ()):
                        deform.setdefault(nm, []).append(frame)
                # 换图变体各自算自己的偏移，并**独立**判关键帧裁剪
                # （网格不同 ⇒ 变化率可能与基础件略不同，别蹭它的裁剪结论）
                for nm in _names_of_base.get(bi, ()):
                    for alt in variants_by_slot.get(nm, ()):
                        vcur = _variant_offsets(alt, world)
                        if vcur is None:
                            continue
                        vkey = ("v", alt)
                        vprev = last_written.get(vkey)
                        if vprev is not None and len(vprev) == len(vcur) \
                                and all(abs(x - y) <= deform_tol
                                        for x, y in zip(vcur, vprev)):
                            continue
                        last_written[vkey] = vcur
                        variant_frames.setdefault((nm, alt), []).append(
                            {"time": fnum(tm),
                             "vertices": [fnum(v, DEFORM_PRECISION)
                                          for v in vcur]})
        anim_obj = {}
        if slot_anim:
            # **`slots` 必须扁平**：`slots.<槽位名>`。
            # 证据（app 附带的 spine-cpp 3.8 参考源码 `SkeletonJson.cpp`）：
            #   动画的 slot 时间轴在 `readAnimation` 里是
            #     for (slotMap = slots->_child; ...) { findSlotIndex(slotMap->_name) ... }
            #   即**直接把键当槽位名**，找不到就 `setError("Slot not found: ...")`；
            #   而 `deform` 才是两级：`findSkin(constraintMap->_name)` → `findSlotIndex(...)`。
            # 2026-10-09 一度按"slots 也带皮肤层"改成 `{"default": ...}`，
            # 结果 JSON 直接加载失败（`.skel` 因为走槽位下标不受影响，所以只测 skel 会漏掉）。
            anim_obj["slots"] = slot_anim
        if deform:
            # 末尾补"保持帧"：关键帧裁剪之后，某部件最后一帧可能停在动画中段，
            # 于是 Spine 动画时长 = 最后关键帧（例如 12.5s 的 clip 只剩 3.5s），
            # 运行时循环节奏就与 Unity 不一致。给每个有键的部件补一帧到 clip 末尾。
            dur_e = float(entry["duration"])
            for nm, frames in deform.items():
                if frames and float(frames[-1]["time"]) < dur_e - 1e-6:
                    last = dict(frames[-1])
                    last["time"] = fnum(dur_e)
                    frames.append(last)
            for _k, frames in variant_frames.items():
                if frames and float(frames[-1]["time"]) < dur_e - 1e-6:
                    last = dict(frames[-1])
                    last["time"] = fnum(dur_e)
                    frames.append(last)
            dd = {}
            for nm, frames in deform.items():
                smap = dd.setdefault("default", {}).setdefault(nm, {})
                smap[nm] = frames
                # Sprite 交换的变体附件：优先用**它自己**的形变帧（顶点数相同但网格
                # 形状可能不同，直接复用基础件的逐顶点偏移会把换图那几帧拉变形）；
                # 只有没算出来（网格与基础件完全一致）时才回落基础件的帧。
                for alt in variants_by_slot.get(nm, ()):
                    smap[alt] = variant_frames.get((nm, alt)) or frames
            anim_obj["deform"] = dd
        # ---- 逐帧排序（`m_SortingOrder` 是可动画属性）→ Spine drawOrder 时间轴 ----
        # 2026-09-18：Unity 逐帧按 `m_SortingOrder` 排序（引擎 `SetBoundCurveFloatValue`
        # case 10），我们原来烘成静态顺序 ⇒ 需要"手指压在带子上面"的帧会画反
        # （draculina 抓绳子的手被盖住）。这里把逐帧顺序写成 Spine 3.8 的 drawOrder
        # 关键帧：只用"非负偏移"能精确表达的帧（`draw_order_offsets` 会返回 None 表示
        # 该帧表达不了，跳过 = 运行时沿用上一帧），并把跳过数打到日志里。
        # 注：多 drawable（`--multi-drawable`）是另一条路（一部件多槽位 + 显隐切换），
        # 默认关；两条互不影响，drawOrder 只对这些静态槽位排序。
        try:
            _dts = sorted(set(times_of[entry["name"]]))
            _do, _nskip = draw_order_timeline(entry, kept, _dts, mdl, fnum)
            if _do:
                anim_obj["drawOrder"] = _do
                print("[drawOrder] %s：采样 %d 帧 → 写 %d 个关键帧（%d 帧表达不了已跳过）"
                      % (entry["name"], len(_dts), len(_do), _nskip))
            elif _MINRANK_DONE:
                # ★ min-rank 重排过的角色：这条动画**没有排序曲线**，但 setup 顺序已经不是
                #   它自己的顺序了 ⇒ 必须在 t=0 落一个键，把它自己的顺序显式写出来，
                #   否则整条动画会按 min-rank 顺序画。
                _k0 = slot_key_with_rank(_MINRANK_RANKS)
                _ord0 = sorted(
                    range(len(kept)),
                    key=lambda i: (sorting_value_of(mdl, entry,
                                                    kept[i]["part"], 0.0),
                                   _k0(kept[i])))
                _offs0 = draw_order_offsets(_ord0, len(kept))
                if _offs0:
                    anim_obj["drawOrder"] = [{
                        "time": 0, "offsets": [
                            {"slot": kept[o["slotIndex"]]["name"],
                             "offset": int(o["offset"])} for o in _offs0]}]
                    print("[drawOrder] %s：无排序曲线，补 t=0 键（%d 个槽位）"
                          % (entry["name"], len(_offs0)))
        except Exception as _ex:                                   # noqa: BLE001
            print("[drawOrder] %s 生成失败（忽略）：%s" % (entry["name"], _ex))
        animations[entry["name"]] = anim_obj
    skeleton = {
        "skeleton": {"hash": "ngui2spine-static-" + base,
                     "spine": "3.8.99", "x": 0, "y": 0,
                     "width": 0, "height": 0, "fps": 60},
        "bones": [{"name": "Root", "length": 0, "x": 0, "y": 0,
                   "rotation": 0, "scaleX": 1, "scaleY": 1}],
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin}],
        "animations": animations,
    }
    stem = base + ("_static_pma" if pma else "_static")
    atlas_path = os.path.join(out_dir, stem + ".atlas")
    skel_path = os.path.join(out_dir, stem + ".skel") if want_skel else None
    # 2026-10-10 改：**标准导出只出 `.skel`**，`.json` 只在 Debug/研究时用
    # `--json` 显式打开（JSON 体积能到 skel 的 4~5 倍，像 BlackWyrm 那种能到 300MB+）。
    json_path = os.path.join(out_dir, stem + ".json") if want_json else None
    if json_path:
        with open(json_path, "w", encoding="utf-8") as fp:
            json.dump(skeleton, fp, ensure_ascii=False, indent=1)
    with open(atlas_path, "w", encoding="utf-8") as fp:
        fp.write(atlas_text(pages))
    if skel_path:
        # Spine 3.8 二进制（依据 SpineSkeletonDataConverter 的
        # SkeletonData38BinaryWriter 实现），数据与上面的 .json 完全一致。
        # 库化（2026-09-17）后这个模块搬到了 `unity2spine/spine/` 下，
        # 老写法 `from .spine38_binary_writer` 会让 `--skel` 直接 ModuleNotFound。
        from ..spine.spine38_binary_writer import write_skeleton_binary
        write_skeleton_binary(skeleton, skel_path)
        print("[skel] 已写出二进制骨架: %s（%.1f MB）"
              % (os.path.basename(skel_path),
                 os.path.getsize(skel_path) / 1048576.0))
    # 查看器配置引用的骨架：优先 `.json`（只有在调试模式下才存在），否则 `.skel`
    _ref = os.path.basename(json_path or skel_path or (stem + ".skel"))
    write_viewer_config(out_dir, skeleton, _ref,
                        os.path.basename(atlas_path),
                        [os.path.splitext(p["file"])[0] for p in pages],
                        scale_factor=(1.0 if units == "px" else None),
                        override_scale=(units == "px"))
    # 注：config 文件名默认取**输出目录名**（= 角色名，不含 `.uAnim`），
    #     即 `<文件夹名>.config.json`；不要传 `base`（那会带上 `.uAnim`）。
    # 清掉上一次导出留下的图集页残留（只动本角色的 <base>_static_*.png）
    keep_files = {p["file"] for p in pages}
    for fn in os.listdir(out_dir):
        if fn.startswith(base + "_static_") and fn.endswith(".png") \
                and fn not in keep_files:
            try:
                os.remove(os.path.join(out_dir, fn))
                print("[clean] 删除旧图集页:", fn)
            except OSError as ex:
                print("[clean] 跳过:", fn, ex)

    # ---- 未支持通道：等动画都写完之后再统计 ----
    unsupported = []
    if sprite_swap and not swap_report:
        unsupported.append({
            "channel": "m_Sprite (m_PPtrCurves)",
            "note": "检测到换贴图动画，但一张变体都没能建出来（sprite 资源缺失？）"})
    # 颜色时间轴已实现（见 color_timeline）：只把"没处理到的"报出来
    for _e in entries:
        _cl = _e["clip"] or {}
        for _p, _d in (_cl.get("color") or {}).items():
            _cls = (_cl.get("color_cls") or {}).get(_p)
            if _cls not in (212, 137):
                unsupported.append({
                    "channel": "m_Color.*（classID=%s）" % _cls,
                    "note": "该绑定的组件类型不认识，颜色/透明度动画未导出：%s" % _p})
                break
    if any((e["clip"] or {}).get("material") for e in entries):
        unsupported.append({
            "channel": "material._AdditionalAlpha 等自定义 shader 属性",
            "note": "着色器自定义属性动画未导出（语义依赖 shader；_Color 已按颜色时间轴处理）"})

    info = {
        "prefab": prefab, "scene": scene, "clip": setup_entry["state"],
        "setupClip": setup_entry["state"],
        "animations": [{"name": e["name"], "animator": e["animator"],
                        "state": e["state"], "duration": round(e["duration"], 3),
                        "frames": len(times_of[e["name"]]),
                        "isMain": bool(e["is_main"])} for e in entries],
        "frames": len(times), "dt": dt,
        "parts": len(kept), "origin": [ox, oy], "flipX": flip_x,
        "pma": bool(pma),
        # ★ 叠加层（非 Base 层）的循环相位（秒）。0 = 与 base clip 的 t=0 对齐；
        #   非 0 表示按 `U2S_LAYER_PHASE` 平移过（用于与某条真值逐帧对齐/出同步版）。
        "layerPhase": float(LAYER_PHASE),
        "units": units, "unitScale": unit_k,
        "animatedOnly": bool(animated_only),
        "place": ([float(place[0]), float(place[1])] if place else None),
        "excludedParts": list(getattr(mdl, "excluded_parts", []) or []),
        "spriteSwap": swap_report,
        # 乘法件（Unity `Particles/Multiply` 影子）的处理口径：
        # 默认 "baked-into-atlas"（把乘法烘进图集、槽位 normal）；
        # 实验模式 "blend-multiply"（槽位 blend=multiply，需要运行时混合支持）。
        "multiply": {
            "mode": ("blend-multiply (experimental)" if MULTIPLY_BLEND
                     else "baked-into-atlas (default)"),
            "count": len(mul_report),
            "parts": mul_report,
        },
        # 加色件（Unity `Particles/Additive`）：图集里**该件 UV 矩形按 alpha 预乘**，
        # 槽位仍写 `blend=additive`（运行时 ONE/ONE）。这里记下改了哪片像素，
        # 供 `tools\check_multiply_bake.py` 判"改动是否都有账可查"。
        "additive": {
            "mode": "premultiplied-in-atlas",
            "count": sum(len(r.get("parts") or []) for r in add_report),
            "items": add_report,
        },
        "unsupportedChannels": unsupported,
        # 渲染顺序：**相对层级 + 多 drawable**（不再用 drawOrder 时间轴）。
        # `slots` = 基础部件数 -> 实际槽位数；`multi` 列出会变层、因此占了
        # 多个 drawable 的部件（动画里按 layerId 切换哪一份可见）。
        "relativeLayers": {
            "mode": ("relative-layer + multi-drawable" if multi_drawable
                     else "relative-layer(诊断；未启用多 drawable)"),
            "multiDrawable": bool(multi_drawable),
            "parts": len(_kept_base), "slots": len(kept),
            "multiCount": len(_multi), "multi": _layer_report},
        "sourceSizes": sorted({_tex_size(p.texture_path)
                               for p in parts if p.texture_path}),
        "note_units": ("坐标是源图像素（1 单位 = 1 像素，%s）：按图片原尺寸渲染"
                       "即 1:1，不需要额外缩放" % ("1:%.2f" % unit_k
                                                   if units == "px" else "世界单位")),
        "note": "仅磁盘静态资源（prefab+clip），无编辑器动态数据；"
                "颜色/混合按 Unity 材质；"
                + ("图集为全局预乘 alpha（PMA），配 spine-unity 的 "
                   "Spine/Skeleton 与 PMA Additive shader"
                   if pma else
                   "图集为直通 alpha（非 PMA），仅加色区域按 alpha 预乘，"
                   "需运行时按 slot 混合模式分别设置混合状态")
                + ("；乘法件保留 blend=multiply（实验口径：贴图直通 + 区域 "
                   "α=1，依赖运行时的 multiply 混合）" if MULTIPLY_BLEND else
                   "；乘法件（Unity Particles/Multiply 影子）已**直接烘进图集**"
                   "（区域写成 黑 + α=1−m、槽位 blend=normal），"
                   "产物不依赖运行时的 multiply 支持"),
        "partsMeta": meta_parts,
    }
    if skel_path:
        info["skel"] = os.path.basename(skel_path)
    info["json"] = os.path.basename(json_path) if json_path else None
    with open(os.path.join(out_dir, "_static_info.json"), "w",
              encoding="utf-8") as fp:
        json.dump(info, fp, ensure_ascii=False, indent=1)
    _write_readme(out_dir, info, pages)
    return json_path, atlas_path, info


def _write_readme(out_dir, info, pages):
    kinds = {}
    blends = {}
    for p in info.get("partsMeta") or []:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
        blends[p["blend"]] = blends.get(p["blend"], 0) + 1
    base = os.path.splitext(os.path.basename(info["prefab"]))[0]
    _mul = info.get("multiply") or {}
    _mul_line = None
    if _mul.get("count"):
        _names = "，".join(m["part"] for m in (_mul.get("parts") or []))
        if str(_mul.get("mode", "")).startswith("baked"):
            _mul_line = ("- 乘法件（Unity `Particles/Multiply` 影子）：%d 个"
                         "**已烘进图集**（区域写成 黑 + α=1−m、槽位 `normal`，"
                         "产物不依赖运行时的 multiply 混合）：%s"
                         % (_mul["count"], _names))
        else:
            _mul_line = ("- 乘法件：%d 个保留 `blend=multiply`（**实验口径**，"
                         "贴图直通 + 区域 α=1，需运行时 multiply 混合）：%s"
                         % (_mul["count"], _names))
    lines = [
        "# %s 静态导出（磁盘资源 -> Spine 3.8）" % base,
        "",
        "- setup clip：`%s`（dt=%gs，%d 帧）" % (
            info.get("setupClip") or info["clip"], info["dt"],
            info["frames"]),
        "- 动画（%d 条，覆盖所有 Animator）× 关键帧：" % len(
            info.get("animations") or [{"name": info["clip"]}])
        + "，".join("%s(%d)" % (a["name"], a.get("frames", 0))
                    for a in (info.get("animations")
                              or [{"name": info["clip"], "frames": 0}])),
        "- 部件：%d（%s）" % (
            info["parts"], "，".join("%s×%d" % (k, v)
                                     for k, v in sorted(kinds.items()))),
        "- 混合：%s" % "，".join("%s×%d" % (k, v)
                                 for k, v in sorted(blends.items())),
        _mul_line,
        "- 图集页：%s" % "，".join(p["file"] for p in pages),
        ("- 二进制骨架：`%s`（Spine 3.8 `.skel`，与 `.json` 同一份数据；"
         "**这是标准导出格式**；重新生成："
         "`python -m ngui2spine.spine38_binary_writer <json>`）"
         % info["skel"]) if info.get("skel") else None,
        ("- JSON 骨架：`%s`（**仅 Debug/研究用**；标准导出只出 `.skel`）"
         % info["json"]) if info.get("json") else
        "- JSON 骨架：未导出（标准导出只出 `.skel`；需要时加 `--json`）",
        "- 可见性：Unity 用 SetActive 切换的表情备选件（眼/眉/嘴多组）写成 "
        "slot 的 attachment 时间轴（不可见时段 `name: null`），"
        "整段动画始终禁用的部件不导出",
        "- 查看器配置：`%s.config.json`（同目录，查看器/编辑器可直接打开）"
        % os.path.basename(os.path.normpath(out_dir)),
        "- Alpha 约定：%s" % (
            "全局预乘 alpha（PMA）—— 配 spine-unity 的 `Spine/Skeleton` 与 "
            "`Spine/Blend Modes/Skeleton PMA Additive`" if info.get("pma")
            else "直通 alpha（非 PMA）—— 普通 slot 用 SrcAlpha/OneMinusSrcAlpha；"
                 "加色 slot（blend: additive）用 ONE/ONE，其区域已按 alpha 预乘；"
                 + ("乘法影子保留 blend=multiply（实验）" if MULTIPLY_BLEND else
                    "乘法影子已烘进图集（走普通混合）")),
        "- 坐标原点（Unity 世界，加色部件贴图已按 alpha 预乘）：%s"
        % [round(v, 4) for v in info["origin"]],
        "",
        "部件明细（名称 / 类型 / 混合 / 顶点色 / 排序 / 来源节点）见 "
        "`_static_info.json` 的 `partsMeta`。",
        "",
        "## 校验方法",
        "",
        "```bat",
        "python tools\\static_check.py <prefab> --scene <save.unity> --spine-dir "
        "<本目录>   # 静态检查：动画/场景引用但未导出的资源",
        "python tools\\calib_geo.py --prefab <prefab> --scene <save.unity>   "
        "# 几何：与 Unity 帧真值对比",
        "python tools\\calib_geo.py --prefab <prefab> --scene <save.unity> ^",
        "  --only-spine-dir --spine-dir <本目录>                     "
        "# 端到端：读 JSON 的 setup+deform 还原再比",
        "python tools\\calib_face.py <本目录> --times 0                 "
        "     # 单脸朝向（IoU）",
        "python tools\\calib_sprites.py <本目录> --time 0                "
        "    # 光晕/颜色层",
        "python tools\\calib_full.py <本目录> --time 0                   "
        "    # 整角色轮廓（有 Unity 整图参考时）",
        "```",
        "",
        "静态检查报告见 `_calib/static_check.json`（由转换时自动生成）。",
        "修复背景见 `docs/静态prefab路线.md`。",
    ]
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(l for l in lines if l is not None) + "\n")


# 兼容旧接口
def convert_static_prefab(prefab, assets, out_dir, dt=0.05, clip_hint=None):
    json_path, atlas_path, _info = convert_static(
        prefab, assets, out_dir, dt=dt, clip_hint=clip_hint)
    return json_path, atlas_path


def convert_static_instance(prefab, assets, scene, out_dir, dt=0.05,
                            clip_hint=None, flip_x=False):
    json_path, atlas_path, _info = convert_static(
        prefab, assets, out_dir, dt=dt, clip_hint=clip_hint, scene=scene,
        flip_x=flip_x)
    return json_path, atlas_path


def _run_calib(json_path, info, pose_path):
    """用 Unity 动态帧真值做几何自检（只读、不参与导出）。"""
    try:
        import math
        import json as _json
        from .convert_2dmodel import build_character_model
        from ..unity.unity_anim2d import AnimSampler, parse_clip
        from ..unity.unity_mesh import mat4_vec
        mdl, parts = load_character(info["prefab"], ASSETS_DEFAULT,
                                    info.get("scene"))
        # 导出时如果做过 --place 平移，这里要同样平移一次，否则自检会
        # 报出那个整体偏移（5.0 / 20.0）。
        _apply_place(mdl, info.get("place"))
        _name, clip = _choose_clip(mdl, ASSETS_DEFAULT, info["clip"])
        sampler = AnimSampler(clip, rest=rest_by_anim_path(mdl))
        # 副 Animator 驱动的部件（如球体光晕）不参与真值比对：Unity 的
        # PoseFrames 真值只推进了主控制器，它们在那里停在 rest。
        assign, clip_infos = build_anim_assignments(
            mdl, ASSETS_DEFAULT, info["clip"], secondary=True)
        main_go = next((g for g, _n, _c, m in clip_infos if m), None)
        secondary_tfs = {tfid for tfid, a in assign.items()
                         if a.get("root") != main_go}
        part_is_secondary = {}
        for tfid in secondary_tfs:
            td = mdl.transforms[tfid]
            for p in parts:
                if p.full_path == td["path"] or \
                        p.full_path.startswith(td["path"] + "/"):
                    part_is_secondary[p.full_path] = True
        pose = _json.load(open(pose_path, encoding="utf-8-sig"))
        ox, oy = info["origin"]
        worst = (0.0, None, None)
        for fr in pose["frames"][::5]:
            tm = fr["time"]
            world = _sample_world(mdl, sampler, tm)
            ent = {}
            for key, kind in (("skinned", "skinned"), ("sprites", "sprite")):
                for e in fr.get(key) or []:
                    ent[e["path"]] = (e, kind)
            for p in parts:
                hit = ent.get(p.full_path)
                if not hit:
                    continue
                if part_is_secondary.get(p.full_path):
                    continue
                e, kind = hit
                ours = _part_points(p, world)
                if kind == "sprite":
                    truth = [(c[0], c[1]) for c in (e.get("worldCorners") or [])]
                else:
                    l2w = e.get("localToWorld")
                    if not l2w:
                        continue
                    flat = [v for row in l2w for v in row]
                    truth = [mat4_vec(flat, v)[:2]
                             for v in (e.get("positions") or [])]
                if not ours or len(ours) != len(truth):
                    continue
                d = max(math.dist((a[0], a[1]), b) for a, b in zip(ours, truth))
                if d > worst[0]:
                    worst = (d, p.full_path, tm)
        print("[calib] 与 Unity 帧真值最大顶点误差 %.5f 世界单位 (%s @ t=%s)"
              % (worst[0], (worst[1] or "").split("/")[-1], worst[2]))
        return worst
    except Exception as ex:            # 校准失败不影响导出
        print("[calib] 跳过:", ex)
        return None


ASSETS_DEFAULT = r"D:\VB\Search\NormalLocal\lastOrign\Assets"
# Unity 侧**动态导出**的统一根（2026-09-18 起）：D:\VB\Unity2Spine\info
INFO_DEFAULT = r"D:\VB\Unity2Spine\info"
POSE_DEFAULT = os.path.join(INFO_DEFAULT, "Data", "PoseFrames")


def _repo_root():
    """仓库根：往上找**含 `tools/static_check.py`** 的那一层。

    库化以后本模块在 `src/unity2spine/convert/` 下，不能再靠
    `dirname(dirname(__file__))` 猜根目录（那会指到 `src/unity2spine`），
    否则导出末尾自动跑的静态检查/face_check 会找不到脚本。
    """
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isfile(os.path.join(d, "tools", "static_check.py")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("out")
    ap.add_argument("--assets", default=ASSETS_DEFAULT)
    ap.add_argument("--dt", type=float, default=0.05)
    ap.add_argument("--clip", default=None)
    ap.add_argument("--scene", default=None)
    ap.add_argument("--flip-x", action="store_true")
    ap.add_argument("--secondary-anim", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="同时采样角色内其它 Animator（如 aeda 的球体光效 "
                         "star_deco：Unity 里这些光晕会相对球运动）；"
                         "用 --no-secondary-anim 关闭")
    ap.add_argument("--calib", action="store_true",
                    help="导出后用 PoseFrames 真值做几何自检")
    ap.add_argument("--no-static-check", action="store_true",
                    help="跳过导出后的静态检查（默认会跑 tools/static_check.py）")
    ap.add_argument("--pma", action="store_true",
                    help="导出全局预乘 alpha（PMA）图集：配 spine-unity 的 "
                         "Spine/Skeleton 与 Spine/Blend Modes/Skeleton PMA "
                         "Additive shader 使用；文件名带 _pma 便于识别")
    ap.add_argument("--units", choices=["px", "world"], default="px",
                    help="坐标单位：px=源图像素（默认，1 单位=1 像素，按原图"
                         "尺寸渲染即 1:1）；world=Unity 世界单位（旧行为）")
    ap.add_argument("--animated-only", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="只导出 Animator 子树下的部件（默认）：audrey 这类"
                         "“静态立绘 + 动态立绘”双根角色会排除静态立绘那张"
                         "整图；用 --no-animated-only 导出全部")
    ap.add_argument("--skel", action="store_true",
                    help="（**已是默认**）输出 Spine 3.8 二进制骨架 "
                         "<角色>_static[_pma].skel；保留本开关只为兼容旧命令")
    ap.add_argument("--json", dest="want_json", action="store_true",
                    help="**仅 Debug/研究用**：额外输出 .json 骨架"
                         "（体积是 .skel 的 4~5 倍；标准导出只出 .skel）")
    ap.add_argument("--skip-texture", action="append", default=None,
                    metavar="NAME",
                    help="屏蔽用某张贴图的部件（可重复，也可逗号分隔）。"
                         "默认已屏蔽 Unity 编辑器助手贴图："
                         "BoneJoint/BoneNoJoint/BoneScaled/IKControl/"
                         "splineControl/splineMiddleControl/icon-*")
    ap.add_argument("--skip-texture-file", default=None, metavar="TXT",
                    help="从文件读屏蔽表（每行一个名字，# 开头为注释）")
    ap.add_argument("--place", default=None, metavar="X,Y",
                    help="把整棵角色子树平移 X,Y 世界单位：角色不在场景里、"
                         "但需要与 Unity 参考帧同框时用（例如 aeda --place -20,0）")
    ap.add_argument("--no-face-check", action="store_true")
    ap.add_argument("--multi-drawable", action="store_true",
                    help="允许「相对层级会变」的部件占多个槽位（每层一个 drawable，"
                         "动画只切换亮哪一个）。**默认关闭**：一个部件要 N 层就要把"
                         "逐帧形变写 N 遍，重角色会膨胀到 GB 级；先用它当诊断量。")
    ap.add_argument("--active-step", action="store_true",
                    help="显隐按关键帧（阶跃 + v>=0.5）求值。**现已是默认**，"
                         "保留只为老命令行不报错。")
    ap.add_argument("--active-runtime", action="store_true",
                    help="显隐改回 Unity 运行时语义（按切线插值 + |v|>1e-3）。"
                         "只和 Play 模式采样真值对拍时用；用它会让互补的表情件"
                         "在切换点前后同时可见（tq.txt 第 2/3 类问题就是这么来的）。")
    ap.add_argument("--cs", dest="cs_runtime", action="store_true",
                    help="把 CS 脚本（Puppet2D 样条/IK、DynamicBone 弹簧）的"
                         "运行态影响**在转换器里离线算出来**再导出（不依赖 Unity）。"
                         "见 src\\unity2spine\\convert\\cs_runtime.py。")
    ap.add_argument("--multiply-blend", action="store_true",
                    help="**实验口径**：乘法件（Unity `Particles/Multiply` 影子）"
                         "输出 `blend=multiply`（贴图直通 + 区域 α=1，依赖运行时的 "
                         "multiply 混合）。默认不用它 —— 默认把乘法**直接烘进图集**"
                         "（槽位写 normal，产物不依赖运行时混合支持）。")
    a = ap.parse_args(argv)

    global USE_RUNTIME_ACTIVE, MULTIPLY_BLEND
    if a.active_runtime:
        USE_RUNTIME_ACTIVE = True
    if a.multiply_blend:
        MULTIPLY_BLEND = True

    skip_textures = list(a.skip_texture or [])
    if a.skip_texture_file and os.path.isfile(a.skip_texture_file):
        for line in open(a.skip_texture_file, encoding="utf-8-sig"):
            line = line.split("#", 1)[0].strip()
            if line:
                skip_textures.append(line)

    json_path, atlas_path, info = convert_static(
        a.prefab, a.assets, a.out, dt=a.dt, clip_hint=a.clip, scene=a.scene,
        flip_x=a.flip_x, secondary_anim=a.secondary_anim, pma=a.pma,
        units=a.units, animated_only=a.animated_only, want_skel=True,
        want_json=a.want_json,
        skip_textures=skip_textures,
        multi_drawable=a.multi_drawable,
        cs_runtime=a.cs_runtime,
        place=([float(v) for v in a.place.split(",")] if a.place else None))
    if json_path:
        print(json_path)
    if info.get("skel"):
        print(os.path.join(a.out, info["skel"]))
    if a.calib:
        name = os.path.splitext(os.path.basename(a.prefab))[0]
        pose = os.path.join(POSE_DEFAULT, name + ".json")
        if not os.path.isfile(pose):
            pass
        elif json_path is None:
            print("[calib] 跳过：标定需要 .json 骨架，请加 --json")
        else:
            _run_calib(json_path, info, pose)
    if not a.no_static_check:
        tool = os.path.join(_repo_root(), "tools", "static_check.py")
        report_path = os.path.join(a.out, "_calib", "static_check.json")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        cmd = [sys.executable, tool, a.prefab, "--assets", a.assets,
               "--spine-dir", a.out, "--json", report_path]
        if a.scene:
            cmd += ["--scene", a.scene]
        if a.clip:
            cmd += ["--clip", a.clip]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            # 控制台编码在 Windows 上可能是 GBK，这里不直接回显中文，
            # 只从 JSON 报告读计数，避免编码异常。
            rep = {}
            if os.path.isfile(report_path):
                rep = json.load(open(report_path, encoding="utf-8"))
            print("[static_check] 场景渲染器 %s / 导出部件 %s / "
                  "动画中引用但未导出 %s / 静态可见未导出 %s / "
                  "与真值可见性冲突 %s / 曲线 path 对不上 %s"
                  % (rep.get("sceneRenderers"), rep.get("exportedParts"),
                     len(rep.get("missingAnimated") or []),
                     len(rep.get("missingStatic") or []),
                     len(rep.get("visibilityConflicts") or []),
                     len(rep.get("unknownCurvePaths") or [])))
            if proc.returncode:
                print("[static_check] 有需要处理的问题，详见",
                      os.path.relpath(report_path))
        except Exception as ex:              # 检查失败不影响导出
            print("[static_check] 跳过:", ex)
    if not a.no_face_check:
        tool = os.path.join(_repo_root(), "tools", "face_check.py")
        try:
            subprocess.run([sys.executable, tool, a.out], check=False)
        except Exception as ex:
            print("[face_check] 跳过:", ex)
    return json_path, atlas_path


if __name__ == "__main__":
    main()
