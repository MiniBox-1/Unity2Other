# -*- coding: utf-8 -*-
"""Convert Mobile-old *.Lihui prefabs into static multi-slot Spine skeletons.

The source prefab hierarchy becomes the Spine bone hierarchy and every
SpriteRenderer becomes a slot whose setup attachment is enabled by default.
This deliberately bypasses the Animator requirement used by the animated
2DModel converter.
"""

import argparse
import gc
import io
import json
import math
import os
import shutil
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SRC = os.path.join(BASE, "SingleSpine", "Shared", "Unity2Spine", "src")
ASSETS_DEFAULT = os.environ.get(
    "U2S_LO_ASSETS",
    r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets")
PREFABS_DEFAULT = (
    os.environ.get("U2S_LO_PREFABS")
    or os.path.join(ASSETS_DEFAULT, "Prefabs"))
OUT_DEFAULT = os.path.join(BASE, "StaticSpine", "LO", "Products", "Current")

if SRC not in sys.path:
    sys.path.insert(0, SRC)

from unity2spine.convert import convert_2dmodel as convert_2dmodel_module  # noqa: E402
from unity2spine.convert.convert_2dmodel import build_character_model  # noqa: E402
from unity2spine.spine.spine38_binary_writer import (  # noqa: E402
    convert_file as write_skel)
from unity2spine.spine.spine_out import (  # noqa: E402
    atlas_text, fnum, write_viewer_config)
from unity2spine.unity.unity_anim2d import quat_to_euler  # noqa: E402


def unique_name(base, used):
    name = base or "unnamed"
    candidate = name
    index = 2
    while candidate in used:
        candidate = "%s_%02d" % (name, index)
        index += 1
    used.add(candidate)
    return candidate


def mat2_point(matrix, point):
    a, b, c, d, tx, ty = matrix
    x, y = point
    return (a * x + b * y + tx, c * x + d * y + ty)


def mat2_mul(parent, child):
    pa, pb, pc, pd, ptx, pty = parent
    ca, cb, cc, cd, ctx, cty = child
    return (
        pa * ca + pb * cc,
        pa * cb + pb * cd,
        pc * ca + pd * cc,
        pc * cb + pd * cd,
        pa * ctx + pb * cty + ptx,
        pc * ctx + pd * cty + pty,
    )


def local_matrix(transform):
    euler = quat_to_euler(tuple(transform.get("quat") or (0, 0, 0, 1)))
    rotation = math.radians(float(euler[2]))
    scale = list(transform.get("scale") or (1, 1, 1))
    pos = list(transform.get("pos") or (0, 0, 0))
    cos_r, sin_r = math.cos(rotation), math.sin(rotation)
    return (
        cos_r * float(scale[0]),
        -sin_r * float(scale[1]),
        sin_r * float(scale[0]),
        cos_r * float(scale[1]),
        float(pos[0]),
        float(pos[1]),
    ), euler


def ordered_transform_ids(transforms):
    order = []
    seen = set()

    def visit(tfid):
        if tfid in seen or tfid not in transforms:
            return
        seen.add(tfid)
        order.append(tfid)
        for child in transforms[tfid].get("kids") or []:
            visit(child)

    for tfid, transform in transforms.items():
        if not transform.get("father"):
            visit(tfid)
    for tfid in transforms:
        visit(tfid)
    return order


def max_world_span(parts, bone_matrices):
    xs, ys = [], []
    for part in parts:
        matrix = bone_matrices.get(part.tfid)
        if not matrix:
            continue
        for point in part.mesh.get("positions") or []:
            x, y = mat2_point(matrix, point[:2])
            xs.append(x)
            ys.append(y)
    if not xs or not ys:
        return 1.0
    return max(max(xs) - min(xs), max(ys) - min(ys))


def convert_prefab(prefab, assets, out_root, flip_v=False):
    model, parsed_parts = build_character_model(prefab, assets)
    if not parsed_parts:
        raise RuntimeError("no drawable parts: " + prefab)

    renderer_by_tfid = {
        renderer.get("tfid"): renderer for renderer in model.renderers
    }
    skipped = []

    def is_visible_part(part):
        renderer = renderer_by_tfid.get(part.tfid) or {}
        alpha = float((part.color or {}).get("a", 1.0))
        if not renderer.get("enabled", True):
            skipped.append((part, "renderer disabled"))
            return False
        if not renderer.get("activeInHierarchy", True):
            skipped.append((part, "gameobject inactive"))
            return False
        if alpha <= 1e-6:
            skipped.append((part, "alpha zero"))
            return False
        return True

    parts = [
        part for part in parsed_parts
        if part.mesh and part.texture_path
        and part.mesh.get("positions") and part.mesh.get("uvs")
        and part.mesh.get("triangles")
        and is_visible_part(part)
    ]
    if not parts:
        raise RuntimeError("no drawable sprites with meshes: " + prefab)
    parts.sort(key=lambda part: (
        int(part.sorting_order or 0),
        int(getattr(part, "order", 0) or 0),
    ))

    base = os.path.splitext(os.path.basename(prefab))[0]
    out_dir = os.path.join(out_root, base)
    os.makedirs(out_dir, exist_ok=True)

    transform_ids = ordered_transform_ids(model.transforms)
    used_bones = set()
    bone_name_by_tfid = {}
    bones = []
    bone_matrices = {}
    warnings = []
    for tfid in transform_ids:
        transform = model.transforms[tfid]
        bone_name = unique_name(
            model.gameobjects.get(transform.get("go"), {}).get("name")
            or transform.get("name"),
            used_bones)
        bone_name_by_tfid[tfid] = bone_name
        matrix, euler = local_matrix(transform)
        if abs(float(euler[0])) > 1e-4 or abs(float(euler[1])) > 1e-4:
            warnings.append(
                "%s has off-plane rotation x=%.6f y=%.6f" %
                (bone_name, float(euler[0]), float(euler[1])))
        father = transform.get("father")
        bone = {
            "name": bone_name,
            "length": 0,
            "x": fnum(float(transform["pos"][0])),
            "y": fnum(float(transform["pos"][1])),
            "rotation": fnum(float(euler[2])),
            "scaleX": fnum(float(transform["scale"][0])),
            "scaleY": fnum(float(transform["scale"][1])),
        }
        if father in bone_name_by_tfid:
            bone["parent"] = bone_name_by_tfid[father]
            bone_matrices[tfid] = mat2_mul(
                bone_matrices[father], matrix)
        else:
            bone_matrices[tfid] = matrix
        bones.append(bone)

    texture_paths = []
    for part in parts:
        if part.texture_path not in texture_paths:
            texture_paths.append(part.texture_path)
    page_names = [base + "_%d" % i for i in range(len(texture_paths))]
    pages = []
    for index, texture_path in enumerate(texture_paths):
        from PIL import Image
        width, height = Image.open(texture_path).size
        page_name = page_names[index]
        shutil.copy2(
            texture_path, os.path.join(out_dir, page_name + ".png"))
        pages.append({
            "file": page_name + ".png",
            "size": (width, height),
            "regions": [(
                "tex%d" % index,
                {"x": 0, "y": 0, "width": width, "height": height},
            )],
        })

    slots = []
    attachments = {}
    used_slots = set()
    part_rows = []
    for part in parts:
        transform = model.transforms[part.tfid]
        source_name = (
            model.gameobjects.get(transform.get("go"), {}).get("name")
            or transform.get("name")
            or part.name)
        slot_name = unique_name(source_name, used_slots)
        tex_index = texture_paths.index(part.texture_path)
        positions = part.mesh.get("positions") or []
        uvs = part.mesh.get("uvs") or []
        vertices = []
        for position in positions:
            vertices.extend([
                fnum(float(position[0])),
                fnum(float(position[1])),
            ])
        mesh_uvs = []
        for u, v in uvs:
            mesh_uvs.extend([
                fnum(float(u)),
                fnum(1.0 - float(v) if flip_v else float(v)),
            ])
        attachment = {
            "type": "mesh",
            "path": "tex%d" % tex_index,
            "uvs": mesh_uvs,
            "triangles": [int(value) for value in part.mesh["triangles"]],
            "vertices": vertices,
            "hull": len(positions),
            "width": 1,
            "height": 1,
        }
        attachments[slot_name] = {slot_name: attachment}
        slots.append({
            "name": slot_name,
            "bone": bone_name_by_tfid[part.tfid],
            "color": "ffffffff",
            "attachment": slot_name,
        })
        part_rows.append({
            "slot": slot_name,
            "bone": bone_name_by_tfid[part.tfid],
            "source": part.texture_path,
            "sortingOrder": int(part.sorting_order or 0),
            "vertices": len(positions),
            "triangles": len(attachment["triangles"]) // 3,
            "defaultEnabled": True,
        })

    data = {
        "skeleton": {
            "hash": "unity2spine-lihui-" + base,
            "spine": "3.8.99",
            "x": 0,
            "y": 0,
            "width": 0,
            "height": 0,
            "fps": 60,
        },
        "bones": bones,
        "slots": slots,
        "skins": [{"name": "default", "attachments": attachments}],
        "animations": {"idle": {}},
    }
    json_path = os.path.join(out_dir, base + ".json")
    atlas_path = os.path.join(out_dir, base + ".atlas")
    skel_path = os.path.join(out_dir, base + ".skel")
    with io.open(json_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    with io.open(atlas_path, "w", encoding="utf-8") as handle:
        handle.write(atlas_text(pages))
    write_skel(json_path, skel_path)

    span = max_world_span(parts, bone_matrices)
    scale_factor = max(0.01, min(10000.0, round(100.0 / span, 1)))
    config_path = write_viewer_config(
        out_dir, data, os.path.basename(json_path),
        os.path.basename(atlas_path), page_names,
        scale_factor=scale_factor, override_scale=True)

    info = {
        "sourcePrefab": prefab,
        "output": out_dir,
        "skeleton": os.path.basename(json_path),
        "skel": os.path.basename(skel_path),
        "atlas": os.path.basename(atlas_path),
        "config": os.path.basename(config_path),
        "bones": len(bones),
        "slots": len(slots),
        "textures": len(texture_paths),
        "parts": part_rows,
        "skippedParts": [
            {
                "name": part.name,
                "reason": reason,
            }
            for part, reason in skipped
        ],
        "warnings": warnings,
    }
    with io.open(os.path.join(out_dir, "_lihui_info.json"),
                 "w", encoding="utf-8") as handle:
        json.dump(info, handle, ensure_ascii=False, indent=2)
    return info


def write_summary(out_root, rows, failures):
    os.makedirs(out_root, exist_ok=True)
    path = os.path.join(out_root, "convert_lihui_summary.json")
    temporary = path + ".tmp"
    with io.open(temporary, "w", encoding="utf-8") as handle:
        json.dump({
            "products": rows,
            "failures": failures,
            "counts": {
                "success": len(rows),
                "failed": len(failures),
            },
        }, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def existing_info(prefab, out_root):
    base = os.path.splitext(os.path.basename(prefab))[0]
    out_dir = os.path.join(out_root, base)
    info_path = os.path.join(out_dir, "_lihui_info.json")
    if not os.path.isfile(info_path):
        return None
    info = json.load(io.open(info_path, encoding="utf-8-sig"))
    required = (
        info.get("skeleton"), info.get("skel"), info.get("atlas"),
        info.get("config"))
    if not all(name and os.path.isfile(os.path.join(out_dir, name))
               for name in required):
        return None
    return info


def collect_prefabs(scan_root):
    prefabs = []
    for dirpath, _, files in os.walk(scan_root):
        for name in files:
            if name.endswith(".Lihui.prefab"):
                prefabs.append(os.path.join(dirpath, name))
    return sorted(prefabs)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "prefabs", nargs="*", help="one or more *.Lihui.prefab paths")
    parser.add_argument("--assets", default=ASSETS_DEFAULT)
    parser.add_argument("--out-root", default=OUT_DEFAULT)
    parser.add_argument("--scan-root", default=PREFABS_DEFAULT)
    parser.add_argument(
        "--all", action="store_true",
        help="scan --scan-root recursively for *.Lihui.prefab")
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True,
        help="reuse products with a complete _lihui_info.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--flip-v", action=argparse.BooleanOptionalAction, default=False,
        help="legacy switch; Sprite renderMesh UVs are already in the "
             "orientation expected by this renderer")
    args = parser.parse_args(argv)

    prefabs = list(args.prefabs)
    if args.all:
        prefabs.extend(collect_prefabs(args.scan_root))
    prefabs = list(dict.fromkeys(os.path.abspath(path) for path in prefabs))
    if args.limit > 0:
        prefabs = prefabs[:args.limit]
    if not prefabs:
        parser.error("no prefabs; pass paths or use --all")

    rows = []
    failures = []
    failed = 0
    reused = 0
    total = len(prefabs)
    for index, prefab in enumerate(prefabs, 1):
        if not os.path.isfile(prefab):
            print("[%d/%d] MISSING %s" % (index, total, prefab), flush=True)
            failed += 1
            failures.append({
                "prefab": prefab,
                "error": "FileNotFoundError",
            })
            write_summary(args.out_root, rows, failures)
            continue
        try:
            info = existing_info(prefab, args.out_root) if args.resume else None
            if info:
                reused += 1
                status = "REUSE"
            else:
                info = convert_prefab(
                    prefab, args.assets, args.out_root, flip_v=args.flip_v)
                status = "OK"
            rows.append(info)
            print(
                "[%d/%d] %-5s %-48s bones=%-3d slots=%-3d textures=%d" % (
                    index, total, status, os.path.basename(prefab),
                    info["bones"], info["slots"], info["textures"]),
                flush=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            failures.append({
                "prefab": prefab,
                "error": "%s: %s" % (type(exc).__name__, exc),
            })
            print("[%d/%d] FAIL %-48s %s: %s" % (
                index, total, os.path.basename(prefab),
                type(exc).__name__, exc), flush=True)
            write_summary(args.out_root, rows, failures)
        finally:
            convert_2dmodel_module._OUTLINE_CACHE.clear()
            gc.collect()
        if index % 25 == 0 or index == total:
            write_summary(args.out_root, rows, failures)

    print("LIHUI_DONE products=%d reused=%d failed=%d" % (
        len(rows), reused, failed), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
