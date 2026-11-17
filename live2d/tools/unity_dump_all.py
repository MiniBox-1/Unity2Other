# -*- coding: utf-8 -*-
r"""Dump Unity bounds + baked world meshes for every character via MCP."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from unity_http_mcp import Client  # noqa: E402

TPL = (ROOT / "tools" / "unity_dump_many.cs").read_text(encoding="utf-8-sig")
REF = ROOT / "Products" / "_unity_ref"


def names():
    return sorted(p.name for p in (ROOT / "Products").iterdir()
                  if p.is_dir() and (p / f"{p.name}.model3.json").exists())


def main(batch=10):
    REF.mkdir(parents=True, exist_ok=True)
    done_file = REF / "_dump_done.json"
    done = json.loads(done_file.read_text(encoding="utf-8")) if done_file.exists() else []
    todo = [n for n in names() if n not in done]
    print(f"remaining {len(todo)}")
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
        print(f"batch {i // batch + 1}: {len(chunk)} -> {'ok' if ok else 'FAIL'}")
        if not ok:
            print(json.dumps(r)[:400])
            break
        done.extend(chunk)
        done_file.write_text(json.dumps(done), encoding="utf-8")
    print("done", len(done))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
