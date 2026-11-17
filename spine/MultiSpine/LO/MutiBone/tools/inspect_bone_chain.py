# -*- coding: utf-8 -*-
"""Print raw transform father chains for selected prefab nodes."""

import argparse
import os
import sys

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, os.path.join(LIB, "src"))

from unity2spine.unity.unity_2dmodel import TwoDModel  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prefab")
    parser.add_argument("--assets", required=True)
    parser.add_argument("--ids", default="",
                        help="comma-separated transform IDs")
    parser.add_argument("--names", default="",
                        help="comma-separated name substrings")
    args = parser.parse_args()
    model = TwoDModel()
    model.build(args.prefab, args.assets)
    wanted_ids = {
        int(value) for value in args.ids.split(",") if value.strip()
    }
    tokens = [
        value.strip().casefold()
        for value in args.names.split(",") if value.strip()
    ]
    rank = {tfid: index for index, tfid in enumerate(model.transforms)}
    selected = []
    for tfid, transform in model.transforms.items():
        if wanted_ids and tfid not in wanted_ids:
            continue
        if tokens and not any(
                token in (transform.get("name") or "").casefold()
                for token in tokens):
            continue
        selected.append(tfid)

    for tfid in selected:
        transform = model.transforms.get(tfid) or {}
        father = transform.get("father")
        father_transform = model.transforms.get(father) or {}
        print(
            "tfid=%s idx=%s name=%s father=%s/%s fidx=%s"
            % (
                tfid, rank.get(tfid), transform.get("name"),
                father, father_transform.get("name"), rank.get(father),
            )
        )
        chain = []
        current = father
        hops = 0
        while current is not None and hops < 300:
            item = model.transforms.get(current) or {}
            chain.append("%s/%s" % (current, item.get("name")))
            current = item.get("father")
            hops += 1
        print("  chain: " + " <- ".join(chain))
    return 0


if __name__ == "__main__":
    sys.exit(main())
