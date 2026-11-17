# -*- coding: utf-8 -*-
r"""刷新产物目录里的 `.config.json`（查看器配置），**不用重新转换**。

什么时候用：
  * 产物是从别处拷来的 / 老版本导出的，目录里缺 `.config.json`；
  * 查看器里把缩放/控制器调乱了，想回到"按骨架跨度自动算"的默认值。

用法：
    python tools\refresh_viewer_config.py <产物目录 或 产物根> [--no-merge] [--quiet]

要点（与转换器 `static_prefab_spine.py` 里的写法一致）：
  * `skeleton` = 同目录的 `<...>_static.json`（查看器会优先读同名的 `.skel`）；
  * 图集页 = 磁盘上 `<base>_*.png`，按文件名排序；atlas = `<base>.atlas`；
  * `_static_info.json` 里 `units == "px"` 时 `scale_factor` 固定 1.0（否则按跨度自动算）；
  * 默认 **merge**：保留查看器里已有的 `controllers` / `options`，只更新骨架与图集引用。
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from unity2spine.spine.spine_out import write_viewer_config   # noqa: E402


def target_dirs(root):
    """root 本身就是产物目录时只处理它；否则处理它下面一层的子目录。"""
    if glob.glob(os.path.join(root, "*_static.json")) or \
            glob.glob(os.path.join(root, "*_static_pma.json")):
        return [root]
    return sorted(d for d in glob.glob(os.path.join(root, "*"))
                  if os.path.isdir(d))


def refresh_one(d, merge=True, quiet=False):
    names = sorted(fn for fn in os.listdir(d)
                   if fn.endswith("_static.json")
                   or fn.endswith("_static_pma.json"))
    done = 0
    for fn in names:
        base = fn[:-5]                      # 去掉 .json
        try:
            data = json.load(open(os.path.join(d, fn), encoding="utf-8-sig"))
        except (ValueError, OSError) as ex:
            print("  [skip] %s：读不动（%s）" % (fn, ex))
            continue
        pages = sorted(p[:-4] for p in os.listdir(d)
                       if p.startswith(base + "_") and p.endswith(".png"))
        if not pages:
            print("  [skip] %s：找不到图集页 %s_*.png" % (fn, base))
            continue
        atlas = base + ".atlas"
        if not os.path.isfile(os.path.join(d, atlas)):
            atlas = ""
        scale, override = None, False
        info_p = os.path.join(d, "_static_info.json")
        if os.path.isfile(info_p):
            try:
                units = json.load(open(info_p, encoding="utf-8-sig")).get("units")
                if units == "px":
                    scale, override = 1.0, True
            except (ValueError, OSError):
                pass
        path = write_viewer_config(d, data, fn, atlas, pages,
                                   scale_factor=scale, merge=merge,
                                   override_scale=override)
        done += 1
        if not quiet:
            print("  [ok] %s <- %s（页 %d）" % (os.path.basename(path), fn,
                                                len(pages)))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="产物目录，或装了多个角色产物的根目录")
    ap.add_argument("--no-merge", action="store_true",
                    help="不保留查看器里已有的 controllers/options，直接写默认值")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    total = 0
    for d in target_dirs(a.root):
        if not a.quiet:
            print("== " + d)
        total += refresh_one(d, merge=not a.no_merge, quiet=a.quiet)
    print("刷新完成：%d 个 .config.json" % total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
