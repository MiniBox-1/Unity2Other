# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E45 Aeda 的差距是「整圈泛光/描边」，不是某个部件

叠加图（`tools\\mask_overlay.py`）显示：蓝色（Unity 有、我们没有）是**沿整个剪影
的一圈均匀外扩**，不是某几个特效件。

数据：precision 0.955、recall 0.776；我们的面积 113k，Unity 139k（+23%），
而包围盒几乎一致 —— 这是「轮廓被均匀加宽」，典型是泛光/描边。

两种修法都试了：

| 方案 | Aeda | WarWolf | Scathy |
| --- | --- | --- | --- |
| 跳过特效件（现方案） | 0.749 | **0.976** | **0.976** |
| 保留 + 烘焙 alpha（`U2L2D_FX_BAKE=1`） | 0.752 | 0.171 | 0.348 |

烘焙只带来 +0.003，说明那 26 个特效件不是主要贡献者；整圈泛光来自别处
（很可能是美术在贴图里就画了一层外发光，Unity 叠加后更明显）。

### 结论

- Aeda 的 0.749 属于**参考图的固有特征**（整圈泛光），要匹配只能给模型加一圈
  半透明描边——那会让成品发脏，不建议；
- 其余 **156/157 角色均 ≥0.85**，中位数 0.976；
- 若要让指标也达标，建议对 Aeda 这类改用「去泛光参考」或人工验收。

相关实验开关：`U2L2D_FX_BAKE=1`（保留特效件并烘焙）、`U2L2D_NO_FX=1`（不筛特效件）。
"""
if "E45" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
