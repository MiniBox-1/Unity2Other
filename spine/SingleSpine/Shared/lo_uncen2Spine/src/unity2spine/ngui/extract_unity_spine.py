# -*- coding: utf-8 -*-
"""读取“由多个 SkeletonAnimation 拼成”的 Unity prefab，导出合并所需的
Unity 布局信息（本地变换、翻转、动画名、SkeletonDataAsset / skel / atlas）。

用法：
  python -m ngui2spine.extract_unity_spine <角色prefab> [输出JSON]
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


import json
import os
import sys

from ..ngui.ngui_model import PrefabModel, resolve_guid_asset


def _find_field(text, key):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(key + ":"):
            return s.split(":", 1)[1].strip()
    return None


def _guid_field(text, key):
    s = _find_field(text, key)
    if not s:
        return None
    if "guid:" not in s:
        return None
    return s.split("guid:")[1].split(",")[0].strip()


def extract_unity_spine(prefab_path, assets_root, out_json=None):
    model = PrefabModel(prefab_path)
    docs = model.docs
    result = {
        "prefab": os.path.basename(prefab_path),
        "root": model.go_name(model.find_root_go()),
        "children": [],
    }

    for gid, monos in model.mono_by_go.items():
        for mono in monos:
            script_guid = (mono.get("m_Script") or {}).get("guid")
            if script_guid != "d247ba06193faa74d9335f5481b2b56c":
                continue  # SkeletonAnimation
            t = model.transform_of_go(gid)
            node_name = model.go_name(gid)
            entry = {
                "gameObject": node_name,
                "localPosition": (t["m_LocalPosition"]["x"], t["m_LocalPosition"]["y"]),
                "localRotationZ": None,
                "localScale": (t["m_LocalScale"]["x"], t["m_LocalScale"]["y"]),
                "initialFlipX": bool(mono.get("initialFlipX")),
                "initialFlipY": bool(mono.get("initialFlipY")),
                "animationName": mono.get("_animationName"),
                "initialSkinName": mono.get("initialSkinName") or "",
                "loop": bool(mono.get("loop")),
                "timeScale": mono.get("timeScale"),
                "scale": 1.0,
            }
            rot = t["m_LocalRotation"]
            # 与转换器同公式
            import math
            entry["localRotationZ"] = math.degrees(math.atan2(
                2 * (rot["w"] * rot["z"] + rot["x"] * rot["y"]),
                1 - 2 * (rot["y"] * rot["y"] + rot["z"] * rot["z"])))

            asset_ref = (mono.get("skeletonDataAsset") or {})
            asset_path = resolve_guid_asset(assets_root, asset_ref.get("guid"))
            entry["skeletonDataAsset"] = asset_path
            if asset_path:
                atext2 = open(asset_path, encoding="utf-8", errors="replace").read()
                sc = _find_field(atext2, "scale")
                if sc:
                    try:
                        entry["scale"] = float(sc)
                    except ValueError:
                        pass

            if asset_path:
                text = open(asset_path, encoding="utf-8", errors="replace").read()
                skel_guid = _guid_field(text, "skeletonJSON")
                skel_path = resolve_guid_asset(assets_root, skel_guid)
                entry["skeleton"] = skel_path
                atlas_guid = None
                # atlasAssets 是列表，取第一个 atlas asset
                for m in __import__("re").finditer(r"guid: ([0-9a-f]+)", text):
                    if m.start() > text.find("atlasAssets"):
                        atlas_guid = m.group(1)
                        break
                atlas_asset = resolve_guid_asset(assets_root, atlas_guid)
                atlas_txt = None
                if atlas_asset:
                    atext = open(atlas_asset, encoding="utf-8", errors="replace").read()
                    atlas_file_guid = _guid_field(atext, "atlasFile")
                    atlas_txt = resolve_guid_asset(assets_root, atlas_file_guid)
                entry["atlas"] = atlas_txt
            result["children"].append(entry)

    if out_json:
        os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as fp:
            json.dump(result, fp, ensure_ascii=False, indent=1)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m ngui2spine.extract_unity_spine <角色prefab> [输出JSON]")
        sys.exit(2)
    prefab = sys.argv[1]
    assets = _resolve(r"D:\VB\Search\BdOne\Assets")
    out = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(extract_unity_spine(prefab, assets, out),
                     ensure_ascii=False, indent=1))
