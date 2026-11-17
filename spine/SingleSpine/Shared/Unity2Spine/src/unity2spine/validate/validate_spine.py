# -*- coding: utf-8 -*-
"""校验 ngui2spine 产物的结构与 Spine 3.8 读取规则一致性。"""

import json
import math
import os
import sys

try:
    from ..spine.spine_out import anim_slots
except (ImportError, ValueError):          # 直接当脚本跑时
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from spine.spine_out import anim_slots


def _mesh_vertex_shape(verts, uvs):
    """判断 mesh 顶点表形状 → (顶点数, "flat"|"weighted"|"bad")。

    · `flat`     ：非加权，vertices 是纯坐标 `[x,y,x,y,…]`，长度 == len(uvs)
    · `weighted` ：3.8 加权，扁平 `[骨数,骨下标,x,y,权重,…]`，顶点数 == len(uvs)/2
    """
    n_uv = len(uvs)
    if not verts:
        return (0, "flat") if n_uv == 0 else (0, "bad")
    if all(isinstance(x, (int, float)) for x in verts):
        if len(verts) == n_uv:
            return (len(verts) // 2, "flat")
        i, cnt = 0, 0
        while i < len(verts):
            n = int(verts[i])
            if n <= 0 or i + 1 + 4 * n > len(verts):
                return (0, "bad")
            i += 1 + 4 * n
            cnt += 1
        if cnt * 2 == n_uv:
            return (cnt, "weighted")
        return (0, "bad")
    if all(isinstance(g, (list, tuple)) for g in verts):
        if all(g and len(g) == 1 + 4 * int(g[0]) for g in verts) \
                and len(verts) * 2 == n_uv:
            return (len(verts), "weighted")
        return (0, "bad")
    return (0, "bad")


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
                    # 2026-10-14：3.8 的**加权 mesh**（多骨骼合并产物）是**扁平**的
                    # `[骨数, 骨下标, x, y, 权重, …]`（不是嵌套数组）——老判据
                    # `len(uvs) == len(verts)` 只对非加权（纯坐标）成立，会把
                    # 合并产物全报成"uv/顶点数不一致"。
                    nverts, shape = _mesh_vertex_shape(verts, uvs)
                    if shape == "bad":
                        errs.append("mesh uv/顶点数不一致: %s" % aname)
                    if not tris:
                        errs.append("mesh 无三角形: %s" % aname)
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
                ts = [f.get("time", 0.0) for f in frames]
                if ts != sorted(ts):
                    errs.append("时间未排序 %s/%s/%s" % (aname, bname, key))
        for sname, sm in anim_slots(a).items():
            if sname not in slot_names:
                errs.append("anim slot not in skeleton: %s" % sname)
            for key in ("attachment", "color", "twoColor"):
                frames = sm.get(key)
                if not frames:
                    continue
                # 2026-10-14：多 Spine 合并产物（merge_existing_spine）的第一帧
                # 常常不写 `time`（等价 0），读回器 / `.skel` 写出器都按 0 处理，
                # 校验器别再直接取键而崩。
                ts = [f.get("time", 0.0) for f in frames]
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
                      and not f.lower().startswith("convert_summary")
                      # 2026-10-14：查看器配置 `<目录名>.config.json` 也是 .json，
                      # 会被当成骨架报"缺少 atlas"的假失败。
                      and not f.lower().endswith(".config.json")
                      # 元数据文件（`_bdone_info.json` / `*_merge_info.json`）同理
                      and not f.startswith("_")
                      and not f.endswith("_merge_info.json")]
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
                       r"D:\VB\Search\SpineOut\安洁利卡") else 1)
