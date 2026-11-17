# -*- coding: utf-8 -*-
"""把 Unity prefab 中“多个已有 SkeletonAnimation(Spine 3.8)”合成一个 Spine。

适用：prefab 的子节点直接挂 SkeletonAnimation，引用现成的
`.skel.bytes` / `.json` + `.atlas`（如 BdOne 的 法兰、伊斯丽洛克）。

两种入口（结果等价，可交叉校验）：
  mode="json"   : 先用第三方转换器把每个 .skel 转成 .json，再合并 JSON；
  mode="direct" : 直接解析 .skel 二进制（spine38_binary），不依赖转换器读入。

输出：<角色>_合并.json/.atlas/图集页（可选再由转换器写回 .skel）。
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

from ..ngui.extract_unity_spine import extract_unity_spine

DEFAULT_CONVERTER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "third_party", "SpineSkeletonDataConverter.exe")


# --------------------------------------------------------------------------
# 名称整理

def _fnum(v, precision=6):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return 0
    if isinstance(v, float):
        r = round(v, precision)
        if r == int(r):
            return float(int(r))
        return r
    return v


def _sanitize_label(text, fallback="part"):
    s = (text or "").strip()
    s = s.replace("Sprite -", "").replace("Sprite-", "")
    s = s.strip().replace(" ", "_").replace("-", "_")
    s = "".join(ch for ch in s if ch.isalnum() or ch in "_")
    s = s.strip("_")
    return s or fallback


def _unique_label(labels, label):
    if label not in labels:
        labels.add(label)
        return label
    n = 2
    while "%s_%d" % (label, n) in labels:
        n += 1
    out = "%s_%d" % (label, n)
    labels.add(out)
    return out


def _unique_name(used, base):
    if base not in used:
        used.add(base)
        return base
    n = 2
    while "%s_%d" % (base, n) in used:
        n += 1
    out = "%s_%d" % (base, n)
    used.add(out)
    return out


# --------------------------------------------------------------------------
# atlas 读取（保留原文块，只改页头与 region 名，避免旋转/PMA 等被破坏）

def _parse_atlas(path):
    """返回 [page]；page = {header, props, regions:[(name, [prop lines])]}"""
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    pages = []
    page = None
    region = None
    after_blank = False
    page_keys = {"size", "format", "filter", "repeat", "premultipliedalpha"}

    def flush_region():
        if page is not None and region is not None:
            page["regions"].append((region[0], region[1]))

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_region()
            region = None
            after_blank = True
            continue
        ind = line.startswith(" ") or line.startswith("\t")
        if not ind and ":" in line and line.split(":", 1)[0].strip().lower() in page_keys:
            if page is None:
                page = {"header": None, "props": [], "regions": []}
                pages.append(page)
            page["props"].append(line)
            after_blank = False
            continue
        if not ind:
            flush_region()
            if page is None or (page["regions"] and after_blank):
                # 空行后且已有 region => 新页面开始
                page = {"header": line, "props": [], "regions": []}
                pages.append(page)
            else:
                if page is None:
                    page = {"header": None, "props": [], "regions": []}
                    pages.append(page)
                if page["header"] is None:
                    page["header"] = line
                else:
                    # 首个 region（无空行分隔）
                    region = [line, []]
                    after_blank = False
                    continue
            region = None
            after_blank = False
            continue
        # 缩进行 = region 属性
        if region is None:
            region = ["", []]
        region[1].append(line)
        after_blank = False
    flush_region()
    return pages


def _resolve_atlas_image(atlas_path, header):
    d = os.path.dirname(atlas_path)
    p = os.path.join(d, header)
    if os.path.isfile(p):
        return p
    base = os.path.basename(header)
    for depth in (d, os.path.dirname(d), os.path.join(d, "images")):
        if depth:
            q = os.path.join(depth, base)
            if os.path.isfile(q):
                return q
    return p


def _write_atlas(out_path, merged_pages):
    """merged_pages: [{'file':..., 'props':[lines], 'regions':[(new_name, props)]}]"""
    chunks = []
    for pi, mp in enumerate(merged_pages):
        body = [mp["file"]] + list(mp["props"])
        for name, props in mp["regions"]:
            body.append(name)
            body.extend(props)
        chunks.append("\n".join(body))
    open(out_path, "w", encoding="utf-8").write("\n\n".join(chunks))


# --------------------------------------------------------------------------
# Spine 数据加载（json 转接 / 直接二进制）

def _run_converter(exe, src, dst):
    r = subprocess.run([exe, src, dst], capture_output=True)
    if not os.path.isfile(dst):
        raise RuntimeError("转换器失败(%s -> %s): %s" % (
            src, dst,
            (r.stdout or r.stderr).decode("utf-8", errors="replace")[-800:]))


def _write_skel_binary(model, skel_path, json_path, converter, writer="auto"):
    """写 `.skel`：python = 本项目原生写出器（spine38_binary_writer），
    exe = third_party 的 SpineSkeletonDataConverter；auto 先 python 后 exe。"""
    if writer not in ("auto", "python", "exe"):
        raise ValueError("skel_writer 只能是 auto / python / exe")
    if writer in ("auto", "python"):
        try:
            # 库化后该模块在 `unity2spine/spine/` 下（老写法会 ModuleNotFound，
            # 然后静默退回第三方 exe —— 现在修好，优先用本项目原生写出器）
            from ..spine.spine38_binary_writer import write_skeleton_binary
            write_skeleton_binary(model, skel_path)
            return "python"
        except Exception as ex:                      # 退回第三方转换器
            if writer == "python":
                raise
            print("[skel] 原生写出器失败，改用转换器：%s" % ex)
    _run_converter(converter, json_path, skel_path)
    return "exe"


def _load_spine_json_by_converter(skel_path, converter_exe, tmp, part_index):
    stem = os.path.splitext(os.path.basename(skel_path))[0]
    stem = "%02d_%s" % (part_index, stem)
    src = os.path.join(tmp, stem + ".skel")
    dst = os.path.join(tmp, stem + ".json")
    shutil.copy2(skel_path, src)
    _run_converter(converter_exe, src, dst)
    with open(dst, encoding="utf-8") as fp:
        return json.load(fp)


def _load_json_file(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


# --------------------------------------------------------------------------
# 合并核心

def _rename_animation(anim, maps, part, rate=1.0):
    """深拷贝并把名字引用改名；rate!=1 时缩放所有 key 的 time。"""
    out = {}

    def scale_frames(frames):
        res = []
        for fr in frames:
            nf = dict(fr)
            if rate != 1.0 and "time" in nf:
                nf["time"] = _fnum(nf["time"] * rate)
            res.append(nf)
        return res

    bmap = maps["bones"][part]
    smap = maps["slots"][part]
    amap = maps["attach"][part]
    kmap = maps["ik"][part]
    tmap = maps["transform"][part]
    pmap = maps["path"][part]
    emap = maps["events"][part]

    if "bones" in anim:
        nb = {}
        for bname, props in anim["bones"].items():
            nprops = {}
            for prop, frames in props.items():
                nprops[prop] = scale_frames(frames)
            nb[bmap.get(bname, bname)] = nprops
        out["bones"] = nb
    if "slots" in anim:
        ns = {}
        for sname, props in anim["slots"].items():
            nprops = {}
            for prop, frames in props.items():
                nframes = scale_frames(frames)
                if prop == "attachment":
                    for fr in nframes:
                        if fr.get("name"):
                            fr["name"] = amap.get(fr["name"], fr["name"])
                nprops[prop] = nframes
            ns[smap.get(sname, sname)] = nprops
        out["slots"] = ns
    if "attachments" in anim:   # Spine 4.x deform/序列时间线（skin->slot->attachment）
        nd = out.setdefault("attachments", {})
        for skin_name, by_slot in anim["attachments"].items():
            nd2 = nd.setdefault("default", {})
            for sname, by_att in by_slot.items():
                nd3 = nd2.setdefault(smap.get(sname, sname), {})
                for aname, props in by_att.items():
                    nprops = {}
                    for prop, frames in props.items():
                        nframes = scale_frames(frames if isinstance(frames, list) else [])
                        nprops[prop] = nframes
                    nd3[amap.get(aname, aname)] = nprops
    for dkey in ("deform", "ffd"):
        if dkey in anim:
            nd = out.setdefault("deform", {})
            for skin_name, by_slot in anim[dkey].items():
                nd2 = nd.setdefault("default", {})
                for sname, by_att in by_slot.items():
                    nd3 = nd2.setdefault(smap.get(sname, sname), {})
                    for aname, frames in by_att.items():
                        nd3[amap.get(aname, aname)] = scale_frames(frames)
    for key, nkey in (("ik", kmap), ("transform", tmap), ("path", pmap)):
        if key in anim:
            nd = {}
            for cname, frames in anim[key].items():
                nd[nkey.get(cname, cname)] = scale_frames(frames)
            out[key] = nd
    if "drawOrder" in anim:
        # 仅单子装配时保留；多子装配的局部 drawOrder 无法安全叠加
        nd = []
        for frame in anim["drawOrder"]:
            nf = dict(frame)
            offs = nf.get("offsets")
            if offs:
                no = []
                for o in offs:
                    x = dict(o)
                    x["slot"] = smap.get(x.get("slot"), x.get("slot"))
                    no.append(x)
                nf["offsets"] = no
            if rate != 1.0 and "time" in nf:
                nf["time"] = _fnum(nf["time"] * rate)
            nd.append(nf)
        out["drawOrder"] = nd
    if "events" in anim:
        nd = []
        for frame in anim["events"]:
            nf = dict(frame)
            if nf.get("name"):
                nf["name"] = emap.get(nf["name"], nf["name"])
            if rate != 1.0 and "time" in nf:
                nf["time"] = _fnum(nf["time"] * rate)
            nd.append(nf)
        out["events"] = nd
    return out


def _deep_merge_anim(dst, src):
    for sec in ("bones", "slots"):
        for name, props in (src.get(sec) or {}).items():
            target = dst.setdefault(sec, {}).setdefault(name, {})
            for prop, frames in props.items():
                target[prop] = list(frames)
    for sec in ("deform", "ffd"):
        for skin_name, by_slot in (src.get(sec) or {}).items():
            dst.setdefault(sec, {}).setdefault(skin_name, {}).update(by_slot)
    for skin_name, by_slot in (src.get("attachments") or {}).items():
        dst.setdefault("attachments", {}).setdefault(skin_name, {}).update(by_slot)
    for sec in ("ik", "transform", "path"):
        for name, props in (src.get(sec) or {}).items():
            dst.setdefault(sec, {})[name] = props
    if src.get("drawOrder"):
        dst["drawOrder"] = list(src["drawOrder"])
    if src.get("events"):
        dst.setdefault("events", []).extend(list(src["events"]))
    return dst


def merge_spine_parts(parts, char_name):
    """parts: 见 merge_existing_spine()。返回 (merged, pages, report)。"""
    def effective_skins(model, skin_name):
        """Unity SkeletonAnimation.initialSkinName 指定的皮肤；缺省回退 default。"""
        skins = model.get("skins") or []
        if skin_name:
            hit = [s for s in skins if s.get("name") == skin_name]
            if hit:
                return hit
        dft = [s for s in skins if s.get("name") == "default"]
        if dft:
            return dft
        return skins[:1]

    used = {"bones": set(), "slots": set(), "ik": set(),
            "transform": set(), "path": set(), "events": set(),
            "attach": set()}
    maps = {"bones": {}, "slots": {}, "attach": {}, "ik": {},
            "transform": {}, "path": {}, "events": {}, "region": {}}

    for part in parts:
        model = part["model"]
        label = part["label"]
        bm, sm, am, ikm, tm, pm, em = {}, {}, {}, {}, {}, {}, {}

        for b in model.get("bones", []):
            old = b["name"]
            bm[old] = _unique_name(used["bones"],
                                   old if old not in used["bones"] else label + "_" + old)
        for s in model.get("slots", []):
            old = s["name"]
            sm[old] = _unique_name(used["slots"],
                                   old if old not in used["slots"] else label + "_" + old)
        for key, nkey in (("ik", ikm), ("transform", tm), ("path", pm)):
            for c in model.get(key, []):
                old = c.get("name")
                if not old:
                    continue
                nkey[old] = _unique_name(
                    used[key], old if old not in used[key] else label + "_" + old)
        ev = model.get("events") or {}
        if isinstance(ev, dict):
            names = list(ev.keys())
        elif isinstance(ev, list):
            names = [x.get("name") for x in ev if isinstance(x, dict)]
        else:
            names = []
        for old in names:
            if not old:
                continue
            em[old] = _unique_name(
                used["events"], old if old not in used["events"] else label + "_" + old)

        # 附件 key 名 与 atlas region(path) 名分开映射；按 initialSkinName 提取皮肤
        cache_name = {}
        cache_region = {}
        # 子副本仍保留该骨架全部皮肤附件（动画 deform 会引用非当前皮肤），
        # 默认显示才由 initialSkinName 决定。
        for sk in model.get("skins") or []:
            for atts in (sk.get("attachments") or {}).values():
                for key, a in atts.items():
                    # 皮肤字典键 = 动画/槽默认引用的附件名；
                    # value 的 name/path = atlas region 名
                    aid = key
                    path = (a or {}).get("path") or (a or {}).get("name") or aid
                    if path not in cache_region:
                        if path in used["attach"]:
                            cache_region[path] = _unique_name(
                                used["attach"], label + "_" + path)
                        else:
                            cache_region[path] = path
                            used["attach"].add(path)
                    if aid not in cache_name:
                        cache_name[aid] = cache_region[path] if aid == path else aid
        am.update(cache_name)
        region_map = cache_region
        maps["bones"][label] = bm
        maps["slots"][label] = sm
        maps["attach"][label] = am
        maps["region"][label] = region_map
        maps["ik"][label] = ikm
        maps["transform"][label] = tm
        maps["path"][label] = pm
        maps["events"][label] = em

    root_name = _unique_name(used["bones"], "Root")
    src_version = "3.8.99"
    for p_ in parts:
        v = (p_["model"].get("skeleton") or {}).get("spine")
        if v:
            src_version = v
            break
    merged = {
        "skeleton": {
            "hash": "ngui2spine-composite-" + char_name,
            "spine": src_version,
            "x": 0, "y": 0, "width": 0, "height": 0, "fps": 60,
        },
        "bones": [{"name": root_name, "length": 0, "x": 0, "y": 0,
                   "rotation": 0, "scaleX": 1, "scaleY": 1}],
        "slots": [],
        "skins": [{"name": "default", "attachments": {}}],
        "animations": {},
    }
    if any(maps["ik"][p["label"]] for p in parts):
        merged["ik"] = []
    if any(maps["transform"][p["label"]] for p in parts):
        merged["transform"] = []
    if any(maps["path"][p["label"]] for p in parts):
        merged["path"] = []
    if any(maps["events"][p["label"]] for p in parts):
        merged["events"] = {}

    base_scale = parts[0]["dataScale"] or 1.0

    # 骨骼：Root + 每子装配 mount + 原骨骼（源根骨骼挂到 mount）
    bone_bases = {}
    for part in parts:
        label = part["label"]
        model = part["model"]
        bm = maps["bones"][label]
        root_old = None
        for b in model.get("bones", []):
            if "parent" not in b:
                root_old = b["name"]
                break
        sx = part["localScale"][0] * (part["dataScale"] / base_scale)
        sy = part["localScale"][1] * (part["dataScale"] / base_scale)
        if part["flipX"]:
            sx = -sx
        if part["flipY"]:
            sy = -sy
        mount_name = _unique_name(used["bones"], "mount_" + label)
        mount = {
            "name": mount_name,
            "parent": root_name,
            "length": 0,
            "x": _fnum(part["pos"][0] / base_scale),
            "y": _fnum(part["pos"][1] / base_scale),
            "rotation": _fnum(part["rot"]),
            "scaleX": _fnum(sx),
            "scaleY": _fnum(sy),
        }
        merged["bones"].append(mount)
        bone_bases[label] = len(merged["bones"])
        for b in model.get("bones", []):
            nb = dict(b)
            nb["name"] = bm[b["name"]]
            if b["name"] == root_old:
                nb.pop("parent", None)
                nb["parent"] = mount_name
            elif "parent" in b:
                nb["parent"] = bm[b["parent"]]
            merged["bones"].append(nb)
        report = part["report"]
        report["mountBone"] = mount["name"]
        report["boneBaseIndex"] = bone_bases[label]
        report["mappedBoneCount"] = len(model.get("bones", []))

    # 槽位：按 prefab 子装配顺序整段堆叠（前面 = 后面? 见文档说明）
    slot_new = {}
    for part in parts:
        label = part["label"]
        model = part["model"]
        sm = maps["slots"][label]
        am = maps["attach"][label]
        eff_slot_atts = {}
        want_sk = part.get("skinName")
        if want_sk and any(s.get("name") == want_sk for s in model.get("skins", [])):
            eff_slot_atts = {}
            for s_ in model.get("skins", []):
                if s_.get("name") == want_sk:
                    for sname2, atts in (s_.get("attachments") or {}).items():
                        eff_slot_atts.setdefault(sname2, {}).update(atts)
                    break
        for sk in effective_skins(model, part.get("skinName")):
            for sname2, atts in (sk.get("attachments") or {}).items():
                eff_slot_atts.setdefault(sname2, {}).update(atts)
        for s in model.get("slots", []):
            old = s["name"]
            new = sm[old]
            slot_new[(label, old)] = new
            default_att = s.get("attachment")
            if default_att not in eff_slot_atts.get(old, {}):
                if eff_slot_atts.get(old):
                    default_att = next(iter(eff_slot_atts[old]))
                else:
                    default_att = None
            ns = {
                "name": new,
                "bone": maps["bones"][label].get(s.get("bone"), s.get("bone")),
                "color": s.get("color", "ffffffff"),
                "attachment": am.get(default_att) if default_att else None,
            }
            if s.get("darkColor"):
                ns["darkColor"] = s["darkColor"]
            if s.get("blend"):
                ns["blend"] = s["blend"]
            if "blendMode" in s:
                ns["blendMode"] = s["blendMode"]
            merged["slots"].append(ns)

    # 默认皮肤附件
    skin_att = merged["skins"][0]["attachments"]
    def _shift_weighted_vertices(na, offset):
        verts = na.get("vertices")
        weighted = False
        if isinstance(verts, list) and verts:
            if isinstance(na.get("uvs"), list):
                weighted = len(verts) != len(na["uvs"])
            elif na.get("vertexCount") is not None:
                weighted = len(verts) != int(na["vertexCount"]) * 2
        if weighted and offset:
            i = 0
            out = list(verts)
            while i < len(verts):
                count = int(verts[i])
                out[i] = count
                i += 1
                for _ in range(count):
                    out[i] = int(verts[i]) + offset
                    i += 4
            na["vertices"] = out

    for part in parts:
        label = part["label"]
        model = part["model"]
        sm = maps["slots"][label]
        am = maps["attach"][label]
        rm = maps["region"][label]
        base = bone_bases[label]
        for sk in model.get("skins") or []:
            for old_slot, atts in (sk.get("attachments") or {}).items():
                target = skin_att.setdefault(sm[old_slot], {})
                for key, a in atts.items():
                    na = dict(a or {})
                    _shift_weighted_vertices(na, base)
                    new_key = am.get(key, key)
                    if na.get("name"):
                        na["name"] = rm.get(na["name"], na["name"])
                    if na.get("path"):
                        na["path"] = rm.get(na["path"], na["path"])
                    if na.get("type") == "linkedmesh":
                        # 合并后所有皮肤并入 default：父网格在同一 default 皮肤内
                        na.pop("skin", None)
                        if na.get("parent"):
                            na["parent"] = am.get(na["parent"], na["parent"])
                    target[new_key] = na

    # 约束
    for key, nmap_key in (("ik", "ik"), ("transform", "transform"), ("path", "path")):
        if key not in merged:
            continue
        for part in parts:
            label = part["label"]
            model = part["model"]
            bm = maps["bones"][label]
            sm = maps["slots"][label]
            cmap = maps[nmap_key][label]
            for c in model.get(key, []):
                nc = dict(c)
                old = c.get("name")
                if old:
                    nc["name"] = cmap.get(old, old)
                nc["bones"] = [bm.get(b, b) for b in c.get("bones", [])]
                if key == "path":
                    if nc.get("target"):
                        nc["target"] = sm.get(nc["target"], nc["target"])
                else:
                    if nc.get("target"):
                        nc["target"] = bm.get(nc["target"], nc["target"])
                merged[key].append(nc)

    # 事件
    evs = merged.get("events")
    if evs is not None:
        for part in parts:
            label = part["label"]
            emap = maps["events"][label]
            for old, data in (part["model"].get("events") or {}).items():
                evs[emap.get(old, old)] = data

    # 动画
    combined = {}
    for part in parts:
        label = part["label"]
        model = part["model"]
        anims = model.get("animations") or {}
        for anim_name, src_anim in anims.items():
            # 每个子 Spine 的全部动画都保留（前缀命名）
            merged["animations"][label + "_" + anim_name] = _rename_animation(
                src_anim, maps, label, rate=1.0)
            # combined 只按 Unity prefab 当前配置的动画、各子节点 timeScale 烘焙
            if part["anim"] and part["anim"] == anim_name:
                ts = part["timeScale"] or 1.0
                rate = 1.0 / ts if ts else 1.0
                renamed = _rename_animation(src_anim, maps, label, rate=rate)
                _deep_merge_anim(combined, renamed)
                part["report"]["combinedAnim"] = anim_name
        if part["anim"] and part["anim"] not in anims:
            part["report"]["warnings"].append(
                "prefab 动画 %r 不存在，跳过" % part["anim"])
    if combined:
        merged["animations"]["combined"] = combined

    # 图集页收集（保留源 atlas 文本块）
    out_pages = []
    for part in parts:
        am = maps["attach"][part["label"]]
        rm = maps["region"][part["label"]]
        for page in part["atlas_pages"]:
            regions = []
            for name, props in page["regions"]:
                nm = rm.get(name, am.get(name, name))
                regions.append((nm, props))
            out_pages.append({
                "src_img": page["src_img"],
                "props": page["props"],
                "regions": regions,
            })
    return merged, out_pages, [p["report"] for p in parts]


# --------------------------------------------------------------------------
# 入口

def _read_part_models(layout, mode, converter, tmp, warn):
    parts = []
    labels = set()
    for i, ch in enumerate(layout["children"]):
        skel = ch.get("skeleton") or ""
        low = skel.lower()
        if low.endswith(".json"):
            model = _load_json_file(skel)
        elif mode == "direct":
            # 2026-10-14 修：模块库化后 spine38_binary 在 ..spine 下，
            # 老代码还在从 validate 包里找，导致 direct 模式一直 ImportError。
            from ..spine import spine38_binary
            model = spine38_binary.read_skeleton_json(skel)
        else:
            model = _load_spine_json_by_converter(skel, converter, tmp, i)
        parts.append({
            "label": _unique_label(labels, _sanitize_label(ch["gameObject"])),
            "model": model,
            "skinName": ch.get("initialSkinName") or "",
            "anim": ch.get("animationName") or "",
            "timeScale": float(ch.get("timeScale") or 1.0),
            "loop": bool(ch.get("loop")),
            "flipX": bool(ch.get("initialFlipX")),
            "flipY": bool(ch.get("initialFlipY")),
            "pos": list(ch.get("localPosition") or (0.0, 0.0)),
            "rot": float(ch.get("localRotationZ") or 0.0),
            "localScale": list(ch.get("localScale") or (1.0, 1.0)),
            "dataScale": float(ch.get("scale") or 1.0),
            "go": ch.get("gameObject"),
            "report": {
                "gameObject": ch.get("gameObject"),
                "skeleton": skel,
                "atlas": ch.get("atlas"),
                "animation": ch.get("animationName"),
                "skin": ch.get("initialSkinName") or "default",
                "warnings": [],
            },
        })
        skn = ch.get("initialSkinName") or ""
        if skn and not any(s.get("name") == skn for s in model.get("skins", [])):
            parts[-1]["report"]["warnings"].append(
                "皮肤 %r 不在骨架中，将按 default 处理" % skn)
        atlas = ch.get("atlas")
        if atlas and os.path.isfile(atlas):
            pages = _parse_atlas(atlas)
            for pg in pages:
                pg["src_img"] = _resolve_atlas_image(atlas, pg.get("header") or "")
            parts[-1]["atlas_pages"] = pages
        else:
            warn("缺少 atlas: %s（%s）" % (atlas, ch.get("gameObject")))
            parts[-1]["atlas_pages"] = []
    return parts


def merge_existing_spine(prefab_path, assets_root, out_dir, mode="json",
                         converter=None, want_skel=False, skel_writer="auto"):
    """返回输出文件列表。mode: 'json' 或 'direct'。"""
    converter = converter or DEFAULT_CONVERTER
    if mode not in ("json", "direct"):
        raise ValueError("mode 只能是 json / direct")
    char = os.path.splitext(os.path.basename(prefab_path))[0]
    layout = extract_unity_spine(prefab_path, assets_root)
    children = layout.get("children") or []
    if len(children) < 2:
        raise ValueError("%s 只有 %d 个子 SkeletonAnimation，无需合并"
                         % (char, len(children)))
    if mode == "json" and not os.path.isfile(converter):
        raise RuntimeError("找不到转换器: %s" % converter)

    base = char + "_合并"
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="spine_merge_", dir=out_dir)
    try:
        parts = _read_part_models(layout, mode, converter, tmp, print)
        merged, out_pages, reports = merge_spine_parts(parts, char)
        # 图集命名：单页 base.png，多页 base_0.png...
        single = len(out_pages) == 1
        for i, page in enumerate(out_pages):
            new_name = base + ".png" if single else "%s_%d.png" % (base, i)
            page["file"] = new_name
            dst = os.path.join(out_dir, new_name)
            if os.path.isfile(page.get("src_img") or ""):
                shutil.copy2(page["src_img"], dst)

        json_path = os.path.join(out_dir, base + ".json")
        atlas_path = os.path.join(out_dir, base + ".atlas")
        with open(json_path, "w", encoding="utf-8") as fp:
            json.dump(merged, fp, ensure_ascii=False, indent=1)
        _write_atlas(atlas_path, out_pages)
        try:
            from ..spine.spine_out import write_viewer_config
            write_viewer_config(
                out_dir, merged, os.path.basename(json_path),
                os.path.basename(atlas_path),
                [os.path.splitext(p["file"])[0] for p in out_pages])
        except Exception as ex:
            print("[config] 跳过:", ex)

        outputs = [json_path, atlas_path] + [
            os.path.join(out_dir, p["file"]) for p in out_pages
            if os.path.isfile(os.path.join(out_dir, p["file"]))]
        if want_skel:
            skel_path = os.path.join(out_dir, base + ".skel")
            how = _write_skel_binary(merged, skel_path, json_path, converter,
                                     skel_writer)
            print("[skel] %s（%s）" % (os.path.basename(skel_path), how))
            outputs.append(skel_path)
        else:
            how = None

        info = {
            "prefab": os.path.abspath(prefab_path),
            "mode": mode,
            "character": char,
            "skelWriter": how,
            "nameRule": "合并骨架: %s.json/.skel；图集单页 %s.png / 多页 %s_n.png"
                        % (base, base, base),
            "children": reports,
            "notes": [
                "槽位整段按 prefab 子装配顺序堆叠；若渲染层次与 Unity 相反，"
                "调换 prefab 子节点顺序即可。",
                "per-child 动画保留原时间轴；combined 已按各自 timeScale "
                "烘焙为真实时间（timeScale=1 播放）。",
            ],
        }
        info_path = os.path.join(out_dir, base + "_merge_info.json")
        with open(info_path, "w", encoding="utf-8") as fp:
            json.dump(info, fp, ensure_ascii=False, indent=1)
        outputs.append(info_path)
        return outputs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_assets_root(prefab_path):
    d = os.path.dirname(os.path.abspath(prefab_path))
    while True:
        if os.path.isdir(os.path.join(d, "prefab")) or \
                os.path.isdir(os.path.join(d, "prefabs")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="多 SkeletonAnimation prefab -> 单 Spine")
    ap.add_argument("prefab", help="角色 prefab 路径")
    ap.add_argument("out_dir", help="输出目录")
    ap.add_argument("--mode", choices=("json", "direct"), default="json",
                    help="json=先转 json 再合并；direct=直接读 skel 合并")
    ap.add_argument("--skel", action="store_true", help="额外输出 .skel")
    ap.add_argument("--converter", default=DEFAULT_CONVERTER)
    ap.add_argument("--skel-writer", choices=("auto", "python", "exe"),
                    default="auto",
                    help="写 .skel 用谁：auto=原生写出器失败再退回转换器"
                         "（默认）；python=只用原生写出器；exe=只用转换器")
    args = ap.parse_args()
    assets = _find_assets_root(args.prefab) or r"D:\VB\Search\BdOne\Assets"
    for f in merge_existing_spine(args.prefab, assets, args.out_dir,
                                  mode=args.mode, converter=args.converter,
                                  want_skel=args.skel,
                                  skel_writer=args.skel_writer):
        print(f)
