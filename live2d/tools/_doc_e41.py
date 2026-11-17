# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E41 修掉一个真 bug：动画采样的「位置」一直丢失

`anim_world.rest_dict()` 只填了 quat/scale，**没填 px/py/pz**，于是
`AnimSampler.sample()` 里 `p.get("px", 0)` 恒为 0 —— 所有按动画采样的世界矩阵
都把骨骼放到了原点。影响面：

- 分块（P4）的「动作真值」帧一直是错的；
- 之前 E25「t=0 当基准姿势」失败也是这个原因（不是思路错）。

补上位置后，用同一时刻对比：**我们的 t=0 姿态与 Unity 逐部件包围盒中心偏差 0.000**
（`tools\\pose_match.py`）。

### 用它当基准姿势？实测不划算

修好后试过把「默认动画 t=0」当基准重建：

```text
RheinRitter  0.554（无变化）
Khan         0.896 -> 0.710（变差）
Alexandra    0.968（不变）
Brownie      0.962（不变）
```

说明这些角色 prefab 里存的姿势本来就等于 t=0；故仍用 bind pose（已回退）。

### 重新全量后的数据

```text
157/157 ok；validate 161/161；20,504 部件（分块因真值修正而变化）
中位数 0.975   >=0.9: 144/157   >=0.8: 149   >=0.7: 154   >=0.5: 156
```

### RheinRitter 的下一个具体线索

`tools\\invisible_parts.py` 显示它有 **10 个部件在渲染里完全透明**
（`parts_Tail_*`、`parts_Gun_L_U`、`parts_GunHolder` 等）——即位置对、但采样到了
透明像素。这指向**纹理页/UV 归属**问题，而不是姿势。
"""
if "E41" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
