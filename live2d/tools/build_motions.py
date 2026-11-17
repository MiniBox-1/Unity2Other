# -*- coding: utf-8 -*-
r"""Build motion3.json for Alexandra from its AnimatorController states.

usage: python tools\build_motions.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.unity import unity_2dmodel as u2d  # noqa: E402
from unity2spine.unity import unity_anim2d as ua  # noqa: E402

from unity2live2d.convert.motion3 import sample_clip, to_motion3, write_motion  # noqa: E402
from unity2live2d.convert.rig import collect_bones  # noqa: E402
from unity2live2d.convert.rigged_model import RigPart, build_rigged  # noqa: E402
from unity2live2d.convert.static_model import verify, write_package  # noqa: E402
from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
PREFAB = PROJ / "Assets" / "Prefabs" / "2DModel_3P_Alexandra_N.uAnim.prefab"
NAME = "2DModel_3P_Alexandra_N_rig"
OUT = ROOT / "Products" / NAME
ASSETS = PROJ / "Assets"


def find_asset_by_guid(guid: str, suffix: str):
    for meta in ASSETS.rglob("*" + suffix + ".meta"):
        s = meta.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"guid: ([0-9a-f]+)", s)
        if m and m.group(1) == guid:
            return meta.with_suffix("")
    return None


def controller_of(prefab: Path):
    t = prefab.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"m_Controller: \{fileID: 9100000, guid: ([0-9a-f]+)", t)
    if not m:
        return None
    return find_asset_by_guid(m.group(1), ".controller")


def main():
    mdl, parts = build_character_model(str(PREFAB), str(ASSETS))
    world = _world_matrices(mdl, {})

    bone_ids = set()
    for p in parts:
        for b in (p.bones or []):
            if b:
                bone_ids.add(b)
    bones = collect_bones(mdl, bone_ids)

    rig_parts = []
    for p in parts:
        mesh = p.mesh or {}
        verts = ([(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
                 if p.kind == "skinned" else
                 [(v[0], v[1]) for v in (mesh.get("positions") or [])])
        raw_uvs = list(mesh.get("uvs") or [])
        uvs = ([c for uv in raw_uvs for c in uv]
               if raw_uvs and isinstance(raw_uvs[0], (tuple, list)) else list(raw_uvs))
        tris = list(mesh.get("triangles") or [])
        if not verts or not uvs or not tris:
            continue
        from unity2live2d.convert.rig import dominant_bone
        rig_parts.append(RigPart(name=p.name, verts=verts, uvs=uvs, indices=tris,
                                 bone=dominant_bone(p, bones, verts) or -1,
                                 sorting_order=p.sorting_order, order=p.order))
    rig_parts.sort(key=lambda s: (s.sorting_order, s.order))

    result = build_rigged(rig_parts, mdl, bones=bones, ppu=1000.0, margin=0.05,
                          angle_range=(-30.0, 30.0))
    write_package(result, NAME, OUT, texture=Path(parts[0].texture_path))
    report = verify(result, NAME)
    print("model:", report["consistency"], "max_err", report["max_err"])

    ctrl_path = controller_of(PREFAB)
    if not ctrl_path:
        raise SystemExit("controller not found")
    states = u2d.parse_animator_controller(str(ctrl_path))
    print("states:", [s["name"] for s in states])

    motions = {}
    for st in states:
        clip_path = find_asset_by_guid(st["clipGuid"], ".anim")
        if not clip_path:
            print("  missing clip", st["name"])
            continue
        clip = ua.parse_clip(str(clip_path))
        curves = sample_clip(clip, bones, mdl.transforms)
        loop = st["name"] not in ("Start",)
        motion = to_motion3(curves, float(clip.get("duration") or 0.0),
                            fps=30.0, loop=loop, fade_in=0.3, fade_out=0.3)
        p = write_motion(motion, OUT / "motions" / f"{st['name']}.motion3.json")
        motions[st["name"]] = p.name
        vals = [c.values[0] for c in curves] if curves else []
        print(f"  {st['name']:8s} dur={clip.get('duration'):5.2f} curves={len(curves):3d} "
              f"file={p.name}")

    # 更新 model3.json 的 Motions
    mp = OUT / f"{NAME}.model3.json"
    model3 = json.loads(mp.read_text(encoding="utf-8"))
    model3["FileReferences"]["Motions"] = {
        name: [{"File": f"motions/{fn}"}] for name, fn in motions.items()
    }
    mp.write_text(json.dumps(model3, ensure_ascii=False, indent=2), encoding="utf-8")

    report["motions"] = motions
    (OUT / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("out:", OUT)


if __name__ == "__main__":
    main()
