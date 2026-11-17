# -*- coding: utf-8 -*-
r"""在**真实多骨骼产物**上二分"一加动画就白屏/爆内存"：按 translate/rotate/scale 通道拆开渲染。

用法：python tools\anim_bisect.py
输出：out\_anim_bisect\result.txt
"""
import json
import os
import shutil
import sys

BASE = r"D:\VB\MutiBone"
SRC = os.path.join(BASE, "out", "banshee_skin1")
WORK = os.path.join(BASE, "out", "_anim_bisect")
RENDER_ROOT = r"D:\VB\Viewer\Render\v4"


def slim(a):
    """每个通道只留第一个键（避免全量键把内存撑爆）。"""
    for _bn, ch in (a.get("bones") or {}).items():
        for k, v in list(ch.items()):
            if isinstance(v, list) and len(v) > 1:
                ch[k] = v[:1]
    return a


def build():
    jp = [f for f in os.listdir(SRC) if f.endswith("_static.json")][0]
    src = json.load(open(os.path.join(SRC, jp), encoding="utf-8"))
    made = []
    cases = {
        "00_setup": None,
        "01_full": ("translate", "rotate", "scale"),
        "02_translate": ("translate",),
        "03_rotate": ("rotate",),
        "04_scale": ("scale",),
        "05_no_scale": ("translate", "rotate"),
        "06_scale_changed": ("translate", "rotate", "scale_changed"),
        "07_empty_anim": ("__empty__",),
        "08_only_changes": ("__changes__",),
        "09_root_only": ("__root__",),
        "10_delta_tr": ("__delta__",),
        "11_delta_t": ("__delta_t__",),
        "12_delta_r": ("__delta_r__",),
    }
    for tag, keep in cases.items():
        d = os.path.join(WORK, tag)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(SRC):
            if f.endswith((".atlas", ".png")):
                shutil.copy2(os.path.join(SRC, f), os.path.join(d, f))
        j = json.loads(json.dumps(src))
        if keep == ("__empty__",):
            j["animations"] = {"Start": {}}
            json.dump(j, open(os.path.join(d, jp), "w", encoding="utf-8"),
                      ensure_ascii=False)
            made.append((tag, d, False))
            continue
        if keep == ("__changes__",):
            bmap = {b["name"]: b for b in j["bones"]}
            for an in j["animations"]:
                for bn, ch in (j["animations"][an].get("bones") or {}).items():
                    b = bmap.get(bn, {})
                    for chn, setup_xy in (("translate", (b.get("x", 0), b.get("y", 0))),
                                          ("rotate", (b.get("rotation", 0),)),
                                          ("scale", (b.get("scaleX", 1), b.get("scaleY", 1)))):
                        ks = ch.get(chn) or []
                        if not ks:
                            continue
                        if chn == "rotate":
                            same = all(abs(k.get("angle", 0) - setup_xy[0]) < 1e-4 for k in ks)
                        else:
                            same = all(abs(k.get("x", 0) - setup_xy[0]) < 1e-4
                                       and abs(k.get("y", 0) - setup_xy[1]) < 1e-4 for k in ks)
                        if same:
                            ch.pop(chn, None)
            for an in j["animations"]:
                for bn, ch in (j["animations"][an].get("bones") or {}).items():
                    for k, v in list(ch.items()):
                        if isinstance(v, list) and len(v) > 1:
                            ch[k] = v[:1]
            json.dump(j, open(os.path.join(d, jp), "w", encoding="utf-8"),
                      ensure_ascii=False)
            made.append((tag, d, False))
            continue
        if keep == ("__root__",):
            root = j["bones"][0]["name"]
            ch = (j["animations"]["Start"].get("bones") or {}).get(root) or {}
            j["animations"] = {"Start": {"bones": {root: {
                k: (v[:1] if isinstance(v, list) else v) for k, v in ch.items()}}}}
            json.dump(j, open(os.path.join(d, jp), "w", encoding="utf-8"),
                      ensure_ascii=False)
            made.append((tag, d, False))
            continue
        if keep == ("__delta__",):
            bmap = {b["name"]: b for b in j["bones"]}
            for an in j["animations"]:
                for bn, ch in (j["animations"][an].get("bones") or {}).items():
                    b = bmap.get(bn, {})
                    if ch.get("translate"):
                        ch["translate"] = [{"time": k["time"],
                                            "x": k.get("x", 0) - b.get("x", 0),
                                            "y": k.get("y", 0) - b.get("y", 0)} for k in ch["translate"]]
                    if ch.get("rotate"):
                        ch["rotate"] = [{"time": k["time"],
                                         "angle": k.get("angle", 0) - b.get("rotation", 0)}
                                        for k in ch["rotate"]]
                    ch.pop("scale", None)
                    for kk, v in list(ch.items()):
                        if isinstance(v, list) and len(v) > 1:
                            ch[kk] = v[:1]
            json.dump(j, open(os.path.join(d, jp), "w", encoding="utf-8"),
                      ensure_ascii=False)
            made.append((tag, d, False))
            continue
        if keep in (("__delta_t__",), ("__delta_r__",)):
            bmap = {b["name"]: b for b in j["bones"]}
            do_t = keep == ("__delta_t__",)
            do_r = keep == ("__delta_r__",)
            for an in j["animations"]:
                for bn, ch in (j["animations"][an].get("bones") or {}).items():
                    b = bmap.get(bn, {})
                    if do_t and ch.get("translate"):
                        ch["translate"] = [{"time": k["time"],
                                            "x": k.get("x", 0) - b.get("x", 0),
                                            "y": k.get("y", 0) - b.get("y", 0)}
                                           for k in ch["translate"]]
                    if do_r and ch.get("rotate"):
                        ch["rotate"] = [{"time": k["time"],
                                         "angle": k.get("angle", 0) - b.get("rotation", 0)}
                                        for k in ch["rotate"]]
                    ch.pop("scale", None)
                    for kk, v in list(ch.items()):
                        if isinstance(v, list) and len(v) > 1:
                            ch[kk] = v[:1]
            json.dump(j, open(os.path.join(d, jp), "w", encoding="utf-8"),
                      ensure_ascii=False)
            made.append((tag, d, False))
            continue
        for an in j["animations"]:
            for _bn, ch in (j["animations"][an].get("bones") or {}).items():
                slim({"bones": {_bn: ch}})
                if keep is not None:
                    if "scale_changed" in keep:
                        # 只保留"真的变化过"的 scale（与 setup 不同）
                        b = {bb["name"]: bb for bb in src["bones"]}.get(_bn, {})
                        ks = ch.get("scale") or []
                        if ks and all(
                                abs(k.get("x", 1) - b.get("scaleX", 1)) < 1e-4
                                and abs(k.get("y", 1) - b.get("scaleY", 1)) < 1e-4
                                for k in ks):
                            ch.pop("scale", None)
                    for chn in list(ch):
                        if chn not in keep and chn != "scale":
                            ch.pop(chn)
        json.dump(j, open(os.path.join(d, jp), "w", encoding="utf-8"),
                  ensure_ascii=False)
        made.append((tag, d, tag == "00_setup"))
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
        for tag, d, setup in made:
            p = os.path.join(d, tag + ".png")
            try:
                struct = detect_spine_dir(d)
                r = SpineRender(session.rw)
                r.Init(session.viewport())
                r.config["Skeleton"], r.config["Atlas"], pngs, r.config["isBinary"] = struct
                r.config["Pngs"] = json.dumps(pngs)
                r.isPma = "pma" in os.path.basename(struct[1]).lower()
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
                m = a.min(axis=2) < 240
                ys, xs = np.where(m)
                box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()),
                       int(m.sum())) if len(xs) else None
            except Exception as ex:                 # noqa: BLE001
                box = "失败 %r" % (ex,)
            line = "%-14s %s" % (tag, box)
            print(line)
            lines.append(line)
    finally:
        try:
            gl.release()
        except Exception:                        # noqa: BLE001
            pass
    open(os.path.join(WORK, "result.txt"), "w", encoding="utf-8").write("\n".join(lines))


if __name__ == "__main__":
    render(build())
