# -*- coding: utf-8 -*-
"""Compare per-slot world geometry between deform and multi-bone Spine JSON."""
import argparse
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compare_runtime_geom import attachment_name, local_matrix, mul, sample  # noqa: E402


def load_json(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def find_json(directory):
    name = next(name for name in os.listdir(directory)
                if name.endswith("_static.json"))
    return os.path.join(directory, name)


def bone_worlds(skel, animation, t):
    bones = skel.get("bones") or []
    index = {bone["name"]: i for i, bone in enumerate(bones)}
    world = []
    for bone in bones:
        local = local_matrix(bone, animation, t)
        parent = bone.get("parent")
        world.append(mul(world[index[parent]], local) if parent else local)
    return index, world


def apply(m, x, y):
    return m[0] * x + m[1] * y + m[4], m[2] * x + m[3] * y + m[5]


def deform_at(frames, t):
    if not frames:
        return None
    if t <= frames[0]["time"]:
        return frames[0].get("vertices") or []
    if t >= frames[-1]["time"]:
        return frames[-1].get("vertices") or []
    lo, hi = 0, len(frames) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if frames[mid]["time"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = frames[lo], frames[hi]
    span = b["time"] - a["time"]
    u = 0.0 if span <= 1e-12 else (t - a["time"]) / span
    av, bv = a.get("vertices") or [], b.get("vertices") or []
    return [x + (y - x) * u for x, y in zip(av, bv)]


def slot_points(skel, animation, t, slot, attachment):
    index, world = bone_worlds(skel, animation, t)
    att = ((skel.get("skins") or [{}])[0].get("attachments") or {})[slot][attachment]
    vertices = list(att.get("vertices") or [])
    uvs = att.get("uvs") or []
    if len(vertices) == len(uvs):
        offsets = deform_at(
            (((animation.get("deform") or {}).get("default") or {})
             .get(slot) or {}).get(attachment), t)
        if offsets:
            vertices = [a + b for a, b in zip(vertices, offsets)]
        slot_map = {s["name"]: s for s in (skel.get("slots") or [])}
        bone = world[index[slot_map[slot]["bone"]]]
        points = [apply(bone, vertices[i], vertices[i + 1])
                  for i in range(0, len(vertices), 2)]
    else:
        points = []
        i = 0
        while i < len(vertices):
            count = int(vertices[i])
            i += 1
            x = y = 0.0
            for _ in range(count):
                bi = int(vertices[i])
                weight = float(vertices[i + 3])
                p = apply(world[bi], vertices[i + 1], vertices[i + 2])
                x += p[0] * weight
                y += p[1] * weight
                i += 4
            points.append((x, y))
    return points


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deform")
    ap.add_argument("multi")
    ap.add_argument("--animation", required=True)
    ap.add_argument("--time", type=float, required=True)
    ap.add_argument("--a-scale", type=float, default=1.0,
                    help="scale applied to deform geometry before comparison")
    ap.add_argument("--a-offset", type=float, nargs=2, default=(0.0, 0.0))
    ap.add_argument("--no-fit", action="store_true",
                    help="disable global uniform-scale/translation fitting")
    args = ap.parse_args()
    a = load_json(find_json(args.deform))
    b = load_json(find_json(args.multi))
    aa = (a.get("animations") or {}).get(args.animation) or {}
    ba = (b.get("animations") or {}).get(args.animation) or {}
    a_slots = {slot["name"]: slot for slot in a.get("slots") or []}
    b_slots = {slot["name"]: slot for slot in b.get("slots") or []}
    pairs = []
    slots = []
    for name in sorted(set(a_slots) & set(b_slots)):
        an = attachment_name(aa, name, a_slots[name].get("attachment"))
        bn = attachment_name(ba, name, b_slots[name].get("attachment"))
        if not an or not bn:
            continue
        apoints = slot_points(a, aa, args.time, name, an)
        bpoints = slot_points(b, ba, args.time, name, bn)
        if len(apoints) != len(bpoints) or not apoints:
            continue
        slots.append((name, apoints, bpoints))
        pairs.extend(zip(apoints, bpoints))

    a_scale = args.a_scale
    a_offset = list(args.a_offset)
    if pairs and not args.no_fit:
        mx = statistics.fmean(p[0][0] for p in pairs)
        my = statistics.fmean(p[0][1] for p in pairs)
        nx = statistics.fmean(p[1][0] for p in pairs)
        ny = statistics.fmean(p[1][1] for p in pairs)
        den = sum((x - mx) ** 2 + (y - my) ** 2 for (x, y), _ in pairs)
        num = sum((x - mx) * (u - nx) + (y - my) * (v - ny)
                  for (x, y), (u, v) in pairs)
        a_scale = num / den if den > 1e-12 else 1.0
        a_offset = [nx - a_scale * mx, ny - a_scale * my]

    rows = []
    for name, apoints, bpoints in slots:
        apoints = [(x * a_scale + a_offset[0],
                    y * a_scale + a_offset[1])
                   for x, y in apoints]
        errors = [math.hypot(x0 - x1, y0 - y1)
                  for (x0, y0), (x1, y1) in zip(apoints, bpoints)]
        rows.append((statistics.median(errors), max(errors), name,
                     len(errors)))
    rows.sort(reverse=True)
    print("animation=%s t=%.4f matched=%d fit_scale=%.8f offset=(%.4f,%.4f)"
          % (args.animation, args.time, len(rows), a_scale,
             a_offset[0], a_offset[1]))
    print("%-48s %4s %10s %10s %10s"
          % ("slot", "n", "median", "max", "maxWorld"))
    for med, mx, name, n in rows[:35]:
        print("%-48s %4d %10.4f %10.4f %10.4f"
              % (name, n, med, mx, mx / 100.0))


if __name__ == "__main__":
    main()
