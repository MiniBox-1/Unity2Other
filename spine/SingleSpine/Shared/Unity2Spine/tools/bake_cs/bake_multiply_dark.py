# -*- coding: utf-8 -*-
r"""把 `blend=multiply`（Unity 的 Particles/Multiply 影子）**烘成"暗色半透明"**，
这样在**不支持按槽位混合**的查看器里也能看出是影子（而不是浅粉贴图）。

原理：
  · Unity 乘法：`out = dst × tex.rgb`（把背景乘暗）；
  · 普通 alpha ：`out = dst×(1-a) + src×a`。取 `src = 黑`，就等价于"把背景压暗 a"。
  所以把颜色改成黑（丢掉 RGB 动画，保留 alpha 的淡入淡出）即可近似，且**不需要
  动图集**（贴图不动）。需要精确乘法语义时就不要用这个脚本，直接用
  `blend=multiply`（Spine 官方运行时支持）。

用法:
    python bake_multiply_dark.py --in <产物目录> --out <新产物目录>
"""

import argparse
import io
import json
import os
import shutil
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--keep-blend", action="store_true",
                    help="保留 blend=multiply（默认改成 normal，因为查看器不认 multiply）")
    a = ap.parse_args()

    os.makedirs(a.dst, exist_ok=True)
    for fn in os.listdir(a.src):
        sp, dp = os.path.join(a.src, fn), os.path.join(a.dst, fn)
        if os.path.isfile(sp):
            shutil.copy2(sp, dp)
    jn = [f for f in os.listdir(a.dst) if f.endswith("_static.json")][0]
    p = os.path.join(a.dst, jn)
    S = json.load(io.open(p, encoding="utf-8-sig"))
    mul = [s for s in S["slots"] if s.get("blend") == "multiply"]
    names = {s["name"] for s in mul}
    for s in mul:
        h = s.get("color") or "ffffff00"
        s["color"] = "000000" + h[6:]            # 只保留 alpha
        if not a.keep_blend:
            s["blend"] = "normal"
    nfr = 0
    for an, A in S["animations"].items():
        for slot, v in (A.get("slots") or {}).items():
            if slot not in names:
                continue
            for f in (v.get("color") or []):
                h = f.get("color") or "ffffff00"
                f["color"] = "000000" + h[6:]
                nfr += 1
    with io.open(p, "w", encoding="utf-8") as fh:
        json.dump(S, fh, ensure_ascii=False, separators=(",", ":"))
    print("改了 %d 个 multiply 槽位、%d 个颜色帧 -> %s" % (len(mul), nfr, p))
    # 重建 .skel
    skel = os.path.splitext(p)[0] + ".skel"
    r = subprocess.run([sys.executable, "-m", "ngui2spine.spine38_binary_writer", p],
                       cwd=r"D:\VB\Unity2Spine", capture_output=True, text=True)
    print("  重建 skel: rc=%s %s" % (r.returncode, (r.stdout or "")[-120:].strip()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
