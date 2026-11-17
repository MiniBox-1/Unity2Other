# -*- coding: utf-8 -*-
"""2DModel 的 AnimatorClip 曲线解析与采样（.anim 文本）。"""

import math
import os
import re
import zlib

from ..ngui.ngui_anim import UnityAnimCurve, _comp, _hermite

# Unity 曲线里的 attribute 有时是数字（typetree_<crc32> / 纯 hash），
# 这里把已知属性名先算成 crc32，解析时反查回来。
_KNOWN_ATTRS = [
    "m_IsActive", "m_Enabled", "m_Sprite",
    "m_Color.r", "m_Color.g", "m_Color.b", "m_Color.a",
    "m_FlipX", "m_FlipY", "m_Size.x", "m_Size.y", "m_SortingOrder",
    "localEulerAngles.x", "localEulerAngles.y", "localEulerAngles.z",
]
_ATTR_BY_HASH = {zlib.crc32(n.encode()) & 0xffffffff: n
                 for n in _KNOWN_ATTRS}

# 本工程 DynamicBone 脚本的 guid（`Assets/Raw/Scripts/DynamicBone.cs.meta`）——
# 用来把"绑在弹簧组件上的 `m_Enabled`"和"绑在渲染器上的 `m_Enabled`"分开。
DB_SCRIPT_GUID = "905d812fdcfac0b284dc07ceaad98046"


def attr_name(attr):
    """把 typetree_<crc32> / 纯数字的 attribute 还原成属性名。"""
    m = re.match(r"^(?:typetree_)?(\d+)$", attr or "")
    if m:
        return _ATTR_BY_HASH.get(int(m.group(1)), attr)
    return attr


def _num(v, key=None):
    if isinstance(v, dict):
        return float(v.get(key, 0.0))
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _slope_of(block, field):
    """读一个关键帧的 inSlope/outSlope（`Infinity` = 编辑器 Constant 阶跃）。

    非有限斜率一律返回 inf —— Unity 用 ±Infinity 表示"常值段"，
    我们只要知道"这一段是阶跃"就够了（见 docs 逆向报告）。
    """
    m = re.search(r"^        " + field + r": (\S+)\s*$", block, re.M)
    if not m:
        return 0.0
    raw = m.group(1)
    if "Infinity" in raw or "inf" in raw.lower():
        return float("inf")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _slope_token(tok):
    """一个斜率记号 -> float；`Infinity`/`-Infinity` -> ±inf（常值段）。

    非有限斜率一律返回 ±inf —— Unity 用 ±Infinity 表示"编辑器 Constant
    切线 = 这一段保持左键的值"，下游按这个判据走阶跃（见 `docs` 逆向报告
    与 `static_prefab_spine.unity_curve_eval`）。
    """
    s = (tok or "").strip()
    if not s:
        return 0.0
    low = s.lower()
    if "inf" in low:
        return float("-inf") if low.startswith("-") else float("inf")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _read_path_field(block):
    """读取曲线块里的 path 字段。

    Unity 序列化超长字符串时会换行续写，例如：

        path: bone_pelvis_01/.../bone_arms_03/parts_glow_body_star_1
          (6)

    旧实现只取第一行，路径被截断，曲线会被错误地套到同名（少了 " (6)"）
    的另一个节点上——表现为这些部件在动画中“跟不上/分离”。
    这里把比 path 行缩进更深的续行拼回。
    """
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)path:\s*(.*?)\s*$", ln)
        if not m:
            continue
        indent = len(m.group(1))
        pieces = [m.group(2)]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                break
            nindent = len(nxt) - len(nxt.lstrip())
            if nindent > indent and not re.match(r"^\s*[\w\[\]_]+:\s", nxt):
                pieces.append(nxt.strip())
                j += 1
            else:
                break
        return " ".join(p for p in pieces if p).strip()
    return ""


def parse_clip(path):
    """返回 {'name':..., 'curves':[...], 'duration':...}。
    直接按文本段解析（Unity 的空 path 会被简单 YAML 解析器误吞）。"""
    text = open(path, encoding="utf-8", errors="replace").read()
    name = ""
    nm = re.search(r"m_Name: (.*?)\n", text)
    if nm:
        name = nm.group(1).strip()
    if not name:
        name = os.path.splitext(os.path.basename(path))[0]
    curves = []

    def read_section(sec_name, kind):
        marker = re.escape(sec_name) + r":\s*(\[\]\s*)?\n"
        mi = re.search(marker, text)
        if not mi:
            return
        start = mi.end()
        end = len(text)
        for other in (r"m_RotationCurves:", r"m_EulerCurves:",
                      r"m_PositionCurves:", r"m_ScaleCurves:",
                      r"m_FloatCurves:"):
            om = re.search(other, text[start:])
            if om:
                end = start + om.start()
                break
        block = text[start:end]
        entries = re.split(r"^  - curve:\s*$", block, flags=re.M)
        for ent in entries[1:]:
            path = _read_path_field(ent)
            keys, slopes = [], {}
            # 关键帧有两种写法：新版 serializedVersion: 3，旧工程用 2，
            # 只看 3 会让旧 clip 整条解析不出关键帧（时长算成 0）
            kfs = re.split(r"^      - serializedVersion: [23]\s*$", ent,
                           flags=re.M)
            for idx, kf in enumerate(kfs[1:]):
                tm = re.search(r"^        time: ([-0-9.eE]+)$", kf, re.M)
                vm = re.search(
                    r"^        value: (?:\{(?:x: ([-0-9.eE]+))?,?"
                    r"(?: y: ([-0-9.eE]+))?,?(?: z: ([-0-9.eE]+))?,?"
                    r"(?: w: ([-0-9.eE]+))?.*?\}|([-0-9.eE]+))",
                    kf, re.M)
                if not tm:
                    continue
                if vm:
                    g = vm.groups()
                    if g[4] is not None:
                        val = float(g[4])
                    else:
                        val = {"x": float(g[0] or 0), "y": float(g[1] or 0),
                               "z": float(g[2] or 0)}
                        if g[3] is not None:
                            val["w"] = float(g[3])
                else:
                    val = {}
                keys.append((float(tm.group(1)), val))
                def _sl(key):
                    # ⚠ 老实现把分量写成 `([-0-9.eE]+)`，**匹配不到 `Infinity`**
                    #   ⇒ 常值切线段（Unity 编辑器 Constant：outSlope=±Infinity）
                    #   的斜率被静默丢成 0，整段被当成平滑 Hermite 插值。
                    #   症状：`Bone_Mouth_Root` 的 Position 曲线在 0.8167→4.2s
                    #   之间本该"保持不动"，产物里却成了一条 3.4 秒的斜线
                    #   （KunoichiKaen 的"嘴巴自动向上漂"，2026-10-11）。
                    sm = re.search(r"^        " + key + r": (.*)$", kf, re.M)
                    if not sm:
                        return {}
                    raw = sm.group(1).strip()
                    if raw.startswith("{"):
                        d = {}
                        for mm in re.finditer(r"([xyzw]):\s*([^,}]+)", raw):
                            d[mm.group(1)] = _slope_token(mm.group(2))
                        return d
                    return _slope_token(raw)
                slopes[(idx, "in")] = _sl("inSlope")
                slopes[(idx, "out")] = _sl("outSlope")
            if keys:
                curves.append(UnityAnimCurve(path, kind, keys, slopes))

    read_section("m_RotationCurves", "rot")
    read_section("m_EulerCurves", "euler")
    read_section("m_PositionCurves", "pos")
    read_section("m_ScaleCurves", "scale")
    # m_FloatCurves 里两类"显隐"曲线：
    #   attribute: m_IsActive  —— GameObject.SetActive（影响整棵子树）
    #   attribute: m_Enabled   —— Renderer.enabled（只影响该组件）
    # 不解析它们就会把该隐藏的部件一直显示（表现为"两个眉毛"、开场多出部件）。
    active, enabled, color = {}, {}, {}
    # ★ 2026-10-12：绑在 **DynamicBone 组件**上的 `m_Enabled`（见下面赋值处的长注释）。
    enabled_db = {}
    # ★ 2026-10-11：**逐 clip 的"脚本字段"曲线**（attack 是 `script_0x...` 哈希）。
    #   这批曲线 Unity 运行时是直接写在组件字段上的（本项目全是 DynamicBone 的
    #   `m_Damping/m_Elasticity/m_Stiffness/m_Inert`），**每帧覆盖**组件平值。
    #   原来整类丢掉 ⇒ 头发/胸/裙摆的软硬在动画里不跟着变（"骨头对得上、头发还是不对"）。
    #   结构： {路径: {attribute: (keys, tans)}}；调用方按字段名映射后接进 CS 运行时。
    script = {}
    # `m_Color.*`（SpriteRenderer 的顶点色/透明度）与 `material._Color.*`（材质色）
    # 都按组件收进 color；classID 记在 color_cls 里给调用方判断（212=SpriteRenderer
    # 是渲染器自身颜色、137=SkinnedMeshRenderer 的是材质属性，语义不同）。
    color_cls = {}
    # blendShape（morph）：attribute 形如 `blendShape.<通道名>`，值是权重百分比。
    # 漏掉它 = 部件顶点不形变（bheur / alice_skin2 / babariana 等一大批角色
    # 的"变形类"部件都会偏，实测误差 0.05~0.07 世界单位）。
    morph = {}
    morph_tan = {}
    # `m_SortingOrder`：渲染排序值动画（前后层交换）。**尚未导出**，
    # 只解析出来给调用方告警（.skel 写出器已支持 drawOrder，见文档）。
    sorting = {}
    sorting_tan = {}
    # 材质属性动画（material.*）：旧结论是"未生效"（aeda 那条恒 0），
    # 这里只解析出来做统计/告警，不参与导出。
    material = {}
    # m_IsActive / m_Enabled 的**逐关键帧切线**。它们决定 Unity 运行时怎么求值：
    #   · inSlope/outSlope = ±Infinity  → 该段是"常值段"（编辑器 Constant，阶跃）；
    #   · 其余（绝大多数是 0）          → 平滑 Hermite 插值，段内会出现 0<v<1 的中间值。
    # 运行时的显隐判据是 **|v| > 0.001**（不是 v >= 0.5，见 docs 逆向报告），
    # 所以插值段"刚离开 0"就会被判为显示 —— 只看关键帧值是算不出来的，必须带切线。
    active_tan, enabled_tan = {}, {}
    fm = re.search(r"m_FloatCurves:\s*(\[\])?\s*\n", text)
    if fm:
        block = text[fm.end():]
        # 条目起始有两种序列化写法（**同一条 clip 只会用其中一种**）：
        #   ① 老：`  - serializedVersion: 2` → `    curve:` → `m_Curve:` → attribute/path
        #   ② 新（AssetRipper 2021.3 的 dump，Mobile-old 就是这种）：
        #        `  - curve:` → `      serializedVersion: 2` → `m_Curve:` → attribute/path
        # 只认 ① 会让 ② 的**整段 FloatCurves 一条都读不到** ⇒ m_IsActive（显隐）、
        # m_Color（淡入淡出）、blendShape（形变）、m_SortingOrder（前后层）全丢，
        # 表现为"该藏的影子一直显示 / 该淡出的不淡出 / 靠 SetActive 打开的部件
        # 被判成'始终禁用'直接不导出"（2026-10-09 在 3P_Alice_NS1 上定位）。
        for ent in re.split(r"^  - (?:curve:|serializedVersion: \d+)\s*$",
                            block, flags=re.M)[1:]:
            am = re.search(r"^    attribute: (.+)$", ent, re.M)
            if not am:
                continue
            attr = attr_name(am.group(1).strip())
            is_euler = attr.startswith("localEulerAngles.")
            if attr.startswith("script_"):
                p = _read_path_field(ent)
                kfs = re.split(r"^      - serializedVersion: [23]\s*$", ent,
                               flags=re.M)
                ks, tn = [], []
                for kf in kfs[1:]:
                    tm2 = re.search(r"^        time: ([-0-9.eE]+)$", kf, re.M)
                    vm2 = re.search(r"^        value: ([-0-9.eE]+)\s*$", kf, re.M)
                    if not tm2 or not vm2:
                        continue
                    # ⚠ 必须是 (time, value) 成对（`unity_curve_eval` 的 keys 格式）；
                    #   只存时间的话求值会 TypeError，而调用方 try/except 一吞就
                    #   "曲线看着接上了、其实一条没生效"（2026-10-11 踩到）。
                    ks.append((float(tm2.group(1)), float(vm2.group(1))))
                    tn.append((_slope_of(kf, "inSlope"),
                               _slope_of(kf, "outSlope")))
                if ks and p:
                    script.setdefault(p, {})[attr] = (ks, tn)
                continue
            if not (is_euler or attr in ("m_IsActive", "m_Enabled",
                                          "m_SortingOrder")
                    or attr.startswith("m_Color.")
                    or attr.startswith("material._Color.")
                    or attr.startswith("blendShape.")
                    or attr.startswith("material.")):
                continue
            # 这里也必须拼接折行的续写（和 read_section 一样）：
            # `parts_xxx` 与 `parts_xxx (1)` 是**两个不同节点**，只读第一行会把
            # 两条曲线折叠成同一个 path，后者覆盖前者 → 显隐错乱
            # （表现为“表情消失 / 眨眼只消失一半 / 手不见了”）。
            path = _read_path_field(ent)
            keys = []
            tans = []
            for kf in re.split(r"^      - serializedVersion: [23]\s*$", ent,
                               flags=re.M)[1:]:
                tm = re.search(r"^        time: ([-0-9.eE]+)$", kf, re.M)
                vm = re.search(r"^        value: ([-0-9.eE]+)$", kf, re.M)
                if tm and vm:
                    keys.append((float(tm.group(1)), float(vm.group(1))))
                    tans.append((_slope_of(kf, "inSlope"),
                                 _slope_of(kf, "outSlope")))
            if keys:
                if is_euler:
                    # 旧格式：欧拉角写在 m_FloatCurves 里，等价 localEulerAnglesRaw.*
                    comp = attr.rsplit(".", 1)[-1]
                    curves.append(UnityAnimCurve(
                        path, "euler", [(t, {comp: v}) for t, v in keys]))
                elif attr == "m_IsActive":
                    active[path] = keys
                    active_tan[path] = tans
                elif attr == "m_Enabled":
                    enabled[path] = keys
                    enabled_tan[path] = tans
                    # ★ 2026-10-12：如果这条 `m_Enabled` 是绑在 **DynamicBone 组件**上
                    #   （classID 114 + 本工程的 DynamicBone 脚本 guid），那它语义完全不同：
                    #   它不是"渲染器显隐"，而是**把弹簧组件本身关掉/打开** ——
                    #     关掉 ⇒ Update/LateUpdate 不跑 ⇒ 弹簧不推进，骨头跟着动画走；
                    #     0→1 重新打开 ⇒ `OnEnable()→ResetParticlesPosition()`
                    #       ⇒ **整条粒子链被重置成那一刻的骨头位置**（并且首帧还会跑
                    #       `Start()→SetupParticles()`，建链姿态=那一刻）。
                    #   全工程 327 条这样的曲线：62 条恒 0（整条链被禁用）、119 条会 0/1 切换。
                    if "classID: 114" in ent and DB_SCRIPT_GUID in ent:
                        enabled_db[path] = (keys, tans)
                elif attr.startswith("blendShape."):
                    # 同一个 (路径, 通道) 出现多条曲线时**后者覆盖前者**
                    chname = attr.split(".", 1)[1]
                    morph.setdefault(path, {})[chname] = keys
                    morph_tan.setdefault(path, {})[chname] = tans
                elif attr == "m_SortingOrder":
                    sorting[path] = keys
                    sorting_tan[path] = tans
                elif (attr.startswith("m_Color.")
                      or attr.startswith("material._Color.")):
                    # 颜色/透明度：按组件收进 color（r/g/b/a）
                    comp = attr.rsplit(".", 1)[-1]
                    color.setdefault(path, {})[comp] = keys
                    cm = re.search(r"^    classID: (\d+)", ent, re.M)
                    if cm:
                        color_cls[path] = int(cm.group(1))
                elif attr.startswith("material."):
                    material.setdefault(path, {})[attr] = keys
                else:
                    pass
    duration = 0.0
    for cu in curves:
        if cu.keys:
            duration = max(duration, cu.keys[-1][0])
    for keys in (list(active.values()) + list(enabled.values())
                 + [k for v in color.values() for k in v.values()]):
        duration = max(duration, keys[-1][0])

    # m_PPtrCurves：**对象引用交换**。实测只有 `attribute: m_Sprite`
    # （SpriteRenderer 换贴图 = 换表情，例如 constantias2_skin1 的 face_ani
    # 在 3.87~5.27s 换成另一张脸再换回来）。
    # 转换器目前只导出 prefab 的静态 sprite，**这条换图时间轴还没做**，
    # 所以这里先解析出来，交给调用方告警/记录（见 static_prefab_spine 的
    # `spriteSwap` 提示），不要静默丢掉。
    pptr = {}
    pm = re.search(r"  m_PPtrCurves:\s*(\[\])?\s*\n", text)
    if pm:
        block = text[pm.end():]
        nxt = re.search(r"\n  m_[A-Za-z]+:", block)
        if nxt:
            block = block[:nxt.start()]
        # ★ 2026-10-13 修：本工程这批 clip 的 PPtr 条目**没有** `serializedVersion`，
        #   而是直接 `  - curve:` 开头（实测 `3P_ConstantiaS2_NS1_2DModel_Lobby_breast.anim`
        #   的 `m_Sprite` 换脸曲线就是这么写的）⇒ 原来的 split 切不出任何条目，
        #   `pptr` 恒为空、换图既不告警也不导出（用户报"breast 脸不会变"就是这个）。
        #   两种格式都收：`  - serializedVersion: N` 或 `  - curve:`。
        for ent in re.split(r"^  - (?:serializedVersion: \d+|curve:)\s*$", block,
                            flags=re.M)[1:]:
            am = re.search(r"^    attribute: (.+)$", ent, re.M)
            pmm = re.search(r"^    path: (.+)$", ent, re.M)
            if not am or not pmm:
                continue
            ks = [(float(t), g, int(fid)) for t, fid, g in re.findall(
                r"-\s*time:\s*([-\d.eE]+)\s*\n\s*value:\s*\{fileID:\s*(\d+),"
                r"\s*guid:\s*([0-9a-f]{32})", ent)]
            if ks:
                pptr.setdefault(_read_path_field(ent),
                                {})[am.group(1).strip()] = ks

    # ★ 2026-10-12：`m_Events`（动画事件）。本工程的这批 clip 用的是
    #   `EventDynamicBone`，`data` 里写的就是要刷新的 **DynamicBone 的物件名**
    #   （`Hair` / `Breast` / `hair_set` / `Hair_set` / `Skirt_set` …）——
    #   也就是"**现在把弹簧参数重新读一遍**"的开关。
    #
    #   背景（为什么需要它）：本工程所有 DynamicBone 的 `RefreshParam` 都是 **false**
    #   （87 个 prefab / 228 个组件实测全 0），而反编译的 `DynamicBone.Update()` 里
    #   `if (this.RefreshParam) this.UpdateParameters();` 是唯一会"逐帧刷新参数"的入口
    #   ⇒ 理论上参数应当是"**建链那一刻的值 + 只在事件时刻刷新**"。
    #   全工程 244 个 clip、572 个事件，时刻集中在 0.0167~0.1667s。
    events = []
    me = re.search(r"m_Events:\s*(\[\])?\s*\n", text)
    if me and not (me.group(1) or "").strip():
        blk = text[me.end():]
        nxt = re.search(r"\n  [A-Za-z_]", blk)
        if nxt:
            blk = blk[:nxt.start()]
        for ent in re.split(r"^  - time:", blk, flags=re.M)[1:]:
            tm = re.match(r"\s*([-\d.eE+]+)", ent)
            fn = re.search(r"^\s*functionName:\s*(\S+)\s*$", ent, re.M)
            da = re.search(r"^\s*data:\s*(.*?)\s*$", ent, re.M)
            if tm is None or fn is None:
                continue
            events.append({"time": float(tm.group(1)),
                           "function": fn.group(1),
                           "data": (da.group(1) if da else "")})
    return {"name": name, "curves": curves, "duration": duration,
            "events": events,
            "active": active, "enabled": enabled, "color": color,
            "enabled_db": enabled_db,
            "script": script,
            "active_tan": active_tan, "enabled_tan": enabled_tan,
            "morph": morph, "morph_tan": morph_tan, "pptr": pptr,
            "sorting": sorting, "sorting_tan": sorting_tan,
            "color_cls": color_cls, "material": material}


class AnimSampler:
    """输入 transform 全路径 -> 基础值，按曲线求某个时刻的 local T/R/S。"""

    def __init__(self, clip, rest=None):
        self.rest = rest or {}
        self.by_path = {}
        for cu in clip["curves"]:
            self.by_path.setdefault(cu.path, []).append(cu)

    def sample(self, path, t):
        p = self.rest.get(path, {})
        out = {"pos": [p.get("px", 0), p.get("py", 0), p.get("pz", 0)],
               "euler": [p.get("rx", 0), p.get("ry", 0), p.get("rz", 0)],
               "quat": None, "scale": [p.get("sx", 1), p.get("sy", 1),
                                       p.get("sz", 1)]}
        if p.get("qx") is not None:
            out["quat"] = (p["qx"], p["qy"], p["qz"], p["qw"])
        here = self.by_path.get(path, [])
        # 同一个对象同时有 `m_RotationCurves`（四元数）和 `localEulerAnglesRaw.*`
        # 时，**Unity 用的是四元数那条**：两条曲线在关键帧上等价，但**插值方式
        # 不同**（四元数按分量 Hermite，欧拉按角度插值），真值只跟四元数吻合
        # （bheur 的 Bone_Pelvis 实测 3.878/1.045/4.458 全中，欧拉那条是
        # 2.89/-0.163/4.133）。所以有 rot 就忽略 euler。
        has_rot = any(cu.kind == "rot" for cu in here)
        for cu in here:
            if has_rot and cu.kind == "euler":
                continue
            if cu.kind in ("pos", "scale"):
                v = cu.value_at(t)
                comps = ("x", "y", "z")
                target = "pos" if cu.kind == "pos" else "scale"
                for i, c in enumerate(comps):
                    if c in v:
                        out[target][i] = v[c]
            elif cu.kind == "euler":
                v = cu.value_at(t)
                for i, c in enumerate(("x", "y", "z")):
                    if c in v:
                        out["euler"][i] = v[c]
                out["quat"] = None   # 以 euler 为准重建
            elif cu.kind == "rot":
                v = cu.value_at(t)
                # value_at 对旋转曲线返回 {'x','y','z','w'}，这里统一成四元组，
                # 否则下游 quat_to_mat 会把字典的键当成分量（部分角色只用
                # m_LocalRotation 曲线，会直接抛 TypeError）
                if isinstance(v, dict):
                    v = (v.get("x", 0.0), v.get("y", 0.0),
                         v.get("z", 0.0), v.get("w", 1.0))
                out["quat"] = v
        return out


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def euler_to_quat(e):
    """Unity 的 x/y/z 欧拉 -> 四元数（x y z 顺序：q = qy*qx*qz）。"""
    cx, cy, cz = (math.cos(math.radians(e[i] / 2.0)) for i in range(3))
    sx, sy, sz = (math.sin(math.radians(e[i] / 2.0)) for i in range(3))
    qx = (sx, 0, 0, cx)
    qy = (0, sy, 0, cy)
    qz = (0, 0, sz, cz)
    return quat_mul(quat_mul(qy, qx), qz)


def quat_to_euler(q, normalize=True):
    """Unity 的四元数 -> x/y/z 欧拉（ZXY 分解，与 `euler_to_quat` 互逆）。

    Unity 的 `Transform.localEulerAngles` 把角度归一到 `[0,360)`，这里默认照做
    （加性动画层要把"prefab 姿态的欧拉"和曲线增量相加，符号/范围必须一致）。
    """
    x, y, z, w = q
    sinx = max(-1.0, min(1.0, 2.0 * (w * x - y * z)))
    ex = math.degrees(math.asin(sinx))
    ey = math.degrees(math.atan2(2.0 * (w * y + z * x),
                                 1.0 - 2.0 * (x * x + y * y)))
    ez = math.degrees(math.atan2(2.0 * (w * z + y * x),
                                 1.0 - 2.0 * (z * z + y * y)))
    if normalize:
        ex, ey, ez = (v % 360.0 for v in (ex, ey, ez))
    return [ex, ey, ez]


def quat_to_mat(q):
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy), 0,
            2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx), 0,
            2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy), 0,
            0, 0, 0, 1]


def trs_mat(pos, quat, scale):
    """Unity 的 Matrix4x4.TRS 语义：M = T · R · S。

    注意缩放要乘在旋转矩阵的**右侧**（即按列缩放）。
    旧实现按行缩放（M = T · S · R），只有“非均匀/带负号缩放 + 有旋转”
    时才与 Unity 不一致；正是这类节点（ch_root 的 [-1,1,0.15]、
    面罩 parts_head 的 [-1,1,1]、腿部骨骼 [-0.9,0.9,0.14]）导致
    “面罩朝向/镜像反复出错”“运动中部件分离”。
    """
    m = quat_to_mat(quat)
    for c in range(3):
        for r in range(3):
            m[r * 4 + c] *= scale[c]
    m[3], m[7], m[11] = pos
    return m
