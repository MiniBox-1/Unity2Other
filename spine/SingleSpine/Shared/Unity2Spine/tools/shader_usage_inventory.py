# -*- coding: utf-8 -*-
r"""清点 **157 个角色 prefab 实际引用的 shader**（内建 fileID + 自定义 guid），
并按 shader 源码里的 `Blend` 指令归类成 normal / additive / multiply / screen。

用法:
    python tools\shader_usage_inventory.py                  # 全量
    python tools\shader_usage_inventory.py --char 2DModel_BR_Echidna_NS1
"""
import argparse
import collections
import io
import os
import re

ASSETS = r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets"

# Unity 内建 shader fileID → (名字, blend)。名字是**用 Unity 引擎实测**的
# （`_scratch\_csbake\probe_shader_names.cs`：加载材质问 `mat.shader.name`）。
BUILTIN = {
    200: ("Legacy Shaders/Particles/Additive", "additive"),
    201: ("Legacy Shaders/Particles/Alpha Blended", "normal"),
    202: ("Legacy Shaders/Particles/Additive (Soft)", "additive"),
    203: ("Legacy Shaders/Particles/Alpha Blended", "normal"),
    205: ("Legacy Shaders/Particles/Multiply", "multiply"),
    206: ("Legacy Shaders/Particles/Multiply (Double)", "multiply"),
    46: ("Standard", "normal"),
    103: ("Legacy Shaders/Transparent/Diffuse", "normal"),
    104: ("Legacy Shaders/Transparent/VertexLit", "normal"),
    10720: ("Mobile/Particles/Additive", "additive"),
    10750: ("Sprites/Diffuse", "normal"),
    10751: ("Sprites/Mask", "normal"),
    10753: ("Sprites/Default", "normal"),
    10754: ("Sprites-Default(材质)", "normal"),
}
NAME_RE = re.compile(r'Shader\s+"([^"]+)"')
BLEND_RE = re.compile(r"^\s*Blend\s+(.+?)\s*$", re.M)


def classify_blend(src, dst):
    src, dst = src.strip(), dst.strip()
    if dst == "OneMinusSrcColor":
        return "screen"
    if dst.startswith("DstColor"):
        return "multiply"
    if src in ("SrcAlpha", "SrcAlphaSaturate") and dst == "One":
        return "additive"
    if src == "One" and dst == "One":
        return "additive"
    return "normal"                     # 含 (One, OneMinusSrcAlpha) 的预乘普通混合


def build_index(assets):
    """guid -> 资产路径（走 .meta，一次遍历）。"""
    idx = {}
    for dp, _dn, fns in os.walk(assets):
        for fn in fns:
            if not fn.endswith(".meta"):
                continue
            try:
                t = io.open(os.path.join(dp, fn), encoding="utf-8",
                            errors="replace").read(300)
            except OSError:
                continue
            m = re.search(r"^guid:\s*([0-9a-f]{32})", t, re.M)
            if m:
                idx[m.group(1)] = os.path.join(dp, fn[:-5])
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=ASSETS)
    ap.add_argument("--prefabs", default=None)
    ap.add_argument("--char", default=None)
    ap.add_argument("--max-examples", type=int, default=4)
    ap.add_argument("--out-txt", default=None,
                    help="把「用到非普通混合的角色」写成一行一个名字的清单"
                         "（喂给 tools\\batch_cs_convert.py --exact-file）")
    a = ap.parse_args()
    assets = a.assets
    pdir = a.prefabs or os.path.join(assets, "Prefabs")
    idx = build_index(assets)
    shader_cache = {}
    mat_cache = {}

    def shader_of(mat_guid):
        if mat_guid in mat_cache:
            return mat_cache[mat_guid]
        out = None
        mp = idx.get(mat_guid)
        if mp and mp.endswith(".mat"):
            try:
                t = io.open(mp, encoding="utf-8", errors="replace").read()
            except OSError:
                t = ""
            m = re.search(
                r"m_Shader:\s*\{fileID:\s*(\d+),\s*guid:\s*([0-9a-f]+)", t)
            if m:
                fid, sg = int(m.group(1)), m.group(2)
                key = (fid, sg)
                if key in shader_cache:
                    name, blend = shader_cache[key]
                elif sg.startswith("0000000000000000"):
                    name, blend = BUILTIN.get(
                        fid, ("内建 fileID %d（未登记）" % fid, "normal"))
                else:
                    sp = idx.get(sg)
                    name, blend = "自定义 guid %s（源码缺失）" % sg, "normal"
                    if sp and sp.endswith(".shader"):
                        st = io.open(sp, encoding="utf-8",
                                     errors="replace").read()
                        nm = NAME_RE.search(st)
                        name = nm.group(1) if nm else os.path.basename(sp)
                        bl = BLEND_RE.findall(st)
                        low = name.lower()
                        if bl:
                            parts = re.split(r"[,\s]+", bl[0].strip())
                            blend = (classify_blend(parts[0], parts[1])
                                     if len(parts) >= 2 else "normal")
                        elif "multiply" in low:
                            blend = "multiply"
                        elif "screen" in low:
                            blend = "screen"
                        elif "additive" in low:
                            blend = "additive"
                shader_cache[key] = (name, blend)
                out = (name, blend, os.path.basename(mp))
        mat_cache[mat_guid] = out
        return out

    usage = collections.defaultdict(lambda: {"mats": set(), "chars": set()})
    per_char = {}
    prefabs = [f for f in sorted(os.listdir(pdir)) if f.endswith(".uAnim.prefab")]
    if a.char:
        prefabs = [f for f in prefabs if f.startswith(a.char)]
    for fn in prefabs:
        raw = io.open(os.path.join(pdir, fn), encoding="utf-8",
                      errors="replace").read()
        guids = set(re.findall(r"guid: ([0-9a-f]{32})", raw))
        char = fn.replace(".uAnim.prefab", "")
        per_char[char] = []
        for g in sorted(guids):
            info = shader_of(g)
            if not info:
                continue
            name, blend, matname = info
            usage[(name, blend)]["mats"].add(matname)
            usage[(name, blend)]["chars"].add(char)
            per_char[char].append((name, blend, matname))

    print("prefab 数 = %d" % len(prefabs))
    print("")
    print("shader → blend 归类 → 引用角色数：")
    for (name, blend), v in sorted(usage.items(),
                                   key=lambda kv: -len(kv[1]["chars"])):
        flag = "" if blend == "normal" else "   ← 特殊混合"
        ex = "、".join(sorted(v["chars"])[:a.max_examples])
        print("  %-50s %-9s 角色 %3d 材质 %3d  例: %s%s"
              % (name, blend, len(v["chars"]), len(v["mats"]), ex, flag))
    print("")
    odd = {c: it for c, it in per_char.items()
           if any(b != "normal" for _n, b, _m in it)}
    print("用到「非普通混合」的角色：%d 个" % len(odd))
    for c in sorted(odd):
        kinds = collections.Counter(b for _n, b, _m in odd[c])
        mats = sorted(set(m for _n, _b, m in odd[c]))[:3]
        print("  %-42s %-34s 例:%s" % (c, dict(kinds), "、".join(mats)))
    if a.out_txt:
        with io.open(a.out_txt, "w", encoding="utf-8") as fh:
            fh.write("\n".join(sorted(odd)) + "\n")
        print("\n清单已写出：%s（%d 个）" % (a.out_txt, len(odd)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
