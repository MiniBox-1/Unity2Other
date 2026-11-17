# -*- coding: utf-8 -*-
r"""自包含审计：扫出项目里**硬编码绝对路径**（`X:\...`）的代码。

要求（2026-10-13 用户）：D:\VB\lo_uncen2Spine 的代码不允许依赖该文件夹以外的
文件 ⇒ 代码里不该出现会**被执行**的绝对路径；位置一律走
`lo_uncen2Spine.json` + `unity2spine.paths.cfg()` / `unity2spine.env.resolve()`
/ 命令行参数 / 环境变量。

判定口径（避免误报）：
  * `.py`：用 `tokenize` 只看**真实字符串字面量**——注释、文档字符串不算；
    已经包在 `_resolve(...)` / `.resolve(...)` 里的不算（位置已可配）；
    看似正则/格式片段（含 `\s \d ? [ {` 等）不算。
  * `.cs/.ps1/.bat`：逐行，跳过注释行（`//` `#` `REM` `::` `*`）。
  * 白名单：`unity2spine/env.py`（老路径→配置的**映射表**，是设计）、
    本文件、`tools/deabs_paths.py`（改写器自己的模式）。

用法：python src/tools\scan_abspaths.py [--root .] [--show 40]
退出码：0 = 干净；1 = 有硬编码绝对路径。
"""
from __future__ import annotations

# --- lo_uncen2Spine: 位置解析（自动插入，见 src/tools\deabs_paths.py）--
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while _ROOT and not _os.path.isdir(_os.path.join(_ROOT, 'unity2spine')):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT and _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from unity2spine.env import resolve as _resolve  # noqa: E402
from unity2spine.console import fix_console as _fix_console  # noqa: E402
_fix_console()
from unity2spine.paths import app_root as _app_root  # noqa: E402
# ---------------------------------------------------------------------

import argparse
import io
import os
import re
import tokenize

CODE_EXT = (".py", ".bat", ".ps1", ".cs")
SKIP_DIRS = {"__pycache__", "dist", ".git", "build", "venv", ".venv",
             "env", "deps", "examples", ".cache"}
SKIP_FILES = {"src/unity2spine/env.py", "src/tools/scan_abspaths.py",
              "src/tools/deabs_paths.py"}
PATH_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/][^\s\"'\);,\]}]+")
#: 真实 Windows 路径里不会出现的字符（出现即视为正则/格式串）。
#: 特意**不**含 `\s` / `\d` / `\w`：`...\src`、`...\data` 是真路径，不是正则。
REGEXISH = ("\\(", "?", "[", "]", "{", "}", "(?:", "|", "*")
COMMENT_START = ("//", "#", "REM", "rem", "::", "*", "/*")


def _offsets(text):
    lines = text.splitlines(keepends=True)
    off = [0] * (len(lines) + 1)
    for i, ln in enumerate(lines):
        off[i + 1] = off[i] + len(ln)
    return off


def _keep(s: str) -> bool:
    if "%CD%" in s or "%~dp0" in s:
        return False
    return not any(x in s for x in REGEXISH)


def scan_py(path: str):
    text = io.open(path, encoding="utf-8", errors="replace").read()
    off = _offsets(text)
    hits = set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return sorted({m.group(0) for m in PATH_RE.finditer(text)})
    for t in toks:
        if t.type != tokenize.STRING:
            continue
        s = t.string
        if "\n" in s or s.startswith('"""') or s.startswith("'''"):
            continue                                        # 文档字符串
        start = off[t.start[0] - 1] + t.start[1]
        if text[:start].rstrip().endswith(("_resolve(", ".resolve(",
                                           "resolve(")):
            continue                                        # 已走位置解析
        for m in PATH_RE.finditer(s):
            if _keep(m.group(0)):
                hits.add(m.group(0))
    return sorted(hits)


def scan_text(path: str):
    hits = set()
    for line in io.open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if not s or s.startswith(COMMENT_START):
            continue
        for m in PATH_RE.finditer(line.split("//")[0]):
            if _keep(m.group(0)):
                hits.add(m.group(0))
    return sorted(hits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=_app_root())
    ap.add_argument("--show", type=int, default=40)
    a = ap.parse_args()
    hits, total = {}, 0
    for dp, dn, fn in os.walk(a.root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if not f.endswith(CODE_EXT):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, a.root).replace("\\", "/")
            if rel in SKIP_FILES:
                continue
            found = scan_py(p) if f.endswith(".py") else scan_text(p)
            if found:
                hits[rel] = found
                total += len(found)
    print("扫描根：%s" % a.root)
    print("含硬编码绝对路径的代码文件 %d 个（%d 处）" % (len(hits), total))
    for k in sorted(hits)[:a.show]:
        print("  %-56s %s" % (k, hits[k][:3]))
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
