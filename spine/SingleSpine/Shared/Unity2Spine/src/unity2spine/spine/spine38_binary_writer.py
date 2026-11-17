# -*- coding: utf-8 -*-
"""Spine 3.8 `.skel` 二进制写出器（JSON 模型 -> binary）。

依据 https://github.com/wang606/SpineSkeletonDataConverter 的
`src/SkeletonData38BinaryWriter.cpp` 实现，并与官方 spine-runtimes 3.8 的读取
约定逐条对齐（spine-csharp `SkeletonBinary.cs`、spine-cpp `SkeletonBinary.cpp`）：

- varint / string / stringRef / color / float 的字节序与编码方式一致；
- `nonessential` 判定与 3.8 一致（fps != 30 或有 images/audio -> 额外写
  fps/images/audio、骨骼颜色、mesh 的 edges+width+height 等）；
- mesh 的 `hull` 写 JSON 原值（spine-csharp: `HullLength = hull << 1`），
  `edges`/`width`/`height` 只在 nonessential 时写。

输入模型与 `spine38_binary.read_skeleton_json()`（SpineSkeletonDataConverter
skel->json 的输出）一致，两者可直接互转。

顺序约定（默认与参考实现逐字节一致）：

- 骨骼 / 插槽 / 动画**列表**保持 JSON 顺序（参考实现的 vector 也是这个顺序，
  查看器里"第一条动画"因此仍是主 clip）；
- 皮肤附件、动画内的槽位/骨骼/附件条目按名字排序（参考实现内部用 `std::map`）；
- `--keep-json-order` 可关掉排序、`--sort-animations` 可连动画列表一起排序。

只写 Spine 3.8 数据；不支持 4.x 的 sequence / physics 等字段。

命令行：

    python -m ngui2spine.spine38_binary_writer <in.json> [out.skel] [--verify]
"""

import json
import os
import struct
import sys

from ..spine.spine38_binary import BLEND_NAMES, TRANSFORM_NAMES, read_skeleton_json
from ..spine.spine_out import anim_slots

try:                                     # numpy 只是加速大 deform 数组
    import numpy as _np
except Exception:                        # pragma: no cover - 退化为 struct
    _np = None

CURVE_LINEAR, CURVE_STEPPED, CURVE_BEZIER = 0, 1, 2

ATTACHMENT_TYPES = {
    "region": 0,
    "boundingbox": 1,
    "mesh": 2,
    "linkedmesh": 3,
    "path": 4,
    "point": 5,
    "clipping": 6,
}


def _to_rgba(value, alpha=True):
    """把 `rrggbb` / `rrggbbaa` / `[r,g,b,a]` / dict 统一成 0~255 四元组。"""
    if value is None:
        return [255, 255, 255, 255]
    if isinstance(value, str):
        s = value.lstrip("#").strip()
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) < 6:
            raise ValueError("颜色格式无法识别: %r" % value)
        out = [int(s[i:i + 2], 16) for i in (0, 2, 4)]
        out.append(int(s[6:8], 16) if (alpha and len(s) >= 8) else 255)
        return out
    if isinstance(value, dict):
        def _c(key, default=1.0):
            v = float(value.get(key, default))
            return max(0, min(255, int(round(v * 255 if v <= 1.0 else v))))
        return [_c("r"), _c("g"), _c("b"), _c("a")]
    out = []
    for v in list(value)[:4]:
        f = float(v)
        out.append(max(0, min(255, int(round(f * 255 if f <= 1.0 else f)))))
    while len(out) < 4:
        out.append(255)
    if not alpha:
        out[3] = 255
    return out


class _Writer:
    """与参考实现逐字节对应的写入器。"""

    def __init__(self):
        self.buf = bytearray()
        self.strings = []
        self._index = {}

    # ------------------------------------------------------------- 基础类型
    def byte(self, v):
        self.buf.append(int(v) & 0xFF)

    def sbyte(self, v):
        self.byte(int(v) & 0xFF)

    def boolean(self, v):
        self.byte(1 if v else 0)

    def int32(self, v):
        self.buf += struct.pack(">i", int(v))

    def float32(self, v):
        self.buf += struct.pack(">f", float(v))

    def floats(self, values):
        vals = [float(v) for v in values]
        if not vals:
            return
        if _np is not None:
            self.buf += _np.asarray(vals, dtype=">f4").tobytes()
        else:                                        # pragma: no cover
            self.buf += struct.pack(">%df" % len(vals), *vals)

    def varint(self, value, positive=True):
        v = int(value)
        if not positive:
            v = (v << 1) ^ (v >> 31)
        if v < 0:
            v &= 0xFFFFFFFF
        while v > 0x7F:
            self.byte((v & 0x7F) | 0x80)
            v >>= 7
        self.byte(v & 0x7F)

    def string(self, s):
        if s is None:
            self.byte(0)
            return
        raw = str(s).encode("utf-8")
        self.varint(len(raw) + 1, True)
        self.buf += raw

    def color(self, value, alpha=True):
        r, g, b, a = _to_rgba(value, alpha)
        self.byte(r)
        self.byte(g)
        self.byte(b)
        if alpha:
            self.byte(a)

    # ------------------------------------------------------------- 字符串表
    def set_strings(self, strings):
        self.strings = list(strings)
        self._index = {s: i for i, s in enumerate(self.strings)}

    def string_ref(self, s):
        if s is None or s == "":
            self.varint(0, True)
            return
        idx = self._index.get(s)
        if idx is None:
            raise ValueError("字符串引用不在字符串表中: %r（写出器内部错误）" % s)
        self.varint(idx + 1, True)


def _ordered(d, sort_keys):
    """按 key 排序（参考实现内部是 std::map）或保持插入顺序。"""
    if not d:
        return []
    if isinstance(d, dict):
        items = list(d.items())
        if sort_keys:
            items.sort(key=lambda kv: kv[0])
        return items
    return list(enumerate(d))


# ------------------------------------------------------------------ 字符串表
def collect_strings(model):
    """与参考实现 `writeBinaryData()` 收集的字符串表一致（排序后写出）。"""
    ss = set()
    for slot in model.get("slots") or []:
        if (slot or {}).get("attachment"):
            ss.add(slot["attachment"])
    for skin in model.get("skins") or []:
        name = (skin or {}).get("name") or "default"
        if name != "default":
            ss.add(name)
        for _slot, mp in ((skin or {}).get("attachments") or {}).items():
            for att_name, att in (mp or {}).items():
                att = att or {}
                ss.add(att_name)
                real = att.get("name") or att_name
                if real != att_name:
                    ss.add(real)
                path = att.get("path") or real
                if path != real:
                    ss.add(path)
    events = model.get("events") or {}
    if isinstance(events, dict):
        ss.update(events.keys())
    for _aname, anim in (model.get("animations") or {}).items():
        anim = anim or {}
        for _slot, tl in anim_slots(anim).items():
            for fr in ((tl or {}).get("attachment") or []):
                if fr.get("name"):
                    ss.add(fr["name"])
        for _skin, slots in (anim.get("deform") or {}).items():
            for _slot, atts in (slots or {}).items():
                ss.update((atts or {}).keys())
    return sorted(ss)


# -------------------------------------------------------------------- 时间线
def _write_curve(w, frame):
    curve = frame.get("curve")
    if curve is None:
        w.byte(CURVE_LINEAR)
    elif curve == "stepped":
        w.byte(CURVE_STEPPED)
    else:
        w.byte(CURVE_BEZIER)
        w.float32(curve)
        w.float32(frame.get("c2", 0.0))
        w.float32(frame.get("c3", 1.0))
        w.float32(frame.get("c4", 1.0))


def _write_timeline(w, frames, value_num, key1, key2=None, default=0.0):
    n = len(frames)
    for i, fr in enumerate(frames):
        w.float32(fr.get("time", 0.0))
        w.float32(fr.get(key1, default))
        if value_num > 1:
            w.float32(fr.get(key2, default))
        if i < n - 1:
            _write_curve(w, fr)


def _write_short_array(w, values):
    vals = [int(v) for v in (values or [])]
    w.varint(len(vals), True)
    for v in vals:
        w.byte((v >> 8) & 0xFF)
        w.byte(v & 0xFF)


def _write_vertices(w, vertices, vertex_count):
    """weighted = [boneCount, bone, x, y, weight, ...]（判定同参考实现）。"""
    verts = [float(v) for v in (vertices or [])]
    weighted = len(verts) != vertex_count * 2
    w.boolean(weighted)
    if not weighted:
        w.floats(verts)
        return
    i = 0
    while i < len(verts):
        bone_count = int(verts[i])
        i += 1
        w.varint(bone_count, True)
        for _ in range(bone_count):
            w.varint(int(verts[i]), True)
            w.float32(verts[i + 1])
            w.float32(verts[i + 2])
            w.float32(verts[i + 3])
            i += 4


# ---------------------------------------------------------------------- 皮肤
def _write_attachment(w, att_name, att, nonessential):
    att = att or {}
    name = att.get("name") or att_name
    path = att.get("path") or name
    kind = att.get("type") or "region"
    if kind not in ATTACHMENT_TYPES:
        raise ValueError("未知附件类型: %r" % kind)
    w.string_ref(att_name)
    w.string_ref(name if name != att_name else None)
    w.byte(ATTACHMENT_TYPES[kind])

    if kind in ("region", "mesh", "linkedmesh"):
        w.string_ref(path if path != name else None)

    if kind == "region":
        w.float32(att.get("rotation", 0.0))
        w.float32(att.get("x", 0.0))
        w.float32(att.get("y", 0.0))
        w.float32(att.get("scaleX", 1.0))
        w.float32(att.get("scaleY", 1.0))
        w.float32(att.get("width", 32.0))
        w.float32(att.get("height", 32.0))
        w.color(att.get("color"))
    elif kind == "boundingbox":
        _write_vertices(w, att.get("vertices"), int(att.get("vertexCount") or 0))
        if nonessential:
            w.color(att.get("color"))
    elif kind == "mesh":
        w.color(att.get("color"))
        uvs = att.get("uvs") or []
        count = len(uvs) // 2
        w.varint(count, True)
        w.floats(uvs)
        _write_short_array(w, att.get("triangles"))
        _write_vertices(w, att.get("vertices"), count)
        w.varint(int(att.get("hull") or 0), True)
        if nonessential:
            _write_short_array(w, att.get("edges"))
            w.float32(att.get("width", 0.0))
            w.float32(att.get("height", 0.0))
    elif kind == "linkedmesh":
        w.color(att.get("color"))
        w.string_ref(att.get("skin"))
        w.string_ref(att.get("parent"))
        deform = att.get("deform", True)
        w.boolean(not (deform is False or deform == 0))
        if nonessential:
            w.float32(att.get("width", 0.0))
            w.float32(att.get("height", 0.0))
    elif kind == "path":
        w.boolean(att.get("closed", False))
        w.boolean(att.get("constantSpeed", True))
        _write_vertices(w, att.get("vertices"), int(att.get("vertexCount") or 0))
        w.floats(att.get("lengths") or [])
        if nonessential:
            w.color(att.get("color"))
    elif kind == "point":
        w.float32(att.get("rotation", 0.0))
        w.float32(att.get("x", 0.0))
        w.float32(att.get("y", 0.0))
        if nonessential:
            w.color(att.get("color"))
    else:                                            # clipping
        w.varint(int(att.get("endIndex", -1)), True)
        _write_vertices(w, att.get("vertices"), int(att.get("vertexCount") or 0))
        if nonessential:
            w.color(att.get("color"))


def _write_skin(w, skin, ctx, default_skin, nonessential, sort_keys):
    skin = skin or {}
    attachments = skin.get("attachments") or {}
    if default_skin:
        w.varint(len(attachments), True)
    else:
        w.string_ref(skin.get("name"))
        for key, table in (("bones", "boneIndex"), ("ik", "ikIndex"),
                           ("transform", "transformIndex"),
                           ("path", "pathIndex")):
            names = skin.get(key) or []
            w.varint(len(names), True)
            for nm in names:
                idx = ctx[table].get(nm)
                if idx is None:
                    raise ValueError("皮肤引用了不存在的 %s: %r" % (key, nm))
                w.varint(idx, True)
        w.varint(len(attachments), True)
    for slot_name, mp in _ordered(attachments, sort_keys):
        idx = ctx["slotIndex"].get(slot_name)
        if idx is None:
            raise ValueError("皮肤引用了不存在的插槽: %r" % slot_name)
        mp = mp or {}
        w.varint(idx, True)
        w.varint(len(mp), True)
        for att_name, att in _ordered(mp, sort_keys):
            _write_attachment(w, att_name, att, nonessential)


# ---------------------------------------------------------------------- 动画
def _write_animation(w, name, anim, ctx, sort_keys):
    anim = anim or {}
    w.string(name)

    slots = anim_slots(anim)
    w.varint(len(slots), True)
    for slot_name, tl in _ordered(slots, sort_keys):
        idx = ctx["slotIndex"].get(slot_name)
        if idx is None:
            raise ValueError("动画 %r 引用了不存在的插槽: %r" % (name, slot_name))
        tl = tl or {}
        subs = [(k, tl[k]) for k in ("attachment", "color", "rgba",
                                     "twoColor", "rgba2") if tl.get(k)]
        w.varint(idx, True)
        w.varint(len(subs), True)
        for key, frames in subs:
            if key == "attachment":
                w.byte(0)
                w.varint(len(frames), True)
                for fr in frames:
                    w.float32(fr.get("time", 0.0))
                    w.string_ref(fr.get("name"))
            elif key in ("color", "rgba"):
                w.byte(1)
                w.varint(len(frames), True)
                for i, fr in enumerate(frames):
                    w.float32(fr.get("time", 0.0))
                    w.color(fr.get("color") or fr.get("light"))
                    if i < len(frames) - 1:
                        _write_curve(w, fr)
            else:                                    # twoColor / rgba2
                w.byte(2)
                w.varint(len(frames), True)
                for i, fr in enumerate(frames):
                    w.float32(fr.get("time", 0.0))
                    w.color(fr.get("color") or fr.get("light"))
                    r, g, b, a = _to_rgba(fr.get("color2") or fr.get("dark"),
                                          alpha=False)
                    w.byte(a)
                    w.byte(r)
                    w.byte(g)
                    w.byte(b)
                    if i < len(frames) - 1:
                        _write_curve(w, fr)

    bones = anim.get("bones") or {}
    w.varint(len(bones), True)
    for bone_name, tl in _ordered(bones, sort_keys):
        idx = ctx["boneIndex"].get(bone_name)
        if idx is None:
            raise ValueError("动画 %r 引用了不存在的骨骼: %r" % (name, bone_name))
        tl = tl or {}
        # 子时间线顺序与参考实现的 std::map 一致（按名字）：rotate/scale/
        # shear/translate；条目本身带类型字节，顺序不影响语义。
        subs = [(k, tl[k]) for k in ("rotate", "scale", "shear", "translate")
                if tl.get(k)]
        w.varint(idx, True)
        w.varint(len(subs), True)
        for key, frames in subs:
            if key == "rotate":
                w.byte(0)
                w.varint(len(frames), True)
                _write_timeline(w, frames, 1, "angle")
            elif key in ("translate", "shear"):
                w.byte(1 if key == "translate" else 3)
                w.varint(len(frames), True)
                _write_timeline(w, frames, 2, "x", "y", 0.0)
            else:
                w.byte(2)
                w.varint(len(frames), True)
                _write_timeline(w, frames, 2, "x", "y", 1.0)

    ik = anim.get("ik") or {}
    w.varint(len(ik), True)
    for ik_name, frames in _ordered(ik, sort_keys):
        idx = ctx["ikIndex"].get(ik_name)
        if idx is None:
            raise ValueError("动画 %r 引用了不存在的 IK 约束: %r" % (name, ik_name))
        w.varint(idx, True)
        w.varint(len(frames), True)
        for i, fr in enumerate(frames):
            w.float32(fr.get("time", 0.0))
            w.float32(fr.get("mix", 1.0))
            w.float32(fr.get("softness", 0.0))
            bend = fr.get("bendDirection", 1)
            w.sbyte(1 if float(bend) >= 0 else -1)
            w.boolean(fr.get("compress", False))
            w.boolean(fr.get("stretch", False))
            if i < len(frames) - 1:
                _write_curve(w, fr)

    tf = anim.get("transform") or {}
    w.varint(len(tf), True)
    for tf_name, frames in _ordered(tf, sort_keys):
        idx = ctx["transformIndex"].get(tf_name)
        if idx is None:
            raise ValueError("动画 %r 引用了不存在的变换约束: %r" % (name, tf_name))
        w.varint(idx, True)
        w.varint(len(frames), True)
        for i, fr in enumerate(frames):
            w.float32(fr.get("time", 0.0))
            w.float32(fr.get("rotateMix", 1.0))
            w.float32(fr.get("translateMix", 1.0))
            w.float32(fr.get("scaleMix", 1.0))
            w.float32(fr.get("shearMix", 1.0))
            if i < len(frames) - 1:
                _write_curve(w, fr)

    paths = anim.get("path") or {}
    w.varint(len(paths), True)
    for path_name, sub in _ordered(paths, sort_keys):
        idx = ctx["pathIndex"].get(path_name)
        if idx is None:
            raise ValueError("动画 %r 引用了不存在的路径约束: %r" % (name, path_name))
        sub = sub or {}
        subs = [(k, sub[k]) for k in ("mix", "position", "spacing")
                if sub.get(k)]
        w.varint(idx, True)
        w.varint(len(subs), True)
        for key, frames in subs:
            w.sbyte({"position": 0, "spacing": 1, "mix": 2}[key])
            w.varint(len(frames), True)
            if key == "mix":
                _write_timeline(w, frames, 2, "rotateMix", "translateMix", 1.0)
            else:
                _write_timeline(w, frames, 1, key)

    deform = anim.get("deform") or {}
    w.varint(len(deform), True)
    for skin_name, slots_map in _ordered(deform, sort_keys):
        skin_idx = ctx["skinIndex"].get(skin_name or "default")
        if skin_idx is None:
            raise ValueError("动画 %r 的 deform 引用了不存在的皮肤: %r"
                             % (name, skin_name))
        w.varint(skin_idx, True)
        slots_map = slots_map or {}
        w.varint(len(slots_map), True)
        for slot_name, atts in _ordered(slots_map, sort_keys):
            slot_idx = ctx["slotIndex"].get(slot_name)
            if slot_idx is None:
                raise ValueError("动画 %r 的 deform 引用了不存在的插槽: %r"
                                 % (name, slot_name))
            atts = atts or {}
            w.varint(slot_idx, True)
            w.varint(len(atts), True)
            for att_name, frames in _ordered(atts, sort_keys):
                w.string_ref(att_name)
                w.varint(len(frames), True)
                for i, fr in enumerate(frames):
                    w.float32(fr.get("time", 0.0))
                    verts = fr.get("vertices") or []
                    w.varint(len(verts), True)
                    if verts:
                        w.varint(int(fr.get("offset") or 0), True)
                        w.floats(verts)
                    if i < len(frames) - 1:
                        _write_curve(w, fr)

    frames = anim.get("drawOrder") or anim.get("draworder") or []
    w.varint(len(frames), True)
    for fr in frames:
        w.float32(fr.get("time", 0.0))
        offsets = fr.get("offsets") or []
        w.varint(len(offsets), True)
        for off in offsets:
            slot_idx = ctx["slotIndex"].get(off.get("slot"))
            if slot_idx is None:
                raise ValueError("动画 %r 的 drawOrder 引用了不存在的插槽: %r"
                                 % (name, off.get("slot")))
            w.varint(slot_idx, True)
            w.varint(int(off.get("offset") or 0), True)

    frames = anim.get("events") or []
    w.varint(len(frames), True)
    events = ctx["events"]
    for fr in frames:
        ev = events.get(fr.get("name")) or {}
        w.float32(fr.get("time", 0.0))
        w.varint(ctx["eventIndex"][fr.get("name")], True)
        w.varint(int(fr.get("int", ev.get("int", 0))), False)
        w.float32(fr.get("float", ev.get("float", 0.0)))
        text = fr.get("string", ev.get("string") or "") or ""
        base = ev.get("string") or ""
        if text != base:
            w.boolean(True)
            w.string(text)
        else:
            w.boolean(False)
        if ev.get("audio"):
            w.float32(fr.get("volume", ev.get("volume", 1.0)))
            w.float32(fr.get("balance", ev.get("balance", 0.0)))


# ---------------------------------------------------------------------- 入口
def build_binary(model, sort_keys=True, sort_animations=False):
    """JSON 模型 dict -> `.skel` 字节串。

    sort_keys       : 皮肤附件 / 动画内条目是否按名字排序（默认 True，与
                      SpineSkeletonDataConverter 的 std::map 写出顺序一致）
    sort_animations : 动画列表是否也按名字排序（默认 False = JSON 顺序）
    """
    sk = model.get("skeleton") or {}
    bones = model.get("bones") or []
    slots = model.get("slots") or []
    skins = model.get("skins") or []
    ik = model.get("ik") or []
    transform = model.get("transform") or []
    paths = model.get("path") or []
    events = model.get("events") or {}
    if not isinstance(events, dict):                 # 兼容 list 形式
        events = {e.get("name"): e for e in events}

    ctx = {
        "boneIndex": {b.get("name"): i for i, b in enumerate(bones)},
        "slotIndex": {s.get("name"): i for i, s in enumerate(slots)},
        "ikIndex": {c.get("name"): i for i, c in enumerate(ik)},
        "transformIndex": {c.get("name"): i for i, c in enumerate(transform)},
        "pathIndex": {c.get("name"): i for i, c in enumerate(paths)},
        "skinIndex": {s.get("name") or "default": i for i, s in enumerate(skins)},
        "events": events,
        "eventIndex": {},
    }
    event_names = list(events.keys())
    if sort_animations:
        event_names.sort()
    ctx["eventIndex"] = {nm: i for i, nm in enumerate(event_names)}

    images = sk.get("images")
    audio = sk.get("audio")
    fps = float(sk.get("fps", 30.0))
    nonessential = (fps != 30.0) or (images is not None) or (audio is not None)

    w = _Writer()
    w.string(sk.get("hash"))
    w.string(sk.get("spine") or "3.8.99")
    w.float32(sk.get("x", 0.0))
    w.float32(sk.get("y", 0.0))
    w.float32(sk.get("width", 0.0))
    w.float32(sk.get("height", 0.0))
    w.boolean(nonessential)
    if nonessential:
        w.float32(fps)
        w.string(images)
        w.string(audio)

    w.set_strings(collect_strings(model))
    w.varint(len(w.strings), True)
    for s in w.strings:
        w.string(s)

    # --- 骨骼
    w.varint(len(bones), True)
    for i, b in enumerate(bones):
        b = b or {}
        w.string(b.get("name"))
        if i != 0:
            parent = b.get("parent")
            if parent is None:
                # 3.8 二进制对非 0 号骨骼总会读一个父索引；缺父时退化为 0 号。
                print("[skel] 警告：骨骼 %r 没有 parent，按 0 号骨骼写出"
                      % b.get("name"), file=sys.stderr)
                w.varint(0, True)
            else:
                idx = ctx["boneIndex"].get(parent)
                if idx is None:
                    raise ValueError("骨骼 %r 的 parent 不存在: %r"
                                     % (b.get("name"), parent))
                w.varint(idx, True)
        w.float32(b.get("rotation", 0.0))
        w.float32(b.get("x", 0.0))
        w.float32(b.get("y", 0.0))
        w.float32(b.get("scaleX", 1.0))
        w.float32(b.get("scaleY", 1.0))
        w.float32(b.get("shearX", 0.0))
        w.float32(b.get("shearY", 0.0))
        w.float32(b.get("length", 0.0))
        mode = b.get("transform") or "normal"
        if mode not in TRANSFORM_NAMES:
            raise ValueError("未知骨骼 transform 模式: %r" % mode)
        w.varint(TRANSFORM_NAMES.index(mode), True)
        w.boolean(b.get("skin", False))
        if nonessential:
            w.color(b.get("color") or "9b9b9bff")

    # --- 插槽
    w.varint(len(slots), True)
    for s in slots:
        s = s or {}
        w.string(s.get("name"))
        idx = ctx["boneIndex"].get(s.get("bone"))
        if idx is None:
            raise ValueError("插槽 %r 的骨骼不存在: %r"
                             % (s.get("name"), s.get("bone")))
        w.varint(idx, True)
        w.color(s.get("color"))
        # 二进制里 slot 的 darkColor 始终是 4 字节（缺省 alpha=255）；
        # 3.8 JSON 的 "dark" 只有 6 位十六进制，两边语义一致。
        w.color(s.get("darkColor"))
        w.string_ref(s.get("attachment"))
        blend = s.get("blend") or s.get("blendMode") or "normal"
        if blend not in BLEND_NAMES:
            raise ValueError("未知混合模式: %r" % blend)
        w.varint(BLEND_NAMES.index(blend), True)

    # --- IK 约束
    w.varint(len(ik), True)
    for c in ik:
        c = c or {}
        w.string(c.get("name"))
        w.varint(c.get("order", 0), True)
        w.boolean(c.get("skin", False))
        names = c.get("bones") or []
        w.varint(len(names), True)
        for nm in names:
            w.varint(ctx["boneIndex"][nm], True)
        w.varint(ctx["boneIndex"][c.get("target")], True)
        w.float32(c.get("mix", 1.0))
        w.float32(c.get("softness", 0.0))
        w.sbyte(1 if float(c.get("bendDirection", 1)) >= 0 else -1)
        w.boolean(c.get("compress", False))
        w.boolean(c.get("stretch", False))
        w.boolean(c.get("uniform", False))

    # --- 变换约束
    w.varint(len(transform), True)
    for c in transform:
        c = c or {}
        w.string(c.get("name"))
        w.varint(c.get("order", 0), True)
        w.boolean(c.get("skin", False))
        names = c.get("bones") or []
        w.varint(len(names), True)
        for nm in names:
            w.varint(ctx["boneIndex"][nm], True)
        w.varint(ctx["boneIndex"][c.get("target")], True)
        w.boolean(c.get("local", False))
        w.boolean(c.get("relative", False))
        w.float32(c.get("rotation", 0.0))
        w.float32(c.get("x", 0.0))
        w.float32(c.get("y", 0.0))
        w.float32(c.get("scaleX", 0.0))
        w.float32(c.get("scaleY", 0.0))
        w.float32(c.get("shearY", 0.0))
        w.float32(c.get("rotateMix", 1.0))
        w.float32(c.get("translateMix", 1.0))
        w.float32(c.get("scaleMix", 1.0))
        w.float32(c.get("shearMix", 1.0))

    # --- 路径约束
    w.varint(len(paths), True)
    for c in paths:
        c = c or {}
        w.string(c.get("name"))
        w.varint(c.get("order", 0), True)
        w.boolean(c.get("skin", False))
        names = c.get("bones") or []
        w.varint(len(names), True)
        for nm in names:
            w.varint(ctx["boneIndex"][nm], True)
        w.varint(ctx["slotIndex"][c.get("target")], True)
        w.varint({"fixed": 0, "percent": 1}.get(c.get("positionMode"), 1), True)
        w.varint({"length": 0, "fixed": 1, "percent": 2}.get(
            c.get("spacingMode"), 0), True)
        w.varint({"tangent": 0, "chain": 1, "chainScale": 2}.get(
            c.get("rotateMode"), 0), True)
        w.float32(c.get("rotation", 0.0))
        w.float32(c.get("position", 0.0))
        w.float32(c.get("spacing", 0.0))
        w.float32(c.get("rotateMix", 1.0))
        w.float32(c.get("translateMix", 1.0))

    # --- 皮肤（default 先写，其余按数量写）
    default_skin = None
    others = []
    for s in skins:
        if (s or {}).get("name") in (None, "default") and default_skin is None:
            default_skin = s
        else:
            others.append(s)
    if default_skin is None:
        w.varint(0, True)
    else:
        _write_skin(w, default_skin, ctx, True, nonessential, sort_keys)
    w.varint(len(others), True)
    for s in others:
        _write_skin(w, s, ctx, False, nonessential, sort_keys)

    # --- 事件
    w.varint(len(event_names), True)
    for nm in event_names:
        ev = events.get(nm) or {}
        w.string_ref(nm)
        w.varint(int(ev.get("int", 0)), False)
        w.float32(ev.get("float", 0.0))
        w.string(ev.get("string"))
        w.string(ev.get("audio"))
        if ev.get("audio"):
            w.float32(ev.get("volume", 1.0))
            w.float32(ev.get("balance", 0.0))

    # --- 动画
    anims = model.get("animations") or {}
    w.varint(len(anims), True)
    for aname, anim in _ordered(anims, sort_animations):
        _write_animation(w, aname, anim, ctx, sort_keys)
    return bytes(w.buf)


def write_skeleton_binary(model, path=None, sort_keys=True,
                          sort_animations=False):
    """JSON 模型 dict -> 写 `.skel`（给了 path 就落盘），返回字节串。"""
    data = build_binary(model, sort_keys=sort_keys,
                        sort_animations=sort_animations)
    if path:
        with open(path, "wb") as fp:
            fp.write(data)
    return data


def convert_file(json_path, skel_path=None, sort_keys=True,
                 sort_animations=False, verify=False):
    """把 Spine JSON 文件转成 `.skel`；verify 时用本项目读回器校验结构。"""
    with open(json_path, encoding="utf-8") as fp:
        model = json.load(fp)
    if not skel_path:
        skel_path = os.path.splitext(json_path)[0] + ".skel"
    data = write_skeleton_binary(model, skel_path, sort_keys=sort_keys,
                                 sort_animations=sort_animations)
    if verify:
        back = read_skeleton_json(skel_path)
        errs = compare_models(model, back)
        if errs:
            raise RuntimeError("读回校验失败：\n  " + "\n  ".join(errs[:10]))
    return skel_path, len(data)


_BONE_DEFAULTS = {"rotation": 0.0, "x": 0.0, "y": 0.0, "scaleX": 1.0,
                  "scaleY": 1.0, "shearX": 0.0, "shearY": 0.0, "length": 0.0}
_REGION_DEFAULTS = {"x": 0.0, "y": 0.0, "rotation": 0.0, "scaleX": 1.0,
                    "scaleY": 1.0, "width": 32.0, "height": 32.0}


def _norm_num(v):
    """比较用：整数统一成 float，方便按容差比较（float32 读回值有 ~1e-6 误差）。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def _canon_attachment(att, name):
    """把一个附件规范成"补齐缺省值"的可比较结构。"""
    att = att or {}
    kind = att.get("type") or "region"
    real = att.get("name") or name
    out = {"type": kind, "name": real, "path": att.get("path") or real}
    if kind == "region":
        out.update({k: att.get(k, d) for k, d in _REGION_DEFAULTS.items()})
    elif kind == "mesh":
        out.update({"width": att.get("width", 32.0),
                    "height": att.get("height", 32.0),
                    "hull": att.get("hull", 0),
                    "edges": list(att.get("edges") or []),
                    "triangles": list(att.get("triangles") or []),
                    "uvs": list(att.get("uvs") or []),
                    "vertices": list(att.get("vertices") or [])})
    elif kind == "linkedmesh":
        out.update({"width": att.get("width", 32.0),
                    "height": att.get("height", 32.0),
                    "skin": att.get("skin"), "parent": att.get("parent"),
                    "deform": att.get("deform", True)})
    elif kind == "boundingbox":
        out.update({"vertexCount": att.get("vertexCount", 0),
                    "vertices": list(att.get("vertices") or [])})
    elif kind == "path":
        out.update({"vertexCount": att.get("vertexCount", 0),
                    "closed": att.get("closed", False),
                    "constantSpeed": att.get("constantSpeed", True),
                    "vertices": list(att.get("vertices") or []),
                    "lengths": list(att.get("lengths") or [])})
    elif kind == "point":
        out.update({"x": att.get("x", 0.0), "y": att.get("y", 0.0),
                    "rotation": att.get("rotation", 0.0)})
    else:                                            # clipping
        out.update({"vertexCount": att.get("vertexCount", 0),
                    "endSlot": att.get("endSlot") or att.get("end"),
                    "vertices": list(att.get("vertices") or [])})
    out["color"] = att.get("color") or "ffffffff"
    return {k: _norm_num(v) for k, v in out.items()}


def _canon_frame(fr):
    """规范一帧：0 / null 等"省略即默认"的键在两边都去掉，只留 time。"""
    out = {}
    for k, v in (fr or {}).items():
        if k == "time":
            out["time"] = _norm_num(v)
            continue
        if v is None:
            continue
        if isinstance(v, list):
            out[k] = [_norm_num(x) for x in v]
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0:
            continue
        out[k] = _norm_num(v)
    out.setdefault("time", 0.0)
    return out


def _canon_model(model):
    """规范成可比较结构（补缺省值、浮点取整、时间线按名归并）。"""
    out = {"bones": [], "slots": [], "skins": {}, "animations": {}}
    for b in model.get("bones") or []:
        b = b or {}
        item = {"name": b.get("name"), "parent": b.get("parent")}
        item.update({k: _norm_num(b.get(k, d))
                     for k, d in _BONE_DEFAULTS.items()})
        item["transform"] = b.get("transform") or "normal"
        item["color"] = b.get("color") or "9b9b9bff"
        out["bones"].append(item)
    for s in model.get("slots") or []:
        s = s or {}
        out["slots"].append({
            "name": s.get("name"), "bone": s.get("bone"),
            "attachment": s.get("attachment"),
            "blend": s.get("blend") or s.get("blendMode") or "normal",
            "color": s.get("color") or "ffffffff",
            "darkColor": s.get("darkColor"),
        })
    for skin in model.get("skins") or []:
        skin = skin or {}
        name = skin.get("name") or "default"
        slots = {}
        for slot_name, mp in (skin.get("attachments") or {}).items():
            slots[slot_name] = {att_name: _canon_attachment(att, att_name)
                                for att_name, att in (mp or {}).items()}
        out["skins"][name] = {"bones": list(skin.get("bones") or []),
                              "ik": list(skin.get("ik") or []),
                              "transform": list(skin.get("transform") or []),
                              "path": list(skin.get("path") or []),
                              "attachments": slots}
    for aname, anim in (model.get("animations") or {}).items():
        anim = anim or {}
        slots = {}
        for slot_name, tl in anim_slots(anim).items():
            tl = tl or {}
            slots[slot_name] = {key: [_canon_frame(f) for f in tl[key]]
                                for key in ("attachment", "color", "twoColor",
                                            "rgba", "rgba2") if tl.get(key)}
        bones = {}
        for bone_name, tl in (anim.get("bones") or {}).items():
            tl = tl or {}
            bones[bone_name] = {key: [_canon_frame(f) for f in tl[key]]
                                for key in ("rotate", "translate", "scale",
                                            "shear") if tl.get(key)}
        deform = {}
        for skin_name, smp in (anim.get("deform") or {}).items():
            deform[skin_name] = {
                slot_name: {att: [_canon_frame(f) for f in frames]
                            for att, frames in (amp or {}).items()}
                for slot_name, amp in (smp or {}).items()}
        out["animations"][aname] = {"slots": slots, "bones": bones,
                                    "deform": deform}
    return out


def compare_models(a, b, path="", tol=2e-3, rel=1e-5):
    """比较两个模型（一个来自 JSON，一个由读回器解出）是否等价。

    先补齐缺省值再逐字段比较；浮点用容差（默认 2e-3 绝对 + 1e-5 相对，
    float32 读回误差远小于此）。返回差异描述列表。
    """
    ca, cb = _canon_model(a), _canon_model(b)
    errs = []

    def num_eq(x, y):
        return abs(x - y) <= max(tol, rel * max(abs(x), abs(y)))

    def walk(p, x, y):
        if len(errs) > 30:
            return
        if isinstance(x, (int, float)) and not isinstance(x, bool) and \
                isinstance(y, (int, float)) and not isinstance(y, bool):
            if not num_eq(float(x), float(y)):
                errs.append("%s 值 %r -> %r" % (p, x, y))
            return
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                if k not in x:
                    errs.append("%s.%s 多出 %r" % (p, k, y[k]))
                elif k not in y:
                    errs.append("%s.%s 缺失（应为 %r）" % (p, k, x[k]))
                else:
                    walk("%s.%s" % (p, k), x[k], y[k])
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                errs.append("%s 长度 %d -> %d" % (p, len(x), len(y)))
                return
            for i, (xi, yi) in enumerate(zip(x, y)):
                walk("%s[%d]" % (p, i), xi, yi)
        elif x != y:
            errs.append("%s 值 %r -> %r" % (p, x, y))

    walk(path or "root", ca, cb)
    return errs


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Spine JSON -> Spine 3.8 .skel（binary）")
    ap.add_argument("json", help="输入 Spine JSON")
    ap.add_argument("skel", nargs="?", help="输出 .skel（默认同名）")
    ap.add_argument("--verify", action="store_true",
                    help="写完后用读回器解析一遍并比对结构")
    ap.add_argument("--keep-json-order", action="store_true",
                    help="皮肤附件 / 动画内条目也保持 JSON 顺序（默认按名字排序，"
                         "与 SpineSkeletonDataConverter 一致）")
    ap.add_argument("--sort-animations", action="store_true",
                    help="动画列表也按名字排序（默认保持 JSON 顺序）")
    a = ap.parse_args(argv)
    out, size = convert_file(a.json, a.skel,
                             sort_keys=not a.keep_json_order,
                             sort_animations=a.sort_animations,
                             verify=a.verify)
    print("%s  (%.1f MB)" % (out, size / 1048576.0))
    return out


if __name__ == "__main__":
    main()
