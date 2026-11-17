# -*- coding: utf-8 -*-
"""BdOne（NGUI 动态立绘）→ Spine 3.8 完整转换（在 convert_chr 路线基础上修硬伤）。

相对老路线（`ngui.convert_chr`）的差异：

1. **图集页走 asset→material→texture 链路**：老代码用"图集 asset 同目录里第一张
   png"，在 `res/<dir>` 这种"一个目录多套图集"的地方会拿错图（阿波罗/协助的
   NpcGUI624 就被裁到了 NpcGUI621 上）；
2. **region 兜底**：名字在指定图集里找不到时，回退到同目录其它图集里找；
   还找不到就跳过并记进 `_bdone_info.json` 的 `excludedParts`；
3. **骨骼命名不会撞车**：重名节点用「父/名」；若这样仍撞车，升级成「全路径」；
4. **有效可见性**：取「自身 m_IsActive 且祖先 m_IsActive」，并认 UISprite 的
   `m_Enabled`；setup 与 attachment 时间线都用有效可见；
5. **颜色多通道**：同一 path 上 mColor.r/g/b/a 多条曲线一起写；
6. **slot 时间线按 3.8 规范**嵌在 `animations[x].slots.default.<槽位>` 下；
7. **region 名与部件解耦**：图集里 region 名跨页可能重复，页内加后缀消歧。
"""

import io
import json
import math
import os
import re

from PIL import Image

from ..ngui.ngui_anim import parse_clip, quat_to_deg_z
from ..ngui.pack_images import pack_items
from ..spine.spine_out import atlas_text, color_hex, fnum, region_geometry
from ..unity.unity_parse import load_unity_docs

GUID_RE = re.compile(r"guid: *([0-9a-f]{32})")

# NGUI UIWidget.Pivot 的 pivotOffset（NGUIMath.GetPivotOffset）
#   索引 = TopLeft, Top, TopRight, Left, Center, Right, BottomLeft, Bottom, BottomRight
PIVOT_OFFSET = [(0.0, 1.0), (0.5, 1.0), (1.0, 1.0),
                (0.0, 0.5), (0.5, 0.5), (1.0, 0.5),
                (0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]


def euler_to_quat(x, y, z):
    """Unity `Quaternion.Euler(x, y, z)`（ZXY 序），角度制。"""
    hx = math.radians(x) * 0.5
    hy = math.radians(y) * 0.5
    hz = math.radians(z) * 0.5
    cx, sx = math.cos(hx), math.sin(hx)
    cy, sy = math.cos(hy), math.sin(hy)
    cz, sz = math.cos(hz), math.sin(hz)
    return {
        "x": cy * sx * cz + sy * cx * sz,
        "y": sy * cx * cz - cy * sx * sz,
        "z": cy * cx * sz - sy * sx * cz,
        "w": cy * cx * cz + sy * sx * sz,
    }


def euler_deg_z(v):
    """欧拉曲线取值 → 局部 z 角（度）。x/y 恒为 0 时就是 z 本身。"""
    x = float(v.get("x", 0.0))
    y = float(v.get("y", 0.0))
    z = float(v.get("z", 0.0))
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return z
    return quat_to_deg_z(euler_to_quat(x, y, z))


def sprite_quad(sw, meta):
    """忠实实现 `UISprite.drawingDimensions`，返回 (中心x, 中心y, 宽, 高)。

    老实现（spine_out.region_geometry）在两个地方和 NGUI 不一致：
      · 奇数尺寸时把「补 1 像素」也算进了分母（NGUI 只用它减右侧/上侧边距）；
      · 忽略 widget 的 pivot（Pivot 不是 Center 时整块会偏）。
    这两条在 BdOne 上都会实打实地错位（实测 1~4 像素级）。
    """
    mw = float(sw["width"])
    mh = float(sw["height"])
    ox, oy = PIVOT_OFFSET[int(sw.get("pivot", 4) or 0) % 9]
    x0 = -ox * mw
    x1 = x0 + mw
    y0 = -oy * mh
    y1 = y0 + mh

    rw = int(meta.get("width", 0) or 0)
    rh = int(meta.get("height", 0) or 0)
    pl = int(meta.get("paddingLeft", 0) or 0)
    pb = int(meta.get("paddingBottom", 0) or 0)
    pr = int(meta.get("paddingRight", 0) or 0)
    pt = int(meta.get("paddingTop", 0) or 0)
    typ = int(sw.get("type", 0) or 0)
    flip = int(sw.get("flip", 0) or 0)

    if typ != 2:                                   # Tiled 不做 padding 缩放
        w = rw + pl + pr
        h = rh + pb + pt
        px = py = 1.0
        if w > 0 and h > 0 and typ in (0, 3):      # Simple / Filled
            if w & 1:
                pr += 1
            if h & 1:
                pt += 1
            px = mw / w
            py = mh / h
        if flip in (1, 3):                         # 水平/双向翻转：左右边距互换
            x0 += pr * px
            x1 -= pl * px
        else:
            x0 += pl * px
            x1 -= pr * px
        if flip in (2, 3):
            y0 += pt * py
            y1 -= pb * py
        else:
            y0 += pb * py
            y1 -= pt * py
    return ((x0 + x1) * 0.5, (y0 + y1) * 0.5, x1 - x0, y1 - y0)


# ------------------------------------------------------------------ 资源索引
def build_guid_index(assets_root):
    """{guid: 资源路径}（扫 .meta）。"""
    idx = {}
    for dirpath, dirnames, files in os.walk(assets_root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in files:
            if not f.endswith(".meta"):
                continue
            p = os.path.join(dirpath, f)
            try:
                text = io.open(p, encoding="utf-8", errors="replace").read(400)
            except OSError:
                continue
            m = GUID_RE.search(text)
            if m:
                idx.setdefault(m.group(1), p[:-5])
    return idx


def read_text(path):
    try:
        return io.open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def load_atlas_regions(asset_path):
    """UIAtlas.asset → {sprite_name: meta dict}。"""
    for cls, _, doc in load_unity_docs(asset_path):
        if cls != 114 or "MonoBehaviour" not in doc:
            continue
        m = doc["MonoBehaviour"]
        if not isinstance(m.get("mSprites"), list):
            continue
        return {sp["name"]: sp for sp in m["mSprites"]}
    return {}


_GLOBAL_ATLAS_CACHE = {}


def _global_atlases(ngui_root):
    """<atlas_root>/_ngui 下所有 UIAtlas（region 名字的全局兜底，缓存）。

    有些 prefab 记录的图集里并没有自己的 region（例：npc8_1 指向 NpcGUI1，
    但 NpcGUI1 只有 npc17/npc9 的 region），真正的 region 落在同级的别的
    atlas 目录里（npc83_11 → npcgui541、Y_npc161-1_1 → npcgui185）。
    """
    if not ngui_root or not os.path.isdir(ngui_root):
        return []
    if ngui_root in _GLOBAL_ATLAS_CACHE:
        return _GLOBAL_ATLAS_CACHE[ngui_root]
    outs = []
    for dp, dn, fn in os.walk(ngui_root):
        pngs = [x for x in fn if x.lower().endswith(".png")]
        for f in sorted(fn):
            if not f.endswith(".asset"):
                continue
            p = os.path.join(dp, f)
            regions = load_atlas_regions(p)
            if not regions:
                continue
            stem = os.path.splitext(f)[0]
            cand = [x for x in pngs if os.path.splitext(x)[0] == stem]
            outs.append(AtlasInfo(None, p, None,
                                  os.path.join(dp, (cand or pngs or [""])[0]),
                                  regions))
    _GLOBAL_ATLAS_CACHE[ngui_root] = outs
    return outs


class AtlasInfo(object):
    """一个 UIAtlas：asset / material / 贴图页 / region 表。"""

    def __init__(self, guid, asset_path, mat_path, png_path, regions):
        self.guid = guid
        self.asset_path = asset_path
        self.mat_path = mat_path
        self.png_path = png_path
        self.regions = regions
        self._page = None

    @property
    def name(self):
        return os.path.basename(self.asset_path or "?")

    def page(self):
        if self._page is None:
            self._page = Image.open(self.png_path).convert("RGBA")
        return self._page


def resolve_atlas(guid, guid_idx):
    ap = guid_idx.get(guid)
    if not ap:
        return None
    txt = read_text(ap)
    mat = None
    m = re.search(r"mMaterial: *\{fileID: *-?\d+, *guid: *([0-9a-f]{32})", txt)
    if m:
        mat = guid_idx.get(m.group(1))
    if mat is None:
        for g in GUID_RE.findall(txt):
            p = guid_idx.get(g)
            if p and p.lower().endswith(".mat"):
                mat = p
                break
    png = None
    if mat:
        for g in GUID_RE.findall(read_text(mat)):
            p = guid_idx.get(g)
            if p and p.lower().endswith(".png"):
                png = p
                break
    if png is None:
        d = os.path.dirname(ap)
        stem = os.path.splitext(os.path.basename(ap))[0]
        pngs = [f for f in os.listdir(d) if f.lower().endswith(".png")]
        if pngs:
            pngs.sort(key=lambda f: (os.path.splitext(f)[0] != stem, f))
            png = os.path.join(d, pngs[0])
    return AtlasInfo(guid, ap, mat, png, load_atlas_regions(ap))
    return AtlasInfo(guid, ap, mat, png, load_atlas_regions(ap))


# ------------------------------------------------------------------ 命名
def unique_bone_names(nodes, paths):
    """给每个节点一个不会撞车的骨骼名。

    1) 名字在本装配里唯一 → 直接用；
    2) 否则用「父/名」；
    3) 仍然撞车（同名同父名的不同子树）→ 用整条相对路径；
       还撞（理论上不会）→ 末尾加 #k。
    """
    count = {}
    for n in nodes:
        count[n.name] = count.get(n.name, 0) + 1
    by_go = {n.go_id: n for n in nodes}
    cand = {}
    for n in nodes:
        if count.get(n.name, 0) == 1:
            cand[n.go_id] = n.name
        else:
            p = by_go.get(n.parent_id)
            cand[n.go_id] = ("%s/%s" % (p.name, n.name)) if p else n.name
    seen = {}
    for n in nodes:
        seen[cand[n.go_id]] = seen.get(cand[n.go_id], 0) + 1
    out = {}
    used = {}
    for n in nodes:
        name = cand[n.go_id]
        if seen.get(name, 0) > 1:
            name = paths.get(n.go_id) or name
        k = used.get(name, 0)
        used[name] = k + 1
        out[n.go_id] = name if k == 0 else "%s#%d" % (name, k + 1)
    return out


def node_path(n, by_go):
    """相对 Animation 所在 GO 的路径（去掉根名，与 .anim 曲线 path 一致）。"""
    parts = []
    cur = n
    while cur is not None and by_go.get(cur.go_id) is not None:
        parts.append(cur.name)
        cur = by_go.get(cur.parent_id)
    if parts:
        parts.pop()
    return "/".join(reversed(parts))


def effective_active(nodes):
    """{go_id: 自身且所有祖先 m_IsActive}（prefab 静态值）。"""
    by_go = {n.go_id: n for n in nodes}
    eff = {}

    def walk(n):
        if n.go_id in eff:
            return eff[n.go_id]
        p = by_go.get(n.parent_id)
        v = bool(n.active) and (walk(p) if p is not None else True)
        eff[n.go_id] = v
        return v

    for n in nodes:
        walk(n)
    return eff


# ------------------------------------------------------------------ 目标装配
class Assembly(object):
    """一次转换要用的信息（从 PrefabModel 的 Assembly 抽出来）。"""

    def __init__(self, asm, clip_path, guid_idx, atlas_cache):
        self.name = asm.name
        self.root_go = asm.root_go_id
        self.nodes = asm.nodes
        self.clip_path = clip_path
        self._guid_idx = guid_idx
        self._atlases = atlas_cache
        self.by_go = {n.go_id: n for n in asm.nodes}
        self.path_of = {n.go_id: node_path(n, self.by_go) for n in asm.nodes}
        self.bone_name = unique_bone_names(asm.nodes, self.path_of)
        self.eff_active = effective_active(asm.nodes)
        self.excluded = []       # [(部件名, sprite 名, 原因)]
        self.resolved = {}       # go_id -> (AtlasInfo, meta, sprite_name)
        self._sibling_cache = {}
        self._resolve_sprites()

    # ---- 图集与 region 解析
    def _atlas(self, guid):
        if guid not in self._atlases:
            self._atlases[guid] = resolve_atlas(guid, self._guid_idx)
        return self._atlases[guid]

    def _sibling_atlases(self, asset_path):
        """同目录下的其它 UIAtlas（region 名字兜底）。"""
        d = os.path.dirname(asset_path)
        if d in self._sibling_cache:
            return self._sibling_cache[d]
        outs = []
        pngs = [x for x in os.listdir(d) if x.lower().endswith(".png")]
        for f in sorted(os.listdir(d)):
            if not f.endswith(".asset"):
                continue
            p = os.path.join(d, f)
            regions = load_atlas_regions(p)
            if not regions:
                continue
            stem = os.path.splitext(f)[0]
            cand = [x for x in pngs if os.path.splitext(x)[0] == stem]
            info = AtlasInfo(None, p, None,
                             os.path.join(d, (cand or pngs or [""])[0]), regions)
            outs.append(info)
        # 兜底：整个 <atlas_root>/_ngui/* 下的图集（有些 prefab 引用的图集里
        # 没有自己的 region，真正的 region 落在别的 atlas 目录里，例如
        # npc83_11 的 region 在 npcgui541、Y_npc161-1_1 的在 npcgui185）。
        outs += _global_atlases(os.path.dirname(d))
        self._sibling_cache[d] = outs
        return outs

    def _resolve_sprites(self):
        for n in self.nodes:
            if not n.sprite:
                continue
            sp = n.sprite
            atlas = self._atlas(sp.get("atlas_guid"))
            if atlas is None or not atlas.regions:
                self.excluded.append((n.name, sp["sprite_name"], "图集缺失"))
                continue
            meta = atlas.regions.get(sp["sprite_name"])
            if meta is None:
                for other in self._sibling_atlases(atlas.asset_path):
                    if sp["sprite_name"] in other.regions:
                        atlas, meta = other, other.regions[sp["sprite_name"]]
                        break
            if meta is None:
                self.excluded.append((n.name, sp["sprite_name"], "region 不存在"))
                continue
            if int(meta.get("width", 0)) <= 0 or int(meta.get("height", 0)) <= 0:
                self.excluded.append((n.name, sp["sprite_name"], "region 尺寸为 0"))
                continue
            self.resolved[n.go_id] = (atlas, meta, sp["sprite_name"])

    # ---- 可见性
    def widget_enabled(self, n):
        return bool((n.sprite or {}).get("enabled", True))

    def visible_static(self, n):
        return bool(self.eff_active.get(n.go_id, True)) and self.widget_enabled(n)

    def visible_at(self, n, t, path_curves):
        """动画 t 时刻是否显示（自身/祖先 m_IsActive + widget enabled）。"""
        cur = n
        while cur is not None:
            if not self.widget_enabled(cur):
                return False
            act = None
            for c in path_curves.get(self.path_of.get(cur.go_id, ""), []):
                if c.kind == "float" and c.attribute == "m_IsActive":
                    act = c.value_at(t)
                    break
            if act is not None:
                if act <= 0.5:
                    return False
            elif not cur.active:
                return False
            cur = self.by_go.get(cur.parent_id)
        return True


# ------------------------------------------------------------------ 骨架
def build_skeleton(asm):
    """返回 (data 骨架部分, 待打包的 region 列表)。"""
    nodes = asm.nodes
    bones = []
    for n in nodes:
        b = {
            "name": asm.bone_name[n.go_id],
            "length": 0,
            "x": fnum(n.pos[0]),
            "y": fnum(n.pos[1]),
            "rotation": fnum(n.rot_deg),
            "scaleX": fnum(n.scale[0]),
            "scaleY": fnum(n.scale[1]),
        }
        p = asm.by_go.get(n.parent_id)
        if p is not None:
            b["parent"] = asm.bone_name[p.go_id]
        bones.append(b)

    sprite_nodes = [n for n in nodes if n.sprite and n.go_id in asm.resolved]
    sprite_nodes.sort(key=lambda n: (n.sprite["depth"], nodes.index(n)))

    # region 名在"一张图集页"里必须唯一：不同图集里同名 region 加后缀区分
    region_names = {}
    used_names = {}
    for n in sprite_nodes:
        atlas, meta, sp_name = asm.resolved[n.go_id]
        key = (atlas.asset_path, sp_name)
        if key in region_names:
            continue
        name = sp_name
        if used_names.get(name):
            stem = os.path.splitext(atlas.name)[0]
            name = "%s#%s" % (sp_name, stem)
            k = 2
            while used_names.get(name):
                name = "%s#%s_%d" % (sp_name, stem, k)
                k += 1
        used_names[name] = key
        region_names[key] = name

    items = {}
    for n in sprite_nodes:
        atlas, meta, sp_name = asm.resolved[n.go_id]
        key = (atlas.asset_path, sp_name)
        if key in items:
            continue
        crop = atlas.page().crop((int(meta["x"]), int(meta["y"]),
                                  int(meta["x"]) + int(meta["width"]),
                                  int(meta["y"]) + int(meta["height"])))
        items[key] = (region_names[key], crop, meta)

    slots = []
    skin = {}
    for n in sprite_nodes:
        atlas, meta, sp_name = asm.resolved[n.go_id]
        x, y, w, h = sprite_quad(n.sprite, meta)
        slot_name = asm.bone_name[n.go_id]
        slots.append({
            "name": slot_name,
            "bone": slot_name,
            "color": color_hex(n.sprite.get("color")),
            "attachment": sp_name if asm.visible_static(n) else None,
        })
        rname = region_names[(atlas.asset_path, sp_name)]
        skin.setdefault(slot_name, {})[rname] = {
            "type": "region",
            "path": rname,
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
            "hash": "bdone-ngui-3.8",
            "spine": "3.8.99",
            "x": 0, "y": 0, "width": 0, "height": 0, "fps": 60,
        },
        "bones": bones,
        "slots": slots,
        "skins": [{"name": "default", "attachments": skin}],
        "animations": {},
    }
    return data, list(items.values()), region_names


# ------------------------------------------------------------------ 动画
def build_animation(data, asm, clip_name, clip_data, dt=0.05):
    """把 Legacy clip 采样成 Spine 时间线（旋转/位移/缩放/附件/颜色）。"""
    path_curves = {}
    for c in clip_data["curves"]:
        path_curves.setdefault(c.path, []).append(c)

    times = set()
    max_t = 0.0
    for c in clip_data["curves"]:
        for t, _ in c.keys:
            times.add(t)
            max_t = max(max_t, t)
    for i in range(int(max_t / dt) + 1):
        times.add(round(i * dt, 6))
    times = sorted(times)

    def curves_of(p, kind, attr=None):
        out = []
        for c in path_curves.get(p, []):
            if c.kind != kind:
                continue
            if attr is not None and c.attribute != attr:
                continue
            out.append(c)
        return out

    anim = data["animations"].setdefault(clip_name, {})
    a_bones = anim.setdefault("bones", {})
    # Spine **3.8** 的 JSON 里 `animations.<name>.slots` 是**扁平**的
    # （`slots.<槽位名>`）；套一层皮肤名是 4.0 才有的写法。
    # 3.8 的 spine-csharp/cpp 读到皮名会当成槽位名 → 抛
    # "Slot not found" 或者整条附件/颜色时间线被丢掉。
    a_slots = {}

    def wrap_deg(a):
        while a > 180:
            a -= 360
        while a <= -180:
            a += 360
        return a

    for node in asm.nodes:
        p = asm.path_of[node.go_id]
        name = asm.bone_name[node.go_id]
        rot_cs = curves_of(p, "rot")
        euler_cs = curves_of(p, "euler")
        if rot_cs or euler_cs:
            keys = []
            last = None
            for t in times:
                if rot_cs:
                    deg = quat_to_deg_z(rot_cs[0].value_at(t))
                else:
                    deg = euler_deg_z(euler_cs[0].value_at(t))
                absdeg = deg if last is None else last + wrap_deg(deg - last)
                last = absdeg
                keys.append({"time": round(t, 6),
                             "angle": round(absdeg - node.rot_deg, 6)})
            a_bones.setdefault(name, {})["rotate"] = keys
        pos_cs = curves_of(p, "pos")
        if pos_cs:
            keys = []
            for t in times:
                v = pos_cs[0].value_at(t)
                keys.append({
                    "time": round(t, 6),
                    "x": round(float(v.get("x", node.pos[0])) - node.pos[0], 6),
                    "y": round(float(v.get("y", node.pos[1])) - node.pos[1], 6),
                })
            a_bones.setdefault(name, {})["translate"] = keys
        sc_cs = curves_of(p, "scale")
        if sc_cs:
            keys = []
            for t in times:
                v = sc_cs[0].value_at(t)
                sx = float(v.get("x", node.scale[0])) / max(abs(node.scale[0]), 1e-9)
                sy = float(v.get("y", node.scale[1])) / max(abs(node.scale[1]), 1e-9)
                keys.append({"time": round(t, 6), "x": round(sx, 6),
                             "y": round(sy, 6)})
            a_bones.setdefault(name, {})["scale"] = keys

    # ---- 槽位：附件（显隐）与颜色
    for node in asm.nodes:
        if not node.sprite or node.go_id not in asm.resolved:
            continue
        sp_name = asm.resolved[node.go_id][2]
        name = asm.bone_name[node.go_id]
        p = asm.path_of[node.go_id]
        chain, cur = [], node
        while cur is not None:
            chain.append(cur)
            cur = asm.by_go.get(cur.parent_id)
        animated_vis = (any(curves_of(asm.path_of[c.go_id], "float", "m_IsActive")
                            for c in chain)
                        or any(not c.active for c in chain)
                        or any(not asm.widget_enabled(c) for c in chain))
        if animated_vis:
            keys = []
            last = "?"
            for t in times:
                v = sp_name if asm.visible_at(node, t, path_curves) else None
                if v != last:
                    keys.append({"time": round(t, 6), "name": v})
                    last = v
            if keys:
                a_slots.setdefault(name, {})["attachment"] = keys
        color_cs = [c for c in path_curves.get(p, [])
                    if c.kind == "float" and str(c.attribute).startswith("mColor.")]
        if color_cs:
            base = node.sprite.get("color") or {}
            # 颜色/透明度在大约 0.3 s 内跑满 0→1，按 0.05 s 采样再线性插值
            # 会明显偏（实测 alpha 差 0.15）。这里对颜色单独用细栅格
            # （0.01 s）并带上曲线自己的关键帧时刻。
            col_times = set()
            for c in color_cs:
                for t, _ in c.keys:
                    col_times.add(t)
            step = min(dt, 0.01)
            for i in range(int(max_t / step) + 1):
                col_times.add(round(i * step, 6))
            keys = []
            last_hex = None
            for t in sorted(col_times):
                rgba = {k: max(0.0, min(1.0, float(base.get(k, 1.0))))
                        for k in ("r", "g", "b", "a")}
                for c in color_cs:
                    ch = str(c.attribute).split(".")[-1]
                    if ch in rgba:
                        rgba[ch] = max(0.0, min(1.0, c.value_at(t)))
                hexv = "".join("%02x" % int(round(rgba[k] * 255))
                               for k in ("r", "g", "b", "a"))
                if hexv != last_hex:
                    keys.append({"time": round(t, 6), "color": hexv})
                    last_hex = hexv
            if keys:
                a_slots.setdefault(name, {})["color"] = keys
    if a_slots:
        anim["slots"] = a_slots
    elif "slots" in anim:
        del anim["slots"]
    return data
