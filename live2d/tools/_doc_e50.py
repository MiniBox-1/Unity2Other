# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E50 真正的元凶：参考图把「编辑器当前场景」也拍进去了

`unity_snap_*.cs` 是直接在**当前打开的场景**里 Instantiate 再 `cam.Render()`。
如果编辑器场景里本来就摆着别的展示内容（大厅/展示台），它会被一起拍进参考图。
`Alice_NS1_DL_N` 的参考图里那个「婚纱新娘 + 伞 + 花」就是这么来的——**根本不是该角色**。

修复：实例化的角色全部放到 **layer 31**，相机 `cullingMask = 1 << 31`，只拍角色本身。

全量重拍 157 张后：

```text
min = 0.877   median = 0.977
>=0.9: 154/157   >=0.8: 157/157   >=0.7: 157/157

Alice_NS1_DL_N   0.435 -> 0.971
Emily_NS1_DL_N   0.631 -> 0.987
Aeda_N           0.749 -> 0.986
WarWolf 0.976 / Scathy 0.976 / Eternity 0.993 / RheinRitter 0.990
RoyalArsenal 0.968 / Banshee 0.984
最差三个：Amy 0.877、Leprechaun 0.884、Khan 0.898
```

也就是说：**转换本身早就是对的**，之前那两个「展示变体」的失败完全是测试集的取景污染。
DL 变体的部件过滤（`hiddenBone`、父物体 inactive）本来就判定正确（E49 已验证）。
"""
if "E50" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
