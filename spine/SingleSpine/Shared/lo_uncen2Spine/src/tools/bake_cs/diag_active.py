# -*- coding: utf-8 -*-
r"""离线排查"SetActive（m_IsActive）显隐"判定：为什么某个部件被当成
"Unity 里始终禁用"而没被导出，或者显隐时间轴算错。

纯离线（只读 prefab / controller / clip），不需要 Unity。

用法:
    python diag_active.py <prefab> --assets <Assets> --match Shadow
"""

import argparse
import os
import sys


from unity2spine.convert.static_prefab_spine import (      # noqa: E402
    _active_value, _curve_lookup, _enabled_value, _renderer_enabled,
    dead_active_paths, enumerate_clips, load_character, node_visible,
    part_visible, probe_times_for)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("--assets", required=True)
    ap.add_argument("--match", default="Shadow")
    ap.add_argument("--times", default="0,0.5,1,2,3,5,8")
    a = ap.parse_args()

    times = [float(x) for x in a.times.split(",") if x.strip()]
    mdl, parts = load_character(a.prefab, a.assets)
    raw = [(p, mdl.transforms.get(p.tfid, {})) for p in parts]
    hits = [(p, td) for p, td in raw
            if a.match.lower() in (td.get("path") or "").lower()]
    print("命中 %d 个部件（match=%s）" % (len(hits), a.match))
    if not hits:
        print("没有命中；全部部件路径示例：")
        for p, td in raw[:10]:
            print("   ", td.get("path"))
    dead = dead_active_paths(mdl)
    print("dead_active_paths: %s" % (sorted(dead) or "（空）"))

    entries = enumerate_clips(mdl, a.assets) or []
    print("动画 %d 条：%s" % (len(entries),
                             "、".join(e["name"] for e in entries)))

    for p, td in hits:
        print("=" * 78)
        print("部件 %s (%s)" % (p.full_path, p.kind))
        print("  tfid=%s  anim_path=%r  静态 active=%r  静态 renderer.enabled=%r"
              % (p.tfid, td.get("anim_path"),
                 mdl.gameobjects.get(td.get("go"), {}).get("active"),
                 _renderer_enabled(mdl, p.tfid)))
        for e in entries:
            clip = e.get("clip") or {}
            pfx = clip.get("_prefix") or ""
            ks = _curve_lookup(clip.get("active") or {},
                               td.get("anim_path") or "", pfx)
            ke = _curve_lookup(clip.get("enabled") or {},
                               td.get("anim_path") or "", pfx)
            if ks is None and ke is None:
                continue
            print("  [%s] m_IsActive 曲线 %s" % (
                e["name"],
                ("键 " + " ".join("(%.3f,%.3f)" % (t, v) for t, v in ks))
                if ks else "无"))
            if ke is not None:
                print("        m_Enabled 曲线 %s"
                      % " ".join("(%.3f,%.3f)" % (t, v) for t, v in ke))
            ts = [t for t in probe_times_for(e, 0.05)]
            vis = [(t, part_visible(mdl, clip, t, p.tfid)) for t in ts]
            show = [t for t, v in vis if v]
            print("        探测 %d 个时刻 → 可见 %d 个%s"
                  % (len(ts), len(show),
                     ("（%.3f~%.3f）" % (show[0], show[-1])) if show else ""))
            av = [(t, _active_value(clip, td.get("anim_path") or "", pfx, t))
                  for t in times]
            print("        _active_value: %s"
                  % " ".join("%.2f→%s" % (t, v) for t, v in av))
    # 顺带把"所有 clip 里提到过但本部件没被导出"的路径列出来
    print("=" * 78)
    print("每条动画的 m_IsActive 曲线里提到 Shadow 的路径：")
    for e in entries:
        clip = e.get("clip") or {}
        for path in sorted((clip.get("active") or {})):
            if a.match.lower() in path.lower():
                ks = clip["active"][path]
                print("  [%s] %s  键=%s" % (
                    e["name"], path,
                    " ".join("(%.2f,%.2f)" % (t, v) for t, v in ks[:8])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
