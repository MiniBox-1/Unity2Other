# Unity 运行时逆向报告：Animator / AnimationClip 与 `m_IsActive`

更新：2026-09-14

起因：`静态prefab路线.md` 8.1.8 把"Play 真值里互补的眼/眉部件同时 ON"解释成
**采样方式**的问题（跳帧 → `SetActive` 被粘在 ON），并据此把 Play 真值判为不可信。
本轮用**反汇编 + 同版本 Unity 实测**把这件事定死：结论是**运行时的判据本身**与
转换器（和当时的认知）不一样，跟采样方式无关。
**只用于解释行为、修正判据，不进成品数据。**

---

## 0. 30 秒版

1. Unity 把 `GameObject` 上的 `m_IsActive` 曲线绑定成"**active 类型**"（type 7），
   每帧写入时执行的是：

   ```c
   if (v > 0.001 || v < -0.001)  GameObject::Activate(go);
   else                          GameObject::Deactivate(go, 0);
   ```

   —— 判据是 **`|v| > 1e-3`**，不是通常以为的 `v >= 0.5`；`m_Enabled`（bool）同理。
2. 曲线值是不是"只有 0/1"取决于**关键帧切线**：编辑器 Constant（阶跃）曲线的
   斜率序列化成 `±Infinity`，其余是 Hermite 插值。
3. 工程里的 `m_IsActive` **绝大多数是插值曲线**（6505 条里 6191 条 slope=0）。
   于是段内曲线值处在 0~1 之间 ⇒ 运行时**一路判为显示**，只在"恰好等于 0"的
   极短窗口里隐藏 —— 这就是"互补的眼/眉同时 ON"的真正原因。
4. 转换器原来按"阶跃 + `v>=0.5`"算显隐，与运行时系统性不一致；已按本报告矫正
   （`--active-step` 可回到老口径对拍）。banshee 四段动画与 Play 真值的不一致
   格子数 **1723 → 1**，且**几何/变形数据逐字节不变**。

---

## 1. 环境：该逆向哪一份 UnityPlayer

| 用途 | 路径 | 说明 |
| --- | --- | --- |
| **游戏自己的运行时（首选）** | `D:\VB\Search\NormalLocal\win64_player_nondevelopment_mono\UnityPlayer.dll` | **30.8 MB，Unity 2022.3.3f1c1**（= 工程版本），旁边还有官方 **PDB**（`UnityPlayer_Win64_player_mono_x64.pdb`，20.9 MB）和 `Data\Managed\*.pdb` |
| 开发版运行时 | `D:\VB\Search\NormalLocal\win64_player_development_mono\UnityPlayer.dll` | 49.4 MB，同版本，另带 development PDB |
| 反汇编库（符号齐全） | `D:\Reverse\win64_player_nondevelopment_il2cpp\UnityPlayer.dll.i64` | IDA 8.3 已分析的库；本体是 **Unity 6000.3.13f1** il2cpp 版（比工程新两个大版本，函数名/RTTI 齐全，适合读逻辑） |
| 同版本编辑器 | `D:\Unity\Editor\2022.3.3f1c1\Editor\Unity.exe` | 用来做**行为实测**（与游戏同版本，语义直接可比） |

> `交接文档.md` 早前记的 `D:\VB\Search\NormalLocal\win64\_player\_*_mono` 是**路径写错**
> （多了一层 `_player`），所以"磁盘上不存在"的结论不成立：
> 现存的目录名是 `win64_player_nondevelopment_mono` / `win64_player_development_mono`，
> **而且带官方 PDB**。要定版本相关行为，优先用这两份，而不是 `D:\Reverse` 那份 Unity 6。

---

## 2. 反汇编证据（IDA 8.3）

> 反汇编用的是 `D:\Reverse\win64_player_nondevelopment_il2cpp\UnityPlayer.dll.i64`
> 的一份**副本**（跑 IDA 会改写 IDB，别在原件上跑）；批处理查询器 = `tools\ida_q.py`，
> 完整用法见 [`汇编核对清单.md`](汇编核对清单.md) 第 6 节。

### 2.1 `m_IsActive` 怎么被绑定：type 7

`AnimationBinder::CalculateTargetPtr`（`0x180B40540`）里对 `GameObject` 名做特判：

```c
if ( a2 == &TypeContainer<GameObject>::rtti && !strcmp(a4, "m_IsActive") )
{
    *a6 = 7;        // 属性类型 = 7（active）
    *a5 = a3;       // 目标指针 = GameObject 本体
    return 1;
}
```

`GenericAnimationBindingCache` 的构造函数（`0x180B35380`）里预先把
`crc32("m_IsActive")` 塞进查表，用来在绑定阶段命中这个特判。

### 2.2 写入时的判据：`|v| > 1e-3`

`UnityEngine::Animation::SetBoundCurveFloatValue`（`0x180B39180`）：

```c
case 6:   // bool（m_Enabled 这类）
    if ( v > 0.001 || v < -0.001 ) { *ptr = 1; } else { *ptr = 0; }
    return changed;
case 7:   // active（m_IsActive）
    if ( v > 0.001 || v < -0.001 ) GameObject::Activate(go);
    else                          GameObject::Deactivate(go, 0);
    return 0;
```

**关键点**：阈值是 `1e-3`，不是 `0.5`。插值曲线只要离开 0（哪怕 0.007），
部件就算"显示"。

### 2.3 谁在每帧调用它（Animator 的通用属性写入）

| 函数 | 地址 | 作用 |
| --- | --- | --- |
| `Animation::SetGenericFloatPropertyValues` | `0x180B45090` | 遍历所有已绑定的 float 曲线 → `SetBoundCurveFloatValue` |
| `Animation::SetGenericIntPropertyValues` | `0x180B44F20` | 同上；type 11 直接写 int，其余仍走 `SetBoundCurveFloatValue` |
| `Animation::SetGenericPPtrPropertyValues` | `0x180B44D70` | 资源引用类曲线 |
| `Animator::WriteStep` | `0x180B5C9B0` | 写场景（本函数只处理 transform/骨骼；通用属性由上面几个负责） |

### 2.4 `Activate/Deactivate` 本身是干净的

`GameObject::Activate` `0x1802F75C0` / `GameObject::Deactivate` `0x1802F76F0`：
置/清 `[go+0x46]` 的 active 位，然后 `ActivateAwakeRecursively` 递归刷新子树 +
发对象变更通知。**没有**"只在跨关键帧时才写"之类的粘滞逻辑 —— 每次调用都生效。
所以"粘在 ON"不可能来自这里，只能来自**上面的值/阈值**。

---

## 3. 同版本实测（决定性证据）

反汇编能给出判据，但要排除"编辑器与运行时不一致"，用 **2022.3.3f1c1**（与游戏同版本）
做了隔离工程实测：`_verify_animator\Assets\Editor\AnimProbe.cs`
（脚本自建 `AnimationClip` + `AnimatorController`，`animator.Update(dt)` 逐步推进，
逐帧记录 `activeSelf`）。

### 3.1 阈值被钉死在 0.001

曲线 `(0,0) → (1,1)`，slope=0（零切线 Hermite）。细步长 0.001 扫描：

| 时刻 | 曲线值 `3u²-2u³` | 实测 `activeSelf` |
| --- | --- | --- |
| 0.018 | 0.00097 | off |
| **0.019** | **0.00108** | **ON** |

手算 `3u²-2u³ = 0.001` 的解是 **u = 0.01826** —— 与实测零点完全吻合。
同一实验里，数值相同但用编辑器 **Constant** 切线的曲线，要到 0.3（下一个 `1`
关键帧）才打开 —— 说明"阶跃 vs 插值"在运行时确实两条路径。

### 3.2 阶跃曲线在文件里长什么样

| 曲线来源 | `inSlope/outSlope` | `tangentMode` | `weightedMode` | 权重 |
| --- | --- | --- | --- | --- |
| 编辑器 Constant（阶跃） | **Infinity** | **103** | 0 | 1/3 |
| 工程里的 `m_IsActive` | **0** | 0 | 0 | 1/3 |

即：**工程数据不是阶跃曲线**，运行时按插值求值。

### 3.3 直接复现工程真值

把 banshee `BR_Banshee_NS1_breast` 的真实关键帧数值（`parts_Eye_Smile`、
`parts_Eyebrow_normal` 等）照搬进隔离工程，实测出来的开关时刻与工程
`info/Data/PlayFrames/banshee_skin1@Size_root@breast.json` **逐帧一致**
（含"0.05 就打开""0.8 又打开"这些看起来反直觉的点）。

### 3.4 顺带否掉 8.1.8 的因果解释

同一实验里 **`Seek`（逐点 Play+Update(0)）与 `NaturalStep`（连续推进）结果完全相同**。
所以：

- "跳帧采样会把 `m_IsActive` 粘在 ON" **不成立**（那是现象，不是机制）；
- Play 真值本身**是可信的**，它就是运行时行为；旧口径下"真值与 clip 不一致"，
  是因为**两边用的判据不同**，不是真值坏了。

### 3.5 补充实测（2026-09-15 下午）：互补备选件**确实会同时显示**

用户对"多口 / 多眼 / 多手"（andvari_skin2 的嘴、banshee_skin1 的手…）的直觉是
"同一时刻只该有一个"。用 `_verify_animator\Assets\Editor\MouthProbe.cs`
把 andvari 嘴部的两条**真实曲线**（`All-0` 切线）做成 clip 跑自然步进：

| 时刻 | Idle 值 | Smile 值 | 实测 `activeSelf` |
| --- | --- | --- | --- |
| 0.00 | 1 | 0 | Idle ON / Smile off |
| 0.05 | 0.99966 | **0.00034** | **Idle ON / Smile ON** |
| 4.55 | 0.00239 | 0.99761 | Idle off / Smile ON |
| 6.10 | 1 | 0 | Idle ON / Smile off |

即：**阈值比 1e-3 还低**（0.00034 已经 ON；4.55 的 0.00239 已经 off —— 与
"Unity 在动画器内部按自己的采样时刻求值、和手算的 u 有极小偏差"一致）。
任一情况下，一条 4.68 秒的 0→1 斜坡会让这个部件**几乎整段**都处于 ON。

⇒ 结论：`|v|>1e-3` 的判据是对的，**"两个备选件同时显示"是运行时的真实行为**，
转换器忠实复现；要"看起来只有一个"必须改**数据**（把切线改回 Constant）或
在转换器里加**按产品口径**的互斥裁决（见主文档 3.24 的三条可选口径）。
原始记录：`docs/data/mouth_probe_20260915.json`。

---

## 4. 数据普查（`Assets/rawLo/*/*/AnimationClip/*.anim`，1825 个 clip）

| 项 | 数量 |
| --- | --- |
| 含 `m_IsActive` 的 clip | 1059 |
| `m_IsActive` 曲线条目 | 6505 |
| ├ slope=0（**插值**） | **6191** |
| ├ slope=±Infinity（阶跃） | 314 |
| └ slope 非 0 有限值 | 6 个关键帧 |
| `m_Enabled` 曲线条目 | 611 |
| `weightedMode != 0` | 0（都用非加权 Hermite） |

> 也就是说：**同一批资源里两种编码混用**，"一律当阶跃"这个前提只对 5% 的曲线成立。

---

## 5. 矫正：转换器按运行时语义求显隐

### 5.1 改了什么

| 文件 | 改动 |
| --- | --- |
| `ngui2spine/unity_anim2d.py` | 解析 `m_IsActive` / `m_Enabled` 时**同时读 `inSlope/outSlope`**（认得 `Infinity`），产出 `active_tan` / `enabled_tan`（老键 `active` / `enabled` 不变，向后兼容） |
| `ngui2spine/static_prefab_spine.py` | 新增 `unity_curve_eval()`（Unity 求值：±Inf 段=常值段，其余 Hermite）、`active_is_on()`（`|v|>1e-3`）、`active_flip_times()`（算"开/关"翻转时刻）；`node_visible/part_visible` 改用它；`probe_times` 补上翻转时刻（否则短可见窗会被 0.05 网格跳过）。新增开关 `--active-step` 回到老口径 |
| `tools/static_check.py` | 探测时刻同样补翻转时刻 |
| `tools/check_clip_visibility.py` | 校验器换成**同一套判据**（原来按"阶跃 + ≥0.5"比，现在必然对不上）；新增 `--spine-root` 便于校验任意产物目录 |

### 5.2 验证：banshee（4 段动画，与 Play 真值逐格比对）

比对方式：产物 slot 的 attachment 时间轴 vs Play 真值的
`activeSelf && activeInHierarchy`（有效可见性，父链关闭也算隐藏），
在 0.05 网格上逐格比。

| 动画 | 旧口径不一致格子 | **新口径** |
| --- | --- | --- |
| breast | 656 | **0** |
| Start | 0 | **0** |
| Tep_1 | 745 | **1**（10.05s 尾帧，属已知 3.19"末尾保持帧"，与本改动无关） |
| lobby | 322 | **0** |
| **合计** | **1723** | **1** |

典型部件（breast，202 帧）：`parts_Eye_Smile` 旧 32 帧显示 → 新 **134 帧**（真值 134）；
`parts_Mouth_angry` 旧 33 → 新 **120**（真值 120）；`parts_Eyebrow_normal` 旧 8 → 新 **92**（真值 92）。
这正是用户反馈的"**banshee breast 动作时表情消失**"。

### 5.3 验证：改动是"手术式"的（几何不变）

同一角色、新旧口径两份产物逐字段比对：

```text
skeleton / skins      : 完全相同
每个动画的 bones      : 完全相同（逐字节）
每个动画的 deform     : 完全相同（逐字节）
每个动画的 slots      : 仅显隐时间轴不同（breast 10 / Tep_1 13 / lobby 7 个 slot）
```

因为 `times_of`（写 deform 关键帧用的时刻表）没有动，只动了 `probe_times`
（显隐时间轴用），所以**三主力"逐顶点误差 ≤1e-5"的验收基线不受影响**。

### 5.4 验证：bheur（用户点名"Lobby 只是上眼眶消失"）

| 动画 | 旧 | **新** |
| --- | --- | --- |
| breast | 274 | **10** |
| Lobby | 51 | **45** |
| Tep_1 | 549 | **10** |
| Drone | 10 | **10** |

整体大幅改善，但 bheur 仍有残留（见第 6 节）。

---

## 6. 残留与后续

1. ~~**bheur `Lobby` 的 45 格**~~ —— **已定性：那个真值文件是废数据**（整段
   transform 一个没变，采样没驱动 Animator，见第 8.1 节）。转换器侧无需改动。
2. **1 帧边界残留**（bheur breast 的 10 格都在 t=3.50）：翻转时刻与 0.05 网格
   对齐时的取整差，属可接受噪声；要更严可以让显隐关键帧直接写翻转时刻。
3. **未做**：50 角色全量重转 + 四层校验（本轮只在 banshee / bheur / aeda 上验）。
   命令见 `报告与校验.md` 2.1，建议先写新目录再替换 `_probe50`。
4. **`check_clip_visibility.py` 的定位变了**：它现在校验"产物与运行时语义一致"，
   不再是"产物与关键帧字面值一致"。要复核"艺术意图"（一个表情一个部件），
   得另写一个按 `v>=0.5 + 阶跃` 的口径报 —— 那是**意图**，不是**运行时行为**。

---

## 7. 复现命令

```bat
:: 反汇编（IDA 批处理；先复制一份库再跑，别改原件）
copy %REVERSE%\win64_player_nondevelopment_il2cpp\UnityPlayer.dll.i64 _reverse\UP.i64
set REQ_INLINE={"op":"decompile","ea":"0x180B39180"}
set REQ_OUT=_reverse\res.json
%IDA%\idat64.exe -A -L_reverse\ida.log -S"%CD%\tools\ida_q.py" _reverse\UP.i64

:: 行为实测（隔离工程，同版本编辑器，见 tools 说明）
D:\Unity\Editor\2022.3.3f1c1\Editor\Unity.exe -batchmode -nographics ^
  -projectPath _verify_animator -executeMethod AnimProbe.Run -logFile _reverse\unity_probe.log

:: 转换器矫正后的验证（旧/新口径对拍）
python -m ngui2spine.static_prefab_spine <prefab> out_rt  --assets <Assets> --scene <save.unity> --no-face-check
python -m ngui2spine.static_prefab_spine <prefab> out_old --assets <Assets> --scene <save.unity> --no-face-check --active-step
python tools\compare_play_truth.py out_rt\<角色>_static.json <PlayFrames\角色@Animator@状态.json> <状态>
python tools\check_clip_visibility.py <产物目录>
python tools\check_skel.py <产物目录> --ref-exe
```

> 完整的"逻辑 ←→ 汇编"对照与本轮的验证命令见
> [`汇编核对清单.md`](汇编核对清单.md)；`_reverse\` 是一次性目录（按需重建），
> `_verify_animator\` 是那套 Unity 行为实测工程（保留）。

---

## 8. Play 真值数据质量审计（2026-09-14）

矫正后用**全部有 Play 真值的 19 个角色**重转了一遍（`_verify_rt/`，带 `--scene`），
再把产物 slot 的显隐时间轴与真值的**有效可见性**
（`activeSelf && activeInHierarchy`，父链关闭也算隐藏）在 0.05 网格上逐格比。
脚本：`tools\convert_all_2dmodel.py --scene <save.unity>`（带场景重转）、
`tools\audit_playframes.py`（真值审计 + 比对）、
`tools\compare_play_truth.py`（单文件比对）；
结果存档 `docs\data\playframes_audit.json`。

### 8.1 结论一：96 个真值文件里有 11 个是废数据

判据：整段动画里 **transform 一个都没变** ⇒ 那次采样根本没驱动 Animator，
文件里记的只是"静止快照"，拿它比显隐只会得到假差异。

| 角色 | 状态 |
| --- | --- |
| alice_skin2 | Start |
| banshee_skin1 | Start |
| bheur_skin1 | **Lobby** |
| blackwyrm_skin1 | lobby |
| cerberus_skin3 | Start |
| cheona_skin1 | 2DModel_BR_Cheona_NS1_Lobby |
| circe_skin1 | PECS_Circe_NS1_Lobby |
| csperrault_skin2 | Start |
| darkelf_skin1 | lobby |
| draculina_skin1 | Start |
| draculina_skin1_fix | Start |

> bheur `Lobby` 的 45 格"残留"就是这一类 —— **不是转换器的问题**（见 7.2 的更正）。

### 8.2 结论二：可用真值里 76/83 完全一致，残差两类

| 分类 | 文件数 | 差异格子 |
| --- | --- | --- |
| 完全一致 | 65 | 0 |
| 小残差（每个文件 1~3 格） | 16 | 68（阈值/网格边界噪声） |
| 大块差异 | 2 | 812 |

两个大块差异文件的共同特征：**transform 在动，但整段里没有任何渲染器的
`activeSelf` 变过**（`truthA=0` / `truthA=2`）—— 与 8.1 的废数据是同一个病根
（那一次采样的通用属性写入没生效），不是判据问题：

| 角色 / 状态 | 格子 | 具体 |
| --- | --- | --- |
| blackwyrm_skin1 / 2DModel_BlackWyrm_NS1_Lobby_BG | 686 | `Part_Balgure_L/R` 各 343（我们按 `Bone_Balgure` 曲线隐藏，真值全程没隐藏过） |
| circe_skin1 / PECS_Circe_NS1_Drone | 126 | `Part_Mouth_Smile_44` 全程 126 |

### 8.3 结论三：受控 A/B（同角色、同参数，只差显隐规则）

`--active-step`（老口径）与默认（运行时口径）各转一份，逐格比同一批真值：

| 角色 | 老口径差异格子 | **新口径** |
| --- | --- | --- |
| banshee_skin1（4 段，含 1 个废文件） | 1723 | **1**（10.05s 尾帧，属 3.19） |
| bheur_skin1（4 段，含 1 个废文件） | 884 | **75**（其中 45 来自废文件 ⇒ 有效真值 30） |
| csperrault_skin2（4 段，含 1 个废文件） | 1049 | **0** |
| **合计** | **3656** | **76** |

### 8.4 顺带修掉的"假理由丢弃"（csperrault_skin2）

同角色同参数只差显隐规则：

| | 部件数 | `Animation` 引用但未导出 | 被丢的部件 |
| --- | --- | --- | --- |
| `--active-step` | 51 | **1** | `.../Eye_C/Eye_smile/parts_Eye_smile_L`，理由写成"Unity 里始终禁用（SetActive=0）" |
| 默认（运行时口径） | **52** | **0** | — |

成因（曲线原文）：`Eye_smile` 组 `(0,0)(3.4667,1)(4.3333,0)` 与
`parts_Eye_smile_L` `(0,1)(3.4667,0)(4.3333,1)` **在阶跃口径下永远不同时为 1**
（互斥）→ 老口径判定"整段不可见"；但插值口径下两条曲线在 **0.06~3.48s 同时非零**
⇒ 运行时一直显示。这与 3.10 的 SetActive 表情切换是同一类问题。

### 8.5 后续

1. **重采真值**：`activateDescendants` 打开、`Rebind()` 放在激活之后，重跑
   `PlayModeProbe`（黑名单：上面 11 个废文件 + blackwyrm Lobby_BG + circe Drone）；
   重采后再跑 `tools\audit_playframes.py` 复核。
2. blackwyrm `Lobby_BG` / circe `Drone` 两个状态要单独查：先确认它们的
   **状态→clip 选择**是否与运行态一致，再判断是真值缺写入还是选错 clip。
3. 小残差（68 格 / 16 文件）都是 1~3 格边界噪声，可接受；若要归零，让显隐关键帧
   直接写"翻转时刻"而不是吸附到 0.05 网格。

---

## 9. 第二轮核查：还有哪些动画通道与转换不一致（2026-09-14）

做法：把 19 个角色的 `*_clip.anim` 里**所有** `m_FloatCurves` 属性列出来，按
"转换器是否处理"分类，再逐个用**运行时语义 + 逐顶点实测**判断影响。

### 9.1 清单

| 通道 | 转换器 | 运行时是否生效 | 影响/证据 |
| --- | --- | --- | --- |
| 变换 `localEulerAnglesRaw.*` / `m_LocalPosition.*` / `m_LocalScale.*` / `m_LocalRotation.*` | ✅ 已处理（带切线 Hermite） | 是 | 三主力逐顶点 0.00000 |
| `m_IsActive` / `m_Enabled` | ✅ 已处理（第 2 节矫正） | 是（`\|v\|>1e-3`） | 见第 5、8 节 |
| `m_FlipX` / `m_FlipY` | ✅ 静态值已处理（3.17） | 是 | — |
| **`blendShape.<通道名>`**（morph） | ❌ → **本轮已修** | **是** | 见 9.2 |
| **`m_PPtrCurves` 的 `m_Sprite`**（换贴图/换表情） | ✅ **已实现**（同 slot 多 attachment + 时间轴） | **是** | 见 9.3 |
| **`m_SortingOrder`**（前后层交换） | ✅ **已实现**（drawOrder；仅当每帧都能精确表达时才导出） | **是** | 见 9.4 |
| **多 Animator 层**（Base Layer 之外的层） | ✅ **已实现**（Override + Additive，含循环） | **是** | 见 9.5 |
| `m_Color.*` / `material._Color.*`（透明度/颜色） | ✅ **已实现**（slot 颜色时间轴） | **是** | 见 9.6 |
| `material._AdditionalAlpha` 等自定义 shader 属性 | ❌ 未导出（登记） | 语义依赖 shader | 在 `unsupportedChannels` 报告 |
| `script_*` / `typetree_*` | ❌ 未导出 | 自定义 MonoBehaviour 属性 = 游戏逻辑，不参与渲染 | 不导 |

### 9.2 blendShape（morph）：已修，有量化收益

**数据**（19 个角色）：13 个角色有带 blendShape 的部件，共 **204 / 1568** 个部件；
morph 曲线条数：cheona 190、bheur 142、babariana 126、alice_skin2 93、
draculina 87、circe 74、cerberus_skin3 72、blackwyrm 67……

**修法**：

1. `unity_mesh._parse_blend_shapes()` 读 Mesh 的 `m_Shapes`
   （`vertices` 形变增量 + `shapes` 帧表 + `channels{name,frameIndex,frameCount}`
   + `fullWeights`）；
2. `unity_anim2d.parse_clip` 收集 `blendShape.<通道名>` 百分比曲线（`morph`/`morph_tan`）；
3. `static_prefab_spine.morph_positions()` 在**蒙皮之前**把
   `v += Σ delta·(w/100)` 加进局部顶点（与 Unity 的
   `v_local = v0 + Σ delta·w/100; v_world = skin(v_local)` 顺序一致）；
   `probe_times` 补上 morph 关键帧时刻。

**验证**（bheur `breast`，与 Play 真值逐顶点，`tools/calib_geo.py`）：

| 部件 | 修前 max | 修后 max |
| --- | --- | --- |
| Part_Thigh_R_15 | 0.07891 | **0.00907** |
| Part_Thigh_R_Push_16 | 0.08014 | **0.01312** |
| Part_Body_20 | 0.08041 | **0.03050** |
| Part_UpperArm_L_70 | 0.07516 | **0.03119** |
| Part_UpperArm_Cloth_L1_71 | 0.06366 | **0.02525** |
| Part_UpperArm_Cloth_L_72 | 0.06589 | **0.02411** |
| Part_Breast_R_19 | 0.06059 | **0.02872** |
| （无 shape 的部件，如 Part_Drone_*） | 不变 | 不变 ✓ |

**回归**：audrey 快速验证仍是 `25 渲染器 / 23 部件 / 四项全 0 / 顶点误差 0.00000`
（没有 shape / 没有 morph 曲线时该分支完全不介入）。

### 9.3 Sprite 交换（`m_PPtrCurves` → `m_Sprite`）：**未做，已告警**

只有 `constantias2_skin1` 命中（3 条 clip），`face_ani` 的脸贴图在动画里换：

```text
lobby:  t=0 c01b5460 → t=3.87 7e1172c0 → t=5.27 c01b5460
breast: t=0 c01b5460 → t=0.12 4295029f → t=1.53 7e1172c0 → t=2.27 c01b5460
```

转换器只导出 prefab 的静态 sprite ⇒ **这段时间的表情是错的**。
现在会打 `[warn] 检测到 Sprite 交换动画…` 并写进 `_static_info.json` 的
`spriteSwap`（含动画名、节点、sprite guid 序列）。
要做完整支持：同一个 slot 出多个 attachment（各 sprite 一套 uv/顶点），
再用 attachment 时间轴在它们之间切（Spine 3.8 原生支持）。

### 9.4 `m_SortingOrder` → `drawOrder` 时间轴：**已实现（可精确表达时才导出）**

19 个角色里 119 条排序曲线，很多只是 ±1 的微调，但也有真交换，例如
draculina `Part_Finger_L0_5`：`5 → 36 → 35 → 5`（手指从身后挪到身前再回去）。

**实现**（`static_prefab_spine.py`）：

1. `unity_int_round()`：Unity 把 float 曲线写进 int 属性时的取整
   （`SetBoundCurveFloatValue` case 10：`v+0.5`，负数再减 `0.99999994`，向零截断）——
   与 Python 的 `round()`（银行家舍入）不同，实测 `0.5→1 / -0.5→0 / -2.5→-2`；
2. `sorting_change_times()`：排序值是 int，斜坡中段就会"跳整数"，这些时刻也要采；
3. `draw_order_offsets()`：把目标绘制顺序编成 Spine 的 `offsets`。
   Spine 3.8 的语义（读 `spine-cpp/src/spine/SkeletonJson.cpp` /
   `SkeletonBinary.cpp` 确认）是：**按 setup 序号升序遍历，把该槽放到
   `setupIndex + offset`；没列出的槽按 setup 顺序填满剩下的位置；偏移是
   unsigned varint，必须 ≥ 0**。所以"要往后挪的槽"只能不列出；
   可精确表达的条件是"这些槽在目标顺序里保持 setup 升序"。
   单元测试：n=3/4/5 全排列分别 6/6、22/24、92/120 可表达，且**编码全部解码正确**。
4. **只有每一帧都能精确表达才导出**；有一帧表达不了就整条动画不导
   （半对的时间轴会把顺序冻在中途，比沿用静态顺序更糟），并在
   `_static_info.json.unsupportedChannels` 里报出帧数。

**验证**：

| 角色 | 结果 |
| --- | --- |
| alice_skin2（breast/Tep_1 各 2 帧：单槽 +1） | ✓ 导出 |
| cheona_skin1（NormalTouch 20 帧） | ✓ 导出 |
| draculina_skin1（breast，926 帧表达不了） | ✗ 不导出（沿用静态顺序） |

- `.skel` 往返：本项目读回器逐帧一致 ✓
- 与 `third_party\SpineSkeletonDataConverter.exe` 的 JSON→skel **逐字节一致** ✓
  （alice_skin2 18,038,326 字节；cheona 45,874,392 字节）
- `tools\static_check.py` / `tools\check_clip_visibility.py` 在带 drawOrder 的产物上
  仍然全 0 ✓

> `tools\check_skel.py` 的**源码已丢失**（只剩 `__pycache__/*.pyc`），这里按它的口径
> 重建了 `tools\check_skel.py`（写出 → 读回 → 与第三方转换器逐字节对拍）。

### 9.5 多 Animator 层：**未做**（影响很直观）

bheur 的 controller 有两层：`Base Layer`（Lobby/Tep_1/breast）+ `Drone`。
运行时**两层同时求值**，而转换器按"某一条状态 clip"采样：

| 层 1（Drone）动画内容 | 后果 |
| --- | --- |
| `Bone_COM/Bone_World/Bone_Drone*` 5 根骨骼的 euler/pos | 无人机部件的姿态不对 |
| `Part_Drone_80` / `Part_Drone_Tail_79` 的 `Morph_Drone_*` | 无人机部件的形变不对 |

逐顶点实测（bheur breast）：`Part_Drone_Tail_79` **0.156**、
`Part_Drone_80` **0.097** ——修复 blendShape 后这两条依旧是全场最大误差，
因为它们来自**另一层**而不是当前 clip。

### 9.6 第三轮：把上一轮登记的四项全部补完（2026-09-14）

| 项 | 做法 | 验证 |
| --- | --- | --- |
| **`m_Sprite` 换脸** | Unity 的 `m_Sprite` 是 PPtr 阶跃曲线；Spine 侧用"**同一个 slot 挂多份 attachment + attachment 时间轴**"。为每张被换到的 sprite 复制一份变体部件（rect/pivot/ppu 都可能不同），attachment 名 `<槽>__2/__3…`，时间轴按 guid 切换 | constantias2_skin1：`face_ani` 3 份 attachment + 时间轴与 clip 的 4 个关键帧一一对应；`.skel` 与第三方转换器**逐字节一致**（2,502,951 字节）；静态检查四项全 0 |
| **多 Animator 层** | 解析控制器层表（`parse_animator_layers`）；**Override** 层直接覆盖同 path+kind 曲线；**Additive** 层按 `v(t)=base(t)+(over(t)−over(0))` 合成，`over` 短于主 clip 时**按自身时长循环**（实测 4.33s 的增量 = 1.0s 的增量，周期 = clip 时长） | bheur `breast` 逐顶点最大误差 **0.1564 → 0.0250**；drone 部件从误差榜消失 |
| **四元数 / 欧拉 曲线优先级** | 同一对象同时有 `m_RotationCurves` 与 `localEulerAnglesRaw.*` 时，**Unity 用的是四元数那条**（两条在关键帧上等价、插值不同）。采样器改成"有 rot 就忽略 euler" | bheur `Bone_Pelvis` 真值 3.878/1.045/4.458 与四元数完全吻合（欧拉那条是 2.89/−0.163/4.133）；改完后 bheur 全场只剩 0.025、其余部件 ≤0.022 |
| **`m_Color.*` / `material._Color.*`** | 生成 Spine **slot 颜色时间轴**（`slots.<槽>.color`，8 位十六进制）。只处理 classID **212**（SpriteRenderer 自身颜色）与 **137**（SMR 的材质色）；`material._AdditionalAlpha` 是自定义 shader 属性、语义依赖 shader，不导（在 `unsupportedChannels` 报告） | csperrault_skin2：clip 里 2 条"会变的"颜色曲线 **2/2 全导出**（其余 74 条是常量、正确跳过），例如 `parts_cheek` 白→红→白、`parts_knee` 白→透明；`.skel` 逐字节一致 |

**顺带修掉一个校验工具假阳性**：`tools/calib_geo.py` 对 sprite 部件是拿真值的
`worldCorners`（= `Renderer.bounds`，**世界空间轴对齐包围盒**）去**逐点**比我们的
旋转四边形 —— 旋转角被当成几何误差（bheur 的 `Part_Balgure` 因此假报 0.091）。
现在 sprite 改比 AABB（skinned 仍逐点比），bheur 的这块误差直接归零，
剩下的才 是真实误差。

**三主力回归（本轮改动后）**：audrey 0.00000（25/23/四项全 0）、
aeda 0.00001（44/44/四项全 0）、blacklilith 0.00000（35/33/四项全 0）——
与验收基线一字不差。

### 9.7 用汇编逐条核对本轮实现（2026-09-14 第四轮）

上面这些结论有些是**实测**出来的，这一节回到反汇编逐条核对"机制是否理解正确"。
用到的函数（`tools\ida_q.py` 可复现，用法见 [`汇编核对清单.md`](汇编核对清单.md)）：

| 问题 | 汇编证据 | 结论 |
| --- | --- | --- |
| 加性层的**参考姿态**是什么？ | `mecanim::animation::InitClipMuscleAdditivePose`（`0x18139CF70`）里 `v110 = a4; EvaluateClip(clip, &v110, ...)` —— 参考 = **clip 在 `a4` 时刻求值**；调用点 `AnimationClip::GenerateMuscleClip`（`0x1813A28A6`）传的是 clip 自己的 `m_AdditiveReferencePoseTime` 字段 | 工程里 27 个带该字段的 clip **全部 `m_HasAdditiveReferencePose: 0`、`m_AdditiveReferencePoseTime: 0`** ⇒ 参考 = **自身 t=0 的姿态** ✓ 与实现一致 |
| 加性层怎么混合？ | `DeltasFromClip<0>`（`0x180BB1480`）算 "clip 姿态 − 参考"；`TransformValueArrayAdd`（`0x180BBB770`）把它加到已有结果上（权重 `a8`） | `v = base + (over − over(0))` ✓ 与实现一致 |
| 加性层的**旋转**怎么加？ | `trsX` 的旋转通道是**四元数**；`TransformValueArrayAdd` 的旋转分支是**四元数乘**（分量乘 + 混洗），不是欧拉相加 | 单轴（本项目数据都是 Z 轴）时两者等价 ✓；**多轴加性层要做四元数乘**（已记入遗留） |
| 层短于主 clip 时循环 | 状态机语义（无退出条件的 state 循环），实测 4.33s 的增量 = 1.0s 的增量（周期 = clip 时长） | 实现按自身时长复制关键帧 ✓ |
| `m_Sprite`（PPtr）写入 | `SetGenericPPtrPropertyValues`（`0x180B44D70`）：直接写引用（`gc_wbarrier_set_field` / 原生 PPtr），**没有任何插值** | 换图是阶跃 ✓ 与实现一致 |
| blendShape 权重语义 | `BlendshapePropertyBinding::SetFloatValue`（`0x18050AF20`）→ `SkinnedMeshRenderer::SetBlendShapeWeight`（`0x1804FE270`）；`CalculateBlendShapeWeights`（`0x1804F42E0`）里 `v36 = weight / thr[frame]`，多帧时 `v28 = (w − thr[k])/(thr[k+1] − thr[k])` 并输出 `(1−v28, v28)` 两帧权重 | **`fullWeights` 是按帧索引的阈值**、单帧/未到首阈值时 `factor = w/thr[0]` 作用在首帧 ⇒ 原来的 `w/100×fullWeight/100` 与"按帧序号插值"是**错的**（已修，见下） |

**由此修掉的一个真实公式错误**（bheur breast 逐顶点）：

| | 最大误差 |
| --- | --- |
| 修前（`w/100 × fullWeight/100` + 帧序号插值） | 0.0250（再往前 0.0636 的中间版本） |
| **修后（按 `CalculateBlendShapeWeights`）** | **0.0054** |

多帧形变在数据里真实存在（44 条通道，阈值形如 `[25,50,75,100]`、甚至非单调的
`[100,50,100]`），`fullWeight≠100` 有 57 条通道 —— 不按汇编对齐就会一直差 0.02~0.06。

### 9.8 结论与剩余

**通道清单已全部收敛**（见 9.1 表）：变换 / `m_IsActive` / `m_Enabled` /
`m_FlipX,Y` / `blendShape` / `m_Sprite` / `m_SortingOrder` / 多层 /
`m_Color`·`material._Color` 都已按运行时语义导出并验证；只留两项**明确登记**的：

1. **`material._AdditionalAlpha` 等自定义 shader 属性** —— 语义依赖 shader
   （不是简单的"alpha 乘 0"），不导；每个角色会在
   `_static_info.json.unsupportedChannels` 里列出来。
2. **draculina 手部的排序整体重排** —— Spine 的 drawOrder 偏移只能非负
   （槽位只能往前挪），该动画 926 帧表达不了，按保守策略整条不导；
   详见 [`已知问题.md`](已知问题.md) 第 2 条（含 4 个可选修法）。

**交付侧**：`_probe50/`、`samples/` 里的产物都是矫正**之前**生成的；
已按报告的全部结论重转了一份到 **`_probe50_rt/`**（50/50 成功、`.skel` 同步、
`check_clip_visibility` 50 角色只剩 4 条校验器侧残留），
详见 `报告与校验.md` 7.8。`samples/`（三主力交付样例）还没重做，需要时按同法补。

所有"未支持"的通道现在**都会打 warn 并写进 `_static_info.json`**
（`spriteSwap` / `unsupportedChannels` / `drawOrder`），不会再静默丢掉。
