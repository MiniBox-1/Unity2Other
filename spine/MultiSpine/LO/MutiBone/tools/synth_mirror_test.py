# -*- coding: utf-8 -*-
r"""合成骨架实验：查查看器对"骨链里的镜像（180°/负缩放）"怎么解释。

背景：真实多骨骼产物里根骨探针正常、深骨探针 0 墨迹；怀疑镜像那层是分水岭。
不依赖 prefab：手搓 4 骨链 + quad，逐组渲染并打印墨迹框。

用法：python tools\synth_mirror_test.py
"""
import json
import os
import shutil
import sys

BASE = r"D:\VB\MutiBone"
OUT = os.path.join(BASE, "out", "_synth_mirror")
ATLAS_SRC = r"D:\VB\Unity2Spine\_probe50_rt4\banshee_skin1"
RENDER_ROOT = r"D:\VB\Viewer\Render\v4"

CASES = {
    "a_nomirror": (0, 1, 1),
    "b_rot180": (180, 1, 1),
    "c_flipY": (0, 1, -1),
    "d_rot180_flipY": (180, 1, -1),
    "e_flipX": (0, -1, 1),
}


def build():
    os.makedirs(OUT, exist_ok=True)
    made = []
    for tag, (rot, sx, sy) in CASES.items():
        d = os.path.join(OUT, tag)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(ATLAS_SRC):
            # ⚠️ **不要**复制 `.config.json`：它里面写着 `"skeleton": "<原产物>.json"`，
            # 复制过来会让查看器去找不存在的骨架 ⇒ 白屏（本轮踩过）。
            if f.endswith((".atlas", ".png")):
                shutil.copy2(os.path.join(ATLAS_SRC, f), os.path.join(d, f))
        cfg = os.path.join(d, ".config.json")
        if os.path.exists(cfg):
            os.replace(cfg, cfg + ".bak")
        j = {
            "skeleton": {"hash": "synth-" + tag, "spine": "3.8.99",
                         "x": 0, "y": 0, "width": 0, "height": 0, "fps": 60},
            "bones": [
                {"name": "root", "x": 0, "y": 0},
                {"name": "A", "parent": "root", "x": 0, "y": 120},
                {"name": "B", "parent": "A", "x": 0, "y": 120,
                 "rotation": rot, "scaleX": sx, "scaleY": sy},
                {"name": "C", "parent": "B", "x": 0, "y": 120},
            ],
            "slots": [{"name": "probe", "bone": "C", "attachment": "probe"}],
            "skins": [{"name": "default", "attachments": {"probe": {"probe": {
                "type": "mesh", "path": "tex0",
                "uvs": [0, 0, 1, 0, 1, 1, 0, 1],
                "triangles": [0, 1, 2, 0, 2, 3], "width": 0, "height": 0,
                "vertices": [-40, -40, 40, -40, 40, 40, -40, 40]}}}}],
            "animations": {"Start": {"bones": {
                "root": {"translate": [{"time": 0, "x": 0, "y": 0}]},
                "A": {"translate": [{"time": 0, "x": 0, "y": 120}]},
                "B": {"translate": [{"time": 0, "x": 0, "y": 120}],
                      "rotate": [{"time": 0, "angle": rot}],
                      "scale": [{"time": 0, "x": sx, "y": sy}]},
                "C": {"translate": [{"time": 0, "x": 0, "y": 120}]},
            }}},
        }
        json.dump(j, open(os.path.join(d, "synth_static.json"), "w",
                          encoding="utf-8"), ensure_ascii=False)
        made.append((tag, d))
    return made


def render(made, size=320):
    if RENDER_ROOT not in sys.path:
        sys.path.insert(0, RENDER_ROOT)
    from render_lib.headless import HeadlessGL
    from render_lib.renderers import Session, _bind
    from render_lib.scanner import detect_spine_dir
    from renderer_src.SpineRender import SpineRender
    import numpy as np
    from PIL import Image

    gl = HeadlessGL(size, size, shader_dir=os.path.join(RENDER_ROOT, "ShaderCode"))
    session = Session(gl, size, size, [1.0, 1.0, 1.0])
    lines = []
    try:
        for tag, d in made:
            p = os.path.join(d, tag + ".png")
            try:
                struct = detect_spine_dir(d)
                r = SpineRender(session.rw)
                r.Init(session.viewport())
                r.config["Skeleton"], r.config["Atlas"], pngs, r.config["isBinary"] = struct
                r.config["Pngs"] = json.dumps(pngs)
                r.isPma = "pma" in os.path.basename(struct[1]).lower()
                r.Update(d)
                # 先渲 setup（不套动画）：本轮要判的是"骨链/镜像"，不是时间轴
                r.ClearAnimations()
                _bind(session)
                r.Draw(0, session.background)
                session.read().save(p)
                r.Dispose()
                a = np.asarray(Image.open(p).convert("RGB"), np.int16)
                m = a.min(axis=2) < 240
                ys, xs = np.where(m)
                box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()),
                       int(m.sum())) if len(xs) else None
            except Exception as ex:                 # noqa: BLE001
                box = "失败 %r" % (ex,)
            line = "%-16s %s" % (tag, box)
            print(line)
            lines.append(line)
    finally:
        try:
            gl.release()
        except Exception:                        # noqa: BLE001
            pass
    open(os.path.join(OUT, "result.txt"), "w", encoding="utf-8").write("\n".join(lines))


if __name__ == "__main__":
    render(build())
