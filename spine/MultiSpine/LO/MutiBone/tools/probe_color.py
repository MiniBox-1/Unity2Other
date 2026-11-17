# -*- coding: utf-8 -*-
"""Diagnose why a clip's color curves do/don't reach the multi-bone output."""
import argparse
import os
import sys

BASE = r"D:\VB\MutiBone"
sys.path.insert(0, os.path.join(BASE, "src"))

from convert_bones import (                                               # noqa: E402
    load_character, enumerate_clips, color_timeline, _compose_overlay_layers,
    part_visible, _animation_times_for)
from ngui2spine.convert_2dmodel import _asset_path                       # noqa: E402
from ngui2spine.unity_2dmodel import parse_animator_layers               # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("--assets", required=True)
    ap.add_argument("--scene")
    ap.add_argument("--state")
    args = ap.parse_args()
    mdl, parts = load_character(args.prefab, args.assets, args.scene)
    entries = enumerate_clips(mdl, args.assets)
    controller = _asset_path(
        args.assets, getattr(mdl, "animator_controller_guid", None) or "")
    print("controller=%s" % controller)
    if controller and os.path.isfile(controller):
        for layer in parse_animator_layers(controller):
            print("layer=%r blend=%r weight=%r default=%r states=%r" % (
                layer.get("name"), layer.get("blend"), layer.get("weight"),
                layer.get("defaultClipGuid"),
                [name for name, _guid in (layer.get("states") or [])]))
    _compose_overlay_layers(mdl, args.assets, entries)
    for entry in entries:
        if args.state and entry["state"] != args.state:
            continue
        clip = entry.get("clip") or {}
        print("%s clips color=%d color_cls=%d prefix=%r"
              % (entry["state"], len(clip.get("color") or {}),
                 len(clip.get("color_cls") or {}), clip.get("_prefix")))
        sample_times = _animation_times_for(entry)
        print("  times near start=%r" % sample_times[:12])
        for path, keys in (clip.get("active") or {}).items():
            near = [(round(tm, 6), value) for tm, value in keys
                    if 0.04 <= tm <= 0.07]
            if near:
                print("  active near 0.05: %s %r" % (path, near))
        curve_times = sorted({
            round(tm, 6)
            for curve in (clip.get("curves") or [])
            for tm, _value in (getattr(curve, "keys", None) or [])
            if 0.04 <= tm <= 0.07
        })
        if curve_times:
            print("  curve keys near 0.05=%r" % curve_times)
        hits = 0
        for part in parts:
            td = mdl.transforms.get(part.tfid) or {}
            visible = [part_visible(mdl, clip, tm, part.tfid)
                       for tm in (0.0, 0.5, 1.0)]
            if not all(visible):
                print("  %s visibility=%r path=%s"
                      % (part.name, visible, td.get("anim_path")))
            frames = color_timeline(
                part, clip, td.get("anim_path") or "",
                clip.get("_prefix") or "", lambda value: round(float(value), 4),
                "ffffffff")
            if frames:
                hits += 1
                print("  %s path=%s frames=%d"
                      % (part.name, td.get("anim_path"), len(frames)))
        print("  total color timelines=%d" % hits)


if __name__ == "__main__":
    main()
