# -*- coding: utf-8 -*-
"""把产物 slot 的显隐时间轴与 **Play 真值**逐格比对（`activeSelf && activeInHierarchy`）。

用法：

    python tools\\compare_play_truth.py <产物json> <PlayFrames\\角色@Animator@状态.json> <状态名> [关键字]

例（bheur 的 breast）：

    python tools\\compare_play_truth.py ^
      _probe50_rt2\\bheur_skin1\\bheur_skin1_static.json ^
      D:\\VB\\Search\\NormalLocal\\lastOrign\\Assets\\Data\\PlayFrames\\bheur_skin1@2DModel_BR_Bhear_NS1@breast.json ^
      breast

输出每个 slot 的「我们 vs 真值」ON 帧数与不一致格子数，最后给一个总数。
注意：**真值文件本身要先验货**（整段 transform 没变的文件是废数据，见
`tools\\audit_playframes.py` 与 docs 逆向报告第 8 节）。
"""
import json
import sys


def on_intervals_from_slot(tl, tmax, step):
    """slot 的 attachment 时间轴 -> 每个采样点是否显示。"""
    out = []
    i = 0
    cur = None
    tl = sorted(tl, key=lambda k: k["time"])
    n = int(round(tmax / step)) + 1
    for idx in range(n):
        t = idx * step
        while i < len(tl) and tl[i]["time"] <= t + 1e-6:
            cur = tl[i].get("name")
            i += 1
        out.append(cur is not None)
    return out


def truth_series(frames, leaf):
    for idx, r in enumerate(frames[0]["renderers"]):
        if r["path"].split("/")[-1] == leaf:
            # 有效可见性 = 自己 activeSelf 且父链 activeInHierarchy
            # （Unity 的 m_IsActive 曲线常打在**父节点**上，只比 activeSelf 会假报错）
            return [(bool(f["renderers"][idx]["activeSelf"])
                     and bool(f["renderers"][idx].get("activeInHierarchy", True)))
                    for f in frames]
    return None


def main():
    spine_path, play_path, clip = sys.argv[1], sys.argv[2], sys.argv[3]
    filt = sys.argv[4] if len(sys.argv) > 4 else None
    js = json.load(open(spine_path, encoding="utf-8"))
    d = json.load(open(play_path, encoding="utf-8"))
    frames = d["frames"]
    step = d.get("step", 0.05)
    tmax = min(js["animations"][clip].get("duration", 0) or 1e9,
               (len(frames) - 1) * step)

    # slot -> leaf name (slot 名是 "<leaf>_<id>")
    slot_leaf = {}
    for s in js["skins"][0]["attachments"] if False else js["slots"]:
        name = s["name"]
        leaf = name.rsplit("_", 1)[0]
        slot_leaf[name] = leaf

    slots = (js["animations"][clip].get("slots") or {})
    print("clip=%s duration=%s  truth frames=%d step=%s" % (clip, tmax, len(frames), step))
    print("slots with attachment timeline: %d / %d" % (len(slots), len(js["slots"])))
    bad_total = 0
    for slot, anim in sorted(slots.items()):
        if "attachment" not in anim:
            continue
        leaf = slot_leaf[slot]
        if filt and filt not in leaf:
            continue
        ours = on_intervals_from_slot(anim["attachment"], tmax, step)
        truth = truth_series(frames, leaf)
        if truth is None:
            print("  %-28s (no truth renderer)" % leaf)
            continue
        n = min(len(ours), len(truth))
        diff = [i for i in range(n) if ours[i] != truth[i]]
        bad_total += len(diff)
        print("  %-28s ours ON=%3d  truth ON=%3d  mismatch=%2d  %s"
              % (leaf, sum(ours[:n]), sum(truth[:n]), len(diff),
                 "" if not diff else "first=%.2f last=%.2f" % (diff[0] * step, diff[-1] * step)))
    print("mismatched (slot,t) cells:", bad_total)


main()
