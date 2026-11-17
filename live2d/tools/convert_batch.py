# -*- coding: utf-8 -*-
r"""Batch-convert Unity uAnim characters into standard Cubism packages.

usage:
  python tools\convert_batch.py --limit 3
  python tools\convert_batch.py --names 2DModel_3P_Alexandra_N,2DModel_3P_Alice_NS1
"""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2live2d.convert.pipeline import _guid_index, convert_character  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
ASSETS = PROJ / "Assets"
PREFAB_DIR = ASSETS / "Prefabs"
OUT = ROOT / "Products"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--names", default="")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    prefabs = sorted(PREFAB_DIR.glob("*.uAnim.prefab"))
    if args.names:
        wanted = [n.strip() for n in args.names.split(",") if n.strip()]
        prefabs = [p for p in prefabs if p.stem.replace(".uAnim", "") in wanted]
    else:
        prefabs = prefabs[:args.limit]

    print(f"characters: {len(prefabs)}")
    guid_index = _guid_index(ASSETS)
    print(f"guid index: {len(guid_index)}")

    reports = []
    t0 = time.time()
    for i, pf in enumerate(prefabs, 1):
        name = pf.stem.replace(".uAnim", "")
        t = time.time()
        try:
            rep = convert_character(pf, ASSETS, Path(args.out) / name,
                                    name=name, guid_index=guid_index)
            ok = rep.get("consistency") == 1 and rep.get("max_err") is not None
            rep["status"] = "ok" if ok else "bad-consistency"
        except Exception as exc:  # noqa: BLE001
            rep = {"name": name, "status": "error", "error": repr(exc),
                   "trace": traceback.format_exc()[-800:]}
        rep["seconds"] = round(time.time() - t, 1)
        reports.append(rep)
        print(f"[{i}/{len(prefabs)}] {name:42s} {rep['status']:16s} "
              f"{rep['seconds']:5.1f}s "
              f"parts={rep.get('parts')} def={rep.get('deformers')} "
              f"motions={len(rep.get('motions') or {})}")

    summary = {
        "total": len(reports),
        "ok": sum(1 for r in reports if r["status"] == "ok"),
        "failed": sum(1 for r in reports if r["status"] != "ok"),
        "seconds": round(time.time() - t0, 1),
        "reports": reports,
    }
    out = Path(args.out) / "_batch_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nok={summary['ok']}/{summary['total']} in {summary['seconds']}s -> {out}")


if __name__ == "__main__":
    main()
