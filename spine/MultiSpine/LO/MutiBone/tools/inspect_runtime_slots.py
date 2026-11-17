# -*- coding: utf-8 -*-
r"""Compare Unity U2SFrameDump slot visibility with a multibone Spine JSON.

The final multibone product intentionally does not keep the large
``_static_info.json`` next to the JSON/SKEL pair.  This tool therefore accepts
the original info file separately, which avoids copying it into every final
role directory.

Example:
    python inspect_runtime_slots.py dump.jsonl `
      --spine out/_reg_final/banshee `
      --info out/_deform_new2/_static_info.json `
      --anim Start --time 0.528 --grep Eye
"""

import argparse
import glob
import io
import json
import os
import sys


def load_json(path):
    with io.open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def find_spine_json(directory):
    matches = sorted(glob.glob(os.path.join(directory, "*_static.json")))
    if not matches:
        raise SystemExit("No *_static.json found in %s" % directory)
    return matches[0]


def sidecar_meta(dump):
    if dump.endswith(".jsonl"):
        path = dump[:-6] + ".meta.json"
    else:
        path = dump + ".meta.json"
    return load_json(path) if os.path.isfile(path) else None


def first_frame_time(dump):
    with io.open(dump, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            return float(json.loads(line).get("t", 0.0))
    raise SystemExit("Dump has no frame: %s" % dump)


def frame_at(dump, target):
    """Stream the dump and return the frame nearest to target."""
    best_frame = None
    best_distance = None
    with io.open(dump, encoding="utf-8") as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            frame = json.loads(line)
            time = float(frame.get("t", 0.0))
            distance = abs(time - target)
            if best_distance is None or distance < best_distance:
                best_frame = frame
                best_distance = distance
            if time > target and distance > best_distance:
                break
    if best_frame is None:
        raise SystemExit("Dump has no frame: %s" % dump)
    return best_frame


def path_candidates(path):
    path = (path or "").replace("\\", "/")
    parts = [part for part in path.split("/") if part]
    candidates = []
    for start in range(min(3, len(parts))):
        candidate = "/".join(parts[start:]).casefold()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def timeline_value(keys, time):
    current = None
    for key in keys or []:
        if float(key.get("time", 0.0)) <= time + 1e-9:
            current = key
        else:
            break
    return current


def spine_state(spine, info, animation, time, alpha_eps):
    slots = {
        slot["name"]: slot
        for slot in spine.get("slots") or []
        if slot.get("name")
    }
    timeline = (spine.get("animations") or {}).get(animation)
    if timeline is None:
        raise SystemExit("Animation not found: %s" % animation)
    animated = (timeline.get("slots") or {}).get("default") or {}
    if not animated:
        # Current multibone JSON writes slot names directly below "slots".
        animated = {
            name: value
            for name, value in (timeline.get("slots") or {}).items()
            if isinstance(value, dict)
        }

    name_by_path = {}
    for part in info.get("partsMeta") or []:
        name = part.get("name")
        if name:
            for candidate in path_candidates(part.get("path")):
                previous = name_by_path.get(candidate)
                if previous is None:
                    name_by_path[candidate] = name
                elif previous != name:
                    # Never silently resolve an ambiguous suffix.
                    name_by_path[candidate] = None

    result = {}
    for name in (part.get("name") for part in info.get("partsMeta") or []):
        if not name:
            continue
        setup = slots.get(name) or {}
        state = dict(setup)
        state["visible"] = bool(setup.get("attachment"))
        state["attachment"] = setup.get("attachment")
        state["alpha"] = 1.0

        slot_timeline = animated.get(name) or {}
        attachment_keys = slot_timeline.get("attachment")
        if attachment_keys:
            key = timeline_value(attachment_keys, time)
            attachment = None if key is None else key.get("name")
            state["attachment"] = attachment
            state["visible"] = bool(attachment)

        color_keys = slot_timeline.get("color")
        if color_keys:
            key = timeline_value(color_keys, time)
            color = (key or {}).get("color") or setup.get("color") or "ffffffff"
            try:
                state["alpha"] = int(color[6:8], 16) / 255.0
            except (TypeError, ValueError):
                state["alpha"] = 1.0
        if state["visible"] and state["alpha"] < alpha_eps:
            state["visible"] = False
        result[name] = state
    return result, name_by_path


def unity_state(frame, meta, alpha_eps, name_by_path):
    paths = {
        obj["i"]: obj.get("path") or ""
        for obj in (meta or {}).get("objects") or []
    }
    renderers = {
        item["o"]: item
        for item in frame.get("rnd") or []
    }
    result = {}
    for obj in frame.get("obj") or []:
        name = None
        for candidate in path_candidates(paths.get(obj["i"], "")):
            if candidate in name_by_path:
                name = name_by_path[candidate]
                break
        if not name:
            continue
        renderer = renderers.get(obj["i"]) or {}
        color = renderer.get("col")
        alpha = float(color[3]) if color else 1.0
        visible = bool(obj.get("ah")) and bool(renderer.get("en", True))
        visible = visible and alpha >= alpha_eps
        current = result.get(name)
        if current is None:
            result[name] = {
                "visible": visible,
                "alpha": alpha,
                "attachment": None,
            }
        else:
            current["visible"] = current["visible"] or visible
            current["alpha"] = max(current["alpha"], alpha)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dump")
    parser.add_argument("--spine", required=True, help="Multibone product directory")
    parser.add_argument("--info", default=None, help="Original _static_info.json")
    parser.add_argument("--anim", required=True)
    parser.add_argument(
        "--time",
        type=float,
        required=True,
        help="Seconds after the first captured dump frame",
    )
    parser.add_argument("--absolute-time", action="store_true")
    parser.add_argument("--grep", default=None)
    parser.add_argument("--alpha-eps", type=float, default=0.02)
    parser.add_argument("--all", action="store_true", help="Print matches too")
    parser.add_argument("--fail-on-mismatch", action="store_true")
    args = parser.parse_args()

    info_path = args.info or os.path.join(args.spine, "_static_info.json")
    if not os.path.isfile(info_path):
        raise SystemExit(
            "Missing %s; pass --info with the original deform _static_info.json"
            % info_path
        )

    meta = sidecar_meta(args.dump)
    spine_path = find_spine_json(args.spine)
    spine = load_json(spine_path)
    info = load_json(info_path)

    absolute_time = args.time
    if not args.absolute_time:
        absolute_time += first_frame_time(args.dump)
    frame = frame_at(args.dump, absolute_time)
    expected, name_by_path = spine_state(
        spine, info, args.anim, args.time, args.alpha_eps
    )
    unity = unity_state(frame, meta, args.alpha_eps, name_by_path)

    grep = args.grep.casefold() if args.grep else None
    slots = sorted(set(unity) | set(expected))
    mismatches = 0
    matched = 0
    print(
        "frame=%s t=%.4f relative=%.4f anim=%s"
        % (frame.get("f"), float(frame.get("t", 0.0)), args.time, args.anim)
    )
    print("%-34s %-9s %-9s %-3s %s" % (
        "path", "unity", "spine", "", "attachment"
    ))
    for slot in slots:
        if grep and grep not in slot.casefold():
            continue
        unity_visible = (unity.get(slot) or {}).get("visible", False)
        spine_item = expected.get(slot) or {}
        spine_visible = bool(spine_item.get("visible"))
        is_mismatch = unity_visible != spine_visible
        if not is_mismatch:
            matched += 1
            if not args.all:
                continue
        else:
            mismatches += 1
        print(
            "%-34s %-9s %-9s %-3s %s"
            % (
                slot,
                "show" if unity_visible else "hide",
                "show" if spine_visible else "hide",
                "!=" if is_mismatch else "",
                spine_item.get("attachment") or "",
            )
        )
    print("matched=%d mismatched=%d" % (matched, mismatches))
    if args.fail_on_mismatch and mismatches:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
