# -*- coding: utf-8 -*-
"""Print root/slot/animation summary from Spine 3.8 binary skeletons."""
import argparse
import os
import sys

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, os.path.join(LIB, "src"))

from unity2spine.spine.spine38_binary import read_skeleton_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("skel", nargs="+")
    ap.add_argument("--animation")
    ap.add_argument("--slots", action="store_true")
    args = ap.parse_args()
    for path in args.skel:
        skel = read_skeleton_json(path)
        bones = skel.get("bones") or []
        roots = [b["name"] for b in bones if not b.get("parent")]
        colored = [s for s in (skel.get("slots") or [])
                   if s.get("color") not in (None, "ffffffff")]
        print("%s bones=%d roots=%d [%s] colored_slots=%d"
              % (os.path.basename(path), len(bones), len(roots),
                 ", ".join(roots), len(colored)))
        for slot in colored[:12]:
            print("  slot %s color=%s blend=%s" % (
                slot.get("name"), slot.get("color"), slot.get("blend")))
        if args.slots:
            print("  slots=" + ",".join(
                slot.get("name") or "" for slot in (skel.get("slots") or [])))
        if args.animation:
            anim = (skel.get("animations") or {}).get(args.animation) or {}
            slots = anim.get("slots") or {}
            print("  %s color_timelines=%d" % (args.animation, len(slots)))
            for name, timeline in list(slots.items())[:12]:
                print("    %s keys=%s" % (name, ",".join(sorted(timeline))))
                attach = timeline.get("attachment") or []
                if attach:
                    print("      attachment %d frames %r -> %r" % (
                        len(attach), attach[0].get("name"),
                        attach[-1].get("name")))
                frames = timeline.get("color") or []
                if frames:
                    print("    %s %d frames %s -> %s" % (
                        name, len(frames), frames[0].get("color"),
                        frames[-1].get("color")))


if __name__ == "__main__":
    main()
