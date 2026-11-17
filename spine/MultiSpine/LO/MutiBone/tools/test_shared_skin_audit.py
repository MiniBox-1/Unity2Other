# -*- coding: utf-8 -*-
"""Regression checks for malformed shared SkinnedMeshRenderer palettes."""

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "src"))

from shared_skin_audit import audit_prefab, drop_candidates  # noqa: E402

ASSETS = r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets"
PREFABS = os.path.join(ASSETS, "Prefabs")


def check_banshee():
    prefab = os.path.join(PREFABS, "2DModel_BR_Banshee_NS1.uAnim.prefab")
    rows, suspicious = audit_prefab(prefab, ASSETS)
    by_name = {row["name"]: row for row in rows}
    bad = by_name["parts_Hand_R_66"]
    good = by_name["parts_Hand_R_68"]
    assert bad["bone_count"] == 3
    assert bad["bindpose_count"] == 4
    assert bad["invalid_pairs"] == 4
    assert bad["invalid_vertices"] == 4
    assert good["bone_count"] == 4
    assert good["bindpose_count"] == 4
    assert [row["name"] for row in suspicious] == ["parts_Hand_R_66"]
    assert drop_candidates(prefab, ASSETS) == {"parts_Hand_R_66"}


def check_no_false_positive():
    prefab = os.path.join(
        PREFABS, "2DModel_3P_ConstantiaS2_SS1.uAnim.prefab")
    _, suspicious = audit_prefab(prefab, ASSETS)
    by_name = {row["name"]: row for row in suspicious}
    hair = by_name.get("CS_parts_hair_3_36")
    assert hair is not None
    assert hair["invalid_pairs"] == 0
    assert drop_candidates(prefab, ASSETS) == set()


def main():
    check_banshee()
    check_no_false_positive()
    print("shared-skin audit tests OK")


if __name__ == "__main__":
    main()
