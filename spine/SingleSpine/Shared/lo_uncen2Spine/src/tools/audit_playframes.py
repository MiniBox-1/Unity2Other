# -*- coding: utf-8 -*-
"""PlayFrames 真值质量审计 + 与产物比对（真值文件要先验货）。

For each <char>@<Animator>@<State>.json:
  moved        = how many transforms changed (0 => the sampling never drove the Animator)
  truth_active = how many renderers had activeSelf change
  ours_slots   = how many product slots carry a visibility timeline
  mismatch     = cells where effective visibility (activeSelf && activeInHierarchy) differs

用法：

    python src/tools\\audit_playframes.py                 # 只审计真值 + 与 _verify_rt 比对
    python src/tools\\audit_playframes.py --old           # 再和 _probe50（旧产物）比一版

结果同时写到 `_reverse\\playframes_audit.json`（也会打印成表）。
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
from unity2spine.paths import app_root as _app_root  # noqa: E402
# ---------------------------------------------------------------------

import glob
import json
import os
import sys

HERE = _app_root()
ASSETS = _resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets")
# 统一导出根（2026-09-18 起）：Play 真值在 info\Data\PlayFrames
INFO = _resolve(r"D:\VB\Unity2Spine\info")
PLAY = os.path.join(INFO, "Data", "PlayFrames")
# 默认比对"带 --scene 重转的 19 个有真值角色"（tools\convert_all_2dmodel.py --scene
# 的输出目录）；想比别的产物时改 ROOT。
ROOT = os.path.join(HERE, "_verify_rt")
OLD_ROOT = os.path.join(HERE, "_probe50")


def product_json(char, root=ROOT):
    d = os.path.join(root, char)
    if not os.path.isdir(d):
        alt = (os.path.join(HERE, "_verify2", char + "_rt", "static_spine")
               if root == ROOT else os.path.join(root, char))
        if os.path.isdir(alt):
            d = alt
        else:
            return None
    for f in sorted(os.listdir(d)):
        if f.endswith(".json") and not f.startswith(("_", ".")):
            return os.path.join(d, f)
    return None


def eff(r):
    return bool(r.get("activeSelf", True)) and bool(r.get("activeInHierarchy", True))


def compare(js, frames, state, step):
    """Return (bad_cells, bad_slots, slots_with_timeline)."""
    if not js:
        return -1, [], -1
    anims = js.get("animations") or {}
    if state not in anims or not frames:
        return -1, [], -1
    tl = anims[state].get("slots") or {}
    rs = frames[0].get("renderers") or []
    idx = {}
    for i, r in enumerate(rs):
        idx.setdefault(r["path"].split("/")[-1], i)
    # 老产物没有 per-animation duration，用"时间轴 + 帧数"兜底
    dur = anims[state].get("duration") or 0
    if not dur:
        dur = (len(frames) - 1) * step
    n = min(len(frames), max(1, int(round(dur / step)) + 1))
    bad = 0
    bad_slots = []
    for slot, anim2 in tl.items():
        keys = sorted(anim2.get("attachment") or [], key=lambda x: x["time"])
        if not keys:
            continue
        i = idx.get(slot.rsplit("_", 1)[0])
        if i is None:
            continue
        cur = None
        k = 0
        mism = 0
        for j in range(n):
            t = frames[j]["t"]
            while k < len(keys) and keys[k]["time"] <= t + 1e-6:
                cur = keys[k].get("name")
                k += 1
            if (cur is not None) != eff(frames[j]["renderers"][i]):
                mism += 1
        if mism:
            bad += mism
            bad_slots.append("%s:%d" % (slot.rsplit("_", 1)[0], mism))
    return bad, bad_slots, len(tl)


def audit_file(char, play_path, js, old_js=None):
    b = os.path.basename(play_path)
    parts = b[:-5].split("@")
    anim, state = parts[1], parts[2]
    d = json.load(open(play_path, encoding="utf-8"))
    frames = d.get("frames") or []
    anims = js.get("animations") or {}
    base = dict(char=char, animator=anim, state=state, frames=len(frames),
                moved="-", truth_active="-", ours_slots="-", mismatch=-1,
                flag="?", bad_slots=[])
    if state not in anims:
        base["flag"] = "产物里没有这个动画"
        return base
    if not frames:
        base["flag"] = "真值空"
        return base
    tr = frames[0].get("transforms") or []
    key = lambda o: json.dumps(o, sort_keys=True)
    moved = sum(1 for i in range(len(tr))
                if key(frames[0]["transforms"][i]) != key(frames[-1]["transforms"][i]))
    rs = frames[0].get("renderers") or []
    truth_active = sum(1 for i in range(len(rs))
                       if len({f["renderers"][i]["activeSelf"] for f in frames}) > 1)
    step = d.get("step", 0.05) or 0.05
    bad, bad_slots, nslots = compare(js, frames, state, step)
    old_bad = compare(old_js, frames, state, step)[0] if old_js else None
    base.update(moved=moved, truth_active=truth_active, ours_slots=nslots,
                mismatch=bad, bad_slots=bad_slots[:6],
                old_mismatch=old_bad,
                flag=("真值无效(采样没驱动)" if moved == 0
                      else ("OK" if bad == 0 else "差异")))
    return base


def main():
    with_old = "--old" in sys.argv
    rows = []
    cache = {}

    def load(path):
        if path not in cache:
            cache[path] = json.load(open(path, encoding="utf-8-sig"))
        return cache[path]

    for f in sorted(glob.glob(os.path.join(PLAY, "*.json"))):
        b = os.path.basename(f)
        if b.endswith("playpose.json") or b.startswith("_"):
            continue
        parts = b[:-5].split("@")
        char = parts[0]
        pj = product_json(char)
        if not pj:
            rows.append(dict(char=char, animator=parts[1], state=parts[2],
                             frames=0, moved="-", truth_active="-",
                             ours_slots="-", mismatch=-1, flag="没有产物",
                             bad_slots=[]))
            continue
        old_pj = product_json(char, OLD_ROOT) if with_old else None
        old_js = load(old_pj) if old_pj else None
        rows.append(audit_file(char, f, load(pj), old_js))
    hdr = "%-22s %-30s %5s %6s %6s %5s %5s  %s"
    print(hdr % ("char", "state", "frm", "moved", "truthA", "new", "old",
                 "verdict"))
    for r in rows:
        extra = ("  " + ",".join(r.get("bad_slots") or [])) if r.get("bad_slots") else ""
        print(hdr % (r["char"], r["state"], r["frames"], r["moved"],
                     r["truth_active"], r["mismatch"], r.get("old_mismatch"),
                     r["flag"] + extra))
    diff = [r for r in rows if r["mismatch"] > 0]
    inert = [r for r in rows if r["flag"] == "真值无效(采样没驱动)"]
    missing = [r for r in rows if r["flag"] == "没有产物"]
    usable = [r for r in rows if r["mismatch"] >= 0 and r["moved"] != 0]
    old_usable = [r for r in usable if r.get("old_mismatch") is not None
                  and r["old_mismatch"] >= 0]
    print("\n文件 %d | 真值无效 %d | 有差异 %d | 差异格子合计 %d | 没有产物 %d"
          % (len(rows), len(inert), len(diff),
             sum(r["mismatch"] for r in diff), len(missing)))
    print("可用真值文件 %d 个：新口径差异格子合计 %d，旧口径合计 %d"
          % (len(usable), sum(r["mismatch"] for r in usable),
             sum(r["old_mismatch"] for r in old_usable)))
    out = os.path.join(HERE, "docs", "data", "playframes_audit.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(rows, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("结果: " + out)


main()
