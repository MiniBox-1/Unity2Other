# -*- coding: utf-8 -*-
"""Compare Spine bone worlds used by selected slots against a Unity frame dump."""
import argparse
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compare_runtime_geom import apply, local_matrix, mul  # noqa: E402

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, os.path.join(LIB, "src"))
sys.path.insert(0, os.path.join(LIB, "tools", "bake_cs"))

from read_framedump import frame_at, load_json, obj_paths, read_dump  # noqa: E402


def unwrap_angle(value):
    while value > 180.0:
        value -= 360.0
    while value < -180.0:
        value += 360.0
    return value


def spine_angle(m):
    return math.degrees(math.atan2(m[2], m[0]))


def unity_parts(l2w):
    """Return (x, y, angle, scale_x, scale_y) from row-major localToWorld."""
    exx, exy = l2w[0], l2w[4]
    eyx, eyy = l2w[1], l2w[5]
    return (l2w[3], l2w[7], math.degrees(math.atan2(exy, exx)),
            math.hypot(exx, exy), math.hypot(eyx, eyy))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("product")
    ap.add_argument("--animation", required=True)
    ap.add_argument("--time", type=float, required=True,
                    help="seconds from the first recorded frame")
    ap.add_argument("--grep", required=True,
                    help="only inspect bones used by matching slot names")
    ap.add_argument("--info-dir")
    ap.add_argument("--unit-k", type=float, default=100.0)
    ap.add_argument("--list-parts", action="store_true",
                    help="print each selected slot's host and weighted bones")
    args = ap.parse_args()

    meta, _ = read_dump(args.dump)
    if meta is None:
        raise SystemExit("missing .meta.json")
    names = obj_paths(meta)
    first = frame_at(args.dump)
    origin = float(first.get("t", 0.0))
    frame = frame_at(args.dump, origin + args.time)
    if frame is None:
        raise SystemExit("frame not found")
    unity_t = float(frame["t"])
    anim_t = unity_t - origin

    info_dir = args.info_dir or args.product
    info = load_json(os.path.join(info_dir, "_static_info.json"))
    json_name = next(name for name in os.listdir(args.product)
                     if name.endswith("_static.json"))
    skel = load_json(os.path.join(args.product, json_name))
    animation = (skel.get("animations") or {}).get(args.animation) or {}
    bones = skel.get("bones") or []
    bone_index = {bone["name"]: i for i, bone in enumerate(bones)}
    worlds = []
    for bone in bones:
        local = local_matrix(bone, animation, anim_t)
        parent = bone.get("parent")
        worlds.append(mul(worlds[bone_index[parent]], local)
                      if parent else local)

    objects = {obj["i"]: obj for obj in frame.get("obj") or []}
    runtime_by_leaf = {}
    for obj_index, path in names.items():
        leaf = path.replace("\\", "/").rsplit("/", 1)[-1]
        runtime_by_leaf.setdefault(leaf, []).append(obj_index)

    attachments = ((skel.get("skins") or [{}])[0].get("attachments") or {})
    slots = {slot["name"]: slot for slot in skel.get("slots") or []}
    grep_tokens = [token.strip().lower()
                   for token in args.grep.split(",") if token.strip()]
    wanted_parts = {
        part["name"] for part in (info.get("partsMeta") or [])
        if any(token in (part.get("name") or "").lower()
               for token in grep_tokens)
    }

    influence = {}
    for name in wanted_parts:
        slot = slots.get(name)
        if slot is None:
            continue
        att = ((attachments.get(name) or {}).get(slot.get("attachment")) or {})
        verts = att.get("vertices") or []
        uvs = att.get("uvs") or []
        part_influence = {}
        if len(verts) == len(uvs):
            host_index = bone_index.get(slot.get("bone"))
            if host_index is not None:
                influence[host_index] = (
                    influence.get(host_index, 0.0) + len(verts) / 2.0)
                part_influence[host_index] = len(verts) / 2.0
            if args.list_parts:
                print("SLOT %s host=%s weighted=no vertices=%d"
                      % (name, slot.get("bone"), len(verts) // 2))
            continue
        i = 0
        while i < len(verts):
            count = int(verts[i])
            i += 1
            for _ in range(count):
                bi = int(verts[i])
                weight = abs(float(verts[i + 3]))
                influence[bi] = influence.get(bi, 0.0) + weight
                part_influence[bi] = part_influence.get(bi, 0.0) + weight
                i += 4
        if args.list_parts:
            used = ", ".join("%s=%.3f" % (bones[bi]["name"], weight)
                             for bi, weight in sorted(
                                 part_influence.items(),
                                 key=lambda item: -item[1]))
            print("SLOT %s host=%s weighted=yes vertices=%d bones=%s"
                  % (name, slot.get("bone"), len(uvs) // 2, used))

    ox, oy = (info.get("origin") or [0.0, 0.0])[:2]
    rows = []
    for bi, total_weight in influence.items():
        bone_name = bones[bi]["name"]
        base = bone_name.rsplit("_", 1)[0]
        candidates = runtime_by_leaf.get(base) or []
        best = None
        for obj_index in candidates:
            obj = objects.get(obj_index)
            if not obj or "l2w" not in obj:
                continue
            ux, uy, ua, usx, usy = unity_parts(obj["l2w"])
            sx = worlds[bi][4] / args.unit_k + ox
            sy = worlds[bi][5] / args.unit_k + oy
            sa = spine_angle(worlds[bi])
            sscx = math.hypot(worlds[bi][0], worlds[bi][2])
            sscy = math.hypot(worlds[bi][1], worlds[bi][3])
            err = math.hypot(sx - ux, sy - uy)
            row = (err, bone_name, bi, total_weight, len(candidates),
                   sx, sy, sa, sscx, sscy, ux, uy, ua, usx, usy,
                   names.get(obj_index, ""))
            if best is None or row[0] < best[0]:
                best = row
        if best is not None:
            rows.append(best)

    rows.sort(reverse=True)
    print("frame=%s unity_t=%.4f anim_t=%.4f parts=%d bones=%d"
          % (frame.get("f"), unity_t, anim_t, len(wanted_parts), len(rows)))
    print("%-42s %5s %8s %8s %8s %8s %8s %s"
          % ("bone", "cand", "weight", "xyzErr", "dAngle", "dSX", "dSY",
             "unity path"))
    for (err, bone_name, _bi, weight, cand, sx, sy, sa, ssx, ssy,
         ux, uy, ua, usx, usy, path) in rows[:40]:
        print("%-42s %5d %8.3f %8.5f %8.3f %8.4f %8.4f %s"
              % (bone_name, cand, weight, err, unwrap_angle(sa - ua),
                 ssx - usx, ssy - usy, path))


if __name__ == "__main__":
    main()
