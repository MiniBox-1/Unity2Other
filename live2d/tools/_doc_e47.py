# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E47 `_DL_N` 变体：静态转换拿不到「脚本决定显示哪一份」

以 `2DModel_3P_Alice_NS1_DL_N` 为例：

- prefab 里 139 个 Renderer，Unity 运行时只有 **36 个 active**；
- 其中有多份重名的 `FullBodyIMG_3P_Alice_NS1_part1_*`（18 / 26 / 26(1) / 27 / 28），
  YAML 的 `m_IsActive` 除 28 外都是 1，但运行时只有 27 是显示的 —— 由脚本切换；
- 我们的 `disabled_transforms` 只按 YAML 判，拿到的是「YAML 上 active」的那批，
  其中 34 个 `hiddenBone_*` 已按命名剔除；最终剩下 35 件，与 Unity active 的 36 件
  只差 `face`（sprite 为空）。

但**渲染结果仍不是同一个造型**：Unity 显示的是「DL 新娘 + 场景（伞、花、水果）」，
我们显示的是 Base Alice（带翅膀）。可见差异来自「同名多份整图里选了哪一份」，
而这一选择是脚本在运行时做的。

试过的两种办法都不行：

| 方案 | Alice_DL_N | Emily_DL_N | Khan |
| --- | --- | --- | --- |
| 保持 disabled 过滤（现方案） | 0.435 | 0.631 | 0.898 |
| 不过滤（全收） | 0.298 | 0.645 | — |
| 同贴图+同 UV 去重（保留 sortingOrder 最高） | 0.435 | 0.631 | 0.884 |

结论：**这两个 DL 变体属于「脚本驱动的多套变体」**，只读 prefab 无法判定，
不适合作为静态转换的验收对象（其余 155/157 均 ≥0.85）。

当前全量：median 0.977、≥0.9 152/157、≥0.8 155/157、≥0.85 155/157。
"""
if "E47" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
