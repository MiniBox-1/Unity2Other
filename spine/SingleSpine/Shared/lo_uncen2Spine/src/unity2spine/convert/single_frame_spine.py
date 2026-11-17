# -*- coding: utf-8 -*-
"""单帧 Spine 生成器（t0 真值 -> Spine 3.8）

输入：TwoDModelUnityExport 导出的 SceneT0 JSON（kind=skinned/sprite/static，
      含 BakeMesh 局部顶点+localToWorld、sprite worldCorners）+ CaptureFrames 相机 txt。
流程：
  1. 用 localToWorld x BakeMesh 局部顶点得到世界坐标（已与 Unity Renderer.bounds 核验）；
  2. 只保留与世界取景窗口相交的部件（排除动画未激活的远距装饰/换装部件）；
  3. 统一做一次中心化 + 等比归一化，输出 Spine mesh（无动画）；
  4. 复制贴图页并生成 atlas。
输出可直接交给 D:\\VB\\Viewer\\Render 离线渲染器预览。
"""
# --- lo_uncen2Spine: 位置解析（自动插入，见 src/tools\deabs_paths.py）------
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while _ROOT and not _os.path.isdir(_os.path.join(_ROOT, 'unity2spine')):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT and _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from unity2spine.env import resolve as _resolve  # noqa: E402
from unity2spine.console import fix_console as _fix_console  # noqa: E402
_fix_console()
# ---------------------------------------------------------------------


import argparse
import json
import os
import shutil
import sys

from ..spine.spine_out import atlas_text, fnum
from ..unity.unity_mesh import mat4_vec


def _flat(m):
    if not m:
        return None
    if isinstance(m[0], (list, tuple)):
        return [v for row in m for v in row]
    return list(m)


def _world(l2w, v):
    m = _flat(l2w)
    if not m:
        return v
    return mat4_vec(m, (v[0], v[1], v[2]))


def _flip_v(uvs):
    """Unity UV(左下原点) -> Spine UV(右上原点)：v 取反。"""
    return [(u, 1.0 - v) for u, v in uvs]


def _aabb(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _read_cam(cam_path):
    cp = {}
    for line in open(cam_path, encoding="utf-8-sig"):
        line = line.strip().lstrip("\ufeff")
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cp[k] = float(v)
    size = cp.get("size", 10.0)
    aspect = cp.get("aspect", 1.0)
    cx = cp.get("cx", 0.0)
    cy = cp.get("cy", 0.0)
    return cx, cy, size, aspect, cp


def convert_single_frame(prefab, assets, truth_path, out_dir,
                         cam_path=None, include_sprites=True,
                         include_static=True, window_pad=1.15):
    from .convert_2dmodel import build_character_model

    mdl, parts = build_character_model(prefab, assets)
    by_path = {}
    for p in parts:
        p.full_path = ""
        if p.tfid in mdl.transforms:
            p.full_path = mdl.transforms[p.tfid]["path"]
        by_path[p.full_path] = p

    data = json.load(open(truth_path, encoding="utf-8-sig"))
    renderers = data.get("renderers", [])

    # ---- 相机取景窗口 ----
    cam_box = None
    if cam_path:
        if not os.path.exists(cam_path):
            raise FileNotFoundError("相机参数文件不存在: " + cam_path)
        cx, cy, size, aspect, _ = _read_cam(cam_path)
        hw = size * aspect * window_pad
        hh = size * window_pad
        cam_box = (cx - hw, cy - hh, cx + hw, cy + hh)

    # ---- 逐部件收集世界坐标 ----
    kept = []
    tex_paths = []
    for ri, r in enumerate(renderers):
        kind = r.get("kind")
        if kind == "skinned":
            bk = r.get("baked") or {}
            pts = bk.get("positions") or []
            uvs = _flip_v(bk.get("uvs") or [])
            tris = bk.get("triangles") or []
            l2w = r.get("localToWorld")
            if not pts or not uvs or not tris or not l2w:
                continue
            verts = [_world(l2w, v) for v in pts]
        elif kind == "sprite" and include_sprites:
            wc = r.get("worldCorners") or []
            rect = r.get("rect") or [0, 0, 0, 0]
            ts = r.get("textureSize") or [1, 1]
            if len(wc) < 4 or not ts[0] or not ts[1]:
                continue
            verts = [list(p) for p in wc]
            u0 = rect[0] / float(ts[0])
            v0 = 1.0 - (rect[1] + rect[3]) / float(ts[1])
            u1 = (rect[0] + rect[2]) / float(ts[0])
            v1 = 1.0 - rect[1] / float(ts[1])
            # Unity 贴图行序与 Spine 相反：区域内把 v0/v1 对调
            uvs = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
            tris = [0, 1, 2, 0, 2, 3]
        elif kind == "static" and include_static:
            p = by_path.get(r.get("path", ""))
            if p is None or not p.mesh:
                continue
            pts = p.mesh.get("positions") or []
            uvs = _flip_v(p.mesh.get("uvs") or [])
            tris = p.mesh.get("triangles") or []
            l2w = r.get("localToWorld")
            if not pts or not uvs or not tris or not l2w:
                continue
            verts = [_world(l2w, v) for v in pts]
        else:
            continue

        part = by_path.get(r.get("path", ""))
        if part is None or not part.texture_path:
            continue
        bb = _aabb(verts)
        if cam_box is not None:
            cx0, cy0, cx1, cy1 = cam_box
            if bb[2] < cx0 or bb[0] > cx1 or bb[3] < cy0 or bb[1] > cy1:
                continue
        if part.texture_path not in tex_paths:
            tex_paths.append(part.texture_path)
        kept.append({
            "name": part.name or r["path"].split("/")[-1],
            "verts": verts,
            "uvs": [list(u) for u in uvs],
            "tris": list(tris),
            "tex": part.texture_path,
            "bb": bb,
            "order": int(getattr(part, "sorting_order", 0) or 0),
            "idx": ri,
        })

    if not kept:
        raise ValueError("没有可用部件（检查 truth JSON / cam 窗口）")
    # Spine slot 顺序 = Unity 绘制顺序：sortingOrder 小者先画（在后面）
    kept.sort(key=lambda e: (e["order"], e["idx"]))

    # ---- 统一坐标：中心化 + 等比缩放（高度约 10 单位，供离线渲染自动取景）----
    all_pts = [p for e in kept for p in e["verts"]]
    gx0, gy0, gx1, gy1 = _aabb(all_pts)
    cxx = (gx0 + gx1) / 2.0
    cyy = (gy0 + gy1) / 2.0
    h = max(1e-3, gy1 - gy0)
    w = max(1e-3, gx1 - gx0)
    s = 10.0 / max(h, w * 0.5)
    for e in kept:
        e["spine"] = [((p[0] - cxx) * s, (p[1] - cyy) * s) for p in e["verts"]]
        e["ref"] = list(e["verts"])

    # ---- 生成 Spine JSON / atlas ----
    base = os.path.splitext(os.path.basename(truth_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    used = set()

    def uniq(n):
        nn = n
        k = 1
        while nn in used:
            nn = "%s_%02d" % (n, k)
            k += 1
        used.add(nn)
        return nn

    slots = []
    skin = {}
    for e in kept:
        nm = uniq(e["name"])
        tex_id = tex_paths.index(e["tex"])
        att = {
            "type": "mesh",
            "uvs": [fnum(x) for uv in e["uvs"] for x in uv],
            "triangles": list(e["tris"]),
            "vertices": [fnum(x) for v in e["spine"] for x in v],
            "hull": len(e["spine"]),
            "width": 1,
            "height": 1,
            "path": "tex%d" % tex_id,
        }
        slots.append({"name": nm, "bone": "Root", "color": "ffffffff",
                      "attachment": nm})
        skin[nm] = {nm: att}

    skeleton = {
        "skeleton": {"hash": "ngui2spine-sf-" + base, "spine": "3.8.99",
                     "x": 0, "y": 0, "width": 0, "height": 0, "fps": 60},
        "bones": [{"name": "Root", "length": 0, "x": 0, "y": 0,
                   "rotation": 0, "scaleX": 1, "scaleY": 1}],
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin}],
        # 离线渲染器按“第一个动画”取帧；空 idle 可让它直接显示 setup pose
        "animations": {"idle": {}},
    }
    json_path = os.path.join(out_dir, base + "_sf.json")
    atlas_path = os.path.join(out_dir, base + "_sf.atlas")
    with open(json_path, "w", encoding="utf-8") as fp:
        json.dump(skeleton, fp, ensure_ascii=False, indent=1)

    pages = []
    for i, tp in enumerate(tex_paths):
        fname = "%s_sf_%d.png" % (base, i)
        shutil.copy2(tp, os.path.join(out_dir, fname))
        from PIL import Image as _I
        w, h = _I.open(tp).size
        pages.append({"file": fname, "size": (w, h), "regions": [
            ("tex%d" % i, {"x": 0, "y": 0, "width": w, "height": h})]})
    with open(atlas_path, "w", encoding="utf-8") as fp:
        fp.write(atlas_text(pages))
    from ..spine.spine_out import write_viewer_config
    write_viewer_config(out_dir, skeleton, os.path.basename(json_path),
                        os.path.basename(atlas_path),
                        [os.path.splitext(p["file"])[0] for p in pages])

    info = {
        "input": truth_path,
        "cam": cam_path,
        "base": base,
        "kept": len(kept),
        "textures": len(tex_paths),
        "worldBox": [gx0, gy0, gx1, gy1],
        "normalize": {"center": [cxx, cyy], "scale": s, "heightUnits": 10.0},
    }
    with open(os.path.join(out_dir, "_sf_info.json"), "w", encoding="utf-8") as fp:
        json.dump(info, fp, ensure_ascii=False, indent=1)
    return json_path, atlas_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab", help="角色 prefab 路径（Assets/...）")
    ap.add_argument("truth", help="SceneT0 JSON")
    ap.add_argument("out", help="输出目录")
    ap.add_argument("--assets", default=_resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets"))
    ap.add_argument("--cam", help="CaptureFrames 相机 txt")
    ap.add_argument("--no-sprites", action="store_true")
    ap.add_argument("--no-static", action="store_true")
    a = ap.parse_args()
    if not (a.prefab and a.truth and a.out):
        print("用法: python -m ngui2spine.single_frame_spine <prefab> <SceneT0 json> <out> [--cam ...]")
        sys.exit(2)
    print(convert_single_frame(
        a.prefab, a.assets, a.truth, a.out,
        cam_path=a.cam,
        include_sprites=not a.no_sprites,
        include_static=not a.no_static))
