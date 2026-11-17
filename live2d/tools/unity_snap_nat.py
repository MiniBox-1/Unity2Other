# -*- coding: utf-8 -*-
r"""Render Unity 'natural state' snapshots (respect prefab active/enabled flags)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from unity_http_mcp import Client  # noqa: E402

TPL = (ROOT / "tools" / "unity_snap_many.cs").read_text(encoding="utf-8-sig")
TPL = TPL.replace(
    "    foreach (var t in go.GetComponentsInChildren<UnityEngine.Transform>(true)) t.gameObject.SetActive(true);\n", "")
TPL = TPL.replace(
    "    foreach (var r0 in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) r0.enabled = true;\n", "")
TPL = TPL.replace("_unity_ref", "_unity_ref_nat")


def run(names):
    code = TPL.replace('new string[] { "2DModel_3P_Alexandra_N" }',
                       "new string[] { " + ",".join('"' + n + '"' for n in names) + " }")
    c = Client()
    c.init()
    r = c.request("tools/call", {"name": "execute_code",
                                 "arguments": {"action": "execute", "code": code}},
                  timeout=1800)
    ok = '"isError": false' in str(r)
    print("ok" if ok else "FAIL", str(r)[:300])
    return ok


if __name__ == "__main__":
    names = sys.argv[1:] or [
        "2DModel_BR_Alvis_NS1_DL_N", "2DModel_BR_Brownie_NS1",
        "2DModel_BR_Khan_N", "2DModel_BR_WarWolf_NS1",
        "2DModel_BR_RoyalArsenal_NS1"]
    run(names)
