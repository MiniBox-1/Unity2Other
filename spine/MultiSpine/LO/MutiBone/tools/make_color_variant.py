# -*- coding: utf-8 -*-
"""Create renderable slot-color variants for image-level diagnostics."""
import argparse
import json
import os
import shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("mode", choices=[
        "all-white", "shadows-transparent", "shadows-white"])
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)
    json_name = next(name for name in os.listdir(args.source)
                     if name.endswith("_static.json"))
    with open(os.path.join(args.source, json_name), encoding="utf-8") as fp:
        skel = json.load(fp)
    changed = 0
    for slot in skel.get("slots") or []:
        name = (slot.get("name") or "").lower()
        if args.mode == "all-white":
            slot["color"] = "ffffffff"
            changed += 1
        elif "shadow" in name:
            slot["color"] = ("00000000" if args.mode == "shadows-transparent"
                             else "ffffffff")
            changed += 1
    out_json = os.path.join(args.output, json_name)
    with open(out_json, "w", encoding="utf-8") as fp:
        json.dump(skel, fp, ensure_ascii=False)
    for name in os.listdir(args.source):
        if name == json_name:
            continue
        if name.endswith((".atlas", ".png")):
            shutil.copy2(os.path.join(args.source, name),
                         os.path.join(args.output, name))
    print("%s -> %s, changed slots=%d" % (args.mode, out_json, changed))


if __name__ == "__main__":
    main()
