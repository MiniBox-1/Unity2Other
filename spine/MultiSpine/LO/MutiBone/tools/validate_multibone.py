# -*- coding: utf-8 -*-
"""Validate the structural invariants of generated multi-bone Spine JSON files."""
import argparse
import glob
import json
import os


def json_paths(paths):
    for path in paths:
        if os.path.isdir(path):
            yield from glob.glob(os.path.join(path, "*_static.json"))
        else:
            yield path


def validate(path):
    with open(path, encoding="utf-8") as fp:
        skel = json.load(fp)
    errors = []
    bones = skel.get("bones") or []
    index = {bone["name"]: i for i, bone in enumerate(bones)}
    if len(index) != len(bones):
        errors.append("duplicate bone names: %d names for %d bones" %
                      (len(index), len(bones)))

    roots = [bone["name"] for bone in bones if not bone.get("parent")]
    if len(roots) != 1:
        errors.append("expected 1 root, got %d: %s" % (len(roots), roots))
    for i, bone in enumerate(bones):
        parent = bone.get("parent")
        if parent and (parent not in index or index[parent] >= i):
            errors.append("bone %s has invalid/late parent %s" % (
                bone["name"], parent))

    slot_names = set()
    for slot in skel.get("slots") or []:
        if slot.get("name") in slot_names:
            errors.append("duplicate slot name %s" % slot.get("name"))
        slot_names.add(slot.get("name"))
        if slot.get("bone") not in index:
            errors.append("slot %s references missing bone %s" % (
                slot.get("name"), slot.get("bone")))

    mesh_count = 0
    weighted_points = 0
    deform_lengths = {}
    for skin in skel.get("skins") or []:
        for slot, attachments in (skin.get("attachments") or {}).items():
            for name, att in attachments.items():
                if att.get("type") != "mesh":
                    continue
                mesh_count += 1
                uvs = att.get("uvs") or []
                expected = len(uvs) // 2
                vertices = att.get("vertices") or []
                if len(vertices) == len(uvs):
                    groups = expected
                    deform_lengths[(slot, name)] = len(vertices)
                else:
                    groups = 0
                    influence_count = 0
                    i = 0
                    while i < len(vertices):
                        count = int(vertices[i])
                        i += 1
                        groups += 1
                        if count <= 0 or i + count * 4 > len(vertices):
                            errors.append("%s/%s has truncated vertex group" % (
                                slot, name))
                            break
                        for _ in range(count):
                            bone_index = int(vertices[i])
                            if not (0 <= bone_index < len(bones)):
                                errors.append(
                                    "%s/%s weight references bone %d" % (
                                        slot, name, bone_index))
                            i += 4
                        weighted_points += count
                        influence_count += count
                    deform_lengths[(slot, name)] = influence_count * 2
                if groups != expected:
                    errors.append("%s/%s groups %d != uvs %d" % (
                        slot, name, groups, expected))
                if int(att.get("hull") or 0) > expected:
                    errors.append("%s/%s hull %s > vertices %d" % (
                        slot, name, att.get("hull"), expected))

    for animation, data in (skel.get("animations") or {}).items():
        for bone_name in (data.get("bones") or {}):
            if bone_name not in index:
                errors.append("animation %s references missing bone %s" % (
                    animation, bone_name))
        for skin_name, slots_map in (data.get("deform") or {}).items():
            for slot_name, attachments in (slots_map or {}).items():
                if slot_name not in {s.get("name") for s in (skel.get("slots") or [])}:
                    errors.append("animation %s deform references missing slot %s" % (
                        animation, slot_name))
                for attachment_name, frames in (attachments or {}).items():
                    expected_deform = deform_lengths.get(
                        (slot_name, attachment_name))
                    if expected_deform is None:
                        errors.append(
                            "animation %s deform references missing attachment %s/%s" % (
                                animation, slot_name, attachment_name))
                        continue
                    previous_time = None
                    for frame in frames or []:
                        frame_time = float(frame.get("time", 0.0))
                        if previous_time is not None and frame_time <= previous_time:
                            errors.append(
                                "animation %s deform %s/%s has non-increasing time %s" % (
                                    animation, slot_name, attachment_name,
                                    frame_time))
                        previous_time = frame_time
                        values = frame.get("vertices") or []
                        offset = int(frame.get("offset") or 0)
                        if "offset" in frame:
                            if offset < 0 or offset + len(values) > expected_deform:
                                errors.append(
                                    "animation %s deform %s/%s range %d+%d > %d" % (
                                        animation, slot_name, attachment_name,
                                        offset, len(values), expected_deform))
                        elif len(values) != expected_deform:
                            errors.append(
                                "animation %s deform %s/%s length %d != %d" % (
                                    animation, slot_name, attachment_name,
                                    len(values), expected_deform))

    print("%-58s bones=%-4d slots=%-4d meshes=%-3d roots=%d %s"
          % (os.path.basename(path), len(bones), len(skel.get("slots") or []),
             mesh_count, len(roots), "OK" if not errors else "FAIL"))
    for error in errors[:20]:
        print("  " + error)
    return not errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()
    ok = True
    for path in json_paths(args.paths):
        ok = validate(path) and ok
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
