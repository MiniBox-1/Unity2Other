# -*- coding: utf-8 -*-
"""校验 ngui2spine 产物的结构与 Spine 3.8 读取规则一致性。"""
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
import math
import os
import sys

try:
    from ..spine.spine_out import anim_slots
except (ImportError, ValueError):          # 直接当脚本跑时
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from spine.spine_out import anim_slots


def check_one(json_path, atlas_path, page_path):
    d = json.load(open(json_path, encoding="utf-8"))
    errs = []

    # atlas 文本解析出 region 名
    regions = set()
    # 新版 atlas：页头/属性行连续，region 之间无空行，直接按行解析
    for line in open(atlas_path, encoding="utf-8").read().splitlines():
        s = line.strip()
        if not s or line.startswith("  ") or ":" in s:
            continue
        if s.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        regions.add(s)

    bone_names = [b["name"] for b in d["bones"]]
    slot_names = [s["name"] for s in d["slots"]]
    if len(set(bone_names)) != len(bone_names):
        errs.append("bone 重名")
    if len(set(slot_names)) != len(slot_names):
        errs.append("slot 重名")

    # 槽位绑定骨骼存在
    bone_set = set(bone_names)
    for s in d["slots"]:
        if s["bone"] not in bone_set:
            errs.append("slot bone missing: %s" % s["name"])

    # 皮肤附件：name/path 都必须能在 atlas 找到；尺寸/坐标有限
    for skin in d["skins"]:
        for slot, atts in (skin.get("attachments") or {}).items():
            if slot not in slot_names:
                errs.append("skin slot missing: %s" % slot)
            for aname, a in atts.items():
                if aname not in regions:
                    pass          # mesh 附件用 path 指区域名，下面单独查
                if a.get("type") == "mesh":
                    path = a.get("path") or aname
                    if path not in regions:
                        errs.append("atlas missing region: %s" % path)
                    uvs = a.get("uvs") or []
                    verts = a.get("vertices") or []
                    tris = a.get("triangles") or []
                    if len(uvs) != len(verts):
                        errs.append("mesh uv/顶点数不一致: %s" % aname)
                    if not tris:
                        errs.append("mesh 无三角形: %s" % aname)
                    nverts = len(verts) // 2
                    for idx in tris:
                        if idx < 0 or idx >= nverts:
                            errs.append("mesh 三角索引越界: %s" % aname)
                            break
                    for v in uvs + verts:
                        if not math.isfinite(float(v)):
                            errs.append("mesh 含非法数值: %s" % aname)
                            break
                    continue
                if aname not in regions:
                    errs.append("atlas missing region: %s" % aname)
                for k in ("x", "y", "width", "height"):
                    v = a.get(k)
                    if v is None or not math.isfinite(float(v)):
                        errs.append("bad attach %s.%s" % (slot, k))
                if a.get("width", 0) <= 0 or a.get("height", 0) <= 0:
                    errs.append("zero size attach: %s" % aname)

    # 动画：时间升序、时间线属性匹配骨骼/槽位
    for aname, a in d.get("animations", {}).items():
        for bname, bm in (a.get("bones") or {}).items():
            if bname not in bone_set:
                errs.append("anim bone not in skeleton: %s" % bname)
            for key in ("rotate", "translate", "scale", "shear"):
                frames = bm.get(key)
                if not frames:
                    continue
                ts = [f["time"] for f in frames]
                if ts != sorted(ts):
                    errs.append("时间未排序 %s/%s/%s" % (aname, bname, key))
        for sname, sm in anim_slots(a).items():
            if sname not in slot_names:
                errs.append("anim slot not in skeleton: %s" % sname)
            for key in ("attachment", "color", "twoColor"):
                frames = sm.get(key)
                if not frames:
                    continue
                ts = [f["time"] for f in frames]
                if ts != sorted(ts):
                    errs.append("slot 时间未排序 %s/%s" % (aname, key))

    if errs:
        return False, errs
    return True, ["ok"]


def main(folder):
    ok = True
    for jf in sorted(x for x in os.listdir(folder)
                     if x.endswith(".json") and not x.startswith("_")):
        base = os.path.splitext(jf)[0]
        atl = os.path.join(folder, base + ".atlas")
        if not os.path.isfile(atl):
            continue          # 没有同名 atlas 的 json（如元数据文件）跳过
        # atlas 内引用的页面名
        page = None
        with open(atl, encoding="utf-8") as fp:
            page = fp.readline().strip()
        good, msgs = check_one(os.path.join(folder, jf), atl, os.path.join(folder, page))
        print("%-40s %s" % (jf, "PASS" if good else "FAIL"))
        if not good:
            ok = False
            for m in msgs[:20]:
                print("   -", m)
    return ok


def validate_tree(root):
    """递归校验一个输出根目录下所有服装资源目录。返回 (通过数, 失败列表)。"""
    failures = []
    ok = 0
    for dirpath, _, files in os.walk(root):
        json_files = [f for f in files if f.lower().endswith(".json")
                      and not f.lower().startswith("convert_summary")]
        if not json_files:
            continue
        for jf in json_files:
            base = os.path.splitext(jf)[0]
            atl = os.path.join(dirpath, base + ".atlas")
            if not os.path.isfile(atl):
                failures.append(os.path.join(dirpath, jf) + " (缺少 atlas)")
                continue
            page = None
            with open(atl, encoding="utf-8") as fp:
                page = fp.readline().strip()
            good, msgs = check_one(os.path.join(dirpath, jf), atl,
                                   os.path.join(dirpath, page))
            if good:
                ok += 1
            else:
                failures.append(os.path.join(dirpath, jf) + ": " + "; ".join(msgs[:3]))
    return ok, failures


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1] if len(sys.argv) > 1 else
                       _resolve(r"D:\VB\Search\SpineOut\安洁利卡")) else 1)
