# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E51 最低的三个（Amy 0.877 / Leprechaun 0.884 / Khan 0.898）是「预览渲染分辨率」不够

### 定位过程

- `mask_stats`：三者 precision≈recall≈0.93~0.95，**面积几乎相等**
  （Amy 53360 vs 53358），说明不是多画/少画，而是整体错位/边缘差异；
- `part_visibility`：没有可疑部件（`hit<0.15` 为 0）；
- `align_probe.py`：允许整体平移几像素后 IoU 大涨

```text
Amy          0.877 --(+3px)--> 0.973
Leprechaun   0.884 --(+4px)--> 0.980
Khan         0.898 --(+2px)--> 0.948
```

- 叠加图（`Products\\_align_amy.png`）几乎全是重合灰色，只剩一圈 1px 红/蓝边 —— 典型的**边缘走样**。

### 根因

我们的 `preview.png` 一直是 **512 高**渲染的，细长角色（Amy/Leprechaun/Khan 都很瘦）
在这个尺度下边缘锯齿明显；参考图是 768 高、且 Unity 自身有 AA。

`tools\\res_probe.py` 直接验证：

| 角色 | 512 | 1024 | 2048 |
| --- | --- | --- | --- |
| Amy | 0.877 | **0.986** | 0.988 |
| Leprechaun | 0.884 | **0.978** | 0.982 |
| Khan | 0.898 | **0.950** | 0.953 |

### 处理

新增 `tools\\render_previews.py <高度>`，全量按 **1024** 重渲染预览后再跑审计：

```text
median 0.977 -> 0.986
min    0.877 -> 0.949
>=0.9: 157/157   >=0.8: 157/157
最差三个：Gnome_NS2 0.949、Gnome_NS2_DL_N 0.949、Khan 0.950
```

**结论：产品本身没问题，之前的低分是「预览太糙」导致的自测偏低。**
"""
if "E51" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
