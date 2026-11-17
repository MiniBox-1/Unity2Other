# -*- coding: utf-8 -*-
"""Validate static *.Lihui presentations converted to Spine 3.8."""

import argparse
import io
import json
import math
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DEFAULT_ROOT = os.path.join(BASE, "StaticSpine", "LO", "Products",
                            "Prototype")


def load_json(path):
    with io.open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def find_main_json(dirpath):
    names = [
        name for name in os.listdir(dirpath)
        if name.endswith(".json")
        and not name.endswith(".config.json")
        and not name.startswith("_")
    ]
    if len(names) != 1:
        raise RuntimeError("expected one skeleton JSON, got %r" % names)
    return names[0]


def validate_product(dirpath):
    errors = []
    json_name = find_main_json(dirpath)
    base = os.path.splitext(json_name)[0]
    atlas_name = base + ".atlas"
    skel_name = base + ".skel"
    config_name = base + ".config.json"
    for name, label in (
            (atlas_name, "atlas"), (skel_name, "skel"),
            (config_name, "config")):
        if not os.path.isfile(os.path.join(dirpath, name)):
            errors.append("missing %s: %s" % (label, name))

    skeleton = load_json(os.path.join(dirpath, json_name))
    bones = skeleton.get("bones") or []
    slots = skeleton.get("slots") or []
    bone_names = [bone.get("name") for bone in bones]
    bone_index = {name: index for index, name in enumerate(bone_names)}
    if len(bone_index) != len(bone_names):
        errors.append("duplicate bone names")
    roots = [bone for bone in bones if not bone.get("parent")]
    if len(roots) != 1:
        errors.append("expected one root, got %d" % len(roots))
    for index, bone in enumerate(bones):
        parent = bone.get("parent")
        if parent and (
                parent not in bone_index or bone_index[parent] >= index):
            errors.append("%s has invalid parent %s" % (
                bone.get("name"), parent))

    slot_names = [slot.get("name") for slot in slots]
    if len(set(slot_names)) != len(slot_names):
        errors.append("duplicate slot names")
    attachments = {}
    for skin in skeleton.get("skins") or []:
        for slot_name, values in (
                skin.get("attachments") or {}).items():
            attachments.update(values or {})
    enabled_slots = []
    for slot in slots:
        name = slot.get("name")
        if slot.get("bone") not in bone_index:
            errors.append("slot %s references missing bone" % name)
        attachment_name = slot.get("attachment")
        if not attachment_name:
            errors.append("slot %s is not enabled by default" % name)
            continue
        enabled_slots.append(name)
        attachment = attachments.get(attachment_name)
        if not attachment:
            errors.append("slot %s references missing attachment" % name)
            continue
        if attachment.get("type") != "mesh":
            errors.append("attachment %s is not mesh" % attachment_name)
            continue
        uvs = attachment.get("uvs") or []
        vertices = attachment.get("vertices") or []
        triangles = attachment.get("triangles") or []
        if not uvs or len(uvs) % 2:
            errors.append("attachment %s has invalid UVs" % attachment_name)
        if len(vertices) != len(uvs):
            errors.append(
                "attachment %s is not a flat non-weighted mesh" %
                attachment_name)
        vertex_count = len(uvs) // 2
        if not triangles:
            errors.append("attachment %s has no triangles" % attachment_name)
        for triangle in triangles:
            if not isinstance(triangle, int) or not (
                    0 <= triangle < vertex_count):
                errors.append(
                    "attachment %s has invalid triangle index" %
                    attachment_name)
                break
        for value in uvs + vertices:
            if not math.isfinite(float(value)):
                errors.append("attachment %s has non-finite data" %
                              attachment_name)
                break

    if os.path.isfile(os.path.join(dirpath, config_name)):
        config = load_json(os.path.join(dirpath, config_name))
        if config.get("skeleton") != json_name:
            errors.append("config skeleton does not match")
        atlas_entries = config.get("atlases") or []
        if not atlas_entries:
            errors.append("config has no atlas")
        for entry in atlas_entries:
            if entry.get("atlas") != atlas_name:
                errors.append("config atlas does not match")
            for texture in entry.get("textures") or []:
                if not os.path.isfile(os.path.join(dirpath, texture)):
                    errors.append("config texture missing: " + texture)

    return {
        "path": dirpath,
        "product": os.path.basename(dirpath),
        "bones": len(bones),
        "slots": len(slots),
        "enabledSlots": enabled_slots,
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=DEFAULT_ROOT)
    args = parser.parse_args(argv)

    products = []
    for name in sorted(os.listdir(args.root)):
        dirpath = os.path.join(args.root, name)
        if not os.path.isdir(dirpath):
            continue
        try:
            products.append(validate_product(dirpath))
        except Exception as exc:  # noqa: BLE001
            products.append({
                "path": dirpath,
                "product": name,
                "bones": 0,
                "slots": 0,
                "enabledSlots": [],
                "errors": [str(exc)],
            })

    failures = [item for item in products if item["errors"]]
    manifest = {
        "generator": "validate_lihui_static.py",
        "root": args.root,
        "products": len(products),
        "bones": sum(item["bones"] for item in products),
        "slots": sum(item["slots"] for item in products),
        "failed": len(failures),
        "items": products,
    }
    with io.open(os.path.join(args.root, "manifest.json"),
                 "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    for item in products:
        print("%-4s %-44s bones=%-3d slots=%-3d [%s]" % (
            "PASS" if not item["errors"] else "FAIL",
            item["product"], item["bones"], item["slots"],
            ", ".join(item["enabledSlots"])))
        for error in item["errors"][:10]:
            print("     " + error)
    print("LIHUI_VALIDATE products=%d bones=%d slots=%d failures=%d" % (
        manifest["products"], manifest["bones"], manifest["slots"],
        manifest["failed"]))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
