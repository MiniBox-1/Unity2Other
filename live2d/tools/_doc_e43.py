# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E43 UI/控制圆环：从「控制组 + 命名」判定（参考无关）

`RoyalArsenal_NS1` 多画的 3 个绿色圆环，查证过程：

1. `tools\\part_visibility.py` → 唯一可疑 drawable 是 `Part_01_IK_Bone_Foot_R_CTRL_28_bone_Foot`
   （hit=0.14、17927 px，正好是圆环）；
2. `tools\\unity_hier_dump.cs`（MCP）→ 该物体层级是
   `.../Global_CTRL/IK_Bone_Foot_R_CTRL_GRP/IK_Bone_Foot_R_CTRL`，
   且 **运行时 `active=False`**（prefab YAML 里 `m_IsActive: 1`，是脚本在运行时关掉的）；
3. 它们在 prefab 里是 `Global_CTRL` 控制组下的 IK 可视化物体。

规则（只读 prefab 层级与命名，不依赖真值）：**同时满足**
「祖先里有 `Global_CTRL` / `CTRL_IK` / `Controllers`」且「自身名字匹配
`^IK_|_IK_|_CTRL|_GRP$|_POLE|GIZMO`」才删除。

全量实测（先试过只按控制组，Banshee 整条骨骼都挂在 `Controllers` 下，误删 78 件，
已改用「控制组 + 命名」双条件）：

```text
RoyalArsenal_NS1  0.484 -> 0.967
Banshee_NS1       0.757 -> 0.984
Khan_N            0.893（不变）
全量：中位数 0.976；>=0.9 153/157；>=0.8 156/157；>=0.7 157/157
```

可复现：RoyalArsenal 重建 moc3 SHA256 = `1b1aa3c6f486ba03`（与产品一致）。

### Aeda_N 是另一类问题

`AGS_Aeda_N` 0.749：它的 `AE_parts_ball_*` / `parts_glow_*` 是叠加发光件
（Particles/Additive）。试过「不跳特效件」重建，IoU 仍是 0.749 —— 画成不透明
只会变成更大的错块；而 WarWolf 不跳会掉回 0.164。说明这是 **moc3 v1 无混合模式**
的固有限制，不属于本轮「UI 圆环」范畴。
"""
if "E43" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
