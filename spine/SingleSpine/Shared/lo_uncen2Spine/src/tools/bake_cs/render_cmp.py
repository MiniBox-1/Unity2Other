# -*- coding: utf-8 -*-
r"""用 D:\VB\Viewer\Render\v4 的离线渲染器，把「基线产物」和「CS 合并后产物」
在同一时刻各渲一张，给出逐像素差异统计 + 三联图（基线 | 合并 | 差异放大）。

为什么自己写而不直接用 src/tools\rt_frames.py：
  1 要在**同一个 GL 会话**里渲两份产物（AGENTS.md：一次只跑一个渲染进程）；
  2 rt_frames.py 的 RENDER_ROOT 还指着旧的 D:\VB\Viewer\Render（已迁到 v4）。

用法（必须用 v4 的 venv 解释器）:
    & "D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe" render_cmp.py ^
        --base <基线产物目录> --merged <合并后产物目录> --anim lobby ^
        --times 0.5,2.0,4.0,6.0 --out <图片输出目录> [--size 800] [--amp 6]
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
import sys

RENDER_ROOT = _resolve(r"D:\VB\Viewer\Render\v4")


def anim_duration(spine_dir, anim, skeleton_json=None):
    """秒。优先读同目录的 _static_info.json，其次从 skeleton JSON 里扫最大关键帧时间。

    为什么需要它：SpineRender.SetAnimationTime(name, normalizeTime) 收的是
    **归一化时间（0~1）**，不是秒 —— 直接传秒会让 >=1 的时刻全部绕回 0。
    """
    info = os.path.join(spine_dir, "_static_info.json")
    if os.path.isfile(info):
        try:
            with open(info, encoding="utf-8-sig") as f:
                d = json.load(f)
            for it in d.get("animations") or []:
                if it.get("name") == anim and it.get("duration"):
                    return float(it["duration"]), "info"
        except Exception:
            pass
    js = skeleton_json
    if js is None:
        for fn in os.listdir(spine_dir):
            if fn.endswith(".json") and not fn.startswith("_"):
                js = os.path.join(spine_dir, fn)
                break
    if js and os.path.isfile(js):
        try:
            with open(js, encoding="utf-8-sig") as f:
                d = json.load(f)
            blk = (d.get("animations") or {}).get(anim) or {}
            mx = 0.0

            def walk(o):
                nonlocal mx
                if isinstance(o, dict):
                    for k, v in o.items():
                        if k in ("time", "t") and isinstance(v, (int, float)):
                            mx = max(mx, float(v))
                        else:
                            walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(blk)
            if mx > 0:
                return mx, "json"
        except Exception:
            pass
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--merged", required=True)
    ap.add_argument("--anim", required=True)
    ap.add_argument("--times", default="0.5,2.0,4.0,6.0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=800)
    ap.add_argument("--amp", type=int, default=6, help="差异图放大倍数")
    ap.add_argument("--skin", default=None)
    a = ap.parse_args()

    if RENDER_ROOT not in sys.path:
        sys.path.insert(0, RENDER_ROOT)
    from render_lib.headless import HeadlessGL
    from render_lib.renderers import Session, _bind
    from render_lib.scanner import detect_spine_dir
    from renderer_src.SpineRender import SpineRender

    import numpy as np
    from PIL import Image

    times = [float(x) for x in a.times.split(",") if x.strip()]
    os.makedirs(a.out, exist_ok=True)
    shader_dir = os.path.join(RENDER_ROOT, "ShaderCode")
    gl = HeadlessGL(a.size, a.size, shader_dir=shader_dir)
    session = Session(gl, a.size, a.size, [1.0, 1.0, 1.0, 1.0])

    def load(d):
        struct = detect_spine_dir(d)
        if struct is None:
            raise RuntimeError("Spine 结构识别失败：%s" % d)
        r = SpineRender(session.rw)
        r.Init(session.viewport())
        r.config["Skeleton"], r.config["Atlas"], pngs, r.config["isBinary"] = struct
        r.config["Pngs"] = json.dumps(pngs)
        pma = "pma" in os.path.basename(struct[1]).lower()
        if not pma:
            try:
                with open(struct[1], "r", encoding="utf-8", errors="ignore") as f:
                    pma = "premultipliedalpha: true" in f.read().replace(" ", "").lower()
            except OSError:
                pass
        r.isPma = pma
        r.Update(d)
        if r.state.UnLoad or r.instance is None:
            raise RuntimeError("Spine 加载失败：%s" % d)
        if a.anim not in (r.Animations or []):
            raise RuntimeError("动画 %r 不存在，可选：%s"
                               % (a.anim, ", ".join(r.Animations or [])))
        if a.skin:
            r.SetSkin(a.skin)
        dur, src = anim_duration(d, a.anim, struct[0])
        return r, dur, src

    def shots(d, tag):
        out = {}
        r, dur, src = load(d)
        print("[cmp] %s 动画 %s 时长=%s 秒（来源:%s）" % (tag, a.anim, dur, src))
        try:
            for t in times:
                r.SetAnimation(a.anim, loop=True, static=True)
                if t and dur:
                    r.SetAnimationTime(a.anim, min(0.999, t / dur))
                elif t:
                    raise RuntimeError("拿不到动画时长，无法把秒换算成归一化时间")
                _bind(session)
                r.Draw(0, session.background)
                img = Image.fromarray(np.asarray(session.read()).astype("uint8"))
                p = os.path.join(a.out, "%s__%s__t%03d.png"
                                 % (tag, a.anim, int(round(t * 1000))))
                img.save(p)
                out[t] = img
                print("[cmp] %s t=%.3f -> %s" % (tag, t, p))
        finally:
            try:
                r.Dispose()
            except Exception:
                pass
        return out

    try:
        A = shots(a.base, "base")
        B = shots(a.merged, "merged")
    finally:
        try:
            gl.release()
        except Exception:
            pass

    print()
    print("%6s | %17s | %10s | %8s | %6s | %-14s | %s"
          % ("时间", "内容像素 基线/合并", "有差异", "差>8", "最大差", "差异重心", "包围盒"))
    print("-" * 104)
    for t in times:
        ia = np.asarray(A[t])[:, :, :3].astype("int16")
        ib = np.asarray(B[t])[:, :, :3].astype("int16")
        d = np.abs(ia - ib).max(axis=2)
        nz = d > 1
        n8 = d > 8
        nwa = int((ia.min(axis=2) < 250).sum())
        nwb = int((ib.min(axis=2) < 250).sum())
        n = int(nz.sum())
        if n:
            ys, xs = np.nonzero(nz)
            cx, cy = float(xs.mean()), float(ys.mean())
            box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        else:
            cx = cy = 0.0
            box = (0, 0, 0, 0)
        print("%6.2f | %8d / %8d | %10d | %8d | %6d | (%6.1f,%6.1f) | %s"
              % (t, nwa, nwb, n, int(n8.sum()), int(d.max()), cx, cy, box))
        amp = np.clip(d.astype("int32") * a.amp, 0, 255).astype("uint8")
        diff_rgb = np.zeros((d.shape[0], d.shape[1], 3), dtype="uint8")
        diff_rgb[:, :, 0] = amp
        diff_rgb[:, :, 1] = 255 - amp
        diff_rgb[:, :, 2] = 255 - amp
        trio = np.concatenate([np.asarray(A[t])[:, :, :3],
                               np.asarray(B[t])[:, :, :3],
                               diff_rgb], axis=1)
        Image.fromarray(trio).save(os.path.join(
            a.out, "trio__%s__t%03d.png" % (a.anim, int(round(t * 1000)))))
    print()
    print("三联图：左=基线  中=CS合并后  右=差异x%d（红=有差异，青色=相同）" % a.amp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
