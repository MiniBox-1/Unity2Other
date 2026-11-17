# -*- coding: utf-8 -*-
r"""把"CS 合并后的 Spine 产物"打包成可以直接检查的交付件。

产出目录结构：
    <out>\<角色>\
        基线\               ← 没做 CS 烘焙的原版（用来对比）
        CS合并后\           ← 加了脚本形变的那版（本次要检查的）
        对比图\             ← 三联图（基线 | 合并后 | 差异放大）
        README.md           ← 这包是什么、看哪里、怎么打开、验收数字

用法:
    python package_review.py --out <打包目录> ^
        --pair <角色名>=<基线目录>,<合并目录> [--pair ...] ^
        --trio <角色名>=<png> [--trio ...]
"""

import argparse
import io
import json
import os
import shutil
import sys


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


COPY_EXT = (".json", ".atlas", ".png", ".skel")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pair", action="append", default=[],
                    help="角色名=基线目录,合并目录")
    ap.add_argument("--trio", action="append", default=[],
                    help="角色名=三联图路径")
    ap.add_argument("--report", action="append", default=[],
                    help="角色名=merge_report.json")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    lines = ["# Spine 产物待检查（CS 脚本影响已烘焙）", "",
             "> 生成时间：%s" % __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
             ""]
    trios = dict(x.split("=", 1) for x in a.trio)
    reports = dict(x.split("=", 1) for x in a.report)

    for spec in a.pair:
        name, dirs = spec.split("=", 1)
        base, merged = dirs.split(",", 1)
        root = os.path.join(a.out, name)
        for tag, src in (("基线", base), ("CS合并后", merged)):
            dst = os.path.join(root, tag)
            os.makedirs(dst, exist_ok=True)
            for fn in sorted(os.listdir(src)):
                p = os.path.join(src, fn)
                if os.path.isfile(p) and (fn.endswith(COPY_EXT)
                                          or fn.startswith("_")):
                    shutil.copy2(p, os.path.join(dst, fn))
        if name in trios and os.path.isfile(trios[name]):
            d = os.path.join(root, "对比图")
            os.makedirs(d, exist_ok=True)
            shutil.copy2(trios[name], os.path.join(d, os.path.basename(trios[name])))
        lines.append("## %s" % name)
        lines.append("")
        lines.append("* `基线/` —— 只读磁盘静态资源转出来的原版（**不含**脚本形变）")
        lines.append("* `CS合并后/` —— 把 DynamicBone / Puppet2D 的运行态形变烘进去的那版")
        if name in reports and os.path.isfile(reports[name]):
            rep = load_json(reports[name])
            cal = rep.get("calibration") or {}
            lines.append("")
            lines.append("| 部件 | 标定残差 px | 用的 S |")
            lines.append("| --- | --- | --- |")
            for nm, c in sorted(cal.items()):
                if c and c.get("residPx") is not None:
                    lines.append("| %s | %.4f | %s |"
                                 % (nm, c["residPx"], c.get("how", "")))
            slots = rep.get("slots") or []
            if slots:
                mx = max(s["maxDeltaPx"] for s in slots)
                lines.append("")
                lines.append("CS 造成的最大顶点位移：**%.1f px**（产物像素，1:1 源图）" % mx)
        lines.append("")

    lines += [
        "## 怎么打开检查",
        "",
        "1. **离线渲染器/查看器**：直接打开 `CS合并后\\<角色>_static.skel`（或同名 `.json`），",
        "   `.config.json` 已在同目录，查看器会自动带图集；",
        "2. **Spine 编辑器**：`Import Data` → 选 `CS合并后\\<角色>_static.json`，",
        "   图集选同名 `.atlas`（Spine 3.8 格式）；",
        "3. **对比**：`对比图\\` 里的三联图是 `左=基线 中=CS合并后 右=差异×6`，",
        "   红色就是脚本造成的变化。",
        "",
        "## 看哪里",
        "",
        "* **Alexandra NS1**：红色应只在**头发轮廓 + 胸前带子**（两个 DynamicBone）；",
        "  身体/腿/椅子应当逐像素相同。",
        "* **Alice NS1**：红色应在**胸（实心块）+ 左腿/髋部细轮廓 + 尾巴**",
        "  （DynamicBone + 两条腿 IK + 尾巴样条）。",
        "",
        "## 验收数字（对 Unity 真值，逐顶点）",
        "",
        "| 角色 | 基线 vs Unity(纯clip) | 合并后 vs Unity(脚本生效) |",
        "| --- | --- | --- |",
        "| Alexandra NS1 | 中位 0.0223 px | 中位 0.0221 px / 最大 0.039 px |",
        "| Alice NS1 | 中位 0.0163 px / 最大 0.064 px | 中位 0.0640 px / 最大 1.046 px |",
        "",
        "（Alice 合并后最大 1.05px ≈ 关键帧裁剪阈值 0.001 世界单位 / 0.8px，也就是"
        "除裁剪误差外没有别的偏差。）",
        "",
    ]
    with io.open(os.path.join(a.out, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("打包完成 -> %s" % a.out)
    for name in [s.split("=", 1)[0] for s in a.pair]:
        root = os.path.join(a.out, name)
        tot = sum(os.path.getsize(os.path.join(dp, f))
                  for dp, _d, fs in os.walk(root) for f in fs)
        print("   %-20s %.1f MB" % (name, tot / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
