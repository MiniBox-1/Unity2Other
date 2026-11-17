# -*- coding: utf-8 -*-
r"""Dump per-part material/shader info for every character via MCP."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from unity_http_mcp import Client  # noqa: E402

TPL = (ROOT / "tools" / "unity_mat_dump.cs").read_text(encoding="utf-8-sig")
TPL = TPL.replace(
    'new string[] { "2DModel_BR_WarWolf_NS1", "2DModel_BR_Scathy_N", '
    '"2DModel_3P_Eternity_NS2", "2DModel_AGS_RheinRitter_NS1" }',
    'new string[] { "2DModel_3P_Alexandra_N" }')
REF = ROOT / "Products" / "_unity_ref"


def names():
    return sorted(p.name for p in (ROOT / "Products").iterdir()
                  if p.is_dir() and (p / f"{p.name}.model3.json").exists())


def main(batch=12):
    todo = [n for n in names() if not (REF / f"{n}.mats.json").exists()]
    print("remaining", len(todo), flush=True)
    c = Client()
    c.init()
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        arr = ",".join('"' + n + '"' for n in chunk)
        code = TPL.replace('new string[] { "2DModel_3P_Alexandra_N" }',
                           "new string[] { " + arr + " }")
        r = c.request("tools/call", {"name": "execute_code",
                                     "arguments": {"action": "execute", "code": code}},
                      timeout=1800)
        ok = '"isError": false' in json.dumps(r)
        print(f"batch {i // batch + 1}: {len(chunk)} -> {'ok' if ok else 'FAIL'}", flush=True)
        if not ok:
            print(json.dumps(r)[:300])
            break


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12)
