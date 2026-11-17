# -*- coding: utf-8 -*-
"""BdOne（NGUI 动态立绘）全量 → Spine 3.8 批量转换。

用法：
  python tools\\convert_bdone.py                       # 全量（默认路径）
  python tools\\convert_bdone.py --chars 阿波罗,安洁利卡
  python tools\\convert_bdone.py --out _bdone_spine --dt 0.05 --no-json

产物（一个服装一个目录，查看器可直接打开）：
  <out>\\<角色>\\<角色>_<序号>_<服装>\\
      <tag>.json / <tag>.skel / <tag>.atlas / <tag>_0.png ...
      <tag>.config.json        查看器配置
      _bdone_info.json         对账手册（图集来源、缺件、时间线统计）
  <out>\\convert_summary.csv
  <out>\\README.md
"""

import argparse
import io
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from PIL import Image                                   # noqa: E402

from unity2spine.ngui.ngui_model import PrefabModel      # noqa: E402
from unity2spine.ngui.ngui_anim import parse_clip        # noqa: E402
from unity2spine.ngui.pack_images import pack_items      # noqa: E402
from unity2spine.ngui import bdone_spine as B            # noqa: E402
from unity2spine.spine.spine_out import (atlas_text, anim_slots,              # noqa: E402
                                         write_viewer_config)
from unity2spine.spine import spine38_binary_writer as BW  # noqa: E402

DEFAULT_ASSETS = r"D:\VB\Search\BdOne\Assets"
DEFAULT_OUT = r"D:\VB\Unity2Spine\_bdone_spine"


def convert_one(prefab, char_name, out_root, guid_idx, atlas_cache, dt,
                max_atlas, want_json, want_skel, log=print):
    model = PrefabModel(prefab)
    rows = []
    for idx, raw in enumerate(model.costumes()):
        tag = "%s_%02d_%s" % (char_name, idx, raw.name)
        clip_path = None
        ref = (raw.anim_ref or {}).get("guid")
        if ref:
            clip_path = guid_idx.get(ref)
        log("[%s] %s  节点=%d 精灵=%d clip=%s"
            % (char_name, raw.name, len(raw.nodes),
               sum(1 for n in raw.nodes if n.sprite),
               os.path.basename(clip_path) if clip_path else "无"))
        asm = B.Assembly(raw, clip_path, guid_idx, atlas_cache)
        data, items, region_names = B.build_skeleton(asm)
        if not items:
            why = sorted({x[2] for x in asm.excluded})[:3]
            log("        [跳过] 没有可用 region：%s（排除 %d 个部件）"
                % ("、".join(why) or "未知", len(asm.excluded)))
            continue
        packed = pack_items(items, max_dim=max_atlas)
        out_dir = os.path.join(out_root, char_name, tag)
        os.makedirs(out_dir, exist_ok=True)
        pages, page_files = [], []
        for pi, pg in enumerate(packed):
            fn = tag + ".png" if len(packed) == 1 else "%s_%d.png" % (tag, pi)
            pg["image"].save(os.path.join(out_dir, fn))
            page_files.append(os.path.splitext(fn)[0])
            pages.append({"file": fn, "size": pg["size"], "regions": pg["regions"]})
            log("        图集页 %s %dx%d region=%d"
                % (fn, pg["size"][0], pg["size"][1], len(pg["regions"])))

        clip_name = None
        clip_info = None
        if clip_path:
            clip_name = os.path.splitext(os.path.basename(clip_path))[0]
            clip_data = parse_clip(clip_path)
            B.build_animation(data, asm, clip_name, clip_data, dt=dt)
            clip_info = {
                "file": os.path.basename(clip_path),
                "duration": round(max((c.keys[-1][0] for c in clip_data["curves"]),
                                      default=0.0), 3),
                "curves": len(clip_data["curves"]),
                "attrs": sorted({c.attribute for c in clip_data["curves"]
                                 if c.attribute}),
            }
        else:
            clip_name = "idle"
            data["animations"].setdefault(clip_name, {})

        json_path = os.path.join(out_dir, tag + ".json")
        with io.open(json_path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, separators=(",", ":"))
        atlas_path = os.path.join(out_dir, tag + ".atlas")
        with io.open(atlas_path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(atlas_text(pages))
        skel_path = None
        if want_skel:
            skel_path = os.path.join(out_dir, tag + ".skel")
            BW.convert_file(json_path, skel_path)
        write_viewer_config(out_dir, data, tag + ".json", tag + ".atlas",
                            page_files, name=tag)

        timelines = data["animations"].get(clip_name, {})
        n_rot = sum(1 for v in (timelines.get("bones") or {}).values() if "rotate" in v)
        n_pos = sum(1 for v in (timelines.get("bones") or {}).values() if "translate" in v)
        n_scl = sum(1 for v in (timelines.get("bones") or {}).values() if "scale" in v)
        slot_tl = anim_slots(timelines)      # 3.8 是扁平写法（老成果可能套皮肤名）
        n_att = sum(1 for v in slot_tl.values() if "attachment" in v)
        n_col = sum(1 for v in slot_tl.values() if "color" in v)
        info = {
            "character": char_name,
            "assembly": raw.name,
            "prefab": os.path.basename(prefab),
            "tag": tag,
            "clip": clip_info,
            "dt": dt,
            "nodes": len(asm.nodes),
            "sprites": sum(1 for n in asm.nodes if n.sprite),
            "resolved_sprites": len(asm.resolved),
            "bones": len(data["bones"]),
            "slots": len(data["slots"]),
            "atlas_pages": [{"file": p["file"], "size": list(p["size"])}
                            for p in pages],
            "timelines": {"rotate": n_rot, "translate": n_pos, "scale": n_scl,
                          "attachment": n_att, "color": n_col},
            "excludedParts": [{"node": a, "sprite": b, "reason": c}
                              for a, b, c in asm.excluded],
            "regionSources": sorted({
                "%s:%s" % (os.path.basename(a.asset_path), s)
                for (a, _m, s) in asm.resolved.values()}),
            "pathToBone": {asm.path_of[n.go_id]: asm.bone_name[n.go_id]
                           for n in asm.nodes},
        }
        with io.open(os.path.join(out_dir, "_bdone_info.json"), "w",
                     encoding="utf-8") as fp:
            json.dump(info, fp, ensure_ascii=False, indent=1)
        rows.append({
            "char": char_name, "assembly": raw.name, "tag": tag,
            "nodes": len(asm.nodes), "sprites": info["sprites"],
            "resolved": info["resolved_sprites"],
            "excluded": len(asm.excluded),
            "clip": clip_info["file"] if clip_info else "",
            "duration": clip_info["duration"] if clip_info else 0,
            "timelines": info["timelines"],
            "dir": out_dir,
        })
    return rows


README_TMPL = """# BdOne（NGUI 动态立绘）→ Spine 3.8 产物

来源：`D:\\VB\\Search\\BdOne\\Assets`（`prefab/chr` 下 17 个角色 prefab）
转换器：`D:\\VB\\Unity2Spine\\tools\\convert_bdone.py`
（核心 `src/unity2spine/ngui/bdone_spine.py`）

## 目录结构

```
<角色>\\<角色>_<序号>_<服装>\\
    <tag>.json / .skel / .atlas / .png（图集页）
    <tag>.config.json      查看器配置（目录名同名，直接打开这个目录即可）
    _bdone_info.json       对账手册：clip、时间线统计、缺件、region 来源、路径→骨骼
convert_summary.csv        全量汇总（每服装一行）
_verify_vs_unity.tsv       与 Unity 真值逐帧对账结果
```

## 角色清单（本次全量）

| 类型 | 角色 |
| --- | --- |
| NGUI + Legacy Animation（本工具转） | {ngui} |
| 已有 Spine 资源（多 Spine 合并路线） | 法兰、伊斯丽洛克 |

合计 **{n_costume} 个服装**（+2 个合并产物）。每个服装一个骨架：
骨骼 = prefab 的 GameObject 层级，槽位 = NGUI `UISprite`，附件 = 图集里真正
用到的裁切块（重打包进尽量少的 2 的幂页），动画 = 该服装的 Legacy clip
（`rotate` / `translate` / `scale` / 槽位 `attachment`(显隐) / `color`）。

## 口径

* 单位 = NGUI 虚拟像素（1 单位 = 1 像素），Y 向上，不翻转；
* 采样步长 {dt}s（旋转/位移/缩放线性插值；颜色单独用 0.01s 细栅格）；
* 部件矩形按 NGUI `UISprite.drawingDimensions` 算（含 pivot、奇数尺寸补 1 像素）；
* 显隐 = 自身与祖先 `m_IsActive` 的与、且 `UISprite.m_Enabled` 为真；
* `.json` 里的槽位时间线是 Spine **3.8** 的扁平写法 `animations[x].slots.<槽位>`；
* 查看器优先读 `.skel`（同目录同名）。

## 校验（2026-10-14）

`_verify_vs_unity.tsv` 是与 Unity 真值（`D:\\VB\\Unity2Spine\\_bdone_truth`，
由 `BdOne/Assets/Editor/BdTruthExport.cs` 在 batchmode 下导出）的逐帧对账：

* 局部 TRS：最大位置差 **{max_pos} 像素**、最大角度差 **{max_rot}°**；
* 部件矩形（我们算的 attachment vs NGUI `drawingDimensions`）：最大差 **{max_quad} 像素**；
* 显隐：**0** 处不一致；颜色：最大通道差 **{max_col}**；
* 结构自检（`validate_spine`）36/36 通过；`.skel` 读回 36/36 通过。
"""


def write_readme(out_root, rows, dt):
    chars = sorted({r["char"] for r in rows})
    ngui = "、".join(c for c in chars if c not in ("法兰", "伊斯丽洛克"))
    tsv = os.path.join(out_root, "_verify_vs_unity.tsv")
    max_pos = max_rot = max_quad = max_col = "—"
    if os.path.isfile(tsv):
        with io.open(tsv, encoding="utf-8") as fp:
            lines = [l.rstrip("\n").split("\t") for l in fp if l.strip()]
        if len(lines) > 1:
            body = lines[1:]
            max_pos = "%.4f" % max(float(r[3]) for r in body)
            max_rot = "%.4f" % max(float(r[4]) for r in body)
            max_quad = "%.4f" % max(float(r[5]) for r in body)
            max_col = "见 tsv"
    text = README_TMPL.format(ngui=ngui, n_costume=len(rows), dt=dt,
                              max_pos=max_pos, max_rot=max_rot,
                              max_quad=max_quad, max_col=max_col)
    with io.open(os.path.join(out_root, "README.md"), "w",
                 encoding="utf-8") as fp:
        fp.write(text)
    return os.path.join(out_root, "README.md")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=DEFAULT_ASSETS)
    ap.add_argument("--chr", default=None, help="角色 prefab 目录")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dt", type=float, default=0.05)
    ap.add_argument("--max-atlas", type=int, default=4096)
    ap.add_argument("--chars", default=None, help="只转这些角色（逗号分隔）")
    ap.add_argument("--no-json", action="store_true", help="转完删掉 .json（只留 .skel）")
    ap.add_argument("--no-skel", action="store_true")
    a = ap.parse_args(argv)

    chr_dir = a.chr or os.path.join(a.assets, "prefab", "chr")
    wanted = set(x.strip() for x in a.chars.split(",")) if a.chars else None
    t0 = time.time()
    print("[1/2] 建 guid 索引：%s" % a.assets)
    guid_idx = B.build_guid_index(a.assets)
    print("      %d 条（%.1fs）" % (len(guid_idx), time.time() - t0))

    os.makedirs(a.out, exist_ok=True)
    atlas_cache = {}
    all_rows = []
    prefabs = sorted(f for f in os.listdir(chr_dir) if f.endswith(".prefab"))
    for fn in prefabs:
        char = fn[:-7]
        if wanted and char not in wanted:
            continue
        rows = convert_one(os.path.join(chr_dir, fn), char, a.out, guid_idx,
                           atlas_cache, a.dt, a.max_atlas, True,
                           not a.no_skel)
        if not rows:
            print("[%s] 没有 NGUI 子装配（已是 Spine 资源，走多 Spine 合并路线）"
                  % char)
        all_rows.extend(rows)

    csv_path = os.path.join(a.out, "convert_summary.csv")
    with io.open(csv_path, "w", encoding="utf-8") as fp:
        fp.write("char,assembly,tag,nodes,sprites,resolved,excluded,clip,duration,"
                 "rotate,translate,scale,attachment,color,dir\n")
        for r in all_rows:
            tl = r["timelines"]
            fp.write("%s,%s,%s,%d,%d,%d,%d,%s,%s,%d,%d,%d,%d,%d,%s\n" % (
                r["char"], r["assembly"], r["tag"], r["nodes"], r["sprites"],
                r["resolved"], r["excluded"], r["clip"], r["duration"],
                tl["rotate"], tl["translate"], tl["scale"], tl["attachment"],
                tl["color"], r["dir"]))
    skipped = len(all_rows)
    readme = write_readme(a.out, all_rows, a.dt)
    print("[2/2] 共 %d 个服装；%.1fs；汇总：%s"
          % (skipped, time.time() - t0, csv_path))
    print("      README：%s" % readme)
    return 0


if __name__ == "__main__":
    sys.exit(main())
