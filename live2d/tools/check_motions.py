# -*- coding: utf-8 -*-
r"""Sanity-check generated motion3 files: duration, curve ids, loop seam."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from unity2live2d.moc3 import CubismCore  # noqa: E402


def main(model3_path: Path):
    m3 = json.loads(model3_path.read_text(encoding="utf-8"))
    base = model3_path.parent
    core = CubismCore()
    model = core.load((base / m3["FileReferences"]["Moc"]).read_bytes())
    known = set(model.parameter_ids())

    for name, entries in m3["FileReferences"]["Motions"].items():
        path = base / entries[0]["File"]
        mot = json.loads(path.read_text(encoding="utf-8"))
        dur = mot["Meta"]["Duration"]
        unknown = sorted({c["Id"] for c in mot["Curves"] if c["Id"] not in known})
        seam, seam_id = 0.0, ""
        const = 0
        for c in mot["Curves"]:
            seg = c["Segments"]
            if len(seg) > 3 and abs(seg[-1] - seg[1]) > seam:
                seam, seam_id = abs(seg[-1] - seg[1]), c["Id"]
            if len(seg) <= 3:
                const += 1
        print(f"{name:8s} dur={dur:5.2f} curves={len(mot['Curves']):3d} "
              f"unknown={len(unknown)} static_curves={const} "
              f"max_seam={seam:.3f} ({seam_id})")
        if unknown:
            print("   unknown:", unknown[:5])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
