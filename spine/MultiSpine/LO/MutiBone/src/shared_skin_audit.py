# -*- coding: utf-8 -*-
"""Detect malformed duplicate SkinnedMeshRenderers sharing one mesh."""

import collections
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
LIB = os.path.join(REPO, "SingleSpine", "Shared", "Unity2Spine")
if os.path.join(LIB, "src") not in sys.path:
    sys.path.insert(0, os.path.join(LIB, "src"))

from unity2spine.unity.unity_2dmodel import (  # noqa: E402
    TwoDModel, find_asset_by_guid,
)
from unity2spine.unity.unity_mesh import parse_mesh  # noqa: E402


def audit_prefab(prefab, assets):
    """Return (all rows, suspicious rows) for skinned mesh bone palettes."""
    model = TwoDModel()
    model.build(prefab, assets)
    mesh_cache = {}
    rows = []
    for renderer_index, renderer in enumerate(model.renderers):
        if renderer.get("kind") != "skinned":
            continue
        mesh_guid = renderer.get("meshGuid")
        mesh_path = find_asset_by_guid(assets, mesh_guid)
        if not mesh_path:
            continue
        mesh = mesh_cache.get(mesh_path)
        if mesh is None:
            mesh = parse_mesh(mesh_path)
            mesh_cache[mesh_path] = mesh

        bone_count = len(renderer.get("bones") or [])
        bindpose_count = len(mesh.get("bindposes") or [])
        weights = mesh.get("weights") or []
        raw_indices = mesh.get("boneIndexRaw") or []
        invalid_pairs = 0
        invalid_vertices = 0
        for vertex_index, weight_row in enumerate(weights):
            index_row = (
                raw_indices[vertex_index]
                if vertex_index < len(raw_indices) else None
            )
            vertex_invalid = False
            for channel, raw_weight in enumerate(weight_row or []):
                weight = float(raw_weight)
                if abs(weight) <= 1e-8:
                    continue
                index = index_row
                if isinstance(index_row, (list, tuple)):
                    index = index_row[channel] if channel < len(index_row) else None
                if not isinstance(index, int) or not 0 <= index < bone_count:
                    invalid_pairs += 1
                    vertex_invalid = True
            invalid_vertices += int(vertex_invalid)

        gameobject = model.gameobjects.get(renderer.get("go")) or {}
        rows.append({
            "renderer_index": renderer_index,
            "name": "%s_%02d" % (
                gameobject.get("name") or "part", renderer_index),
            "go": renderer.get("go"),
            "tfid": renderer.get("tfid"),
            "mesh_path": mesh_path,
            "mesh_guid": mesh_guid,
            "bone_count": bone_count,
            "bindpose_count": bindpose_count,
            "invalid_pairs": invalid_pairs,
            "invalid_vertices": invalid_vertices,
        })

    by_mesh = collections.defaultdict(list)
    for row in rows:
        by_mesh[row["mesh_guid"]].append(row)
    for group in by_mesh.values():
        for row in group:
            row["mesh_peers"] = len(group)
            row["complete_peers"] = sum(
                1 for peer in group
                if peer["bone_count"] == peer["bindpose_count"]
                and peer["bindpose_count"] > 0
            )

    suspicious = [
        row for row in rows
        if row["bone_count"] != row["bindpose_count"]
        and (row["invalid_pairs"] or row["complete_peers"])
    ]
    return rows, suspicious


def drop_candidates(prefab, assets):
    """Names of malformed short-palette peers safe to omit from drawing.

    The condition is intentionally narrow: a nonzero weighted influence points
    outside the renderer's palette, and the exact same mesh has another renderer
    with a complete palette.  In the current asset set this selects only
    Banshee ``parts_Hand_R_66`` (3 bones versus 4 bindposes).
    """
    _, rows = audit_prefab(prefab, assets)
    return {
        row["name"] for row in rows
        if row["bone_count"] != row["bindpose_count"]
        and row["invalid_pairs"] > 0
        and row["complete_peers"] > 0
    }
