# -*- coding: utf-8 -*-
r"""Pick per-character the UV variant that matches Unity under the viewer convention."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import unity_iou_audit as A  # noqa: E402
from unity2live2d.moc3 import CubismCore  # noqa: E402
from preview_moc3 import render_model  # noqa: E402

REF = ROOT / "Products" / "_unity_ref_nat"
WORK = ROOT / "Products" / "_dual2"
REPORT = ROOT / "Products" / "_dual_report2.json"
FLIP = True          # 预览 flip=True 与查看器一致（Alexandra 等已由此验证）


def score(pkg, name):
    m3p = pkg / f"{name}.model3.json"
    if not m3p.exists():
        return None
    m3 = json.loads(m3p.read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    texs = [pkg / t for t in (m3["FileReferences"].get("Textures") or [])]
    img, _ = render_model(model, texs, 512, FLIP)
    tmp = WORK / f"{name}_chk.png"
    img.save(tmp)
    ref = REF / f"{name}.png"
    if not ref.exists():
        return None
    ma, mb = A.mask(tmp), A.mask(ref)
    if ma is None or mb is None:
        return None
    return A.iou(ma, mb)


def main(dry=False):
    out = {}
    picked = 0
    for n in sorted(p.name for p in (ROOT / "Products").iterdir()
                    if p.is_dir() and (p / f"{p.name}.model3.json").exists()
                    and not p.name.startswith("_")) :
        a_dir = WORK / "A" / n
        b_dir = WORK / "B" / n
        if not a_dir.exists() or not b_dir.exists():
            continue
        sa, sb = score(a_dir, n), score(b_dir, n)
        if sa is None or sb is None:
            continue
        best = "A" if sa >= sb else "B"
        out[n] = {"A": round(sa, 3), "B": round(sb, 3), "best": best}
        if best == "B":
            picked += 1
            if not dry:
                dst = ROOT / "Products" / n
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(b_dir, dst)
        print(f"{n[:38]:38s} A={sa:.3f} B={sb:.3f} -> {best}", flush=True)
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("B picked:", picked, "/", len(out))


if __name__ == "__main__":
    main("--dry" in sys.argv)
