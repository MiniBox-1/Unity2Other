# -*- coding: utf-8 -*-
r"""批量同源 A/B：deform vs 多骨骼（同一 prefab），输出 ink/平均差。

每步都通过 `mem_probe.ps1` 串行执行（转换 4500 MB / 渲染 3000 MB 护栏）。

用法：python tools\batch_ab.py
"""
import glob
import argparse
import json
import os
import subprocess
import sys

BASE = r"D:\VB\MutiBone"
PROJ = r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old"
ASSETS = os.path.join(PROJ, "Assets")
SCENE = os.path.join(ASSETS, "Sences", "save.unity")
PRE_DIR = os.path.join(ASSETS, "Prefabs")
OUT = os.path.join(BASE, "out", "_batch")
PY = r"D:\Anconda\python.exe"
VIEW = r"D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe"
MEMP = r"D:\VB\Unity2Spine\tools\mem_probe.ps1"
RT = r"D:\VB\Unity2Spine\tools\rt_frames.py"

CHARS = [
    "2DModel_BR_NightAngel_NS2.uAnim",
    "2DModel_PECS_CoCoWhiteShell_N.uAnim",
    "2DModel_3P_ConstantiaS2_NS0.uAnim",
    "2DModel_PECS_Babariana_NS1.uAnim",
    "2DModel_3P_Daphne_NS1.uAnim",
]


def probe(exe, args, cwd, limit):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", MEMP,
           "-Exe", exe, "-ArgList", "|".join(args), "-LimitMB", str(limit),
           "-WorkDir", cwd]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=2400)
    tail = [l for l in (p.stdout or "").splitlines() if "peak=" in l]
    return (tail[-1] if tail else "（无内存行）"), p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simplify", type=float, default=0.05,
                    help="多骨骼线性关键帧抽稀误差；0=关闭")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for ch in CHARS:
        prefab = os.path.join(PRE_DIR, ch + ".prefab")
        if not os.path.isfile(prefab):
            print("[skip] 没找到", prefab)
            continue
        tag = ch.replace(".uAnim", "")
        ddir = os.path.join(OUT, tag, "deform")
        mdir = os.path.join(OUT, tag, "multi")
        print("==== %s" % tag)
        line, rc = probe(PY, ["-m", "ngui2spine.static_prefab_spine", prefab, ddir,
                              "--assets", ASSETS, "--scene", SCENE,
                              "--json", "--no-face-check"],
                         r"D:\VB\Unity2Spine", 4500)
        print("   deform:", line)
        if rc != 0 or not glob.glob(os.path.join(ddir, "*_static.json")):
            print("   [skip] deform 失败")
            continue
        line, rc = probe(PY, [os.path.join(BASE, "src", "convert_bones.py"), prefab,
                              mdir, "--assets", ASSETS, "--scene", SCENE,
                              "--reuse-from", ddir,
                              "--simplify", str(a.simplify)], BASE, 4500)
        print("   multi :", line)
        mj = glob.glob(os.path.join(mdir, "*_static.json"))
        if rc != 0 or not mj:
            print("   [skip] multi 失败")
            continue
        anims = list(json.load(open(mj[0], encoding="utf-8"))["animations"])
        anim = next((a for a in anims if "lobby" in a.lower()), anims[0])
        fd = os.path.join(OUT, tag, "fd")
        fm = os.path.join(OUT, tag, "fm")
        probe(VIEW, [RT, ddir, anim, "--out", fd, "--times", "0", "--size", "360"], BASE, 3000)
        probe(VIEW, [RT, mdir, anim, "--out", fm, "--times", "0", "--size", "360"], BASE, 3000)
        try:
            from PIL import Image
            import numpy as np
            pa = glob.glob(os.path.join(fm, "*__t000.png"))
            pb = glob.glob(os.path.join(fd, "*__t000.png"))
            if not (pa and pb):
                print("   [skip] 缺渲染图")
                continue
            A = np.asarray(Image.open(pa[0]).convert("RGB"), np.int16)
            B = np.asarray(Image.open(pb[0]).convert("RGB"), np.int16)
            d = np.abs(A - B).max(axis=2)
            ma, mb = A.min(axis=2) < 240, B.min(axis=2) < 240
            row = "%-28s anim=%-8s ink=%6d/%6d  mean=%6.2f  gt32=%6d" % (
                tag, anim, int(ma.sum()), int(mb.sum()), float(d.mean()),
                int((d > 32).sum()))
        except Exception as ex:                     # noqa: BLE001
            row = "%-28s 对比失败 %r" % (tag, ex)
        print("   " + row)
        rows.append(row)
    open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8").write("\n".join(rows))


if __name__ == "__main__":
    main()
