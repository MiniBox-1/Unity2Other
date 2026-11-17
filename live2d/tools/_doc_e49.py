# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "04_可行性验证记录.md"
s = p.read_text(encoding="utf-8")
add = """

## E49 DL 变体继续追：部件集合已对齐，差异在「姿势」

用 MCP 逐级追 `activeSelf`，确认 `Alice_NS1_DL_N` 里 4 份重名整图是被**父物体**关掉的：

```text
..._18  <-  Bone_tongue[0]                      YAML m_IsActive: 0
..._26  <-  2DModel_3P_Alice_NS1_BG[0]          YAML m_IsActive: 0
..._28  <-  自身 m_IsActive: 0
..._27  <-  全链 1（唯一显示）                  ← 我们保留的也正是它
```

`disabled_transforms()` 对这 4 份判定全部正确（`in_bad=True`），说明**过滤逻辑没问题**。

### 试了「默认动画 t=0 作为基准姿势」

新增开关 `U2L2D_REST_T0=1`（默认关闭）：

```text
Alice_NS1_DL_N    0.435 -> 0.589
Emily_NS1_DL_N    0.631 -> 0.631
Alexandra_N       0.968 -> 0.968   （无副作用）
```

改善明显但没到 0.85。

### 现在的判断

用 MCP 抓同一时刻的逐部件包围盒：我们 123 个部件与 Unity 的中位偏差
`|dx|=0.071`、`|dy|=0.132`（角色总高约 2 单位）；整体范围 x 2.63 × y 1.99，
与我们渲染的比例一致。也就是说**几何量级是对的，差的是局部姿势**（翅膀展开 vs 收拢）。

DL 这种「展示变体」把多套姿势/多份整图塞在一个 prefab 里，静态资源里没有
「该摆哪个姿势」的字段（默认状态 Start 没有 isActive 曲线，位置曲线只能给出 t=0）。

### 现状

```text
median 0.977   >=0.85: 155/157
Alice_NS1_DL_N 0.435（开 U2L2D_REST_T0 可到 0.589）
Emily_NS1_DL_N 0.631
```
"""
if "E49" not in s:
    s = s.rstrip() + add
p.write_text(s + "\n", encoding="utf-8")
print("ok")
