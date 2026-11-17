# -*- coding: utf-8 -*-
"""把 Legacy AnimationClip 的采样结果写成 Spine 3.8 动画时间线。"""

from ..ngui.ngui_anim import quat_to_deg_z


def _wrap_deg(a):
    while a > 180:
        a -= 360
    while a <= -180:
        a += 360
    return a


def _node_path(node, by_go):
    parts = []
    cur = node
    while cur is not None and by_go.get(cur.go_id) is not None:
        parts.append(cur.name)
        cur = by_go.get(cur.parent_id)
    parts.pop()  # 去掉 root 名：动画 path 相对 Animation 所在 GO
    return "/".join(reversed(parts))


def _curve_for(path_curves, path, kind):
    return [c for c in path_curves.get(path, []) if c.kind == kind]


def build_animation(data, asm, clip_name, clip_data, sample_dt=0.05):
    nodes = asm.nodes
    by_go = asm.node_by_go()
    path_of = {n.go_id: _node_path(n, by_go) for n in nodes}
    # 与 spine_out.make_skeleton_json 保持同一命名：重名节点用 父/名 全名
    name_count = {}
    for n in nodes:
        name_count[n.name] = name_count.get(n.name, 0) + 1

    def uniq_name(n):
        if name_count.get(n.name, 0) == 1:
            return n.name
        p = by_go.get(n.parent_id)
        return (p.name + "/" + n.name) if p is not None else n.name

    path_curves = {}
    for c in clip_data["curves"]:
        path_curves.setdefault(c.path, []).append(c)

    def rot_at(t, node, path):
        cs = _curve_for(path_curves, path, "rot")
        if not cs:
            return node.rot_deg
        return quat_to_deg_z(cs[0].value_at(t))

    def value_at(t, node, path, kind, key, default):
        cs = _curve_for(path_curves, path, kind)
        if not cs:
            return default
        v = cs[0].value_at(t)
        return float(v.get(key, default))

    # 采样时间轴：所有曲线关键帧时刻 + 0..max 的规则栅格
    times = set()
    max_t = 0.0
    for c in clip_data["curves"]:
        for t, _ in c.keys:
            times.add(t)
            max_t = max(max_t, t)
    n = int(max_t / sample_dt)
    for i in range(n + 1):
        times.add(round(i * sample_dt, 6))
    times = sorted(times)

    # setup pose = 动画在 t=0 求值结果（Legacy 播放时 0 秒即覆盖到曲线首值）
    setup = {}
    for node in nodes:
        p = path_of[node.go_id]
        setup[node.go_id] = {
            "rot": rot_at(0.0, node, p),
            "x": value_at(0.0, node, p, "pos", "x", node.pos[0]),
            "y": value_at(0.0, node, p, "pos", "y", node.pos[1]),
            "sx": value_at(0.0, node, p, "scale", "x", node.scale[0]),
            "sy": value_at(0.0, node, p, "scale", "y", node.scale[1]),
        }

    anim_obj = data["animations"].setdefault(clip_name, {})
    bones_obj = anim_obj.setdefault("bones", {})
    bone_names = {n.go_id: uniq_name(n) for n in nodes}

    # 旋转：曲线上的骨骼按规则栅格写线性关键帧
    for node in nodes:
        p = path_of[node.go_id]
        if not _curve_for(path_curves, p, "rot"):
            continue
        last = None
        keys = []
        for t in times:
            deg = rot_at(t, node, p)
            if last is None:
                absdeg = deg
            else:
                absdeg = last + _wrap_deg(deg - last)
            last = absdeg
            keys.append({
                "time": round(t, 6),
                "angle": round(absdeg - setup[node.go_id]["rot"], 6),
            })
        bones_obj.setdefault(bone_names[node.go_id], {})["rotate"] = keys

    # 位移
    for node in nodes:
        p = path_of[node.go_id]
        if not _curve_for(path_curves, p, "pos"):
            continue
        keys = []
        for t in times:
            x = value_at(t, node, p, "pos", "x", node.pos[0]) - setup[node.go_id]["x"]
            y = value_at(t, node, p, "pos", "y", node.pos[1]) - setup[node.go_id]["y"]
            keys.append({"time": round(t, 6), "x": round(x, 6), "y": round(y, 6)})
        bones_obj.setdefault(bone_names[node.go_id], {})["translate"] = keys

    # 缩放（本项目 clip 基本没有，保留支持）
    for node in nodes:
        p = path_of[node.go_id]
        if not _curve_for(path_curves, p, "scale"):
            continue
        keys = []
        for t in times:
            x = value_at(t, node, p, "scale", "x", node.scale[0]) / max(setup[node.go_id]["sx"], 1e-9)
            y = value_at(t, node, p, "scale", "y", node.scale[1]) / max(setup[node.go_id]["sy"], 1e-9)
            keys.append({"time": round(t, 6), "x": round(x, 6), "y": round(y, 6)})
        bones_obj.setdefault(bone_names[node.go_id], {})["scale"] = keys

    # 槽位：m_IsActive（显示/隐藏）与 mColor.*
    slots_obj = anim_obj.setdefault("slots", {})
    for node in nodes:
        if not node.sprite:
            continue
        p = path_of[node.go_id]
        slot = bone_names[node.go_id]
        active = [c for c in _curve_for(path_curves, p, "float") if c.attribute == "m_IsActive"]
        if active:
            keys = []
            for t in times:
                v = active[0].value_at(t)
                keys.append({
                    "time": round(t, 6),
                    "name": node.sprite["sprite_name"] if v > 0.5 else None,
                })
            slots_obj.setdefault(slot, {})["attachment"] = keys
        colors = [c for c in _curve_for(path_curves, p, "float") if str(c.attribute).startswith("mColor.")]
        if colors:
            channel = str(colors[0].attribute).split(".")[-1]
            base = node.sprite.get("color") or {}

            def comp(key):
                return max(0.0, min(1.0, float(base.get(key, 1.0))))

            keys = []
            for t in times:
                rgba = {"r": comp("r"), "g": comp("g"), "b": comp("b"), "a": comp("a")}
                rgba[channel] = max(0.0, min(1.0, colors[0].value_at(t)))
                hexs = "".join("%02x" % int(round(v * 255)) for v in
                               (rgba["r"], rgba["g"], rgba["b"], rgba["a"]))
                keys.append({"time": round(t, 6), "color": hexs})
            slots_obj.setdefault(slot, {})["color"] = keys
    return data
