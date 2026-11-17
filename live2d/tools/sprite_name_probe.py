# -*- coding: utf-8 -*-
r"""Resolve sprite names for a character's parts (texture .meta spriteSheet by rect).

Puppet2D_GlobalControl 按「精灵名含 Control/ffd」决定隐藏，
而我们的部件只带贴图 GUID，所以这里把贴图 .meta 里的子精灵名读出来做对照。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")

from unity2spine.convert.convert_2dmodel import build_character_model  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
SPRITE_RE = re.compile(
    r"-\s*serializedVersion:.*?\n\s*name:\s*(?P<name>[^\n]+)\n\s*rect:\s*\n"
    r"\s*serializedVersion:\s*2\n\s*x:\s*(?P<x>-?[\d.]+)\n\s*y:\s*(?P<y>-?[\d.]+)\n"
    r"\s*width:\s*(?P<w>-?[\d.]+)\n\s*height:\s*(?P<h>-?[\d.]+)", re.S)


def sprite_names_for(tex_path: Path):
    meta = tex_path.with_name(tex_path.name + ".meta")
    if not meta.exists():
        return []
    txt = meta.read_text(encoding="utf-8", errors="replace")
    out = []
    for m in SPRITE_RE.finditer(txt):
        out.append((m.group("name").strip(), float(m.group("x")), float(m.group("y")),
                    float(m.group("w")), float(m.group("h"))))
    return out


def main(name: str, needle: str):
    prefab = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
    _mdl, parts = build_character_model(str(prefab), str(PROJ / "Assets"))
    cache = {}
    for p in parts:
        if needle not in p.name:
            continue
        tp = getattr(p, "texture_path", None)
        if not tp:
            continue
        tp = Path(str(tp))
        if tp not in cache:
            cache[tp] = sprite_names_for(tp)
        rect = (p.sprite or {}).get("rect") or {}
        if isinstance(rect, dict):
            rw = rect.get("w") or rect.get("width") or 0
            rh = rect.get("h") or rect.get("height") or 0
        else:
            rw = rect[2] if len(rect) > 2 else 0
            rh = rect[3] if len(rect) > 3 else 0
        hit = None
        for nm, x, y, w, h in cache[tp]:
            if abs(w - rw) < 1.5 and abs(h - rh) < 1.5:
                hit = nm
                break
        print(f"{p.name[:44]:44s} rect=({rw:.0f}x{rh:.0f}) sprite={hit}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "FullBody")
