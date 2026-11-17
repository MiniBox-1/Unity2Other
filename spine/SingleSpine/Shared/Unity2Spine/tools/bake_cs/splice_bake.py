# -*- coding: utf-8 -*-
r"""把一份 bake.json 里某些 state 的片段，换成另一份 bake.json 里的同名片段。

用途：只重采少数 state（例如 Alice 的 curtain 需要叠基底层重采），
不必把整条角色的 5 条 state 全跑一遍。

用法:
    python splice_bake.py --base <原 bake.json> --replace <新 bake.json> ^
        --out <合并后 bake.json>
"""

import argparse
import io
import json
import os
import sys


def load(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--replace", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    base = load(a.base)
    rep = load(a.replace)
    if (base.get("product") != rep.get("product")
            or float(base.get("fps")) != float(rep.get("fps"))):
        print("[warn] 两份 bake 的 product/fps 不一致：%s vs %s"
              % (base.get("product"), rep.get("product")))

    rmap = {c["state"]: c for c in rep.get("clips", [])}
    out = []
    used = set()
    for c in base.get("clips", []):
        if c["state"] in rmap:
            out.append(rmap[c["state"]])
            used.add(c["state"])
            print("  替换 %-24s 帧 %d -> %d，渲染器 %d -> %d"
                  % (c["state"], len(c.get("times") or []),
                     len(rmap[c["state"]].get("times") or []),
                     len(c.get("renderers") or []),
                     len(rmap[c["state"]].get("renderers") or [])))
        else:
            out.append(c)
    for st, c in rmap.items():
        if st not in used:
            out.append(c)
            print("  新增 %s" % st)

    merged = dict(base)
    merged["clips"] = out
    with io.open(a.out, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, separators=(",", ":"))
    print("写出 %s（%.1f MB，%d 条 state）"
          % (a.out, os.path.getsize(a.out) / 1048576.0, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
