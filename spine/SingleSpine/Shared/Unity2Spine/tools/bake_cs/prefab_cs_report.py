# -*- coding: utf-8 -*-
r"""列出某个 uAnim prefab 里"运行态脚本"挂了什么、影响哪些骨骼/渲染器。

用法:
    python prefab_cs_report.py <prefab> [--assets <Assets 目录>] [--out report.json]

为什么需要它:
    static_prefab_spine 只读磁盘资源, 运行态由 CS 脚本产生的形变(主要是
    DynamicBone 的逐帧弹簧)不在产物里。要做"烘焙", 先得知道:
      * 这个 prefab 上有哪些 MonoBehaviour, 分别是什么脚本;
      * DynamicBone 的 m_Root 落在哪根骨头, 它管辖哪些 Transform;
      * 哪些 SkinnedMeshRenderer 的 bones 里含这些 Transform(= 视觉会变的部件)。

本脚本是纯离线解析(不需要 Unity)。
"""

import argparse
import io
import json
import os
import re
import sys

DOC_RE = re.compile(r"^--- !u!(\d+) &(\d+)(?: stripped)?\s*$")
GUID_RE = re.compile(r"guid:\s*([0-9a-fA-F]{32})")


def split_docs(text):
    """把多文档 YAML 切成 [(classid, fileid, [lines])]。"""
    docs = []
    cur = None
    for line in text.splitlines():
        m = DOC_RE.match(line)
        if m:
            if cur:
                docs.append(cur)
            cur = [int(m.group(1)), m.group(2), []]
            continue
        if cur is not None:
            cur[2].append(line)
    if cur:
        docs.append(cur)
    return docs


def field(lines, key, indent=2):
    """取形如 '  key: value' 的标量字段。"""
    pat = re.compile(r"^\s{%d}%s:\s*(.*)$" % (indent, re.escape(key)))
    for ln in lines:
        m = pat.match(ln)
        if m:
            return m.group(1).strip()
    return None


def refs(lines, key, indent=2):
    """取 key 下的 '{fileID: N}' 列表(YAML 的换行写法)。"""
    pat = re.compile(r"^\s{%d}%s:\s*$" % (indent, re.escape(key)))
    out = []
    started = False
    for ln in lines:
        if not started:
            if pat.match(ln):
                started = True
            continue
        s = ln.strip()
        if not s.startswith("- "):
            break
        m = re.search(r"\{fileID:\s*(-?\d+)\}", s)
        if m and m.group(1) != "0":
            out.append(m.group(1))
    return out


def inline_ref_list(lines, key, indent=2):
    """取单行写法 '  key: [{fileID: 1}, {fileID: 2}]' 或 '  key: []'。"""
    v = field(lines, key, indent)
    if v is None or "[]" in v:
        return []
    return [m for m in re.findall(r"\{fileID:\s*(-?\d+)\}", v) if m != "0"]


def script_index(assets):
    """.cs.meta -> {guid: 相对路径}。"""
    idx = {}
    for dirpath, _d, files in os.walk(assets):
        for fn in files:
            if not fn.endswith(".cs.meta"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                head = io.open(p, encoding="utf-8", errors="replace").read(400)
            except OSError:
                continue
            m = GUID_RE.search(head)
            if m:
                idx[m.group(1).lower()] = os.path.relpath(
                    p[:-5], assets).replace("\\", "/")
    return idx


def parse(prefab, assets):
    text = io.open(prefab, encoding="utf-8", errors="replace").read()
    docs = split_docs(text)
    sidx = script_index(assets) if assets else {}

    objs = {}
    by_class = {}
    for cid, fid, lines in docs:
        by_class.setdefault(cid, []).append(fid)
        objs[fid] = {"class": cid, "lines": lines}

    for fid in by_class.get(1, []):
        o = objs[fid]
        o["name"] = (field(o["lines"], "m_Name") or "").strip()
        o["components"] = inline_ref_list(o["lines"], "m_Component")
        o["active"] = field(o["lines"], "m_IsActive")

    for fid in by_class.get(4, []):
        o = objs[fid]
        o["go"] = re.sub(r"\D", "", field(o["lines"], "m_GameObject") or "") or None
        o["father"] = re.sub(r"\D", "",
                             field(o["lines"], "m_Father") or "") or None

    for fid in by_class.get(1, []):
        objs[fid]["tf"] = None
    for fid in by_class.get(4, []):
        go = objs[fid].get("go")
        if go in objs:
            objs[go]["tf"] = fid

    path_cache = {}

    def tf_path(tfid):
        if not tfid:
            return ""
        if tfid in path_cache:
            return path_cache[tfid]
        parts = []
        cur = tfid
        guard = 0
        while cur and cur in objs and guard < 512:
            go = objs[cur].get("go")
            nm = objs.get(go, {}).get("name", "?") if go else "?"
            parts.append(nm)
            cur = objs[cur].get("father")
            guard += 1
        out = "/".join(reversed(parts))
        path_cache[tfid] = out
        return out

    children = {}
    for fid in by_class.get(4, []):
        children.setdefault(objs[fid].get("father"), []).append(fid)

    def subtree(tfid):
        out = []
        stack = [tfid]
        while stack:
            cur = stack.pop()
            out.append(cur)
            stack.extend(children.get(cur, []))
        return out

    monos = []
    for fid in by_class.get(114, []):
        o = objs[fid]
        body = "\n".join(o["lines"])
        m = re.search(r"m_Script:\s*\{fileID:\s*\d+,\s*guid:\s*([0-9a-fA-F]{32})",
                      body)
        guid = m.group(1).lower() if m else None
        go = re.sub(r"\D", "", field(o["lines"], "m_GameObject") or "")
        monos.append({
            "fileID": fid,
            "script": sidx.get(guid, "«未知 guid %s»" % guid),
            "guid": guid,
            "go": objs.get(go, {}).get("name", "?"),
            "go_path": tf_path(objs.get(go, {}).get("tf")),
            "enabled": field(o["lines"], "m_Enabled"),
            "lines": o["lines"],
        })

    dyn = []
    for mo in monos:
        if not mo["script"].endswith("DynamicBone.cs"):
            continue
        root = re.sub(r"\D", "", field(mo["lines"], "m_Root") or "")
        bones = inline_ref_list(mo["lines"], "m_Bones") + refs(mo["lines"], "m_Bones")
        dyn.append({
            "fileID": mo["fileID"],
            "on": mo["go"],
            "on_path": mo["go_path"],
            "script": mo["script"],
            "root_tf": root or None,
            "root_path": tf_path(root),
            "bones_explicit": [tf_path(b) for b in bones],
            "params": {
                "weight": field(mo["lines"], "m_Weight"),
                "damping": field(mo["lines"], "m_Damping"),
                "elasticity": field(mo["lines"], "m_Elasticity"),
                "stiffness": field(mo["lines"], "m_Stiffness"),
                "inert": field(mo["lines"], "m_Inert"),
                "gravity": field(mo["lines"], "m_Gravity"),
                "force": field(mo["lines"], "m_Force"),
                "updateRate": field(mo["lines"], "m_UpdateRate"),
                "updateMode": field(mo["lines"], "m_UpdateMode"),
                "endLength": field(mo["lines"], "m_EndLength"),
                "endOffset": field(mo["lines"], "m_EndOffset"),
                "freezeAxis": field(mo["lines"], "m_FreezeAxis"),
                "isTransFormCalculate": field(mo["lines"], "IsTransFormCalculate"),
                "colliders": inline_ref_list(mo["lines"], "m_Colliders"),
                "exclusions": inline_ref_list(mo["lines"], "m_Exclusions"),
            },
        })

    for d in dyn:
        ex = set()
        for t in d["params"]["exclusions"]:
            ex.update(subtree(t))
        if d["bones_explicit"]:
            wanted = set(d["bones_explicit"])
            ids = [tf for tf in by_class.get(4, []) if tf_path(tf) in wanted]
        else:
            ids = subtree(d["root_tf"]) if d["root_tf"] else []
        d["affected_tf"] = sorted([i for i in ids if i not in ex],
                                  key=tf_path)
        d["affected_paths"] = [tf_path(i) for i in d["affected_tf"]]

    smrs = []
    for fid in by_class.get(137, []):
        o = objs[fid]
        go = re.sub(r"\D", "", field(o["lines"], "m_GameObject") or "")
        bones = inline_ref_list(o["lines"], "m_Bones") + refs(o["lines"], "m_Bones")
        smrs.append({
            "fileID": fid,
            "go": objs.get(go, {}).get("name", "?"),
            "path": tf_path(objs.get(go, {}).get("tf")),
            "bones": [tf_path(b) for b in bones],
            "mesh": field(o["lines"], "m_Mesh"),
        })

    affected_paths = set()
    for d in dyn:
        affected_paths.update(d["affected_paths"])
    hit = []
    for s in smrs:
        inter = [b for b in s["bones"] if b in affected_paths]
        if inter:
            hit.append({"renderer": s["path"] or s["go"],
                        "n_bones_total": len(s["bones"]),
                        "n_bones_in_dyn": len(inter),
                        "sample": inter[:6]})

    return {
        "prefab": prefab,
        "counts": {
            "gameobjects": len(by_class.get(1, [])),
            "transforms": len(by_class.get(4, [])),
            "monobehaviours": len(monos),
            "skinned": len(smrs),
            "sprites": len(by_class.get(212, [])),
        },
        "scripts": sorted({m["script"] for m in monos}),
        "monobehaviours": [{"script": m["script"], "go": m["go"],
                            "go_path": m["go_path"], "enabled": m["enabled"]}
                           for m in monos],
        "dynamic_bones": dyn,
        "skinned_renderers": smrs,
        "renderers_affected_by_dyn": hit,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("--assets", default=None,
                    help="工程 Assets 目录(用来把脚本 guid 换成名字)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    rep = parse(a.prefab, a.assets)
    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as fp:
            json.dump(rep, fp, ensure_ascii=False, indent=1)
    if a.quiet:
        return 0

    print("prefab : %s" % rep["prefab"])
    print("规模   : %s" % rep["counts"])
    print("脚本   : %s" % ", ".join(rep["scripts"]))
    print()
    print("== MonoBehaviour 明细 ==")
    for m in rep["monobehaviours"]:
        print("   %-30s on %-26s enabled=%s" % (m["script"], m["go_path"] or m["go"],
                                                m["enabled"]))
    print()
    print("== DynamicBone ==")
    for d in rep["dynamic_bones"]:
        print("   #%s on %s" % (d["fileID"], d["on_path"]))
        print("      root      : %s" % d["root_path"])
        print("      参数      : %s" % d["params"])
        print("      管辖骨骼  : %d 根" % len(d["affected_paths"]))
        for p in d["affected_paths"][:12]:
            print("         - %s" % p)
        if len(d["affected_paths"]) > 12:
            print("         … 其余 %d 根" % (len(d["affected_paths"]) - 12))
    print()
    print("== 视觉会受 DynamicBone 影响的渲染器 ==")
    for h in rep["renderers_affected_by_dyn"]:
        print("   %-56s bones %d/%d  %s" % (h["renderer"], h["n_bones_in_dyn"],
                                             h["n_bones_total"], h["sample"]))
    print()
    print("== SkinnedMeshRenderer(全部)==")
    for s in rep["skinned_renderers"]:
        print("   %-56s bones=%d" % ((s["path"] or s["go"]), len(s["bones"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
