# -*- coding: utf-8 -*-
r"""体检：产物里"影子/备选附件"这类槽位的**显隐（attachment 时间轴）**与
**位置（setup 平移 + deform）**，并可并排对比两份产物。

用法:
    python diag_shadow.py --dir <产物目录> [--dir <另一份>] --match Shadow
    python diag_shadow.py --dir <产物目录> --slot parts_Tail_Shadow
"""

import argparse
import io
import json
import math
import os


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)
    raise SystemExit("no _static.json in %s" % d)


def fmt_time(t):
    return ("%g" % round(float(t), 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--match", default="Shadow")
    ap.add_argument("--slot", action="append", default=[])
    ap.add_argument("--anim", default=None)
    a = ap.parse_args()

    prods = []
    for d in a.dir:
        S = load_json(find_json(d))
        info = load_json(os.path.join(d, "_static_info.json"))
        prods.append((os.path.basename(d.rstrip("\\/")) or d, d, S, info))

    slots = sorted(prods[0][2]["skins"][0]["attachments"])
    want = [s for s in slots
            if s in a.slot or (a.match and a.match.lower() in s.lower())]
    print("要看的槽位: %s" % want)

    # 每份产物的 setup 里这些槽位挂在哪个 bone 下、有没有平移/旋转
    for tag, d, S, info in prods:
        print("=" * 78)
        print("产物 %s" % d)
        bonelist = {b["name"]: b for b in S["bones"]}
        pm = {m.get("name"): m for m in (info.get("partsMeta") or [])}
        # bone -> slot 的父子关系
        par = {}
        for b in S["bones"]:
            if b.get("parent"):
                par[b["name"]] = b["parent"]
        for nm in want:
            print("-- 槽位 %s" % nm)
            b = bonelist.get(nm)
            if b:
                print("   bone: parent=%s  x=%.4f y=%.4f rot=%.3f scale=(%.4f,%.4f)"
                      % (b.get("parent"), b.get("x", 0), b.get("y", 0),
                         b.get("rotation", 0), b.get("scaleX", 1), b.get("scaleY", 1)))
            else:
                print("   bone: 无（槽位没有对应 bone）")
            m = pm.get(nm)
            if m:
                print("   partsMeta: kind=%s path=%s blend=%s color=%s"
                      % (m.get("kind"), m.get("path"), m.get("blend"),
                         m.get("color")))
            att = S["skins"][0]["attachments"].get(nm) or {}
            for an_, av in att.items():
                v = av.get("vertices") or []
                verts = [[round(v[i], 2), round(v[i + 1], 2)]
                         for i in range(0, min(len(v), 8), 2)]
                print("   attach[%s] verts=%d  first=%s" % (an_, len(v) // 2, verts))
            # 每条动画：attachment 时间轴 / deform 帧数
            for an in (S.get("animations") or {}):
                if a.anim and an != a.anim:
                    continue
                A = S["animations"][an]
                slots_tl = ((A.get("slots") or {}).get("default") or {}).get(nm)
                dfr = ((A.get("deform") or {}).get("default") or {}).get(nm) or {}
                tk = None
                if slots_tl and "attachment" in slots_tl:
                    tk = [(fmt_time(f["time"]), f.get("name"))
                          for f in slots_tl["attachment"]]
                # deform 幅度
                mag = None
                for att_name, frames in dfr.items():
                    if not frames:
                        continue
                    base = frames[0]["vertices"]
                    mx = 0.0
                    for f in frames:
                        v = f["vertices"]
                        for i in range(0, min(len(v), len(base)) - 1, 2):
                            mx = max(mx, math.hypot(v[i] - base[i],
                                                    v[i + 1] - base[i + 1]))
                    mag = max(mag or 0.0, mx)
                    print("      [%s] deform %s: %d 帧  最大形变 %.2fpx"
                          % (an, att_name, len(frames), mx))
                if tk is None and mag is None:
                    print("      [%s] 无 slot/deform 时间轴" % an)
                elif tk is not None:
                    names = sorted(set(n for _t, n in tk))
                    print("      [%s] attachment 时间轴 %d 键  出现的附件=%s"
                          % (an, len(tk), names))
                    if len(tk) <= 24:
                        print("           %s" % tk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
