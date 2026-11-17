# -*- coding: utf-8 -*-
"""Print raw Unity skin influences for selected prefab parts."""
import argparse
import collections
import os
import sys

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(LIB, "src"))

from ngui2spine.static_prefab_spine import (  # noqa: E402
    ASSETS_DEFAULT, assignments_for_entry, enumerate_clips, load_character,
    make_samplers, _sample_world_multi)


def planar_values(matrix):
    values = [float(value) for value in list(matrix or [])]
    if len(values) < 16:
        return None
    return values[2], values[6], values[8], values[9]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--assets", default=ASSETS_DEFAULT)
    ap.add_argument("--scene", default="")
    args = ap.parse_args()

    mdl, parts = load_character(args.prefab, args.assets, args.scene or None)
    entries = enumerate_clips(mdl, args.assets)
    samplers = make_samplers(mdl, entries)
    world = _sample_world_multi(
        mdl, assignments_for_entry(mdl, samplers, entries, entries[0]), 0.0)
    wanted = list(args.parts)
    for part in parts:
        if not any(token.lower() in part.name.lower() for token in wanted):
            continue
        raw_bones = list(getattr(part, "bones", None) or [])
        raw = (part.mesh or {}).get("boneIndexRaw") or []
        weights = (part.mesh or {}).get("weights") or []
        counts = collections.Counter()
        invalid = 0
        pairs = 0
        for vi, weight_row in enumerate(weights):
            index_row = raw[vi] if vi < len(raw) else None
            for k, value in enumerate(weight_row or []):
                weight = float(value)
                if abs(weight) <= 1e-8:
                    continue
                pair = index_row
                if isinstance(index_row, (list, tuple)):
                    pair = index_row[k] if k < len(index_row) else None
                if not isinstance(pair, int) or not 0 <= pair < len(raw_bones):
                    invalid += 1
                    continue
                tfid = raw_bones[pair]
                td = mdl.transforms.get(tfid) or {}
                counts[(tfid, td.get("name") or "")] += weight
                pairs += 1
        print("\nPART %s kind=%s tfid=%s host=%s verts=%d weighted_pairs=%d invalid=%d"
              % (part.name, part.kind, part.tfid,
                 (mdl.transforms.get(part.tfid) or {}).get("name"),
                 len(weights), pairs, invalid))
        print("  raw_bones:")
        for i, tfid in enumerate(raw_bones):
            td = mdl.transforms.get(tfid) or {}
            pv = planar_values(world.get(tfid))
            print("    %2d tfid=%-20s name=%-36s planar=%s "
                  "z=(%.6g,%.6g,%.6g,%.6g)"
                  % (i, tfid, td.get("name") or "",
                     bool(pv is not None and max(abs(x) for x in pv) < 1e-4),
                     *(pv or (float("nan"),) * 4)))
        print("  effective weights:")
        for (tfid, name), total in counts.most_common():
            print("    %-40s tfid=%-20s weight_sum=%.6f"
                  % (name, tfid, total))


if __name__ == "__main__":
    main()
