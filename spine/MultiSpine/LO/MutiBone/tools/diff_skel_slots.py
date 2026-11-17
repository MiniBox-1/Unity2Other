# -*- coding: utf-8 -*-
"""Compare setup slots and one animation's slot timelines between two .skel files."""
import argparse
import os
import sys

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, os.path.join(LIB, "src"))

from unity2spine.spine.spine38_binary import read_skeleton_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--animation", default="Start")
    args = ap.parse_args()
    a = read_skeleton_json(args.a)
    b = read_skeleton_json(args.b)
    sa = {slot["name"]: slot for slot in a.get("slots") or []}
    sb = {slot["name"]: slot for slot in b.get("slots") or []}
    for name in sorted(set(sa) | set(sb)):
        if sa.get(name) != sb.get(name):
            print("setup slot differs:", name, sa.get(name), sb.get(name))
    ta = ((a.get("animations") or {}).get(args.animation) or {}).get("slots") or {}
    tb = ((b.get("animations") or {}).get(args.animation) or {}).get("slots") or {}
    shown = 0
    for name in sorted(set(ta) | set(tb)):
        if ta.get(name) != tb.get(name):
            print("timeline differs:", name)
            print("  A:", ta.get(name))
            print("  B:", tb.get(name))
            shown += 1
            if shown >= 30:
                break
    print("animation slots: A=%d B=%d differences=%d"
          % (len(ta), len(tb), shown))


if __name__ == "__main__":
    main()
