# -*- coding: utf-8 -*-
r"""读 U2SFrameDump 导出的 JSONL，做两件事：

  ① 列某一帧**所有子物体**的可见性/矩阵/颜色（--frame / --time，可 --grep 过滤）
  ② 和一份 Spine 产物**对显隐**（--spine <产物目录> --anim <动画>）：
     Unity 的 activeInHierarchy/enabled/alpha 与产物的 slot attachment/颜色时间轴逐槽位比，
     这正是"影子/备选表情该显示却没显示"这类问题的判据。

用法:
    python read_framedump.py dump.jsonl
    python read_framedump.py dump.jsonl --time 2.0 --grep Shadow
    python read_framedump.py dump.jsonl --time 2.0 --spine <产物目录> --anim breast
"""

import argparse
import io
import json
import math
import os
import sys


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)
    raise SystemExit("产物目录里没有 *_static.json：%s" % d)


def read_dump(path):
    """元数据 + 表头（**不**把整份 JSONL 读进内存：大文件会有几百 MB）。"""
    meta = None
    mp = path[:-6] + ".meta.json"
    if os.path.isfile(mp):
        meta = load_json(mp)
    head = None
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                head = line
                continue
            break
    return meta, head


def scan(path):
    """流式扫一遍：返回 (帧数, 首帧t, 末帧t, 首帧状态hash)。"""
    n = 0
    t0 = t1 = None
    h0 = None
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line or line[0] == "#":
                continue
            n += 1
            if n == 1:
                f = json.loads(line)
                t0 = float(f.get("t", 0))
                h0 = (f.get("anim") or {}).get("fullPathHash")
            else:
                # 只取 "t": 后面的数字，不必整行解析（末帧也很快）
                i = line.find('"t":')
                if i >= 0:
                    j = line.find(',', i)
                    try:
                        t1 = float(line[i + 4:j])
                    except ValueError:
                        pass
    return n, t0, t1 if t1 is not None else t0, h0


def frame_at(path, t=None, idx=None):
    """流式找出最接近目标时间/帧号的那一帧并返回（只保留一帧，省内存）。"""
    if t is None and idx is None:
        with io.open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line or line[0] == "#":
                    continue
                return json.loads(line)
        return None
    best = None
    bestd = None
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line or line[0] == "#":
                continue
            if idx is None and t is not None:
                i = line.find('"t":')
                if i < 0:
                    continue
                j = line.find(',', i)
                try:
                    tt = float(line[i + 4:j])
                except ValueError:
                    continue
                d = abs(tt - t)
                if bestd is None or d < bestd:
                    bestd = d
                    best = json.loads(line)
                # t 单调递增：已经越过目标就没必要继续
                if tt > t and bestd is not None and tt - t > bestd:
                    break
                continue
            f = json.loads(line)
            if idx is not None and f.get("f") == idx:
                return f
            if t is not None:
                d = abs(float(f.get("t", 0)) - t)
                if bestd is None or d < bestd:
                    bestd, best = d, f
    return best


def pick_frame(frames, t=None, idx=None):
    if idx is not None:
        for f in frames:
            if f.get("f") == idx:
                return f
        return None
    if t is None:
        return frames[0] if frames else None
    best = min(frames, key=lambda f: abs(float(f.get("t", 0)) - t))
    return best


def obj_paths(meta):
    out = {}
    for o in (meta or {}).get("objects") or []:
        out[o["i"]] = o.get("path") or ""
    return out


def unify(p):
    """把 Unity 的路径统一成产物 partsMeta 的相对路径形式（去掉层后缀/大小写不敏感）。"""
    p = (p or "").replace("\\", "/")
    seg = p.split("/")
    return "/".join(seg[1:]) if len(seg) > 1 else p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--time", type=float, default=None)
    ap.add_argument("--frame", type=int, default=None)
    ap.add_argument("--grep", default=None)
    ap.add_argument("--spine", default=None)
    ap.add_argument("--anim", default=None)
    ap.add_argument("--spine-time", type=float, default=None,
                    help="用产物里的这个时刻比（默认用 dump 里的 t；"
                         "例如 Unity 跑了 Start 之后进 lobby，就用它对齐循环相位）")
    ap.add_argument("--count", action="store_true", help="只统计帧数/时间范围")
    ap.add_argument("--timeline", action="store_true",
                    help="只打 Animator 状态时间线（状态 hash/归一化时间/时长）")
    ap.add_argument("--every", type=int, default=120)
    ap.add_argument("--times", default=None,
                    help="逗号分隔的多个时刻：一次扫完，每个时刻打一遍（配合 --grep）")
    ap.add_argument("--alpha-eps", type=float, default=0.02,
                    help="alpha 小于它算看不见（默认 0.02）")
    a = ap.parse_args()

    meta, head = read_dump(a.dump)
    names = obj_paths(meta)
    print("dump %s  objects=%d  captureFps=%s"
          % (os.path.basename(a.dump), len(names),
             (meta or {}).get("captureFramerate")))
    if head:
        print("  表头: %s" % head.lstrip("# "))
    n, t0, t1, h0 = scan(a.dump)
    print("  帧数=%d  时间 %.3f ~ %.3f s（%.1f 秒素材）  首帧状态hash=%s"
          % (n, t0 or 0, t1 or 0, (t1 or 0) - (t0 or 0), h0))
    if a.count:
        return 0
    if a.timeline:
        with io.open(a.dump, encoding="utf-8") as fh:
            for line in fh:
                if not line or line[0] == "#":
                    continue
                # 这里必须整行解析：下面要遍历 obj / rnd（只截帧头会得到空表）
                f = json.loads(line)
                if not f or f.get("f") % a.every:
                    continue
                an = f.get("anim") or {}
                print("f=%-6s t=%8.3f dt=%.5f  hash=%-12s norm=%-8s len=%s"
                      % (f.get("f"), f.get("t", 0), f.get("dt", 0),
                         an.get("fullPathHash"),
                         ("%.3f" % an["normalizedTime"]) if an else "-",
                         ("%.2f" % an["length"]) if an else "-"))
        return 0
    if n == 0:
        return 1
    if a.times:
        wants = [float(x) for x in a.times.split(",") if x.strip()]
        want = sorted(wants)
        with io.open(a.dump, encoding="utf-8") as fh:
            got = []
            wi = 0
            for line in fh:
                if not line or line[0] == "#":
                    continue
                if wi >= len(want):
                    break
                # 整行解析（下面要遍历 obj/rnd；只截帧头会得到空表）
                f = json.loads(line)
                tt = float(f.get("t", 0))
                while wi < len(want) and tt >= want[wi]:
                    got.append((want[wi], f))
                    wi += 1
        if not got:
            print("没扫到目标时刻")
            return 1
        rnd_cache = {}
        for want_t, f in got:
            fr = f
            rnd = {r["o"]: r for r in fr.get("rnd") or []}
            an = fr.get("anim") or {}
            st = "" if not an else "  状态hash=%s norm=%.3f len=%.2f" % (
                an.get("fullPathHash"), an.get("normalizedTime"),
                an.get("length"))
            print("\n== t=%.3f (取到 f=%s t=%.3f)%s =="
                  % (want_t, fr.get("f"), float(fr.get("t", 0)), st))
            print("   %-4s %-6s %-4s %-6s %s" % ("idx", "hier", "rnd", "alpha", "path"))
            for o in fr.get("obj") or []:
                p = names.get(o["i"], "")
                if a.grep and a.grep.lower() not in p.lower():
                    continue
                r = rnd.get(o["i"])
                col = (r or {}).get("col")
                fl = (r or {}).get("flip")
                print("   %-4d %-6s %-4s %-6s %-12s %s"
                      % (o["i"], o.get("ah"),
                         "-" if r is None else r.get("en"),
                         "-" if not col else "%.3f" % col[3],
                         "-" if not fl else "flip=%s,%s" % (fl[0], fl[1]), p))
        return 0

    fr = frame_at(a.dump, a.time, a.frame)
    if fr is None:
        print("找不到该帧")
        return 1
    an = fr.get("anim") or {}
    print("取帧 f=%s t=%.4f  动画状态 hash=%s 归一化时间=%s"
          % (fr.get("f"), float(fr.get("t", 0)), an.get("fullPathHash"),
             ("%.3f" % an["normalizedTime"]) if an else "-"))

    # 注意：每帧的渲染器条目里 "i" 是渲染器序号、"o" 才是**对象索引**，
    # 按对象索引建表才能和 obj 对齐（第一版按 i 建表，颜色/顶点全取不到）。
    rnd = {r["o"]: r for r in fr.get("rnd") or []}
    print("本帧渲染器 %d 个" % len(fr.get("rnd") or []))
    rows = []
    for o in fr.get("obj") or []:
        r = rnd.get(o["i"])
        p = names.get(o["i"], "")
        if a.grep and a.grep.lower() not in p.lower():
            continue
        col = (r or {}).get("col")
        alpha = col[3] if col else None
        vis = bool(o.get("ah")) and (r is None or bool((r or {}).get("en")))
        if vis and alpha is not None and alpha < a.alpha_eps:
            vis = False
        rows.append({
            "i": o["i"], "path": p, "a": o.get("a"), "ah": o.get("ah"),
            "en": None if r is None else r.get("en"), "alpha": alpha,
            "nv": (r or {}).get("nv"), "vis": vis,
            "sort": (r or {}).get("sort"),
        })
    print("%-4s %-6s %-4s %-4s %-6s %-8s %s"
          % ("idx", "active", "hier", "rnd", "alpha", "verts", "path"))
    shown = 0
    for x in rows:
        if a.grep is None and x["path"] != "" and x["vis"] == x["vis"]:
            pass
        print("%-4d %-6s %-4s %-4s %-6s %-8s %s"
              % (x["i"], x["a"], x["ah"], x["en"],
                 "-" if x["alpha"] is None else "%.3f" % x["alpha"],
                 "-" if x["nv"] is None else x["nv"], x["path"]))
        shown += 1
        if a.grep is None and shown >= 60:
            print("...（省略，用 --grep 过滤）")
            break

    if not a.spine:
        return 0

    # ---------------- 与 Spine 产物对显隐 ----------------
    S = load_json(find_json(a.spine))
    info = load_json(os.path.join(a.spine, "_static_info.json"))
    anim = a.anim or list(S.get("animations", {}).keys())[0]
    A = S["animations"][anim]
    slots = (A.get("slots") or {}).get("default") or {}
    t = float(fr.get("t", 0)) if a.spine_time is None else float(a.spine_time)

    def att_at(slot):
        v = slots.get(slot)
        if not v or not v.get("attachment"):
            return True, None       # 没有时间轴 = 一直显示 setup 附件
        name = None
        for k in v["attachment"]:
            if float(k["time"]) <= t + 1e-9:
                name = k.get("name")
            else:
                break
        return name is not None, name

    def alpha_at(slot):
        v = slots.get(slot) or {}
        c = v.get("color")
        if not c:
            return None
        cur = None
        for k in c:
            if float(k["time"]) <= t + 1e-9:
                cur = k
            else:
                break
        if cur is None:
            cur = c[0]
        h = cur.get("color") or "ffffffff"
        return int(h[6:8], 16) / 255.0

    bypath = {}
    for m in info.get("partsMeta") or []:
        bypath[unify(m.get("path"))] = m.get("name")
    # Unity 侧每个部件路径只取一份可见性（同路径可能有多个渲染器）
    unity = {}
    for o in fr.get("obj") or []:
        p = names.get(o["i"], "")
        nm = bypath.get(unify(p))
        if not nm:
            continue
        r = rnd.get(o["i"])
        col = (r or {}).get("col")
        alpha = col[3] if col else None
        vis = bool(o.get("ah")) and (r is None or bool((r or {}).get("en")))
        if vis and alpha is not None and alpha < a.alpha_eps:
            vis = False
        # 同路径多份：只要有一份可见就算可见
        unity[nm] = unity.get(nm, False) or vis
        if alpha is not None:
            unity[nm + "\x00alpha"] = min(unity.get(nm + "\x00alpha", 1.0), alpha)

    print()
    print("== 对显隐（Spine 动画 %s，t=%.3f，alpha 阈值 %.2f）==" % (anim, t, a.alpha_eps))
    bad = []
    for nm in sorted(set(list(unity) + [k for k in bypath.values() if k])):
        if nm.endswith("\x00alpha"):
            continue
        if nm not in unity:
            continue
        uv = unity[nm]
        sv, att = att_at(nm)
        if sv and alpha_at(nm) is not None and alpha_at(nm) < a.alpha_eps:
            sv = False
        if uv != sv:
            bad.append((nm, uv, sv, att, unity.get(nm + "\x00alpha"), alpha_at(nm)))
    print("比较 %d 个部件，不一致 %d 个" % (len(unity) - sum(
        1 for k in unity if k.endswith("\x00alpha")), len(bad)))
    for nm, uv, sv, att, ua, sa in bad:
        print("   %-34s Unity=%s%s  Spine=%s(%s / alpha=%s)"
              % (nm, uv, "" if ua is None else " alpha=%.3f" % ua,
                 sv, att, "-" if sa is None else "%.2f" % sa))
    return 0


if __name__ == "__main__":
    sys.exit(main())
