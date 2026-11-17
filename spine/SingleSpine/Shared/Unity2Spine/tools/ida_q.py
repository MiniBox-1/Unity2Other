# -*- coding: utf-8 -*-
"""IDA 批处理查询器（逆向 UnityPlayer 用；2026-09-14 那几轮核对就是它跑的）。

用法（无界面）：

    cd D:\\VB\\Unity2Spine
    # 先把要查的库复制一份（不要在原始 .i64 上跑，IDB 会被 IDA 改写）
    copy D:\\Reverse\\win64_player_nondevelopment_il2cpp\\UnityPlayer.dll.i64 _reverse\\UP.i64
    set REQ_INLINE={"op":"decompile","ea":"0x180B39180"}      （或 REQ_JSON=请求文件）
    set REQ_OUT=_reverse\\res.json
    D:\\Reverse\\IDA_Pro_v8.3_Portable\\idat64.exe -A -L_reverse\\ida.log ^
        -S"D:\\VB\\Unity2Spine\\tools\\ida_q.py" _reverse\\UP.i64

`REQ_INLINE` 也可以是一个请求数组（一次加载跑多条查询，省去每次 20~30 秒的库加载）。

支持的 op：info / names / strings / xrefs_to / disasm / decompile / funcs_at /
calls / bytes_at（见下面 OPS）。

Request json:
    {"op": "...", ...}

Ops:
    info                         basic database info
    names     {regex, limit}     search symbol names
    strings   {substr, limit}    search string literals
    xrefs_to  {name|ea}          code xrefs to an address/name
    disasm    {name|ea, count}   disassembly listing
    decompile {name|ea}          hex-rays pseudocode
    funcs_at  {regex}            function entry for each matching name
    calls     {name|ea, depth}   callers up to depth
    bytes_at  {name|ea, count}   raw bytes
"""
import json
import os
import re
import sys
import traceback

import idaapi
import idautils
import idc
import ida_bytes
import ida_funcs
import ida_ida
import ida_name
import ida_nalt
import ida_segment
import ida_hexrays


if os.environ.get("REQ_INLINE"):
    REQ = json.loads(os.environ["REQ_INLINE"])
else:
    REQ = json.loads(open(os.environ["REQ_JSON"], "r", encoding="utf-8").read())
OUT = os.environ.get("REQ_OUT", "")


def ea_of(req):
    if "ea" in req and req["ea"] is not None:
        return int(req["ea"]) if not isinstance(req["ea"], str) else int(req["ea"], 0)
    name = req.get("name")
    if not name:
        return idaapi.BADADDR
    ea = idc.get_name_ea_simple(name)
    if ea == idaapi.BADADDR:
        ea = idaapi.get_name_ea(idaapi.BADADDR, name)
    return ea


def fmt_ea(ea):
    return "0x%X" % ea if ea != idaapi.BADADDR else "BADADDR"


def do_info(_req):
    segs = []
    for s in idautils.Segments():
        seg = ida_segment.getseg(s)
        segs.append({
            "name": ida_segment.get_segm_name(seg),
            "start": fmt_ea(seg.start_ea),
            "end": fmt_ea(seg.end_ea),
            "perm": int(seg.perm),
        })
    funcs = list(idautils.Functions())
    named = 0
    for ea in funcs:
        if ida_funcs.get_func_name(ea) and not ida_funcs.get_func_name(ea).startswith("sub_"):
            named += 1
    return {
        "kernel_version": str(idaapi.get_kernel_version()),
        "ida_version": str(idaapi.get_ida_version()) if hasattr(idaapi, "get_ida_version") else None,
        "input": ida_nalt.get_root_filename(),
        "input_path": ida_nalt.get_input_file_path(),
        "imagebase": fmt_ea(idaapi.get_imagebase()),
        "procname": ida_ida.inf_get_procname(),
        "is_64bit": bool(ida_ida.inf_is_64bit()),
        "func_count": len(funcs),
        "named_func_count": named,
        "string_count": sum(1 for _ in idautils.Strings()),
        "hexrays": bool(ida_hexrays.init_hexrays_plugin()),
        "segments": segs,
    }


def do_names(req):
    rx = re.compile(req["regex"])
    lim = int(req.get("limit", 200))
    hits = []
    for ea, name in idautils.Names():
        if rx.search(name):
            hits.append({"ea": fmt_ea(ea), "name": name})
            if len(hits) >= lim:
                break
    return {"count": len(hits), "hits": hits}


def do_strings(req):
    want = req.get("substr", "")
    rx = re.compile(want) if req.get("regex", False) else None
    lim = int(req.get("limit", 200))
    hits = []
    for s in idautils.Strings():
        try:
            text = str(s)
        except Exception:
            continue
        if (rx.search(text) if rx else (want in text)):
            hits.append({"ea": fmt_ea(s.ea), "str": text[:400], "len": s.length})
            if len(hits) >= lim:
                break
    return {"count": len(hits), "hits": hits}


def do_xrefs_to(req):
    ea = ea_of(req)
    if ea == idaapi.BADADDR:
        return {"error": "not found", "req": {k: v for k, v in req.items() if k != "op"}}
    lim = int(req.get("limit", 200))
    out = []
    for x in idautils.XrefsTo(ea, 0):
        f = ida_funcs.get_func(x.frm)
        out.append({
            "frm": fmt_ea(x.frm),
            "func": ida_funcs.get_func_name(f.start_ea) if f else None,
            "type": int(x.type),
        })
        if len(out) >= lim:
            break
    return {"target": fmt_ea(ea), "count": len(out), "xrefs": out}


def do_disasm(req):
    ea = ea_of(req)
    if ea == idaapi.BADADDR:
        return {"error": "not found"}
    cnt = int(req.get("count", 60))
    lines = []
    for _ in range(cnt):
        line = idc.generate_disasm_line(ea, 0)
        lines.append("%s  %s" % (fmt_ea(ea), idc.tag_remove(line) if hasattr(idc, "tag_remove") else line))
        nxt = idc.next_head(ea)
        if nxt <= ea:
            break
        ea = nxt
    f = ida_funcs.get_func(ea_of(req))
    return {
        "start": fmt_ea(ea_of(req)),
        "func": ida_funcs.get_func_name(f.start_ea) if f else None,
        "lines": lines,
    }


def do_decompile(req):
    ea = ea_of(req)
    if ea == idaapi.BADADDR:
        return {"error": "not found"}
    if not ida_hexrays.init_hexrays_plugin():
        return {"error": "hexrays unavailable"}
    f = ida_funcs.get_func(ea)
    if f is None:
        return {"error": "no function at %s" % fmt_ea(ea)}
    try:
        cf = ida_hexrays.decompile(f.start_ea)
    except Exception as exc:  # noqa: BLE001
        return {"error": "decompile failed: %r" % (exc,)}
    if cf is None:
        return {"error": "decompile returned None"}
    return {
        "func": ida_funcs.get_func_name(f.start_ea),
        "ea": fmt_ea(f.start_ea),
        "pseudocode": str(cf),
    }


def do_funcs_at(req):
    rx = re.compile(req["regex"])
    lim = int(req.get("limit", 500))
    out = []
    for ea, name in idautils.Names():
        if rx.search(name):
            f = ida_funcs.get_func(ea)
            if f is not None:
                out.append({
                    "name": name,
                    "ea": fmt_ea(ea),
                    "func_ea": fmt_ea(f.start_ea),
                    "func_name": ida_funcs.get_func_name(f.start_ea),
                    "size": f.end_ea - f.start_ea,
                })
                if len(out) >= lim:
                    break
    return {"count": len(out), "hits": out}


def do_calls(req):
    ea = ea_of(req)
    if ea == idaapi.BADADDR:
        return {"error": "not found"}
    depth = int(req.get("depth", 2))
    lim = int(req.get("limit", 300))
    seen = set()
    levels = []
    cur = [ea]
    for _ in range(depth):
        nxt = []
        for a in cur:
            for x in idautils.XrefsTo(a, 0):
                f = ida_funcs.get_func(x.frm)
                if f is None:
                    continue
                if f.start_ea in seen:
                    continue
                seen.add(f.start_ea)
                nxt.append(f.start_ea)
                if len(seen) >= lim:
                    break
            if len(seen) >= lim:
                break
        levels.append([{"ea": fmt_ea(a), "name": ida_funcs.get_func_name(a)} for a in nxt])
        cur = nxt
        if not cur or len(seen) >= lim:
            break
    return {"target": fmt_ea(ea), "levels": levels}


def do_bytes_at(req):
    ea = ea_of(req)
    if ea == idaapi.BADADDR:
        return {"error": "not found"}
    cnt = int(req.get("count", 64))
    data = ida_bytes.get_bytes(ea, cnt)
    return {"ea": fmt_ea(ea), "hex": data.hex() if data else None}


OPS = {
    "info": do_info,
    "names": do_names,
    "strings": do_strings,
    "xrefs_to": do_xrefs_to,
    "disasm": do_disasm,
    "decompile": do_decompile,
    "funcs_at": do_funcs_at,
    "calls": do_calls,
    "bytes_at": do_bytes_at,
}


def main():
    reqs = REQ if isinstance(REQ, list) else [REQ]
    results = []
    for one in reqs:
        op = one.get("op")
        result = {"op": op}
        try:
            result.update(OPS[op](one))
        except Exception:
            result["error"] = traceback.format_exc()
        results.append(result)
    payload = json.dumps(results if isinstance(REQ, list) else results[0],
                         ensure_ascii=False, indent=1)
    if OUT:
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write(payload)
    else:
        sys.stdout.write(payload)
    idc.qexit(0)


main()
