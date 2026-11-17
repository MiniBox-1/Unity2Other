# -*- coding: utf-8 -*-
"""Inspect character Animators, duplicate hosts and retained clips."""
import argparse
import os
import sys

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(LIB, "src"))

from ngui2spine.static_prefab_spine import (  # noqa: E402
    ASSETS_DEFAULT, enumerate_clips, load_character)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("--assets", default=ASSETS_DEFAULT)
    ap.add_argument("--scene")
    args = ap.parse_args()

    mdl, _parts = load_character(args.prefab, args.assets, args.scene)
    entries = enumerate_clips(mdl, args.assets)
    paths = {td["go"]: td.get("path", "")
             for td in mdl.transforms.values()}
    print("prefab=%s" % args.prefab)
    for animator in getattr(mdl, "char_animators", None) or []:
        go = animator.get("go")
        print("animator go=%s path=%s controller=%s" % (
            go, paths.get(go, ""), animator.get("controllerGuid")))
    print("dedupe_host=%r" % (getattr(mdl, "dedupe_host", {}) or {},))
    print("retained entries:")
    for go, state in sorted(set((entry["go"], entry["state"])
                                for entry in entries)):
        print("  go=%s state=%s" % (go, state))


if __name__ == "__main__":
    main()
