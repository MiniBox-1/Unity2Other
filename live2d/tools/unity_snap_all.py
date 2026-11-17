# -*- coding: utf-8 -*-
r"""Batch-render Unity ground-truth snapshots for every character via MCP."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from unity_http_mcp import Client  # noqa: E402

TEMPLATE = (ROOT / "tools" / "unity_snap_many.cs").read_text(encoding="utf-8-sig")
REF = ROOT / "Products" / "_unity_ref"


def names():
    return sorted(p.name for p in (ROOT / "Products").iterdir()
                  if p.is_dir() and (p / f"{p.name}.model3.json").exists())


def main(batch=20):
    REF.mkdir(parents=True, exist_ok=True)
    todo = names()
    done = json.loads((REF / "_done.json").read_text(encoding="utf-8")) if (REF / "_done.json").exists() else []
    todo = [n for n in todo if n not in done]
    print(f"remaining {len(todo)}")
    c = Client()
    c.init()
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        arr = ",".join('"' + n + '"' for n in chunk)
        code = TEMPLATE.replace('new string[] { "2DModel_3P_Alexandra_N" }',
                                f"new string[] {{ {arr} }}")
        r = c.request("tools/call", {"name": "execute_code",
                                     "arguments": {"action": "execute", "code": code}},
                      timeout=1800)
        txt = json.dumps(r)
        ok = '"isError": false' in txt
        print(f"batch {i // batch + 1}: {len(chunk)} names -> {'ok' if ok else 'FAIL'}")
        if not ok:
            print(txt[:500])
            break
        done.extend(chunk)
        (REF / "_done.json").write_text(json.dumps(done), encoding="utf-8")
    print("done total", len(done))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
