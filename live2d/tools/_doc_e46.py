# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E46 参考图取景 bug：Aeda 的 0.749 其实是「参考只有 40×45 像素」

评估脚本 `unity_snap_many.cs` 用 **全部 Renderer（含 inactive/禁用）** 的 bounds 取景，
Aeda 有一个巨大的 bounds 把角色压成了 40×45 像素的缩略图 —— 放大后自然「一圈虚边」，
于是 IoU 只有 0.749。之前 E45 推测的「整圈泛光」就是它。

修复：取景只用 `enabled && activeInHierarchy` 的渲染器。
重拍参考后：

```text
AGS_Aeda_N   0.749 -> 0.986
全量中位数   0.976 -> 0.977
```

### 顺带暴露出两个 `_DL_N` 变体的问题

同样被「缩略图参考」掩盖过的还有两个角色，重拍后：

```text
2DModel_3P_Alice_NS1_DL_N   0.435
2DModel_BR_Emily_NS1_DL_N   0.631
```

目检对比（`Products\\_alice_emily.png`）：我们的输出和 Unity 渲染的**根本不是同一个
造型**——说明这些 `_DL_N` 变体 prefab 里有多套部件/覆盖，我们的抽取挑错了子集
（与之前「备用姿势部件」类似，但更彻底）。这是下一轮要查的方向。

当前分布（修正参考后）：

```text
median 0.977   >=0.9: 152/157   >=0.8: 155/157   >=0.7: 155/157
最差：Alice_NS1_DL_N 0.435、Emily_NS1_DL_N 0.631、Leprechaun 0.861
```
"""
if "E46" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
