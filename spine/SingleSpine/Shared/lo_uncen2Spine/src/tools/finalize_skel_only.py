# -*- coding: utf-8 -*-
r"""把已导出的产物统一成**标准导出**口径（2026-10-10 起的新设定）：

  * 只保留 `<角色>_static[_pma].skel`（**删掉** `*_static*.json`，那只是 Debug/研究用）；
  * 查看器配置从 `.config.json` 改名成 **`<目录名>.config.json`**，并把里面的
    `skeleton` 指向 `.skel`；
  * 同步 `_static_info.json` 的 `json` 字段（置 null）。

用法:
    python src/tools\finalize_skel_only.py [--dir <产物根>] [--dry-run]
默认 --dir = 归档-proj-Mobile-old\_spine_conv_cs_port
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
import io
import json
import os
import sys

DEFAULT_DIR = _resolve(r"D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv_cs_port")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root = a.dir
    if not os.path.isdir(root):
        raise SystemExit("没有这个目录: " + root)
    n_done = n_skip = n_json = 0
    freed = 0
    renamed = 0
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        files = os.listdir(d)
        skel = [f for f in files if f.endswith(".skel")]
        if not skel:
            n_skip += 1
            continue
        skel = skel[0]
        # ① 删 JSON（Debug 留档不在这里）
        for f in files:
            if f.endswith(".json") and f not in ("_static_info.json",) \
                    and not f.endswith(".config.json"):
                p = os.path.join(d, f)
                freed += os.path.getsize(p)
                n_json += 1
                if not a.dry_run:
                    os.remove(p)
        # ② config 改名 + 指向 skel
        #    可能的旧名字：`.config.json`（最老）、`<prefab基名>.config.json`（含 .uAnim）
        #    统一改成 `<目录名>.config.json`
        new_cfg = os.path.join(d, name + ".config.json")
        cfg = None
        if os.path.isfile(new_cfg):
            cfg = json.load(io.open(new_cfg, encoding="utf-8-sig"))
        else:
            for f in files:
                if not f.endswith(".config.json"):
                    continue
                old_cfg = os.path.join(d, f)
                try:
                    cfg = json.load(io.open(old_cfg, encoding="utf-8-sig"))
                except (ValueError, OSError):
                    cfg = None
                if not a.dry_run:
                    os.replace(old_cfg, new_cfg)
                renamed += 1
                break
        if cfg is not None:
            cfg["skeleton"] = skel
            if not a.dry_run:
                with io.open(new_cfg, "w", encoding="utf-8") as fh:
                    json.dump(cfg, fh, ensure_ascii=False, indent=2)
        # ③ _static_info.json
        ip = os.path.join(d, "_static_info.json")
        if os.path.isfile(ip):
            try:
                info = json.load(io.open(ip, encoding="utf-8-sig"))
            except (ValueError, OSError):
                info = None
            if isinstance(info, dict):
                info["json"] = None
                if not a.dry_run:
                    with io.open(ip, "w", encoding="utf-8") as fh:
                        json.dump(info, fh, ensure_ascii=False, indent=1)
        n_done += 1
    print("标准口径化：处理 %d 个角色目录，跳过 %d 个（还没 skel）"
          % (n_done, n_skip))
    print("  删除 json %d 个，共 %.2f GB；改名的 config %d 个%s"
          % (n_json, freed / 1073741824.0, renamed,
             "（dry-run，未落盘）" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
