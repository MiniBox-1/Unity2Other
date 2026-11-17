# -*- coding: utf-8 -*-
r"""Regenerate the nat/bind snapshot variants from unity_snap_many.cs."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = (ROOT / "tools" / "unity_snap_many.cs").read_text(encoding="utf-8-sig")

nat = base.replace(
    "    foreach (var t in go.GetComponentsInChildren<UnityEngine.Transform>(true)) t.gameObject.SetActive(true);\n", "")
nat = nat.replace(
    "    foreach (var r0 in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) r0.enabled = true;\n", "")
nat = nat.replace("_unity_ref", "_unity_ref_nat")
(ROOT / "tools" / "unity_snap_nat.cs").write_text(nat, encoding="utf-8")

bind = nat.replace("_unity_ref_nat", "_unity_ref_bind")
bind = bind.replace(
    "    var rs = go.GetComponentsInChildren<UnityEngine.Renderer>(true);",
    "    foreach (var an in go.GetComponentsInChildren<UnityEngine.Animator>(true)) an.enabled = false;\n"
    "    var rs = go.GetComponentsInChildren<UnityEngine.Renderer>(true);")
(ROOT / "tools" / "unity_snap_bind.cs").write_text(bind, encoding="utf-8")
print("regenerated nat/bind snapshot scripts")
