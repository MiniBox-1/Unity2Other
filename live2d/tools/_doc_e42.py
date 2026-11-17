# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E42 RheinRitter 破案：UV 翻转只应作用于 Sprite 部件

定位链：

1. `tools\\invisible_parts.py` → RheinRitter 有 10 个部件渲染完全透明
   （`parts_Tail_*`、`parts_Gun_L_U`、`parts_GunHolder` …）；
2. `tools\\invisible_probe.py` → 这些部件在 page0 上采样到的区域 alpha 全 0；
3. 对比 Unity 的逐部件材质 dump：它们的贴图确实是 part2（page0），**页分配没错**；
4. 于是问题在 UV 本身：`_uvs_unity()` 之前对**所有非蒙皮部件**都翻转 V；
   但库里只有 **Sprite 自建四边形**是左上原点，`static`（MeshRenderer）部件
   本来就是 Unity 的左下原点 —— 被多翻了一次，采样就落到了透明区。

修复：`_uvs_unity` 只在 `p.kind == "sprite"` 时翻 V。

```text
RheinRitter  0.554 -> 0.917   （其余不变：Alexandra 0.968 / Brownie 0.962 / Khan 0.893）
```

### 全量结果（Unity 仅作测试集，转换不读任何真值）

```text
157/157 ok；validate 161/161；20,504 部件 / 21.2 MB
中位数 0.976（目标 >=0.97 ✓）
>=0.9: 150/157   >=0.8: 154   >=0.7: 156   >=0.5: 156

4 个目标角色全部达标：
  WarWolf_NS1    0.976
  Scathy_N       0.976
  Eternity_NS2   0.993
  RheinRitter_NS1 0.917
```

可复现：RheinRitter 重建 moc3 SHA256 = `cd6408f48ddce648`（与产品一致）。

余下低于 0.85 的（不在本目标范围）：`RoyalArsenal_NS1` 0.484（多画 UI 绿圆环）、
`Aeda_N` 0.749、`Banshee_NS1` 0.757。
"""
if "E42" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
