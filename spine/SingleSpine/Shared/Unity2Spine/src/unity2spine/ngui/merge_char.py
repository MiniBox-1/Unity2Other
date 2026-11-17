# -*- coding: utf-8 -*-
"""把 Unity prefab 中“多个服装/子装配”各自生成的 Spine 合并成一个 Spine。

合并依据：
  - 每个服装子装配在 Unity prefab 里的根 Transform 就是它子树 Spine 的
    根骨骼；合并时把这些根骨骼挂到一个新增 Root 下即可保留相对位置。
  - 槽位顺序按 Unity 中各 UISprite 的 mDepth 全局排序。
  - 每个服装的图集页继续保留为 Spine atlas 的一个 page。

用法：
  python -m ngui2spine.merge_char <角色prefab> <输出目录>
"""

import json
import os
import re
import shutil
import sys

from ..ngui.convert_chr import convert_character
from ..ngui.ngui_model import PrefabModel
from ..spine.spine_out import atlas_text, write_outputs


def _read_atlas(path):
    """解析已生成的 .atlas（页头后无空行格式）。"""
    pages = {}
    cur_page = None
    cur_region = None
    region_meta = None
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.rstrip()
        if not line.strip():
            cur_region = None
            continue
        if line.startswith("  "):
            k, v = line.strip().split(":", 1)
            if cur_region is not None:
                region_meta[k] = v.strip()
            continue
        s = line.strip()
        low = s.lower()
        if low.endswith(".png") and ":" not in s:
            cur_page = s
            pages[cur_page] = {"size": None, "regions": {}}
            cur_region = None
            continue
        if ":" in s:
            if low.startswith("size:"):
                w, h = low.split(":", 1)[1].split(",")
                if cur_page:
                    pages[cur_page]["size"] = (int(w), int(h))
            continue
        cur_region = s
        region_meta = {}
        pages.setdefault(cur_page, {"size": None, "regions": {}})
        pages[cur_page]["regions"][cur_region] = region_meta
    return pages


def _prefix(name, costume):
    if name == costume:
        return costume
    return costume + "_" + name


def _split_parts(parts_root):
    files = []
    for f in sorted(os.listdir(parts_root)):
        if f.endswith(".json"):
            files.append(f)
    return files


def merge_character(prefab_path, assets_root, out_dir, sample_dt=0.05, max_atlas=4096):
    model = PrefabModel(prefab_path)
    costumes = model.costumes()
    if len(costumes) < 2:
        raise ValueError("该 prefab 只有一个子装配，无需合并: " + str(len(costumes)))

    char_name = os.path.splitext(os.path.basename(prefab_path))[0]
    base = char_name + "_合并"
    parts_root = os.path.join(out_dir, "_parts")
    os.makedirs(parts_root, exist_ok=True)

    # 1) 先生成每个子装配的独立 Spine
    convert_character(prefab_path, assets_root, parts_root,
                      sample_dt=sample_dt, max_atlas=max_atlas)
    part_files = _split_parts(parts_root)
    if len(part_files) != len(costumes):
        raise RuntimeError("子装配数量不一致: prefab=%d outputs=%d"
                           % (len(costumes), len(part_files)))

    # 2) 读每份独立 Spine 与图集
    parts = []
    for ci, costume in enumerate(costumes):
        json_name = next(f for f in part_files if f.startswith(char_name + "_%02d_" % ci))
        spine = json.load(open(os.path.join(parts_root, json_name), encoding="utf-8"))
        atlas_path = os.path.join(parts_root, json_name[:-5] + ".atlas")
        parts.append({
            "costume": costume,
            "json": spine,
            "atlas": atlas_path,
            "atlas_data": _read_atlas(atlas_path),
            "dir": parts_root,
        })

    # 3) 名字映射：bone/slot/动画均加服装前缀
    merged = {
        "skeleton": {
            "hash": "ngui2spine-merged-" + char_name,
            "spine": "3.8.99",
            "x": 0, "y": 0, "width": 0, "height": 0, "fps": 60,
        },
        "bones": [{"name": "Root", "length": 0, "x": 0, "y": 0,
                   "rotation": 0, "scaleX": 1, "scaleY": 1}],
        "slots": [],
        "skins": [{"name": "default", "attachments": {}}],
        "animations": {},
    }

    combined_anim = {"bones": {}, "slots": {}}
    slot_orders = []          # (costume_name, depth, slot dict, default_attach)
    old_to_new_bone = {}
    old_attach_to_new = {}
    all_old_names = set()

    for ci, part in enumerate(parts):
        costume = part["costume"]
        spine = part["json"]

        # 旧骨骼/槽位名 -> 新名字
        for b in spine["bones"]:
            old_to_new_bone[(costume.name, b["name"])] = _prefix(b["name"], costume.name)

        # 皮肤附件区域名（默认不重名；若与其它服装重名则加前缀）
        for slot, atts in spine["skins"][0].get("attachments", {}).items():
            for aname, a in atts.items():
                key = (costume.name, aname)
                if aname in all_old_names:
                    old_attach_to_new[key] = costume.name + "_" + aname
                else:
                    old_attach_to_new[key] = aname
                all_old_names.add(aname)

    # 4) 合并骨骼
    for ci, part in enumerate(parts):
        costume = part["costume"]
        spine = part["json"]
        for b in spine["bones"]:
            new_name = old_to_new_bone[(costume.name, b["name"])]
            nb = dict(b)
            nb["name"] = new_name
            if b["name"] == costume.name:
                nb["parent"] = "Root"     # 保留 Unity 子装配根本地变换
            elif "parent" in b:
                nb["parent"] = old_to_new_bone[(costume.name, b["parent"])]
            merged["bones"].append(nb)

    # 5) 槽位按 Unity mDepth 全局排序
    for ci, part in enumerate(parts):
        costume = part["costume"]
        nodes = {n.name: n for n in costume.nodes if n.sprite}
        for slot in part["json"]["slots"]:
            depth = nodes.get(slot["name"]).sprite["depth"] if slot["name"] in nodes else 0
            default_attach = None
            if slot.get("attachment"):
                default_attach = old_attach_to_new.get(
                    (costume.name, slot["attachment"]), slot["attachment"])
            slot_orders.append((costume.name, depth, slot, default_attach))

    slot_orders.sort(key=lambda x: (x[1], x[0]))
    slot_new_names = {}
    for ci, part in enumerate(parts):
        costume = part["costume"].name
        for slot in part["json"]["slots"]:
            slot_new_names[(costume, slot["name"])] = old_to_new_bone[(costume, slot["name"])]

    for costume_name, _depth, slot, default_attach in slot_orders:
        new_name = slot_new_names[(costume_name, slot["name"])]
        ns = {
            "name": new_name,
            "bone": new_name,
            "color": slot.get("color", "ffffffff"),
            "attachment": default_attach,
        }
        merged["slots"].append(ns)

    # 6) 默认 skin：合并所有附件（附件 path 与区域名对应）
    for ci, part in enumerate(parts):
        costume = part["costume"].name
        for old_slot, atts in part["json"]["skins"][0].get("attachments", {}).items():
            new_slot = slot_new_names[(costume, old_slot)]
            target = merged["skins"][0]["attachments"].setdefault(new_slot, {})
            for aname, a in atts.items():
                na = dict(a)
                na["path"] = old_attach_to_new[(costume, aname)]
                target[old_attach_to_new[(costume, aname)]] = na

    # 7) 合并动画（保留各自 clip，并额外生成 combined）
    for ci, part in enumerate(parts):
        costume = part["costume"].name
        for anim_name, anim in part["json"].get("animations", {}).items():
            m_anim = {"bones": {}, "slots": {}}
            for bname, bm in anim.get("bones", {}).items():
                nb = old_to_new_bone[(costume, bname)]
                m_anim["bones"][nb] = bm
                combined_anim["bones"].setdefault(nb, {}).update(
                    {k: list(v) for k, v in bm.items()})
            for sname, sm in anim.get("slots", {}).items():
                ns = slot_new_names[(costume, sname)]
                m_anim["slots"][ns] = sm
                combined_anim["slots"].setdefault(ns, {}).update(
                    {k: list(v) for k, v in sm.items()})
            merged["animations"][costume + "_" + anim_name] = m_anim
    merged["animations"]["combined"] = combined_anim

    # 8) 合并图集页（先收集，再按页数命名：单页同名，多页 _0/_1...）
    raw_pages = []
    for ci, part in enumerate(parts):
        costume = part["costume"].name
        for pi, (page_name, page_data) in enumerate(part["atlas_data"].items()):
            src = os.path.join(part["dir"], page_name)
            regions = []
            for rname, meta in page_data["regions"].items():
                nm = old_attach_to_new.get((costume, rname), rname)
                rm = {
                    "x": int(meta["xy"].split(",")[0]),
                    "y": int(meta["xy"].split(",")[1]),
                    "width": int(meta["size"].split(",")[0]),
                    "height": int(meta["size"].split(",")[1]),
                    "paddingLeft": 0, "paddingRight": 0,
                    "paddingTop": 0, "paddingBottom": 0,
                }
                regions.append((nm, rm))
            raw_pages.append({"src": src, "size": page_data["size"],
                              "regions": regions})

    pages = []
    for i, rp in enumerate(raw_pages):
        new_page = base + ".png" if len(raw_pages) == 1 else "%s_%d.png" % (base, i)
        if os.path.isfile(rp["src"]):
            shutil.copy2(rp["src"], os.path.join(out_dir, new_page))
        pages.append({"file": new_page, "size": rp["size"], "regions": rp["regions"]})

    write_outputs(merged, pages, out_dir, base)
    return os.path.join(out_dir, base + ".json")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python -m ngui2spine.merge_char <角色prefab> <输出目录>")
        sys.exit(2)
    p = sys.argv[1]
    assets = os.path.join(os.path.dirname(os.path.dirname(p)), "")
    if not os.path.isdir(os.path.join(assets, "prefab")):
        assets = r"D:\VB\Search\BdOne\Assets"
    print(merge_character(p, assets, sys.argv[2]))
