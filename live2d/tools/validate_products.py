# -*- coding: utf-8 -*-
r"""Validate every generated Cubism package under Products\.

Checks per package:
  * moc3 passes csmHasMocConsistency
  * model3.json references existing moc/texture/motions
  * every motion curve id exists in the model parameters
  * reports parts / deformers / params / motions

usage: python tools\validate_products.py [ProductsDir]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from unity2live2d.moc3 import CubismCore  # noqa: E402


def validate_one(model3_path: Path, core: CubismCore) -> dict:
    base = model3_path.parent
    out = {"name": base.name, "ok": False, "problems": []}
    try:
        m3 = json.loads(model3_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        out["problems"].append(f"model3.json: {exc!r}")
        return out

    refs = m3.get("FileReferences") or {}
    moc_path = base / (refs.get("Moc") or "")
    if not moc_path.is_file():
        out["problems"].append("missing moc3")
        return out
    data = moc_path.read_bytes()
    out["bytes"] = len(data)
    if core.consistency(data) != 1:
        out["problems"].append("consistency=0")
        return out
    model = core.load(data)
    if model is None:
        out["problems"].append("core load failed")
        return out

    params = set(model.parameter_ids())
    out["parts"] = len(model.part_ids())
    out["params"] = len(params)

    for tex in refs.get("Textures") or []:
        if not (base / tex).is_file():
            out["problems"].append(f"missing texture {tex}")

    # SDK 结构对齐（CubismModel3Json / CubismDisplayInfo3Json / CubismMotion3Json）
    if m3.get("Version") != 3:
        out["problems"].append("model3 Version != 3")
    for key in ("Moc", "Textures"):
        if key not in refs:
            out["problems"].append(f"FileReferences missing {key}")
    cdi = refs.get("DisplayInfo")
    if cdi:
        p = base / cdi
        if not p.is_file():
            out["problems"].append("missing cdi3")
        else:
            c = json.loads(p.read_text(encoding="utf-8"))
            if not all(k in c for k in ("Version", "Parameters", "ParameterGroups", "Parts")):
                out["problems"].append("cdi3 schema mismatch")

    # 每张 ArtMesh 的纹理下标必须落在 Textures 范围内
    n_tex = len(refs.get("Textures") or [])
    bad_tex = [i for i in range(len(model.drawable_ids()))
               if model.drawable(i)["texture"] >= max(1, n_tex)]
    if bad_tex:
        out["problems"].append(f"{len(bad_tex)} drawables reference missing textures")
    out["textures"] = n_tex

    motions = refs.get("Motions") or {}
    count = 0
    for group, entries in motions.items():
        for e in entries:
            p = base / e["File"]
            if not p.is_file():
                out["problems"].append(f"missing motion {e['File']}")
                continue
            try:
                mot = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                out["problems"].append(f"bad motion {p.name}: {exc!r}")
                continue
            count += 1
            if mot.get("Version") != 3 or "Meta" not in mot:
                out["problems"].append(f"{p.name}: motion3 schema mismatch")
            for key in ("Duration", "Fps", "Loop"):
                if key not in (mot.get("Meta") or {}):
                    out["problems"].append(f"{p.name}: Meta missing {key}")
            bad = [c["Id"] for c in mot.get("Curves", []) if c["Id"] not in params]
            if bad:
                out["problems"].append(f"{p.name}: {len(bad)} unknown ids")
            for c in mot.get("Curves", []):
                if c.get("Target") != "Parameter" or "Segments" not in c:
                    out["problems"].append(f"{p.name}: curve schema mismatch")
                    break
    out["motions"] = count
    out["ok"] = not out["problems"]
    return out


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "Products"
    core = CubismCore()
    rows = []
    for m3 in sorted(root.glob("*/*.model3.json")):
        rows.append(validate_one(m3, core))

    ok = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    print(f"packages: {len(rows)}  ok: {len(ok)}  bad: {len(bad)}")
    if ok:
        print(f"  total parts={sum(r['parts'] for r in ok)} "
              f"params={sum(r['params'] for r in ok)} "
              f"motions={sum(r['motions'] for r in ok)} "
              f"moc3 MB={sum(r['bytes'] for r in ok)/1e6:.1f}")
    for r in bad[:20]:
        print("  BAD", r["name"], r["problems"][:3])

    report = {"total": len(rows), "ok": len(ok), "bad": len(bad), "rows": rows}
    (root / "_validate_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("report:", root / "_validate_report.json")


if __name__ == "__main__":
    main()
