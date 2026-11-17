# -*- coding: utf-8 -*-
r"""Build two UV-orientation variants per character, keep whichever matches Unity better.

Variant A: current pipeline (sprite UVs flipped to Unity convention).
Variant B: raw UVs untouched.

Each variant is rendered with the sampling convention that corresponds to it
(A: flip at sampling, B: no flip) and compared with the Unity natural snapshot.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import unity_iou_audit as A  # noqa: E402
from unity2live2d.moc3 import CubismCore  # noqa: E402
from preview_moc3 import render_model  # noqa: E402

REF = ROOT / "Products" / "_unity_ref_nat"
WORK = ROOT / "Products" / "_dual"
REPORT = ROOT / "Products" / "_dual_report.json"


def names():
    return sorted(p.name for p in (ROOT / "Products").iterdir()
                  if p.is_dir() and (p / f"{p.name}.model3.json").exists()
                  and not p.name.startswith("_"))


def build(name, out, env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "convert_batch.py"),
                        "--names", name, "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    return r.returncode == 0 and (out / name / f"{name}.model3.json").exists()


def score(pkg, name, flip):
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    texs = [pkg / t for t in (m3["FileReferences"].get("Textures") or [])]
    img, _ = render_model(model, texs, 512, flip)
    tmp = WORK / f"{name}_{int(flip)}.png"
    img.save(tmp)
    ref = REF / f"{name}.png"
    if not ref.exists():
        return None
    ma, mb = A.mask(tmp), A.mask(ref)
    if ma is None or mb is None:
        return None
    return A.iou(ma, mb)


def main(limit=0):
    WORK.mkdir(parents=True, exist_ok=True)
    todo = names()
    if limit:
        todo = todo[:limit]
    prev = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    for i, n in enumerate(todo):
        a_root = WORK / "A"
        b_root = WORK / "B"
        ok_a = build(n, a_root, {})
        ok_b = build(n, b_root, {"U2L2D_NO_UVFIX": "1"})
        a_dir = a_root / n
        b_dir = b_root / n
        sa = score(a_dir, n, True) if ok_a else None
        sb = score(b_dir, n, False) if ok_b else None
        best = "A" if (sa or 0) >= (sb or 0) else "B"
        prev[n] = {"A": sa, "B": sb, "best": best}
        if best == "B" and sb is not None:
            dst = ROOT / "Products" / n
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(b_dir, dst)
        print(f"[{i+1}/{len(todo)}] {n[:38]:38s} A={sa if sa is None else round(sa,3)} "
              f"B={sb if sb is None else round(sb,3)} -> {best}", flush=True)
        if (i + 1) % 10 == 0:
            REPORT.write_text(json.dumps(prev, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT.write_text(json.dumps(prev, ensure_ascii=False, indent=2), encoding="utf-8")
    picks = sum(1 for v in prev.values() if v.get("best") == "B")
    print("done; B chosen for", picks)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
