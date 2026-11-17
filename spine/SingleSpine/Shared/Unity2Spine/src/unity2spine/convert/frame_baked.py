# -*- coding: utf-8 -*-
"""帧烘焙模式：把 Unity PoseFrames（BakeMesh 顶点/世界矩阵/sprite 四角）
直接还原成 Spine mesh+deform，不再自行重建骨骼蒙皮。"""

import json
import math
import os
import shutil
import sys

from ..spine.spine_out import atlas_text, fnum, write_viewer_config
from ..unity.unity_mesh import mat4_vec


def _flat(m):
    if not m:
        return None
    if isinstance(m[0], (list, tuple)):
        return [v for row in m for v in row]
    return list(m)


def _world(l2w, p):
    m = _flat(l2w)
    if not m:
        return p
    return mat4_vec(m, (p[0], p[1], p[2]))


def _flip_v(uvs):
    """Unity UV(左下原点) -> Spine UV(右上原点)：v 取反。"""
    return [(u, 1.0 - v) for u, v in uvs]


# 头部类 sprite 在部分动画轨中会被动画摆到离屏（-120 等），但预览/序列化姿态
# 里它贴在 bone_head 上。这里按“父骨骼世界坐标 + 固定偏移”把脸钉回头部。
# offset 来自 save.unity 序列化姿态：parts_head GO 相对 bone_head 的位移。
HEAD_PINS = {
    "parts_head": {"parent": "bone_head", "offset": (-0.107, 0.861)},
}


def convert_frame_baked(prefab, assets, pose_path, out_dir,
                        layout_path=None, skinned_only=False,
                        normalize=True, cam_path=None):
    # 用现有离线解析拿材质贴图与完整路径
    from .convert_2dmodel import build_character_model
    mdl, parts = build_character_model(prefab, assets)
    by_path = {}
    for p in parts:
        p.full_path = ""
        if p.tfid in mdl.transforms:
            p.full_path = mdl.transforms[p.tfid]["path"]
        by_path[p.full_path] = p

    frames = json.load(open(pose_path, encoding="utf-8-sig"))

    def entries(fr):
        out = []
        for key in ("skinned", "sprites"):
            for x in fr.get(key, []) or []:
                out.append(x)
        for x in fr.get("static", []) or []:
            out.append(x)
        return out

    def is_skinned(r):
        return "baked" in r or (
            isinstance(r.get("positions"), list) and
            isinstance(r.get("triangles"), list))

    base = os.path.splitext(os.path.basename(prefab))[0]
    frs = frames.get("frames", [])
    if not frs:
        raise ValueError("PoseFrames 没有帧: " + pose_path)

    renderer_paths = []
    for r in entries(frs[0]):
        if r.get("path") in by_path and (
                is_skinned(r) or "worldCorners" in r or "localToWorld" in r):
            leaf = r["path"].split("/")[-1]
            # additive 光晕只保留 Unity 中确实可见的三类：
            #  1) aeda_ball_glow 球光（仅 bone_glow_1 (2)/(3) 下名为 parts_glow_1 的直接子级）
            #  2) 身上逐渐上升的光点（bone_pelvis_01/bone_glow_1）
            #  3) 手臂小光（bone_glow_L_Arm_2/parts_glow_1）
            if leaf.startswith("parts_glow"):
                in_ball = (
                    "aeda_ball_glow" in r["path"] and
                    ("bone_glow_1 (2)" in r["path"] or
                     "bone_glow_1 (3)" in r["path"]) and
                    leaf == "parts_glow_1")
                rising = r["path"].find("bone_pelvis_01/bone_glow_1/") >= 0
                arm = ("bone_glow_L_Arm_2" in r["path"] and
                       "bone_arms" not in r["path"] and
                       leaf == "parts_glow_1")
                keep = in_ball or rising or arm
                if not keep:
                    continue
            renderer_paths.append(r["path"])

    # Spine slot 顺序 = Unity 绘制顺序：优先用导出时的 sortingOrder，
    # 没有则退回 prefab 解析值；同 order 按原遍历顺序保持稳定。
    first_map = {}
    for e in entries(frs[0]):
        if e.get("path") in by_path:
            first_map[e["path"]] = e
    def _order_of(p):
        e = first_map.get(p) or {}
        if e.get("sortingOrder") is not None:
            base = int(e["sortingOrder"])
        else:
            base = int(getattr(by_path[p], "sorting_order", 0) or 0)
        # 头部脸片：画在身体/颈部之上、白色头发(后画)之下
        if p.split("/")[-1] in HEAD_PINS:
            return 1.5
        return base
    seq = {}
    for i, p in enumerate(renderer_paths):
        seq.setdefault((_order_of(p), 0), []).append(p)
    renderer_paths = [p for k in sorted(seq) for p in seq[k]]

    # 收集贴图并决定图集页（先整页复制，页数多时可再改裁切）
    tex_paths = []
    for path in renderer_paths:
        tp = by_path[path].texture_path
        if tp and tp not in tex_paths:
            tex_paths.append(tp)

    def frame_vertices(rpath, fi):
        fr = frs[fi]
        r = None
        for x in entries(fr):
            if x.get("path") == rpath:
                r = x
                break
        p = by_path[rpath]
        if r is None:
            return None, None, None
        if "baked" in r:
            bk = r["baked"]
            local = bk.get("positions", [])
            l2w = r.get("localToWorld")
            verts = [_world(l2w, v) for v in local]
            uvs = _flip_v(bk.get("uvs", []))
            tris = bk.get("triangles", [])
        elif is_skinned(r):
            verts = [_world(r.get("localToWorld"), v)
                     for v in r.get("positions", [])]
            uvs = _flip_v(r.get("uvs", []))
            tris = list(r.get("triangles", []))
        elif r.get("worldCorners"):
            wc = r["worldCorners"]
            rect = r.get("rect") or [0, 0, 0, 0]
            ts = r.get("textureSize") or [1, 1]
            # Editor PoseFramesExporter 的 sprite 项不带 rect；回退到离线 sprite 元数据
            part = by_path.get(rpath)
            sp_meta = getattr(part, "sprite", None) or {}
            if not r.get("rect") and sp_meta.get("rect"):
                rect = list(sp_meta["rect"])
            if (ts[0] or 1) <= 1 and part is not None and part.texture_path:
                try:
                    from PIL import Image as _I
                    _w, _h = _I.open(part.texture_path).size
                    ts = [_w, _h]
                except Exception:
                    pass
            leaf = rpath.split("/")[-1]
            pin = HEAD_PINS.get(leaf)
            # Sprite 公式已修、导出坐标已正确；直接使用每帧真实 worldCorners，
            # 避免旧“离屏钉回”在坐标阈值两侧切换导致脸偶尔镜像
            _ = pin
            verts = list(wc)
            u0 = rect[0] / max(1, ts[0])
            v0 = 1.0 - (rect[1] + rect[3]) / max(1, ts[1])
            u1 = (rect[0] + rect[2]) / max(1, ts[0])
            v1 = 1.0 - rect[1] / max(1, ts[1])
            # Unity 贴图行序与 Spine 相反：区域内把 v0/v1 对调（上端顶点配下方纹素）
            uvs = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
            tris = [0, 1, 2, 0, 2, 3]
        elif r.get("localToWorld") and p.mesh is not None:
            verts = [_world(r.get("localToWorld"), v)
                     for v in p.mesh.get("positions", [])]
            uvs = _flip_v(p.mesh.get("uvs", []))
            tris = list(p.mesh.get("triangles", []))
        else:
            return None, None, None
        return verts, uvs, tris

    # setup = 第 0 帧
    setup = {}
    uvmap = {}
    trimap = {}
    for rp in renderer_paths:
        v, u, t = frame_vertices(rp, 0)
        if v:
            setup[rp] = v
            uvmap[rp] = u
            trimap[rp] = t

    # 以 SceneLayout bounds 为基准做整体平移对齐
    shift = (0.0, 0.0)
    if layout_path:
        try:
            lay = json.load(open(layout_path, encoding="utf-8-sig"))
        except Exception:
            lay = None
        if lay:
            lmap = {}
            for ch in lay.get("children", []):
                for rr in ch.get("renderers", []):
                    bb = rr.get("bounds")
                    if len(bb or []) == 4:
                        lmap[rr.get("path")] = tuple(bb)
            dxs, dys = [], []
            for rp in setup:
                lb = lmap.get(rp)
                if not lb or len(setup[rp]) < 2:
                    continue
                xs = [p[0] for p in setup[rp]]
                ys = [p[1] for p in setup[rp]]
                pb = (min(xs), min(ys), max(xs), max(ys))
                dxs.append(pb[0] - lb[0])
                dys.append(pb[1] - lb[1])
            if dxs:
                dxs.sort()
                dys.sort()
                shift = (dxs[len(dxs) // 2], dys[len(dys) // 2])
                for rp in setup:
                    setup[rp] = [(p[0] - shift[0], p[1] - shift[1], p[2])
                                 for p in setup[rp]]

    if cam_path:
        cp = {}
        for line in open(cam_path, encoding="utf-8-sig"):
            k, v = line.strip().lstrip("\ufeff").split("=")
            cp[k] = float(v)
        half_w = cp["size"] * cp["aspect"]
        rx0, ry0 = cp["cx"] - half_w, cp["cy"] - cp["size"]
        rx1, ry1 = cp["cx"] + half_w, cp["cy"] + cp["size"]
        keep = {}
        for rp, pts in setup.items():
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if max(xs) >= rx0 and min(xs) <= rx1 and \
                    max(ys) >= ry0 and min(ys) <= ry1:
                keep[rp] = pts
        setup = keep

    # 仅保留蒙皮主体并做比例归一化，保证各帧不随远处特效/漂移而变形
    norm_scale = 1.0
    raw_setup = {rp: list(v) for rp, v in setup.items()}
    if skinned_only:
        skinned_paths = [rp for rp in setup
                         if any(is_skinned(r) for r in entries(frs[0])
                                if r.get("path") == rp)]
        setup = {rp: setup[rp] for rp in skinned_paths}
    if normalize:
        pts = []
        for rp in setup:
            for p in setup[rp]:
                pts.append((p[0], p[1]))
        if pts:
            cx = sum(x for x, _ in pts) / len(pts)
            cy = sum(y for _, y in pts) / len(pts)
            ys = [p[1] for p in pts]
            xs = [p[0] for p in pts]
            h = max(1e-3, max(ys) - min(ys))
            w = max(1e-3, max(xs) - min(xs))
            norm_scale = 5.0 / max(h, w * 0.5)
            for rp in setup:
                setup[rp] = [((p[0] - cx) * norm_scale,
                              (p[1] - cy) * norm_scale, p[2])
                             for p in setup[rp]]

    # 只保留与蒙皮主体同簇的 sprite（远距特效会撑爆自动取景）
    skinned_paths = [rp for rp in setup
                     if any("baked" in r for r in entries(frs[0])
                            if r.get("path") == rp)]
    pts = []
    for rp in skinned_paths:
        for p in setup[rp]:
            pts.append((p[0], p[1]))
    if pts:
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        extent = max(max(abs(x - cx), abs(y - cy)) for x, y in pts)
        limit = max(extent * 2.0, 30.0)
        for rp in list(setup):
            if rp in skinned_paths:
                continue
            pts2 = setup[rp]
            if pts2 and any(abs(p[0] - cx) > limit or abs(p[1] - cy) > limit
                            for p in pts2):
                setup.pop(rp, None)

    used = set()

    def uniq(n):
        while n in used:
            n += "_x"
        used.add(n)
        return n

    slots = []
    skin = {}
    for rp in renderer_paths:
        if rp not in setup:
            continue
        nm = uniq(by_path[rp].name if by_path[rp].name else rp.split("/")[-1])
        slots.append({"name": nm, "bone": "Root", "color": "ffffffff",
                      "attachment": nm})
        tex_id = tex_paths.index(by_path[rp].texture_path) \
            if by_path[rp].texture_path in tex_paths else 0
        att = {
            "type": "mesh",
            "uvs": [fnum(x) for uv in uvmap[rp] for x in uv],
            "triangles": list(trimap[rp]),
            "vertices": [fnum(x) for v in setup[rp] for x in (v[0], v[1])],
            "hull": len(setup[rp]),
            "width": 1, "height": 1, "path": "tex%d" % tex_id,
        }
        skin[nm] = {nm: att}

    rp_slot = {}
    deform = {}
    k = 0
    for rp in renderer_paths:
        if rp in setup:
            rp_slot[rp] = slots[k]["name"]
            k += 1
    for fi, fr in enumerate(frs):
        t = fr.get("time", fi * 0.05)
        for rp, nm in rp_slot.items():
            v, _u, _t = frame_vertices(rp, fi)
            if not v or len(v) != len(setup[rp]):
                continue
            cur = []
            for a, b in zip(v, raw_setup[rp]):
                cur.extend([a[0] - b[0], a[1] - b[1]])
            deform.setdefault(nm, []).append({
                "time": fnum(t),
                "vertices": [fnum(x * norm_scale) for x in cur],
            })

    skeleton = {
        "skeleton": {"hash": "ngui2spine-framebake-" + base,
                     "spine": "3.8.99", "x": 0, "y": 0,
                     "width": 0, "height": 0, "fps": 60},
        "bones": [{"name": "Root", "length": 0, "x": 0, "y": 0,
                   "rotation": 0, "scaleX": 1, "scaleY": 1}],
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin}],
        "animations": {},
    }
    if deform:
        defo = {}
        for nm, fl in deform.items():
            defo.setdefault("default", {}).setdefault(nm, {})[nm] = fl
        skeleton["animations"]["idle"] = {"deform": defo}

    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, base + "_fb.json")
    atlas_path = os.path.join(out_dir, base + "_fb.atlas")
    with open(json_path, "w", encoding="utf-8") as fp:
        json.dump(skeleton, fp, ensure_ascii=False, indent=1)
    pages = []
    for i, tp in enumerate(tex_paths):
        fname = "%s_fb_%d.png" % (base, i)
        shutil.copy2(tp, os.path.join(out_dir, fname))
        from PIL import Image as _I
        w, h = _I.open(tp).size
        pages.append({"file": fname, "size": (w, h), "regions": [
            ("tex%d" % i, {"x": 0, "y": 0, "width": w, "height": h})]})
    open(atlas_path, "w", encoding="utf-8").write(atlas_text(pages))
    write_viewer_config(out_dir, skeleton, os.path.basename(json_path),
                        os.path.basename(atlas_path),
                        [os.path.splitext(p["file"])[0] for p in pages])
    return json_path, atlas_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("pose")
    ap.add_argument("out")
    ap.add_argument("--layout")
    ap.add_argument("--skinned-only", action="store_true")
    ap.add_argument("--no-normalize", action="store_true")
    ap.add_argument("--cam", help="CaptureFrames 相机参数 txt")
    a = ap.parse_args()
    if not (a.prefab and a.pose and a.out):
        print("用法: python -m ngui2spine.frame_baked <prefab> <pose json> <输出目录> [--layout json]")
        sys.exit(2)
    print(convert_frame_baked(
        a.prefab, r"D:\VB\Search\NormalLocal\lastOrign\Assets",
        a.pose, a.out, layout_path=a.layout,
        skinned_only=a.skinned_only,
        normalize=not a.no_normalize,
        cam_path=a.cam))
