# -*- coding: utf-8 -*-
r"""Dump Unity renderer bounds (natural state) for a list of characters."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from unity_http_mcp import Client  # noqa: E402

TPL = (ROOT / "tools" / "unity_bounds.cs").read_text(encoding="utf-8-sig")
TPL = TPL.replace(
    "foreach (var t in go.GetComponentsInChildren<UnityEngine.Transform>(true)) t.gameObject.SetActive(true);\n", "")
TPL = TPL.replace(
    "foreach (var r0 in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) r0.enabled = true;\n", "")
# 支持多名字：把 name 从硬编码改成数组循环
TPL = TPL.replace('string name = "2DModel_BR_Khan_N";',
                  'string[] allNames = new string[] { "2DModel_BR_Khan_N" };')
BODY_START = 'string outPath = @"D:\\VB\\Unity2Live2D\\Products\\_unity_ref\\" + name + ".bounds.json";'


def build(names):
    arr = ",".join('"' + n + '"' for n in names)
    code = TPL.replace('new string[] { "2DModel_BR_Khan_N" }', "new string[] { " + arr + " }")
    # 包一层循环
    lines = code.splitlines()
    head = []
    body = []
    seen_prefab = False
    for ln in lines:
        if ln.startswith("var prefab ="):
            seen_prefab = True
        if seen_prefab:
            body.append(ln)
        else:
            head.append(ln)
    wrapped = []
    wrapped.extend(head)
    wrapped.append("int okCount = 0;")
    wrapped.append("foreach (var name in allNames) {")
    wrapped.extend(["    " + b for b in body])
    wrapped.append("    okCount++;")
    wrapped.append("}")
    wrapped.append('return "done=" + okCount;')
    return "\n".join(wrapped)


def run(names):
    c = Client()
    c.init()
    r = c.request("tools/call", {"name": "execute_code",
                                 "arguments": {"action": "execute", "code": build(names)}},
                  timeout=1800)
    print(str(r)[:400])


if __name__ == "__main__":
    run(sys.argv[1:] or ["2DModel_BR_Brownie_NS1"])
