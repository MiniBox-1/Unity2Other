# -*- coding: utf-8 -*-
r"""In-process dual UV-variant build with per-character selection (fast)."""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import unity_iou_audit as A  # noqa: E402
from unity2live2d.convert.pipeline import convert_character, _guid_index  # noqa: E402
from unity2live2d.moc3 import CubismCore  # noqa: E402
from preview_moc3 import render_model  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
REF = ROOT / "Products" / "_unity_ref_nat"
WORK = ROOT / "Products" / "_dual2"
REPORT = ROOT / "Products" / "_dual_report.json"


def score(pkg, name, flip):
    m3p = pkg / f"{name}.model3.json"
    if not m3p.exists():
        return None
    m3 = json.loads(m3p.read_text(encoding="utf-8"))
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
    names = sorted(p.name for p in (ROOT / "Products").iterdir()
                   if p.is_dir() and (p / f"{p.name}.model3.json").exists()
                   and not p.name.startswith("_")
                   and not p.name.endswith(("_rig", "_seg")))
    if limit:
        names = names[:limit]
    gi = _guid_index(PROJ / "Assets")
    out = {}
    for i, n in enumerate(names):
        prefab = PROJ / "Assets" / "Prefabs" / f"{n}.uAnim.prefab"
        if not prefab.exists():
            continue
        a_dir = WORK / "A" / n
        b_dir = WORK / "B" / n
        try:
            os.environ.pop("U2L2D_NO_UVFIX", None)
            convert_character(prefab, PROJ / "Assets", a_dir, n, 30, gi)
            os.environ["U2L2D_NO_UVFIX"] = "1"
            convert_character(prefab, PROJ / "Assets", b_dir, n, 30, gi)
        finally:
            os.environ.pop("U2L2D_NO_UVFIX", None)
        sa = score(a_dir, n, True)
        sb = score(b_dir, n, False)
        best = "A" if (sa or 0) >= (sb or 0) else "B"
        out[n] = {"A": sa, "B": sb, "best": best}
        if best == "B" and (b_dir / f"{n}.model3.json").exists():
            dst = ROOT / "Products" / n
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(b_dir, dst)
        print(f"[{i+1}/{len(names)}] {n[:36]:36s} A={sa if sa is None else round(sa,3)} "
              f"B={sb if sb is None else round(sb,3)} -> {best}", flush=True)
        if (i + 1) % 20 == 0:
            REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("B chosen:", sum(1 for v in out.values() if v["best"] == "B"))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
