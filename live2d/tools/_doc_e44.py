# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E44 试过「把叠加发光烘焙进贴图」——对多数角色反而更差

思路（按要求）：moc3 v1 没有混合模式，那就把叠加/正片叠底的发光件烘焙成普通
alpha 贴图（`alpha_new = clamp(max(rgb)/255)`，RGB 直通），再按普通混合绘制。
实现见 `src/unity2live2d/convert/texture_bake.py`（只改该部件在图集里的矩形，
矩形互不重叠，所以不会影响别的部件）。

实测：

| 角色 | 跳过特效件（现方案） | 烘焙进贴图 |
| --- | --- | --- |
| WarWolf_NS1 | **0.976** | 0.171 |
| Scathy_N | **0.976** | 0.348 |
| Aeda_N | 0.749 | 0.746 |

结论：烟雾/横幅这类特效在 Unity 的「自然状态」截图里本来就几乎不可见，
烘成不透明只会变成更大的错块；Aeda 则完全没有改善。**已回退为「跳过」**。

### Aeda_N 为什么只能到 0.749

对比图（`Products\\_aeda_bake.png`）：我们的是**清晰的角色 + 圆环**，
Unity 自然截图是**整片泛光/发虚**的版本（大量加色 glow 叠加）。

- precision 0.955（我们画出来的几乎都对），recall 0.776（少了 22% 的泛光面积）；
- 这 22% 就是 Unity 里那层泛光，moc3 v1 无法表达；硬要匹配只能把泛光烘成
  大块半透明遮罩，那会让成品明显变脏，得不偿失。

当前全量：`>=0.85` 的角色 **156/157**，唯一例外就是 Aeda_N（0.749），
它属于「参考图本身带泛光」的评估偏差，而不是转换错误。
"""
if "E44" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
