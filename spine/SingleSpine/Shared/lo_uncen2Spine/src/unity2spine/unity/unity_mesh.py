# -*- coding: utf-8 -*-
"""解析 Unity 文本序列化的 Mesh(.asset) 与 Sprite(.asset)（2DModel 用）。"""

import math
import os
import re
import struct


def _f(text, key, default=0.0):
    m = re.search(key + r":\s*([-0-9.eE]+)", text)
    return float(m.group(1)) if m else default


def _hex_field(text, name, until):
    i = text.find(name + ":")
    if i < 0:
        return ""
    j = text.find(until, i)
    if j < 0:
        j = len(text)
    # 有些 mesh 在 m_IndexBuffer 与 m_VertexData 之间还夹着别的顶层字段
    # （例如带具名骨骼权重的 `m_Skin:`），不截断的话会把这些文本
    # 当成十六进制索引，bytes.fromhex 直接报错。
    m = re.search(r"\n  m_[A-Za-z]", text[i:j])
    if m:
        j = i + m.start()
    return re.sub(r"\s+", "", text[i + len(name) + 1:j])


def _parse_skin(text):
    """解析旧格式 mesh 的 `m_Skin:` 段（每顶点 4 组 weight/boneIndex）。

    这类 mesh 的骨骼权重不放在顶点流通道里，而是单独写成：
        m_Skin:
          - weight[0]: 1
            weight[1]: 0
            ...
            boneIndex[0]: 0
            ...
    不解析的话顶点拿不到权重，蒙皮退化成静态（或整块被丢掉）。
    返回 [(weights4, indices4), ...]，顺序与顶点一致。
    """
    i = text.find("m_Skin:")
    if i < 0:
        return []
    m = re.search(r"\n  m_[A-Za-z]", text[i:])
    seg = text[i:(i + m.start() if m else len(text))]
    out = []
    for ent in re.split(r"^  - ", seg, flags=re.M)[1:]:
        w = [0.0] * 4
        b = [0] * 4
        for k in range(4):
            mw = re.search(r"weight\[%d\]: ([-0-9.eE]+)" % k, ent)
            mb = re.search(r"boneIndex\[%d\]: (-?\d+)" % k, ent)
            if mw:
                w[k] = float(mw.group(1))
            if mb:
                b[k] = int(mb.group(1))
        out.append((tuple(w), tuple(b)))
    return out


def _local_aabb(text):
    """解析 mesh 的 `m_LocalAABB`（顶点局部包围盒）-> (center3, extent3)。"""
    i = text.find("m_LocalAABB:")
    if i < 0:
        return None
    seg = text[i:i + 400]
    c = re.search(r"m_Center: \{x: ([-0-9.eE]+), y: ([-0-9.eE]+), "
                  r"z: ([-0-9.eE]+)\}", seg)
    e = re.search(r"m_Extent: \{x: ([-0-9.eE]+), y: ([-0-9.eE]+), "
                  r"z: ([-0-9.eE]+)\}", seg)
    if not (c and e):
        return None
    return ([float(x) for x in c.groups()], [float(x) for x in e.groups()])


def _list_of_vec(text, name):
    """m_BindPose 的 16 个 e 值行 -> 4x4（行主序）。"""
    out = []
    i = text.find(name + ":")
    if i < 0:
        return out
    # 每次匹配一个 4x4
    pat = re.compile(r"- e00: ([-0-9.eE]+)\s+e01: ([-0-9.eE]+)\s+e02: ([-0-9.eE]+)\s+e03: ([-0-9.eE]+)\s+e10: ([-0-9.eE]+)\s+e11: ([-0-9.eE]+)\s+e12: ([-0-9.eE]+)\s+e13: ([-0-9.eE]+)\s+e20: ([-0-9.eE]+)\s+e21: ([-0-9.eE]+)\s+e22: ([-0-9.eE]+)\s+e23: ([-0-9.eE]+)\s+e30: ([-0-9.eE]+)\s+e31: ([-0-9.eE]+)\s+e32: ([-0-9.eE]+)\s+e33: ([-0-9.eE]+)")
    for m in pat.finditer(text, i):
        out.append([float(x) for x in m.groups()])
    return out


TYPE_SIZE = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2,
            6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}
# Sprite 的顶点流实际只用 float32（format 0）；其它 format 语义（归一化整数等）
# 没实现，遇到就让 `_parse_sprite_render_mesh` 返回 None、走回落路径。
TYPE_FMT = {0: "f", 1: "e", 2: "B", 3: "b", 4: "H", 5: "h",
            6: "B", 7: "b", 8: "H", 9: "h", 10: "I", 11: "i"}


def _index_from_float_bits(x):
    """把 0x3F800000 这类 float 位模式还原成整数索引；不是则返回 None。"""
    try:
        f = struct.unpack("<f", struct.pack("<I", int(x) & 0xFFFFFFFF))[0]
    except (struct.error, ValueError, OverflowError):
        return None
    if not math.isfinite(f):
        return None
    r = round(f)
    if abs(f - r) <= 1e-4 and 0 <= r <= 4096:
        return int(r)
    return None


def _pick_bone_indices(raw, weights, n_bones):
    """判定 blend 索引的存放方式：原始整数 or float 位模式。

    判据：非零权重对应的索引应落在 [0, n_bones) 内。
    """
    if not raw:
        return raw
    as_int = [tuple(int(v) for v in t) for t in raw]
    as_bits = [tuple(_index_from_float_bits(v) for v in t) for t in raw]

    def score(seq):
        ok = bad = 0
        for vi, t in enumerate(seq):
            w = weights[vi] if weights and vi < len(weights) else None
            for k in range(min(4, len(t))):
                if t[k] is None:
                    bad += 1
                    continue
                if w is None or k >= len(w) or float(w[k]) <= 1e-6:
                    continue
                if 0 <= t[k] < max(1, n_bones):
                    ok += 1
                else:
                    bad += 1
        return ok, bad

    int_ok, int_bad = score(as_int)
    bit_ok, bit_bad = score(as_bits)
    if bit_bad == 0 and bit_ok > 0 and (int_bad > 0 or int_ok == 0):
        return as_bits
    return as_int


def parse_mesh(path):
    """解析 Unity Mesh 资源，返回 dict：
    positions/uvs/triangles/bindposes/bone_weights(每顶点 [idx.., w..])"""
    text = open(path, encoding="utf-8", errors="replace").read()
    vcount = int(_f(text, r"m_VertexCount", 0))
    mesh = {"name": os.path.basename(path), "vertexCount": vcount,
            "positions": [], "uvs": [], "triangles": [],
            "bindposes": _list_of_vec(text, "m_BindPose"),
            "weights": [], "hasSkin": False}
    aabb = _local_aabb(text)
    if aabb:
        mesh["aabb"] = aabb
    if not vcount:
        return mesh

    # 通道
    channels = []
    for cm in re.finditer(
            r"- stream: (\d+)\s+offset: (\d+)\s+format: (\d+)\s+dimension: (\d+)",
            text):
        channels.append(tuple(int(x) for x in cm.groups()))
    data_hex = _hex_field(text, "_typelessdata", "m_CompressedMesh")
    if not data_hex:
        data_hex = _hex_field(text, "_typelessdata", "m_LocalAABB")
    data = bytes.fromhex(data_hex) if data_hex else b""

    strides = {}
    for stream, off, fmt, dim in channels:
        if dim:
            strides[stream] = max(strides.get(stream, 0),
                                  off + dim * TYPE_SIZE.get(fmt, 4))
    sbase = {}
    base = 0
    for st in sorted(strides):
        sbase[st] = base
        # Unity 顶点流按 16 字节对齐存放
        stream_bytes = strides[st] * vcount
        base += (stream_bytes + 15) // 16 * 16

    def chan_values(stream, off, dim, as_int=False):
        vals = []
        stride = strides.get(stream)
        if not stride:
            return vals
        fmt = None
        for st2, o2, fm2, d2 in channels:
            if st2 == stream and o2 == off and d2 == dim:
                fmt = fm2
                break
        if fmt is None:
            return vals
        for vi in range(vcount):
            at = sbase[stream] + vi * stride + off
            if as_int:
                if fmt == 10:
                    vals.append(struct.unpack_from("<%dI" % dim, data, at))
                elif fmt in (6, 7):
                    vals.append(struct.unpack_from("<%d%c" % (dim, "Bb"[fmt - 6]),
                                                   data, at))
                elif fmt in (8, 9):
                    vals.append(struct.unpack_from("<%d%c" % (dim, "Hh"[fmt - 8]),
                                                   data, at))
                else:
                    vals.append(None)
            else:
                if fmt == 0:
                    vals.append(struct.unpack_from("<%df" % dim, data, at))
                elif fmt == 1:
                    vals.append(struct.unpack_from("<%de" % dim, data, at))
                else:
                    vals.append(None)
        return vals

    # 约定通道索引：0=pos 1=normal 2=tangent 4=uv0 12=blend权重 13=blend索引
    for idx, (stream, off, fmt, dim) in enumerate(channels):
        if dim == 0:
            continue
        if idx == 0:
            mesh["positions"] = chan_values(stream, off, dim)
        elif idx == 4:
            mesh["uvs"] = chan_values(stream, off, dim)
        elif idx == 12:
            mesh["weights"] = chan_values(stream, off, dim)
        elif idx == 13:
            # blend 索引通道通常为 UInt32(format=10)/UInt8，按整数读取。
            # 注意：不同资源里同一 format 的存放方式不一致——
            #   a) 直接存整数（0x00000002 -> 索引 2）；
            #   b) 存 float 位模式（0x3F800000 -> 索引 1）。
            # 旧实现写死了 (b)，遇到 (a) 时索引全变 0（所有顶点绑到第 0 根
            # 骨骼）：静止姿态看不出，动画一动就“部件分离”。
            # 这里按“非零权重对应的索引必须落在骨骼数范围内”自动判定。
            raw = chan_values(stream, off, dim, as_int=True)
            if fmt == 10:
                mesh["boneIndexRaw"] = _pick_bone_indices(
                    raw, mesh.get("weights"), len(mesh.get("bindposes") or []))
            else:
                mesh["boneIndexRaw"] = raw
    # 通道顺序在不同 Unity 版本/导出下并不总是标准槽位（有的省略 Color 通道，
    # UV 会前移到索引 3），按固定下标取会读不到 UV，部件随后被整块丢掉。
    # 这里按“维度 + 浮点格式”兜底。
    if not mesh.get("uvs"):
        for stream, off, fmt, dim in channels:
            if dim == 2 and fmt in (0, 1):
                mesh["uvs"] = chan_values(stream, off, dim)
                break
    # 注意：**不要**去猜权重通道。blendWeights 固定在索引 12，而索引 2 的
    # tangent 也是 dim=4——按"dim==4 就是权重"去兜底会把切线当成权重
    # （baekto 的 parts_Weapon_Skinned_002 就是这样读出了 (-1,0,0,-1)，
    # 而 Unity 读出来是正常的 (1,0,0,0)）。没有权重通道时，
    # Unity 的规则是"第一个骨骼索引权重为 1"，由下游按此处理。
    if not mesh.get("boneIndexRaw"):
        for stream, off, fmt, dim in channels:
            if dim in (1, 2, 3, 4) and fmt in (6, 7, 8, 9, 10):
                raw = chan_values(stream, off, dim, as_int=True)
                if fmt == 10:
                    raw = _pick_bone_indices(
                        raw, mesh.get("weights"),
                        len(mesh.get("bindposes") or []))
                if raw and any(v for v in raw if v):
                    mesh["boneIndexRaw"] = raw
                    break
    # 旧格式 mesh：权重写在 `m_Skin:` 段里，和顶点一一对应，最可靠；
    # 顶点流里的同名字段有时是编辑期快照（值可能对不上），所以以 m_Skin 为准。
    skin = _parse_skin(text)
    if len(skin) >= int(vcount):
        mesh["weights"] = [s[0] for s in skin]
        mesh["boneIndexRaw"] = [s[1] for s in skin]
    mesh["hasSkin"] = (bool(mesh["bindposes"])
                       or bool(mesh.get("boneIndexRaw")))

    # blendShape（morph）：**动画会驱动它**（动画曲线 attribute 是
    # `blendShape.<通道名>`，值是百分比 0~100），漏掉它 = 部件顶点不动
    # （实测 bheur 的 Part_Balgure / Part_UpperArm_* 等误差 0.05~0.07 世界单位）。
    # 结构（见 Mesh 资源 YAML）：
    #   m_Shapes:
    #     vertices:  - {vertex:{}, normal:{}, tangent:{}, index: N}   # 形变增量
    #     shapes:    - {firstVertex, vertexCount, hasNormals, hasTangents}
    #     channels:  - {name, nameHash, frameIndex, frameCount}
    #     fullWeights: - 100
    # 一个 channel 覆盖 shapes[frameIndex .. frameIndex+frameCount-1] 帧；
    # 权重 w（0~100）→ 帧位置 w/100*(frameCount-1)，在相邻帧之间线性插值。
    shapes = _parse_blend_shapes(text)
    if shapes:
        mesh["blendShapes"] = shapes

    # 索引
    tri_hex = _hex_field(text, "m_IndexBuffer", "m_VertexData")
    idx_bytes = bytes.fromhex(tri_hex) if tri_hex else b""
    tri = []
    if idx_bytes:
        if _f(text, r"m_IndexFormat", 0) == 0:
            tri = [idx_bytes[i] | (idx_bytes[i + 1] << 8)
                   for i in range(0, len(idx_bytes), 2)]
        else:
            tri = [idx_bytes[i] | (idx_bytes[i + 1] << 8) |
                   (idx_bytes[i + 2] << 16) | (idx_bytes[i + 3] << 24)
                   for i in range(0, len(idx_bytes), 4)]
    mesh["triangles"] = tri
    # 子网格（多材质）：一个 Mesh 可以带多个材质 → Unity 按子网格分段画，
    # 每段用自己的材质/贴图。不拆开会把整块都贴上第一个材质（babariana 的
    # `parts_004_upperarm_L_skinned` 就是 2 个材质，第二个子网格贴错图
    # ⇒ 背包上出现一块棕色方块）。
    subs = []
    sm = re.search(r"  m_SubMeshes:\n(.*?)\n  (?:m_BindPose|m_MeshCompression|"
                   r"m_IsReadable|m_StreamData|m_VertexData):", text, re.S)
    if sm:
        for blk in re.findall(r"- serializedVersion: \d+\n((?:    .*\n)+)",
                              sm.group(1)):
            fb = re.search(r"firstByte: (\d+)", blk)
            ic = re.search(r"indexCount: (\d+)", blk)
            if fb and ic:
                # firstByte 是字节偏移；索引是 16 位 ⇒ /2 换算成索引下标
                subs.append((int(fb.group(1)) // 2, int(ic.group(1))))
    if len(subs) > 1:
        mesh["submeshes"] = subs
    return mesh


def _parse_blend_shapes(text):
    """解析 `m_Shapes` → [{name, frameWeights, frames: [[(index, dx, dy, dz), ...]]}]。

    没有 blendShape 的 Mesh 返回 []。`frames` 是"每个 shape 帧"的形变增量表，
    单帧（frameCount=1）时外层只有一个元素。

    **`fullWeights` 是按"帧"索引的，不是按通道**（参考实现对多帧形变用
    `CalculateBlendShapeWeights`：`factor = weight / fullWeights[frame]`，
    多帧时按相邻两帧的阈值在权重空间插值）。所以这里保存每帧的权重阈值。
    """
    m = re.search(r"  m_Shapes:\n(.*?)\n  (?:m_BindPose|m_MeshCompression|"
                  r"m_IsReadable|m_StreamData|m_VertexData):", text, re.S)
    if not m:
        return []
    blk = m.group(1)
    if "shapes: []" in blk or "channels: []" in blk:
        return []
    # 形变增量顶点
    deltas = []
    for vm in re.finditer(
            r"-\s*vertex:\s*\{x:\s*([-0-9.eE]+),\s*y:\s*([-0-9.eE]+),"
            r"\s*z:\s*([-0-9.eE]+)\}.*?index:\s*(\d+)", blk, re.S):
        dx, dy, dz, idx = vm.groups()
        deltas.append((int(idx), float(dx), float(dy), float(dz)))
    # shape 帧表
    frames = []
    fm = re.search(r"^\s*shapes:\s*$((?:\n\s*-.*|\n\s{4,}.*)*)", blk, re.M)
    if fm:
        for sm in re.finditer(r"firstVertex:\s*(\d+)\s*\n\s*vertexCount:\s*(\d+)",
                              fm.group(1)):
            frames.append((int(sm.group(1)), int(sm.group(2))))
    if not frames:
        return []
    # 通道（一个通道覆盖 frameIndex..frameIndex+frameCount-1 帧）
    out = []
    full = [float(x) for x in
            re.findall(r"^\s*-\s*([-0-9.eE]+)\s*$", blk, re.M)] if False else []
    fw_block = re.search(r"fullWeights:\s*\n((?:\s*-\s*[-0-9.eE]+\s*\n?)+)", blk)
    if fw_block:
        full = [float(x) for x in
                re.findall(r"-\s*([-0-9.eE]+)", fw_block.group(1))]
    for ci, cm in enumerate(re.finditer(
            r"-\s*name:\s*(.+?)\s*\n\s*nameHash:\s*(\d+)\s*\n"
            r"\s*frameIndex:\s*(\d+)\s*\n\s*frameCount:\s*(\d+)", blk)):
        name = cm.group(1).strip()
        fi, fc = int(cm.group(3)), max(1, int(cm.group(4)))
        shape_frames = []
        frame_weights = []
        for k in range(fc):
            if fi + k >= len(frames):
                break
            first, count = frames[fi + k]
            shape_frames.append(deltas[first:first + count])
            frame_weights.append(full[fi + k] if fi + k < len(full) else 100.0)
        if not shape_frames:
            continue
        out.append({"name": name,
                    "frameWeights": frame_weights,
                    "fullWeight": (frame_weights[0] if frame_weights else 100.0),
                    "frames": shape_frames})
    return out


def parse_sprite(path):
    """解析 Sprite .asset：rect / pivot / texture guid / pixelsToUnits / 渲染网格。

    其中 `renderMesh` 是 **Unity 自己在导入时生成的渲染网格**（紧致多边形），
    直接从资产里读出来就行，不需要复刻 `GenerateSpriteOutline` 的
    "alpha → 轮廓 → 简化" 算法（见 docs/已知问题.md 1.7）。
    """
    text = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    rm = re.search(r"m_Rect:[\s\S]*?x: ([-0-9.eE]+)\s+y: ([-0-9.eE]+)\s+width: ([-0-9.eE]+)\s+height: ([-0-9.eE]+)", text)
    if rm:
        out["rect"] = [float(v) for v in rm.groups()]
    pm = re.search(r"m_Pivot: \{x: ([-0-9.eE]+), y: ([-0-9.eE]+)", text)
    if pm:
        out["pivot"] = [float(pm.group(1)), float(pm.group(2))]
    om = re.search(r"m_Offset: \{x: ([-0-9.eE]+), y: ([-0-9.eE]+)", text)
    if om:
        out["offset"] = [float(om.group(1)), float(om.group(2))]
    tm = re.search(r"texture: \{fileID: \d+, guid: ([0-9a-f]+)", text)
    if tm:
        out["textureGuid"] = tm.group(1)
    out["pixelsToUnits"] = _f(text, r"m_PixelsToUnits", 100)
    # m_Extrude 就是 SpriteUtility.GenerateSpriteOutline 的 extrude，
    # 也是 SpriteMeshGenerator::mask::dilate 的半径（见 sprite_outline.py）
    out["extrude"] = _f(text, r"m_Extrude", 0)
    rm = _parse_sprite_render_mesh(text)
    if rm:
        out["renderMesh"] = rm
    return out


#: SpriteRenderData.m_VertexData.m_Channels 的固定 14 项顺序
_SPRITE_CHANNELS = ("position", "normal", "tangent", "color",
                    "uv0", "uv1", "uv2", "uv3", "uv4", "uv5", "uv6", "uv7",
                    "weights", "indices")


def _hex_after(text, key):
    """取 `key:` 之后到行尾的十六进制串（资产里这些字段都是单行长串）。"""
    i = text.find(key + ":")
    if i < 0:
        return b""
    j = text.find("\n", i)
    seg = text[i + len(key) + 1:(j if j > 0 else len(text))]
    seg = re.sub(r"[^0-9a-fA-F]", "", seg)
    if len(seg) % 2:
        seg = seg[:-1]
    return bytes.fromhex(seg)


def _parse_sprite_render_mesh(text):
    """解析 Sprite 的 `m_RD`（SpriteRenderData）里的顶点/索引/变换。

    结构（Unity 2022.3 文本序列化）：

    ```
      m_RD:
        m_SubMeshes: - {firstByte, indexCount, …, vertexCount}
        m_IndexBuffer: <hex，16 位索引>
        m_VertexData:
          m_VertexCount: N
          m_Channels: - {stream, offset, format, dimension} × 14
          _typelessdata: <hex，先 stream0 的全部顶点，再 stream1…>
        textureRect: {x, y, width, height}
        uvTransform: {x: ppu, y: 图集内 pivot 像素 x, z: ppu, w: 图集内 pivot 像素 y}
        downscaleMultiplier: 1
    ```

    **uv 不进顶点流**（那一通道是 0），要用 `uvTransform` 现算：
    `u = (x*uvT.x + uvT.y) / 贴图宽`、`v = (y*uvT.z + uvT.w) / 贴图高`（v 自底边算）。
    已与运行时 `Sprite.vertices / uv / triangles` 逐位核对：
    `banshee_skin1` 35/35、`alice_skin1_dl_idle` 111/111 全一致（位置/uv 差 ≤ 5e-6，
    索引个数相同）。
    """
    i = text.find("m_RD:")
    if i < 0:
        return None
    seg = text[i:]
    m = re.search(r"m_VertexCount: (\d+)", seg)
    if not m:
        return None
    n = int(m.group(1))
    ch = []
    for cm in re.finditer(r"- stream: (\d+)\s+offset: (\d+)\s+format: (\d+)"
                          r"\s+dimension: (\d+)", seg):
        ch.append(tuple(int(g) for g in cm.groups()))
    if any(dim > 0 and fmt != 0 for _s, _o, fmt, dim in ch):
        return None                 # 非 float32 的顶点流没实现，回落
    raw = _hex_after(seg, "_typelessdata")
    if not raw or not ch:
        return None
    stride = {}
    for s, off, fmt, dim in ch:
        if dim > 0:
            stride[s] = max(stride.get(s, 0),
                            off + dim * TYPE_SIZE.get(fmt, 4))
    start, pos = {}, 0
    for s in sorted(stride):
        start[s] = pos
        pos += stride[s] * n
    if pos > len(raw):
        return None
    attrs = {}
    for k, (s, off, fmt, dim) in enumerate(ch[:len(_SPRITE_CHANNELS)]):
        if dim <= 0:
            continue
        vals = []
        for v in range(n):
            o = start[s] + off + v * stride[s]
            vals.append([struct.unpack_from("<" + TYPE_FMT.get(fmt, "f"),
                                            raw, o + c * TYPE_SIZE.get(fmt, 4))[0]
                         for c in range(dim)])
        attrs[_SPRITE_CHANNELS[k]] = vals
    ib = _hex_after(seg, "m_IndexBuffer")
    tris = [struct.unpack_from("<H", ib, j)[0]
            for j in range(0, len(ib) - 1, 2)]
    uvtr = re.search(r"uvTransform: \{x: ([-0-9.eE]+), y: ([-0-9.eE]+), "
                     r"z: ([-0-9.eE]+), w: ([-0-9.eE]+)\}", seg)
    dm = re.search(r"downscaleMultiplier: ([-0-9.eE]+)", seg)
    if not attrs.get("position") or not tris or not uvtr:
        return None
    return {
        "positions": attrs["position"],
        "triangles": tris,
        "uvTransform": [float(v) for v in uvtr.groups()],
        "downscaleMultiplier": float(dm.group(1)) if dm else 1.0,
        "vertexCount": n,
    }


def sprite_mesh_from_sprite(sp, tex_size, flip_x=False, flip_y=False):
    """Sprite 资产里的渲染网格 -> 我们产物的 mesh 结构（局部坐标、pivot 在原点）。

    拿不到可读网格时返回 None（调用方依次回落 alpha 轮廓 / 四边形）。
    """
    rm = (sp or {}).get("renderMesh")
    if not rm or not rm.get("positions") or not rm.get("triangles"):
        return None
    # 降采样过的精灵 uvTransform 口径不同，稳妥起见不用（回落轮廓/四边形）
    if abs(float(rm.get("downscaleMultiplier") or 1.0) - 1.0) > 1e-6:
        return None
    tw, th = float(tex_size[0]), float(tex_size[1])
    if tw <= 0 or th <= 0:
        return None
    ppu, cx, ppu_v, cy = [float(v) for v in rm["uvTransform"][:4]]
    pos, uvs = [], []
    for p in rm["positions"]:
        x, y = float(p[0]), float(p[1])
        pos.append((x, y, 0.0))
        # 本链路的 v 以贴图顶行为 0（见 _part_uvs 的说明），资产里的 v 自底边算
        uvs.append(((x * ppu + cx) / tw, 1.0 - (y * ppu_v + cy) / th))
    tris = [int(v) for v in rm["triangles"]]
    if flip_x:
        pos = [(-x, y, z) for x, y, z in pos]
    if flip_y:
        pos = [(x, -y, z) for x, y, z in pos]
    if flip_x != flip_y:
        # 只翻一个轴会反转绕序，跟着反一下（与建四边形那条一致）
        tris = [t for i in range(0, len(tris) - 2, 3)
                for t in (tris[i], tris[i + 2], tris[i + 1])]
    return {"positions": pos, "uvs": uvs, "triangles": tris,
            "bindposes": [], "weights": [], "boneIndexRaw": []}


def mat4_mul(a, b):
    """4x4 行主序矩阵相乘。"""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
    return out


def mat4_vec(m, v):
    x, y, z = v
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def mat4_invert(m):
    """高斯消元求逆（带 3D 平移，2D 场景小矩阵）。"""
    a = [list(m[i * 4:i * 4 + 4]) + ([1.0 if i == j else 0.0 for j in range(4)])
         for i in range(4)]
    for col in range(4):
        piv = max(range(col, 4), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError("矩阵不可逆")
        a[col], a[piv] = a[piv], a[col]
        d = a[col][col]
        a[col] = [x / d for x in a[col]]
        for r in range(4):
            if r == col:
                continue
            f = a[r][col]
            a[r] = [x - f * y for x, y in zip(a[r], a[col])]
    return [a[r][c] for r in range(4) for c in range(4, 8)]


def mat4_invert_tolerant(m, eps=1e-12):
    """容错求逆：遇见奇异方向**不抛异常**，而是把那个方向在逆里置 0。

    为什么要它（2026-10-10）：`2DModel_BR_RoyalArsenal_NS1` 这种 rig 里存在
    **世界矩阵奇异**的节点（某个轴的缩放是 0，或者整块被压扁成平面），
    而 CS 运行时写 `poleVector` / 骨位时要 `set_world` → 需要求父矩阵的逆，
    于是 `mat4_invert` 抛 `ValueError("矩阵不可逆")` 把整条转换打挂。
    Unity 那边遇到同样情况只是"丢掉不可恢复的那个轴"，所以这里也按"丢掉"处理：
    该方向的局部坐标取 0，其余方向照常解 —— 对只用来定位的控制体足够，
    也保证转换不会因为一个退化控制体整条失败。
    """
    a = [list(m[i * 4:i * 4 + 4]) + ([1.0 if i == j else 0.0 for j in range(4)])
         for i in range(4)]
    for col in range(4):
        piv = max(range(col, 4), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < eps:
            for r in range(4):
                a[r][col + 4] = 0.0
            continue
        a[col], a[piv] = a[piv], a[col]
        d = a[col][col]
        a[col] = [x / d for x in a[col]]
        for r in range(4):
            if r == col:
                continue
            f = a[r][col]
            a[r] = [x - f * y for x, y in zip(a[r], a[col])]
    return [a[r][c] for r in range(4) for c in range(4, 8)]
