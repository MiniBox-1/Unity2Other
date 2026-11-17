# 副 Animator 的显隐曲线修复（2026-09-14）

## 问题

带副 Animator 的角色（daphne 的左右翅膀、aeda 的 `star_deco`、babariana 的
`Bg_Only` 等），其特效部件的显隐**整条丢失**：该亮不亮、该灭不灭，甚至被误判成
"Unity 里始终禁用（SetActive=0）"而**根本不导出**。

daphne_skin1 是最典型的一例：`3P_Daphne_FX` 这条动画在产物里只有 **6 个 slot**
有时间轴，而 FX clip 里有 **59 条 m_IsActive 曲线**；230 个 `parts_wing_fx*` 部件
几乎全部没有时间轴。

## 根因

AnimatorClip 里曲线的 `path:` 是**相对该 Animator 所在物体**的。

副 Animator 的曲线长这样（相对翅膀自己）：

```
bone_wing_fx (21)/parts_wing_fx1
```

而转换器给每个节点算的 `anim_path` 是**相对主 Animator**的：

```
3P_Daphne_NS1/Bone_pelvis/Bone_spine1/Bone_spine2/bone_L_wing/bone_L_wing/bone_wing_fx (21)/parts_wing_fx1
```

`active_curves.get(td["anim_path"])` 永远匹配不上 → 该部件在所有动画里都被判定为
不可见 → 被丢进 `excludedParts`，理由写成"Unity 里始终禁用"（**假理由**）。

3.8 节当时修的是副 Animator 的**变换**（rest 参考表 + 按宿主重算 `anim_path`），
显隐曲线这条路径没跟上。

## 修法

`ngui2spine/static_prefab_spine.py`：

1. 新增 `_curve_lookup(curves, anim_path, prefix)`：先按 `anim_path` 精确查；查不到
   就把 `anim_path` **去掉该 Animator 的前缀**（`rel_path_in(prefix, anim_path)`）
   再查一次。
2. `enumerate_clips()` 给每条 entry 的 clip 挂 `_prefix`（= 该 Animator 相对主根的
   路径）。**同一个 clip 被多个 Animator 引用时必须先 `dict(clip)` 复制**，否则
   左右翅膀会互相覆盖前缀。
3. `node_visible()` / `part_visible()` 查表时带上 `clip["_prefix"]`。
   主 Animator 前缀为空，行为与改动前完全一致。

> **踩过的坑**：第一版用"全局后缀匹配"兜底，结果链上本来不该命中曲线的祖先也命中
> 了，`node_visible()` 里"整条链从头 inactive 就当成场景摆放"的逃生口被误触发，
> 显隐直接**极性反转**（daphne 左翼曾经输出 `0 显示 → 1.35 隐藏 → 2.5667 显示`，
> 而曲线是 `(0,0)(1.0667,1)(2.7833,1)(2.8,0)`）。**不要用后缀兜底，只能按显式前缀换算。**

## 效果

| | 修复前 | 修复后 |
| --- | --- | --- |
| daphne `3P_Daphne_FX` 的 slot 时间轴 | 6 | 123 |
| daphne 导出部件 | 260 | 266 |
| daphne `excludedParts` | 110 | 104 |

左翼验证通过：`parts_wing_fx1_209` 在 `bone_L_wing_3P_Daphne_FX_2` 里是
`0 隐藏 → 1.0667 显示 → 2.8 隐藏`，与 clip 原始关键帧一字不差。

全量重转 50 个角色后，`tools/check_clip_visibility.py --all-in-probe50` 的结果：
**49 / 50 与 clip 逐帧一致**（修复前是 43/50，且 bheur、cheona、csperrault、
amy、constantias2_skin0 等一批报错全部转 ✓）。

## 遗留（未完成）

> **2026-09-14 更正**：早前写在这里的"daphne 右翼是产物真错"，经父链逐层打点后
> **不成立** —— 产物是对的，那 57 个是**校验器的假阳性**。更正过程见本节末尾。

### 早前的误判（保留作记录）

曾认为 daphne_skin1 右翼 57 个 slot 是**产物真错**：

```
parts_wing_fx1_01
  自己的曲线 : 无
  祖先 bone_wing_fx (9) : (0,1) (2.8,0) (3.0,1)         → 0~2.8 显示
  我们的时间轴          : 0 显示 → 1.35 隐藏 → 1.5 显示   ← 两个时刻在整条链上都不存在
```

左翼正确、右翼错，而左右翼的层级深度不同：

```
左翼：…/bone_L_wing/bone_L_wing/bone_wing_fx (21)/parts_wing_fx1            （两层同名）
右翼：…/bone_R_wing/bone_R_wing_fx/bone_R_wing/bone_wing_fx (9)/parts_wing_fx1（三层，中间多一层）
```

已排除的假设：不是 `m_Enabled` 曲线驱动（该 clip 里没有对应路径的 `m_Enabled`）。

**下一步**：把右翼链上每层的 `anim_path`、`_prefix`、以及 `lookup` 实际用的 key
全部打出来逐层对齐，确认是 `_prefix` 取错层还是 `rel_path_in()` 在"前缀里出现
同名段"时截错位置（该函数的注释里已经记着"宿主名互为前缀会串台"这个坑）。

### 更正：产物是对的，57 个是校验器假阳性

按上面说的把父链逐层打点（在 `node_visible()` 里加 `SPINE_DBG_CHAIN` 开关），
在 **干净的空目录**重转 daphne 复现后拿到：

```
[chain] t=1.35 node=daphne_skin1                  keys=-   vis=True  seen=False
[chain] t=1.35 node=3P_Daphne_NS1                 keys=-   vis=True  seen=True
[chain] t=1.35 node=…/Bone_spine2/bone_R_wing     keys=-   vis=True  seen=True
[chain] t=1.35 node=…/bone_R_wing/bone_R_wing_fx  keys=-   vis=True  seen=True
[chain] t=1.35 node=…/bone_R_wing_fx/bone_R_wing  rel=''   keys=-  vis=True seen=True
[chain] t=1.35 node=…/bone_wing_fx (9)            rel='bone_wing_fx (9)'  keys=HIT  vis=False seen=True
```

祖先 `bone_wing_fx (9)` 在 t=1.35 **命中曲线并返回 False**，所以产物里的
`0 显示 → 1.35 隐藏 → 1.5 显示` 正是按父链语义推出来的正确结果。

同时排除了 `_prefix` 串台、`rel_path_in()` 截错、`m_Enabled` 驱动、子树隔离失效、
陈旧产物五个假设（都有实测记录）。

**误判的根源**：早先读那条曲线时只打了前 4 个关键帧（`curves[k][:4]`），
打印成 `(0,1) (2.8,0) (3.0,1)`，看起来 1.35 处该是"显示"——**实际曲线在
1.3/1.5 附近还有"翅膀闪一下"的短促开关关键帧**，被截断的打印藏掉了。
教训：**核对曲线时不要截断关键帧列表**。

### 剩余工作：改校验器（不用再动转换器）

`check_clip_visibility.py` 的两处口径与转换器不一致，导致上面这类假阳性：

1. `ancestor_curve_keys()` 用"子串 `"/k/"` 是否出现在完整路径里"判祖先，而
   转换器 `node_visible()` 用的是"按 Animator 前缀换算后的相对路径**精确匹配**"。
   两套规则不等价 → 某些祖先曲线在方向 2 里认不出来，被报成"clip 里没有相关曲线"。
2. 多 Animator 角色（daphne 有 3 个 Animator、4 条 FX 动画、共用 2 份 clip）里，
   给某条动画选的 clip 仍可能不是它自己那份。

修法：让校验器用**和转换器同一套换算**（先按该动画所属 Animator 的前缀还原相对
路径，再精确查表），方向 1/方向 2 的判据就完全同构。

### 待清理

- `static_prefab_spine.py` 的 `node_visible()` 里 `SPINE_DBG_CHAIN` 打点（默认无副作用，可删）
- 临时目录 `_verify2/`（约 100 MB）

## 工具与备份

| 路径 | 说明 |
| --- | --- |
| `tools/check_clip_visibility.py` | **离线**显隐校验器，拿 clip 的 m_IsActive 当基准；已补父链语义（`effective_clip_curve`）、按 Animator 选 clip（`states_by_animator`）、子树过滤 |
| `tools/write_all_skel.py` | 批量补写 `.skel`（`convert_all_2dmodel.py` 不透传 `--skel`）；**JSON 变了要 `--force` 重写** |
| `_probe50` | 当前 50 个角色，已全部来自前缀版转换器，`.skel` 与 JSON 同步 |
| `_probe50_stale_20260913` | 修复前全套产物（可回退） |
| `backup/20260914_before_secondary_anim_path` | 本次改动前的 `static_prefab_spine.py` / `unity_anim2d.py` |

批量重转的正确姿势（`convert_all_2dmodel.py` 会把 `prefabs/lo/*` 下**所有** prefab
扫进来，里面混着没有 Animator 的模型，直接跑会全失败）：

```text
python tools\collect_convertible.py --json _convertible.json          # 工程里可转换的一共 412 个
# 只转 Change50 这 50 个：先过滤出清单
python tools\convert_all_2dmodel.py --names-from _convertible50.json --out _probe50 --jobs 5
python tools\write_all_skel.py _probe50 --force
python tools\check_clip_visibility.py --all-in-probe50
```
