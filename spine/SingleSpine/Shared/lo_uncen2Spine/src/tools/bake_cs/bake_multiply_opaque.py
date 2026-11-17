# -*- coding: utf-8 -*-
r"""把 `blend=multiply` 槽位用到的图集区域**改成不透明**（α=255，rgb 不变）。

为什么：Spine 的 multiply 混合是 `out = dst×src.rgb + src.rgb×(1−src.a)`
（`glBlendFunc(DST_COLOR, ONE_MINUS_SRC_ALPHA)`）。只有 **src.a = 1** 时才退化成
纯乘法 `out = dst×src.rgb` —— 也就是 Unity 的 `Particles/Multiply`。而项目的影子
贴图本身是"浅粉 + α≈0.29"，直接用会被加上一大块亮色（实测亮度 197→225，更白）。

Unity 的乘法 shader 用的是 `tex.rgb`（α 不参与 rgb 乘法），所以把 α 置 1 才是等价做法。
只改这些槽位自己的 UV 矩形内的像素，不动 JSON/skel（blend=multiply 已经写上）。

用法:
    python bake_multiply_opaque.py --product <产物目录> [--dry-run]
"""

import argparse
import io
import json
import os
import re

from PIL import Image


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def atlas_page_map(atlas_path):
    """region 名 -> 页文件名（本链路里 region 名就是 texN）。"""
    out = {}
    cur = None
    for ln in io.open(atlas_path, encoding="utf-8").read().splitlines():
        s = ln.strip()
        if s.lower().endswith(".png"):
            cur = s
        elif s and cur and ":" not in s:
            out[s] = cur
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    jn = [f for f in os.listdir(a.product) if f.endswith("_static.json")][0]
    S = load_json(os.path.join(a.product, jn))
    at = [f for f in os.listdir(a.product) if f.endswith(".atlas")][0]
    pages = atlas_page_map(os.path.join(a.product, at))
    att = S["skins"][0]["attachments"]
    mul = [s["name"] for s in S["slots"] if s.get("blend") == "multiply"]
    print("multiply 槽位 %d 个：%s" % (len(mul), ", ".join(mul)))

    # 收集 (页, uv 矩形)
    boxes = {}
    for nm in mul:
        for av in (att.get(nm) or {}).values():
            u = av.get("uvs") or []
            if not u:
                continue
            pg = pages.get(av.get("path") or "")
            if not pg:
                print("  [warn] %s 的页找不到：%r" % (nm, av.get("path")))
                continue
            xs, ys = u[0::2], u[1::2]
            r = (min(xs), min(ys), max(xs), max(ys))
            boxes.setdefault((pg, r), []).append(nm)

    for (pg, r), nms in sorted(boxes.items()):
        p = os.path.join(a.product, pg)
        im = Image.open(p).convert("RGBA")
        W, H = im.size
        box = (max(0, int(r[0] * W) - 1), max(0, int(r[1] * H) - 1),
               min(W, int(r[2] * W) + 2), min(H, int(r[3] * H) + 2))
        crop = im.crop(box)
        px = list(crop.getdata())
        n_change = sum(1 for q in px if q[3] != 255)
        print("  %-38s %s 区域内 %d 像素，其中 α≠255 的 %d 个 -> 置 255（%s）"
              % (os.path.basename(pg), "矩形%s" % (box,), len(px), n_change,
                 ", ".join(nms)[:40]))
        if a.dry_run or n_change == 0:
            continue
        crop.putdata([(q[0], q[1], q[2], 255) for q in px])
        im.paste(crop, box[:2])
        im.save(p)
    if a.dry_run:
        print("(dry-run，未写文件)")
    else:
        print("已就地更新图集 PNG（JSON/skel 不动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
