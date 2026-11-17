# -*- coding: utf-8 -*-
"""一次进程内渲染同一动画的**多个时刻**（离线预览渲染器的多帧版）。

`render_offline.py` 的 `spine.time_norm` 只能给一个标量，逐帧核对要反复起
进程（每起一次都要重建 GL 上下文，几秒钟）。这里复用同一个 GL 会话，
把一条动画在多个时刻各渲一张，方便"和 Unity 参考帧逐帧对"。

用法：
    python tools\\rt_frames.py <spine目录> <动画名> --out <输出目录> \
        --times 0.0,0.1,0.2 --size 900 --pma auto [--skin default]
"""
import argparse
import json
import os
import sys

# 渲染器已迁到 v4 子目录（2026-10-08 发现旧路径下只剩 v3/v4 两个子目录）。
RENDER_ROOT = r"D:\VB\Viewer\Render\v4"
if not os.path.isdir(os.path.join(RENDER_ROOT, "render_lib")):
    RENDER_ROOT = r"D:\VB\Viewer\Render"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("spine_dir")
    ap.add_argument("animation")
    ap.add_argument("--out", required=True)
    ap.add_argument("--times", default="0.0,0.2,0.4,0.6,0.8")
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--pma", default="auto", choices=["auto", "true", "false"])
    ap.add_argument("--skin", default=None)
    ap.add_argument("--bg", default="255,255,255,255")
    a = ap.parse_args(argv)

    if RENDER_ROOT not in sys.path:
        sys.path.insert(0, RENDER_ROOT)
    from render_lib.headless import HeadlessGL
    from render_lib.renderers import Session, _bind
    from render_lib.scanner import detect_spine_dir
    from renderer_src.SpineRender import SpineRender

    times = [float(x) for x in str(a.times).split(",") if x.strip() != ""]
    bg = [int(x) for x in str(a.bg).split(",")]
    if len(bg) == 3:
        bg.append(255)
    os.makedirs(a.out, exist_ok=True)

    shader_dir = os.path.join(RENDER_ROOT, "ShaderCode")
    gl = HeadlessGL(a.size, a.size, shader_dir=shader_dir)
    session = Session(gl, a.size, a.size, [v / 255.0 for v in bg])
    try:
        struct = detect_spine_dir(a.spine_dir)
        if struct is None:
            raise RuntimeError("Spine 结构识别失败：%s" % a.spine_dir)
        r = SpineRender(session.rw)
        r.Init(session.viewport())
        r.config["Skeleton"], r.config["Atlas"], pngs, r.config["isBinary"] = struct
        r.config["Pngs"] = json.dumps(pngs)
        if a.pma == "auto":
            lower = os.path.basename(struct[1]).lower()
            pma = "pma" in lower
            if not pma:
                try:
                    with open(struct[1], "r", encoding="utf-8",
                              errors="ignore") as f:
                        pma = ("premultipliedalpha: true"
                               in f.read().replace(" ", "").lower())
                except OSError:
                    pass
        else:
            pma = (a.pma == "true")
        r.isPma = pma
        r.Update(a.spine_dir)
        if r.state.UnLoad or r.instance is None:
            raise RuntimeError("Spine 加载失败（结构不完整或版本不支持）")
        anim = a.animation
        if anim not in (r.Animations or []):
            raise RuntimeError("动画 %r 不存在，可选：%s"
                               % (anim, ", ".join(r.Animations or [])))
        if a.skin:
            r.SetSkin(a.skin)
        base = os.path.basename(os.path.normpath(a.spine_dir)) or "spine"
        print("[rt] pma=%s skins=%s anims=%s"
              % (pma, getattr(r, "Skins", None), list(r.Animations or [])))
        for t in times:
            r.SetAnimation(anim, loop=True, static=True)
            if t:
                r.SetAnimationTime(anim, t)
            _bind(session)
            r.Draw(0, session.background)
            img = session.read()
            out = os.path.join(a.out, "%s__%s__t%03d.png"
                               % (base, anim, int(round(t * 1000))))
            img.save(out)
            print("[rt] ->", out)
        try:
            r.Dispose()
        except Exception:                        # noqa: BLE001
            pass
    finally:
        try:
            gl.release()
        except Exception:                        # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
