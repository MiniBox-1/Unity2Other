# -*- coding: utf-8 -*-
"""Audit SkinnedMeshRenderer bone palettes against shared mesh bindposes."""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "src"))

from shared_skin_audit import audit_prefab  # noqa: E402


def default_prefabs():
    root = r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets\Prefabs"
    return sorted(
        os.path.join(root, name)
        for name in os.listdir(root)
        if name.endswith(".uAnim.prefab")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prefabs", nargs="*")
    parser.add_argument(
        "--assets",
        default=r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets",
    )
    parser.add_argument("--all", action="store_true",
                        help="Print complete renderers too")
    args = parser.parse_args()
    prefabs = args.prefabs or default_prefabs()
    total = 0
    for prefab in prefabs:
        rows, suspicious = audit_prefab(prefab, args.assets)
        selected = rows if args.all else suspicious
        if not selected:
            continue
        total += len(suspicious)
        print("\n%s" % os.path.basename(prefab))
        print("%-42s %5s %5s %7s %7s %7s %s" % (
            "renderer", "bones", "bind", "badPair", "badVert", "peers", "verdict"
        ))
        for row in selected:
            verdict = (
                "drop-candidate" if (
                    row["invalid_pairs"] and row["complete_peers"]
                ) else "-"
            )
            print("%-42s %5d %5d %7d %7d %7d %s" % (
                row["name"], row["bone_count"], row["bindpose_count"],
                row["invalid_pairs"], row["invalid_vertices"],
                row["mesh_peers"], verdict,
            ))
    print("\nSUSPICIOUS_RENDERERS=%d prefabs=%d" % (total, len(prefabs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
