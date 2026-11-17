# -*- coding: utf-8 -*-
"""Validate BdOne region-to-mesh products and write a delivery manifest."""

import argparse
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def load_json(path):
    with io.open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def atlas_regions(path):
    names = set()
    for raw in io.open(path, encoding="utf-8-sig"):
        line = raw.rstrip("\r\n")
        if not line or line[0].isspace() or ":" in line:
            continue
        if line.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        names.add(line)
    return names


def find_products(root):
    for dirpath, _, files in os.walk(root):
        if (
                any(name.endswith(".atlas") for name in files)
                and any(name.endswith(".config.json") for name in files)):
            yield dirpath


def main_json(dirpath):
    configs = [
        name for name in os.listdir(dirpath)
        if name.endswith(".config.json") and not name.startswith("_")
    ]
    if len(configs) != 1:
        raise RuntimeError("expected one config JSON, got %r" % configs)
    config = load_json(os.path.join(dirpath, configs[0]))
    name = config.get("skeleton")
    if not name or not os.path.isfile(os.path.join(dirpath, name)):
        raise RuntimeError(
            "config references missing skeleton JSON %r" % name)
    return name


def validate_product(dirpath):
    errors = []
    json_name = main_json(dirpath)
    base = os.path.splitext(json_name)[0]
    atlas_path = os.path.join(dirpath, base + ".atlas")
    skel_path = os.path.join(dirpath, base + ".skel")
    for path, label in ((atlas_path, "atlas"), (skel_path, "skel")):
        if not os.path.isfile(path):
            errors.append("missing %s: %s" % (label, os.path.basename(path)))

    skeleton = load_json(os.path.join(dirpath, json_name))
    info_path = os.path.join(dirpath, "_bdone_info.json")
    info = load_json(info_path) if os.path.isfile(info_path) else {}
    regions = atlas_regions(atlas_path) if os.path.isfile(atlas_path) else set()
    bones = skeleton.get("bones") or []
    slots = skeleton.get("slots") or []
    bone_index = {bone.get("name"): i for i, bone in enumerate(bones)}
    slot_names = {slot.get("name") for slot in slots}

    if len(bone_index) != len(bones):
        errors.append("duplicate bone names")
    if not bones:
        errors.append("no bones")
    else:
        roots = [bone.get("name") for bone in bones if not bone.get("parent")]
        if len(roots) != 1:
            errors.append("expected one root, got %d" % len(roots))
        for i, bone in enumerate(bones):
            parent = bone.get("parent")
            if parent and (
                    parent not in bone_index or bone_index[parent] >= i):
                errors.append("%s has invalid parent %s" % (
                    bone.get("name"), parent))

    if len(slot_names) != len(slots):
        errors.append("duplicate slot names")
    for slot in slots:
        if slot.get("bone") not in bone_index:
            errors.append("slot %s references missing bone %s" % (
                slot.get("name"), slot.get("bone")))

    mesh_count = 0
    rigid_mesh_count = 0
    existing_mesh_count = 0
    weighted_count = 0
    for skin in skeleton.get("skins") or []:
        for slot_name, attachments in (
                skin.get("attachments") or {}).items():
            if slot_name not in slot_names:
                errors.append("attachment references missing slot " + slot_name)
            for att_name, attachment in (attachments or {}).items():
                if not attachment.get("type"):
                    errors.append("%s/%s is still an implicit region" % (
                        slot_name, att_name))
                    continue
                if attachment.get("type") != "mesh":
                    errors.append("%s/%s is not mesh" % (
                        slot_name, att_name))
                    continue
                mesh_count += 1
                path = attachment.get("path") or att_name
                if regions and path not in regions:
                    errors.append("%s/%s missing atlas region %s" % (
                        slot_name, att_name, path))
                uvs = attachment.get("uvs") or []
                vertices = attachment.get("vertices") or []
                triangles = attachment.get("triangles") or []
                if not uvs or len(uvs) % 2:
                    errors.append("%s/%s has invalid UV payload" % (
                        slot_name, att_name))
                    continue
                vertex_count = 0
                influences = 0
                if len(vertices) == len(uvs):
                    vertex_count = len(uvs) // 2
                    influences = vertex_count
                else:
                    cursor = 0
                    while cursor < len(vertices):
                        count = vertices[cursor]
                        cursor += 1
                        if (
                                not isinstance(count, int)
                                or count <= 0
                                or cursor + count * 4 > len(vertices)):
                            errors.append("%s/%s has truncated weights" % (
                                slot_name, att_name))
                            break
                        for _ in range(count):
                            bone_pos = vertices[cursor]
                            if (
                                    not isinstance(bone_pos, int)
                                    or not 0 <= bone_pos < len(bones)):
                                errors.append(
                                    "%s/%s weight references bone %r" % (
                                        slot_name, att_name, bone_pos))
                            if not all(math.isfinite(float(value))
                                       for value in vertices[
                                           cursor + 1:cursor + 4]):
                                errors.append(
                                    "%s/%s has non-finite weight data" % (
                                        slot_name, att_name))
                            cursor += 4
                            influences += 1
                        vertex_count += 1
                if not triangles:
                    errors.append("%s/%s has no triangles" % (
                        slot_name, att_name))
                for triangle in triangles:
                    if not isinstance(triangle, int) or not (
                            0 <= triangle < vertex_count):
                        errors.append("%s/%s triangle index is invalid" % (
                            slot_name, att_name))
                        break
                hull = int(attachment.get("hull") or 0)
                if hull > vertex_count:
                    errors.append("%s/%s hull %d > vertices %d" % (
                        slot_name, att_name, hull, vertex_count))
                weighted_count += influences
                rigid = (
                    len(vertices) == 20
                    and uvs == [
                        0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
                    and triangles == [0, 1, 2, 0, 2, 3]
                    and attachment.get("hull") == 4
                    and all(
                        vertices[index * 5] == 1
                        and vertices[index * 5 + 4] == 1.0
                        for index in range(4))
                )
                if rigid:
                    rigid_mesh_count += 1
                else:
                    existing_mesh_count += 1

    if info and mesh_count != int(info.get("slots") or 0):
        errors.append("mesh count %d != source metadata slots %d" % (
            mesh_count, int(info.get("slots") or 0)))
    if info and len(bones) != int(info.get("bones") or 0):
        errors.append("bone count %d != source metadata bones %d" % (
            len(bones), int(info.get("bones") or 0)))

    config_candidates = [
        name for name in os.listdir(dirpath)
        if name.endswith(".config.json") and not name.startswith("_")
    ]
    if len(config_candidates) != 1:
        errors.append("expected one *.config.json, got %r" %
                      config_candidates)
    else:
        config = load_json(os.path.join(dirpath, config_candidates[0]))
        configured_skeleton = config.get("skeleton")
        if configured_skeleton != json_name:
            errors.append("config skeleton %r != %r" % (
                configured_skeleton, json_name))
        configured_atlas = (config.get("atlases") or [{}])[0].get("atlas")
        if configured_atlas != os.path.basename(atlas_path):
            errors.append("config atlas %r != %r" % (
                configured_atlas, os.path.basename(atlas_path)))
        textures = (config.get("atlases") or [{}])[0].get("textures") or []
        if not textures:
            errors.append("config has no textures")
        for texture in textures:
            if not os.path.isfile(os.path.join(dirpath, texture)):
                errors.append("config texture missing: " + texture)

    for animation_name, animation in (
            skeleton.get("animations") or {}).items():
        for bone_name, timelines in (animation.get("bones") or {}).items():
            if bone_name not in bone_index:
                errors.append("%s references missing bone %s" % (
                    animation_name, bone_name))
            for key in ("rotate", "translate", "scale", "shear"):
                times = [float(frame.get("time", 0.0))
                         for frame in (timelines.get(key) or [])]
                if times != sorted(times):
                    errors.append("%s/%s/%s times are not sorted" % (
                        animation_name, bone_name, key))
        for slot_name, timelines in (animation.get("slots") or {}).items():
            if slot_name not in slot_names:
                errors.append("%s references missing slot %s" % (
                    animation_name, slot_name))
            for key in ("attachment", "color", "twoColor"):
                times = [float(frame.get("time", 0.0))
                         for frame in (timelines.get(key) or [])]
                if times != sorted(times):
                    errors.append("%s/%s/%s times are not sorted" % (
                        animation_name, slot_name, key))

    return {
        "path": dirpath,
        "character": os.path.basename(os.path.dirname(dirpath)),
        "product": os.path.basename(dirpath),
        "clip": (info.get("clip") or {}).get("file"),
        "duration": (info.get("clip") or {}).get("duration"),
        "bones": len(bones),
        "slots": len(slots),
        "meshes": mesh_count,
        "rigidMeshes": rigid_mesh_count,
        "existingMeshes": existing_mesh_count,
        "weightedVertices": weighted_count,
        "animations": sorted((skeleton.get("animations") or {}).keys()),
        "skelBytes": os.path.getsize(skel_path)
        if os.path.isfile(skel_path) else 0,
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root",
        nargs="?",
        default=os.path.join(
            BASE, "MultiSpine", "BD", "Products", "Current"))
    args = parser.parse_args(argv)

    products = []
    for dirpath in sorted(find_products(args.root)):
        try:
            products.append(validate_product(dirpath))
        except Exception as exc:  # noqa: BLE001
            products.append({
                "path": dirpath,
                "character": os.path.basename(os.path.dirname(dirpath)),
                "product": os.path.basename(dirpath),
                "errors": [str(exc)],
            })

    failures = [product for product in products if product["errors"]]
    manifest = {
        "generator": "validate_bd_mesh.py",
        "source": os.path.join(
            BASE, "SingleSpine", "BD", "Products", "_bdone_spine"),
        "root": args.root,
        "products": len(products),
        "characters": len({product["character"] for product in products}),
        "bones": sum(product.get("bones", 0) for product in products),
        "slots": sum(product.get("slots", 0) for product in products),
        "meshes": sum(product.get("meshes", 0) for product in products),
        "rigidMeshes": sum(
            product.get("rigidMeshes", 0) for product in products),
        "existingMeshes": sum(
            product.get("existingMeshes", 0) for product in products),
        "weightedVertices": sum(
            product.get("weightedVertices", 0) for product in products),
        "failed": len(failures),
        "items": products,
    }
    manifest_path = os.path.join(args.root, "manifest.json")
    with io.open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    for product in products:
        status = "PASS" if not product["errors"] else "FAIL"
        print("%-4s %-48s bones=%-4d slots=%-4d "
              "meshes=%-4d rigid=%-4d existing=%-3d" % (
            status,
            product["character"] + "/" + product["product"],
            product.get("bones", 0),
            product.get("slots", 0),
            product.get("meshes", 0),
            product.get("rigidMeshes", 0),
            product.get("existingMeshes", 0)))
        for error in product["errors"][:10]:
            print("     " + error)
    print("BD_MESH_VALIDATE products=%d characters=%d bones=%d slots=%d "
          "meshes=%d rigid=%d existing=%d failures=%d" % (
              manifest["products"], manifest["characters"],
              manifest["bones"], manifest["slots"], manifest["meshes"],
              manifest["rigidMeshes"], manifest["existingMeshes"],
              manifest["failed"]))
    print("manifest:", manifest_path)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
