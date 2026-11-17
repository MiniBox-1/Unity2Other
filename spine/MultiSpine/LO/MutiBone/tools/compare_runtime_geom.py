# -*- coding: utf-8 -*-
"""Compare multi-bone weighted-mesh geometry against one U2SFrameDump frame."""
import argparse
import json
import math
import os
import statistics
import sys

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, os.path.join(LIB, "src"))
sys.path.insert(0, os.path.join(LIB, "tools", "bake_cs"))

from read_framedump import frame_at, load_json, obj_paths, read_dump  # noqa: E402


def sample(keys, t, field, default):
    if not keys:
        return default
    if t <= keys[0]["time"]:
        return float(keys[0].get(field, default))
    if t >= keys[-1]["time"]:
        return float(keys[-1].get(field, default))
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid]["time"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = keys[lo], keys[hi]
    span = b["time"] - a["time"]
    u = 0.0 if span <= 1e-12 else (t - a["time"]) / span
    va = float(a.get(field, default))
    vb = float(b.get(field, default))
    return va + (vb - va) * u


def deform_at(frames, t):
    if not frames:
        return []
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
    av = a.get("vertices") or []
    bv = b.get("vertices") or []
    return [x + (y - x) * u for x, y in zip(av, bv)]


def mul(a, b):
    return (
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[0] * b[4] + a[1] * b[5] + a[4],
        a[2] * b[4] + a[3] * b[5] + a[5],
    )


def local_matrix(bone, animation, t):
    timeline = (animation.get("bones") or {}).get(bone["name"]) or {}
    tx = sample(timeline.get("translate"), t, "x", 0.0)
    ty = sample(timeline.get("translate"), t, "y", 0.0)
    rot = bone.get("rotation", 0.0) + sample(
        timeline.get("rotate"), t, "angle", 0.0)
    # Spine 3.8 ScaleTimeline values are multipliers of setup scale.
    sx = bone.get("scaleX", 1.0) * sample(
        timeline.get("scale"), t, "x", 1.0)
    sy = bone.get("scaleY", 1.0) * sample(
        timeline.get("scale"), t, "y", 1.0)
    angle = math.radians(rot)
    co, si = math.cos(angle), math.sin(angle)
    return (co * sx, -si * sy, si * sx, co * sy,
            bone.get("x", 0.0) + tx, bone.get("y", 0.0) + ty)


def apply(m, x, y):
    return m[0] * x + m[1] * y + m[4], m[2] * x + m[3] * y + m[5]


def attachment_name(animation, slot, default):
    timeline = ((animation.get("slots") or {}).get(slot) or {}).get(
        "attachment")
    if not timeline:
        return default
    if timeline[0]["time"] > 0:
        return default
    value = default
    for frame in timeline:
        if frame["time"] > 0:
            break
        value = frame.get("name")
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("product")
    ap.add_argument("--animation", required=True)
    ap.add_argument("--time", type=float, required=True)
    ap.add_argument("--grep")
    ap.add_argument("--info-dir", help="directory containing _static_info.json")
    ap.add_argument("--unit-k", type=float, default=100.0,
                    help="multi-bone output units per Unity world unit")
    ap.add_argument("--absolute-time", action="store_true",
                    help="treat --time as Unity's absolute Time.time instead of "
                         "seconds from the first recorded frame")
    args = ap.parse_args()

    meta, _ = read_dump(args.dump)
    names = obj_paths(meta)
    first = frame_at(args.dump)
    if first is None:
        raise SystemExit("dump has no frames")
    unity_origin = float(first.get("t", 0.0))
    target_unity_time = (args.time if args.absolute_time
                         else unity_origin + args.time)
    frame = frame_at(args.dump, target_unity_time)
    if frame is None:
        raise SystemExit("frame not found")
    unity_t = float(frame["t"])
    t = unity_t - unity_origin
    info_dir = args.info_dir or args.product
    info = load_json(os.path.join(info_dir, "_static_info.json"))
    js = next(os.path.join(args.product, name)
              for name in os.listdir(args.product)
              if name.endswith("_static.json"))
    skel = load_json(js)
    animation = (skel.get("animations") or {}).get(args.animation) or {}
    bones = skel.get("bones") or []
    index = {bone["name"]: i for i, bone in enumerate(bones)}
    world = []
    for bone in bones:
        local = local_matrix(bone, animation, t)
        parent = bone.get("parent")
        world.append(mul(world[index[parent]], local) if parent else local)
    slots = {slot["name"]: slot for slot in skel.get("slots") or []}
    attachments = ((skel.get("skins") or [{}])[0].get("attachments") or {})
    parts_meta = info.get("partsMeta") or []
    parts_by_path = {}
    for part in parts_meta:
        rel = (part.get("path") or "").replace("\\", "/")
        if "/" in rel:
            rel = rel.split("/", 1)[1]
        parts_by_path[rel] = part
    objects = {obj["i"]: obj for obj in frame.get("obj") or []}
    unit_k = args.unit_k
    ox, oy = (info.get("origin") or [0.0, 0.0])[:2]

    out = []
    for renderer in frame.get("rnd") or []:
        obj = objects.get(renderer.get("o"))
        path = names.get(renderer.get("o"), "")
        if not obj or not path or "v" not in renderer or not renderer.get("vn"):
            continue
        if args.grep and args.grep.lower() not in path.lower():
            continue
        part = parts_by_path.get(path.replace("\\", "/"))
        if part is None:
            continue
        name = part["name"]
        slot = slots.get(name)
        if slot is None:
            continue
        attached = attachment_name(animation, name, slot.get("attachment"))
        if not attached:
            continue
        att = ((attachments.get(name) or {}).get(attached))
        if not att or att.get("type") != "mesh":
            continue
        verts = att.get("vertices") or []
        uvs = att.get("uvs") or []
        deform_frames = (((animation.get("deform") or {}).get("default") or {})
                         .get(name) or {}).get(attached)
        deform = deform_at(deform_frames, t) if deform_frames else []
        points = []
        if len(verts) == len(uvs):
            bone_world = world[index[slot["bone"]]]
            for i in range(0, len(verts), 2):
                p = apply(bone_world, verts[i], verts[i + 1])
                points.append((p[0] / unit_k + ox, p[1] / unit_k + oy))
        else:
            i = 0
            fi = 0
            while i < len(verts):
                count = int(verts[i])
                i += 1
                x = y = 0.0
                for _ in range(count):
                    bi = int(verts[i])
                    weight = float(verts[i + 3])
                    vx = verts[i + 1]
                    vy = verts[i + 2]
                    if fi + 1 < len(deform):
                        vx += deform[fi]
                        vy += deform[fi + 1]
                    fi += 2
                    p = apply(world[bi], vx, vy)
                    x += p[0] * weight
                    y += p[1] * weight
                    i += 4
                points.append((x / unit_k + ox, y / unit_k + oy))
        raw = renderer["v"]
        n = min(len(points), len(raw) // 3)
        if n == 0 or n != int(renderer.get("vn") or 0):
            continue
        errors = [math.hypot(points[k][0] - raw[3 * k],
                             points[k][1] - raw[3 * k + 1])
                  for k in range(n)]
        mean_dx = statistics.fmean(
            points[k][0] - raw[3 * k] for k in range(n))
        mean_dy = statistics.fmean(
            points[k][1] - raw[3 * k + 1] for k in range(n))
        centered = statistics.median(math.hypot(
            points[k][0] - raw[3 * k] - mean_dx,
            points[k][1] - raw[3 * k + 1] - mean_dy) for k in range(n))
        out.append((statistics.median(errors), max(errors), name, n,
                    mean_dx, mean_dy, centered))

    out.sort(reverse=True)
    print("frame=%s unity_t=%.4f anim_t=%.4f matched=%d"
          % (frame.get("f"), unity_t, t, len(out)))
    print("%-46s %4s %10s %10s %10s %10s %10s"
          % ("slot", "n", "median", "max", "mean_dx", "mean_dy", "centered"))
    for med, mx, name, n, mean_dx, mean_dy, centered in out[:30]:
        print("%-46s %4d %10.5f %10.5f %10.5f %10.5f %10.5f"
              % (name, n, med, mx, mean_dx, mean_dy, centered))


if __name__ == "__main__":
    main()
