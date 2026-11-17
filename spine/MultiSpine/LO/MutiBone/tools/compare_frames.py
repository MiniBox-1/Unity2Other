# -*- coding: utf-8 -*-
"""Compare two rendered frames with the same size and transparent background."""
import argparse
import os
import re

import numpy as np
from PIL import Image


def bbox(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def frame_map(path):
    frames = {}
    for name in os.listdir(path):
        match = re.search(r"__t(\d+)\.png$", name)
        if match:
            frames[int(match.group(1))] = os.path.join(path, name)
    return frames


def compare(ref_path, got_path, threshold, diff_out=None, search_shift=0.0):
    ref = np.asarray(Image.open(ref_path).convert("RGB"), dtype=np.int16)
    got = np.asarray(Image.open(got_path).convert("RGB"), dtype=np.int16)
    if ref.shape != got.shape:
        raise SystemExit("size mismatch: %s vs %s" % (ref.shape, got.shape))

    diff = np.abs(ref - got).max(axis=2)
    ref_ink = ref.min(axis=2) < threshold
    got_ink = got.min(axis=2) < threshold
    union = ref_ink | got_ink
    iou = float((ref_ink & got_ink).sum()) / max(1, int(union.sum()))
    inside = ref_ink & got_ink
    inside_mean = float(diff[inside].mean()) if inside.any() else 0.0
    strong = diff > 32
    best_shift = None
    if search_shift > 0:
        source = Image.fromarray(got.astype(np.uint8), "RGB")
        steps = int(round(search_shift / 0.25))
        best = None
        for iy in range(-steps, steps + 1):
            for ix in range(-steps, steps + 1):
                dx, dy = ix * 0.25, iy * 0.25
                moved = source.transform(
                    source.size, Image.Transform.AFFINE,
                    (1, 0, -dx, 0, 1, -dy), resample=Image.Resampling.BICUBIC)
                value = float(np.abs(
                    np.asarray(moved, dtype=np.int16) - ref).mean())
                if best is None or value < best[0]:
                    best = (value, dx, dy)
        best_shift = best
    if diff_out:
        heat = np.zeros_like(got, dtype=np.uint8)
        heat[..., 0] = np.clip(diff * 8, 0, 255)
        heat[..., 1] = np.clip((diff - 32) * 2, 0, 255)
        Image.fromarray(heat, "RGB").save(diff_out)
    bias = (got - ref).reshape(-1, 3).mean(axis=0)
    suffix = ""
    if best_shift:
        suffix = " bestShift=(%.2f,%.2f) shiftedMean=%.4f" % (
            best_shift[1], best_shift[2], best_shift[0])
    return ("ink=%d/%d mean=%.4f gt32=%d bias=(%.3f,%.3f,%.3f) "
            "iou=%.5f inside=%.4f bbox=%s/%s strong_bbox=%s"
            % (int(got_ink.sum()), int(ref_ink.sum()), float(diff.mean()),
               int(strong.sum()), bias[0], bias[1], bias[2],
               iou, inside_mean,
               bbox(got_ink), bbox(ref_ink), bbox(strong))) + suffix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference")
    ap.add_argument("candidate")
    ap.add_argument("--threshold", type=int, default=240)
    ap.add_argument("--diff-out")
    ap.add_argument("--search-shift", type=float, default=0.0)
    a = ap.parse_args()

    if os.path.isdir(a.reference) and os.path.isdir(a.candidate):
        refs = frame_map(a.reference)
        got = frame_map(a.candidate)
        common = sorted(set(refs) & set(got))
        if not common:
            raise SystemExit("no matching __tNNN.png frames")
        for t in common:
            diff_out = None
            if a.diff_out:
                root, ext = os.path.splitext(a.diff_out)
                diff_out = "%s_t%d%s" % (root, t, ext or ".png")
            print("t=%d %s"
                  % (t, compare(refs[t], got[t], a.threshold, diff_out,
                                a.search_shift)))
    else:
        print(compare(a.reference, a.candidate, a.threshold, a.diff_out,
                      a.search_shift))


if __name__ == "__main__":
    main()
