# -*- coding: utf-8 -*-
r"""**骨链深度二分**：把同一个手搓探针 quad 依次挂到骨链的不同深度上渲染。

目的：定位"查看器对我们这条骨链的组合"从哪一层开始与预期不一致。
（背景：根骨挂 quad 正常、深骨 `Bone_Head` 挂 quad 一点墨迹都没有。）

用法：python tools\probe_chain.py [--size 320]
"""
import argparse
import json
import os
import shutil
import sys

BASE = r"D:\VB\MutiBone"
SRC = os.path.join(BASE, "out", "_bones4", "banshee_skin1")
WORK = os.path.join(BASE, "out", "_probe_chain")
RENDER_ROOT = r"D:\VB\Viewer\Render\v4"

# 从根到深，逐个挂探针
CHAIN = [
    ("01_root", "banshee_skin1_"),
    ("02_model_root", "2DModel_BR_Banshee_NS1_root_"),
    ("03_size_root", "Size_root_"),
    ("04_global_ctrl", "Global_CTRL_"),
    ("05_pelvis", "Bone_Pelvis_"),
    ("06_spine1", "Bone_Spine1_"),
    ("07_spine2", "Bone_Spine2_"),
    ("08_nack", "Bone_Nack_"),
    ("09_head", "Bone_Head_"),
]


def build():
    jp = [f for f in os.listdir(SRC) if f.endswith("_static.json")][0]
    base = json.load(open(os.path.join(SRC, jp), encoding="utf-8"))
    made = []
    for tag, prefix in CHAIN:
        d = os.path.join(WORK, tag)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(SRC):
            if f.endswith((".atlas", ".png")) or f == ".config.json":
                shutil.copy2(os.path.join(SRC, f), os.path.join(d, f))
        j = json.loads(json.dumps(base))
        hit = [b["name"] for b in j["bones"] if b["name"].startswith(prefix)]
        if not hit:
            print("[skip] 找不到骨前缀 %s" % prefix)
            continue
        bone = hit[0]
        j["slots"] = [{"name": "probe", "bone": bone, "attachment": "probe"}]
        j["skins"][0]["attachments"] = {"probe": {"probe": {
            "type": "mesh", "path": "tex0",
            "uvs": [0, 0, 1, 0, 1, 1, 0, 1],
            "triangles": [0, 1, 2, 0, 2, 3], "width": 0, "height": 0,
            "vertices": [-60, -60, 60, -60, 60, 60, -60, 60]}}}
        json.dump(j, open(os.path.join(d, jp), "w", encoding="utf-8"),
                  ensure_ascii=False)
        made.append((tag, bone, d))
    return made


def render(made, size):
    if RENDER_ROOT not in sys.path:
        sys.path.insert(0, RENDER_ROOT)
    from render_lib.headless import HeadlessGL
    from render_lib.renderers import Session, _bind
    from render_lib.scanner import detect_spine_dir
    from renderer_src.SpineRender import SpineRender
    import numpy as np
    from PIL import Image

    lines = []
    gl = HeadlessGL(size, size, shader_dir=os.path.join(RENDER_ROOT, "ShaderCode"))
    session = Session(gl, size, size, [1.0, 1.0, 1.0])
    try:
        for tag, bone, d in made:
            out = os.path.join(d, "%s.png" % tag)
            try:
                struct = detect_spine_dir(d)
                r = SpineRender(session.rw)
                r.Init(session.viewport())
                r.config["Skeleton"], r.config["Atlas"], pngs, r.config["isBinary"] = struct
                r.config["Pngs"] = json.dumps(pngs)
                r.isPma = "pma" in os.path.basename(struct[1]).lower()
                r.Update(d)
                r.SetAnimation("Start", loop=True, static=True)
                r.SetAnimationTime("Start", 0)
                _bind(session)
                r.Draw(0, session.background)
                session.read().save(out)
                r.Dispose()
                a = np.asarray(Image.open(out).convert("RGB"), np.int16)
                m = a.min(axis=2) < 240
                ys, xs = np.where(m)
                box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()),
                       int(m.sum())) if len(xs) else None
                line = "%-14s %-52s %s" % (tag, bone[:52], box)
            except Exception as ex:                 # noqa: BLE001
                line = "%-14s %-52s 失败：%r" % (tag, bone[:52], ex)
            print(line)
            lines.append(line)
    finally:
        try:
            gl.release()
        except Exception:                        # noqa: BLE001
            pass
    with open(os.path.join(WORK, "result.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=320)
    a = ap.parse_args()
    made = build()
    print("探针变体 %d 个，开始逐个渲染（同一进程、串行）" % len(made))
    render(made, a.size)


if __name__ == "__main__":
    main()
