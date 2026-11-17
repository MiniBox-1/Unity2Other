# -*- coding: utf-8 -*-
r"""把历史工具里的**硬编码绝对路径**机械改写成经 `unity2spine.env.resolve(...)`
解析——这样代码本身不"写死"某个盘符位置，位置全部来自配置/环境变量/参数。

用法：
    python src/tools\deabs_paths.py            # 预览（不改文件）
    python src/tools\deabs_paths.py --apply    # 真的改

实现要点（2026-10-13 重写，避免误伤）：

* 用 `tokenize` 定位**真实的字符串字面量**，只在字面量上包裹 `_resolve(...)`，
  原字面量原样保留（含转义）⇒ 取值与改写前**完全一致**，只是多了一层位置解析；
* 跳过三引号（文档字符串/多行块）、已经包过的 `_resolve(...)`、含正则元字符的
  "看起来像路径其实是模式"的串；
* 只在 .py 上工作；bat/ps1/cs 需要手工——它们要被拷进 Unity 工程，
  走环境变量（见 `docs\自包含与位置约定.md`）。
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import re
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
DEFAULT_TARGETS = ("src/tools", "misc/legacy_gui", "src/unity2spine",
                   "src/ext_lo", "src/ext_bdone")

PATHISH = re.compile(r"^[A-Za-z]:[\\/]")
#: 这些字符**真实 Windows 路径里不会出现**（出现在字面量里就是正则/格式串）；
#: 注意**不**把 `\s` / `\d` / `\w` 算进来——`...\src`、`...\data` 这种是**真路径**，
#: 老版本把它们当正则跳过，结果 `D:\VB\Unity2Spine\src` 这类漏网。
REGEXISH = ("\\(", "?", "[", "]", "{", "}", "(?:", "|", "*")
BOOT = (
    "\n# --- lo_uncen2Spine: 位置解析（自动插入，见 src\\tools\\deabs_paths.py）--\n"
    "import os as _os\n"
    "import sys as _sys\n"
    "_ROOT = _os.path.dirname(_os.path.abspath(__file__))\n"
    "while _ROOT and not _os.path.isdir(_os.path.join(_ROOT, 'unity2spine')):\n"
    "    _ROOT = _os.path.dirname(_ROOT)\n"
    "if _ROOT and _ROOT not in _sys.path:\n"
    "    _sys.path.insert(0, _ROOT)\n"
    "from unity2spine.env import resolve as _resolve  # noqa: E402\n"
    "from unity2spine.paths import app_root as _app_root  # noqa: E402\n"
    "from unity2spine.console import fix_console as _fix_console  # noqa: E402\n"
    "_fix_console()\n"
    "# ---------------------------------------------------------------------\n"
)


def _offsets(text):
    lines = text.splitlines(keepends=True)
    off = [0] * (len(lines) + 1)
    for i, ln in enumerate(lines):
        off[i + 1] = off[i] + len(ln)
    return off


def _at(off, rc):
    row, col = rc
    return off[row - 1] + col


def boot_offset(text):
    """BOOT 头插入位置：模块文档字符串之后（`from __future__` 之上一行）。"""
    off = _offsets(text)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return 0
    for t in toks:
        if t.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING,
                      tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            continue
        if t.type == tokenize.STRING:
            return _at(off, t.end)
        break
    return 0


def rewrite(text):
    """返回 (新文本, 改写处数)。"""
    off = _offsets(text)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text, 0
    toks = [t for t in toks if t.type not in (tokenize.NL, tokenize.NEWLINE,
                                              tokenize.COMMENT)]
    # 1) 把**隐式拼接**的相邻字符串合成一段（老代码常把长路径折成两行）
    groups = []                                    # [(first_i, last_i)]
    i = 0
    while i < len(toks):
        if toks[i].type != tokenize.STRING:
            i += 1
            continue
        j = i
        while j + 1 < len(toks) and toks[j + 1].type == tokenize.STRING:
            gap = text[_at(off, toks[j].end):_at(off, toks[j + 1].start)]
            if gap.strip(" \t\r\n\\"):
                break
            j += 1
        groups.append((i, j))
        i = j + 1

    repls = []                                     # (start, end, new)
    for first, last in groups:
        parts = toks[first:last + 1]
        raw = text[_at(off, parts[0].start):_at(off, parts[-1].end)]
        if "\n" in parts[0].string or parts[0].string.startswith(
                ('"""', "'''")):
            continue                               # 多行/文档字符串
        vals, ok = [], True
        for t in parts:                            # 隐式拼接：逐段求值再拼
            pre = re.match(r"^([A-Za-z]{0,2})", t.string).group(1)
            if "f" in pre.lower():
                ok = False
                break                              # f-string 里有占位，跳过
            try:
                v = ast.literal_eval(t.string)
            except (ValueError, SyntaxError):
                ok = False
                break
            if not isinstance(v, str):
                ok = False
                break
            vals.append(v)
        if not ok:
            continue
        val = "".join(vals)
        if not PATHISH.match(val):
            continue
        if '"' in val or "'" in val or "\n" in val:
            continue
        if any(x in val for x in REGEXISH):
            continue                               # 正则/格式片段
        start, end = _at(off, parts[0].start), _at(off, parts[-1].end)
        before = text[:start].rstrip()
        if before.endswith("_resolve(") or before.endswith(".resolve("):
            continue                               # 已经包过
        repls.append((start, end, '_resolve(r"%s")' % val))
    if not repls:
        return text, 0
    out = []
    pos = 0
    for start, end, new in repls:
        out.append(text[pos:start])
        out.append(new)
        pos = end
    out.append(text[pos:])
    return "".join(out), len(repls)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--targets", default=",".join(DEFAULT_TARGETS))
    a = ap.parse_args()
    total = 0
    for t in [x for x in a.targets.split(",") if x]:
        base = os.path.join(ROOT, t)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in ("__pycache__",)]
            for f in fn:
                if not f.endswith(".py") or f in ("deabs_paths.py", "env.py"):
                    continue
                p = os.path.join(dp, f)
                raw = open(p, "rb").read()
                had_bom = raw.startswith(b"\xef\xbb\xbf")
                src = raw.decode("utf-8-sig", errors="replace")
                new, n = rewrite(src)
                if not n:
                    continue
                if "from unity2spine.env import resolve" not in new \
                        and "def resolve(" not in new:
                    ins = boot_offset(new)
                    new = new[:ins] + "".join(BOOT) + new[ins:]
                rel = os.path.relpath(p, ROOT)
                print("  %-56s 改写 %d 处" % (rel, n))
                total += n
                if a.apply:
                    io.open(p, "w", newline="\n",
                            encoding="utf-8-sig" if had_bom else "utf-8"
                            ).write(new)
    print("%s：共 %d 处"
          % ("已改完" if a.apply else "预览（加 --apply 才写）", total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
