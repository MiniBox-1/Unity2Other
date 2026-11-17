# -*- coding: utf-8 -*-
"""命令行入口（调试用）—— 与 GUI 走**同一条**协议路径，方便无界面复现问题。

用法：
    python -m unity2spine.cli list
    python -m unity2spine.cli run lo --input <角色>.uAnim.prefab [--out DIR] [--json]
    python -m unity2spine.cli run bdone --input <立绘>.prefab
    python -m unity2spine.cli run lo --input ... --env U2S_LAYER_PHASE=0.499
    python -m unity2spine.cli gui

`--opt k=v` / `--env K=V` 可重复；`--json`、`--no-cs` 是常用开关的糖。
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List

from .console import fix_console


def _kv(pairs: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for s in pairs or []:
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main(argv: List[str] | None = None) -> int:
    fix_console()
    ap = argparse.ArgumentParser(
        "unity2spine", description="Unity 原生数据 → Spine 3.8（调试用 CLI）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出所有线路（扩展库注册的 Profile）")
    r = sub.add_parser("run", help="跑一条线路")
    r.add_argument("profile", help="线路名（list 里看到的 name）")
    r.add_argument("--input", required=True, help="prefab 绝对路径")
    r.add_argument("--out", default="", help="输出目录（缺省用线路默认）")
    r.add_argument("--assets", default="", help="Unity Assets 根（缺省用线路默认）")
    r.add_argument("--opt", action="append", default=[], help="线路参数 k=v，可重复")
    r.add_argument("--env", action="append", default=[],
                   help="环境变量 K=V（每角色口径），可重复")
    r.add_argument("--json", action="store_true", help="糖：opt json=true（研究用）")
    r.add_argument("--no-cs", action="store_true", help="糖：opt cs=false")
    sub.add_parser("gui", help="打开 GUI")
    a = ap.parse_args(argv)

    from unity2spine.api import ConvertRequest, discover
    profiles = discover()

    if a.cmd == "list":
        if not profiles:
            print("(没发现任何线路：检查 ext_bdone / ext_lo 是否在 sys.path 上)")
            return 1
        for p in profiles:
            print("%-8s %-34s input=%s" % (p.name, p.label, p.input_kind))
            if p.defaults:
                print("         defaults=%s" % p.defaults)
        return 0

    if a.cmd == "gui":
        from unity2spine.gui.main import main as gui_main
        return gui_main()

    prof = next((p for p in profiles if p.name == a.profile), None)
    if prof is None:
        print("找不到线路 %s；可选：%s"
              % (a.profile, ", ".join(p.name for p in profiles)))
        return 2
    if prof.run is None:
        print("线路 %s 没有 run()（扩展库没接好）" % prof.name)
        return 2

    opts: Dict[str, object] = dict(_kv(a.opt))
    if a.json:
        opts["json"] = True
    if a.no_cs:
        opts["cs"] = False
    req = ConvertRequest(
        input_path=os.path.abspath(a.input),
        output_dir=os.path.abspath(a.out or prof.defaults.get("output_dir", ".")),
        assets_dir=os.path.abspath(a.assets or prof.defaults.get("assets_dir", "")),
        options=opts, env=_kv(a.env),
        log=lambda s: print(s, flush=True))
    res = prof.run(req)
    print("[cli] ok=%s detail=%s outputs=%s" % (res.ok, res.detail, res.outputs))
    return 0 if res.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
