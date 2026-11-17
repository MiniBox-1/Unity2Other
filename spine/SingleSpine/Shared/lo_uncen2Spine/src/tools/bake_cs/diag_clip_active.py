# -*- coding: utf-8 -*-
r"""看一条 clip 的 `m_FloatCurves` 到底被解析成什么：
active（m_IsActive）/ enabled / color 的键，以及**原始文本里**这些属性的条数。

用来判"显隐曲线丢了"是解析器没读、还是路径被改名/哈希后挂到别的键上。

用法:
    python diag_clip_active.py <prefab> --assets <Assets> [--grep Shadow] [--raw]
"""

import argparse
import io
import os
import re
import sys


from unity2spine.convert.static_prefab_spine import (      # noqa: E402
    enumerate_clips, load_character)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("--assets", required=True)
    ap.add_argument("--grep", default="Shadow")
    ap.add_argument("--raw", action="store_true", help="同时打印原始文本片段")
    a = ap.parse_args()

    mdl, _parts = load_character(a.prefab, a.assets)
    for e in enumerate_clips(mdl, a.assets) or []:
        clip = e.get("clip") or {}
        print("=" * 78)
        print("[%s] clip=%s  duration=%.3f  _prefix=%r"
              % (e["name"], clip.get("name"), float(e.get("duration") or 0),
                 clip.get("_prefix")))
        for key in ("active", "enabled", "color", "morph", "sorting"):
            d = clip.get(key) or {}
            if not isinstance(d, dict):
                continue
            print("  %-8s %d 条" % (key, len(d)))
            hits = [k for k in d if a.grep and a.grep.lower() in k.lower()]
            for k in hits:
                v = d[k]
                if key == "morph":
                    print("      命中 %s -> %s" % (k, list(v)))
                elif key == "color":
                    # color[path][attr] = keys
                    for attr, keys in sorted(v.items()):
                        print("      命中 %s.%s -> %d 键 %s"
                              % (k, attr, len(keys),
                                 " ".join("(%.2f,%.2f)" % (t, val)
                                          for t, val in list(keys)[:8])))
                else:
                    print("      命中 %s -> %d 键 %s"
                          % (k, len(v),
                             " ".join("(%.2f,%.2f)" % (t, val)
                                      for t, val in list(v)[:6])))
            if key == "active" and len(d) <= 40:
                for k in sorted(d):
                    print("      · %s" % k)
        # 原始文本统计
        gp = clip.get("_src") or clip.get("_path") or clip.get("path")
        if gp and os.path.isfile(gp):
            txt = io.open(gp, encoding="utf-8", errors="replace").read()
            n_act = len(re.findall(r"^    attribute: m_IsActive$", txt, re.M))
            n_sha = len(re.findall(r"(?i)shadow", txt))
            print("  原始文件 %s：attribute=m_IsActive %d 条，出现 'shadow' %d 次"
                  % (os.path.basename(gp), n_act, n_sha))
            if a.raw and n_sha:
                for m in re.finditer(r"(?i)^\s*path: .*shadow.*$", txt, re.M):
                    print("      raw path: %s" % m.group(0).strip())
                    if m.start() and n_sha > 40:
                        break
        else:
            print("  （拿不到 clip 源文件路径：keys=%s）"
                  % [k for k in clip.keys() if k.startswith("_")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
