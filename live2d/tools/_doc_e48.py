# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E48 读 `Assets\\Raw\\Scripts`：控制件的显隐是 Puppet2D 脚本用「精灵名」判的

脚本目录里与本问题相关的是 Puppet2D 那一套（AssetRipper 反编译）：

| 脚本 | 作用 |
| --- | --- |
| `Puppet2D_GlobalControl.cs` | 全局控制件显隐：`UpdateVisibility()` 按序列化开关设置 |
| `Puppet2D_HiddenBone.cs` | 只做朝向/缩放，不切显隐（34 个 `hiddenBone_*` 上挂的就是它） |
| `ActorPartsView.cs` / `Actor.cs` | 只剩序列化字段（反编译失败，是 Dummy），没有逻辑 |

关键在 `Puppet2D_GlobalControl`：

```csharp
foreach (SpriteRenderer r in this._Controls)
    r.enabled = this.ControlsVisiblity;        // 默认 0
foreach (SpriteRenderer r in this._FFDControls)
    r.transform.parent.gameObject.SetActive(this.FFD_Visiblity);  // 默认 0
```

而 `_Controls` / `_FFDControls` 是在 `TraverseHierarchy()` 里按**精灵名**收集的：

```csharp
if (component.sprite.name.Contains("Control")) this._Controls.Add(component);
else if (component.sprite.name.Contains("ffd")) this._FFDControls.Add(component);
```

prefab 里这些开关是序列化字段，可以直接读：

```text
2DModel_3P_Alice_NS1_DL_N.uAnim.prefab:
  ControlsVisiblity = 0   BonesVisiblity = 0   FFD_Visiblity = 0   ControlsEnabled = 1
```

**结论**：控制类部件（IK 圆环、控制柄等）的隐藏规则是
「精灵名含 `Control`/`ffd` 且 `ControlsVisiblity`/`FFD_Visiblity` 为 0」，
完全可以从 prefab + sprite 名静态判定 —— 这比现在的「控制组 + 命名」启发式更准确。

### 仍无法解释的部分

DL 变体里那几份 `FullBodyIMG_3P_Alice_NS1_part1_*`（18/26/26(1)/27）既没有挂脚本，
精灵名也不含 `Control`/`ffd`，但运行时只有 27 显示。它们由谁关掉，目前没在
`Raw\\Scripts` 里找到对应逻辑（`ActorPartsView` 的 `_listSwapDeactiveObject`
字段在本 prefab 上并不存在）。下一步要么继续找别的脚本（可能在
`Assets\\Scripts` 或 dll 里），要么按「展示变体」把这批排除。

### 下一步可落地项

用「精灵名 + GlobalControl 开关」替换现有 control-gizmo 规则，预计能：
- 更准确地剔除 IK 圆环类（RoyalArsenal 那批已经是 0.967，不会退化）；
- 减少对「控制组命名」的依赖。
"""
if "E48" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
