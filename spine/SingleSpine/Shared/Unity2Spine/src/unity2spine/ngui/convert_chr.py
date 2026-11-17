# -*- coding: utf-8 -*-
"""NGUI 动态立绘(prefab) -> Spine 3.8 转换入口（兼容老签名）。

> **2026-10-14 起本函数是薄壳**：真正干活的是
> `unity2spine.ngui.bdone_spine` + `unity2spine.tools.convert_bdone` 那套实现。
> 老的实现在 4 个地方是错的（都是拿 Unity 真值对出来的）：
>   1. 图集页取"同目录第一张 png" → 一目录多图集时裁错图；
>   2. 部件矩形没按 NGUI `drawingDimensions` 算（奇数尺寸的 1 像素、
>      widget 的 pivot）→ 部件位置/尺寸差 1~4 像素；
>   3. 只读 `m_RotationCurves`，漏掉 `m_EulerCurves`（BdOne 42 个 clip 里
>      37 个带这个，很多部件整段动作丢）→ 实测漏 20+ 个部件；
>   4. `animations[x].slots` 写成"套一层皮肤名"的 4.x 形状（3.8 读不了），
>      且空时间线会写出一个假槽位 `default` 让 `.skel` 写出器报错。

保留这个函数是为了 `gui\\gui.py` / `run_cli.py` 的老入口继续能用；
产物布局变成 `<out>/<角色>_<序号>_<服装>/…`（一个服装一个可打开的目录）。
"""

import json
import os

from ..ngui import bdone_spine as B
from ..ngui.ngui_model import PrefabModel
from ..ngui.ngui_anim import parse_clip
from ..ngui.pack_images import pack_items
from ..spine.spine_out import atlas_text, write_viewer_config


def load_atlas(asset_path):
    """兼容老接口：读 UIAtlas .asset 的 region 表。"""
    return B.load_atlas_regions(asset_path)


def find_png_near(asset_path):
    """兼容老接口（已不用于取图！）：只用于诊断。"""
    d = os.path.dirname(asset_path or "")
    if not d or not os.path.isdir(d):
        return None
    pngs = sorted(f for f in os.listdir(d) if f.lower().endswith(".png"))
    return os.path.join(d, pngs[0]) if pngs else None


def convert_character(prefab_path, project_root, out_dir,
                      sample_dt=0.05, max_atlas=4096, want_skel=True):
    model = PrefabModel(prefab_path)
    char_name = os.path.splitext(os.path.basename(prefab_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    guid_idx = B.build_guid_index(project_root)
    atlas_cache = {}
    summary = []
    costumes = model.costumes()
    for idx, raw in enumerate(costumes):
        tag = "%s_%02d_%s" % (char_name, idx, raw.name)
        print("[%d/%d] 转换 %s (节点 %d, 精灵 %d)"
              % (idx + 1, len(costumes), raw.name, len(raw.nodes),
                 sum(1 for n in raw.nodes if n.sprite)))
        clip_path = guid_idx.get((raw.anim_ref or {}).get("guid"))
        asm = B.Assembly(raw, clip_path, guid_idx, atlas_cache)
        data, items, _region_names = B.build_skeleton(asm)
        packed = pack_items(items, max_dim=max_atlas)
        sub = os.path.join(out_dir, tag)
        os.makedirs(sub, exist_ok=True)
        pages, page_files = [], []
        for pi, pg in enumerate(packed):
            fn = tag + ".png" if len(packed) == 1 else "%s_%d.png" % (tag, pi)
            pg["image"].save(os.path.join(sub, fn))
            page_files.append(os.path.splitext(fn)[0])
            pages.append({"file": fn, "size": pg["size"],
                          "regions": pg["regions"]})
            print("  重打包图集页 %s：%dx%d，%d 个精灵"
                  % (fn, pg["size"][0], pg["size"][1], len(pg["regions"])))
        clip_name = "idle"
        if clip_path:
            clip_name = os.path.splitext(os.path.basename(clip_path))[0]
            clip_data = parse_clip(clip_path)
            B.build_animation(data, asm, clip_name, clip_data, dt=sample_dt)
            print("  动画 %s：曲线 %d 条，时长 %.2fs"
                  % (clip_name, len(clip_data["curves"]),
                     max((c.keys[-1][0] for c in clip_data["curves"]), default=0)))
        else:
            data["animations"].setdefault(clip_name, {})
        if asm.excluded:
            print("  [warn] 跳过 %d 个部件（region 缺失）：%s"
                  % (len(asm.excluded),
                     ", ".join(sorted({x[1] for x in asm.excluded})[:4])))
        json_path = os.path.join(sub, tag + ".json")
        with open(json_path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, separators=(",", ":"))
        atlas_path = os.path.join(sub, tag + ".atlas")
        with open(atlas_path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(atlas_text(pages))
        if want_skel:
            from ..spine import spine38_binary_writer as BW
            BW.convert_file(json_path, json_path[:-5] + ".skel")
        write_viewer_config(sub, data, tag + ".json", tag + ".atlas",
                            page_files, name=tag)
        summary.append([tag, raw.name, len(raw.nodes),
                        sum(1 for n in raw.nodes if n.sprite), clip_name,
                        "|".join(p["file"] for p in pages), json_path, atlas_path])

    with open(os.path.join(out_dir, "convert_summary.csv"), "w",
              encoding="utf-8") as fp:
        fp.write("name,costume,nodes,sprites,anim,page,json,atlas\n")
        for row in summary:
            fp.write(",".join(str(x) for x in row) + "\n")
    return summary


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--chr", required=True)
    ap.add_argument("--project", default=r"D:\VB\Search\BdOne\Assets")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dt", type=float, default=0.05)
    a = ap.parse_args()
    convert_character(a.chr, a.project, a.out, sample_dt=a.dt)
