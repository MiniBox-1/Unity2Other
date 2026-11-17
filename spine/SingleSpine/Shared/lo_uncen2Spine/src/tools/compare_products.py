# -*- coding: utf-8 -*-
r"""产物一致性对比：新旧两批产物**逐文件比 MD5**，出一份 markdown 报告。

用途：重整/改代码之后，确认"转出来的 Spine 结果和原来一模一样"
（`--ref` 指老代码的产物目录，`--new` 指新跑的目录）。

用法：
    python src/tools\compare_products.py ^
        --ref "<老产物根>" --new "<新产物根>" ^
        [--chars-file misc\verification\chars.txt] ^
        [--skip _calib] [--out misc\verification\一致性对比.md]

判定：每个角色一个子目录，比同名文件的 MD5；`--skip` 里的子目录名整棵跳过
（例：`_calib\static_check.json` 里写着绝对路径，天然不同）。
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
from unity2spine.paths import app_root as _app_root  # noqa: E402
from unity2spine.console import fix_console as _fix_console  # noqa: E402
_fix_console()
# ---------------------------------------------------------------------

import argparse
import hashlib
import io
import os
import time


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def walk_files(root, skip=()):
    """返回 {相对路径: 字节数}（`skip` 里的**目录名或文件名**整棵跳过）。"""
    out = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f in skip:
                continue
            p = os.path.join(dirpath, f)
            out[os.path.relpath(p, root)] = os.path.getsize(p)
    return out


def read_chars(path):
    chars = []
    for ln in io.open(path, encoding="utf-8-sig"):
        ln = ln.split("#", 1)[0].strip()
        if ln:
            chars.append(ln)
    return chars


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="老（基准）产物根")
    ap.add_argument("--new", required=True, help="新跑出来的产物根")
    ap.add_argument("--chars-file", default="",
                    help="只比这些角色（每行一个，可带 # 注释）")
    ap.add_argument("--skip", default="_calib",
                    help="整棵跳过的子目录名，逗号分隔")
    ap.add_argument("--out", default="", help="markdown 报告写到哪儿")
    a = ap.parse_args(argv)
    skip = tuple(s.strip() for s in a.skip.split(",") if s.strip())
    if a.chars_file and os.path.isfile(a.chars_file):
        chars = read_chars(a.chars_file)
    else:
        # 不给清单就比"基准里的全部**角色目录**"（根目录下的散落文件，
        # 例如早期手工跑的 `_qc_*.json`，不算角色）
        chars = sorted(d for d in os.listdir(a.ref)
                       if os.path.isdir(os.path.join(a.ref, d)))
    lines = ["# 产物一致性对比（MD5）", "",
             "- 基准（`--ref`）：`%s`" % a.ref,
             "- 新产物（`--new`）：`%s`" % a.new,
             "- 跳过：%s（内容含绝对路径，天然不同）" % (", ".join(skip) or "无"),
             "- 时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"), "",
             "| 角色 | 文件 | 基准 MD5 | 新 MD5 | 判定 |",
             "| --- | --- | --- | --- | --- |"]
    same = diff = missing = 0
    bad_chars = []
    for c in chars:
        r, n = os.path.join(a.ref, c), os.path.join(a.new, c)
        if not os.path.isdir(r):
            lines.append("| `%s` | — | — | — | **缺基准** |" % c)
            missing += 1
            continue
        if not os.path.isdir(n):
            lines.append("| `%s` | — | — | — | **缺新产物** |" % c)
            missing += 1
            bad_chars.append(c)
            continue
        fr, fn = walk_files(r, skip), walk_files(n, skip)
        for k in sorted(set(fr) | set(fn)):
            if k not in fn or k not in fr:
                which = "新产物缺文件" if k not in fn else "基准缺文件"
                lines.append("| `%s` | `%s` | — | — | **%s** |" % (c, k, which))
                missing += 1
                bad_chars.append(c)
                continue
            h1, h2 = md5(os.path.join(r, k)), md5(os.path.join(n, k))
            ok = h1 == h2
            same += ok
            diff += (not ok)
            if not ok:
                bad_chars.append(c)
            lines.append("| `%s` | `%s` | `%s` | `%s` | %s |"
                         % (c, k, h1[:12], h2[:12],
                            "**相同**" if ok else "**不同**"))
    lines += ["", "## 汇总", "",
              "- 相同 **%d** 个文件，不同 **%d** 个，缺失 **%d** 个"
              % (same, diff, missing),
              "- 涉及不一致的角色：%s" % (", ".join(sorted(set(bad_chars))) or "无"),
              "- 结论：%s" % ("**逐字节一致**"
                              if (diff == 0 and missing == 0) else "**有差异，需要排查**")]
    text = "\n".join(lines) + "\n"
    if a.out:
        d = os.path.dirname(os.path.abspath(a.out))
        if d:
            os.makedirs(d, exist_ok=True)
        io.open(a.out, "w", encoding="utf-8", newline="\n").write(text)
        print("报告写到 %s" % a.out)
    print("相同 %d / 不同 %d / 缺失 %d" % (same, diff, missing))
    return 0 if (diff == 0 and missing == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
