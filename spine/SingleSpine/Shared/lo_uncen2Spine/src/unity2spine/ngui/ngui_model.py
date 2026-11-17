# -*- coding: utf-8 -*-
"""把 Unity prefab / 场景资源读成便于转换的树模型。"""

import math
import os
import re

from ..unity.unity_parse import load_unity_docs, parse_scalar

NGUI_UISPRITE_GUID = "1b3dc54f924693f41b5cbecb267e647a"


def q_to_euler_z(q):
    """Unity Quaternion -> 局部 Z 欧拉角（度）。"""
    if q is None:
        return 0.0
    x = float(q.get("x", 0))
    y = float(q.get("y", 0))
    z = float(q.get("z", 0))
    w = float(q.get("w", 1))
    # 2D 旋转的 z 分量（yaw）
    sinz = 2.0 * (w * z + x * y)
    cosz = 1.0 - 2.0 * (y * y + z * z)
    return math.degrees(math.atan2(sinz, cosz))


def v3(v, default=0.0):
    if not isinstance(v, dict):
        return default, default, default
    return (float(v.get("x", default)), float(v.get("y", default)), float(v.get("z", default)))


class Node:
    __slots__ = (
        "go_id", "name", "parent_id", "children", "pos", "rot_deg",
        "scale", "active", "sprite", "transform_id", "depth",
    )

    def __init__(self, go_id, name, parent_id):
        self.go_id = go_id
        self.name = name
        self.parent_id = parent_id
        self.children = []
        self.pos = (0.0, 0.0, 0.0)
        self.rot_deg = 0.0
        self.scale = (1.0, 1.0, 1.0)
        self.active = True
        self.sprite = None
        self.transform_id = None
        self.depth = 0

    def __repr__(self):
        return f"<Node {self.name} children={len(self.children)}>"


class Assembly:
    """一次动态立绘中的一个“子装配”（本项目的服装/子 prefab）。"""

    def __init__(self, name, root_go_id, anim_ref=None):
        self.name = name
        self.root_go_id = root_go_id
        self.nodes = []            # 深度优先
        self.anim_ref = anim_ref   # {fileID,guid,type} or None
        self.atlas_path = None
        self.atlas_png_path = None
        self.clip_path = None

    def node_by_go(self):
        return {n.go_id: n for n in self.nodes}


class PrefabModel:
    def __init__(self, path):
        self.path = path
        self.docs = load_unity_docs(path)
        self.gos = {}
        self.transforms = {}          # transform 文档 fileID -> doc
        self.transform_by_go = {}     # GameObject id -> transform doc
        self.mono_by_go = {}          # GameObject id -> [mono docs]
        self.animations = {}          # doc fileID -> Animation doc
        self._index()

    def _index(self):
        for cls, fid, doc in self.docs:
            if cls == 1 and "GameObject" in doc:
                self.gos[fid] = doc["GameObject"]
            elif cls == 4 and "Transform" in doc:
                t = doc["Transform"]
                self.transforms[fid] = t
                self.transform_by_go[t.get("m_GameObject", {}).get("fileID")] = t
            elif cls == 114 and "MonoBehaviour" in doc:
                m = doc["MonoBehaviour"]
                gid = m.get("m_GameObject", {}).get("fileID")
                self.mono_by_go.setdefault(gid, []).append(m)
            elif cls == 111 and "Animation" in doc:
                self.animations[fid] = doc["Animation"]

    def go_name(self, gid):
        g = self.gos.get(gid)
        return g.get("m_Name", "?") if g else "?"

    def transform_of_go(self, gid):
        return self.transform_by_go.get(gid)

    def find_root_go(self):
        """返回没有父 Transform 的 GameObject id（若有多个只取第一个）。"""
        roots = []
        for gid, t in self.transform_by_go.items():
            father = t.get("m_Father") or {}
            if not father.get("fileID"):
                roots.append(gid)
        if len(roots) > 1:
            # 取名字与文件名一致的，或者第一个
            base = os.path.splitext(os.path.basename(self.path))[0]
            for gid in roots:
                if self.go_name(gid) == base:
                    return gid
        return roots[0] if roots else None

    def animation_components_in(self, gid, out=None):
        """收集该 GO 子树内（含自身）的 Animation 组件。"""
        if out is None:
            out = []
        t = self.transform_of_go(gid)
        if t is None:
            return out
        for comp in self.gos.get(gid, {}).get("m_Component", []):
            fid = (comp.get("component") or {}).get("fileID") if isinstance(comp, dict) else None
            if fid in self.animations:
                out.append((gid, self.animations[fid]))
        for child_tid in self.child_transform_ids(t):
            td = self.transforms.get(child_tid)
            if td:
                self.animation_components_in(td["m_GameObject"]["fileID"], out)
        return out

    @staticmethod
    def child_transform_ids(transform):
        ch = transform.get("m_Children") or []
        return [c.get("fileID") for c in ch if isinstance(c, dict)]

    def build_subtree(self, root_gid):
        """从 root GO 深度优先生成节点树。返回 (root_Node, [nodes...])。"""
        root = self._node_from_go(root_gid, None)
        order = []
        self._build_children(root, order)
        order.insert(0, root)
        return root, order

    def _node_from_go(self, gid, parent):
        g = self.gos.get(gid, {})
        node = Node(gid, g.get("m_Name", "?"), parent.go_id if parent else None)
        t = self.transform_of_go(gid)
        if t is not None:
            node.transform_id = id(t)
            node.pos = v3(t.get("m_LocalPosition"))
            node.rot_deg = q_to_euler_z(t.get("m_LocalRotation"))
            node.scale = v3(t.get("m_LocalScale"), 1.0)
            node.active = bool(g.get("m_IsActive", True))
        sp = self.find_uisprite(gid)
        if sp:
            node.sprite = {
                "atlas_guid": (sp.get("mAtlas") or {}).get("guid"),
                "sprite_name": sp.get("mSpriteName", ""),
                "width": int(sp.get("mWidth", 0) or 0),
                "height": int(sp.get("mHeight", 0) or 0),
                "depth": int(sp.get("mDepth", 0) or 0),
                "color": sp.get("mColor"),
                "type": int(sp.get("mType", 0) or 0),
                "flip": int(sp.get("mFlip", 0) or 0),
            }
            node.depth = node.sprite["depth"]
        return node

    def _build_children(self, node, order):
        t = self.transform_by_go.get(node.go_id)
        if t is None:
            return
        for tid in self.child_transform_ids(t):
            td = self.transforms.get(tid)
            if td is None:
                continue
            gid = td["m_GameObject"]["fileID"]
            child = self._node_from_go(gid, node)
            node.children.append(child)
            order.append(child)
            self._build_children(child, order)

    def find_uisprite(self, gid):
        for m in self.mono_by_go.get(gid, []):
            if (m.get("m_Script") or {}).get("guid") == NGUI_UISPRITE_GUID:
                return m
        return None

    def find_animation_components(self):
        out = []
        for gid in self.gos:
            for m in self.gos.get(gid, {}).get("m_Component", []):
                fid = (m.get("component") or {}).get("fileID") if isinstance(m, dict) else None
                if fid in self.animations:
                    out.append((gid, self.animations[fid]))
        return out

    def costumes(self):
        """返回 (Assembly) 列表：带 Animation 组件的子树（本项目=服装子装配）。"""
        assemblies = []
        seen = set()
        for gid, anim in self.find_animation_components():
            if gid in seen:
                continue
            seen.add(gid)
            ref = anim.get("m_Animation")
            asm = Assembly(self.go_name(gid), gid, ref)
            _, asm.nodes = self.build_subtree(gid)
            assemblies.append(asm)
        return assemblies


def resolve_guid_asset(root, guid, ext=None):
    """在 Unity 工程里按 meta guid 找资源路径（返回 .meta 对应资源路径）。"""
    if not guid:
        return None
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.endswith(".meta"):
                continue
            p = os.path.join(dirpath, f)
            try:
                text = open(p, encoding="utf-8", errors="replace").read(500)
            except OSError:
                continue
            if re.search(r"guid: *" + re.escape(guid), text):
                res = p[:-5]
                if ext and not res.lower().endswith(ext):
                    continue
                return res
    return None
