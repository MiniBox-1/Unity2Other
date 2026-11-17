# -*- coding: utf-8 -*-
r"""Dump Unity bounds+bake for specific characters."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from unity_http_mcp import Client  # noqa: E402

TPL = (ROOT / "tools" / "unity_dump_many.cs").read_text(encoding="utf-8-sig")


def run(names):
    arr = ",".join('"' + n + '"' for n in names)
    code = TPL.replace('new string[] { "2DModel_3P_Alexandra_N" }',
                       "new string[] { " + arr + " }")
    c = Client()
    c.init()
    r = c.request("tools/call", {"name": "execute_code",
                                 "arguments": {"action": "execute", "code": code}},
                  timeout=1800)
    print(json.dumps(r)[:400])


if __name__ == "__main__":
    run(sys.argv[1:])
