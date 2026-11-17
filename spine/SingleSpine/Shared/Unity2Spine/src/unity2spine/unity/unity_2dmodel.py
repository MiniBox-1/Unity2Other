# -*- coding: utf-8 -*-
"""解析 Sprite+Mesh（2DModel）prefab：Transform/渲染器/材质/动画引用。"""

import os
import re
import json

from ..unity.unity_parse import load_unity_docs


def _comp_ref(v):
    if isinstance(v, dict):
        inner = v.get("component") or {}
        if isinstance(inner, dict) and inner:
            return inner.get("fileID")
        return v.get("fileID")
    return None


def _dfs_transforms(transforms, roots):
    """按层级深度优先展开 transform（自身 → 子物体按 m_Children 顺序）。"""
    order, seen = [], set()
    stack = [r for r in reversed(list(roots or []))]
    while stack:
        tfid = stack.pop()
        if tfid in seen or tfid not in transforms:
            continue
        seen.add(tfid)
        order.append(tfid)
        kids = [k for k in (transforms[tfid].get("kids") or [])
                if k in transforms and k not in seen]
        stack.extend(reversed(kids))
    return order


def pick_main_animator(transforms, animators, roots):
    """挑主 Animator：对齐 Unity 侧 `GetComponentInChildren<Animator>(true)`
    —— 按层级深度优先取第一个（不是按组件在文件里的先后顺序）。

    一个角色常有**多个 Animator**（辅助件/换装用），例如
    blacklilith_skin1 的 `3P_BlackLilith_NS1_Chair_Only`（没挂控制器）、
    daika_skin1_dl 的 `BR_Daika_NS1_Chair_Only`（部件全被 SetActive=0）。
    以前取 `animators[0]`——组件在 prefab 与 scene 里的文档顺序不同，会选到
    这些辅助 Animator，于是：
      · 没控制器的那个 → 报“没有可用 AnimatorClip”，导出直接失败；
      · 部件全禁用的那个 → 真正的主角子树被当成“次要 Animator 驱动”排除，
        校验拿不到样本（表现为“未校准”）。
    没挂控制器的 Animator 拿不到任何 clip，所以优先跳过。
    """
    order = _dfs_transforms(transforms, roots)
    by_tf = {}
    for a in animators or []:
        tf = a.get("tf")
        if tf is not None:
            by_tf.setdefault(tf, a)
    first = None
    for tfid in order:
        a = by_tf.get(tfid)
        if a is None:
            continue
        if first is None:
            first = a
        if a.get("controllerGuid"):
            return a
    return first


def rel_path_in(host_path, full_path):
    """节点相对 Animator 宿主的曲线 path（按**全路径分段**截断）。

    不能用名字 `find` / `rfind`：节点重名，或者一个宿主名正好是另一个宿主名的
    前缀时会串台——babariana 的 `Char_PECS_Babariana_NS1` 与
    `Char_PECS_Babariana_NS1_Bg_Only` 就是这种关系（`rfind` 会截错位置）。
    不在宿主子树里（或宿主路径为空）时返回 None，调用方自行回退。
    """
    host_path = host_path or ""
    full_path = full_path or ""
    if not host_path:
        return full_path
    if full_path == host_path:
        return ""
    pre = host_path + "/"
    if full_path.startswith(pre):
        return full_path[len(pre):]
    return None


class TwoDModel:
    def __init__(self):
        self.roots = []
        self.transforms = {}      # tfid -> dict
        self.gameobjects = {}     # gid -> {'name', 'path'}
        self.go_of_component = {}
        self.renderers = []       # 全部可见部件
        self.animator_controller_guid = None
        self.anim_root_path = ""
        self.animators = []
        self.component_of_go = {}

    def build(self, prefab_path, assets_root):
        docs = load_unity_docs(prefab_path)
        # 先收集 MeshRenderer(23) 的排序/材质（static MeshFilter 对应 GO 上）
        mesh_renderers = {}   # go -> {materials:[guid], sortingOrder:int}
        for c, fid, d in docs:
            if c == 1 and "GameObject" in d:
                g = d["GameObject"]
                self.gameobjects[fid] = {"name": g.get("m_Name") or "",
                                         "active": int(g.get("m_IsActive", 1)) != 0,
                                         "comps": [
                                             (_comp_ref(x) if isinstance(x, dict)
                                              else None)
                                             for x in g.get("m_Component") or []]}
        for gid, g in self.gameobjects.items():
            for cid in g["comps"]:
                self.go_of_component[cid] = gid

        for c, fid, d in docs:
            if c == 23 and "MeshRenderer" in d:
                mr = d["MeshRenderer"]
                gid = self.go_of_component.get(fid)
                if gid is None:
                    continue
                mats = []
                for m0 in mr.get("m_Materials") or []:
                    g = (m0 or {}).get("guid")
                    if g:
                        mats.append(g)
                mesh_renderers[gid] = {
                    "materials": mats,
                    "sortingOrder": int(mr.get("m_SortingOrder", 0) or 0),
                }

        for c, fid, d in docs:
            if c == 4 and "Transform" in d:
                t = d["Transform"]
                gid = _comp_ref(t.get("m_GameObject"))
                rot = t.get("m_LocalRotation") or {}
                pos = t.get("m_LocalPosition") or {}
                sc = t.get("m_LocalScale") or {}
                self.transforms[fid] = {
                    "go": gid, "father": _comp_ref(t.get("m_Father")),
                    "kids": [(_comp_ref(x) if isinstance(x, dict) else None)
                             for x in t.get("m_Children") or []],
                    "pos": [float(pos.get("x", 0)), float(pos.get("y", 0)),
                            float(pos.get("z", 0))],
                    "quat": [float(rot.get("x", 0)), float(rot.get("y", 0)),
                             float(rot.get("z", 0)), float(rot.get("w", 1))],
                    "scale": [float(sc.get("x", 1)), float(sc.get("y", 1)),
                              float(sc.get("z", 1))],
                }
        for tfid, t in self.transforms.items():
            gid = t["go"]
            nm = self.gameobjects.get(gid, {}).get("name", "")
            parts = [nm]
            f = t["father"]
            seen = 0
            while f in self.transforms and seen < 100:
                g2 = self.transforms[f]["go"]
                parts.append(self.gameobjects.get(g2, {}).get("name", ""))
                f = self.transforms[f]["father"]
                seen += 1
            t["name"] = nm
            t["path"] = "/".join(reversed(parts))
            if self.transforms.get(t["father"]) is None:
                self.roots.append(tfid)

        def owner_gid(cid):
            return self.go_of_component.get(cid)

        for c, fid, d in docs:
            if c == 137 and "SkinnedMeshRenderer" in d:
                smr = d["SkinnedMeshRenderer"]
                gid = owner_gid(fid)
                mesh_guid = (smr.get("m_Mesh") or {}).get("guid")
                bones = [(_comp_ref(b) if isinstance(b, dict) else None)
                         for b in smr.get("m_Bones") or []]
                mats = []
                for m0 in smr.get("m_Materials") or []:
                    g = (m0 or {}).get("guid")
                    if g:
                        mats.append(g)
                # SMR 自己的包围盒（局部空间）。没有 m_Bones 的部件，
                # Unity 实际渲染范围以它为准，可用来反推缺失的缩放。
                ab = smr.get("m_AABB") or {}
                ac = ab.get("m_Center") or {}
                ae = ab.get("m_Extent") or {}
                aabb = ([float(ac.get("x", 0) or 0),
                         float(ac.get("y", 0) or 0),
                         float(ac.get("z", 0) or 0)],
                        [float(ae.get("x", 0) or 0),
                         float(ae.get("y", 0) or 0),
                         float(ae.get("z", 0) or 0)])
                self.renderers.append({
                    "kind": "skinned", "go": gid,
                    "tfid": self._tf_of_go(gid, docs),
                    "meshGuid": mesh_guid,
                    "bones": bones,
                    "rootBone": _comp_ref(smr.get("m_RootBone")),
                    "materials": mats,
                    "aabb": aabb,
                    "enabled": int(smr.get("m_Enabled", 1)) != 0,
                    "sortingOrder": int(smr.get("m_SortingOrder", 0) or 0),
                })
            elif c == 33 and "MeshFilter" in d:
                mf = d["MeshFilter"]
                gid = owner_gid(fid)
                mrinfo = mesh_renderers.get(gid) or {}
                self.renderers.append({
                    "kind": "static", "go": gid,
                    "tfid": self._tf_of_go(gid, docs),
                    "meshGuid": (mf.get("m_Mesh") or {}).get("guid"),
                    "bones": [],
                    "materials": mrinfo.get("materials") or [],
                    "sortingOrder": mrinfo.get("sortingOrder", 0),
                    "enabled": True,
                })
            elif c == 212 and "SpriteRenderer" in d:
                sr = d["SpriteRenderer"]
                gid = owner_gid(fid)
                mats = []
                for m0 in sr.get("m_Materials") or []:
                    g = (m0 or {}).get("guid")
                    if g:
                        mats.append(g)
                if not mats:
                    m0 = sr.get("m_Material") or {}
                    if m0.get("guid"):
                        mats.append(m0["guid"])
                self.renderers.append({
                    "kind": "sprite", "go": gid,
                    "tfid": self._tf_of_go(gid, docs),
                    "spriteGuid": (sr.get("m_Sprite") or {}).get("guid"),
                    "materials": mats,
                    "enabled": int(sr.get("m_Enabled", 1)) != 0,
                    "color": sr.get("m_Color") or {},
                    "sortingOrder": int(sr.get("m_SortingOrder", 0) or 0),
                    # Unity 的 flipX/flipY 只翻贴图（UV），不动几何矩阵。
                    # 不读它就会看到“脸/眼镜方向反了”这类问题
                    # （constantias2_skin1 的 face / face_ani 就是 flipX=1）。
                    "flipX": int(sr.get("m_FlipX", 0) or 0) != 0,
                    "flipY": int(sr.get("m_FlipY", 0) or 0) != 0,
                })
            elif c == 95 and "Animator" in d:
                ac = (d["Animator"].get("m_Controller") or {})
                gid = owner_gid(fid)
                self.animators.append({"go": gid,
                                       "tf": self._tf_of_go(gid, docs),
                                       "controllerGuid": ac.get("guid")})
        if self.animators:
            sel = pick_main_animator(self.transforms, self.animators,
                                     self.roots)
            if sel is None:
                sel = next((a for a in self.animators
                            if a.get("controllerGuid")), self.animators[0])
            self.animator_controller_guid = sel.get("controllerGuid")
            self.anim_root_name = self.gameobjects.get(sel["go"], {}).get("name", "")
            self.anim_root_path = next(
                (t["path"] for t in self.transforms.values()
                 if t["go"] == sel["go"]), "")
        else:
            self.anim_root_name = ""
            self.anim_root_path = ""
        for tfid, t in self.transforms.items():
            rel = rel_path_in(self.anim_root_path, t["path"])
            t["anim_path"] = t["path"] if rel is None else rel
        # activeInHierarchy：自身 m_IsActive 与所有祖先都启用才算可见
        # （Unity 里用 SetActive 切换表情部件，禁用的部件不该被导出成常显）
        for tfid, t in self.transforms.items():
            ok, cur, hops = True, tfid, 0
            while cur is not None and hops < 500:
                td = self.transforms.get(cur)
                if td is None:
                    break
                if not self.gameobjects.get(td["go"], {}).get("active", True):
                    ok = False
                    break
                cur = td.get("father")
                hops += 1
            t["activeInHierarchy"] = ok
        for r in self.renderers:
            td = self.transforms.get(r.get("tfid")) or {}
            r["activeInHierarchy"] = bool(td.get("activeInHierarchy", True))
        return self

    def _tf_of_go(self, gid, docs=None):
        for tfid, t in self.transforms.items():
            if t["go"] == gid:
                return tfid
        return None

    def setup_transform(self, tfid):
        t = self.transforms[tfid]
        return {"pos": list(t["pos"]), "quat": list(t["quat"]),
                "scale": list(t["scale"])}


_GUID_CACHE = {}
_GUID_INDEX = None


def _guid_index_path(assets_root):
    import hashlib
    tag = hashlib.md5(os.path.abspath(assets_root).encode("utf-8")).hexdigest()[:12]
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".guid_index_%s.json.gz" % tag)


def _load_guid_index(assets_root):
    """整棵 Assets 的 guid->资源路径索引（进程内 + 磁盘缓存）。

    旧实现每查一个 guid 都要遍历整棵 Assets 目录树，单次转换要跑几分钟；
    这里改成一次性建索引并缓存，后续查询 O(1)。
    """
    global _GUID_INDEX
    if _GUID_INDEX is not None:
        return _GUID_INDEX
    path = _guid_index_path(assets_root)
    if os.path.isfile(path):
        try:
            if path.endswith(".gz"):
                import gzip
                with gzip.open(path, "rt", encoding="utf-8") as fp:
                    idx = json.load(fp)
            else:
                with open(path, encoding="utf-8") as fp:
                    idx = json.load(fp)
            if idx.get("root") == os.path.abspath(assets_root):
                _GUID_INDEX = idx.get("map") or {}
                return _GUID_INDEX
        except (OSError, ValueError, EOFError):
            pass
    idx = {}
    if os.path.isdir(assets_root):
        for dirpath, _dirs, files in os.walk(assets_root):
            for fn in files:
                if not fn.endswith(".meta"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, encoding="utf-8", errors="replace") as fp:
                        head = fp.read(200)
                except OSError:
                    continue
                m = re.search(r"guid: ([0-9a-fA-F]+)", head)
                if m:
                    idx.setdefault(m.group(1), p[:-5])
    try:
        import gzip
        blob = json.dumps({"root": os.path.abspath(assets_root), "map": idx})
        with gzip.open(path, "wt", encoding="utf-8") as fp:
            fp.write(blob)
    except OSError:
        pass
    _GUID_INDEX = idx
    return idx


def find_asset_by_guid(assets_root, guid):
    """按 .meta 中的 guid 定位资源路径（进程内缓存）。"""
    if guid in _GUID_CACHE:
        return _GUID_CACHE[guid]
    idx = _load_guid_index(assets_root)
    path = idx.get(guid)
    _GUID_CACHE[guid] = path
    return path


def parse_animator_controller(path):
    """从 AnimatorController 文本里取出状态名 -> clip guid 映射（Base Layer）。

    **顺序必须和 Unity 的 `AnimatorController.animationClips` 一致** —— 它是按
    状态机里 `m_ChildStates` 的排列顺序遍历，而不是按动画状态对象在文件里的
    先后。反例：`3P_Alice_NS1.controller` 里对象顺序是 breast/Tep_1/Start/
    curtain/lobby，但 `m_ChildStates` 是 Start 打头 —— Unity 侧
    `TwoDModelCalibExport.MainClip` 的兜底分支取 `animationClips[0]` 会拿到
    `3P_Alice_NS1_start`，转换器原来按文件顺序拿 `breast`，两边主 clip 不是同一条
    （`calib_geo` 会直接拒绝比对）。见 `docs/待跑数据清单.md` 第 4 条。
    """
    text = open(path, encoding="utf-8", errors="replace").read()
    blocks = {}
    order = []
    for m in re.finditer(r"^--- !u!(\d+) &(\d+)\s*\n(.*?)(?=^--- |\Z)",
                         text, re.M | re.S):
        cls, fid, body = int(m.group(1)), int(m.group(2)), m.group(3)
        blocks[fid] = (cls, body)
        order.append(fid)

    states = {}
    for fid in order:
        cls, body = blocks[fid]
        if cls != 1102:                      # AnimatorState
            continue
        nm = re.search(r"m_Name: (.*)", body)
        mo = re.search(r"m_Motion: \{fileID: \d+, guid: ([0-9a-f]+), type: 2\}",
                       body)
        if nm and mo:
            states[fid] = {"name": nm.group(1).strip(), "clipGuid": mo.group(1)}

    # 按状态机（1107）的 m_ChildStates / m_ChildStateMachines 顺序展开
    sms = {}
    for fid in order:
        cls, body = blocks[fid]
        if cls != 1107:                      # AnimatorStateMachine
            continue
        kids = re.search(r"m_ChildStates:\n((?:  .*\n)+)", body)
        subs = re.search(r"m_ChildStateMachines:\n((?:  .*\n)+)", body)
        sms[fid] = ([int(x) for x in re.findall(r"fileID: (\d+)", kids.group(1))]
                    if kids else [],
                    [int(x) for x in re.findall(r"fileID: (\d+)", subs.group(1))]
                    if subs else [])

    out, seen = [], set()

    def walk(fid, depth=0):
        for kid in sms.get(fid, ([], []))[0]:
            if kid in states and kid not in seen:
                seen.add(kid)
                out.append(states[kid])
        if depth < 8:
            for sub in sms.get(fid, ([], []))[1]:
                walk(sub, depth + 1)

    # 第一个状态机 = 基层的根状态机（Unity 也是从它开始）
    for fid in order:
        if blocks[fid][0] == 1107:
            walk(fid)
            break
    for fid in order:                        # 剩下没被列进去的按文件顺序补
        if fid in states and fid not in seen:
            out.append(states[fid])
    return out


def parse_animator_layers(path):
    """解析 AnimatorController 的**层**结构。

    返回 `[{"name","weight","blend","defaultClipGuid","states":[(名字, guid)]}]`。

    为什么要：运行时**所有层同时求值**（高层以 Override 覆盖低层），而转换器
    原来按"单条状态 clip"采样，其它层的骨骼/morph/显隐就丢了（bheur 的 Drone 层
    是典型：drone 骨骼 + `Morph_Drone_*`）。
    """
    text = open(path, encoding="utf-8", errors="replace").read()
    blocks = {}
    for m in re.finditer(r"^--- !u!(\d+) &(\d+)\s*\n(.*?)(?=^--- |\Z)",
                         text, re.M | re.S):
        blocks[int(m.group(2))] = (int(m.group(1)), m.group(3))

    states = {}
    for fid, (c, body) in blocks.items():
        if c != 1102:
            continue
        nm = re.search(r"m_Name: (.*)", body)
        mo = re.search(r"m_Motion: \{fileID: \d+, guid: ([0-9a-f]+), type: 2\}",
                       body)
        states[fid] = {"name": (nm.group(1).strip() if nm else ""),
                       "clipGuid": (mo.group(1) if mo else None)}

    sms = {}
    for fid, (c, body) in blocks.items():
        if c != 1107:
            continue
        dflt = re.search(r"m_DefaultState: \{fileID: (\d+)\}", body)
        sms[fid] = {"default": (int(dflt.group(1)) if dflt else None),
                    "states": [int(x) for x in
                               re.findall(r"m_State: \{fileID: (\d+)\}", body)]}

    out = []
    for _fid, (c, body) in blocks.items():
        if c != 91:
            continue
        pos = body.find("m_AnimatorLayers:")
        if pos < 0:
            continue
        seg = body[pos:]
        for lay in re.finditer(
                r"-\s*serializedVersion: \d+\s*\n\s*m_Name: (.*?)\n"
                r"\s*m_StateMachine: \{fileID: (\d+)\}([\s\S]*?)"
                r"(?=\n\s*-\s*serializedVersion: \d+\s*\n\s*m_Name: |\Z)",
                seg):
            name = lay.group(1).strip()
            smfid = int(lay.group(2))
            rest = lay.group(3)
            w = re.search(r"m_DefaultWeight: ([-0-9.eE]+)", rest)
            b = re.search(r"m_BlendingMode: (\d+)", rest)
            sm = sms.get(smfid, {})
            states_of_layer = []
            for s in sm.get("states", []):
                info = states.get(s)
                if info and info.get("clipGuid"):
                    states_of_layer.append((info["name"], info["clipGuid"]))
            dflt = states.get(sm.get("default")) or {}
            out.append({"name": name,
                        "weight": (float(w.group(1)) if w else 1.0),
                        "blend": (int(b.group(1)) if b else 0),
                        "defaultClipGuid": dflt.get("clipGuid"),
                        "states": states_of_layer})
    return out
