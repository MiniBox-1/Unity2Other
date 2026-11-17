# -*- coding: utf-8 -*-
"""Scan product animation times against one Unity frame in a single process."""
import argparse
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compare_runtime_geom import (  # noqa: E402
    apply, deform_at, local_matrix, mul)

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, os.path.join(LIB, "src"))
sys.path.insert(0, os.path.join(LIB, "tools", "bake_cs"))

from read_framedump import frame_at, load_json, obj_paths, read_dump  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("product")
    ap.add_argument("--animation", required=True)
    ap.add_argument("--runtime-time", type=float, required=True,
                    help="seconds from first recorded frame")
    ap.add_argument("--from-time", type=float, default=0.0)
    ap.add_argument("--to-time", type=float, default=1.0)
    ap.add_argument("--step", type=float, default=0.02)
    ap.add_argument("--info-dir")
    ap.add_argument("--unit-k", type=float, default=100.0)
    args = ap.parse_args()

    meta, _ = read_dump(args.dump)
    names = obj_paths(meta)
    first = frame_at(args.dump)
    origin = float(first.get("t", 0.0))
    target = frame_at(args.dump, origin + args.runtime_time)
    if target is None:
        raise SystemExit("frame not found")
    objects = {obj["i"]: obj for obj in target.get("obj") or []}
    runtime = []
    for renderer in target.get("rnd") or []:
        obj = objects.get(renderer.get("o"))
        path = names.get(renderer.get("o"), "").replace("\\", "/")
        if obj and path and renderer.get("v") and renderer.get("vn"):
            runtime.append((path, renderer["v"]))

    info_dir = args.info_dir or args.product
    info = load_json(os.path.join(info_dir, "_static_info.json"))
    json_name = next(name for name in os.listdir(args.product)
                     if name.endswith("_static.json"))
    skel = load_json(os.path.join(args.product, json_name))
    animation = (skel.get("animations") or {}).get(args.animation) or {}
    bones = skel.get("bones") or []
    index = {bone["name"]: i for i, bone in enumerate(bones)}
    slots = {slot["name"]: slot for slot in skel.get("slots") or []}
    attachments = ((skel.get("skins") or [{}])[0].get("attachments") or {})
    parts_by_path = {}
    for part in info.get("partsMeta") or []:
        rel = (part.get("path") or "").replace("\\", "/")
        if "/" in rel:
            rel = rel.split("/", 1)[1]
        parts_by_path[rel] = part
    ox, oy = (info.get("origin") or [0.0, 0.0])[:2]

    rows = []
    t = args.from_time
    while t <= args.to_time + 1e-9:
        world = []
        for bone in bones:
            local = local_matrix(bone, animation, t)
            parent = bone.get("parent")
            world.append(mul(world[index[parent]], local) if parent else local)
        errors = []
        for path, raw in runtime:
            part = parts_by_path.get(path)
            if part is None or part["name"] not in slots:
                continue
            name = part["name"]
            slot = slots[name]
            att = ((attachments.get(name) or {}).get(slot.get("attachment")) or {})
            verts = att.get("vertices") or []
            uvs = att.get("uvs") or []
            deform_frames = (((animation.get("deform") or {}).get("default") or {})
                             .get(name) or {}).get(slot.get("attachment"))
            deform = deform_at(deform_frames, t) if deform_frames else []
            points = []
            if len(verts) == len(uvs):
                bone = world[index[slot["bone"]]]
                for i in range(0, len(verts), 2):
                    p = apply(bone, verts[i], verts[i + 1])
                    points.append((p[0] / args.unit_k + ox,
                                   p[1] / args.unit_k + oy))
            else:
                i = fi = 0
                while i < len(verts):
                    count = int(verts[i])
                    i += 1
                    x = y = 0.0
                    for _ in range(count):
                        bi = int(verts[i])
                        weight = float(verts[i + 3])
                        vx, vy = verts[i + 1], verts[i + 2]
                        if fi + 1 < len(deform):
                            vx += deform[fi]
                            vy += deform[fi + 1]
                        fi += 2
                        p = apply(world[bi], vx, vy)
                        x += p[0] * weight
                        y += p[1] * weight
                        i += 4
                    points.append((x / args.unit_k + ox,
                                   y / args.unit_k + oy))
            n = min(len(points), len(raw) // 3)
            for k in range(n):
                errors.append(math.hypot(
                    points[k][0] - raw[3 * k],
                    points[k][1] - raw[3 * k + 1]))
        if errors:
            rows.append((statistics.median(errors),
                         statistics.fmean(errors), max(errors), t, len(errors)))
        t += args.step

    rows.sort(key=lambda row: row[1])
    print("runtime_frame=%s runtime_t=%.4f"
          % (target.get("f"), float(target["t"]) - origin))
    print("scan %d candidates")
    for med, mean, mx, t, count in rows[:15]:
        print("t=%7.4f median=%9.5f mean=%9.5f max=%9.5f n=%d"
              % (t, med, mean, mx, count))


if __name__ == "__main__":
    main()
