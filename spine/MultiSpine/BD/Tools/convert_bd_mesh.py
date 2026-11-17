# -*- coding: utf-8 -*-
"""Convert BdOne region attachments to rigid per-bone weighted meshes.

The source products keep the complete NGUI node hierarchy as Spine bones.
This branch changes each UISprite region attachment into a four-corner
weighted mesh rigidly bound to that sprite's own node bone. It is a true
multi-bone skeleton while preserving the existing animation timelines.
"""

import argparse
import io
import json
import math
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SHARED = os.path.join(BASE, "SingleSpine", "Shared")
SRC = os.path.join(SHARED, "Unity2Spine", "src")
DEFAULT_INPUT = os.path.join(
    BASE, "SingleSpine", "BD", "Products", "_bdone_spine")
DEFAULT_OUTPUT = os.path.join(
    BASE, "MultiSpine", "BD", "Products", "Current")

if SRC not in sys.path:
    sys.path.insert(0, SRC)

from unity2spine.spine import spine38_binary_writer as BW  # noqa: E402


def load_json(path):
    with io.open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def parse_atlas(path):
    """Return region name -> page metadata from a Spine 3.8 atlas."""
    result = {}
    page = None
    page_size = None
    page_sizes = {}
    current = None
    for raw in io.open(path, encoding="utf-8-sig"):
        line = raw.rstrip("\r\n")
        if not line.strip():
            page = None
            page_size = None
            current = None
            continue
        if not line.startswith(" "):
            name = line.strip()
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                page = name
                page_size = None
                current = None
            elif ":" in name:
                key, _, value = name.partition(":")
                if key == "size" and page is not None:
                    page_size = tuple(
                        int(part.strip()) for part in value.split(","))
                    page_sizes[page] = page_size
            else:
                current = {"page": page, "rotate": False}
                result[name] = current
            continue
        if current is None or page is None:
            continue
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        value = value.strip()
        if key == "size" and current is None:
            page_size = tuple(
                int(part.strip()) for part in value.split(","))
            page_sizes[page] = page_size
            continue
        if key == "rotate":
            current["rotate"] = value.lower() == "true"
            continue
        if key == "xy":
            x, y = [int(part.strip()) for part in value.split(",")]
            current["x"], current["y"] = x, y
        elif key == "size":
            width, height = [int(part.strip()) for part in value.split(",")]
            current["width"], current["height"] = width, height
    for name, meta in result.items():
        size = page_sizes.get(meta["page"])
        if size:
            meta["pageWidth"], meta["pageHeight"] = size
    return result


def region_to_mesh(att, bone_index, meta):
    x = float(att.get("x", 0.0))
    y = float(att.get("y", 0.0))
    width = float(att.get("width", meta["width"]))
    height = float(att.get("height", meta["height"]))
    # Spine JSON's region rotation rotates the centered local rectangle
    # before translating it by the attachment x/y offset.
    angle = math.radians(-float(att.get("rotation", 0.0)))
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    corners = [
        (-width * 0.5, -height * 0.5),
        (width * 0.5, -height * 0.5),
        (width * 0.5, height * 0.5),
        (-width * 0.5, height * 0.5),
    ]
    local = []
    for corner_x, corner_y in corners:
        rotated_x = corner_x * cos_angle - corner_y * sin_angle
        rotated_y = corner_x * sin_angle + corner_y * cos_angle
        local.append((x + rotated_x, y + rotated_y))
    vertices = []
    for lx, ly in local:
        vertices.extend([1, bone_index, round(lx, 6), round(ly, 6), 1.0])
    return {
        "type": "mesh",
        "path": att.get("path") or meta["path"],
        # Spine 3.8 calls these region UVs. updateUVs() maps 0..1 through
        # the atlas region's page offset; page-absolute UVs would be shifted
        # a second time and sample unrelated parts.
        "uvs": [0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
        "triangles": [0, 1, 2, 0, 2, 3],
        "vertices": vertices,
        "hull": 4,
    }


def convert_product(src_dir, dst_dir):
    config_name = next(
        name for name in os.listdir(src_dir)
        if name.endswith(".config.json") and not name.startswith("_"))
    config = load_json(os.path.join(src_dir, config_name))
    json_name = config.get("skeleton")
    if not json_name or not os.path.isfile(os.path.join(src_dir, json_name)):
        raise RuntimeError(
            "config skeleton missing in %s: %r" % (src_dir, json_name))
    atlas_name = next(
        name for name in os.listdir(src_dir) if name.endswith(".atlas")
    )
    source = load_json(os.path.join(src_dir, json_name))
    atlas = parse_atlas(os.path.join(src_dir, atlas_name))
    bone_index = {
        bone["name"]: index for index, bone in enumerate(source.get("bones") or [])
    }
    slot_by_name = {
        slot["name"]: slot for slot in source.get("slots") or []
    }
    converted = 0
    for slot_name, attachments in (
            (source.get("skins") or [{}])[0].get("attachments") or {}).items():
        slot = slot_by_name.get(slot_name) or {}
        bone_name = slot.get("bone")
        if bone_name not in bone_index:
            continue
        for att_name, attachment in list(attachments.items()):
            # In Spine JSON, an omitted attachment type means region.
            if attachment.get("type") not in (None, "region"):
                continue
            region_name = (
                attachment.get("path")
                or attachment.get("name")
                or att_name
            )
            meta = atlas.get(region_name)
            if not meta:
                raise RuntimeError(
                    "atlas region missing: %s in %s" % (region_name, src_dir))
            meta = dict(meta)
            meta["path"] = region_name
            attachments[att_name] = region_to_mesh(
                attachment, bone_index[bone_name], meta)
            converted += 1

    os.makedirs(dst_dir, exist_ok=True)
    dst_json = os.path.join(dst_dir, json_name)
    with io.open(dst_json, "w", encoding="utf-8") as handle:
        json.dump(source, handle, ensure_ascii=False, separators=(",", ":"))
    for name in os.listdir(src_dir):
        if name == json_name:
            continue
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
    skel_name = os.path.splitext(json_name)[0] + ".skel"
    canonical_config = os.path.splitext(json_name)[0] + ".config.json"
    if config_name != canonical_config:
        with io.open(os.path.join(dst_dir, canonical_config),
                     "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
        stale_config = os.path.join(dst_dir, config_name)
        if os.path.isfile(stale_config):
            os.remove(stale_config)
    BW.convert_file(dst_json, os.path.join(dst_dir, skel_name))
    return converted


def iter_products(root):
    for dirpath, _, files in os.walk(root):
        if not any(name.endswith(".atlas") for name in files):
            continue
        if not any(
                name.endswith(".config.json") and not name.startswith("_")
                for name in files):
            continue
        yield dirpath


def product_relpath(src, root):
    """Keep normal character/product nesting and normalize merged examples."""
    rel = os.path.relpath(src, root)
    if "_bdone_info.json" in os.listdir(src):
        return rel
    config_name = next(
        name for name in os.listdir(src)
        if name.endswith(".config.json") and not name.startswith("_"))
    config = load_json(os.path.join(src, config_name))
    skeleton_name = config.get("skeleton")
    if not skeleton_name:
        raise RuntimeError("config has no skeleton: %s" % config_name)
    product_name = os.path.splitext(skeleton_name)[0]
    return os.path.join(os.path.basename(os.path.normpath(src)), product_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=DEFAULT_INPUT)
    parser.add_argument("--out", default=DEFAULT_OUTPUT)
    parser.add_argument("--only", default="",
                        help="comma-separated character/costume name filters")
    args = parser.parse_args()
    filters = [
        value.strip().casefold()
        for value in args.only.split(",") if value.strip()
    ]
    products = list(iter_products(args.source))
    rows = []
    for src in sorted(products):
        rel = product_relpath(src, args.source)
        if filters and not any(token in rel.casefold() for token in filters):
            continue
        dst = os.path.join(args.out, rel)
        converted = convert_product(src, dst)
        rows.append({
            "source": src,
            "output": dst,
            "meshAttachments": converted,
        })
        print("MESH %-48s %d" % (rel, converted), flush=True)
    os.makedirs(args.out, exist_ok=True)
    with io.open(os.path.join(args.out, "convert_mesh_summary.json"),
                 "w", encoding="utf-8") as handle:
        json.dump({"products": rows}, handle, ensure_ascii=False, indent=2)
    print("BD_MESH_DONE products=%d" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
