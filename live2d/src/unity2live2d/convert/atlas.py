# -*- coding: utf-8 -*-
"""Minimal Spine .atlas parser (pages + regions) for the reference renderer."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class Region:
    name: str
    page: int
    x: int
    y: int
    w: int
    h: int


@dataclass
class Atlas:
    pages: List[str] = field(default_factory=list)
    regions: Dict[str, Region] = field(default_factory=dict)
    page_size: Dict[int, Tuple[int, int]] = field(default_factory=dict)


def load_atlas(path: Path) -> Atlas:
    atlas = Atlas()
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    page = -1
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if not ln:
            i += 1
            continue
        # page header: ends with .png (not indented)
        if not lines[i].startswith((" ", "\t")) and ln.lower().endswith(".png"):
            atlas.pages.append(ln)
            page += 1
            i += 1
            continue
        # region name
        if not lines[i].startswith((" ", "\t")) and ln and ":" not in ln:
            name = ln
            region = Region(name=name, page=page, x=0, y=0, w=0, h=0)
            i += 1
            while i < len(lines) and lines[i].startswith((" ", "\t")):
                kv = lines[i].strip()
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    v = v.strip()
                    if k.strip() == "xy":
                        region.x, region.y = [int(float(t)) for t in v.split(",")]
                    elif k.strip() == "size":
                        region.w, region.h = [int(float(t)) for t in v.split(",")]
                    elif k.strip() == "orig" and region.w == 0:
                        region.w, region.h = [int(float(t)) for t in v.split(",")]
                i += 1
            atlas.regions[name] = region
            continue
        i += 1
    return atlas
