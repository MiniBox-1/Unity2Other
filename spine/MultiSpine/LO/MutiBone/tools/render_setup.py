# -*- coding: utf-8 -*-
r"""用查看器的渲染库渲**setup 姿态**（不套任何动画）——用来把"骨架/网格错"和
"动画错"分开。

用法：python _scratch\render_setup.py <spine 目录> <输出 png> [尺寸]
"""
import os
import sys

RENDER_ROOT = r"D:\VB\Viewer\Render"


def main():
    spine_dir, out = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    if RENDER_ROOT not in sys.path:
        sys.path.insert(0, RENDER_ROOT)
    from render_lib.headless import HeadlessGL
    from render_lib.renderers import Session, _bind
    from render_lib.scanner import detect_spine_dir
    from renderer_src.SpineRender import SpineRender

    shader_dir = os.path.join(RENDER_ROOT, "ShaderCode")
    gl = HeadlessGL(size, size, shader_dir=shader_dir)
    session = Session(gl, size, size, [1.0, 1.0, 1.0])
    try:
        struct = detect_spine_dir(spine_dir)
        r = SpineRender(session.rw)
        r.Init(session.viewport())
        r.config["Skeleton"], r.config["Atlas"], pngs, r.config["isBinary"] = struct
        r.config["Pngs"] = __import__("json").dumps(pngs)
        r.isPma = "pma" in os.path.basename(struct[1]).lower()
        r.Update(spine_dir)
        r.ClearAnimations()          # ← setup 姿态
        _bind(session)
        r.Draw(0, session.background)
        session.read().save(out)
        print("->", out)
    finally:
        try:
            gl.release()
        except Exception:            # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
