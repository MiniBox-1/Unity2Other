# -*- coding: utf-8 -*-
"""用 **Play 模式真值**（info/Data/PlayFrames/<角色>@<状态>.json）逐帧判定显隐。

和 `check_visibility.py` 的区别：
  · check_visibility 用的是 AnimationMode 采样的 PoseFrames，它的
    `activeInHierarchy` 会被 animator.Update(0) 覆盖，且分不清是"父链禁的"还是
    "自己禁的"；
  · 这里用的是 `PlayModeSampler.cs` 在 Play 模式下按状态机采的真值，带
    `activeSelf` / `activeInHierarchy` / `enabled` 三个字段，判断最准。

输出每一处不一致，并指出真值那一侧"为什么不可见"：
  parent=父链 inactive / self=自己 SetActive=false / renderer=m_Enabled=false

用法：
  python tools/check_play_visibility.py <spine目录> [--play-dir <PlayFrames>]
      [--step 1] [--top 20] [--json 报告.json]
"""

import argparse
import json
import os
import sys

ASSETS = r"D:\VB\Search\NormalLocal\lastOrign\Assets"
# 统一导出根（2026-09-18 起）：Play 真值在 info\Data\PlayFrames
INFO = r"D:\VB\Unity2Spine\info"


def load_spine(spine_dir):
    jsons = [f for f in sorted(os.listdir(spine_dir))
             if f.endswith(".json") and not f.startswith(("_", "."))]
    if not jsons:
        raise SystemExit("目录里没有 Spine JSON: " + spine_dir)
    data = json.load(open(os.path.join(spine_dir, jsons[0]),
                          encoding="utf-8-sig"))
    info = {}
    ip = os.path.join(spine_dir, "_static_info.json")
    if os.path.isfile(ip):
        info = json.load(open(ip, encoding="utf-8-sig"))
    return data, info


def slot_visible_at(per_slot, slot, t):
    keys = per_slot.get(slot)
    if not keys:
        return True
    v = keys[0][1]
    for kt, kv in keys:
        if kt <= t + 1e-9:
            v = kv
        else:
            break
    return v


def anim_timelines(anim):
    out = {}
    for slot, s in (anim.get("slots") or {}).items():
        keys = s.get("attachment") or []
        if keys:
            out[slot] = [(float(k["time"]), k.get("name") is not None)
                         for k in keys]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("spine_dir")
    ap.add_argument("--play-dir", default=os.path.join(INFO, "Data", "PlayFrames"))
    ap.add_argument("--char", default=None, help="角色名，默认取产物目录名")
    ap.add_argument("--step", type=int, default=1, help="真值抽帧步长")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    spine_dir = a.spine_dir.rstrip("\\/")
    char = a.char or os.path.basename(spine_dir)
    data, info = load_spine(spine_dir)
    # 多 drawable：一个部件可能占多个槽位（`<原名>` / `<原名>#<层级>`）。
    # 对"部件可见性"来说任意一个槽位可见即可见 —— 这里按 path 收集**全部**槽位。
    path2slots = {}
    for p in info.get("partsMeta") or []:
        path2slots.setdefault(p["path"], []).append(p["name"])
    anims = data.get("animations") or {}

    if not os.path.isdir(a.play_dir):
        raise SystemExit("没有 PlayFrames 目录: " + a.play_dir)

    def collect(d):
        return [f for f in sorted(os.listdir(d))
                if f.startswith(char + "@") and f.endswith(".json")
                and not f.endswith(".playpose.json")]

    play_dir = a.play_dir
    files = collect(play_dir)
    if not files:
        # PlayFrames 下面可能有子目录（例如 probe_step）；自动往下找一层
        for sub in sorted(os.listdir(play_dir)):
            d = os.path.join(play_dir, sub)
            if not os.path.isdir(d):
                continue
            got = collect(d)
            if got:
                play_dir, files = d, got
                print("（自动改用子目录：%s）" % d)
                break
    if not files:
        raise SystemExit("%s 在 %s 里没有真值（先跑 PlayModeSampler）" % (char, a.play_dir))

    print("角色 %s：产物动画 %d 条，Play 模式真值 %d 条" %
          (char, len(anims), len(files)))
    # 同一个状态名可能来自多个 Animator（主 + 副），优先用主 Animator 那份
    by_state = {}
    for f in files:
        d = json.load(open(os.path.join(play_dir, f), encoding="utf-8-sig"))
        st = d.get("state") or ""
        cur = by_state.get(st)
        if cur is None or (d.get("isMain") and not cur[1].get("isMain")):
            by_state[st] = (f, d)
    files = [f for f, _d in by_state.values()]
    rows = []
    for f in files:
        d = json.load(open(os.path.join(play_dir, f), encoding="utf-8-sig"))
        state = d.get("state") or ""
        anim = anims.get(state)
        if anim is None:                      # 我们的动画名可能是 "state_2" 这类
            cands = [k for k in anims if k.startswith(state)]
            anim = anims.get(cands[0]) if cands else None
        if anim is None:
            print("  [%s] 产物里没有同名动画，跳过" % state)
            continue
        per_slot = anim_timelines(anim)
        mism = {}
        frames = d.get("frames") or []
        samples = 0
        for i in range(0, len(frames), max(1, a.step)):
            fr = frames[i]
            t = float(fr.get("t") or 0.0)
            samples += 1
            for r in fr.get("renderers") or []:
                slots_here = path2slots.get(r["path"])
                if not slots_here:
                    continue
                ours = any(slot_visible_at(per_slot, s, t)
                           for s in slots_here)
                truth = bool(r.get("activeSelf", True)) and \
                    bool(r.get("activeInHierarchy", True)) and \
                    bool(r.get("enabled", True))
                if ours == truth:
                    continue
                if truth:
                    # 真值三件套都开着，我们却隐藏了 → 问题在我们这边
                    why = "ours"
                elif not bool(r.get("activeSelf", True)):
                    why = "self(Unity SetActive=0)"          # 自己关的
                elif not bool(r.get("activeInHierarchy", True)):
                    why = "parent(父链 inactive)"             # 父链关的
                elif not bool(r.get("enabled", True)):
                    why = "renderer(m_Enabled=0)"            # 渲染器禁用
                else:
                    why = "?"
                # 归组用的名字：一个渲染器可能对应多个槽位（同名多点），
                # 只有一个槽位时用槽位名，否则退回渲染器节点名。
                slot = (slots_here[0] if len(slots_here) == 1
                        else r["path"].split("/")[-1])
                m = mism.setdefault(slot, {"truth_only": 0, "ours_only": 0,
                                           "first": t, "why": why,
                                           "path": r["path"]})
                m["truth_only" if truth else "ours_only"] += 1
        rows.append({"state": state, "clip": d.get("clip"),
                     "duration": d.get("duration"), "samples": samples,
                     "mismatch": [dict(slot=s, **v) for s, v in mism.items()]})
        total = sum(v["truth_only"] + v["ours_only"] for v in mism.values())
        print("  [%-18s] %-14s 采样 %3d 帧  不一致 slot %2d 个（共 %d 处）%s" %
              (state, (d.get("animator") or "")[:14], samples, len(mism), total,
               "" if total else "  ✓ 一致"))

    flat = []
    for r in rows:
        for m in r["mismatch"]:
            flat.append(dict(m, state=r["state"]))
    flat.sort(key=lambda x: -(x["truth_only"] + x["ours_only"]))
    if flat:
        print("\n不一致明细（truth_only=Unity 显示而我们隐藏）：")
        print("  %-16s %-34s %8s %8s %8s  真值原因" %
              ("状态", "slot", "Unity显示", "我们显示", "首帧"))
        for m in flat[:a.top]:
            print("  %-16s %-34s %8d %8d %8.2f  %s" %
                  (m["state"], m["slot"][:34], m["truth_only"],
                   m["ours_only"], m["first"], m["why"]))
        print("  合计 %d 个 slot 有差异" % len(flat))
    else:
        print("\n显隐完全一致（所有状态、所有部件，逐帧比对）")
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("报告: " + a.json)
    return 1 if flat else 0


if __name__ == "__main__":
    sys.exit(main())
