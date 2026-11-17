# -*- coding: utf-8 -*-
r"""诊断：某产物里"同一时刻都可见、且 AABB 明显重叠"的部件组。

用来定位用户报的"多口 / 多眼 / 多手 / 两张脸"这类重复件。
用法: python _scratch\overlap_visible.py <产物目录> [动画名...]
"""
import glob
import json
import os
import re
import sys
from bisect import bisect_right


def load(d):
    p = glob.glob(os.path.join(d, "*_static.json"))[0]
    with open(p, encoding="utf-8") as f:
        J = json.load(f)
    with open(os.path.join(d, "_static_info.json"), encoding="utf-8") as f:
        I = json.load(f)
    return J, I


def visible_at(J, anim, slot, tl, t):
    cur = slot.get("attachment")
    if tl:
        for fr in tl:
            if fr["time"] <= t + 1e-9:
                cur = fr.get("name")
    return cur is not None


def aabb_at(J, anim, nm, t):
    att = J["skins"][0]["attachments"].get(nm)
    if not att:
        return None
    a = att.get(nm) or list(att.values())[0]
    v = list(a["vertices"])
    de = (anim.get("deform") or {}).get("default", {}).get(nm) or {}
    for _att, keys in de.items():
        # 关键帧时间升序，二分即可
        ts = [k["time"] for k in keys]
        i = bisect_right(ts, t + 1e-9) - 1
        cur = keys[max(0, i)]["vertices"]
        if cur is not None and len(cur) == len(v):
            v = [x + y for x, y in zip(v, cur)]
        break
    xs, ys = v[0::2], v[1::2]
    return (min(xs), max(xs), min(ys), max(ys))


def family(name):
    """部件名去掉尾部编号，得到"同一组备选"的族名。"""
    n = re.sub(r"_\d+(_\d+)?$", "", name)
    return n


def main():
    d = sys.argv[1]
    J, I = load(d)
    durs = {a["name"]: a["duration"] for a in I["animations"]}
    anims = sys.argv[2:] or list(J["animations"])
    for an in anims:
        A = J["animations"][an]
        dur = float(durs.get(an) or 0)
        tl = A.get("slots") or {}
        # 只把"同族"（名字去掉编号相同）的部件放在一起比
        fams = {}
        for s in J["slots"]:
            fams.setdefault(family(s["name"]), []).append(s["name"])
        fams = {k: v for k, v in fams.items() if len(v) > 1}
        global _SLOT
        _SLOT = {s["name"]: s for s in J["slots"]}
        pairs = {}
        t = 0.0
        _step = 0
        while t <= dur + 1e-9:
            _step += 1
            on = []
            for _fam, members in fams.items():
                for nm in members:
                    sl = _SLOT.get(nm)
                    if visible_at(J, an, sl,
                                  (tl.get(nm) or {}).get("attachment"), t):
                        bb = aabb_at(J, A, nm, t)
                        if bb:
                            on.append((nm, bb))
            for i in range(len(on)):
                for k in range(i + 1, len(on)):
                    a, b = on[i][1], on[k][1]
                    ox = min(a[1], b[1]) - max(a[0], b[0])
                    oy = min(a[3], b[3]) - max(a[2], b[2])
                    if ox <= 0 or oy <= 0:
                        continue
                    sa = (a[1] - a[0]) * (a[3] - a[2])
                    sb = (b[1] - b[0]) * (b[3] - b[2])
                    if min(sa, sb) <= 0:
                        continue
                    # 小件大部分被大件包住 = 疑似互斥候选
                    if ox * oy < 0.6 * min(sa, sb):
                        continue
                    if max(sa, sb) > 6 * min(sa, sb):
                        continue
                    key = (on[i][0], on[k][0])
                    e = pairs.setdefault(key, [0, round(t, 2), ox * oy])
                    e[0] += 1
            t += 0.05
        if not pairs:
            continue
        print("== %s (%s) dur=%.2f" % (d, an, dur))
        for (x, y), e in sorted(pairs.items(), key=lambda kv: -kv[1][0])[:12]:
            print("   %-32s %-32s %4d 帧  首次 t=%.2f  重叠面积≈%.0f"
                  % (x, y, e[0], e[1], e[2]))


if __name__ == "__main__":
    main()
