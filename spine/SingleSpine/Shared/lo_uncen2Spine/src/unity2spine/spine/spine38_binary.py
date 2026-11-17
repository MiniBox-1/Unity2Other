# -*- coding: utf-8 -*-
"""Spine 3.8 `.skel` 二进制读取器（仅读取，不写文件）。

依据官方 spine-cpp 3.8 SkeletonBinary.cpp 实现。输出与
SpineSkeletonDataConverter skel->json 兼容的 JSON 模型（缩放均取 1，
坐标保持源数据原始数值）。
"""

import json
import math
import os
import struct


def _fnum(v, precision=6):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return 0
    if isinstance(v, float):
        r = round(v, precision)
        if r == int(r):
            return float(int(r))
        return r
    return v


class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def _b(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def varint(self, positive=True):
        b = self._b()
        value = b & 0x7F
        if b & 0x80:
            b = self._b()
            value |= (b & 0x7F) << 7
            if b & 0x80:
                b = self._b()
                value |= (b & 0x7F) << 14
                if b & 0x80:
                    b = self._b()
                    value |= (b & 0x7F) << 21
                    if b & 0x80:
                        value |= (self._b() & 0x7F) << 28
        if not positive:
            value = ((value >> 1) ^ -(value & 1))
        return value

    def string(self):
        n = self.varint(True)
        if n == 0:
            return ""
        s = self.d[self.p:self.p + n - 1]
        self.p += n - 1
        return s.decode("utf-8", errors="replace")

    def int32(self):
        v = struct.unpack(">i", self.d[self.p:self.p + 4])[0]
        self.p += 4
        return v

    def uint32(self):
        v = struct.unpack(">I", self.d[self.p:self.p + 4])[0]
        self.p += 4
        return v

    def float32(self):
        v = struct.unpack(">f", self.d[self.p:self.p + 4])[0]
        self.p += 4
        return v

    def bool(self):
        return self._b() != 0

    def sbyte(self):
        v = self._b()
        return v - 256 if v >= 128 else v

    def color4(self):
        return [self._b(), self._b(), self._b(), self._b()]

    def u16(self):
        v = struct.unpack(">H", self.d[self.p:self.p + 2])[0]
        self.p += 2
        return v


def _hex4(rgba):
    return "%02x%02x%02x%02x" % tuple(rgba)


TRANSFORM_NAMES = ("normal", "onlyTranslation", "noRotationOrReflection",
                   "noScale", "noScaleOrReflection")
BLEND_NAMES = ("normal", "additive", "multiply", "screen")


def read_skeleton_json(skel_path):
    """把 .skel/.skel.bytes 读成 converter 风格 JSON dict。"""
    data = open(skel_path, "rb").read()
    r = Reader(data)
    model = _read(r)
    return model


def _read(r):
    _trace = os.environ.get("SPINE_TRACE")

    def tr(msg):
        if _trace:
            print("TRACE %5d %s" % (r.p, msg), flush=True)

    hashv = r.string()
    version = r.string()
    if version == "3.8.75":
        raise RuntimeError("Unsupported skeleton data, please export with a newer version of Spine.")
    x = r.float32()
    y = r.float32()
    w = r.float32()
    h = r.float32()
    nonessential = r.bool()
    fps = None
    images_path = ""
    audio_path = ""
    if nonessential:
        fps = r.float32()
        images_path = r.string()
        audio_path = r.string()

    strings = [r.string() for _ in range(r.varint(True))]
    tr("strings=%d" % len(strings))

    def sref():
        i = r.varint(True)
        return strings[i - 1] if i > 0 else ""

    # ---------------- bones
    bones = []
    for i in range(r.varint(True)):
        name = r.string()
        parent = None
        if i > 0:
            parent = bones[r.varint(True)]["name"]
        b = {"name": name}
        rotation = r.float32()
        bx = r.float32()
        by = r.float32()
        sx = r.float32()
        sy = r.float32()
        shearx = r.float32()
        sheary = r.float32()
        length = r.float32()
        tm = r.varint(True)
        r.bool()  # skinRequired
        if nonessential:
            b["color"] = _hex4(r.color4())
        if parent:
            b["parent"] = parent
        if rotation:
            b["rotation"] = _fnum(rotation)
        if bx:
            b["x"] = _fnum(bx)
        if by:
            b["y"] = _fnum(by)
        if sx != 1:
            b["scaleX"] = _fnum(sx)
        if sy != 1:
            b["scaleY"] = _fnum(sy)
        if shearx:
            b["shearX"] = _fnum(shearx)
        if sheary:
            b["shearY"] = _fnum(sheary)
        if length:
            b["length"] = _fnum(length)
        if tm:
            b["transform"] = TRANSFORM_NAMES[tm] if tm < len(TRANSFORM_NAMES) else "normal"
        bones.append(b)
    tr("bones=%d" % len(bones))

    # ---------------- slots
    slots = []
    for _ in range(r.varint(True)):
        name = r.string()
        bone = bones[r.varint(True)]["name"]
        col = r.color4()
        dark = r.color4()
        has_dark = not (dark[0] == 0xff and dark[1] == 0xff
                        and dark[2] == 0xff and dark[3] == 0xff)
        att = sref()
        blend = r.varint(True)
        s = {"name": name, "bone": bone}
        if _hex4(col) != "ffffffff":
            s["color"] = _hex4(col)
        if has_dark:
            s["darkColor"] = "%02x%02x%02xff" % (dark[0], dark[1], dark[2])
        if att:
            s["attachment"] = att
        if blend:
            s["blendMode"] = BLEND_NAMES[blend] if blend < len(BLEND_NAMES) else "normal"
        slots.append(s)
    tr("slots=%d" % len(slots))

    # ---------------- constraints
    ik = []
    for _ in range(r.varint(True)):
        name = r.string()
        order = r.varint(True)
        r.bool()  # skinRequired
        bones_idx = [r.varint(True) for _ in range(r.varint(True))]
        target = r.varint(True)
        mix = r.float32()
        softness = r.float32()
        bend = r.sbyte()
        compress = r.bool()
        stretch = r.bool()
        uniform = r.bool()
        c = {"name": name, "order": order,
             "bones": [bones[i]["name"] for i in bones_idx],
             "target": bones[target]["name"]}
        if mix != 1.0:
            c["mix"] = _fnum(mix)
        if softness:
            c["softness"] = _fnum(softness)
        if bend:
            c["bendDirection"] = bend
        if compress:
            c["compress"] = True
        if stretch:
            c["stretch"] = True
        if uniform:
            c["uniform"] = True
        ik.append(c)
    tr("ik=%d" % len(ik))

    transform = []
    for _ in range(r.varint(True)):
        name = r.string()
        order = r.varint(True)
        r.bool()
        bones_idx = [r.varint(True) for _ in range(r.varint(True))]
        target = r.varint(True)
        local = r.bool()
        relative = r.bool()
        rot = r.float32()
        ox = r.float32()
        oy = r.float32()
        osx = r.float32()
        osy = r.float32()
        oshear = r.float32()
        rmix = r.float32()
        tmix = r.float32()
        smix = r.float32()
        shmix = r.float32()
        c = {"name": name, "order": order,
             "bones": [bones[i]["name"] for i in bones_idx],
             "target": bones[target]["name"],
             "rotateMix": _fnum(rmix), "translateMix": _fnum(tmix),
             "scaleMix": _fnum(smix), "shearMix": _fnum(shmix)}
        if local:
            c["local"] = True
        if relative:
            c["relative"] = True
        if rot:
            c["rotation"] = _fnum(rot)
        if ox:
            c["x"] = _fnum(ox)
        if oy:
            c["y"] = _fnum(oy)
        if osx:
            c["scaleX"] = _fnum(osx)
        if osy:
            c["scaleY"] = _fnum(osy)
        if oshear:
            c["shearY"] = _fnum(oshear)
        transform.append(c)
    tr("transform=%d" % len(transform))

    path = []
    for _ in range(r.varint(True)):
        name = r.string()
        order = r.varint(True)
        r.bool()
        bones_idx = [r.varint(True) for _ in range(r.varint(True))]
        target = r.varint(True)
        pos_mode = r.varint(True)
        spacing_mode = r.varint(True)
        rotate_mode = r.varint(True)
        rot = r.float32()
        pos = r.float32()
        if pos_mode == 1:  # Fixed
            pos *= 1.0
        spacing = r.float32()
        if spacing_mode in (1, 2):
            spacing *= 1.0
        rmix = r.float32()
        tmix = r.float32()
        c = {"name": name, "order": order,
             "bones": [bones[i]["name"] for i in bones_idx],
             "target": slots[target]["name"],
             "positionMode": ("fixed", "percent")[pos_mode],
             "spacingMode": ("length", "fixed", "percent")[spacing_mode],
             "rotateMode": ("tangent", "chain", "chainScale")[rotate_mode]}
        if rot:
            c["rotation"] = _fnum(rot)
        if pos:
            c["position"] = _fnum(pos)
        if spacing:
            c["spacing"] = _fnum(spacing)
        if rmix:
            c["rotateMix"] = _fnum(rmix)
        if tmix:
            c["translateMix"] = _fnum(tmix)
        path.append(c)
    tr("path=%d" % len(path))

    # ---------------- skins
    skins = []
    linked = []

    def read_vertices(vcount, scale=1.0):
        weighted = r.bool()
        verts = []
        if not weighted:
            for _ in range(vcount * 2):
                verts.append(_fnum(r.float32() * scale))
            return verts, None
        # weighted: [boneCount, bone, x, y, weight, ...]
        out = []
        for _ in range(vcount):
            bn = r.varint(True)
            out.append(bn)
            for __ in range(bn):
                out.append(r.varint(True))
                out.append(_fnum(r.float32() * scale))
                out.append(_fnum(r.float32() * scale))
                out.append(_fnum(r.float32()))
        return out, None

    def read_attachment(slot_idx, att_name, skin, default_skin=False):
        name = sref() or att_name
        atype = r._b()
        if atype == 0:      # region
            path = sref() or name
            rot = r.float32()
            ax = r.float32()
            ay = r.float32()
            asx = r.float32()
            asy = r.float32()
            aw = r.float32()
            ah = r.float32()
            col = r.color4()
            a = {}
            if path != name:
                a["path"] = path
            if rot:
                a["rotation"] = _fnum(rot)
            if ax:
                a["x"] = _fnum(ax)
            if ay:
                a["y"] = _fnum(ay)
            if asx != 1:
                a["scaleX"] = _fnum(asx)
            if asy != 1:
                a["scaleY"] = _fnum(asy)
            a["width"] = _fnum(aw)
            a["height"] = _fnum(ah)
            if _hex4(col) != "ffffffff":
                a["color"] = _hex4(col)
            return name, a
        if atype == 1:      # boundingbox
            vcount = r.varint(True)
            verts, _ = read_vertices(vcount)
            if nonessential:
                r.color4()
            return name, {"type": "boundingbox", "vertexCount": vcount,
                          "vertices": verts}
        if atype == 2:      # mesh
            path = sref() or name
            col = r.color4()
            vcount = r.varint(True)
            uvs = [_fnum(r.float32()) for _ in range(vcount * 2)]
            tris = [r.u16() for _ in range(r.varint(True))]
            verts, _ = read_vertices(vcount)
            # 3.8 二进制里的 hull 就是 JSON 的 "hull"（顶点个数）：
            # spine-csharp `SkeletonBinary.cs` 读的是 `hull << 1`，
            # 与 `SkeletonJson.cs` 的 `hull * 2` 一致；不能在这里再右移。
            hull = r.varint(True)
            edges = None
            mw = mh = 0.0
            if nonessential:
                edges = [r.u16() for _ in range(r.varint(True))]
                mw = r.float32()
                mh = r.float32()
            a = {"type": "mesh"}
            if path != name:
                a["path"] = path
            if _hex4(col) != "ffffffff":
                a["color"] = _hex4(col)
            a["width"] = _fnum(mw)
            a["height"] = _fnum(mh)
            a["hull"] = hull
            a["triangles"] = tris
            if edges:
                a["edges"] = edges
            a["uvs"] = uvs
            a["vertices"] = verts
            return name, a
        if atype == 3:      # linkedmesh
            path = sref() or name
            col = r.color4()
            skin_name = sref()
            parent = sref()
            inherit = r.bool()
            mw = mh = 0.0
            if nonessential:
                mw = r.float32()
                mh = r.float32()
            linked.append((skin, slot_idx, name, path, skin_name,
                           parent, inherit))
            a = {"type": "linkedmesh"}
            if path != name:
                a["path"] = path
            if _hex4(col) != "ffffffff":
                a["color"] = _hex4(col)
            a["width"] = _fnum(mw)
            a["height"] = _fnum(mh)
            if skin_name:
                a["skin"] = skin_name
            a["parent"] = parent
            if not inherit:
                a["deform"] = False
            return name, a
        if atype == 4:      # path attachment
            closed = r.bool()
            const_speed = r.bool()
            vcount = r.varint(True)
            verts, _ = read_vertices(vcount)
            lengths = [_fnum(r.float32()) for _ in range(vcount // 3)]
            if nonessential:
                r.color4()
            return name, {"type": "path", "closed": closed,
                          "constantSpeed": const_speed,
                          "vertexCount": vcount, "vertices": verts,
                          "lengths": lengths}
        if atype == 5:      # point
            rot = r.float32()
            px = r.float32()
            py = r.float32()
            if nonessential:
                r.color4()
            a = {"type": "point"}
            if rot:
                a["rotation"] = _fnum(rot)
            if px:
                a["x"] = _fnum(px)
            if py:
                a["y"] = _fnum(py)
            return name, a
        if atype == 6:      # clipping
            end_idx = r.varint(True)
            vcount = r.varint(True)
            verts, _ = read_vertices(vcount)
            if nonessential:
                r.color4()
            return name, {"type": "clipping", "endSlot": slots[end_idx]["name"],
                          "vertexCount": vcount, "vertices": verts}
        raise RuntimeError("未知附件类型 %d" % atype)

    def read_skin(default_skin):
        if default_skin:
            slot_count = r.varint(True)
            if slot_count == 0:
                return None
            skin = {"name": "default", "attachments": {}}
        else:
            skin_name = sref()
            bones_names = [bones[r.varint(True)]["name"]
                           for _ in range(r.varint(True))]
            ik_names = [ik[r.varint(True)]["name"] for _ in range(r.varint(True))]
            tf_names = [transform[r.varint(True)]["name"]
                        for _ in range(r.varint(True))]
            path_names = [path[r.varint(True)]["name"] for _ in range(r.varint(True))]
            slot_count = r.varint(True)
            skin = {"name": skin_name, "attachments": {}}
            if bones_names:
                skin["bones"] = bones_names
            if ik_names or tf_names or path_names:
                skin["constraints"] = ik_names + tf_names + path_names
        for _ in range(slot_count):
            slot_idx = r.varint(True)
            for __ in range(r.varint(True)):
                att_name = sref()
                name, a = read_attachment(slot_idx, att_name, skin,
                                          default_skin=default_skin)
                skin["attachments"].setdefault(
                    slots[slot_idx]["name"], {})[name] = a
        return skin

    ds = read_skin(True)
    tr("default skin ok")
    if ds:
        skins.append(ds)
    for _ in range(r.varint(True)):
        sk = read_skin(False)
        if sk:
            skins.append(sk)
    tr("skins=%d" % len(skins))

    # linked mesh parent resolution happens only in the runtime; 名字已保留

    # ---------------- events
    events_order = []
    for _ in range(r.varint(True)):
        name = sref()
        ival = r.varint(False)
        fval = r.float32()
        sval = r.string()
        audio = r.string()
        ev = {"name": name}
        ev["int"] = ival
        ev["float"] = _fnum(fval)
        ev["string"] = sval
        if audio:
            ev["audio"] = audio
            ev["volume"] = _fnum(r.float32())
            ev["balance"] = _fnum(r.float32())
        events_order.append(ev)
    events = {}
    for ev in events_order:
        name = ev["name"]
        events[name] = ev
    tr("events=%d" % len(events_order))

    # ---------------- animations
    animations = {}
    for _ in range(r.varint(True)):
        name = r.string()
        animations[name] = _read_animation(r, sref, strings, bones, slots,
                                           ik, transform, path, skins,
                                           events_order)
    tr("animations done")

    sk = {"skeleton": {"hash": hashv, "spine": version, "x": _fnum(x),
                       "y": _fnum(y), "width": _fnum(w), "height": _fnum(h)},
          "bones": bones, "slots": slots, "skins": skins,
          "animations": animations}
    if events:
        sk["events"] = events
    if nonessential:
        sk["skeleton"]["images"] = images_path
        sk["skeleton"]["audio"] = audio_path
    if ik:
        sk["ik"] = ik
    if transform:
        sk["transform"] = transform
    if path:
        sk["path"] = path
    return sk


def _read_animation(r, sref, strings, bones, slots, ik, transform, path,
                    skins, events_order):
    anim = {}
    _trace = os.environ.get("SPINE_TRACE")

    def tr(msg):
        if _trace:
            print("TRACE-A %5d %s" % (r.p, msg), flush=True)

    def curve_after(fr):
        t = r._b()
        if t == 1:
            fr["curve"] = "stepped"
        elif t == 2:
            c1 = r.float32()
            c2 = r.float32()
            c3 = r.float32()
            c4 = r.float32()
            fr["curve"] = _fnum(c1)
            if c2:
                fr["c2"] = _fnum(c2)
            if c3 != 1:
                fr["c3"] = _fnum(c3)
            if c4 != 1:
                fr["c4"] = _fnum(c4)

    def push_timeline(timelines, key, frames):
        timelines.setdefault(key, []).extend(frames)

    # --- slot timelines
    slots_tl = {}
    n_slot_tl = r.varint(True)
    tr("slotTlCount=%d" % n_slot_tl)
    for _ in range(n_slot_tl):
        slot_idx = r.varint(True)
        sname = slots[slot_idx]["name"]
        n_ttl = r.varint(True)
        tr(" slot=%d sub=%d" % (slot_idx, n_ttl))
        for __ in range(n_ttl):
            ttype = r._b()
            fcount = r.varint(True)
            tr("   type=%d frames=%d" % (ttype, fcount))
            frames = []
            if ttype == 0:      # attachment
                for _f in range(fcount):
                    fr = {}
                    t = r.float32()
                    if t:
                        fr["time"] = _fnum(t)
                    nm = sref()
                    if nm:
                        fr["name"] = nm
                    frames.append(fr)
                push_timeline(slots_tl.setdefault(sname, {}),
                              "attachment", frames)
            elif ttype == 1:    # color
                for _f in range(fcount):
                    t = r.float32()
                    col = [r._b() for _ in range(4)]
                    fr = {"color": _hex4(col)}
                    if t:
                        fr["time"] = _fnum(t)
                    frames.append(fr)
                    if _f < fcount - 1:
                        curve_after(fr)
                push_timeline(slots_tl.setdefault(sname, {}), "color", frames)
            elif ttype == 2:    # two color
                for _f in range(fcount):
                    t = r.float32()
                    fr = {"color": _hex4([r._b() for _ in range(4)]),
                          "color2": _hex4([r._b() for _ in range(4)])}
                    if t:
                        fr["time"] = _fnum(t)
                    frames.append(fr)
                    if _f < fcount - 1:
                        curve_after(fr)
                push_timeline(slots_tl.setdefault(sname, {}),
                              "twoColor", frames)
            else:
                raise RuntimeError("未知 slot 时间线类型 %d" % ttype)
    if slots_tl:
        # 动画的 slots 是**扁平**的 `slots.<槽位名>`（见 SkeletonJson.cpp 的 readAnimation：
        # 直接 findSlotIndex(键名)；只有 deform 才带皮肤层）
        anim["slots"] = slots_tl

    # --- bone timelines
    bones_tl = {}
    n_bone_tl = r.varint(True)
    tr("boneTlCount=%d" % n_bone_tl)
    for _ in range(n_bone_tl):
        bone_idx = r.varint(True)
        bname = bones[bone_idx]["name"]
        n_ttl = r.varint(True)
        tr(" bone=%d(%s) sub=%d" % (bone_idx, bname, n_ttl))
        for __ in range(n_ttl):
            ttype = r._b()
            fcount = r.varint(True)
            tr("   bone type=%d frames=%d" % (ttype, fcount))
            frames = []
            if ttype == 0:      # rotate
                for _f in range(fcount):
                    fr = {}
                    t = r.float32()
                    if t:
                        fr["time"] = _fnum(t)
                    ang = r.float32()
                    if ang:
                        fr["angle"] = _fnum(ang)
                    frames.append(fr)
                    if _f < fcount - 1:
                        curve_after(fr)
                push_timeline(bones_tl.setdefault(bname, {}), "rotate", frames)
            elif ttype in (1, 2, 3):   # translate/scale/shear
                prop = ("translate", "scale", "shear")[ttype - 1]
                for _f in range(fcount):
                    fr = {}
                    t = r.float32()
                    if t:
                        fr["time"] = _fnum(t)
                    fx = r.float32()
                    fy = r.float32()
                    if fx:
                        fr["x"] = _fnum(fx)
                    if fy:
                        fr["y"] = _fnum(fy)
                    frames.append(fr)
                    if _f < fcount - 1:
                        curve_after(fr)
                push_timeline(bones_tl.setdefault(bname, {}), prop, frames)
            else:
                raise RuntimeError("未知 bone 时间线类型 %d" % ttype)
    if bones_tl:
        anim["bones"] = bones_tl

    # --- ik
    ik_tl = {}
    n_ik_tl = r.varint(True)
    tr("ikTlCount=%d" % n_ik_tl)
    for _ in range(n_ik_tl):
        idx = r.varint(True)
        fcount = r.varint(True)
        frames = []
        for _f in range(fcount):
            fr = {}
            t = r.float32()
            if t:
                fr["time"] = _fnum(t)
            mix = r.float32()
            soft = r.float32()
            bend = r.sbyte()
            comp = r.bool()
            stretch = r.bool()
            if mix != 1.0:
                fr["mix"] = _fnum(mix)
            if soft:
                fr["softness"] = _fnum(soft)
            if bend:
                fr["bendDirection"] = bend
            if comp:
                fr["compress"] = True
            if stretch:
                fr["stretch"] = True
            frames.append(fr)
            if _f < fcount - 1:
                curve_after(fr)
        ik_tl[ik[idx]["name"]] = frames
    if ik_tl:
        anim["ik"] = ik_tl

    # --- transform
    tf_tl = {}
    n_tf_tl = r.varint(True)
    tr("tfTlCount=%d" % n_tf_tl)
    for _ in range(n_tf_tl):
        idx = r.varint(True)
        fcount = r.varint(True)
        frames = []
        for _f in range(fcount):
            fr = {}
            t = r.float32()
            if t:
                fr["time"] = _fnum(t)
            rm = r.float32()
            tm2 = r.float32()
            sm = r.float32()
            shm = r.float32()
            if rm != 1.0:
                fr["rotateMix"] = _fnum(rm)
            if tm2 != 1.0:
                fr["translateMix"] = _fnum(tm2)
            if sm != 1.0:
                fr["scaleMix"] = _fnum(sm)
            if shm != 1.0:
                fr["shearMix"] = _fnum(shm)
            frames.append(fr)
            if _f < fcount - 1:
                curve_after(fr)
        tf_tl[transform[idx]["name"]] = frames
    if tf_tl:
        anim["transform"] = tf_tl

    # --- path
    path_tl = {}
    n_path_tl = r.varint(True)
    tr("pathTlCount=%d" % n_path_tl)
    for _ in range(n_path_tl):
        idx = r.varint(True)
        cname = path[idx]["name"]
        sub = {}
        for __ in range(r.varint(True)):
            ttype = r.sbyte()
            fcount = r.varint(True)
            frames = []
            if ttype in (0, 1):     # position / spacing
                key = "position" if ttype == 0 else "spacing"
                for _f in range(fcount):
                    fr = {}
                    t = r.float32()
                    if t:
                        fr["time"] = _fnum(t)
                    v = r.float32()
                    if v:
                        fr[key] = _fnum(v)
                    frames.append(fr)
                    if _f < fcount - 1:
                        curve_after(fr)
                sub[key] = frames
            elif ttype == 2:        # mix
                for _f in range(fcount):
                    fr = {}
                    t = r.float32()
                    if t:
                        fr["time"] = _fnum(t)
                    rm = r.float32()
                    tm2 = r.float32()
                    if rm != 1.0:
                        fr["rotateMix"] = _fnum(rm)
                    if tm2 != 1.0:
                        fr["translateMix"] = _fnum(tm2)
                    frames.append(fr)
                    if _f < fcount - 1:
                        curve_after(fr)
                sub["mix"] = frames
        if sub:
            path_tl[cname] = sub
    if path_tl:
        anim["path"] = path_tl

    # --- deform
    deform = {}
    n_def = r.varint(True)
    tr("deformCount=%d" % n_def)
    for _ in range(n_def):
        skin_idx = r.varint(True)
        skin = skins[skin_idx]
        skin_name = skin["name"]
        sub = deform.setdefault(skin_name, {})
        for __ in range(r.varint(True)):
            slot_idx = r.varint(True)
            sname = slots[slot_idx]["name"]
            att_map = sub.setdefault(sname, {})
            for ___ in range(r.varint(True)):
                att_name = sref()
                fcount = r.varint(True)
                frames = []
                for _f in range(fcount):
                    fr = {}
                    t = r.float32()
                    if t:
                        fr["time"] = _fnum(t)
                    end = r.varint(True)
                    if end:
                        start = r.varint(True)
                        fr["offset"] = start
                        fr["vertices"] = [_fnum(r.float32())
                                          for _ in range(start, start + end)]
                    frames.append(fr)
                    if _f < fcount - 1:
                        curve_after(fr)
                att_map[att_name] = frames
    if deform:
        anim["deform"] = deform

    # --- drawOrder
    draw_count = r.varint(True)
    tr("drawCount=%d" % draw_count)
    if draw_count:
        frames = []
        slot_count = len(slots)
        for _i in range(draw_count):
            fr = {}
            t = r.float32()
            if t:
                fr["time"] = _fnum(t)
            n_off = r.varint(True)
            offsets = []
            for __ in range(n_off):
                slot_idx = r.varint(True)
                off = r.varint(True)
                offsets.append({"slot": slots[slot_idx]["name"],
                                "offset": off})
            fr["offsets"] = offsets
            frames.append(fr)
        anim["drawOrder"] = frames

    # --- events
    ev_count = r.varint(True)
    tr("animEventCount=%d" % ev_count)
    if ev_count:
        evs = []
        for _i in range(ev_count):
            fr = {}
            t = r.float32()
            if t:
                fr["time"] = _fnum(t)
            ev_idx = r.varint(True)
            edata = events_order[ev_idx]
            ival = r.varint(False)
            fval = r.float32()
            free_str = r.bool()
            sval = r.string() if free_str else ""
            fr["name"] = edata["name"]
            if ival != edata.get("int", 0):
                fr["int"] = ival
            if _fnum(fval) != edata.get("float", 0):
                fr["float"] = _fnum(fval)
            if free_str:
                fr["string"] = sval
            if edata.get("audio"):
                fr["volume"] = _fnum(r.float32())
                fr["balance"] = _fnum(r.float32())
            evs.append(fr)
        anim["events"] = evs
    return anim


if __name__ == "__main__":
    import sys
    m = read_skeleton_json(sys.argv[1])
    print(json.dumps(m, ensure_ascii=False, indent=1))
