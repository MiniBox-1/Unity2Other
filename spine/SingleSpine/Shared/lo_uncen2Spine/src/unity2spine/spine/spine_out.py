# -*- coding: utf-8 -*-
"""把 NGUI 动态立绘的一个子装配转换成 Spine 3.8 JSON + .atlas。"""

import json
import math
import os


def fnum(v, precision=6):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return 0
    if isinstance(v, float):
        r = round(v, precision)
        if r == int(r):
            return float(int(r))
        return r
    return v


def color_hex(c):
    vals = []
    for k in ("r", "g", "b", "a"):
        v = float((c or {}).get(k, 1.0))
        vals.append(max(0, min(255, int(round(v * 255)))))
    return "%02x%02x%02x%02x" % tuple(vals)


def anim_slots(anim):
    """取一条动画的 slot 时间轴表，返回 **{槽位名: {...}}**。

    Spine 3.8 JSON 的规范形状是 `animations[x].slots.<皮肤名>.<槽位名>`（皮肤层
    通常就是 `"default"`，和 `deform` 同一套约定）。本转换器 2026-10-09 之前
    写的是**扁平**的 `slots.<槽位名>`，Spine 编辑器/任何读 JSON 的运行时会把它
    当成皮肤名、于是**整条附件/颜色时间轴被静默忽略**（`.skel` 侧不受影响，
    因为二进制格式里 slot 时间轴带的是槽位下标）。
    这里两种形状都认，便于读旧产物。
    """
    s = (anim or {}).get("slots") or {}
    inner = s.get("default")
    if isinstance(inner, dict) and inner:
        return inner
    return s


def region_geometry(sprite_widget, atlas_sprite):
    """计算 NGUI UISprite 部件在自身节点坐标系下的可见矩形。

    返回 (x, y, width, height)：区域中心相对节点原点，及绘制的宽高。
    NGUI(UISprite.cs drawingDimensions + OnFill)中，atlas 裁切块被
    按整帧画布比例放大后放回 padding 指定的位置。
    """
    fw = atlas_sprite["width"] + atlas_sprite["paddingLeft"] + atlas_sprite["paddingRight"]
    fh = atlas_sprite["height"] + atlas_sprite["paddingTop"] + atlas_sprite["paddingBottom"]
    ww = float(sprite_widget["width"])
    wh = float(sprite_widget["height"])
    if ww <= 0 or wh <= 0 or fw <= 0 or fh <= 0:
        return 0.0, 0.0, float(atlas_sprite["width"]), float(atlas_sprite["height"])
    # UISprite.drawingDimensions：奇宽高时把 1px 补到 right/top
    eff_w = fw + (fw & 1)
    eff_h = fh + (fh & 1)
    px = ww / eff_w
    py = wh / eff_h
    w = atlas_sprite["width"]
    h = atlas_sprite["height"]
    pl = atlas_sprite["paddingLeft"]
    pb = atlas_sprite["paddingBottom"]
    pt = atlas_sprite["paddingTop"]
    x = (pl + w * 0.5) * px - ww * 0.5
    y = (pb + h * 0.5) * py - wh * 0.5
    return x, y, w * px, h * py


def make_skeleton_json(asm, atlas_by_name, atlas_name=None, clip_name=None):
    """asm: ngui_model.Assembly；atlas_by_name: {sprite_name: sprite_meta}。"""
    nodes = asm.nodes
    by_go = asm.node_by_go()
    name_count = {}
    for n in nodes:
        name_count[n.name] = name_count.get(n.name, 0) + 1

    def uniq(n, suffix_seed=0):
        if name_count[n.name] == 1:
            return n.name
        # 少见重名：加父名
        p = by_go.get(n.parent_id)
        return ("%s/%s" % (p.name, n.name)) if p else (n.name + "_%d" % suffix_seed)

    bone_names = {}
    for n in nodes:
        bone_names[n.go_id] = uniq(n)

    bones = []
    root_name = None
    for n in nodes:
        parent = by_go.get(n.parent_id)
        bone = {
            "name": bone_names[n.go_id],
            "length": 0,
            "x": fnum(n.pos[0]),
            "y": fnum(n.pos[1]),
            "rotation": fnum(n.rot_deg),
            "scaleX": fnum(n.scale[0]),
            "scaleY": fnum(n.scale[1]),
        }
        if parent is not None:
            bone["parent"] = bone_names[parent.go_id]
        else:
            root_name = bone["name"]
        bones.append(bone)

    sprite_nodes = [n for n in nodes if n.sprite]
    # NGUI 按 widget.depth 绘制：depth 小先画（在底层）
    sprite_nodes = sorted(
        sprite_nodes, key=lambda n: (n.sprite["depth"], nodes.index(n)))
    slots = []
    skin_attach = {}
    for n in sprite_nodes:
        sp = n.sprite
        meta = atlas_by_name.get(sp["sprite_name"])
        if meta is None:
            print("  [warn] atlas region missing:", sp["sprite_name"])
            continue
        x, y, w, h = region_geometry(sp, meta)
        slot = {
            "name": bone_names[n.go_id],
            "bone": bone_names[n.go_id],
            "color": color_hex(sp.get("color")),
            "attachment": sp["sprite_name"] if n.active else None,
        }
        slots.append(slot)
        skin_attach.setdefault(bone_names[n.go_id], {})[sp["sprite_name"]] = {
            "type": "region",
            "path": sp["sprite_name"],
            "x": fnum(x),
            "y": fnum(y),
            "scaleX": 1,
            "scaleY": 1,
            "rotation": 0,
            "width": fnum(w),
            "height": fnum(h),
        }

    data = {
        "skeleton": {
            "hash": "ngui2spine-3.8",
            "spine": "3.8.99",
            "x": 0,
            "y": 0,
            "width": 0,
            "height": 0,
            "fps": 60,
        },
        "bones": bones,
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin_attach}],
        "animations": {},
    }
    if clip_name:
        data["animations"][clip_name] = {}
    return data


def atlas_text(pages):
    """Spine 3.8 .atlas 文本。
    pages: [{"file":..., "size":(w,h), "regions":[(name,meta)]}]
    """
    out = []
    for pi, page in enumerate(pages):
        out.append(page["file"])
        out.append("size: %d,%d" % page["size"])
        out.append("format: RGBA8888")
        out.append("filter: Linear,Linear")
        out.append("repeat: none")
        for name, meta in page["regions"]:
            # 该管线（spine 3.8 运行时/离线 Render）的 .atlas xy 与
            # NGUI UIAtlas.asset 一样以图片左上角为原点，直接写原值即可。
            y = meta["y"]
            out.append(name)
            out.append("  rotate: false")
            out.append("  xy: %d, %d" % (meta["x"], y))
            out.append("  size: %d, %d" % (meta["width"], meta["height"]))
            out.append("  orig: %d, %d" % (meta["width"], meta["height"]))
            out.append("  offset: 0, 0")
            out.append("  index: -1")
        if pi + 1 < len(pages):
            out.append("")
    # **末尾必须有一个换行**（2026-09-17 实测）：
    # spine-cpp 3.8 的 .atlas 解析在"文件正好在最后一行属性处结束（EOF 无换行）"
    # 时会越界读，多页图集尤其明显 —— beasthunter_skin1 的 416 B atlas 让
    # `SpineData` 构造直接 0xC0000005；同一份内容补 1 个字节（`\n`/空格/`\0`…）
    # 就正常。单页图集不触发，所以以前一直没发现。
    # 详见 docs/历史问题与修复.md「spine-cpp 3.8 的 atlas 越界读」。
    return "\n".join(out) + "\n"


def write_outputs(data, pages, out_dir, base_name):
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, base_name + ".json")
    atlas_path = os.path.join(out_dir, base_name + ".atlas")
    with open(json_path, "w", encoding="utf-8") as fp:
        # **紧凑输出**（不带 indent/分隔符空格）。indent=1 时纯数字数组会被
        # 撑到 ~2.3 倍（Alice 基线实测 105.8MB → 紧凑 45MB），查看器加载明显变慢；
        # 合并工具（merge_cs_bake）本来就是紧凑写，两边口径也不一致。
        json.dump(data, fp, ensure_ascii=False, separators=(",", ":"))
    with open(atlas_path, "w", encoding="utf-8") as fp:
        fp.write(atlas_text(pages))
    write_viewer_config(out_dir, data, os.path.basename(json_path),
                        os.path.basename(atlas_path),
                        [os.path.splitext(p["file"])[0] for p in pages])
    return json_path, atlas_path


# ---------------------------------------------------------------- 查看器配置
# 与本项目查看器（Live2D 编辑器同款的 .config.json）保持同一 schema：
#   type=9 表示 Spine；controllers 是播放控制器的默认参数；
#   options.scale_factor 只影响打开时的初始缩放；
#   atlases[].tex_names 是图集页文件名（不含扩展名）。
VIEWER_CONTROLLERS = {
    "param_hit": {},
    "param_loop": {},
    "key_trigger": {},
    "eye_blink": {"min_interval": 500, "max_interval": 6000},
    "lip_sync": {"gain": 5.0},
    "mouse_tracking": {"smooth_time": 0.15},
    "auto_breath": {},
    "extra_motion": {},
    "accelerometer": {},
    "intimacy_system": {},
    "slot_opacity": {},
    "slot_color": {},
}
VIEWER_TARGET_SPAN = 100.0     # 初始缩放的参考尺寸：scale = 100 / 骨架跨度


def _skeleton_extent(data):
    """骨架内容包围盒 (w, h)：网格附件取顶点，region 附件取 x/y/width/height。"""
    xs, ys = [], []
    for skin in data.get("skins") or []:
        for atts in (skin.get("attachments") or {}).values():
            for a in atts.values():
                v = a.get("vertices") or []
                # 只处理"非加权 mesh 的扁平坐标数组"；加权 mesh / 其它格式跳过
                if isinstance(v, list) and len(v) % 2 == 0 and all(
                        isinstance(x, (int, float)) for x in v):
                    xs += [float(x) for x in v[0::2]]
                    ys += [float(x) for x in v[1::2]]
                elif isinstance(v, list) and v and all(
                        isinstance(p, (list, tuple)) and len(p) >= 2 for p in v):
                    xs += [float(p[0]) for p in v]
                    ys += [float(p[1]) for p in v]
                if a.get("type") == "region":
                    try:
                        x = float(a.get("x") or 0.0)
                        y = float(a.get("y") or 0.0)
                        w = float(a.get("width") or 0.0)
                        h = float(a.get("height") or 0.0)
                        xs += [x - w / 2, x + w / 2]
                        ys += [y - h / 2, y + h / 2]
                    except (TypeError, ValueError):
                        pass
    if not xs or not ys:
        return None
    return max(xs) - min(xs), max(ys) - min(ys)


def viewer_config(data, skeleton_name, atlas_name, page_names,
                  scale_factor=None):
    if scale_factor is None:
        ext = _skeleton_extent(data)
        span = max(ext) if ext else 0.0
        scale_factor = VIEWER_TARGET_SPAN / span if span > 1e-6 else 1.0
        scale_factor = max(0.01, min(10000.0, round(scale_factor, 1)))
    return {
        "type": 9,
        "controllers": VIEWER_CONTROLLERS,
        "options": {
            "scale_factor": scale_factor,
            "tex_type": 0,
            "edge_padding": False,
            "shader_type": 1,
        },
        "skeleton": skeleton_name,
        "atlases": [{
            "atlas": atlas_name,
            "tex_names": list(page_names),
            "textures": [n + ".png" for n in page_names],
        }],
    }


def write_viewer_config(out_dir, data, skeleton_name, atlas_name, page_names,
                        scale_factor=None, merge=True, override_scale=False,
                        name=None):
    """写 `<out_dir>/<name>.config.json`（默认 name = 目录名），方便查看器直接打开本目录。

    2026-10-10：文件名从 `.config.json`（无前缀，藏在目录里）改成
    **`<目录名>.config.json`**（和角色同名，一眼能认出来是哪个角色的配置）。
    若老导出留下了 `.config.json`，会先把它**改名迁移**过来再合并，配置不丢。

    merge=True（默认）时，若已存在配置文件，则**保留查看器里已有的设置**
    （controllers / options，例如用户调好的缩放），只更新骨架与图集引用，
    避免每次导出都覆盖掉用户在查看器里调好的参数。
    """
    cfg = viewer_config(data, skeleton_name, atlas_name, page_names,
                        scale_factor)
    stem = name or os.path.basename(os.path.normpath(out_dir))
    path = os.path.join(out_dir, stem + ".config.json")
    legacy = os.path.join(out_dir, ".config.json")
    if not os.path.isfile(path) and os.path.isfile(legacy):
        try:
            os.replace(legacy, path)
        except OSError:
            pass
    if merge and os.path.isfile(path):
        try:
            old = json.load(open(path, encoding="utf-8-sig"))
        except (ValueError, OSError):
            old = None
        if isinstance(old, dict):
            merged = dict(old)
            merged["type"] = old.get("type", cfg["type"])
            if not isinstance(merged.get("controllers"), dict):
                merged["controllers"] = cfg["controllers"]
            opts = dict(cfg["options"])
            for k, v in (old.get("options") or {}).items():
                if k in opts:
                    opts[k] = v
            if override_scale and scale_factor is not None:
                opts["scale_factor"] = scale_factor
            merged["options"] = opts
            merged["skeleton"] = skeleton_name
            merged["atlases"] = cfg["atlases"]
            cfg = merged
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(cfg, fp, ensure_ascii=False, indent=2)
    return path
