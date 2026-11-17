# -*- coding: utf-8 -*-
r"""判定查看器/引擎把骨时间轴的 translate 当**绝对量**还是**增量**。

做法：两个着色 quad（红在根骨、蓝在深骨 y=200），对比三种情况的**红蓝垂直距离**：
  setup（无动画）           绝对/增量都一样：200
  动画 key = setup(200)      绝对 → 200；增量 → 400
  动画 key = 400             绝对 → 400；增量 → 600
距离按"setup 的距离 D"归一化后即可判定。

用法：python tools\synth_delta_test.py
"""
import json
import os
import shutil
import sys

BASE = r"D:\VB\MutiBone"
OUT = os.path.join(BASE, "out", "_synth_delta")
ATLAS_SRC = r"D:\VB\Unity2Spine\_probe50_rt4\banshee_skin1"
RENDER_ROOT = r"D:\VB\Viewer\Render\v4"


def quad(color):
    return {"type": "mesh", "path": "tex0",
            "uvs": [0, 0, 1, 0, 1, 1, 0, 1],
            "triangles": [0, 1, 2, 0, 2, 3], "width": 0, "height": 0,
            "color": color,
            "vertices": [-30, -30, 30, -30, 30, 30, -30, 30]}


def build():
    os.makedirs(OUT, exist_ok=True)
    base = {
        "skeleton": {"hash": "synth-delta", "spine": "3.8.99",
                     "x": 0, "y": 0, "width": 0, "height": 0, "fps": 60},
        "bones": [{"name": "root", "x": 0, "y": 0},
                  {"name": "B", "parent": "root", "x": 0, "y": 200}],
        "slots": [{"name": "s_red", "bone": "root", "attachment": "red"},
                  {"name": "s_blue", "bone": "B", "attachment": "blue"}],
        "skins": [{"name": "default", "attachments": {
            "s_red": {"red": quad("ff0000ff")},
            "s_blue": {"blue": quad("0000ffff")}}}],
    }
    cases = {
        "a_setup": None,
        "b_key_setup": 200,
        "c_key_double": 400,
        "d_key_zero": 0,
    }
    made = []
    for tag, ky in cases.items():
        d = os.path.join(OUT, tag)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(ATLAS_SRC):
            if f.endswith((".atlas", ".png")):
                shutil.copy2(os.path.join(ATLAS_SRC, f), os.path.join(d, f))
        j = json.loads(json.dumps(base))
        j["animations"] = {"Start": {} if ky is None else {"bones": {"B": {
            "translate": [{"time": 0, "x": 0, "y": ky}]}}}}
        json.dump(j, open(os.path.join(d, "synth_static.json"), "w",
                          encoding="utf-8"), ensure_ascii=False)
        made.append((tag, d, ky is None))
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
    out = []
    try:
        for tag, d, setup in made:
            p = os.path.join(d, tag + ".png")
            struct = detect_spine_dir(d)
            r = SpineRender(session.rw)
            r.Init(session.viewport())
            r.config["Skeleton"], r.config["Atlas"], pngs, r.config["isBinary"] = struct
            r.config["Pngs"] = json.dumps(pngs)
            r.isPma = False
            r.Update(d)
            if setup:
                r.ClearAnimations()
            else:
                r.SetAnimation("Start", loop=True, static=True)
                r.SetAnimationTime("Start", 0)
            _bind(session)
            r.Draw(0, session.background)
            session.read().save(p)
            r.Dispose()
            a = np.asarray(Image.open(p).convert("RGB"), np.int16)
            red = (a[:, :, 0] > 150) & (a[:, :, 1] < 100) & (a[:, :, 2] < 100)
            blue = (a[:, :, 2] > 150) & (a[:, :, 0] < 100) & (a[:, :, 1] < 100)
            if red.sum() < 20 or blue.sum() < 20:
                line = "%-12s red=%d blue=%d（着色没生效？）" % (tag, red.sum(), blue.sum())
            else:
                yr = np.where(red)[0].mean()
                yb = np.where(blue)[0].mean()
                line = "%-12s 红=%d 蓝=%d  垂直差=%.1f px" % (tag, red.sum(), blue.sum(),
                                                            abs(yb - yr))
            print(line)
            out.append(line)
    finally:
        try:
            gl.release()
        except Exception:                        # noqa: BLE001
            pass
    open(os.path.join(OUT, "result.txt"), "w", encoding="utf-8").write("\n".join(out))


if __name__ == "__main__":
    render(build())
