#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线显隐校验：拿 **clip 的 m_IsActive 曲线**（按 Unity 运行时语义求值）当基准，
检查产物 slot 时间轴。

求值口径（2026-09-14 逆向校正，见 `docs/Unity运行时逆向报告.md`）：
  · 曲线按关键帧切线求值：slope=±Infinity 的段是常值段（编辑器 Constant 阶跃），
    其余走 Hermite 插值；
  · 判据是 **|v| > 1e-3** 就算"显示"（不是 `v >= 0.5`）。
工程里那批 slope=0 的 m_IsActive（6191/6505 条）在段内一直会被判为显示 ——
这不是采样器把值"粘在 ON"，而是运行时的真实行为（同版本 Unity 实测复现）。
旧口径按"阶跃 + v>=0.5"比，会和运行时的真实可见性系统性对不上。

为什么不用 Play/Pose 真值当基准：见 docs `静态prefab路线` 8.1.8。
实测 banshee 的 breast：
  clip 里 `parts_Eye_normal` 与 `parts_Eye_Smile` 是互补对（永不同时显示），
  但两条 Unity 采样通道都让它们 202 帧里 130 帧同时 ON —— 采样器把
  "动画里 SetActive 过的物体" 一直留在 ON，离散曲线被吞掉了。
所以判定"转换器有没有漏关键帧"必须以 clip 原文为准；真值只用来查
"Unity 里没被动画管、但被父链/渲染器开关"的显隐。

用法：
    python tools/check_clip_visibility.py banshee_skin1
    python tools/check_clip_visibility.py --all <角色1> <角色2> ...
    python tools/check_clip_visibility.py --all-in-probe50
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


import argparse
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ngui2spine.static_prefab_spine import (      # noqa: E402
    ACTIVE_DEAD_BY_ROLE, USE_RUNTIME_ACTIVE, active_flip_times, active_is_on,
    unity_curve_eval)
from ngui2spine.unity_2dmodel import parse_animator_layers   # noqa: E402

ASSETS = _resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets")
PROBE50 = _resolve(r"D:\VB\Unity2Spine\_probe50")
TOL = 0.021          # 时间容差（秒），我们的关键帧按 0.05 网格取整
GRID = 0.05          # 采样网格（秒），可见性比对就在这个网格上做


def read(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def guid_of(asset_path):
    m = re.search(r"guid:\s*([0-9a-f]{32})", read(asset_path + ".meta")[:400])
    return m.group(1) if m else None


_GUID_INDEX = None


def guid_index():
    """guid -> 资产路径（只索引 rawLo 下的 .controller / .anim，够用且快）。"""
    global _GUID_INDEX
    if _GUID_INDEX is not None:
        return _GUID_INDEX
    idx = {}
    for dirpath, _d, files in os.walk(os.path.join(ASSETS, "rawLo")):
        base = os.path.basename(dirpath)
        if base not in ("AnimationClip", "AnimatorController"):
            continue
        for fn in files:
            if not (fn.endswith(".anim.meta") or fn.endswith(".controller.meta")):
                continue
            p = os.path.join(dirpath, fn[:-5])
            g = guid_of(p)
            if g:
                idx[g] = p
    _GUID_INDEX = idx
    return idx


def controller_guid_of_prefab(prefab):
    m = re.search(r"m_Controller:\s*\{fileID:\s*-?\d+,\s*guid:\s*([0-9a-f]{32})", read(prefab))
    return m.group(1) if m else None


def parse_states(ctrl_path):
    out = {}
    for blk in re.split(r"\n--- !u!", read(ctrl_path)):
        if not blk.startswith("1102 &"):
            continue
        mn = re.search(r"m_Name:\s*(.*)", blk)
        mm = re.search(r"m_Motion:\s*\{fileID:\s*-?\d+,\s*guid:\s*([0-9a-f]{32})", blk)
        if mn:
            out[mn.group(1).strip()] = mm.group(1) if mm else None
    return out


def states_by_animator(prefab):
    """{Animator 所在物体名: {state: clip guid}}。

    daphne 有 3 个 Animator、4 条 FX 动画、共用 2 份 clip。校验器原来只会从
    主控制器的状态表里找 clip，于是拿右翼的动画去要求左翼的部件也有时间轴，
    报出一堆假阳性。这里按"动画属于哪个 Animator"取对应的控制器。
    """
    txt = read(prefab)
    goname = {}
    for blk in re.split(r"\n--- !u!", txt):
        if not blk.startswith("1 &"):
            continue
        fid = blk.split(" &")[1].split("\n")[0].strip()
        m = re.search(r"\n\s*m_Name:\s*(.*)", blk)
        if m:
            goname[fid] = m.group(1).strip()
    out = {}
    for blk in re.split(r"\n--- !u!", txt):
        if not blk.startswith("95 &"):
            continue
        mg = re.search(r"m_GameObject:\s*\{fileID:\s*(\d+)\}", blk)
        mc = re.search(r"m_Controller:\s*\{fileID:\s*-?\d+,\s*guid:\s*([0-9a-f]{32})", blk)
        if not mg or not mc:
            continue
        nm = goname.get(mg.group(1))
        ctrl = guid_index().get(mc.group(1))
        if nm and ctrl:
            out[nm] = parse_states(ctrl)
    return out


def read_path_field(block):
    """读曲线块的 path 字段，并把 Unity 的折行续写拼回去。

    超长路径会被 Unity 序列化成：
        path: bone_pelvis_01/.../parts_glow_body_star_1
          (6)
    只取第一行会把 `parts_xxx` 和 `parts_xxx (1)` 折叠成同一个节点 ——
    转换器早就处理了这个（见 unity_anim2d._read_path_field），校验器必须一致。
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
            ni = len(nxt) - len(nxt.lstrip())
            if ni <= indent:
                break
            pieces.append(nxt.strip())
            j += 1
        # 折行处原本是**一个空格**（YAML 折行语义）：`parts_Eye_normal` + `\n      (2)`
        # 还原成 `parts_Eye_normal (2)`。用 "" join 会变成 `parts_Eye_normal(2)`，
        # 和节点真实路径差一个空格 → 那条曲线整条匹配不上（转换器用的是 " ".join）。
        return " ".join(p for p in pieces if p).strip()
    return None


def parse_clip_isactive(clip_path):
    """返回 {相对路径: (keys, tans)}；keys=[(t, value)]，tans=[(inSlope, outSlope)]。

    同一个路径出现多条曲线时**后者覆盖前者**（和转换器、Unity 求值顺序一致）。
    切线必须一起读：`Infinity` 表示常值段（阶跃），0 表示平滑插值 —— 运行时
    对这两者的求值结果完全不同（见模块 docstring）。

    **`m_Enabled` 也要读**（键名加 `#enabled` 后缀）：Unity 里
    `Renderer.enabled` 和 `GameObject.SetActive` 是**两个独立开关**，部件可见
    必须两个都为真。只读 `m_IsActive` 会漏掉"m_IsActive 还开着、但 m_Enabled
    已经关了"的窗口 —— `bheur_skin1` 的 `Part_Eye_Close_R` 正是这样：
    `m_IsActive` 到 0.45 才关，但 `m_Enabled` **0.13333 就关了**，所以真实
    可见窗是 [0, 0.13333]（转换器的做法是对的，早先校验器只读 m_IsActive
    所以假报"不一致"）。
    """
    out = {}
    for blk in re.split(r"\n  - serializedVersion:", read(clip_path)):
        if "attribute: m_IsActive" in blk:
            suffix = ""
        elif "attribute: m_Enabled" in blk:
            suffix = "#enabled"
        else:
            continue
        path = read_path_field(blk)
        if not path:
            continue
        ks, ts = [], []
        # 关键帧的缩进是固定的（`      - serializedVersion: 3` + 8 空格的
        # `time:` / `value:`）：用宽松的 `\s*` 会把**下一个 entry** 的关键帧
        # 一起吞进来，读出一条根本不存在的"合成曲线"（bheur 的
        # `Part_Eye_Close_R` 就是这么被误读成 0→0.05→0.45 的）。
        for kf in re.split(r"^      - serializedVersion: [23]\s*$", blk,
                           flags=re.M)[1:]:
            mt = re.search(r"^        time: ([-\d.eE]+)\s*$", kf, re.M)
            mv = re.search(r"^        value: ([-\d.eE]+)\s*$", kf, re.M)
            if not (mt and mv):
                continue
            ks.append((float(mt.group(1)), float(mv.group(1))))
            ts.append((_slope(kf, "inSlope"), _slope(kf, "outSlope")))
        if ks:
            out[path + suffix] = (ks, ts)
    return out


def hash_path_table(full_paths):
    """{CRC32(路径): 路径}，用 partsMeta 的全路径**及其所有尾巴**建立。

    游戏里打包过的 clip 会把路径写成 `path_0x…`（= CRC32，见主文档 3.36）。
    这里不做模型解析，只用现成的全路径加尾巴去撞——曲线 path 是相对 Animator
    宿主的，所以它一定是某条全路径的一个尾巴。
    """
    import binascii
    tab = {}
    for fp in full_paths:
        segs = fp.split("/")
        for i in range(len(segs)):
            cand = "/".join(segs[i:])
            tab.setdefault(binascii.crc32(cand.encode("utf-8")) & 0xFFFFFFFF,
                           cand)
    return tab


def resolve_hashed(curves, table):
    """把 `path_0x…` 键换成真实路径（转换器同口径）。"""
    if not table:
        return curves
    for k in [k for k in curves if k.startswith("path_0x")]:
        m = re.match(r"path_0x([0-9A-Fa-f]+)", k)
        real = table.get(int(m.group(1), 16)) if m else None
        if real:
            curves[real] = curves.pop(k)
    return curves


def _slope(block, field):
    m = re.search(r"^\s*" + field + r":\s*(\S+)\s*$", block, re.M)
    if not m:
        return 0.0
    raw = m.group(1)
    if "Infinity" in raw or raw.lower().startswith(("inf", "-inf")):
        return float("inf")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def clip_vis(keys, tans, t):
    """clip 侧在 t 时刻的可见性 —— **跟转换器同口径**。

    转换器默认按"关键帧（阶跃 + v>=0.5）"求显隐（见 `static_prefab_spine.py`
    顶部 `USE_RUNTIME_ACTIVE` 的说明：插值口径会让互补的表情件在切换点前后
    同时可见）。这里如果写死运行时判据，就会把"口径不同"误报成产物 bug ——
    2026-09-16 夜实测：写死时 16 个角色报 261 个 slot，改成一回事之后 0 个。
    """
    if USE_RUNTIME_ACTIVE:
        return active_is_on(unity_curve_eval(
            keys, tans or [(0.0, 0.0)] * len(keys), t))
    v = keys[0][1]
    for kt, kv in keys:
        if kt <= t + 1e-9:
            v = kv
        else:
            break
    return v >= 0.5


def norm_clip(seq, is_clip=True):
    """归一成"值发生跳变"的序列，干掉连续同值的冗余关键帧。"""
    out = []
    for t, v in seq:
        v = (v >= 0.5) if is_clip else bool(v)
        if out and out[-1][1] == v:
            continue
        out.append((t, v))
    return out


def keys_match(ours, clip):
    """在**采样网格**上比可见性，而不是比关键帧列表。

    为什么不能比关键帧列表：阶跃曲线的首关键帧时刻无意义（3.0 秒前也是保持首值）、
    转换器会合掉连续同值的冗余帧、关键帧还会被吸附到采样网格 —— 这些都会造成
    假阳性。真正决定观众看到什么的是"每个采样时刻可见还是不可见"。

    """
    o = norm_clip(ours, is_clip=False)
    c = norm_clip(clip, is_clip=False)
    tmax = max([t for t, _ in o] + [t for t, _ in c])
    bad = []
    # clip 侧的翻转时刻不在 0.05 网格上（插值曲线离开 0 的时刻是算出来的），
    # 所以网格点上挨着翻转点的 1 帧差异按容差放过，只报真正错位的变化。
    edges = [t for t, _ in o] + [t for t, _ in c]
    i = 0
    while i * GRID <= tmax + 1e-6:
        t = i * GRID
        if vis_at(o, t) != vis_at(c, t):
            if not any(abs(t - e) <= TOL for e in edges):
                bad.append(t)
        i += 1
    if not bad:
        return True, ""
    return False, "在 %d 个采样点不一致（首个 %.3f） 我们 %s | clip %s" % (
        len(bad), bad[0], fmt_keys(o), fmt_keys(c))


def vis_at(keys, t):
    v = keys[0][1]
    for kt, kv in keys:
        if kt <= t + 1e-9:
            v = kv
        else:
            break
    return v


def ancestor_curve_keys(curves, rel_path):
    """找出 rel_path 的**祖先**节点的曲线 key（和转换器同一套规则）。

    `rel_path` = 部件**相对该 Animator** 的路径（`partsMeta.path` 去掉
    `<角色>/<Animator 路径>/` 前缀）。转换器的 `node_visible()` 是沿模型父链
    逐层**精确比较** `anim_path`，所以这里也只认"按 `/` 分段的前缀"：

        rel = a/b/c  →  候选祖先 = a, a/b

    旧实现用"`/k/` 是否出现在完整路径里"的子串匹配，会把**不该命中**的曲线
    也算成祖先（daphne 右翼那 57 个 slot 就是这么假报的）。
    """
    out = []
    parts = [p for p in (rel_path or "").split("/") if p]
    for i in range(1, len(parts)):
        anc = "/".join(parts[:i])
        if anc in curves:
            out.append(anc)
    return out


def effective_clip_curve(curves, rel_path, own_key):
    """把"自己的曲线"和"祖先的曲线"合成一条有效显隐曲线（二进制跳变序列）。

    转换器是按 Unity 的父链语义推的：祖先被 SetActive=0，后代一样不可见。
    校验器原来只看节点自己的曲线，于是把"祖先切换导致的变化"误判成差异
    （daphne 的翅膀、bheur 的闭眼组都是这一类）。这里先在 clip 侧合出来，
    再和产物比。
    """
    keysets = [curves[own_key]] if own_key in curves else []
    # 自己的 `m_Enabled`（Renderer.enabled）和 `m_IsActive` 是两个开关，都要满足
    _ek = own_key + "#enabled"
    if _ek in curves:
        keysets.append(curves[_ek])
    for k in ancestor_curve_keys(curves, rel_path):
        if k != own_key:
            keysets.append(curves[k])
    if not keysets:
        return None
    # 采样时刻 = 各条曲线的关键帧时刻 ∪ 翻转时刻（插值曲线的可见窗从"离开 0"
    # 那一刻开始，不在关键帧上）
    times = set()
    for ks, ts in keysets:
        times.update(t for t, _ in ks)
        times.update(active_flip_times(ks, ts))
    out = []
    for t in sorted(times):
        v = all(clip_vis(ks, ts, t) for ks, ts in keysets)
        out.append((t, 1.0 if v else 0.0))
    return out


def fmt_keys(keys, n=8):
    return ",".join("%.2f:%d" % (t, v) for t, v in keys[:n])


def check_char(char, verbose=False, root=None):
    sdir = char if os.path.isdir(char) else os.path.join(root or PROBE50, char)
    if not os.path.isdir(sdir):
        return None
    info = json.load(io.open(os.path.join(sdir, "_static_info.json"), encoding="utf-8-sig"))
    sjs = [f for f in os.listdir(sdir)
           if f.endswith(".json") and not f.startswith(("_", "."))]
    if not sjs:
        return None
    data = json.load(io.open(os.path.join(sdir, sjs[0]), encoding="utf-8-sig"))
    anims = data.get("animations") or {}
    meta = info.get("partsMeta") or []
    full_paths = [p["path"] for p in meta]
    htab = hash_path_table(full_paths)
    # 注意：**同一个 path 可能对应两个 slot**（daphne 的翅膀部件被列了两次：
    # 266 个部件只有 152 个唯一路径）。用 path->name 的字典会把其中一个名字吃掉，
    # 于是"名字 -> 路径"反查失败、这些 slot 被判成"clip 里没有曲线"（57 个假阳性）。
    path2slots = {}
    slot2path = {}
    unbound = set()          # 同名孪生里**没被 Unity 绑上曲线**的部件（2026-09-18）
    for _p in meta:
        path2slots.setdefault(_p["path"], []).append(_p["name"])
        slot2path[_p["name"]] = _p["path"]
        if _p.get("bound") is False:
            unbound.add(_p["name"])
    path2slot = {k: v[-1] for k, v in path2slots.items()}

    cg = controller_guid_of_prefab(info["prefab"])
    ctrl = guid_index().get(cg)
    states = parse_states(ctrl) if ctrl else {}
    by_anim = states_by_animator(info["prefab"]) if info.get("prefab") else {}
    name2anim = {a.get("name"): (a.get("animator") or "")
                 for a in (info.get("animations") or [])}

    rows = []
    for name, anim in anims.items():
        st = anim.get("state") or name
        sttab = by_anim.get(anim.get("animator") or "") or states
        clip_path = guid_index().get(sttab.get(st) or "")
        if not clip_path:
            rows.append((name, "找不到 clip（state=%s）" % st, 0, []))
            continue
        curves = resolve_hashed(parse_clip_isactive(clip_path), htab)
        # 多层合并：转换器会把"其它层默认状态 clip"的离散属性（m_IsActive）
        # 覆盖进来（见 `compose_layers`）。校验器必须照做，否则第二层的动画
        # （bheur Drone / blackwyrm Lobby_BG / circe Drone）会因为
        # "clip 里没有这条曲线"而假报。
        try:
            _layers = parse_animator_layers(ctrl) if ctrl else []
        except Exception:                             # noqa: BLE001
            _layers = []
        if _layers:
            _s2l = {}
            for _li, _L in enumerate(_layers):
                for _nm, _g in (_L.get("states") or []):
                    _s2l.setdefault(_nm, _li)
            _mine = _s2l.get(st)
            if _mine is not None:
                for _li, _L in enumerate(_layers):
                    if _li == _mine or not _L.get("defaultClipGuid"):
                        continue
                    _op = guid_index().get(_L["defaultClipGuid"])
                    if not _op or not os.path.isfile(_op):
                        continue
                    for _p2, _kv in resolve_hashed(
                            parse_clip_isactive(_op), htab).items():
                        curves[_p2] = _kv          # 离散属性按 Override 处理
        # **运行时"曲线没绑上"的例外**：转换器有一张 `ACTIVE_DEAD_BY_ROLE`
        # （例如 `bheur_skin1` 的 `Bone_Close_Eye`：那条 m_IsActive 在运行时
        # 根本没绑上，所以转换器故意不采纳）。校验器必须共用同一张口径，
        # 否则会拿"原始 clip"去比，必然假报不一致（2026-09-17 实测）。
        _dead = set(ACTIVE_DEAD_BY_ROLE.get(os.path.basename(sdir.rstrip("\\/")), ()))
        _dead_hit = [p for p in list(curves) if p in _dead]
        for _p3 in _dead_hit:
            curves.pop(_p3, None)
        if _dead_hit:
            print("   [例外] %s：按运行时例外表忽略 %d 条曲线（%s）"
                  % (os.path.basename(sdir.rstrip("\\/")), len(_dead_hit),
                     ",".join(os.path.basename(p) for p in _dead_hit)))
        # clip 相对路径 -> partsMeta 完整路径（**全部命中**，不是第一个）
        # 多 Animator 共用一份 clip（daphne 的左右翼）、且两侧有同名部件
        # （`bone_wing_fx (9)/parts_wing_fx1` 与 `(21)/…`）时，只取第一个命中
        # 会把曲线算到另一侧头上，于是本侧被判成"clip 里没有曲线"（假阳性）。
        rel2slots = {}
        for rp in curves:
            # `#enabled` 只是"同一条 m_Enabled 曲线"的标记，映射槽位时要去掉
            _base = rp.split("#", 1)[0]
            suf = "/" + _base
            hit = [nm for fp in full_paths if fp.endswith(suf) or fp == _base
                   for nm in path2slots.get(fp, [])]
            if hit:
                rel2slots[rp] = hit
        rel2slot = {rp: hs[0] for rp, hs in rel2slots.items()}
        all_slots_with_curve = {s for hs in rel2slots.values() for s in hs}
        slots = anim.get("slots") or {}
        bad = []
        # 方向 1：双方都有的，比关键帧
        # （slot2path 在函数开头按 partsMeta 全量构建，**不要**在这里用
        #  path2slot 反推：同一个 path 有两个 slot 时会丢掉一个名字）
        for rp, hs in rel2slots.items():
            # 同一份 clip 会被多个 Animator 引用（daphne 左右翅膀共用一个 .anim），
            # 每条动画只驱动它自己 Animator 子树里的部件 —— 不是这棵子树的不比。
            _an = anim.get("animator") or name2anim.get(name) or ""
            _an = _an.split("/")[-1]
            if _an:
                # **必须先把整组槽位过滤掉**：同名叶子（daphne 的 `parts_wing_fx1`）
                # 会同时命中左右两翼，只判断 hs[0] 的话，另一翼那些"在本动画里
                # 本来就没时间轴"的槽位会被算进来，于是假报
                # "我们完全没有时间轴（一直显示）"（旧实现实测 9 个 slot）。
                hs = [s for s in hs
                      if ("/" + _an + "/") in slot2path.get(s, "")]
            if not hs:
                continue
            # **同名孪生节点（2026-09-18）**：同一条路径命中多个槽位时，Unity 只把曲线
            # 绑给**第一个**节点，其余同名节点保持 prefab 姿态 ⇒ 它们的槽位**不该**有
            # 时间轴（转换器的 `dedupe_anim_paths` 就是这么做的）。
            # 所以：只要这组里**有**槽位带时间轴，就只比这些（= 被绑上的那些）；
            # 一个都没有时才按"真·漏了"处理（保持原来的告警）。
            _with_tl = [s for s in hs
                        if (slots.get(s) or {}).get("attachment")]
            if _with_tl:
                hs = _with_tl
            # 转换器标了 `bound:false` 的部件（同名孪生里没被 Unity 绑的那个）
            # **不该**跟 clip 的显隐曲线一致 —— 它在 Unity 里保持 prefab 姿态。
            _bound_ok = [s for s in hs if s not in unbound]
            if _bound_ok:
                hs = _bound_ok
            else:
                continue
            slot = hs[0]
            # **多 drawable**：同一个部件的相对层级会变时会占多个槽位
            # （`<原名>` / `<原名>#<层级>`），每个槽位各自有一条 attachment
            # 时间轴（只有"当前该亮那一层"的那条挂附件）。对"部件可见性"来说
            # 正确的合成是 **任意一个槽位可见 = 部件可见**；只取第一个槽位
            # 会在层级切换时假报"少显示了一段"。
            if any(not (slots.get(s) or {}).get("attachment") for s in hs):
                ours = []                    # 有一个槽位没有时间轴 ⇒ 一直显示
            else:
                tl_list = [[(float(k["time"]), k.get("name") is not None)
                            for k in (slots.get(s) or {}).get("attachment")]
                           for s in hs]
                ours = [(t, any(vis_at(tl, t) for tl in tl_list))
                        for t in sorted({t for tl in tl_list for t, _ in tl})]
            # 部件相对该 Animator 的路径：<角色>/<Animator 路径>/ 之后的部分
            # 注意用 **rsplit**：Animator 的名字在路径里可能出现多次
            # （daphne 右翼是 .../bone_R_wing/bone_R_wing_fx/bone_R_wing/...），
            # 取第一次会把前缀链切错，祖先曲线就认不出来了。
            fp = slot2path.get(slot, "")
            rel = (fp.rsplit("/" + _an + "/", 1)[1]
                   if (_an and ("/" + _an + "/") in fp) else fp)
            clip = effective_clip_curve(curves, rel, rp)
            cn = norm_clip(clip, is_clip=False)
            if not ours:
                # clip 只有"恒为 1"这一种情况时，等于一直显示，我们不出时间轴是对的
                if len(cn) == 1 and cn[0][1]:
                    continue
                bad.append((slot, "clip 的显隐是 %s，我们完全没有时间轴（一直显示）"
                            % ",".join("%.2f:%d" % (t, v) for t, v in cn[:6])))
                continue
            ok, why = keys_match(ours, clip)
            if not ok:
                bad.append((slot, why))
        # 方向 2：我们有时间轴但 clip 没有对应曲线
        for slot, s in slots.items():
            keys2 = s.get("attachment") or []
            if not keys2:
                continue
            if slot in all_slots_with_curve:
                continue
            nx = []
            for rp, sl in rel2slot.items():
                if sl == slot:
                    nx.append(rp)
            if nx:
                continue
            # 祖先被动画切换（父链上有一条 m_IsActive 曲线）也会让这个部件时隐时现，
            # 那是正常的、由 node_visible 沿父链推出来的，不算"无曲线"。
            fp2 = None
            fp2 = slot2path.get(slot)
            # 和转换器同一套：只认"按 / 分段的前缀"精确匹配（旧实现用子串，
            # daphne 右翼那 57 个 slot 就是这么假报的）
            _an2 = anim.get("animator") or name2anim.get(name) or ""
            _an2 = _an2.split("/")[-1]
            _rel2 = (fp2.rsplit("/" + _an2 + "/", 1)[1]
                     if (fp2 and _an2 and ("/" + _an2 + "/") in fp2) else (fp2 or ""))
            if ancestor_curve_keys(curves, _rel2):
                continue        # 祖先被动画切换，属正常
            # 常量时间轴（物体在场景里就是关的、clip 也没碰它）是正常的，不算问题
            vals = set(bool(k.get("name") is not None) for k in keys2)
            if len(keys2) == 1 or len(vals) == 1:
                continue
            bad.append((slot, "我们有 %d 帧的显隐变化，但 clip 里没有相关的 m_IsActive 曲线"
                        % len(keys2)))
        rows.append((name, None, len(bad), bad))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chars", nargs="*")
    ap.add_argument("--all-in-probe50", action="store_true")
    ap.add_argument("--all", action="store_true", help="同 --all-in-probe50")
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--spine-root", default=PROBE50,
                    help="产物根目录（默认 _probe50）；chars 也可直接给绝对路径")
    a = ap.parse_args()

    chars = list(a.chars)
    if a.all_in_probe50 or a.all:
        chars = sorted(d for d in os.listdir(PROBE50)
                       if os.path.isdir(os.path.join(PROBE50, d)))
    if not chars:
        raise SystemExit("用法: python tools/check_clip_visibility.py <角色> | --all-in-probe50")

    tot_bad = 0
    bad_chars = []
    for c in chars:
        rows = check_char(c, root=a.spine_root)
        if rows is None:
            print("%-24s (跳过：没有产物)" % c)
            continue
        nbad = sum(r[2] for r in rows if r[1] is None and r[2])
        tot_bad += nbad
        if nbad:
            bad_chars.append((c, nbad))
            print("\n== %s ==  异常 slot %d 个" % (c, nbad))
            for name, err, n, bad in rows:
                if err:
                    print("   [%-22s] %s" % (name, err))
                    continue
                if not n:
                    print("   [%-22s] ✓" % name)
                    continue
                print("   [%-22s] %d 个 slot 有问题" % (name, n))
                for slot, why in bad[:a.top]:
                    print("        %-36s %s" % (slot[:36], why))
        else:
            print("%-24s ✓ 全部动画与 clip 关键帧一致（%d 条）" % (c, len(rows)))

    print()
    print("=" * 60)
    print("总计：%d 个角色，%d 个 slot 有问题" % (len(chars), tot_bad))
    if bad_chars:
        print("有问题的角色：")
        for c, n in sorted(bad_chars, key=lambda x: -x[1]):
            print("   %-24s %d" % (c, n))


if __name__ == "__main__":
    main()
