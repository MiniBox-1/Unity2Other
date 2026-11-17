# -*- coding: utf-8 -*-
"""NGUI 动态立绘(prefab) -> Spine 3.8 JSON + atlas 转换入口。

用法示例：
  python convert_chr.py --chr "D:\\VB\\Search\\BdOne\\Assets\\prefab\\chr\\安洁利卡.prefab"
                       --out "D:\\VB\\Search\\SpineOut\\安洁利卡"
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
# ---------------------------------------------------------------------


import argparse
import os

from PIL import Image

from ..ngui.ngui_anim import parse_clip
from ..ngui.ngui_model import PrefabModel, resolve_guid_asset
from ..ngui.anim_to_spine import build_animation
from ..ngui.pack_images import pack_items
from ..spine.spine_out import make_skeleton_json, write_outputs
from ..unity.unity_parse import load_unity_docs


def load_atlas(asset_path):
    """读取 UIAtlas .asset：返回 {sprite_name: meta} 与 page 信息。"""
    for cls, _, doc in load_unity_docs(asset_path):
        if cls != 114 or "MonoBehaviour" not in doc:
            continue
        m = doc["MonoBehaviour"]
        if not isinstance(m.get("mSprites"), list):
            continue
        metas = {}
        for sp in m["mSprites"]:
            metas[sp["name"]] = sp
        return metas
    return {}


def find_png_near(asset_path):
    d = os.path.dirname(asset_path)
    pngs = [f for f in os.listdir(d) if f.lower().endswith(".png")]
    return os.path.join(d, pngs[0]) if pngs else None


def convert_character(prefab_path, project_root, out_dir,
                      sample_dt=0.05, max_atlas=4096):
    model = PrefabModel(prefab_path)
    char_name = os.path.splitext(os.path.basename(prefab_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    summary = []

    for idx, asm in enumerate(model.costumes()):
        tag = "%s_%02d_%s" % (char_name, idx, asm.name)
        print("[%d/%d] 转换 %s (节点 %d, 精灵 %d)"
              % (idx + 1, len(model.costumes()), asm.name, len(asm.nodes),
                 sum(1 for n in asm.nodes if n.sprite)))
        if not asm.anim_ref:
            print("  无 Animation 组件，跳过")
            continue

        # 图集：一个子装配可能跨多个 UIAtlas（主图 + 翅膀/特效页），
        # 收集“真正用到”的裁切块，随后重打包进尽量少的页。
        sprite_nodes = [n for n in asm.nodes if n.sprite]
        atlas_union = {}
        src_items = []
        by_guid = {}
        for n in sprite_nodes:
            guid = n.sprite.get("atlas_guid")
            by_guid.setdefault(guid, []).append(n)
        for guid, nodes in by_guid.items():
            atlas_path = resolve_guid_asset(project_root, guid)
            png_path = find_png_near(atlas_path) if atlas_path else None
            if not atlas_path or not png_path:
                print("  [warn] 找不到图集:", guid)
                continue
            meta = load_atlas(atlas_path)
            atlas_union.update(meta)
            page_img = Image.open(png_path)
            seen = set()
            for n in nodes:
                name = n.sprite["sprite_name"]
                if name in meta and name not in seen:
                    seen.add(name)
                    sp = meta[name]
                    crop = page_img.crop((sp["x"], sp["y"],
                                          sp["x"] + sp["width"],
                                          sp["y"] + sp["height"]))
                    src_items.append((name, crop, sp))
            miss = [n.sprite["sprite_name"] for n in nodes
                    if n.sprite["sprite_name"] not in meta]
            for name in miss:
                print("  [warn] atlas region missing:", name)
        if not src_items:
            print("  [warn] 没有可用图集页")
            continue

        packed = pack_items(src_items, max_dim=max_atlas)
        pages = []
        page_files = []
        if len(packed) == 1:
            page_files.append(tag + ".png")
        else:
            for pi in range(len(packed)):
                page_files.append("%s_%d.png" % (tag, pi))
        for pi, pg in enumerate(packed):
            page_file = page_files[pi]
            pg["image"].save(os.path.join(out_dir, page_file))
            pages.append({
                "file": page_file,
                "size": pg["size"],
                "regions": pg["regions"],
            })
            print("  重打包图集页 %s：%dx%d，%d 个精灵"
                  % (page_file, pg["size"][0], pg["size"][1], len(pg["regions"])))

        # 骨架 JSON
        skeleton = make_skeleton_json(asm, atlas_union)
        clip_file = resolve_guid_asset(project_root, asm.anim_ref.get("guid"))
        if clip_file:
            clip_name = os.path.splitext(os.path.basename(clip_file))[0]
            clip_data = parse_clip(clip_file)
            build_animation(skeleton, asm, clip_name, clip_data, sample_dt=sample_dt)
            print("  动画 %s：曲线 %d 条，时长 %.2fs"
                  % (clip_name, len(clip_data["curves"]),
                     max((c.keys[-1][0] for c in clip_data["curves"]), default=0)))
        else:
            clip_name = "idle"

        json_path, atlas_out = write_outputs(skeleton, pages, out_dir, tag)
        summary.append([tag, asm.name, len(asm.nodes), len(sprite_nodes),
                        clip_name, "|".join(p["file"] for p in pages),
                        json_path, atlas_out])

    with open(os.path.join(out_dir, "convert_summary.csv"), "w", encoding="utf-8") as fp:
        fp.write("name,costume,nodes,sprites,anim,page,json,atlas\n")
        for row in summary:
            fp.write(",".join(str(x) for x in row) + "\n")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chr", required=True)
    ap.add_argument("--project", default=_resolve(r"D:\VB\Search\BdOne\Assets"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    convert_character(args.chr, args.project, args.out)
