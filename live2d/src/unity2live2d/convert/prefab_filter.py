# -*- coding: utf-8 -*-
"""Filter out parts whose GameObject is inactive / whose renderer is disabled.

Unity 只绘制 activeInHierarchy 且 renderer.enabled 的物体；这些 prefab 里存在
大量「备用姿势」部件（隐藏骨骼、放下/抬起的手臂等），它们在 Unity 里不显示，
但我们照单全收会把它们画出来 —— 表现为散落的碎片。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Set

BLOCK = re.compile(r"^--- !u!(\d+) &(\d+).*?$", re.M)

RENDERER_CLASSES = {212, 137, 23, 33, 114, 1001}  # Sprite/SkinnedMesh/Mesh/... 
GO, TRANSFORM = 1, 4


def _blocks(text: str):
    marks = list(BLOCK.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        yield int(m.group(1)), int(m.group(2)), text[m.end():end]


def _fid(body: str, key: str) -> int | None:
    m = re.search(rf"{key}:\s*\{{fileID:\s*(-?\d+)\}}", body)
    return int(m.group(1)) if m else None


CONTROL_GROUPS = {"Global_CTRL", "CTRL_IK", "Controllers"}

# 备注：Puppet2D_GlobalControl 用「精灵名含 Control/ffd + 序列化开关」隐藏控制件
# （见 docs\04 E48）。我们的部件只有贴图 GUID、没有精灵名，而现有的
# 「控制组 + 命名」规则已能覆盖同类物体（RoyalArsenal 0.967），故不启用。
CONTROL_GROUPS = {"Global_CTRL", "CTRL_IK", "Controllers"}


def control_transforms(prefab: Path) -> Set[int]:
    """返回「挂在控制组下、但有 Renderer 的物体」的 Transform fileID。

    这类物体是 IK/控制器可视化（如 RoyalArsenal 的绿色圆环），Unity 运行时会
    由脚本关掉，不应该进入成品。判据完全来自 prefab 层级命名。
    """
    text = Path(prefab).read_text(encoding="utf-8", errors="replace")
    go_name: Dict[int, str] = {}
    tr_go: Dict[int, int] = {}
    tr_parent: Dict[int, int] = {}
    go_has_renderer: Dict[int, bool] = {}

    for cls, fid, body in _blocks(text):
        if cls == GO:
            m = re.search(r"m_Name:\s*(.*)", body)
            go_name[fid] = m.group(1).strip() if m else ""
        elif cls == TRANSFORM:
            g = _fid(body, "m_GameObject")
            if g is not None:
                tr_go[fid] = g
            f = _fid(body, "m_Father")
            if f is not None:
                tr_parent[fid] = f
        elif cls in RENDERER_CLASSES:
            g = _fid(body, "m_GameObject")
            if g is not None:
                go_has_renderer[g] = True

    def in_control(tr: int) -> bool:
        cur = tr
        for _ in range(12):
            g = tr_go.get(cur)
            if g is not None and go_name.get(g) in CONTROL_GROUPS:
                return True
            cur = tr_parent.get(cur, 0)
            if not cur:
                break
        return False

    import re as _re
    gizmo = _re.compile(r"(^IK_|_IK_|_CTRL|^CTRL|_GRP$|_POLE|GIZMO|Gizmo|hiddenBone)", _re.I)

    def looks_like_gizmo(tr: int) -> bool:
        g = tr_go.get(tr)
        return bool(g is not None and gizmo.search(go_name.get(g, "")))

    hidden = _re.compile(r"hiddenBone", _re.I)

    def named_hidden(tr: int) -> bool:
        g = tr_go.get(tr)
        return bool(g is not None and hidden.search(go_name.get(g, "")))

    return {tr for tr, go in tr_go.items()
            if go_has_renderer.get(go)
            and ((in_control(tr) and looks_like_gizmo(tr)) or named_hidden(tr))}


def disabled_transforms(prefab: Path) -> Set[int]:
    text = Path(prefab).read_text(encoding="utf-8", errors="replace")
    go_active: Dict[int, bool] = {}
    go_parent: Dict[int, int] = {}
    tr_go: Dict[int, int] = {}
    tr_parent: Dict[int, int] = {}
    renderers: Dict[int, list] = {}   # go -> [enabled,...]

    for cls, fid, body in _blocks(text):
        if cls == GO:
            a = re.search(r"m_IsActive:\s*(\d)", body)
            go_active[fid] = (a.group(1) == "1") if a else True
        elif cls == TRANSFORM:
            g = _fid(body, "m_GameObject")
            if g is not None:
                tr_go[fid] = g
            f = _fid(body, "m_Father")
            if f is not None:
                tr_parent[fid] = f
        elif cls in RENDERER_CLASSES:
            g = _fid(body, "m_GameObject")
            e = re.search(r"m_Enabled:\s*(\d)", body)
            if g is not None:
                renderers.setdefault(g, []).append((e.group(1) == "1") if e else True)

    # 层级：子物体会继承父物体的 inactive
    tr_children: Dict[int, list] = {}
    for tr, par in tr_parent.items():
        if par:
            tr_children.setdefault(par, []).append(tr)

    def hierarchy_active(tr: int, depth: int = 0) -> bool:
        if depth > 200 or tr not in tr_go:
            return True
        go = tr_go[tr]
        if not go_active.get(go, True):
            return False
        par = tr_parent.get(tr, 0)
        return hierarchy_active(par, depth + 1) if par else True

    disabled: Set[int] = set()
    for tr, go in tr_go.items():
        if not hierarchy_active(tr):
            disabled.add(tr)
            continue
        rs = renderers.get(go)
        if rs and not any(rs):
            disabled.add(tr)
    return disabled
