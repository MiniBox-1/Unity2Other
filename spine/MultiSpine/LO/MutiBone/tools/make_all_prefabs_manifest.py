# -*- coding: utf-8 -*-
"""Build a manifest for all converted *.uAnim.prefab products."""

import argparse
import hashlib
import json
import os
import sys


def find_one(directory, suffix):
    for name in sorted(os.listdir(directory)):
        if name.endswith(suffix):
            return os.path.join(directory, name)
    return None


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assets",
        default=r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets",
    )
    parser.add_argument(
        "--out",
        default=r"D:\VB\MutiBone\out\_all_prefabs",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    prefab_root = os.path.join(args.assets, "Prefabs")
    all_prefabs = []
    anim_prefabs = []
    for root, _, files in os.walk(prefab_root):
        for name in files:
            if not name.endswith(".prefab"):
                continue
            path = os.path.join(root, name)
            all_prefabs.append(path)
            if name.endswith(".uAnim.prefab"):
                anim_prefabs.append(path)
    anim_prefabs.sort(key=lambda path: os.path.basename(path).lower())

    rows = []
    missing = []
    total_bytes = 0
    for prefab in anim_prefabs:
        stem = os.path.splitext(os.path.basename(prefab))[0]
        product = os.path.join(args.out, stem)
        json_path = find_one(product, "_static.json") if os.path.isdir(product) else None
        skel_path = find_one(product, "_static.skel") if os.path.isdir(product) else None
        atlas_path = find_one(product, ".atlas") if os.path.isdir(product) else None
        png_paths = (
            sorted(
                os.path.join(product, name)
                for name in os.listdir(product)
                if name.lower().endswith(".png")
            ) if os.path.isdir(product) else []
        )
        if not (json_path and skel_path and atlas_path and png_paths):
            missing.append({
                "prefab": os.path.relpath(prefab, prefab_root).replace("\\", "/"),
                "stem": stem,
                "product": product,
            })
            continue
        with open(json_path, encoding="utf-8") as handle:
            data = json.load(handle)
        files = [json_path, skel_path, atlas_path] + png_paths
        sizes = [os.path.getsize(path) for path in files]
        total_bytes += sum(sizes)
        rows.append({
            "prefab": os.path.relpath(prefab, prefab_root).replace("\\", "/"),
            "stem": stem,
            "product": product,
            "bones": len(data.get("bones") or []),
            "slots": len(data.get("slots") or []),
            "animations": len(data.get("animations") or {}),
            "jsonBytes": os.path.getsize(json_path),
            "skelBytes": os.path.getsize(skel_path),
            "jsonSha256": sha256(json_path),
            "skelSha256": sha256(skel_path),
            "atlas": os.path.basename(atlas_path),
            "pngCount": len(png_paths),
        })

    report = {
        "allPrefabCount": len(all_prefabs),
        "uAnimPrefabCount": len(anim_prefabs),
        "convertedCount": len(rows),
        "missingCount": len(missing),
        "nonUAnimSkippedCount": len(all_prefabs) - len(anim_prefabs),
        "totalProductMB": round(total_bytes / 1048576.0, 2),
        "missing": missing,
        "products": rows,
    }
    os.makedirs(args.out, exist_ok=True)
    report_path = os.path.join(args.out, "manifest.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    conversion_report = {
        "total": len(anim_prefabs),
        "completed": len(rows),
        "ok": len(rows),
        "failed": len(missing),
        "results": [
            {
                "prefab": row["prefab"],
                "stem": row["stem"],
                "status": "ok",
                "bones": row["bones"],
                "slots": row["slots"],
                "animations": row["animations"],
                "jsonBytes": row["jsonBytes"],
                "skelBytes": row["skelBytes"],
            }
            for row in rows
        ] + [
            {
                "prefab": row["prefab"],
                "stem": row["stem"],
                "status": "missing-product",
            }
            for row in missing
        ],
    }
    with open(os.path.join(args.out, "conversion_report.json"),
              "w", encoding="utf-8") as handle:
        json.dump(conversion_report, handle, ensure_ascii=False, indent=2)
    skipped_path = os.path.join(args.out, "non_uAnim_prefabs.csv")
    with open(skipped_path, "w", encoding="utf-8-sig") as handle:
        handle.write("name,path\n")
        for path in sorted(all_prefabs, key=lambda item: item.lower()):
            if path.endswith(".uAnim.prefab"):
                continue
            rel = os.path.relpath(path, prefab_root).replace("\\", "/")
            handle.write('"%s","%s"\n' % (
                os.path.basename(path).replace('"', '""'),
                rel.replace('"', '""'),
            ))
    print(
        "ALL_PREFABS_MANIFEST_OK uAnim=%d converted=%d missing=%d "
        "non_uAnim_skipped=%d size=%.1f MB"
        % (
            report["uAnimPrefabCount"], report["convertedCount"],
            report["missingCount"], report["nonUAnimSkippedCount"],
            report["totalProductMB"],
        )
    )
    print("manifest=%s" % report_path)
    print("skipped=%s" % skipped_path)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
