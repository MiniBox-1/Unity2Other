# -*- coding: utf-8 -*-
r"""扫描 50 个角色：clip 里有多少曲线用 **哈希路径**（`path_0x...`）写的，
还原后还剩多少解不出来。

Unity 打包过的 AnimationClip 会把节点路径换成 `CRC32(路径)`（序列化成
`path: path_0xAC28B92_sMUTMHJ`）。不还原 = 这些曲线绑不到节点：
`m_IsActive` 丢了 → 表情/手一直不显示；位姿曲线丢了 → 骨骼不动（"运动错位"）。

用法:
  python tools\hash_path_scan.py [--root _probe50_rt4] [角色名...]
"""
import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from ngui2spine.static_prefab_spine import (  # noqa: E402
    ASSETS_DEFAULT, _asset_path, load_character)
from ngui2spine.unity_2dmodel import parse_animator_controller  # noqa: E402
from ngui2spine.unity_anim2d import parse_clip  # noqa: E402

KINDS = ("active", "enabled", "sorting", "morph", "pptr", "color", "material")


def scan(role, root):
    info = json.load(io.open(os.path.join(root, role, "_static_info.json"),
                             encoding="utf-8-sig"))
    mdl, _ = load_character(info["prefab"], ASSETS_DEFAULT, info.get("scene"))
    n_disc = n_pose = n_clip = 0
    for ani in (mdl.char_animators or []):
        cp = _asset_path(ASSETS_DEFAULT, ani.get("controllerGuid"))
        if not cp or not os.path.isfile(cp):
            continue
        for st in parse_animator_controller(cp):
            cl = _asset_path(ASSETS_DEFAULT, st.get("clipGuid") or "")
            if not cl or not os.path.isfile(cl):
                continue
            n_clip += 1
            c = parse_clip(cl)
            for k in KINDS:
                d = c.get(k) or {}
                n_disc += sum(1 for p in d if p.startswith("path_0x"))
            n_pose += sum(1 for cu in (c.get("curves") or [])
                          if (cu.path or "").startswith("path_0x"))
    return {"role": role, "clips": n_clip, "hashed_discrete": n_disc,
            "hashed_pose": n_pose}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(HERE, "_probe50_rt4"))
    ap.add_argument("--json", default=None)
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    names = a.names or sorted(
        d for d in os.listdir(a.root)
        if os.path.isfile(os.path.join(a.root, d, "_static_info.json")))
    rows, bad = [], []
    for n in names:
        try:
            r = scan(n, a.root)
        except Exception as e:                        # noqa: BLE001
            print("  %-24s 失败 %s" % (n, e))
            continue
        rows.append(r)
        if r["hashed_discrete"] or r["hashed_pose"]:
            print("  %-24s clip=%-2d 哈希路径: 显隐/排序等=%-3d 位姿曲线=%-4d"
                  % (n, r["clips"], r["hashed_discrete"], r["hashed_pose"]))
            bad.append(r)
    print("\n扫描 %d 个角色，有哈希路径的 %d 个；合计 显隐/排序等 %d 条、"
          "位姿 %d 条" % (len(rows), len(bad),
                        sum(r["hashed_discrete"] for r in rows),
                        sum(r["hashed_pose"] for r in rows)))
    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as fp:
            json.dump(rows, fp, ensure_ascii=False, indent=1)
        print("报告：" + a.json)


if __name__ == "__main__":
    main()
