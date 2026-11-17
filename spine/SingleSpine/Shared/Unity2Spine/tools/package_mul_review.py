# -*- coding: utf-8 -*-
r"""把"用到非普通混合材质"的角色产物打包成一个**给人肉眼看**的文件夹 + README。

用途（2026-10-10 用户指令）：观感 / shader / 颜色这类问题**不跟 Unity 比**，
直接把产物摊开让用户肉眼看 —— 眼睛看没问题就是没问题。

用法:
    python tools\package_mul_review.py --list <清单.txt> --out <交付文件夹> \
        [--src <产物根>]

清单由 `python tools\shader_usage_inventory.py --out-txt <文件>` 生成。
每个角色目录按标准口径打包（`.skel` + `.atlas` + 图集 PNG + `<目录名>.config.json`
+ `_static_info.json` + `README.md`），**不带 `.json`**（Debug 件）。
"""

import argparse
import io
import json
import os
import shutil
import sys

SRC_DEFAULT = r"D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv_cs_port"


def load(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def fmt_names(names, cap=8):
    """列部件名：多了就省略，别让 README 变成一堵墙（Daphne 有 233 个加色件）。"""
    if not names:
        return "—"
    head = "、".join("`%s`" % n for n in names[:cap])
    return head if len(names) <= cap else "%s 等 **%d** 个" % (head, len(names))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, help="角色清单（一行一个名字）")
    ap.add_argument("--out", required=True, help="交付文件夹")
    ap.add_argument("--src", default=SRC_DEFAULT)
    a = ap.parse_args()

    names = []
    for line in io.open(a.list, encoding="utf-8-sig"):
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)

    os.makedirs(a.out, exist_ok=True)
    rows = []
    for n in names:
        s = os.path.join(a.src, n)
        d = os.path.join(a.out, n)
        if not os.path.isdir(s):
            print("[skip] 产物不在: %s" % s)
            continue
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
        kept = 0
        for fn in os.listdir(s):
            if fn.endswith("_static.json"):
                continue                      # 不带 Debug 用的骨架 JSON
            # 注意：`_static_info.json`（对账手册）**要带**，它不是 "_static.json" 后缀，
            # 早先的 `endswith(".json")` 把它一起跳过了（README 里乘法件数全是 0）。
            src_p, dst_p = os.path.join(s, fn), os.path.join(d, fn)
            if os.path.isdir(src_p):
                shutil.copytree(src_p, dst_p)     # 例：_calib\static_check.json
                continue
            shutil.copy2(src_p, dst_p)
            kept += 1
        info_p = os.path.join(d, "_static_info.json")
        mul = add = []
        if os.path.isfile(info_p):
            info = load(info_p)
            mul = [m["part"] for m in ((info.get("multiply") or {})
                                       .get("parts") or [])]
            add = [p["name"] for p in (info.get("partsMeta") or [])
                   if p.get("blend") == "additive"]
        rows.append((n, mul, add, kept))
        print("%-48s 文件 %2d  乘法件 %d  加色件 %d" % (n, kept, len(mul), len(add)))

    lines = [
        "# 乘法/加色件 —— 肉眼检查包（2026-10-10）",
        "",
        "这一包里全是**用到非普通混合材质**的角色（`Legacy Shaders/Particles/Multiply`、",
        "`Particles/Additive` 等）。**默认口径已经改了**：乘法件不再依赖运行时的 multiply",
        "混合，而是**直接烘进图集**（该件 UV 矩形内 texel 改成 `黑 + α=1−m`），槽位走普通混合。",
        "",
        "## 怎么打开",
        "",
        "每个角色目录里有 `<目录名>.config.json`，用查看器/编辑器直接打开即可（读 `.skel`）。",
        "参考图集页：`<角色>.uAnim_static_*.png`（带 `_mul` 后缀的是乘法件裁出来的小页）。",
        "",
        "## 该看什么",
        "",
        "* **影子**：应该是「把背景压暗一点的半透明影子」，**不是**浅粉/白色的一块、也不是完全不透明的实体；",
        "  位置、形状跟着身体走。",
        "* **加色件**（特效/发光）：应该发亮叠加，不能变成一块暗的。",
        "* 影子/特效的**边缘**：不应出现 1px 的浅色接缝（本轮修掉过这个）。",
        "",
        "## 已知特例（不用当问题）",
        "",
        "* `2DModel_PECS_Babariana_NS1` 的 `parts_004_shadow acc_skinned_21`：该件贴图区域是**纯白**，",
        "  Unity 里 `dst×1` 本来就不改画面 ⇒ 产物里它是**完全透明**的（忠实结果）。",
        "",
        "## 逐角色明细",
        "",
        "| 角色 | 乘法件（已烘进图集） | 加色件 |",
        "| --- | --- | --- |",
    ]
    for n, mul, add, _k in rows:
        lines.append("| `%s` | %s | %s |"
                     % (n, fmt_names(mul), fmt_names(add)))
    lines += [
        "",
        "## 发现不对时怎么反馈",
        "",
        "按「角色 + 部件名 + 什么动画/时刻 + 看到什么 + Unity 里应该什么样」写给我；",
        "**观感问题我直接改烘法**；**如果是运动/骨骼不对**，那就按约定**拉 Unity 真值**再对。",
        "",
    ]
    with io.open(os.path.join(a.out, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n交付文件夹: %s（%d 个角色）" % (a.out, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
