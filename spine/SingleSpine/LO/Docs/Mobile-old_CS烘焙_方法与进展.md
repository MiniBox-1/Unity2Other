# Mobile-old：把 CS 脚本的影响「烘焙」进 Spine 产物 —— 方法与进展

> 写于 2026-10-08 晚。承接 `Mobile-old_转Spine_条件与目的.md` §6。
> 本文记录**已经跑通并逐顶点验证过**的做法、踩过的坑、以及两个样例角色
> （Alexandra NS1 / Alice NS1）的实测数字。
>
> **本文是"过程记录"**（逐轮排查、当时的判断与后来的更正都保留，便于复盘）。
> **要快速上手请看 [`Mobile-old_Spine转换_交接文档.md`](Mobile-old_Spine转换_交接文档.md)**，
> 那里面只讲"现状 / 交付物 / 必看约束 / 待办"。

---

## 1 一句话结论

静态转换器只读**磁盘资源**（clip 曲线 + 网格 + 蒙皮），运行态由 CS 脚本产生的形变
（DynamicBone 的逐帧弹簧、Puppet2D 的 spline/IK 解算）**不在产物里**。
现在做成了这样一条**可复现、可验收**的补法：

```
Unity 里逐帧跑「clip 姿态 A -> 跑 CS -> 姿态 B」，只取 B-A
   -> 把差值按实测标定出的线性映射换成产物坐标
   -> 加到产物已有的 deform 关键帧上
```

**Alexandra NS1 端到端验收：合并后产物 vs Unity 真值 = 中位 0.022 px**
（和基线 vs 纯 clip 的 0.022 px 完全一样 ⇒ 加进去的 CS 形变没有引入任何可测误差）。

---

## 2 工具链（都已落地）

| 文件 | 作用 |
| --- | --- |
| `D:\VB\Unity2Spine\tools\bake_cs\prefab_cs_report.py` | **离线**列 prefab 上挂了哪些脚本、DynamicBone 管辖哪些骨骼、哪些渲染器会被动到 |
| `…\bake_cs\run_bake.py` | 驱动端：从产物取「候选部件 + 关键帧时刻」，**逐 state** 调 Unity 采集，再拼 `bake.json` |
| `…\_scratch\_csbake\runner_bake2.cs` | Unity 侧采集器（`execute_code` 片段）：跑 CS 驱动器、逐关键帧记 `delta / l2w / absA` |
| `…\bake_cs\merge_cs_bake.py` | 把 `delta` 标定+合并进产物 JSON，并重建 `.skel` |
| `…\_scratch\_csbake\verify_cs.cs` + `verify_merge.py` | **独立**校验：另起一次运行到同一时刻取 A/B，与基线/合并产物逐顶点对账 |
| `…\bake_cs\mcp_exec.py` | 把 `.cs` 片段文件丢给 Unity MCP 的 `execute_code` 并取回结果（避免 PowerShell 吃引号） |

CS 驱动器**按脚本名自动发现**（不依赖编译引用）：

| 脚本 | 何时被调 | 影响 |
| --- | --- | --- |
| `DynamicBone` | 每 clip 一次 `SetupParticles()`；每帧前 `InitTransforms()`、帧后 `UpdateDynamicBones(dt)` | 逐帧弹簧（头发/胸/耳环/领带） |
| `Puppet2D_GlobalControl` | 一次 `Init()`；每帧 `Run()`（先于 DynamicBone） | spline（尾巴）+ IK（腿）+ parent/FFD 控制 |
| `Puppet2D_HiddenBone` | 不用调（反编译代码里没有任何地方会调它的 `Refresh`，是编辑期辅助件） | — |
| 未启用的组件（如 Alice 的 `CTRL_Dynamic/Bone_Hair` DynamicBone） | **跳过** | 运行时不生效 |

---

## 3 三条硬约束（不遵守就一定出错，逐条都是踩出来的）

### 3.1 乘积公式里必须带「局部 z」

2D 模型的渲染器 transform 是**绕 X 轴转 90°**的，局部网格躺在 **XZ 平面**上：

```
世界 = l2w * (x_local, y_local≈0, z_local)
```

只存 x,y 会把**整根纵向轴**丢掉（症状：拟合残差 100+px、delta 对不上）。
→ `bake.json` 里 `delta`/`absA` 都是**3 分量**，用 `l2w` 的线性部分转世界。

### 3.2 只能在「产物自己的关键帧时刻」取样

产物的 deform 是**逐帧采样后又做过关键帧裁剪**的；在任意时刻线性插值出来的值
**不等于**真值。拿它做标定会把插值误差当模型误差（实测残差从 0.004px 顶到 100px）。
→ 由 `run_bake.py` 从产物导出每条动画的关键帧时刻，交给采集器，**只在这些帧**读顶点。

### 3.3 探测和正式采集不能用同一个实例

为了知道"哪些渲染器真的会被动到"，要先跑一遍探测（跑 CS 再比较形状指纹）。
探测会把 DynamicBone 的粒子状态搅乱，之后即使 `InitTransforms()+SetupParticles()`
重新起，`B-A` 仍会偏差 **1e-3 世界单位（≈8px）**。
→ 探测单独跑一次（`bake=0`），把命中的渲染器写成 `picked.txt`；正式采集用
`probe=0 + picked=picked.txt`，在**全新实例**上跑。修好后误差降到 5e-7（≈0.003px）。

### 3.4 其它要点

| 点 | 说明 |
| --- | --- |
| 采样根 | `AnimationMode.SampleAnimationClip` 的根必须是 **Animator 所在物体**（曲线 path 相对它），不是 prefab 根 —— 传错就"什么都采样不到" |
| 必须在 Edit 模式手动步进 | Edit 模式下 MonoBehaviour 的 Update/LateUpdate 不跑，不会和手动步进抢；Play 模式会被 Animator/DynamicBone 自己抢先 |
| `AnimationMode` 的告警 | `Could not register property modification for animation binding ...` 是 DynamicBone 直接写 Transform 造成的，实例用完即毁、不用回滚；采集期间用 `Debug.unityLogger.logEnabled=false` 静音 |
| MCP 超时 | `execute_code` 大概 50 s 会被服务端判超时（返回 null，Unity 其实还在跑）。**一次调用只采一个 state** |
| 复杂度 | 帧循环必须在**外层**、渲染器在内层。反过来写就是 O(渲染器×帧)：Alice 那次跑了 5 min、写出 266MB 才结束 |

---

## 4 产物的坐标口径（关键发现）

产物顶点**不是** `unit_k*(世界-原点)`。实测（Alexandra，8 个受动部件全部一致）：

```
产物顶点 = S * (Unity 世界顶点) + T        S 对角、无翻转、各部件同一份
Alexandra:  S = 5367.036*I   （info 里 unitScale=732.6）
            S == unit_k / lossyScale = 732.601 / 0.136500 = 5367.037  ← 差 2e-7
```

也就是说转换器内部的坐标树根与 Unity 根之间差一个整体缩放（1/0.1365）。
**因此合并量 = S * (l2w_linear * (B_local - A_local))**，S 靠 `absA` 最小二乘标定，
并用 `unit_k/lossyScale` 交叉验证。

> 注意：`S = unit_k/lossyScale` 只在**整个 rig 只有一个尺度**时成立。
> Alice 的渲染器 lossyScale 有 `0.12443 / 0.99 / 1.0` 三种，标定出的是汇总值
> `[[822.07, 4.28],[9.79, 831.29]]` —— 所以**标定不能省**，解析式只当旁证。

### 4.1 ⚠️ 更正：S 是**逐部件**的 `unit_k / |lossyScale|`

上面那段"Alice 要用汇总值"的结论**是错的**，2026-10-08 晚用新写的
`PartDataRecorder` / `PartDataExport`（§8）重新测过：

| 部件 | lossyScale | 用汇总 S=822 的残差 | 用 `unit_k/\|lossy\|` 的残差 |
| --- | --- | --- | --- |
| parts_Body | 0.12442 | 中位 **158.96 px** / 最大 371.8 | 中位 **0.0021 px** / 最大 0.048 |
| parts_Breast_L / legs / tail … | 0.99 / 1.0 | ~0.003–15 px | ~0.003–15 px |

（口径：`lobby` 整条 601 帧 × 85 顶点 = 5.1 万个样本，只解一个平移。）

**原因**：一个角色里不同渲染器的 `lossyScale` 可以差 8 倍（Alice 的
`parts_Body` 是 0.12442，四肢是 0.99），全局拟合会被"多数派"带偏，
body 这类少数派就被算成 159px 的假误差。转换器内部的坐标口径等价于

```
产物 = unit_k / |渲染器 lossyScale| * (l2w_linear · 局部顶点) + T
```

`merge_cs_bake.py` 已改成**逐部件**用这个式子（`lossyScale` 缺失时才退回汇总拟合），
汇总拟合只作为旁证打印。

改完之后 Alice 的基线误差从"中位 2.68px / parts_Body 161.8px"降到
**中位 0.0557px**（最大 27.7px，见 §5.3）。

---

## 5 两个样例的实测数字

### 5.1 Alexandra NS1（只有 DynamicBone）

| 项 | 值 |
| --- | --- |
| 挂的脚本 | `Actor` / `ActorPartsView` / `ActorAnimator`（空壳）+ DynamicBone ×2 |
| DynamicBone | ①`bone_Breast/Breast`（6 根）②`Hair_set/bone_Hair/Hair`（28 根） |
| 受动渲染器 | **8 / 36**：`parts_{F,L,BR,B}_hair`、`parts_tie`、`parts_breast`、`parts_{L,R}_earring` |
| delta 幅度 | 最大 0.37 世界单位 ≈ **270 px**（后发）；胸最小 |
| 关键帧 | 5596 → 4495（**-19.7%**，因为按世界的裁剪阈值做了二次裁剪） |
| 验收 | 基线 vs Unity(A) 0.022px；**并合 vs Unity(B) 0.022px**；(并合-基线) vs S(B-A) 0.003px |

### 5.2 Alice NS1（DynamicBone + Puppet2D）—— 用户点名的例子

| 项 | 值 |
| --- | --- |
| 规模 | 325 个 GameObject / 44 个 MonoBehaviour（28 个 SMR + 112 个 SpriteRenderer） |
| 挂的脚本 | `Puppet2D_GlobalControl`×1、`Puppet2D_HiddenBone`×31、`Puppet2D_SplineControl`×1（尾巴）、`Puppet2D_IKHandle`×2（两腿）、DynamicBone×2（`Bone_Breast` **启用**、`Bone_Hair` **未启用→跳过**）、`Actor`/`ActorPartsView`/`CameraBoundary`（空壳） |
| 产物 | 41 个部件、5 条动画（Start 2.5s / breast 8s / Tep_1 9s / lobby 10s / `3P_Alice_NS1_curtain` 3.5s），`static_check` 四项全 0 |
| 受动渲染器 | **13 / 41**：`parts_Body`、`parts_Breast_{L,R,wing,L_F}`、`parts_Gatherbelt_Neck`、`parts_leg_{foot,L_up,L_down,R_up,R_down}`、`parts_Tail_{B,F}` |
| 关键帧 | 8130 → 5237（**-35.6%**） |
| 采集耗时 | 每个 state **0.4–1.5 s**（探测一次 + 5 次采集）；`bake.json` 27.7 MB |
| 并合精度 | (并合-基线) vs S(B-A)：中位 **0.0175 px**、p90 0.42、最大 1.0（n=1278） |

### 5.3 基线误差（已更正）

> **2026-10-08 晚更正**：之前这里写着"`parts_Body` 基线偏 137px，是转换器的问题"，
> **那是错的** —— 真正的原因是当时用了"全局 S"标定（见 §4.1）。换成逐部件
> `unit_k/|lossyScale|` 之后，`parts_Body` 的基线误差是 **0.031 px**。

现在的真实基线误差（`lobby` t=3.0，逐顶点对账 Unity 的纯 clip 真值）：

| 部件 | 中位 | p90 | 最大 | 说明 |
| --- | --- | --- | --- | --- |
| parts_Body | 0.031 px | 0.141 | 0.149 | 已正常 |
| parts_Breast_* / belt | 0.003–0.074 px | ≤1.3 | ≤1.3 | 已正常 |
| parts_leg_* | 0.83–3.40 px | ≤5.1 | ≤5.1 | 小偏差 |
| **parts_Tail_F / Tail_B** | **21.3 / 17.5 px** | 27.0 / 23.6 | 27.0 / 23.6 | ⚠️ **唯一还剩的真问题** |

汇总：基线 vs Unity(A) 中位 **0.0557 px**、p90 17.71、最大 27.65（n=1278）；
合并后 vs Unity(B) 中位 0.3553、p90 17.71、最大 27.65 —— **CS 烘焙没有恶化任何东西**。

尾巴这两个部件是 `Puppet2D_SplineControl`（`CTRL_Spline_Tail`）驱动的，
17–21px 大约是尾巴自身尺寸（541×149 px）的 4%。**下一步排查方向**（尚未做）：
核对 clip 到底是"动画 CTRL 样条控制点"还是"直接动画尾骨"——
若是前者，转换器读到的尾骨姿态可能来自另一条路径。
`tools\bake_cs\diag_part_err.py` / `check_part_S.py` 可以直接复用。

### 5.4 尾巴这 17–21px 查到哪一步了（2026-10-09）

**已经查实的：**

1. 尾巴的**变形骨链**是 `Global_CTRL/Controllers/CTRL_Spline/bone_1 … bone_30/…`
   （`parts_Tail_F` 的 15 根骨、`parts_Tail_B` 的 22 根骨都在这一支上），
   和 `Bone_Pelvis/Bone_Tail_0/…` **不是同一条链**。
2. 逐个解析 `3P_Alice_NS1_breast.anim` / `_idle` / `_tep` 的曲线路径，含 Tail/Spline 的
   只有这些：`Bone_Pelvis/Bone_Tail_0`、**`CTRL_Spline_Tail/spline_GRP_1/spline_Ctrl_GRP_1..7/spline_Ctrl_N`**、
   `…/spline_Ctrl_7/Bone_Tail_End`、`Bone_Tail_Shadow2`。
   **变形骨链 `Controllers/CTRL_Spline/bone_N` 不在里面** ⇒ 纯 clip 姿态下它是靠
   `Puppet2D_SplineControl.Run()` 的 Catmull-Rom 解算才动的（运行时行为）。
   注：clip 里还有约 90 条 `path: <数字>` 的**哈希路径曲线**，需要单独核
   （工程里有 `tools\hash_path_scan.py`）。
3. 用 `diag_part_err.py` 看偏差形状：在 `Start` t=0 时它是**纯常量平移**
   （逐顶点标准差 **0.00**，平移量 ≈ (13.5, −5.7) px ≈ 0.018 世界单位），
   这个部件单独重拟合仿射后残差只有 **0.0048 px** —— 也就是说
   **几何本身是对的，差的是一段整体位移**（在 `lobby` t=3.0 上再叠加约 6.8 px 的形状抖动）。
4. 用转换器自己的 API（`diag_tail_assign.py`）跑：尾巴相关 91 个 transform 里，
   t=0→t=3 世界坐标变了的只有 **2 个**（`Bone_Tail_0` Δ=0.0056、`Bone_Tail_End` Δ=0.039）；
   真正的变形骨链 **Δ=0**。⇒ 转换器也认为这条链在纯 clip 下是静止的。

5. **结论**：这 17–21px 是**基线（转换器）侧的问题**，跟 CS 烘焙无关 ——
   合并前后这个偏差一模一样（21.310 → 21.308 px）。
   尾部**运行时由样条驱动的那部分形变**，CS 烘焙是照常加进去的（`lobby` 里最大 11 px）。

**还没钉死的 / 下一步：**

* 产品里 `parts_Tail_F` 在 `lobby` 上的 deform 幅度有 17.1 px，但转换器自己算出来这条链
  是静止的 —— 两边矛盾，指向"这段形变在转换器里的来源不是骨骼链本身"
  （候选：① clip 里那 ~90 条哈希路径曲线被映射到了别的 transform；
  ② 该部件的 `setup` 参考帧不是 setup clip 的 t=0；③ 蒙皮用的 `bones` 列表与实际不同）。
  下一步用 `world_of('lobby', t)` 直接把这条链每帧的世界坐标打出来对比即可定位。
* 影响面：尾巴整体偏移约 0.018 世界单位（≈4% 尾巴尺寸），**不影响"能不能用"**，
  但同一套机理如果出现在别的角色上，可能解释其它零星偏差。

### 5.5 尾巴查清了：**形状与运动都对，只差一个固定平移**（2026-10-09 收尾）

> **⚠️ 本节结论已在 §5.6 被推翻**：那个"固定平移"是我 bake 里 A 被污染的产物，
> 不是产品/转换器的问题。修好后尾巴残差 0.0031px。保留本节是为了记住排查路径。

先纠正 5.4 里那句"转换器自己算出来这条链是静止的" —— 那是**看错了指标**：
当时读的是**质心**位移（尾巴绕近端转，质心几乎不动），而真正该看的是**逐顶点最大位移**。

用 `cmp_tail_motion.py` 在同一把尺子下对等比较（产品 deform 的**变化量** vs
Unity 纯 clip 的**逐顶点最大位移**，都相对各自首帧，消掉常量）：

| clip | 产品 deform 变化量 | Unity 纯 clip 位移 | 差 |
| --- | --- | --- | --- |
| Start | 51.90 px | 51.69 px | 0.4% |
| Tep_1 | 169.24 px | 167.55 px | 1.0% |
| breast | 194.37 px | 192.43 px | 1.0% |
| lobby | 17.21 px | 17.20 px | 0.06% |

**⇒ 转换器在尾巴上的"运动"是对的**（和 Unity 逐条吻合到 1% 以内）。

再用 `diag_tail_err_time.py` 看残差的**时间结构**（`lobby`，601 帧全查）：

```
      t        mean(e)            std(e)      |mean(e)-mean(e0)|
  0.000 (  13.49,  -5.67)          0.001            0.000
  3.000 (  13.49,  -5.67)          0.001            0.000
  6.000 (  13.49,  -5.67)          0.008            0.002
 10.000 (  13.49,  -5.67)          0.001            0.000
  mean(e) 相对首帧的最大漂移 = 0.03 px
```

**⇒ 整个残差 = 一个恒定平移 (13.49, −5.67) px（≈0.018 世界单位）**；
逐顶点形状误差 std **0.001–0.010 px**，601 帧漂移 **0.03 px**。

**最终定性**：

| 项 | 状态 |
| --- | --- |
| 尾巴的**形状** | ✅ 与 Unity 一致（0.01 px） |
| 尾巴的**运动**（含样条驱动的部分） | ✅ 一致（1% 以内），CS 形变也照常烘进去 |
| 尾巴的**绝对位置** | ⚠️ 整体偏 **14.6 px ≈ 0.018 世界单位**（约尾巴自身宽度的 2.7%） |

这个 14.6 px 是**常量**，来源是标定里的 **T（每部件的平移项）**：
`T` 是用 `setupClip`（Alice 是 `Start`）拟出来的，而尾巴在不同动画下的
`T` 会差这么多 —— 即"尾巴相对身体被平移了一点点"，不是形变错、也不是 CS 烘焙错
（合并前后这个偏差一模一样：21.310 → 21.308 px）。

**要不要修 / 怎么修**：这是**常量偏移**，量级 2.7%，画面上几乎看不出；
如果要修，属于转换器侧"每部件每动画的常量项"问题（用
`diag_tail_err_time.py` 对任意部件都能一键量出来），与本文的 CS 烘焙链路无关。

---

### 5.6 ✅ 真凶：**bake 采到的 "A" 被 CS 脚本污染了**（2026-10-09 定案并修复）

**怎么抓到的**：同一 clip、同一 t，`runner_bake2` 和 `PartDataExport` 给出的尾巴
顶点位置不一致（t=0.1 时前者 (-0.8551,0.0402)、后者 (-0.8521,0.0373)）——
两个采集器对同一帧给出不同答案，说明其中一个采到的不是"纯 clip"。

**根因**：`AnimationMode.SampleAnimationClip` 只写**有曲线的属性**。
Alice 尾巴那条链（`Global_CTRL/Controllers/CTRL_Spline/bone_1..30/…`）
**在 clip 里一条曲线都没有**（已用字符串路径 + CRC32 双重确认），
于是每帧采样**不会覆盖**它 —— 上一帧 `Puppet2D_GlobalControl.Run()` 写进去的
姿态就**残留**下来。结果：

| 量 | 实际采到的 |
| --- | --- |
| A（"纯 clip"） | 残留着上一帧脚本解算结果 ≠ 纯 clip |
| B − A | 只是脚本效果的**逐帧增量**，不是完整效果 |

Alexandra 没暴露这个问题，因为她的头发骨头**有曲线**，每帧都被 clip 覆盖。

**修法**（三处采集器都改了）：

```
进 Play/Instantiate 后先快照所有 Transform 的 local TRS
每帧： 恢复全部 Transform 到该快照  ->  SampleAnimationClip(t)  ->  记 A
                                   ->  跑 CS  ->  记 B
```

即"**先回到预制体初始姿态，再让 clip 覆盖能覆盖的**"，这样没有曲线的节点
就真的是静止的（= 静态转换器看到的样子），A 与 B 的口径一致。
改动落在 `runner_bake2.cs` / `verify_cs.cs` 的 `preStep`。

**修完的实测（Alice `lobby`，13 个部件 × 1278 顶点）**：

| 指标 | 修之前 | 修之后 |
| --- | --- | --- |
| 标定残差（逐部件中位） | 尾巴 15.69px / 最大 37.0px | **全部 0.0027–0.0031px，最大 0.0052px** |
| 基线 vs Unity A（中位/p90/最大） | 0.0557 / 17.71 / 27.65 px | **0.0163 / 0.0557 / 0.0637 px** |
| 并合 vs Unity B（中位/p90/最大） | 0.3553 / 17.71 / 27.65 px | **0.0640 / 0.4768 / 1.0462 px** |
| 尾巴 parts_Tail_F | 基线 21.3px | **基线 0.001px / 合并后 0.004px** |
| Alexandra（对照） | — | 0.0221px（**无退化**） |

> 合并后最大 1.05px 正好等于关键帧裁剪阈值（0.001 世界单位 ≈ 0.8px），
> 也就是说**除了裁剪误差，已经没有别的偏差**。

**教训（写进"必看手段"）**：做"脚本前/脚本后"对比时，
**必须显式把整棵 hierarchy 复位到参考姿态**再采样；
"clip 没动画它" ≠ "它是静止的"——只要有人写过它，它就不是静止的。

---

## 6 复现命令（照抄）

```powershell
cd D:\VB\Unity2Spine\tools\bake_cs
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"

# 0) 先静态转出基线（若还没转）
cd D:\VB\Unity2Spine
python -m ngui2spine.static_prefab_spine <uAnim.prefab> <产物目录> `
  --assets <工程>\Assets --skel --no-face-check

# 1) 采集（自动：探测一次 + 逐 state 各一次 MCP 调用）
cd tools\bake_cs
python run_bake.py --product <产物目录> --prefab <uAnim.prefab> --outdir <bake 目录>

# 2) 合并（标定 + 加到 deform + 重建 .skel）
python merge_cs_bake.py --product <产物目录> --bake <bake 目录>\bake.json `
  --out <合并后产物目录> --report <bake 目录>\merge_report.json

# 3) 独立验收（另起一次 Unity 运行取真值）
#    D:\VB\Unity2Spine\_scratch\_csbake\verify.txt 里填 prefab/state/time/out/parts
python mcp_exec.py ..\..\_scratch\_csbake\verify_cs.cs
python verify_merge.py --product <产物目录> --merged <合并后产物目录> `
  --verify <verify.json> --calib <merge_report.json>
```

---

## 7 离线渲染对比（D:\VB\Viewer\Render）

**渲染器已迁到 `D:\VB\Viewer\Render\v4`**（旧路径下现在只剩 `v3`/`v4` 两个子目录），
venv 也变成 `D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe`；
`tools\rt_frames.py` 的 `RENDER_ROOT` 已改成"优先 v4、缺失再回落旧路径"。

对比工具：**`tools\bake_cs\render_cmp.py`** —— 在**同一个 GL 会话**里先渲基线、再渲合并后，
输出逐时刻的 `base__<动画>__t####.png` / `merged__…png` 和三联图
`trio__<动画>__t####.png`（左=基线 中=合并后 右=差异×N），并打印
内容像素数 / 有差异像素数 / 差>8 的像素数 / 最大差 / 差异重心与包围盒。

```powershell
cd D:\VB\Unity2Spine\tools\bake_cs
& "D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe" render_cmp.py `
  --base   "D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv\3P_Alice_NS1" `
  --merged "D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv_cs\3P_Alice_NS1" `
  --anim breast --times 5.5,5.9,6.2,7.0 `
  --out "D:\VB\Unity2Spine\_scratch\_csbake\render\alice_breast" --size 800
```

### 7.1 踩到的坑：`SetAnimationTime` 收的是**归一化时间**

`SpineRender.SetAnimationTime(name, normalizeTime)` 的第二个参数是 0~1 的**归一化时间**，
不是秒。直接传秒会让所有 `>=1` 的时刻绕回 0（症状：t=2/4/6/8 渲出来一模一样）。
`render_cmp.py` 现在自己从 `_static_info.json`（或 skeleton JSON 的最大关键帧时间）
取时长再换算。

### 7.2 实测（`lobby`：Alexandra vs Alice）

| 角色/动画 | 有差异像素 | 差>8 | 最大差 | 差异包围盒 | 视觉结论 |
| --- | --- | --- | --- | --- | --- |
| Alexandra `lobby` | 8.8K–21.9K | 3.6K–18.5K | 191–242 | x296–485, y0–254 | 红色**只在头发轮廓 + 胸前带子**；身体/腿/椅子逐像素相同 |
| Alice `lobby` | 0.4K–1.4K | 39–327 | 67–107 | x301–460, y346–472 | 只有胸口/髋部一点点轮廓变化 |
| Alice `breast` | 5.0K–6.8K | 3.9K–4.5K | 222–223 | x301–464, y338–492 | 红色集中**在胸（实心块）+ 左腿/髋部细轮廓** |

> 注意 Alice 的 `lobby` 与 `breast` 差别很大：CS 造成的顶点位移**逐动画不同**，
> 不能只看一条动画就下结论。

### 7.3 每个部件到底被 CS 推了多少（产物像素，1:1 源图像素）

| Alexandra | 最大位移 | | Alice | 最大位移 |
| --- | --- | --- | --- | --- |
| parts_B_hair | **266 px** | | parts_leg_L_up | **331 px** |
| parts_tie | 167 px | | parts_leg_L_down | 331 px |
| parts_L/R_earring | 110 / 96 px | | parts_leg_foot | 196 px |
| parts_L/F/BR_hair | 90 / 55 / 49 px | | parts_Gatherbelt_Neck | 147 px |
| parts_breast | 43 px | | parts_Breast_wing / L / R | 51 / 34 / 25 px |
| | | | parts_Tail_F / B | 11 / 5 px |

（Alice 的腿部大位移出现在 `breast` 动画 t≈5.9：那里的姿态下左腿大部分被身体/尾巴挡住，
所以画面上只表现为一条细红轮廓 —— **位移大 ≠ 画面变化大**，两个指标都要看。）

---

## 8 逐帧部件数据导出（两个 C# 脚本）

为了把"部件级"的口径钉死，写了两个**装在 Unity 工程里**的脚本，一起放在
`proj-Mobile-old\Assets\`：

### 8.1 `Raw\Scripts\PartDataRecorder.cs`（挂上去就能用）

一个带 `[SerializeField]` 字段的 MonoBehaviour：把脚本挂到模型根节点（或它的父节点），
Inspector 里设好字段，进 Play 模式按热键（默认 **F9**）开录；勾了
`Auto Start On Play` 就自动录。**每条动画写一个 `<state>.json`。**

Inspector 字段：

| 字段 | 作用 |
| --- | --- |
| `Output Dir` | 输出目录 |
| `File Tag` | 文件名前缀（多次录同一角色时区分） |
| `FPS` | 采样帧率（同时用来设 `Time.captureFramerate`，保证固定步长） |
| `States` | 要录的 state（留空=控制器里全部） |
| `Part Filter` | 路径子串过滤（留空=全部渲染器） |
| `Record Vertices` | 是否逐顶点记录（关掉只记矩阵/包围盒，文件小很多） |
| `Record Bones` | 是否记每根骨骼的局部 pos/quat/scale |
| `Record Invisible Too` | 关掉的渲染器要不要也记 |
| `Drive Cs Scripts` | **true=录"脚本生效后"(B)；false=录制时临时关掉 DynamicBone/Puppet2D，得到"纯 clip"(A)** |
| `Hotkey` | 开始录制热键 |

也可以由脚本/MCP 精确调用：

```csharp
var rec = go.AddComponent<PartDataRecorder>();
rec.Configure(outDir, 60f, new[]{"lobby"}, "parts_Tail", true, false);
rec.BeginCapture();                       // 协程逐帧录
rec.CaptureOneFrame(clipTime, normTime);  // 或者只抓一帧（自己步进时用）
```

### 8.2 `Editor\PartDataExport.cs`（编辑模式，精确到帧，不用进 Play）

菜单 **Tools/2DModel/逐帧部件数据导出/**：
* `导出到…`（选中 prefab 资产）—— 一次导出 **A（纯 clip）+ B（脚本生效）**两份，
  同帧对齐，直接可以逐帧做差；
* `导出选中角色（A 与 B 都导）` —— 输出到上次选的目录。

原理：`AnimationMode.SampleAnimationClip` 在 **Animator 所在物体**上手工逐帧采样
（曲线 path 相对它），CS 脚本按运行时顺序手工驱动：

```
InitTransforms -> SampleAnimation(t) -> [A] -> GlobalControl.Run()
                                      -> UpdateDynamicBones(dt) -> [B]
```

MCP 里直接调（反射，脚本已编进 Assembly-CSharp(-Editor)）：

```csharp
PartDataExport.Run(prefabPath, outDir, 60f, new[]{"lobby"}, "parts_Body", true, true);
```

### 8.3 输出格式（两边的 JSON 同一套 schema）

```
{ "prefab","unity","mode"(edit|play),"state","length","fps","csDriven",
  "times":[...], "normalized":[...],
  "parts":[ {"path","kind","n","lossyScale":[3],"bonePaths":[...]} ],
  "frames":[ {"t","nt","parts":[ {"i","active","l2w":[16],"bounds":[6],
                                 "verts":[3n], "bones":[10/根] } ]} ] }
```

`verts` 是**渲染器局部坐标**（蒙皮走 `BakeMesh`，精灵走 `Sprite.vertices`），
要用 `l2w` 转世界；**必须带 z**（2D 模型的局部网格躺在 XZ 平面，§3.1）。

### 8.4 配套的对账脚本

| 脚本 | 干什么 |
| --- | --- |
| `tools\bake_cs\check_part_S.py` | 拿 `__A.json` 逐帧检验"产物 = S*世界+T"的 S 该取哪个（就是 §4.1 用的那支） |
| `tools\bake_cs\diag_part_err.py` | 定位单个部件的偏差形状（常量偏移/刚性差/形变差） |
| `tools\bake_cs\render_cmp.py` | 基线 vs 合并后的离线渲染三联图（§7） |

---

## 9 CS 逻辑搬进转换器（`src\unity2spine\convert\cs_runtime.py`）

> 2026-10-09 开的新路线：**不再"录 Unity 数据再合并"**，而是把反编译出来的 C# **逐行复刻**，
> 让 `static_prefab_spine` 自己就能算出脚本效果。

**已完成：**

| 件 | 状态 |
| --- | --- |
| `parse_cs_components(prefab, assets)` | ✅ 纯离线读 prefab 上的 CS 组件。Alice 实测正确识别：`DynamicBone×2 / GlobalControl×1 / SplineControl×1 / IKHandle×2 / HiddenBone×34`，并带出 `m_Root / m_Weight / numberBones / _splineCTRLS / bones / m_Bones` 等字段 |
| `Runtime`（world/local 矩阵 + `set_world` 语义） | ✅ 脚本写的是 world 的 position/rotation，这里同样按 world 写、再重算子树 |
| `Puppet2D_SplineControl.Run` | ✅ Catmull-Rom + `LookRotation` + `eulerAngles.y`，**已验证** |
| `Puppet2D_IKHandle.CalculateIK` | ✅ 两骨 IK + pole + AimDirection + Offset，**已验证** |
| `DynamicBone` 逐帧弹簧 | 🔶 已写完，**弹簧数值对，但写回姿态后蒙皮炸了**（见 §9.3） |

**样条复刻的验证**（Alice `breast`，`parts_Tail_F`，单位=世界单位）：

| t | Unity \|B−A\| 中位 | 转换器算的脚本位移 中位 | 两者差 |
| --- | --- | --- | --- |
| 0.000 | 0.00131 | 0.00131 | 0.00000 / 0.00001 |
| 1.333 | 0.11552 | 0.11552 | 0.00000 / 0.00001 |
| 2.667 | 0.18536 | 0.18537 | 0.00000 / 0.00001 |
| 4.000 | 0.21575 | 0.21576 | 0.00000 / 0.00001 |
| 5.333 | 0.09861 | 0.09861 | 0.00000 / 0.00001 |

**最大偏差 1e-5 世界单位 ≈ 0.008 px** —— 样条那条路（也就是"CS 主要影响的尾巴"）
已经**脱离 Unity 也能算对**。

### 9.1 IK 复刻的验证（Alice `breast` → `parts_leg_L_up`）

| t | Unity \|B−A\| 中位 | 转换器算的脚本位移 | 两者差 |
| --- | --- | --- | --- |
| 0.000 | 0.06994 | 0.06994 | 0.00000 / 0.00004 |
| 1.333 | 0.00386 | 0.00386 | 0.00000 / 0.00004 |
| 2.667 | 0.00549 | 0.00549 | 0.00000 / 0.00004 |
| 4.000 | 0.02001 | 0.02001 | 0.00000 / 0.00004 |
| 5.333 | 0.06721 | 0.06721 | 0.00000 / 0.00004 |

**最大偏差 4e-5 世界单位 ≈ 0.03 px**。两条腿的 IK（含 pole / AimDirection /
`Offset` 旋转 / 层级带动的中间关节位置）都是一次对拍通过。

### 9.2 移植时踩到的坑（记一下免得再犯）

| 坑 | 症状 | 修法 |
| --- | --- | --- |
| `mdl.transforms` 键是 **int**，YAML 读出来是 **str** | `str in dict` 永远 False，样条一个控制点都解析不到 | `_as_tfid()` 统一转 int |
| `_splineCTRLS` 是 `List<Transform>`、`bones` 是 `List<GameObject>` | 两个映射混用 | 分别用 tfid / `go→tfid` |
| `_field()` 把 `m_Root: {fileID: 123}` **整串**存下来 | `int()` 失败 → DynamicBone 找不到根节点（valid=False） | 引用/向量单独用 `_ref()`/`_vec3()` 解析 |
| `_norm()` 返回标量却被当向量用 | 重力为 0 时 `gn[i]` 抛异常 | 另写 `_normalized()` |

### 9.3 🔶 DynamicBone：两个真 bug 已修，还差一点精度

修掉的两个 bug（都会让结果炸掉，值得单独记）：

| # | bug | 症状 | 根因 |
| --- | --- | --- | --- |
| 1 | `mat4_scale` 取**行**范数 | 缩放被平方放大，顶点跑到 1e7–1e8 | `mat4_from_trs` 建的是 `M = R·S`（缩放落在**列**上，和转换器 `mat4_mul`/`mat4_vec` 同一套列向量约定）。行范数只在"均匀缩放 / 90° 换轴"时碰巧相等 —— **尾巴和腿正好是后者，所以前面两个对拍都过了**；胸骨链有任意旋转就露馅 → `mat4_quat` 拿到非正交矩阵 → 返回**非单位四元数**（实测模长 272！） |
| 2 | `set_world` 用 (pos,quat,scale) **重建**世界矩阵 | 即使不做任何物理，t=0 就凭空偏 **0.039 世界单位（31px）** | Unity 的语义是"改 **local**，再由父级合成 world"。父级非均匀缩放 + 旋转会让 world 矩阵带**剪切**（这个 rig 的 `Size_root` 有 0.001 的 Z 缩放，一旋转就有剪切），重建会把剪切丢掉。改成"算 local 再 `parent×local`"后，t=0 精确为 0 |

**修完的对拍**（Alice `breast` → `parts_Breast_L`，单位=世界单位）：

| t | Unity \|B−A\| | 转换器算的 | 差 |
| --- | --- | --- | --- |
| 0.000 | 0.00000 | 0.00000 | 0.00000 |
| 1.133 | 0.00974 | 0.01026 | 0.00068 / 0.00352 |
| 2.267 | 0.00577 | 0.00433 | 0.00224 / 0.00447 |
| 3.400 | 0.00633 | 0.00430 | 0.00192 / 0.00417 |
| 4.533 | 0.00142 | 0.00054 | 0.00084 / 0.00483 |
| 5.667 | 0.00346 | 0.00101 | 0.00245 / 0.00708 |
| 6.800 | 0.00414 | 0.00211 | 0.00195 / 0.00348 |
| 7.933 | 0.00206 | 0.00156 | 0.00050 / 0.00101 |

**量级已经对了**（不再发散、t=0 精确、随时间的变化趋势一致），
但残差 0.0005–0.0071 世界单位 ≈ **0.4–5.7 px**，比样条（0.008px）/IK（0.03px）差两个数量级。

**下一步排查方向**（按可能性排序）：

**2026-10-09 又推进了一步**：

**（2026-10-09 第二轮）粒子链顺序 + 单步隔离**：

* 根因之一找到并修掉：**粒子链必须按 Unity 的 `m_Children` 兄弟顺序建**，
  不能按解析器的 dict 顺序 —— `ApplyParticlesToTransforms` 是**顺序相关**的
  （它写进去的 rotation/position 会被后续迭代读到）。修之前坐标系仿射拟合残差
  **0.271**（粒子尺度才 0.35），修之后 **0.032**，单步误差 **0.19 → 7.5e-4**（好 25 倍）。
  新增 `parse_transform_child_order(prefab)` 就是干这个的。
* 新增 `diag_db_step.py` —— **单步隔离测试**：把 Unity 上一帧的粒子状态喂进移植版，
  只跑一步再比 Unity 下一帧。这样能把"某一步公式不对"和"误差逐帧累积"彻底分开。
  实测每步仍有 ~7.5e-4 的残差 ⇒ **还有一处公式层面的细小差异**（不是累积放大）。
* 粒子对应关系已确认完全一致：我的 7 个粒子与 Unity 的 7 个**同序同集合**
  （到 0 号粒子的距离集合两边到 4 位小数相同）。

**（2026-10-09 第三轮）纯公式测试：物理基本对了，剩下的在映射/写回**

为了绕开"坐标映射不完美 → 比较不准 → 看起来物理也错"的循环论证，把 Unity 那侧
**每一步的输入**（`bonePos` / `target` / `n` / 父索引）也 dump 出来
（`dump_db_particles.cs` 现在每条粒子每帧 14 个数），然后**完全在 Unity 的空间里**、
用 Unity 自己的输入和上一帧状态跑移植版的公式（`diag_db_formula.py`）：

| frame | 粒子0 误差 | 全部粒子最大误差 |
| --- | --- | --- |
| 1 | 0 | **2.4e-05** |
| 5 | 0 | 1.5e-04 |
| 20 | 0 | 7.9e-04 |
| 100 | 0 | 5.1e-04 |
| 300 | 0 | 4.9e-04 |

**结论**：

1. 根粒子（0 号）误差恒为 0（它的位置直接取自骨位置）✓；
2. 其它粒子单步误差 **2.4e-5 → 5e-4 就饱和**，**不累积**（约 0.02px → 0.4px）；
3. 所以**弹簧公式本身基本是对的**，之前测到的"网格级 0.4–5.7px"里，
   主要成分在**坐标映射 + 写回**这一段（`set_world` 的 local/world 往返、
   以及转换器坐标系的非均匀缩放），不在物理。

**（2026-10-09 第四轮）修正仪器错误后 —— DynamicBone 物理已复刻正确 ✅**

先修了一个**仪器 bug**：`dump_db_particles.cs` 原来是在 `UpdateDynamicBones`
**之后**再算 `bonePos/target/n` 的 —— 那时 `ApplyParticlesToTransforms` 已经把骨位
改过了，dump 出来的是"结果"不是"输入"，导致纯公式测试无效。把它挪到 step **之前**
再测：

| frame | 粒子0 误差 | 全部粒子最大误差 |
| --- | --- | --- |
| 1 | 0 | **2.42e-05** |
| 2 | 0 | 2.40e-05 |
| 5 | 0 | 1.23e-05 |
| 20 | 0 | 1.95e-04 |
| 100 | 0 | 2.45e-04 |
| 300 | 0 | 1.24e-04 |

**最大 2.45e-4 ≈ 0.2 px，且不累积**（就是 float32/float64 与算子顺序的量级）
⇒ **弹簧物理（PreUpdate / UpdateParticles1 / 2 / Skip / Apply）已复刻正确**。

**剩下最后一处的确切性质（已定位，未修）**：`_apply` 里那个
`FromToRotation(parent.TransformDirection(childLocalPos), Δpos)` 是在**转换器坐标系**
里算旋转，而这个 rig 的度量是**非均匀**的（`Size_root` 的局部 Z 缩放 = 0.001，
于是骨骼世界尺度是 `(0.124, 0.124, 0.000124)`）。非均匀度量下，"Unity 的那个旋转"
在转换器坐标系里**无法用四元数表达**（共轭 `D⁻¹·R_u·D` 不再是正交矩阵）。

⇒ **正确修法**：让整个 CS 运行时在**统一度量空间**里跑（把转换器坐标按该子树的
世界尺度缩放回 Unity 度量 → 物理与旋转都在那边算 → 再映射回产物坐标）。
这是设计层面的改动，单独一步做；它只影响"移植版"的精度（0.4~5.7px 那部分），
**不影响已交付的合并路线产物**。

* 新增 `_scratch\_csbake\dump_db_particles.cs` —— 反射把 Unity 侧 DynamicBone 的
  **粒子内部状态**（`m_Particles[i].m_Position / m_PrevPosition`）逐帧导出来，
  这样能把"弹簧物理"和"写回+蒙皮"彻底分开对账；
* 结果显示**粒子轨迹的量级已经对上 ~8%**（f=6：Unity 0.008256 / 我 0.008924；
  f=54：0.1686 / 0.1823），说明弹簧公式本身是对的，剩下的是细节项；
* 输入侧已排除：把骨骼**局部 TRS**（新增 `recordBones` 开关）逐帧对比，
  Unity 与转换器**到 6 位小数完全一致**；
* 已修但本例无效的一处（通用正确性仍要保留）：`Transform.TransformDirection`
  **不受缩放影响**，我原来的 `_mat_dir` 用了完整线性部分；这个 rig 的父骨旋转接近
  单位阵所以恰好是 no-op，但换角色会出错，已改成先 Gram-Schmidt 正交化。

1. `_update2()` 里 `n`（骨长）的读取时机 —— C# 是先算 `n = |parent.pos - this.pos|` 再进
   elasticity/stiffness，我这边顺序一致但对象是本帧采样后的骨头，值得逐帧打点核对；
2. `m_Time` 子步累加（`UpdateRate=60` + 每帧 `1/60`）在浮点边界上是否每帧恰好 1 步；
3. `_apply()` 里"父级旋转"的写入顺序（C# 是在一次循环里同时改 p2 旋转与 p 位置，
   p2 旋转会立刻影响后面的 `particle2.m_Transform.position` 读取）。

（另外：`SetupParticles` 在 Unity 里是 `Start()` 跑的、那一刻是**预制体姿态**，
我按 rest 姿态建粒子后结果与按 clip t=0 完全一致 —— 说明这条不是误差来源。）

### 9.4 （历史）修之前的状态

**已经对的**：解析与弹簧数值都对 —— Alice 的 `Bone_Breast` 解出 **7 个粒子**
（和 `prefab_cs_report` 报的"管辖 7 根骨骼"一致）、`骨长合计 0.2837`、
`object_scale 0.12442`、参数 `damping 0.07 / elasticity 0.03 / stiffness 0.10`；
逐帧跑 3 帧，粒子位置稳定在 `|pos| ≈ 0.35~0.43`（没有发散）。

**不对的**：把这套粒子姿态**写回 transform** 之后，`_skin_mesh` 出来的顶点跑到 **1e7~1e8**
世界单位（正常应该是 1 量级）。也就是说 —— **不是弹簧公式的问题，是"写回 + 重算子树"
这一环**：`Runtime.set_world()` 用 `mat4_scale(当前world)` 当缩放、再用 `mat4_invert(parent)`
求 local，疑似在某根骨头上遇到近奇异矩阵。

**下一步（很具体）**：在 `_apply()` 前后逐根打印 `parts_Breast_L` 那 3 根骨的
world 矩阵行列式/缩放，找出是哪一根、哪一个轴坏掉；对照 `unity_mesh.mat4_invert`
是否对 `det≈0` 有保护。修完再跑同一个 `validate_cs_port.py` 对拍即可。

对称验证脚本：`tools\bake_cs\validate_cs_port.py`（拿 `PartDataExport` 导的 A/B 当参照，
比的是"转换器算出来的脚本位移"vs"Unity 真实的 B−A"，差分之后坐标系差异自动消掉）。

**移植时踩到的坑（记一下免得再犯）**：

* `mdl.transforms` 的键是 **int**，YAML 里读出来的 fileID 是 **str** —— `str in dict` 永远 False，
  第一版一个控制点都没解析到；
* `_splineCTRLS` 是 `List<Transform>`（YAML 里直接是 Transform fileID = tfid），
  而 `bones` 是 `List<GameObject>`（要经 GameObject fileID 换算），**两个映射不能混**。

**下一步**：① 移植 `IKHandle`（两条腿）与 `DynamicBone`（胸），同样用 `validate_cs_port.py` 对拍；
② 给 `static_prefab_spine` 加 `--cs` 开关，把 `cs_runtime` 接进逐帧采样（
"每帧先把没曲线的 transform 复位到预制体姿态 → 采样 → 跑 CS"），
这样产出的就是自带脚本效果的一版，`run_bake.py`/`merge_cs_bake.py` 退化成回归对照。

---

## 10 已知限制 / 待办

1. **`Actor.cs` / `ActorPartsView.cs`（157/157 与 56/157 引用）仍是空壳**：换肤、部件开关
   这类"离散"影响没进这条烘焙链路（它们更适合落成 Spine 的 `skins` / attachment 时间轴，
   见 §6.2 的②）。目前链路只覆盖**逐帧连续形变**。
2. **多 Animator（副控制器）**：采集只驱动主 Animator；像 aeda 那种"第二套 Animator 驱动
   光晕"的角色要先扩展。
3. **`absA` 只在 setup clip 里记**，靠汇总拟合标定 S；若某角色 setup clip 里几乎不动，
   标定会退化，需要换 clip 或退回解析式。
4. **Alice `parts_Body` 的基线偏差**（§5.3）待查。
5. **批量**：单角色（Alice 规模）约 2–3 分钟（探测 1 次 + 5 次采集 + 合并 + 重建 skel）；
   157 个角色的中间 `bake.json` 合计约 3–5 GB，**合并完即可删**。
6. `verify_cs.cs` 目前只按 `parts=` 清单选渲染器；若要全量对账，把 `picked.txt` 换成
   产物全部部件的路径表即可。

---

## 11 2026-10-09 第二轮：尾巴离群定位（`curtain` / `Tep_1`）与两处修复

起点：`cmp_products.py` 拿"移植版（`--cs`）"对"已验证的合并产物"，中位 0.056px，
但列表里挂着尾巴：

```
3P_Alice_NS1_curtain parts_Tail_F_29   84   20.3864   60.6974
3P_Alice_NS1_curtain parts_Tail_B_113 122   17.2264   33.5712
Tep_1                parts_Tail_B_113 122   12.4682  101.5151
```

### 11.1 先看清"谁在动"：三条产物的尾巴曲线

`tools\bake_cs\diag_curtain.py` 把 基线 / 合并 / 移植 三条产物的 deform 逐帧摆在一起：

| 状态·槽位 | 基线 | 合并 | 移植 |
| --- | --- | --- | --- |
| `curtain` Tail_F 相对首帧最大位移 | 51.899px | 51.524px | 62.807px |
| `curtain` Tail_B | 8.506px | 8.314px | 33.571px |

而且 **合并版在每一个共同时刻上都和基线逐字节相等**（36.434=36.434、50.154=50.154…）。
即"合并版根本没给 curtain 的尾巴加任何脚本修正"。

### 11.2 录制数据本身：curtain 的 delta 恒为 0

翻 `_scratch\_csbake\3P_Alice_NS1\3P_Alice_NS1_curtain.json`：
13 个渲染器 × 105 帧，`delta` **每一个分量都精确等于 0.0**（不是"很小"，是 0）。
同一条管线在 `Start`（0.075）、`lobby`（0.052）、`breast`（0.269）上都有正常量级
—— 精确 0 只能是"B 通道没跑"，即 `postStep()` 什么都没改。

### 11.3 根因一：非 Base Layer 的状态，采 A 时漏了基底层

用 MCP 读 AnimatorController（`probe_layers.cs`）：

```
layer 0 name=Base Layer defaultWeight=0.000 blend=Override defaultState=Start
    state Start(3P_Alice_NS1_start) / breast / Tep_1 / lobby(3P_Alice_NS1_idle)
layer 1 name=curtain   defaultWeight=1.000 blend=Override defaultState=3P_Alice_NS1_curtain
```

再看各 clip 的曲线绑定（`probe_curtain.cs`）：

```
3P_Alice_NS1_curtain len=3.5   curves=24  tail=0  spline=0  ik=0  ctrl=0
Start                len=2.5   curves=188 tail=36 spline=30 ik=3 ctrl=179
lobby                len=10.0  curves=203 tail=39 spline=27 ik=3 ctrl=194
```

**curtain clip 只有 24 条曲线，压根不碰尾巴/样条控制点。**
而采集器建 A 用的是 `AnimationMode.SampleAnimationClip(go, 单条 clip, t)` —— 等价于
"把其余 transform 复位到预制体姿态，再只叠这一条 clip"，于是 A 的尾巴=静止姿态，
`GlobalControl.Run()` 在静止控制点上跑样条又还原出静止姿态 ⇒ **B−A ≡ 0**。

转换器侧不是这么干的：它按 Animator 层把 **基底层默认状态 clip 合成进这条 state**
（`compose_layers`），所以产物的 curtain 尾巴走的是基底层那条曲线。也就是说
**产物的 A 姿态 ≠ 录制侧的 A 姿态，录到的 delta 对不上，合并版白丢了一次修正。**

### 11.4 根因二：合并时把 delta 重采样到"产物自己的稀疏关键帧"上

`Tep_1` 不涉及层，问题在别处。基线产物对"纯 clip 几乎不动"的部件裁得很稀：`Tep_1`
的 `parts_Tail_B` 只有 53 个关键帧，**1.55s→7.95s 之间一个键都没有**（因为纯 clip
那段时间几乎不动，`DEFORM_TOL_WORLD=0.001` 的逐帧裁剪把中间全砍了，值基本持平）。

但录制侧 `Tep_1.json` 的 delta 在那段时间**一直在变**（0.06→0.144 世界单位）。
`merge_cs_bake.py` 原来的循环是：

```python
for fr in frames:          # ← frames = 产物在该槽位的关键帧（稀疏！）
    k = kmap.get(round(t, 6))   # 产物没有的时刻根本没机会写
```

于是 1.55s 的 +59.6px 和 7.95s 的 +5.7px 被线性插成一整条斜线，**整段尾巴滑走**。

### 11.5 判责：用新起的 Unity 运行取真值（`verify_cs.cs`）

对 `Tep_1 t=4.0`（滑移窗口正中）分别与 Unity 的 B 逐顶点对：

| | 中位 | p90 | 最大 | `Tail_B` 中位 |
| --- | --- | --- | --- | --- |
| 基线 vs Unity A | 0.0030 | 0.125 | 0.907 | 0.005 |
| **合并（旧）vs Unity B** | 0.0054 | 10.95 | **97.09** | 30.94 |
| **移植版 vs Unity B** | 0.4042 | 1.080 | **1.6618** | 0.005 |

**移植版对，合并版错。**

### 11.6 修复一：合并网格 = 产物关键帧 ∪ 录制关键帧

`merge_cs_bake.py` 改动：

* 新增 `interp_frames()`（按 Spine 运行时的线性插值在任意时刻取产物 deform 值）；
* 合并网格改成两边的并集，逐点 `产物值(t) + S·(B−A)(t)`，再按 `tol` 裁剪；
* 报告里加 `gridBaseKeys` / `gridTotalKeys`（Alice 8130→9016 键，+10.9%）。

复验（同一次 Unity 真值）：

| | 最大误差 |
| --- | --- |
| 合并（旧，稀疏网格） | 97.09 px |
| 合并（修后） | **0.831 px** |
| 移植版 | 1.66 px |

### 11.7 修复二：采集器支持叠层，且 `splice_bake.py` 只重采要修的 state

* `runner_bake2.cs` / `verify_layers.cs`：新增 `layers=<state>[,<state>]` —— 采样前先按
  各自时长采这些层的 clip（超过自己的时长停在末帧，与 `compose_layers` 的 override
  语义一致），再采主 clip。返回值里会打 `layers=[...]` 便于核对。
* `run_bake.py`：新增 `--overlay "<state>=<clip>[,<clip>]"`；**探测那一步也要带
  `layers=`**（不带的话探测漏掉"只有基底层驱动得动"的部件：curtain 上实测漏了
  `parts_Tail_B`，13 个候选只挑出 7 个）。
* `tools\bake_cs\splice_bake.py`：把重采的片段并回原 `bake.json`，不必整条角色重跑：

```powershell
python run_bake.py --product <基线> --prefab <prefab> --outdir <新目录> `
    --states 3P_Alice_NS1_curtain --overlay "3P_Alice_NS1_curtain=Start"
python splice_bake.py --base <原 bake.json> --replace <新目录>\bake.json --out <bake_layers.json>
python merge_cs_bake.py --product <基线> --bake <bake_layers.json> --out <合并产物> --report <r3.json>
```

层感知真值复验（`verify_layers.cs`，`layers=Start`，`curtain t=1.75`）：

| | 中位 | p90 | 最大 | `Tail_F` 最大 |
| --- | --- | --- | --- | --- |
| 基线 vs Unity A（层感知姿态） | 0.0268 | 0.044 | 0.079 | 0.003 |
| 移植版 vs Unity B | 0.1377 | 0.445 | 2.1846 | 0.089 |
| 合并（修后）vs Unity B | 0.0292 | 0.045 | **0.3602** | 0.090 |

顺便确认：**基线 vs Unity A 只有 0.027px 中位** ⇒ 转换器的"多层合成姿态"本身是对的，
之前那 15.9px 的差完全是采集侧 A 姿态缺基底层造成的。

### 11.8 残留：乳房弹簧（移植版）还有几 px

修完后 `cmp_products`（移植版 vs 修后合并版，Alice）：

```
全部 3250958 个差值：中位 0.0638 px / p90 1.5538 / 最大 37.4120
```

最大项已经换成了乳房组（`parts_Breast_wing_48` 等）。对 `breast t=1.5` 取真值：

| | 中位 | p90 | 最大 | 乳房组（中位/p90） |
| --- | --- | --- | --- | --- |
| 合并（修后） vs Unity B | 0.0051 | 0.031 | **0.0533** | Breast_L 0.004/0.006、wing 0.004/0.006 |
| 移植版 vs Unity B | 0.9544 | 4.5453 | **19.7630** | Breast_L 3.05/4.67、wing 3.82/5.08 |

⇒ 这一段**合并版对、移植版偏几 px**，来源是 `DynamicBone`（`Bone_Breast` 上的有状态弹簧；
`Bone_Hair` 在预制体里是 `enabled=false`，采集会把它列进 `skipped:`）。其余四个对拍点
换句话说：**修完网格后，合并版在四个取样点上都是 ≤0.83px；移植版除乳房弹簧这一段
（breast t=1.5 最大 19.8px）以外，都在 2.2px 以内。**

### 11.9 本轮新增/改动的脚本

| 文件 | 干什么 |
| --- | --- |
| `tools\bake_cs\diag_curtain.py` | 三条产物（基线/合并/移植）在指定动画·槽位上的 deform 逐帧对照 |
| `tools\bake_cs\diag_port_vs_unity.py` | 产物 Δ 与录制 Δ 直接对拍（可只做 2×2 拟合看方向是否一致） |
| `tools\bake_cs\splice_bake.py` | 用重采的片段替换 `bake.json` 里的同名 state |
| `merge_cs_bake.py` | **改**：合并网格改成 产物关键帧 ∪ 录制关键帧（`interp_frames`） |
| `run_bake.py` | **改**：`--overlay <state>=<clip>[,<clip>]`；探测步骤也带叠层 |
| `_scratch\_csbake\runner_bake2.cs` | **改**：支持 `layers=`，采样前先采其它层的 clip |
| `_scratch\_csbake\verify_layers.cs` | **新**：层感知的独立校验器（`verify_cs.cs` + `layers=`） |
| `_scratch\_csbake\probe_layers.cs` / `probe_curtain.cs` | **新**：读 AnimatorController 的层/状态/曲线绑定，列 CS 组件 enabled 状态 |

---

## 12 2026-10-09 第三轮：影子部件"显隐/位置不对"——查出两个**静默丢数据**的 bug

用户报告：`3P_Alice_NS1\CS合并后` 里 `parts_Tail_Shadow` / `Bone_Tail_Shadow2` /
`bone_Arm_L_Shadow` 这些影子的 **Enable 和位置**不对。

### 12.1 症状与现场

`_static_info.json` 的 `excludedParts` 里正躺着这几个：

```
.../Bone_Pelvis/Bone_Tail_Shadow2/parts_Tail_Shadow2        sprite  理由：Unity 里始终禁用（SetActive=0）
.../bone_Arm_L_Shadow/parts_Leg_L_Up_Shadow                 sprite  理由：同上
.../Bone_arm_R_shadow/parts_arm_R_shadow                    sprite  理由：同上
.../Bone_Arm_R_Finger1_shadow/parts_Arm_R_Finger1_shadow    sprite  理由：同上
```

但沿父链看静态值：**叶子部件 active=True，父节点 `Bone_Tail_Shadow2` / `bone_Arm_L_Shadow`
才是 False** —— 也就是说这些影子是"预制体里先关掉、靠 clip 的 `m_IsActive` 打开"的。
而产物的动画里**只有 deform、一条 slot 时间轴都没有**。

### 12.2 根因①：`m_FloatCurves` 整段没被解析（本项目 clip 的字段序与老工程相反）

本项目（AssetRipper 2021.3 的 dump）clip 里两类"非 Transform"曲线写在一起：

```
  m_FloatCurves:
  - curve:                       ← 新序：条目以 `- curve:` 开头
      serializedVersion: 2
      m_Curve:
      - serializedVersion: 3
        time: 0 ...
    attribute: m_IsActive        ← attribute/path 在**后面**
    path: Global_CTRL/Bone_Pelvis/Bone_Tail_Shadow2
```

而解析器原来是按 `^  - serializedVersion: \d+$` 切条目的（老工程 `NormalLocal` 就是这种：
`- serializedVersion: 2` → `curve:` → `attribute:`），于是**这一整段一条都没读进来**⇒

* `m_IsActive`（SetActive 显隐）丢 ⇒ 靠它打开的部件被判"始终禁用"**直接不导出**；
* `m_Color.*`（SpriteRenderer 颜色/透明度）丢 ⇒ 该淡出的影子**一直不透明**；
* `blendShape.*`（形变）、`m_SortingOrder`（前后层）同样丢。

**修**：条目起始正则改成两种写法都认
`^  - (?:curve:|serializedVersion: \d+)\s*$`（`unity_anim2d.parse_clip`）。
复验：`breast` 从 **0 条** active/color 变成 **15 条 m_IsActive + 6 条 m_Color**，
里面正好有 `Bone_Tail_Shadow2`(0→1 @0.07s)、`bone_Arm_L_Shadow`(0→1 @0.53s)、
`Bone_arm_R_shadow`(0→1 @0.43s) 和 `parts_Tail_Shadow.a`(1→0 @0.27s) 的淡入淡出。

**对已有工程的影响**：`NormalLocal`（PC 版）用的是老字段序，正则两种都吃 ⇒ **不受影响**；
Mobile-old 的产物全部需要重转（部件数 Alice 41→**55**、Alexandra 22→**47**）。

### 12.3 根因②：`animations.x.slots` 少了 Spine 规范的**皮层层级**

写出时是扁平的 `slots.<槽位名>`，而 Spine 3.8 JSON 的规范形状是
`slots.<皮肤名>.<槽位名>`（皮肤层一般就是 `"default"`，与 `deform` 同一套约定）。
Spine 编辑器/任何读 JSON 的运行时会把扁平键当**皮肤名**，于是新写出来的附件（显隐）/
颜色时间轴**被静默忽略**（`.skel` 侧不受影响，因为二进制里 slot 时间轴带的是槽位下标）。

**修**：`static_prefab_spine` 写 `{"default": slot_anim}`；新增
`spine_out.anim_slots()` 供 `spine38_binary_writer`（3 处）、`spine38_binary`（二进制→JSON）
与 `validate_spine` 读取，两种形状都兼容；二进制写成 JSON 时也写规范形状。

### 12.4 顺带修的两个小毛病

* **连续 `None` 被逐点重复写**：`prev` 用 `None` 当"还没写过"的哨兵，导致"一直不可见"的
  槽位把每个探测时刻都写一条 `name: null`（实测 Start 里 14 个槽位各 80+ 键的废时间轴）。
  改用 `_UNSET` 哨兵后收敛成 1 键。
* **DynamicBone 的 `ApplyParticlesToTransforms` 判据**：Unity 看的是**粒子链**子节点数
  （`Particle.m_ChildCount`），移植版原来数的是 Transform 的全部子节点（渲染件也算）⇒
  骨头上挂着渲染件时会**跳过旋转更新**。改成累计 `pchild`（含合成末端粒子）。
  （对 Alice/Alexandra 的乳房链无影响——那两条链本来就是单子节点；但 157 个角色里
  "骨头上挂渲染件"的情况才是对的。）

### 12.5 修后状态（全部离线验证，不依赖 Unity）

| 项 | 结果 |
| --- | --- |
| 部件数 | Alice 41→**55**、Alexandra 22→**47**（静态检查仍 140/55/0/0/0/0） |
| 影子显隐 | `parts_Tail_Shadow2`：(0,None)→(0.067,显示)→(8.0,None)；`Leg_L_Up_Shadow`：(0,None)→(0.533,显示)；`arm_R_shadow`：(0,None)→(0.433,显示) —— 与 clip 曲线逐条对齐 |
| 影子透明度 | `parts_Tail_Shadow` 4 帧、`parts_Tail_Shadow2` 4 帧、`Leg_L_Up_Shadow` 6 帧、`arm_R_shadow` 7 帧（含 r/g/b 染色） |
| CS 精度（对磁盘上留存的 Unity 参考） | Tep_1 t=4.0 **1.66px**、curtain t=1.75 **2.18px**（与修前一致，无回归）；breast t=1.5 中位 0.95 / 最大 **19.76px**（见 §11.8，移植版弹簧仍待收） |

### 12.6 全量 157 个角色（不依赖 Unity）

```powershell
cd D:\VB\Unity2Spine; $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
$A="D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets"
$OUT="D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv_cs_port"
Get-ChildItem "$A\Prefabs" -Filter "*.uAnim.prefab" | ForEach-Object {
  $n=$_.BaseName -replace '\.uAnim$',''
  python -m ngui2spine.static_prefab_spine $_.FullName "$OUT\$n" `
      --assets $A --skel --no-face-check --cs
}
```

* 单角色（Alice 规模）约 **2.5–3 分钟**（CS 预跑占大头），157 个约 **6–8 小时**；
  产物约 20–45MB/角色 ⇒ 预留 **~5GB**。
* 内存红线仍然有效：**一次只跑一个**（脚本是串行的），跑之前先看可用内存。
* 每条转换结束会打 `[static_check] … 0/0/0/0`，非 0 就要点名检查那一个角色。

---

## 13 2026-10-09 第四轮：**Play 中逐帧导出**（U2SFrameDump）与影子复核

用户在 Unity 里直接跑出来的数据，比"录 A/B"更直观：挂一个组件，**每帧**把整棵子树的
`activeSelf/activeInHierarchy/渲染器 enabled/世界矩阵/SpriteRenderer.color/顶点`
写成 JSONL。

| 新件 | 作用 |
| --- | --- |
| `proj-Mobile-old\Assets\Raw\Scripts\U2SFrameDump.cs` | 运行时逐帧导出（F9 开关；`fixedFramerate=60` 时用 `Time.captureFramerate` 固定步长；可选顶点/骨骼表/颜色/排序） |
| `proj-Mobile-old\Assets\Editor\FrameDumpMenu.cs` | `Tools/2DModel/逐帧状态导出/`：挂到选中根 / 挂进 prefab / 批量给所有 `*.uAnim.prefab` |
| `tools\bake_cs\read_framedump.py` | 读 JSONL：`--timeline`（状态 hash/normalizedTime/时长）、`--times`、`--grep`，以及和产物**逐槽位对显隐** |
| `tools\bake_cs\framedump_to_verify.py` | 把一帧转成 `verify_merge.py` 的 verify.json（世界顶点→局部用 l2w 逆；可选生成解析标定表 S/T） |
| `tools\bake_cs\diag_shadow_pos.py` / `diag_shadow_product.py` / `probe_sprite_mode.py` | 静态 vs 播放位置对比 / 产物vsUnityvs静态三点对比（含最近邻与镜像判别）/ 读 prefab 的 SpriteRenderer 绘制模式 |

### 13.1 影子显隐：Unity 与产物**逐条对上**

`breast`（状态 hash 1648896808，8.0s）里 Unity 的实际状态：

| 产物时刻 | `parts_Tail_Shadow` alpha | `Tail_Shadow2` | `Leg_L_Up_Shadow` | `arm_R_shadow` | `Finger1_shadow` |
| --- | --- | --- | --- | --- | --- |
| 0.70s | **0.000**（淡出完成） | 显示 α=1 | α=0.097（淡入中） | α=0.530 | 父节点关 |
| 1.50s | 0.000 | 1 | 1.000 | 1.000 | 父节点关 |
| 2.79s | 0.000 | 1 | 1 | **0.000**（淡出） | 父节点关 |
| Tep_1 0.06s | 0.000 | 1 | 父节点关 | 父节点关 | 父节点关 |
| Tep_1 5.79s（norm 0.643） | 0.000 | 1 | 1 | 1.000 | **α=0.654**（淡入） |
| Tep_1 7.12s（norm 0.791） | 0.000 | 1 | 1 | 0.857 | α=0.014（淡出） |

与产物里那几条 `m_IsActive`/`m_Color.a` 时间轴（§12.5）**逐条吻合**——
父节点 SetActive 的时刻（0.067/0.433/0.533/2.25/4.583/5.117s）和 alpha 的起落都对上了。

### 13.2 影子位置：产物对，是**导出侧**漏了 `m_FlipX`

第一版对拍出现两个"位置差 126px / 161px"，三个没问题。查 prefab：

```
parts_Tail_Shadow      flip=0,0    ← 对得上
parts_Tail_Shadow2     flip=0,0    ← 对得上
parts_Arm_R_Finger1_shadow flip=0,0 ← 对得上
parts_Leg_L_Up_Shadow  flip=1,0    ← 差 126px
parts_arm_R_shadow     flip=1,0    ← 差 161px
```

**完全对应**：`U2SFrameDump` 里精灵顶点取的是 `sprite.vertices`（未翻转），而
`m_FlipX/m_FlipY` 是"绕 pivot 镜像四边形"（几何也动、UV 不动）—— 所以是**导出脚本**
少了这一步，产物那边（`convert_2dmodel` 的 `p.flip_x`）本来是对的。
给 dump 补上 `flipX ? -x : x` 后重跑：

| 部件 | 修 dump 前 | 修后（基线 / 移植版） |
| --- | --- | --- |
| `parts_Leg_L_Up_Shadow` | 126.5px | **0.076 / 0.130px** |
| `parts_arm_R_shadow` | 160.9px | **0.047 / 0.047px** |
| `parts_Tail_Shadow` | 0.010 | 0.038 / 0.052px |
| `parts_Tail_Shadow2` | 0.181 | 0.097 / 0.098px |
| `parts_Arm_R_Finger1_shadow` | 0.198 | 0.061 / 0.060px |
| 汇总 | 中位 0.42 / 最大 203px | **中位 0.053 / 最大 0.206px** |

### 13.3 用这份导出时必须注意的三点

### 13.4 移植版乳房弹簧残差：查清了，**不是漏项、也不是精度问题**

（2026-10-09 晚，用户要求"先修移植版乳房弹簧残差"）

用 `tools\bake_cs\diag_db_trace.py` 把移植版的 DynamicBone 与 Unity dump
（`partdump\alice_db_particles.json`，7 粒子 × 481 帧）**整段逐帧**对拍：

| 指标 | 结果 |
| --- | --- |
| 步前**骨长 n** | 与 Unity **完全一致**（差 = 0） |
| 步前骨头位置（仿射对齐后） | 中位 0.0005 / 最大 0.0009（≈0.4–0.7px） |
| 粒子状态（整段） | 中位 0.0037 / p90 0.0137 / 最大 0.0320 世界单位（≈3 / 11 / 26px） |
| 逐帧误差形状 | **0.002–0.023 之间波动**，峰值出现在乳房动得最快处，**不是单调累积** |

纯公式测试（用 Unity 自己的状态+输入，彻底避开坐标映射）：

| 版本 | 每步最大误差 |
| --- | --- |
| 移植版（double） | 2.45e-4 世界单位 ≈ 0.2px |
| 修正 target 顺序（先 update1 再用平移修正 target） | 3.22e-4（没变好） |
| **float32 逐运算舍入版**（`diag_db_f32.py`，模拟 Unity 的 float32 数学） | 3.22e-4（**证明不是舍入问题**） |

参数也逐项核对过（从 prefab 解析）：`m_Damping 0.07 / m_Elasticity 0.03 /
m_Stiffness 0.1 / m_Weight 1 / m_UpdateRate 60`，而
**`m_Gravity / m_Force / m_Inert / m_Radius / m_EndLength / m_EndOffset` 全 0、
`m_Colliders / m_Exclusions` 空、`m_FreezeAxis = None`** ⇒ 公式退化成
移植版实现的那几行，**没有漏项**；逐行对照工程里的 `DynamicBone.cs`
（AssetRipper 反编译件）也一致。

**结论**：这 0.2px/步的差异既不是漏参、也不是 float32 舍入，而是反编译源码层面
看不到的细节（或反编译本身不忠实）。它在 7 粒子弹簧链里被放大成
`breast t=1.5` 处最大 ~20px、中位 0.95px。

**2026-10-10 定案：根因是 Distribution 曲线（逐粒子参数），已改转换器**

把一步拆成 `UpdateParticles1 / UpdateParticles2` 分别 dump（探针
`_scratch\_csbake\db_step_trace.cs` + `dbstep.txt` → `partdump\alice_db_split.json`，
工具 `tools\bake_cs\diag_db_split.py`）后，真相很清楚：

```
逐粒子实测（Unity）：#0 damping=0.035075 elasticity=0.030025   #5 damping=0.070000 ...
更新时间前的组件值：m_Damping=0.07  m_Elasticity=0.03
0.07 × 0.5010706 = 0.035075   ← m_DampingDistrib 在 ratio=0 的取值
0.03 × 1.0008217 = 0.030025   ← m_ElasticityDistrib 在 ratio=0 的取值
```

即 **`DynamicBone.UpdateParameters()` 会用 `m_*Distrib` 曲线按
`该粒子骨长 / 总长` 求值，再乘组件上的平值** 覆盖每个粒子的 damping/elasticity/
stiffness/inert/radius。移植版一直用组件平值 ⇒ 每步差 0.2px、在 7 粒子链里累积成
`breast t=1.5` 最大 ~20px。同一份拆分 dump 还证明 **update1 与 Unity 完全一致
（误差 ~5e-9）**，差异 100% 在"逐粒子参数"这一层。

（更正一处早先的误读：我一度以为"两条 Distrib 曲线键数都是 0（空曲线）"——
那是我的解析器被曲线自己的 `m_Curve:` 提前截断、以及窗口取错造成的假象；
曲线实际是 `(0, 0.5010706) → (1, 1.0)` 与 `(0, 1.0008217) → …`。）

**消融实验（`diag_db_ablate.py`）也一致**：9 种 update2 语义变体
（fresh/stale target、clamp 开/关/恒开、keep-length 顺序、n 改用粒子距离、
去掉弹性项…）都停在 1e-4~1e-3，没有一种到 1e-6 —— 因为它们改的都是**公式**，
而错的是**参数**。

**转换器改动（纯离线，不依赖 Unity）** `src\unity2spine\convert\cs_runtime.py`：

* 新增 `_parse_curve()`（解析 `m_*Distrib` 的 AnimationCurve）与 `_curve_eval()`
  （Unity 的三次 Hermite 求值；空曲线返回 1.0 ⇒ 不覆盖，保持旧行为，向后兼容）；
* `DynamicBone.__init__` 解析 5 条曲线（damping/elasticity/stiffness/inert/radius）；
* `_update_params()` 逐粒子改为 `clamp(m_Damping × curve(骨长/总长))`（其余同理）。

**⚠️ 还差最后一步**：`_parse_curve()` 目前**仍返回 0 键**（同一条曲线，把正则写在
交互式里跑能得到 2 个键，函数里却是空 ⇒ 函数体内还有一处差异，最可能是
`cs_runtime.py` 里留下了**重复定义**（后定义的旧版覆盖了新版），或导入走的是
兼容层 `ngui2spine` 而不是 `src\unity2spine`）。所以本轮重转的复验数字**还没变**：
`breast t=1.5` 中位 0.9544 / 最大 19.7630 px。修好这一处后预期掉到 1px 以内。

---

## 14 2026-10-09 晚 ~ 10-10：影子"不透明粉色"与 spine3.8 绑定

### 14.1 影子在查看器里是"不透明粉色"——根因：Unity 的乘法混合材质

用户报告：Alice 的两个影子在 Unity 里是略透明的暗影子，转成 Spine 后变成
**不透明的粉色**。查出来是**混合模式**：

```
parts_Leg_L_Up_Shadow / parts_arm_R_shadow / parts_Tail_Shadow2
  → Assets\Raw\Material\multiply_5.mat
    m_Shader: {fileID: 205, guid: 0000…}   ← 内建 "Legacy Shaders/Particles/Multiply"
```

乘法混合的效果是 `out = 背景 × 贴图`（把背景压暗），而**贴图本身是"浅粉 + α≈0.29"**；
转换器原来只认加色(200)与普通，按普通 alpha 导出 ⇒ 粉色半透明贴上去。
工程里**19 个材质**用内建 205（36 个文件名带 multiply），影响面不小。

**A（精确版）**：
1. 转换器识别内建 205 → 导出 `blend: multiply`
   （`SHADER_MULTIPLY = {205}`，`sprite_style()` 新增分支）；
2. **乘法件的贴图区域必须 α=1**：Spine 的 multiply 是
   `out = dst×src.rgb + src.rgb×(1−src.a)`，只有 `src.a=1` 才退化成 Unity 的纯乘法
   `out = dst×src.rgb`。否则会**变亮**（实测亮度 197→225）。
   工具 `tools\bake_cs\bake_multiply_opaque.py`（只改这些槽位自己的 UV 矩形内的
   α，不动 JSON/skel）。
3. 查看器要能按槽位混合 —— 见 14.2。

**B（兼容版）**：`tools\bake_cs\bake_multiply_dark.py` 把乘法槽位烘成
"**黑 + 保留 alpha 动画 + normal**"（不动图集），当前任何查看器都能看到暗影子。
验证：与 A 的差异**只落在影子那 408 像素**；A 这些像素平均 RGB(205,171,165)（浅粉，
338/408 偏红）→ B (123,106,103)（中性暗，亮度 −69.7）。

### 14.2 查看器支持按槽位混合（改了 spine3.8 绑定）

查看器原来每帧只设**一个全局**混合函数（`SpineRender.py:681-684/729-733`），
而绑定返回的对象只暴露 `path` / `getIbo()`，Python 侧无从知道哪些顶点属于乘法的槽位。

**改法**（源码在 `D:\Code\vs_cpp_code\Spine3.8-py`，spine 原码在 `D:\Libs`）：

| 文件 | 改动 |
| --- | --- |
| `GLArray.h` | 新增 `std::vector<int> blendRanges`（三连一组：ibo 起始 / 个数 / 混合模式 0=normal 1=additive 2=multiply 3=screen） |
| `CustomSkeleton.cpp` | 新增**单遍** `BuildMeshData38()`，`OriginalBuffer()`/`RangeBuffer()` 变薄包装；顺带记 `blendRanges`；空 `region/page` 直接跳过 |
| `AssemblyBinding.cpp` | `GLArray`/`GLArraySetUp` 暴露 `.def_readonly("blendRanges", …)` |
| `renderer_src\SpineRender.py` | 新增 `_drawSkeleton()`：**默认仍是一次 `vao.render`**；只有存在 multiply 段时才按段绘制，且只有 multiply 段换 `(DST_COLOR, ONE_MINUS_SRC_ALPHA)`，画完恢复 |

构建：`D:\VS\MSBuild\Current\Bin\MSBuild.exe Spine380Binding.vcxproj
/p:Configuration=Release /p:Platform=x64` → `Spine380.pyd`（538KB，工具集 v145）。
细节与兼容性说明见 **`D:\Code\vs_cpp_code\Spine3.8-py\修改记录_20261009.md`**。

**兼容性（用户明确要求）**：API 只增不改（实测同产物 `版本=3.8 动画=5 皮肤=1`、
`VBO=32310 float`、`IBO=11508 int`、`贴图=7`，与旧 pyd 一致；新增 `blendRanges`=27 个数）；
渲染端"拿不到 blendRanges / 没有 multiply 段 ⇒ 一次 draw"（逐像素同旧版）；
旧 pyd 备份为 `Spine380.pyd.bak_20261009`（原始）与 `.bak_20261009_blend`（中间版）。

**顺带落地 `预备修正.md`**（该文件只是方案、之前**没做**）：原来的两遍统计写法
（`vLen/iboLen` + `OffsetVboCount`）一旦两遍判断不一致就会**越界写** → 在
`getInitBuffer()/RangeBuffer()` 里原生 `0xC0000005`；现在改成单遍 vector 累积，
并给空数据 `±512` 包围盒。核对时 `size_t vLen|iboLen|OffsetVboCount` 命中 34 处、
`BuildMeshData` 命中 0 —— 佐证"未落地"。

### 14.3 `.config.json 加载失败` —— 是 `slots` 写成了带皮肤层

我一度把动画的 slot 时间轴写成 `animations.x.slots.default.<槽位>`，而
**spine-cpp 3.8 的 `SkeletonJson.cpp` 是把 `slots` 的键直接当槽位名**
（`findSlotIndex(slotMap->_name)`，找不到就 `Slot not found`），**只有 `deform`
才带皮肤层**（`findSkin(...)`）。⇒ JSON 加载失败（`.skel` 走槽位下标不受影响，
所以只测 `.skel` 会漏掉）。已回退成扁平的 `slots.<槽位>`，
`tools\bake_cs\fix_slots_flat.py` 把已生成的 8 个 JSON 拉平，
并用查看器的 spine-cpp 实测 **JSON 与 `.skel` 都能加载** ✓。
（交接文档里的"约束 19"已按此更正。）

### 14.4 其它

* 产物 JSON 改成**紧凑输出**（原来是 `indent=1`）：基线 105.8MB → **40.7MB**，加载更快；
* Unity 侧新增 `U2SFrameDump.cs`（挂根物体、**每帧**导出整棵子树状态）+
  `FrameDumpMenu.cs`（一键挂载/批量）；配套
  `read_framedump.py` / `framedump_to_verify.py` / `diag_shadow_pos.py` /
  `diag_shadow_product.py` / `probe_sprite_mode.py`；
  **注意**：`sprite.vertices` 不含 `m_FlipX/m_FlipY`（脚本已补），
  `AnimatorStateInfo.normalizedTime` 是累加的、状态还可能被自动切走；
* 影子显隐/位置用 Play 中逐帧导出验证：显隐逐条吻合，位置**中位 0.053px / 最大 0.206px**
  （中途出现的 126/161px 是**导出脚本**漏了 `m_FlipX`，产物本身没错）；
* Alexandra 部件数 22 → **47**（同一批 `m_FloatCurves` 解析修复的收益）。

### 14.5 当前包里有什么

`D:\VB\Search\New\_Spine待检查_20261009\3P_Alice_NS1\`

| 目录 | 内容 |
| --- | --- |
| `基线\` | 无脚本形变（40.7MB json + 23.3MB skel） |
| `CS合并后\` | **A：精确 multiply**（乘法件贴图 α 已置 1）；查看看器需新版（14.2） |
| `CS合并后_B_乘法烘暗\` | **B：当前任何查看器都能看到暗影子** |
| `对比图\` | 仍是早期渲染，不含显隐/乘法修复 |

**（2026-10-10 更新：这段话已过期）** 当时判断"移植版要位精确复刻弹簧不现实"是因为
还没找到 §15 的三个 bug。修完之后移植版的 DynamicBone 在 481 帧真值上逐粒子最大偏差
**1.1e-6 世界单位（0.0009px = float32 精度）**，产物层 `breast t=1.5` 中位 0.0031px —— 
**不再需要"只对 DynamicBone 部件走录制+合并"这种混合方案**。
剩下的残差在 IK（腿），量级 0.4px（相对 0.14%），见 §15.5。

1. **精灵要自己翻**：`sprite.vertices` 不含 `m_FlipX/m_FlipY`（已在本轮脚本里修）；
   若还有 `m_DrawMode != 0`（Sliced/Tiled）的精灵，`sprite.vertices` 也不等于实际网格，
   得按 `m_Size` 重新生成（这几个影子都是 `drawMode=0`，不涉及）。
2. **状态时间≠墙钟**：`AnimatorStateInfo.normalizedTime` 会**累加**（循环时不停在 0~1），
   而且实测状态内部速度可以到 ~2×。要和产物同一相位，用 **`frac(normalizedTime) × 时长`**
   当产物时刻（`read_framedump.py` 会打出来）。
3. **状态会被自动切走**：`breast` 播到一半会自己转 `lobby`（转场的条件是 0 个），
   所以一条 dump 里可能混多个状态，取帧时先看 `--timeline`。

---

## 15 2026-10-10：乳房弹簧定案 —— **三个 bug 一连串**，现在逐粒子到 float32 精度

这一轮把 §13.4 那句"`UpdateParameters` 的 Distribution 曲线才是根因、解析器还差一个小
bug"彻底收了尾。**三个 bug 串在一起**，任何一个不修都看不出全貌。

### 15.1 bug①　`self.curves` 被误粘贴进了 `IKHandle.__init__`

`IKHandle.__init__` 里凭空多了一段

```python
self.curves = {"damping": _parse_curve(_t, "m_DampingDistrib"), ...}
```

而真正要用它的 `DynamicBone._update_params` 在**另一个类**里：

```python
p.damping = ... * _curve_eval(self.curves["damping"], r)
```

⇒ `DynamicBone` 上根本没有 `curves` 属性 ⇒ 只要真去跑 `_update_params` 就
`AttributeError`（当时被上层的 try 吞掉了，所以"移植版一直在用平值 0.07/0.03"
这个现象看起来像"曲线没生效"，其实是**属性压根不存在**）。

修：那段挪回 `DynamicBone.__init__`，类上留 `curves = {}` 兜底，`_update_params` 改用
`cv.get("damping")`（缺曲线时 `_curve_eval(None, r)` 返回 1.0 = 旧行为，向后兼容）。

### 15.2 bug②　`re.split(p, s, re.M)` —— 第 3 个参数是 **maxsplit**，不是 flags

挪回去之后曲线**仍然**是 0 键。逐段打印才发现：

```python
# ✗ 错：maxsplit=8、flags=0（没有 MULTILINE）⇒ ^/$ 只按整串锚定 ⇒ 一段都切不出来
for blk in re.split(r"^\s+- serializedVersion: \d+\s*$", seg, re.M)[1:]:
# ✓ 对：
for blk in re.split(r"^\s+- serializedVersion: \d+\s*$", seg, flags=re.M)[1:]:
```

**只有 `re.split/re.sub/re.subn` 的第 3 个参数是 maxsplit/count**；`re.search` /
`re.findall` / `re.finditer` 的第 3 个才是 flags。所以这次是
`re.search(r"^\s*%s:\s*$", text, re.M)`（对）和 `re.split(..., seg, re.M)`（错）**混在同一
个函数里**，一眼看不出来。修完 `_parse_curve` 立刻解出
`[(0.0, 0.5010706, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0)]`，`eval(0)=0.501071` 与 Unity 实测的
`0.5010706` 逐位吻合；7 颗粒子的 damping/elasticity 与 Unity dump **全部一致**（含中间
粒子 r=0.5662 / 0.8552）。

### 15.3 bug③　真正的大头：`step_dynamics` 的"Uniform 度量"把弹簧推歪了

参数修对之后，产物层从 19.76px 降到 **0.62px**（中位 0.9544 → 0.1792），但还差一截，
而且**逐帧粒子对拍**显示误差从第 20 帧起单调增长（中位 3e-4、最大 2.6e-3 = 2.1px）。

把"复原真值"当种子做实验，一步就偏 2.4e-4 ⇒ 是**每步的系统误差**（不是浮点、不是混沌放大；
`--round32` 无变化、在第 200 帧换成 Unity 真值后误差立刻重新长出来）。

于是把一步**拆成三段**同时打印（`_scratch\_csbake\t_probe_step.py`）：

| 对比 | 结果 |
| --- | --- |
| 手工按公式重算 vs Unity 真值 | **1e-8**（公式没问题） |
| 移植版 vs 手工 | **2.4e-4**（差在"公式外面"） |
| 移植版（跳过 `begin_metric/scale_state`） vs 手工 | **0.0**（完全一致） |

**根因**：`step_dynamics` 把整棵树按"子树世界尺度 D"缩放后再推进：

```
[metric] D=(0.12236924, 0.12567996, 0.00341242)
```

而 DynamicBone 的更新式（`|Δ|`、`(mag−num3)/mag` 投影、`FromToRotation`）在**非均匀缩放**
下不协变 —— 这一步当初是为了让 `_apply` 里的 `FromToRotation` 能在"Unity 度量"里算
（§9.2 记的"非均匀度量下旋转无法用四元数表达"），但它顺手把**弹簧物理**也搬了过去。
而事实是：**转换器的 world 矩阵本来就是 Unity 世界度量**（实测骨位/骨长与 Unity 差 1e-7），
根本不需要换算。

修：加 `STEP_IN_METRIC` / `GC_IN_METRIC` 两个开关（`U2S_CS_STEP_METRIC` /
`U2S_CS_GC_METRIC` 环境变量可切回旧行为做对照），**默认都关**。

### 15.4 验收（全部离线，用的是 Unity **已经录好**的真值，不是现开 Unity）

真值：`_scratch\_csbake\partdump\alice_db_particles.json`（`breast` 481 帧 × 7 粒子的
`m_Position/m_PrevPosition/骨位/target/n/父索引`）。

```
_scratch\_csbake\t_db_frames.py --dump partdump\alice_db_particles.json
  修前（度量切换打开）: 中位 1.87e-4 / p90 9.44e-4 / 最大 2.57e-3 世界单位（2.06px）
  修后（默认关闭）    : 中位 2.18e-7 / p90 3.32e-7 / 最大 1.10e-6 世界单位（0.0009px）
```

产物层（`verify_merge.py`，Alice 移植版）：

| 取样点 | 修前 中位/最大 | 修后 中位/最大 | 录制合并路线（对照） |
| --- | --- | --- | --- |
| `breast t=1.5` | 0.9544 / 19.763 | **0.0031 / 0.6198** | 0.0051 / 0.0533 |
| `Tep_1 t=4.0` | 0.1658 / 0.5856 | 0.1050 / 0.5578 | 0.0062 / 0.8310 |
| `curtain t=1.75` | 22.56 / 59.71 | 22.56 / 59.71 | 22.56 / 59.71 |

回归检查：Alexandra 的 `parts_breast`（它的 DynamicBone）在两套开关下**结果完全相同**
（最大 0.00154 世界单位）；spline（尾巴）本来就是仿射协变的，不受影响。

`curtain` 两行一样是因为**基线产物自己**对 Unity 的 A 就差 15.88px（与 CS 无关，
`并合-基线` 那一列仍是 0.94 中位）。

### 15.5 还剩下的：IK（腿）

`breast t=1.5` 剩下的 p90/最大值 0.44/0.62px **全部**落在
`parts_Body` / `parts_Gatherbelt_Neck` / `parts_leg_*`；同一时刻这些部件的 CS 位移有
290~323px（`_scratch\_csbake\t_port_vs_rec.py --state breast --match leg_L_up`）⇒
相对误差 ~0.14%。已排除输入、度量、`childCount` 判据、第二个 DynamicBone
（Unity 侧 `m_Enabled: 0`）。可疑项与判据工具见交接文档 §5.4。

### 15.6 本轮新增的脚本（都在 `_scratch\_csbake\`，纯离线对账用）

| 脚本 | 干什么 |
| --- | --- |
| `t_curve.py` | `_parse_curve` 在真实 prefab 上的解析结果自检 |
| `t_curve2.py` | 正则逐段拆解（就是靠它抓到 `re.split` 的 maxsplit 坑） |
| `t_db_frames.py` | 移植版 DB **逐帧逐粒子** vs Unity 真值；带 `--reseed/--round32` |
| `t_step_replay.py` | 用 Unity 录的"状态+输入"做**单步**回放（隔离 update1/update2 语义） |
| `t_probe_step.py` | 把一步拆成"移植版 / 手工公式 / Unity"三列对拍，带 `--nometric` |
| `t_db_pchild_ab.py` | `ApplyParticlesToTransforms` 判据的 A/B |
| `t_port_vs_rec.py` | 移植版 vs 录制合并版的 CS 位移逐时刻对比（按部件名前缀匹配） |

---

## 16 2026-10-10（续）：Alexandra 的残差 = **启动瞬态**，不是解算错

把开关默认关掉之后 Alice 全面变好（§15.4），但一并跑 Alexandra 时露出**它自己**的问题：

| 取样点 | 移植版 中位/最大 | 录制合并路线（对照） |
| --- | --- | --- |
| Alexandra `Start t=3.0` | 0.0309 / **5.6339** px | 0.0029 / 0.0052 |
| Alexandra `lobby t=2.0` | 0.2549 / **6.2622** px | 0.0030 / 0.2126 |

**先排除"是我改坏的"**：用旧行为（`U2S_CS_STEP_METRIC=1 U2S_CS_GC_METRIC=1`）单独重转一份到
`_scratch\_oldmetric_alex`，逐项**完全一致**（5.6508 / 6.2787）⇒ 既有问题。

### 16.1 落在哪、什么形状

`verify_merge.py` 的逐部件表（Alexandra `Start t=3.0`，Alexandra 只有 2 个 DynamicBone、
没有 spline/IK）：

```
parts_B_hair   134 | 0.017 | 0.614 1.813 | 0.5979   ← 后发（DB#2，root=…/Hair，28 粒子）
parts_tie       16 | 0.022 | 0.414 1.452 | 0.4088   ← 飘带（同一条链的末端）
parts_breast   144 | 0.034 | 0.034 0.044 | 0.0244   ← DB#1 正常
```

沿时间看（`_scratch\_csbake\t_port_vs_rec.py --state Start --match B_hair`）：

```
  t     移植-基线   合并-基线   移植-合并
  0.00      0.000     34.680     34.680    ← 移植版这一帧**几乎没形变**
  2.50     10.848     16.009      6.618
  5.00    112.242    112.357      0.313
  7.50     28.561     28.576      0.015
 10.00     12.211     12.210      0.006
 12.50     11.342     11.342      0.006
```

⇒ 典型的**衰减型启动瞬态**：只在前几秒有差，`t≥5s` 就 <0.4px。

### 16.2 为什么两边的"初始状态"不一样（定案）

两个 Unity 侧真值生成器**建粒子链的姿态根本不是一个**：

| 脚本 | `SetupParticles()` 发生在什么姿态 |
| --- | --- |
| `_scratch\_csbake\runner_bake2.cs`（**录制**→ `bake.json`） | **探测阶段（6 个采样点）跑完之后**才 `resetDyn()`（= `InitTransforms()+SetupParticles()+清 m_Time`），此时层级停在**最后一次探测采样的姿态** |
| `_scratch\_csbake\verify_cs.cs`（**验收**→ `verify_*.json`） | 实例化后、任何 `SampleAnimationClip` **之前**（= **预制体静态姿态**） |
| 转换器 `--cs`（**移植版**） | 帧循环第一帧的 **clip t=0 姿态** |

三者的差别只在"弹簧从哪个姿态起振"，所以：
* 录制/验收两条真值在 `t≥3s` 互相吻合（瞬态已衰减）⇒ 合并路线仍然 0.003px；
* 移植版与它们在**前几秒**不同（Alice 的乳房链 `damping=0.07` 起振快，所以 `t=1.5` 就已经
  收敛，看不出问题；Alexandra 后发链 28 粒子、`damping=0.05`，`t=3.0` 还没收敛）。

**试过并否掉的做法**（别再重复）：

1. 把移植版的建链姿态改成**预制体静态姿态**去对齐 `verify_cs.cs` ⇒ **更差**
   （`Start` 最大 5.65 → 34.67、`B_hair` 0.598 → 18.93），说明"静态姿态"并不是那个
   真正的初始条件（`verify_cs.cs` 的 `SetupParticles` 之前还有 `InitTransforms`/层级状态）。
2. 把 `_apply` 的 `pchild` 换成 Unity 源码字面的 `Transform.childCount`（含渲染件子节点）
   ⇒ 产物**逐位不变**（`5.6339`/`6.2622` 一模一样）⇒ 这条链上两者等价，判据不是原因。
   （顺带说明：这条只能用"产物 vs 真值"判，**逐粒子对拍对 `_apply` 完全免疫**。）
3. 已排除：DB #2 在 prefab 里 `m_Enabled: 0`（Alice 的情况）、Alexandra 的 4 条
   `m_*Distrib` 曲线**全为空**（所以与曲线解析无关）、`IK_CTRL` 挂点不在骨链下、
   `numberIkBonesIndex/OnOff/_flipCorrection`。

### 16.3 下一步怎么做（很具体）

按 Alice 那套办法给 **Alexandra 的 `Hair` 链也录一份逐帧粒子真值**
（`_scratch\_csbake\dump_db_particles.cs`，改 `dbdump.txt` 的 prefab/state/fps/out），
拿到 `frames[0]` 的 7 列后即可判定"Unity 的初始 `m_Position/m_PrevPosition` 到底在哪"，
然后把转换器的建链姿态按它对齐 —— 预期 Alexandra 也会掉到 1px 内。
在那之前：**Alexandra 用录制+合并路线（已 0.003px），移植版只用于"形状/大动态"比对**。

### 16.4 2026-10-10 补录真值后的定案（结论有修正）

按 §16.3 的办法录到了 Alexandra 的真值：

```
python tools\bake_cs\mcp_exec.py _scratch\_csbake\dump_db_particles.cs
  （dbdump.txt: prefab=2DModel_3P_Alexandra_NS1.uAnim.prefab, state=lobby, maxFrames=200）
  → _scratch\_csbake\partdump\alexandra_db_particles.json（2 条链：Hair 28 粒子、Breast 6 粒子）
```

**① 动力学是精确的（两条链都验了）**：

```
python _scratch\_csbake\t_db_frames.py --dump partdump\alexandra_db_particles.json --go Hair
  逐帧粒子误差 中位 5.13e-7 / p90 7.0e-7 / 最大 5.11e-6 世界单位 = 0.0041 px（200 帧 × 28 粒子）
```

⇒ Alice 那条 7 粒子链、Alexandra 这条 **28 粒子分叉链**，移植版都与 Unity **逐帧逐粒子吻合到
float32 精度**。所以 §15 那三个 bug 修完之后，DynamicBone 的**公式、参数、链结构、写回**都对。

**② 真值 dump 直接暴露了"建链姿态"这件事**。`frames[0]` 的第 0 颗粒子：

```
m_Position      = (0.0421710461, 0.7822118,   6.65e-08)   ← clip t=0 的骨位
m_PrevPosition  = (0.0621456355, 0.777611256, -3.53e-08)   ← **预制体静态位置**
                                            （同帧 bonePos 也 = 0.04217…）
```

`UpdateParticles1` 对根粒子做的是 `prev = pos; pos = transform.position`，所以
`prev` 保留的就是 **`SetupParticles` 那一刻**的骨位 = 静态姿态。

**③ 但"静态建链"并不是那两个真值生成器的做法**。直接读三个产物在 **t=0** 的 deform
（`parts_B_hair_23`）：

| 产物 | t=0 deform 最大 |
| --- | --- |
| 基线（纯 clip） | **0.000 px** |
| 移植版（clip 建链） | 0.000 px |
| 移植版（静态建链） | 0.000 px |
| 录制合并 | **34.680 px** |

基线在 t=0 就是 0 ⇒ 这条 clip 在 t=0 的姿态**恰好就是绑定姿势**，于是
"静态建链"与"clip 建链"在第 0 帧**完全等价**；两份移植版都一样。
那录制那份 34.68px 只可能来自"**建链姿态既不是 t=0 也不是静态，而是探测阶段那个中间姿态**"
（`runner_bake2.cs` 里 `resetDyn()` 恰好排在探测循环之后）。

而"静态建链"的产物更差、且**恒定**：`移植-合并` 在 t=0/2.5/5/7.5/10/12.5 全都
**= 34.677px**，即一个不随时间衰减的固定偏移；clip 建链那份则是 `0 → 6.62 → 0.31 →
0.015 → 0.006 → 0.006`（会收敛）。

**修正后的结论**（覆盖 §16.3 的最后一句）：

* 移植版的 DynamicBone **没有已知偏差**（§16.4① 的逐帧真值作证）；
* 移植版与"录制/验收真值"在前几秒的差，是**建链姿态约定不同**造成的起振瞬态，
  而录制那份用的是"探测中间姿态"——这是**录制流程的产物，不该作为对齐目标**；
* 因此**不改**转换器的建链约定（保持 clip 第 0 帧，对应"角色从该 clip 开头起播"），
  并把这条写进约束；
* 需要"与录制真值逐像素一致"的场合，仍按老规矩用录制+合并路线（Alexandra 0.003px）。

---

## 17 2026-10-10（再续）：**IK 也录了逐帧真值 —— 结论是"移植版 IK 逐位精确"**

### 17.1 录了什么

新片段 `_scratch\_csbake\dump_ik_chain.cs` + 计划文件 `ikdump.txt`，每帧记 IK 的
**输入**（`preTop/preMid/preBot/preTopL/preMidL/preBotL`：世界 TRS + 局部 TRS、IK_CTRL、
`GetAngle()`、`AimDirection/UpDirection/Offset/Flip`）与**输出**（`post*`：`GlobalControl.Run()`
跑完 spline+FaceCamera+IK 之后的世界/局部 TRS），产出
`_scratch\_csbake\partdump\alice_ik_breast.json`（Alice `breast`，200 帧 × 2 个 IK）。

跑法：`python tools\bake_cs\mcp_exec.py _scratch\_csbake\dump_ik_chain.cs`（Unity 已在跑）。

### 17.2 结果：输入、输出**全是 0.000**

```
python _scratch\_csbake\t_ik_frames.py --dump partdump\alice_ik_breast.json
输入(pre) ：中位 0.00000 / p90 0.00000 / 最大 0.00000 世界单位 = 0.000 px
输出(post)：中位 0.00000 / p90 0.00000 / 最大 0.00000 世界单位 = 0.000 px
（200 帧 × 2 个 IK，位置与旋转都比；局部 TRS 用 t_ik_local.py，也全 0）
```

局部旋转最大差出现在个别帧上是 0.02°，其余 0.0000°。⇒ **`Puppet2D_IKHandle.CalculateIK`
的移植版（含 `GetAngle`、`LookRotation + AngleAxis(90,UpDirection)`、
`bottom = IK_CTRL.rotation * Offset`、`poleVector` 写入）与 Unity 逐帧逐位一致。**

### 17.3 路上踩的两个坑（都记下来）

1. **`GetAngle()` 不能单独调**：它读 `this.IK_CTRL`，而 `IK_CTRL` 是 `CalculateIK()` 里才赋值的
   ⇒ 直接反射调用会 `NullReferenceException`（探针 `_scratch\_csbake\probe_ik.cs` 抓到的）。
   要预读就在调用前手动把 `IK_CTRL` 指到组件自己的 transform。
2. **物理步必须放在"帧循环的外层"**（老坑的新版本）：我第一版把 `GlobalControl.Run()` 写在了
   `for (每个 IK)` 的**内层**，于是第 2 个 IK 的 "pre" 采到的是"第 1 个 IK 已经跑完"的值
   —— 表现为"右腿 pre 局部旋转差 17~22°"，看着像真 bug，其实是 dump 的锅。
   探针 `probe_hidden.cs` 一句话就把它戳破了：t=2.0 时 `Bone_Leg_R_Up_ik.localRotation`
   在 `Run()` **之前** = 预制体值、**之后** = 我 dump 里那个"pre"值。

### 17.4 那 0.4px 到底还剩在哪（范围已缩到"产物侧"）

现在这几条都有逐帧真值背书，全部**精确**：

| 环节 | 真值来源 | 残差 |
| --- | --- | --- |
| DynamicBone（7 粒子链） | `alice_db_particles.json` | 0.0009 px |
| DynamicBone（28 粒子分叉链） | `alexandra_db_particles.json` | 0.0041 px |
| spline（尾巴） | `verify_*` 三处 | 0.0007~0.0012 px |
| **IK（腿，2 个）** | **`alice_ik_breast.json`** | **0.000 px** |
| `Run()` 里的其它项 | `_ParentControls=0`、`_ffdControls=0`、`AimDirection` 已按 `FaceCamera` 复刻 | — |

而 `breast t=1.5` 仍剩 **p90/最大 0.43/0.62px**，全部落在
`parts_leg_*` / `parts_Body` / `parts_Gatherbelt_Neck`（都是被 IK/骨盆带动的部件）。
注意一个强线索：**连"纯 clip 的基线"在这几个部件上也有 0.030~0.038px 的偏差，
而乳房部件只有 0.002~0.003px（差一个数量级）** ⇒ 剩下这段更像**产物侧的网格/蒙皮写出
（`_skin_mesh` / 绑定）或这几个部件的标定**问题，而不是 CS 运行时。
下一步的判据：把腿部那个 `SkinnedMeshRenderer` 的 **bones 列表 + 每根骨的 world 矩阵**
也 dump 出来，和移植版的 `rt.world` 逐根对（真值脚本可以直接在 `dump_ik_chain.cs` 上加）。

---

## 18 2026-10-10（三续）：骨头级真值 —— **每根骨都精确，残差在"产物写出"侧**

新片段 `_scratch\_csbake\dump_smr_bones.cs`（计划文件 `smrbones.txt`）：对指定部件导出
**蒙皮骨头清单** + 每帧每根骨的**世界 TRS 与局部 TRS**，跑法与烘焙器 `postStep` 一致
（`restore all locals` → `SampleAnimationClip` → `GlobalControl.Run()` →
`DynamicBone.UpdateDynamicBones(dt)`），产出
`partdump\alice_smr_bones.json`（Alice `breast`，200 帧 × 5 个部件）。

对拍脚本 `t_smr_bones.py`（判据：**必须比局部量**）。

```
state=breast 帧=200 渲染器=5
  [0] .../parts_Body            skinned n=85   骨=9
  [1] .../parts_Breast_L        skinned n=235  骨=3
  [2] .../parts_Gatherbelt_Neck skinned n=94   骨=6
  [3] .../parts_leg_L_up        skinned n=43   骨=3
  [4] .../parts_leg_R_up        skinned n=78   骨=5
  → 每根骨头的 局部位置 0.000px / 局部旋转 0.0000°（最差 0.0264°@Bone_Spine2 一帧）
    / 局部缩放 0.000；乳房那两根 DB 骨 0.004~0.007px（≈float 噪声）
```

⇒ **这 5 个部件蒙皮依赖的每一根骨头，逐帧都精确。**

⚠️ **两个"看着像错"的量，别被它们带偏**：

1. **世界矩阵上"提取旋转"**：`mat4_quat(rt.world[tf])`（Gram-Schmidt 正交化）和 Unity 的
   `Transform.rotation`（层级四元数相乘）在这个 rig（`Size_root` Z 缩放 0.001 ⇒ 世界矩阵带剪切）
   下**本来就不相等** —— 用世界量比会看到 6~84° 的"差"，但**局部量是 0.0000°**。
   比"骨头对不对"一律用局部量（`dst\...\localRotation` vs `rt.local`）。
2. **世界位置**倒是可以直接比：全部 0.000px（位置对剪切/提取方式不敏感）。

### 18.1 那么 0.43/0.62px 剩在哪 —— 唯一剩下的位置

到此为止，链路上每一环都有真值背书且都精确：

| 环节 | 真值 | 残差 |
| --- | --- | --- |
| clip 采样（含 IK/spline 骨） | `alice_ik_breast.json` | 0.000 px / 0.0000° |
| DynamicBone 7 粒子链 | `alice_db_particles.json` | 0.0009 px |
| DynamicBone 28 粒子分叉链 | `alexandra_db_particles.json` | 0.0041 px |
| spline（尾巴） | 三处 verify | 0.0007~0.0012 px |
| IK ×2 | `alice_ik_breast.json` | 0.000 px |
| **这 5 个部件的每根骨（局部 TRS）** | **`alice_smr_bones.json`** | **0.000** |

⇒ 剩下的 0.43px **不可能是"骨头算错"**，只能是：

* **`_skin_mesh`（蒙皮/绑定）**：`Σ w_i · bone_i.world · bindpose_i · v` 的实现细节
  （bindpose 的口径、`rootBone`、权重归一化…）；或
* 那几个部件的**标定 S**（`merge_report6.json` 里逐部件的 2×2 矩阵）。

判据（下一步）：对 `parts_leg_L_up` 在 `t=1.5` 把 Unity 的
`SkinnedMeshRenderer.BakeMesh()` 世界顶点、`bones` / `bindposes` / `boneWeights` 一起 dump，
和 `_skin_mesh` 的输出逐顶点对 —— 就能分清是"蒙皮公式"还是"标定"。
（注意基线本身在这几个部件上就有 0.030~0.038px、乳房部件只有 0.002~0.003px，
差一个数量级，这条线索也指向"这几个部件的蒙皮路径/标定"。）

---

## 19 2026-10-10（四续）：蒙皮真值 —— **也没问题；残差是"逐部件单位口径"**

### 19.1 怎么测的

新片段 `_scratch\_csbake\dump_skin.cs`（计划文件 `skin.txt`）：导出指定部件
①`sharedMesh` 的顶点 / `bindposes` / `boneWeights`、②`bones` / `rootBone` 列表、
③**两种姿态下的世界顶点**（`BakeMesh(false)` × `transform.localToWorldMatrix`）：

* **A** = 纯 `clip(t)` 姿态；
* **P** = A 上再跑 `GlobalControl.Run()`（真实 IK 姿态，移植版同样能复现 —— 用它当
  "已知扰动"，把绑定的常量偏移消掉，只看**蒙皮响应**）。

对拍脚本 `t_skin.py`。

### 19.2 结果

```
[0] parts_Body            n=85  ①顶点1.1e-7 bindpose5e-8 骨9/9同名 权重0/85不一致
                              ③(P−A) 中位 0.0000 / 最大 10.73 px
                              ④拟合标量 k 后残差：中位 0.0000 / 最大 0.000000   k=8.036989
[1] parts_Breast_L        n=235 ①全部一致
                              ③中位 0.0000 / 最大 0.0000
[2] parts_Gatherbelt_Neck n=94  ①全部一致  ③中位 0.0039 / 最大 0.3622
                              ④拟合 k 后残差 0.000000   k=1.010102
[3] parts_leg_L_up        n=43  ①顶点/bindpose/骨头全一致（权重只是 2 通道 vs 4 通道补齐）
                              ③中位 0.0237 / 最大 0.1222
                              ④拟合 k 后残差 0.000000   k=1.010073
[4] parts_leg_R_up        n=78  ①全部一致  ③中位 0.0001 / 最大 0.0004
                              ④拟合 k 后残差 0.000000   k=1.000000
```

**三条结论**：

1. **解析精确**：这 5 个部件的 `sharedMesh` 顶点（~1e-7）、`bindposes`（~5e-8）、
   `bones` 列表（逐名对应）、`boneWeights`（只有通道数补齐的差别）都和 Unity 一致。
2. **蒙皮公式精确**：把 Unity 的位移场 `u = P−A` 用最小二乘映射到移植版的位移场 `p`
   （`p ≈ k·u`，或 2×2 矩阵 `M`），**拟合残差全部 0.000000**。也就是说移植版算出来的
   形变场就是 Unity 的形变场**乘一个逐部件常数**（`k` 就是 `1/|lossyScale|`：
   Body 8.037 = 1/0.1244，Gatherbelt/leg_L 1.0101 = 1/0.99，leg_R 1.000000）。
3. ⇒ **`_skin_mesh`（绑定/蒙皮）没有问题，骨架也没有问题。** 剩下的 ≤0.43px 只能在
   **"逐部件单位换算 / 标定"** 上：移植版用理想的 `unit_k / |lossyScale|`，而
   `merge_report*.json` 里的 `S` 是从**录制数据最小二乘拟合**出来的，两者差 ~0.1% 量级，
   表现在 290px 的位移上就是那 0.4px。

### 19.3 顺带两个"别再犯"（都是这次对拍脚本自己的坑）

1. **`rt.local = lv` 是同一个 dict**：`run_global_control` 会就地改写 `rt.local`
   ⇒ 下一个部件复用 `lv` 时 A 姿态被污染（实测让 `parts_leg_R_up` 的 A 差出 57px、
   拟合 k 直接失真）。**要么每次 `dict(lv)` 传副本**。
2. **绝对顶点不能直接比**：移植版 `_skin_mesh` 的输出在"转换器空间"，和 Unity 世界差一个
   **逐部件**的 `1/|lossyScale|`（Body 差 8×，leg_L/Gatherbelt 差 1.01×，leg_R 差 1.000×）
   ⇒ 只有 (P−A) 差值、或拟合后的残差才有意义。

---

## 20 2026-10-10（定案）：那 0.4px 的真凶 = **产物的关键帧裁剪阈值**

### 20.1 走过的一条弯路（记下来别再追）

我一度怀疑是 `merge_cs_bake.py:239-246` 里按 **Unity `lossyScale`** 算的 `S`：

```python
ls = ls_of.get(nm)                 # 录制器给的 r["lossyScale"][0]
k = unit_k / ls                    # S = unit_k / |Unity lossyScale|
```

并从产物反推出"逐部件实际系数"`s_implied`，看到它和 `S` 在 5 个部件上差 0.2%~2%
（Body 0.980、Gatherbelt 0.992、leg_L_up 1.012、leg_R_up 0.998，其余 8 个吻合到 1e-6），
于是以为找到了"尺度口径"的根因。**这个推断是错的**——`s_implied` 的偏差本身就是
"在裁剪掉的关键帧之间做线性插值"造成的，属于同一个根因的表现，不是独立证据。

### 20.2 真正的根因（代码位置 + 一行）

`src\unity2spine\convert\static_prefab_spine.py`：

```python
DEFORM_TOL_WORLD = 0.001          # 第 2168 行附近
deform_tol = DEFORM_TOL_WORLD * unit_k        # ≈ 0.8 px（Alice unit_k=803.7）
... 只有"相对上一个已写关键帧"的变化 > deform_tol 才写新关键帧   # ~3129 / ~3146 行
```

而**消费端（查看器 / `verify_merge` / `diag_port_vs_rec`）在没有写帧的时刻是线性插值**，
所以产物能偏到接近这个阈值。原来那句注释写着"比验收阈值 0.05 低 50 倍"，
其实 **0.8px 比 0.05px 大 16 倍**。

### 20.3 A/B（把阈值做成环境变量 `U2S_DEFORM_TOL_WORLD`，其它一律不动）

| 取样点 | 原版 0.001（0.8px） | **EXP 0.00012（0.096px）** | EXP 0 | 录制路线（对照） |
| --- | --- | --- | --- | --- |
| Alice `breast t=1.5` 中位/p90/最大 | 0.0009 / **0.4272** / **0.5998** | **0.0006 / 0.0014 / 0.0555** | 0.0006 / 0.0012 / 0.0198 | 0.0032 / 0.0057 / 0.0371 |
| `并合 vs Unity B` 同处 | 0.0031 / 0.4263 / **0.6198** | **0.0029 / 0.0293 / 0.0430** | — | 0.0051 / 0.0312 / 0.0533 |
| Alice `Tep_1 t=4.0` 中位/最大 | **0.1490** / 0.8064 | **0.0007 / 0.8216**（p90 0.5183→0.1245） | 0.0007 / — | 0.0033 / 0.5432 |
| Alice `lobby t=3.0` 中位/p90/最大 | 0.0169 / 0.0848 / 0.3494 | 0.0067 / 0.0542 / **0.0621** | — | 0.0043 / 0.0267 / 0.2770 |
| 体积（json / skel） | 101.0 / 22.1 MB | 124.2 / 27.1 MB（+23%） | 125.9 / 27.5 MB | — |

⇒ **采纳 `DEFORM_TOL_WORLD = 0.00012`（≈0.096px，验收阈值 0.05px 的两倍）**：
移植版产物在 `breast t=1.5` 上达到 `中位 0.0029 / 最大 0.0430`，
**与录制路线（0.0051 / 0.0533）同级甚至更好，而且完全离线**。

回退方式（不做任何代码改动）：`U2S_DEFORM_TOL_WORLD=0.001` 回到旧裁剪；
`=0` 表示逐帧不裁剪（最精确、体积最大）。

### 20.4 产物落位

| 目录 | 内容 |
| --- | --- |
| `归档-proj-Mobile-old\_spine_conv_cs_port\3P_Alice_NS1` / `3P_Alexandra_NS1` | **采纳后**（默认 0.00012） |
| `归档-proj-Mobile-old\_spine_conv_cs_port_tol001\3P_Alice_NS1` | 采纳**前**的备份（0.001） |
| `_scratch\_exp_tol0_alice` / `_scratch\_exp_tol01_alice` | EXP 两份（0 / 0.00012）对照 |
| `_Spine待检查_20261009\3P_Alice_NS1\移植版_离线_逐帧精确\` | **给用户看的导出**（json 124.2MB / skel 27.1MB / 7 张图集） |

⚠️ 这一项**不影响** Alexandra 的 5.6px —— 那是 DynamicBone 的"建链姿态/启动瞬态"（§16），
与关键帧裁剪无关；改阈值后它的数字一模一样。

---

## 21 2026-10-10（收尾）：Alexandra 的"建链姿态"A/B 判定 + **全量 157 个已启动**

### 21.1 `U2S_CS_DB_SETUP=rest` 实验结果：**不合格，弃用**

把"粒子链按预制体静态姿态建"（= `verify_cs.cs` / `dump_db_particles.cs` 两个真值生成器的口径）
做成开关 `U2S_CS_DB_SETUP=rest`（默认仍是 `clip`），两边各转一份对拍：

| 取样点 | `rest` 建链 | **`clip` 建链（保留）** |
| --- | --- | --- |
| Alexandra `Start t=3.0` | 3.3730 / 25.73 / **34.68** | **0.0309 / 0.967 / 5.634** |
| Alexandra `lobby t=2.0` | 3.3728 / 25.73 / **34.68** | **0.2549 / 3.399 / 6.262** |
| Alice `breast t=1.5` | 0.0006 / 0.0014 / 0.0555 | 完全相同 |
| Alice `Tep_1 t=4.0` / `lobby t=3.0` | 完全相同 | — |

⇒ **`rest` 明显更差（Alexandra 差 6 倍）**，且对 Alice 毫无影响（Alice 那条链在两种口径下等价）。
所以**保持 `clip`**，`U2S_CS_DB_SETUP=rest` 只作为实验开关保留。

（有意思的是：`t_db_frames.py` 在这个 `rest` 口径下能让**粒子**与 Unity 一致到 0.004px，
但**产物顶点**反而差 3.37px ⇒ 两个 Unity 真值脚本的"建链时刻"其实并不一致，
`dump_db_particles.cs` 的口径 ≠ `verify_cs.cs` 的口径。想再往下追，得先确认
`verify_cs.cs` 在 `SetupParticles` 之前到底有没有跑过 `SampleAnimationClip`。）

### 21.2 全量 157 个：已启动（纯离线）

新脚本 `tools\batch_cs_convert.py`（每个角色一个子进程，崩/挂不中断；实时日志 + 汇总）：

```powershell
cd D:\VB\Unity2Spine
D:\Anconda\python.exe tools\batch_cs_convert.py --skip-done --no-static-check
```

* 冒烟 3 个：**3/3 OK**，平均 **186.6s/角色** ⇒ 157 个 ≈ **8.1 小时**；
* 日志：`_scratch\batch_cs_<时间戳>.log`（每角色一行开始/结束 + 耗时），
  汇总：`_scratch\batch_cs_<时间戳>_summary.txt`（ok/FAIL 清单）；
* 产物：`归档-proj-Mobile-old\_spine_conv_cs_port\<角色>\`（json/skel/atlas/png/config）；
* 跑之前看过内存与磁盘（串行、一次一个；D 盘 218GB 可用，人均 20~45MB）。

⚠️ `--skip-done` 的小坑：产物 skel 名里**保留 `.uAnim`**（`<prefab基名>_static.skel`），
早期版本按"去掉 .uAnim"去找所以永不命中 —— 已修；本轮因此把前 5 个又转了一遍（多花 ~15min）。
**下一轮 QC**：批量结束后再单独跑 `tools\static_check.py` 过一遍（本轮为了时间没带
`--static-check`），看每角色的 `missingAnimated/missingStatic/visibilityConflicts` 是否为 0。

---

## 22 2026-10-10（导出设定定稿）：标准导出只出 `.skel`，配置改名，一致性已验收

### 22.1 用户定的三条新设定（已落地）

| 设定 | 实现 |
| --- | --- |
| 配置文件从 `.config.json` 改成 **`<文件夹名>.config.json`** | `spine_out.write_viewer_config(..., name=None)`：默认取输出目录名（= 角色名，**不含 `.uAnim`**）；老名字（`.config.json` / `<prefab基名含.uAnim>.config.json`）会在重导时**自动改名迁移**，查看器里调好的设置不丢。用 `tools\finalize_skel_only.py` 批量统一 |
| **标准导出 = 只出 `.skel`** | `convert_static(..., want_skel=True, want_json=False)`；`.skel` 恒写 |
| JSON 只在 Debug/研究时导出 | 新增 CLI 开关 **`--json`**；旧的 `--skel` 保留但已是默认（兼容旧命令）；`--calib` 需要 `.json`，没带 `--json` 会打印提示；README/`_static_info.json`（`json: null`）同步；`face_check.py` 在没有 json 时给出明确提示 |

### 22.2 删 JSON 之前先验收"skel ≡ json"（关键动作）

新工具 `tools\check_skel_vs_json.py`：用查看器那套 spine-cpp（`Spine380.pyd`）**把两个文件各加载一遍**，比
①动画名/皮肤名；②`SetToSetupPose` 与**每条动画 × 若干归一化时刻**（`SetAnimationTime → Update → Apply →
UpdateWorldTransform`）后的**顶点缓冲逐元素**、索引缓冲、`blendRanges`。
（顶点要走 **buffer 协议**：`np.array(gb, copy=False, dtype='f4')` / `gb.getIbo()`，和 `SpineRender.py:810` 一样。）

| 角色 | json | skel | 结果 |
| --- | --- | --- | --- |
| `BR_Amy_N` | 3.8 MB | 0.8 MB | 动画/皮肤名一致；**VBO max\|Δ\|=0.000e+00**、IBO/blendRanges 一致 |
| `3P_Alexandra_N` | 7.0 MB | 1.5 MB | 逐位一致 |
| `BR_Leprechaun_NS1` | 16 MB | 3.4 MB | 逐位一致 |
| `BR_Miho_NS1` | 37 MB | 7.9 MB | 逐位一致 |
| `3P_Alice_NS2` | 90 MB | 19.5 MB | 逐位一致（284s） |
| `3P_Alice_NS1` | 124 MB | 27.1 MB | 逐位一致（434s） |
| `3P_Eternity_NS1` / `3P_BlackWyrm_NS1` / `BR_Nymph_NS1` | 254/314/319 MB | 55.9/69.6/71.1 MB | 只加载 skel：结构完整（如 Nymph 13 条动画 / 67446 float / 16992 int） |

⇒ **`.skel` 与 `.json` 是同一份数据（逐位一致）**，删 JSON 不丢东西。
已对已完成的 98 个角色执行 `finalize_skel_only.py`（删 json 98 个共 **6.02 GB**、config 全部改名并指向 `.skel`）。

⚠️ **一次只跑一个角色、别拿超大 JSON 喂 cpp**：本轮我把 124 MB 的 JSON 丢给 spine-cpp，看着像"卡死"，
实测只是慢（434s）；内存全程 9~10 GB 可用。这条同时适用于 `check_skel_vs_json.py` 的用法说明。

### 22.3 本轮修掉的两个真问题

1. **`2DModel_BR_RoyalArsenal_NS1` 转换崩溃**（`ValueError: 矩阵不可逆`）：这个 rig 里有**世界矩阵奇异**的
   退化节点，IK 写 `poleVector` 时 `set_world` 要对父矩阵求逆 → 整条转换打挂。
   修：`unity_mesh.mat4_invert_tolerant()`（奇异方向在逆里置 0，等价"丢掉不可恢复的那个轴"，和 Unity 行为一致）
   + `Runtime.set_world` 里 `try mat4_invert / except → mat4_invert_tolerant`。重转该角色 **66s 成功**。
2. **config 名字写成了 `<prefab基名含.uAnim>.config.json`**：因为我把 `base` 传给了 `write_viewer_config` 的
   `name=`。已改成用**输出目录名**；`finalize_skel_only.py` 也扩成"任何 `*.config.json` 都归一成 `<目录名>.config.json`"。

---

## 23 2026-10-10（全量完成）：157 个角色转完 + 逐角色 QC 干净 + 备份

### 23.1 两轮批量的结果

| 轮次 | 说明 | 结果 |
| --- | --- | --- |
| 第 1 轮 11:34 启动 | 旧设定（带 `.json`），跑到第 33 个时我按用户要求停了（改导出设定） | 98 个完成 |
| 第 2 轮 14:11 启动（`--skip-done`，新设定=skel-only） | **61 个待转** | **成功 60 / 失败 1，69.5 分钟** |
| 失败那 1 个 | `2DModel_BR_RoyalArsenal_NS1`：零缩放 rig 导致 `矩阵不可逆`（见 §22.3） | **修完重转 66s 成功** |

单角色耗时：最快 17.3s / 中位 56.9s / 最慢 320.2s（大角色）。

### 23.2 全量完整性检查（脚本化，逐条过）

```
prefab 数 157 / 产物目录 157
缺产物目录: 0        缺 skel: 0
还有 json : 0        缺 atlas: 0
config 名不对: 0     （全部是 <目录名>.config.json，且 skeleton 指向 .skel）
```

顺手把两个"无 `2DModel_` 前缀"的早期手工产物目录（`3P_Alexandra_NS1`/`3P_Alice_NS1`，重复品）
挪到 `Unity2Spine\delete\stale_port_20261010\`，避免与批量产物混淆。

### 23.3 逐角色 QC（`tools\batch_static_check.py`，157 个全跑）

每个角色跑 `tools\static_check.py`，看四项：`missingAnimated`（动画引用了但没导出）、
`missingStatic`（静态可见没导出）、`visibilityConflicts`（与 Unity 真值显隐冲突）、
`unknownCurvePaths`（曲线 path 对不上场景节点）。

**结果：157 个角色全部四项为 0**（日志 `_scratch\qc_<时间戳>.log`，逐角色报告 `_scratch\qc\<角色>.json`，
汇总 `_scratch\qc_<时间戳>_summary.tsv`）。

首轮跑出来 **2 个角色被标红**，逐条查完都是**工具侧的保守误报**（产物没问题），并顺手把工具口径修成与转换器一致：

| 角色 | 标记 | 真相 | 处理 |
| --- | --- | --- | --- |
| `2DModel_BR_Phoenix_NS1` | `missingAnimated=4`：`hiddenBone_3/4/5/6` | 这几个的贴图是 **`BoneJoint_8.png`**（Puppet2D 骨骼关节编辑器辅助图），本就在默认屏蔽规则里（`'bonejoint'`）；动画确实 K 了它们的 transform，于是被判"动了没导" | `_renderer_reason()` 增加"贴图命中屏蔽规则"判定 → 归入 `unexportable` 并写明原因。复查 **0/0/0/0** |
| `2DModel_PECS_ElvenForestmaker_NS1_DL_N` | `missingAnimated=2`：`parts_Eyebrow_Normal`、`parts_Milk5` | 转换器**有意排除**它们，`_static_info.json` 的 `excludedParts` 里写着原因：**"Unity 里始终禁用（SetActive=0）"**（表情/换装备选件，整段动画都不显示）。`static_check` 自己的 `active_any` 判据比转换器的 `visible_anywhere` 松 → 误报 | `build_report()` 改为**先采信产物的 `excludedParts` 原因**。复查 **0/0/0/0** |

⇒ **最终：157/157 角色的 `missingAnimated` / `missingStatic` / `visibilityConflicts` /
`unknownCurvePaths` 全部为 0。** QC 用时 62.3 分钟。

### 23.4 备份

项目整体备份到 **`D:\VB\lo_uncen2Spine\`**（跳过可公开获取的资料/源码/软件）：

| 目录 | 内容 | 体积 |
| --- | --- | --- |
| `Unity2Spine\` | 转换器本体（`src`/`tools`/`docs`/`info`/`gui`/`samples`/`_reverse`…），已排除 `third_party`/`_reference`/`delete`/`_probe50_rt4`/`_scratch` 里的实验件 | 20.9 GB |
| `products\_spine_conv_cs_port\` | **157 个角色的 skel-only 产物**（含图集/config/README） | 2.9 GB |
| `products\_spine_conv\` / `_spine_conv_cs\` / `_spine_conv_cs_port_tol001\` | 基线 / 录制合并 / 旧阈值备份（验收与 A/B 用） | 0.37 GB |
| `deliverable\_Spine待检查_20261009\` | 交付包（基线 / A / B / 对比图 / 移植版） | 0.49 GB |
| `binding\Spine3.8-py\` + `binding\viewer_patch\` | 改过的 spine3.8 pybind11 工程（含 `修改记录_20261009.md`/`预备修正.md`/`BUG_RangeBuffer_Mesh_OOB.md`）+ 查看器补丁（`SpineRender.py`、`Spine380.pyd`） | 65 MB |
| `docs\` | 两份交接/进展 md + `问题记录` | 小 |

排除清单（网上可公开获取，未备份）：`third_party\`、`_reference\`、`_probe50_rt4\`（测试输出）、
`delete\`（待删件）、`__pycache__`/`*.pyc`、以及 `D:\Libs`（spine-runtimes、pybind11 等原始库）、
Unity 安装与 `proj-Mobile-old` 本体（约定不打包）。

---

## 24 2026-10-10（本轮）：shader 清点 + 自动识别（修掉一个真 bug）+ 用户检查清单

用户给了两份东西：① 对**全部 shader 引用**做检查、要求转换器**自动识别不同部件的 shader**
（可指定 uuid 之类的特殊识别）；② 肉眼看出来的 9 条角色问题（`Sampler.txt`）。下面是 ① 的进展。

### 24.1 shader 清点（两个新工具）

| 工具 | 作用 | 结果 |
| --- | --- | --- |
| `tools\shader_inventory.py` | 扫工程里**所有** `.mat` 引用的 shader | 494 个材质 / **22 种** shader |
| `tools\shader_usage_inventory.py` | 扫 **157 个 prefab 实际引用**的 shader，并按 shader 源码 `Blend` 归类 | 只用到 **6 种**；其中 **25 个角色**用到非普通混合 |

157 个角色实际用到的 shader（内建名字是**用 Unity 引擎实测**的：
`_scratch\_csbake\probe_shader_names.cs` 加载材质问 `mat.shader.name`）：

| shader | blend | 角色数 | 转换器（修前 → 修后） |
| --- | --- | --- | --- |
| `Sprites/Default`（10753） | normal | 157 | ✓ → ✓ |
| `Legacy Shaders/Particles/Additive`（200） | additive | 14 | ✓ → ✓ |
| `Legacy Shaders/Particles/Multiply`（205） | multiply | 12 | ✓ → ✓ |
| `Legacy Shaders/Particles/Alpha Blended`（203） | normal | 2 | 未登记（结果对）→ 已登记 |
| **`Mobile/Particles/Additive`（10720）** | **additive** | **1（`3P_Ran_NS1`）** | ✗ 当 normal → **已修** |
| `Standard`（46） | normal(opaque) | 1 | 未登记（结果对）→ 已登记 |

另外全工程里还有 `202 Additive(Soft)`、`206 Multiply(Double)`、`Skeleton PMA Multiply/Additive/Screen`、
`Spine/Skeleton Tint` 等 —— 但它们**没有被这 157 个角色引用**（是工程里遗留的 Spine 材质），
仍然按"通用规则"支持（见 24.3）。

### 24.2 修掉的真 bug：`mesh_style()` **永远返回 normal**

```python
def mesh_style(assets, part):
    """静态/蒙皮 mesh 的顶点色（材质 _Color，默认白）。"""
    ...
    return col, "normal", False          # ← 加法/乘法件全被当普通透明！
```

`sprite_style()` 一直有 additive/multiply 分支，而给 **蒙皮/静态网格**用的 `mesh_style()` 没有。
⇒ 所有"蒙皮网格 + 加色/乘法材质"的部件都是错的。用户点名的
`2DModel_BR_May_NS3.uAnim` 的 `parts_Breast_Shadow_Multiple_015_Skinned` 正是这一类。

修法：`mesh_style()` 与 `sprite_style()` **同口径**（additive 的 `4*_TintColor` 折算、
multiply 的 `2*_TintColor` 折算、screen、premultiply 标记）。**已验证**：

```
2DModel_BR_May_NS3（重转 + --json 抽查）
  parts_Breast_Shadow_Multiple_015_Skinned_02   blend = multiply   ← 修前是 normal
  parts_Machine_Shadow_Multiple_012_Skinned_32  blend = multiply
  parts_R_Thigh_Shadow_009_Skinned / parts_L_Thigh_Shadow_012_Skinned → normal（它们用 Sprites/Default，本来就对）
```

同类受益的角色（用 multiply/additive 且含蒙皮件）：`PECS_Babariana_NS1`（`..._shadow`）、
`BR_DrM_NS1`（`R_Thigh_Multiply`）、`PECS_DarkElf_NS1(_DL_N)`（`*_Multiply`）、
`ST_Tiamat_NS1`（`parts Multiply`）、`BR_Cheona_NS1`/`BR_Raven_N`/`BR_Shirayuri_NS1`/`BR_Undine_NS1` 等。

### 24.3 内建 fileID 补齐 + 自定义 shader 按源码 `Blend` 自动识别

* `SHADER_ADDITIVE = {200, 202, 10720}`（原来只有 200）、`SHADER_MULTIPLY = {205, 206}`（原来只有 205）；
  另外把 `201/203/46/103/104/10750/10751/10753/10754` 登记成 normal（只为报告清楚）。
* 新增 `_custom_shader_blend(assets, guid)`：**读自定义 shader 的 `.shader` 源码里第一条 `Blend` 指令**
  判语义 —— `(One,One)`/`(SrcAlpha,One)`→additive、`(DstColor,*)`→multiply、
  `(One,OneMinusSrcColor)`→screen、`(One,OneMinusSrcAlpha)`→normal+预乘；源码缺失时用
  shader 名字里带 Multiply/Screen/Additive 兜底。
  ⇒ 这满足用户"转换器能自动识别不同部件的 shader（含按 uuid 指定）"的要求：**按 guid 找到 shader 源码 → 按语义判混合**，不是白名单。
* 副产品记录（Spine 系 shader 的 Blend 语义，实测源码）：`PMA Additive = One One`、
  `PMA Multiply = DstColor OneMinusSrcAlpha`、`PMA Screen = One OneMinusSrcColor`、
  `Spine/Skeleton = One OneMinusSrcAlpha`（预乘普通混合）。`spine38_binary.BLEND_NAMES`
  确认支持 `('normal','additive','multiply','screen')` 四种。

### 24.4 用户指令：导出设定改默认（**已于 §25 落地**）

用户 2026-10-10 指令原文意思（我的理解，动手前再确认一次）：
* **默认：转换时"直接对图集处理"** —— 即把乘法影子的观感烘进图集（暗色 + α，走普通混合），
  这样产物不依赖运行时的 multiply 支持就能看对（等价于之前 B 版"乘法烘暗"）。
* **把 `blend=multiply` 这套（逐槽位混合 + 图集 α=1）归档为"实验性方法"**，默认转换不用它。
* 同理，"其他非默认的导出设定"都走实验开关，默认关。

要落地的改动（纯离线；**2026-10-10 傍晚已全部做完，见 §25**）：
1. 图集阶段加"乘法件区域烘暗"（把 `tools\bake_cs\bake_multiply_dark.py` 的公式并进
   `convert_static` 的图集合成；按每个 multiply 槽位自己的 UV 矩形处理）；
2. 这些槽位的 `blend` 输出 **normal**；
3. A 方案（`blend=multiply` + α=1）挂到实验开关（例如 `--multiply-blend` / `U2S_MULTIPLY_BLEND=1`）；
4. 重新转换 25 个受影响角色并抽查（May_NS3 / Babariana / DarkElf / Tiamat / Ran 等）。

### 24.5 ⏳ 用户新检查出的 9 条（`Sampler.txt`）—— 待办清单

完整清单与逐条初步分析写在交接文档 §5.5（A 类 shader 2 条 + B 类算法/转换 7 条）。
其中 **A2（May_NS3 乘法阴影）本轮已修**；其余待逐条用"Unity 真值 vs 产物"定位后再动代码。

---

## 25 2026-10-10（收官）：乘法件默认"直接对图集处理"

用户指令（两次，意思一致）：

> "默认对图集直接处理吧，把其他导出设定为实验性的方法，默认转换的方式不用这个。"

即：**默认转换就把乘法烘进图集**（产物不依赖运行时的 multiply 混合支持），
把"逐槽位 `blend=multiply` + 图集 α=1"这套**归档成实验性方法**、默认路径不用它。

### 25.1 为什么"烘进图集"能与 Unity 的乘法等价

Unity 的 `Legacy Shaders/Particles/Multiply`（内建 fileID 205，影子材质）：

```
片元:  col.rgb = 2 · i.color.rgb · _TintColor.rgb · tex.rgb = m   （逐通道）
混合:  Blend Zero SrcColor  ⇒  out.rgb = dst.rgb × m
```

普通 alpha 混合（Spine 的 `normal`）在 `src.rgb = 黑` 时：

```
out = src.rgb·src.a + dst·(1 − src.a) = 0 + dst·(1 − src.a)
```

令 `src.a = 1 − m` ⇒ `out = dst · m`，**与乘法逐像素等价**（`m` 为灰时完全等价）。

于是烘焙规则是：**把该件 UV 矩形内的 texel 改成 `rgb = 0`、`α = 1 − m`**，
槽位颜色取"黑 + 原 alpha"（`000000xx`）。`m` 里的顶点色/`_TintColor` 用**静态值**
（`min(1, i.color·2·_TintColor)`，与 `sprite_style/mesh_style` 原来的乘法分支同一口径）。

三个附带好处：

* **白底自动正确**：贴图白 → `m=1` → `α=0` → 完全不可见（Unity 里乘 1 也是"什么都不改"）；
* **α 掩码贴图也自动正确**：不会再把"浅粉 + α≈0.29"的贴图当成一块粉色挡在画面上（§5.1.7 的病根）；
* 产物**不再依赖运行时的 multiply 混合**，任何查看器/引擎直接看就对（不再需要 §3.5 的按槽位分批混合）。

### 25.2 代码改在哪（`src\unity2spine\convert\static_prefab_spine.py`）

| 位置 | 改动 |
| --- | --- |
| `MULTIPLY_BLEND`（模块常量） | 默认 `False`；环境变量 `U2S_MULTIPLY_BLEND=1` 打开实验口径 |
| `apply_multiply_policy(e)` | 默认口径下把乘法因子搬到 `e["mult_factor"]`、槽位颜色改 `黑 + 原 alpha`、`blend → normal`、打上 `bake_multiply` 标记 |
| 条目构造（`kept` / `variant_entries`） | 一律过一遍 `apply_multiply_policy` |
| 图集合成（`convert_static` 内） | 新增 `_uv_rects` / `_bake_px` / `_bake_rects` / `_crop_page`：按**因子分组**处理乘法件；矩形若被别的部件共用（`_touches`）就**裁成独立小页**（`*_static_N_mul.png`）并重映射 UV；加色（预乘）那条老路径原样保留、共用同一套 `_bake_*` 原语 |
| 槽位/附件输出 | 区域解析改走 `_region_for()`（裁剪页 > 预乘页 > 直通页）、UV 重映射走 `_remap_uv()` |
| `color_timeline(...)` | 新增 `bake_dark`：乘法件的槽位颜色 rgb 恒 0，只让 alpha 曲线继续淡入淡出 |
| `_static_info.json` | 新增 `multiply` 段（`mode` / `count` / `parts`[部件名、因子、页、是否裁剪]），`partsMeta` 里乘法件带 `multiplyBaked` + `multiplyFactor` |
| README（逐角色） | 加一行"乘法件：N 个已烘进图集（槽位 normal）"，实验口径下改写成"保留 blend=multiply（实验）" |
| CLI | 新增 `--multiply-blend`（**实验口径**） |

### 25.3 已知限制（写清楚，别踩）

1. **彩色乘法因子会灰化**：`m` 三通道不一致时取均值（`avg(m_r,m_g,m_b)`）—— 单靠一个 alpha
   表达不了逐通道缩放。实测这批影子因子都是 `(1,1,1)` 灰，无影响。
2. **乘法件的 rgb 颜色曲线不再有语义**：默认口径下槽位 rgb 恒 0，只有 alpha 曲线有效
   （`color_timeline(bake_dark=True)` 会把 rgb 强制 0）。若将来遇到"靠 m_Color 的 rgb 动画
   调乘法深浅"的件，要么改回实验口径，要么把该曲线烘成图集的多帧纹理。
3. **两种口径的产物不能混用**：默认产物再喂"支持 multiply 的查看器"会**双倍变暗**；
   实验产物喂普通查看器会**泛白**（贴图直通 + 区域 α=1）。目录里 `_static_info.json`
   的 `multiply.mode` 写着是哪种。
4. 乘法件贴在**同一张图**上、且矩形与别的部件重叠时会多出一张小页（`_mul` 后缀），
   图集页数 +1 —— 这是为了让"别的部件的像素保持直通"（与加色件的 A/B 方案同一思路）。

### 25.4 账本 + 验收（`tools\check_multiply_bake.py`）

**账本**：`_static_info.json` 的 `multiply.parts` 每条记
`factor / page / rects（闭区间，源图像素）/ uvMap / pageSize`。校验器**按账本逐条核验**，
不去猜"槽位名 ↔ 部件名"，也不用 JSON 里被四舍五入过的 UV 反推矩形
（2026-10-10 的教训：那样反推出来的框比真实烘焙范围**多 1px**，
会在框的最外一圈看到"没烘到"的源像素，看着像 bug，其实是**工具的 off-by-one**）。

校验器查四件事：① 产物里还有没有 `blend=multiply`（实验口径则查"数量是否与账本一致"）；
② 每条账本矩形内 `rgb=0`、`α=1−m`（实验口径查 `α=255`）；③ 裁剪页整页只应是"黑 + α"；
④ `--base <旧产物>` 逐页比对，确认**改动只发生在这些矩形里**。

**同轮修掉的一个真 off-by-one**：`_bake_rects` 原来写 `arr[y0:y1, x0:x1]`
（右/下**开**区间），比账本矩形少烘 1 行 1 列 ⇒ 乘法件边缘留一条"原贴图"的浅粉细线
（加色件那条老路径同样有这个问题，只是看不出来）。改成**闭区间**后：

```
修改前：…_static_2.png 改动 65136 像素（矩形 277×237=65649，差 513 = 一条边）
修改后：…_static_2.png 改动 65649 像素 = 矩形面积，完全相等
```

样例 `2DModel_BR_May_NS3`（终版口径）：

```
模式: baked-into-atlas (default)   乘法件 2 个
非普通混合的槽位: 0 个
  parts_Machine_Shadow_Multiple_012_Skinned_32  裁剪页 …_static_0_mul.png 481×497
     矩形 (2,2)-(478,494)         rgb_max=0  α 0/255/157.1  ⇒ m ∈ [0.000, 1.000]
  parts_Breast_Shadow_Multiple_015_Skinned_02   页 …_static_2.png
     矩形 (1726,1541)-(2002,1777) rgb_max=0  α 0/245/78.2   ⇒ m ∈ [0.039, 1.000]
  …_static_1.png ≈旧 …_static_0.png 改动 0 像素，矩形外 0 个
  …_static_2.png ≈旧 …_static_1.png 改动 65649 像素，矩形外 0 个
PASS：乘法件的图集口径正确（与转换器账本逐条吻合）
```

再跑 `tools\check_skel_vs_json.py --dir <产物>`：3 条动画 × 5 个时刻 + setup
**VBO `max|Δ| = 0.000e+00`**、IBO 8304/8304 一致、`blendRanges [0, 8304, 0]`
（= 没有任何槽位落在非默认混合段里）。⇒ 新口径没有把骨架/时间轴数据写歪。

### 25.5 重转范围：只动 25 个角色

改动只影响"用到非普通混合材质"的角色（`tools\shader_usage_inventory.py` 判定）：
**157 个里 25 个**（`Particles/Additive` 14 个、`Particles/Multiply` 12 个、
`Mobile/Particles/Additive` 1 个，去重后 25）。其余 132 个角色的图集是"源贴图逐字节复制"，
**这条路径没改**，所以不用重转。

```powershell
cd D:\VB\Unity2Spine
python tools\shader_usage_inventory.py --out-txt _scratch\non_normal_chars_20261010.txt
python tools\batch_cs_convert.py --exact-file _scratch\non_normal_chars_20261010.txt
```

（`batch_cs_convert.py` 本轮加了 `--exact-file`：按清单精确匹配角色名，
免得 `--only` 的子串匹配把 `Khan_N` 连 `Khan_NS1/NS2` 一起转。）

重转前的 25 个旧产物留在
`归档-proj-Mobile-old\_spine_conv_cs_port_旧_乘法烘图集前_20261010\`，供 A/B 与
`check_multiply_bake.py --base` 使用。

### 25.6 一个"看着像 bug、其实忠实"的例子

`PECS_Babariana_NS1` 的 `parts_004_shadow acc_skinned_21` 烘出来是**全透明页**（α 全 0）。
查证链：

* 账本说它"就地烘在图集页"→ 但裁剪页 164×232 的 PNG 只有 **227 字节**（整块同值）；
* 该件 UV 矩形落在贴图 `PECS_Babariana_NS1_part2.png` 的一块**纯白**区域
  （该贴图 rgb 均值 234.8、透明区是白色；全白 160×228 窗口有几千个）；
* 材质是内建 **205**、`.mat` 里**没有** `_TintColor` ⇒ shader 默认 0.5 灰 ⇒ 因子 = 1；
* ⇒ `m = tex.rgb = 1` ⇒ Unity 里就是 `dst×1`（**什么都不改**）。

所以"不可见"是对的；同角色另外 3 个影子（part1 的三个 shadow）正常烘出 α ≤ 255。
**结论**：乘法件的可见性差异来自**贴图 rgb 本身**，不是烘法。

### 25.7 验证口径（用户 2026-10-10 指令）

* **观感 / shader / 颜色**类问题：**不跟 Unity 比**，产物直接丢进交付文件夹由用户**肉眼看**
  （本轮的交付包：`D:\VB\Search\New\_Spine待检查_20261010_乘法烘图集\`，25 个角色 + README）。
* **算法 / 运动 / 骨骼**类问题：**必须与 Unity 导出的真值对照**
  （`PartDataRecorder.cs` / `verify_cs.cs` / `calib_geo.py` / `compare_play_truth.py`），
  并把"真值是怎么导出来的"写清楚；不许拿"另一条路线的产物"当唯一判据。

---

## 26 2026-10-10（第二轮）：**逐 shader 实测**——乘法烘法错了，加色查看器漏了

用户肉眼过完 25 个角色后反馈（原话）：Alice_NS1 的 `breast` 原先对、现在错（多边形淡影）、
Daphne 也是、DrM_NS1 腿上多色块、May_NS3 整个胸变黑、Scathy_N 面板看不清、Shirayuri_NS1 脸上黑块。
指令：**"取各含有不同 shader 的模型各一个为代表，修复转化，然后我来看是否正确"**、
**"把剩下几个 shader 与转化一个个检查是否逻辑正确"**。

### 26.1 办法：不猜源码，直接在 Unity 里量

新探针 `_scratch\_csbake\probe_shader_blend.cs`（走 MCP，`tools\bake_cs\mcp_exec.py`）：
自建 quad + 1×1 贴图 + 顶点色 + 已知背景，**渲染一个像素读回来**，
对 6 个 shader × 3 种顶点色 × 6 种 texel = 108 组取样。
工程是 **Gamma 空间**（探针第一行就报出来），所以数值不需要线性/伽马换算。

### 26.2 量出来的公式（bg=0.5，`i.color` = 顶点色/渲染器色，`tex` = 贴图）

| shader（fileID） | **实测合成** | 转换器原映射 | 判定 |
| --- | --- | --- | --- |
| `Sprites/Default`（10753） | `out = src.rgb·src.a + dst·(1−src.a)`，`src.rgb = i.color.rgb·tex.rgb`，`src.a = i.color.a·tex.a` | 槽位颜色 = `i.color·_Color`、图集直通、`blend=normal` | ✅ 等价 |
| `Particles/Alpha Blended`（203） | 与 `Sprites/Default` **逐位一致** | 同 | ✅ 等价 |
| `Legacy Shaders/Particles/Additive`（200） | `out = dst + src.rgb·src.a`，`src.rgb = 2·i.color.rgb·_TintColor.rgb·tex.rgb`，`src.a = 2·i.color.a·_TintColor.a·tex.a` | 槽位 rgb = `i.color·4·_TintColor.rgb·_TintColor.a`；该区域按 `tex.a` 预乘；`blend=additive`(ONE/ONE) | ✅ 等价 |
| `Mobile/Particles/Additive`（10720） | 与 200 **逐位一致** | 同 | ✅ 等价 |
| `Legacy Shaders/Particles/Multiply`（205） | **`out = dst·(1 − src.a·(1−m0))`**，`m0 = 2·i.color.rgb·_TintColor.rgb·tex.rgb`（**逐通道**），`src.a = 2·i.color.a·_TintColor.a·tex.a` | ✗ 原来只烘 `α = 1−m0`（漏掉 `src.a` 调制） | ❌→✅ 本轮已修 |
| `Standard`（46） | 不透明（无 alpha 混合、受光照） | 当 `normal`（alpha 混合） | ⚠️ 仅 `BR_Andvari_NS2` 用到，件本身 α=1 时等价；待单独核 |

`_TintColor` 没写在 `.mat` 里时用 shader 内建默认 `(0.5,0.5,0.5,0.5)` ⇒
乘法的 `m0 = tex.rgb`、加色的增益 = 1 ✓（实测正是如此）。

### 26.3 乘法错的根因：**alpha 是"乘暗强度"的调制**

```
out.rgb = dst.rgb × (1 − src.a·(1 − m0))
```

* `src.a = 0` ⇒ **什么都不改**（贴着看就是"没影子"）；
* `src.a` 小 ⇒ 影子淡（这就是"略透明的影子"的由来）；
* `src.a = 1` ⇒ 退化成纯乘法 `dst×m0`。

实测样例（`Probe` 原始数据）：`i.color=(0.5,0.5,0.5,0.5)`、`tex=(0.2,0.4,0.6,1)`：
`m0 = (0.1,0.2,0.3)`、`src.a = 0.5` ⇒ 预测 `out = 0.5×(1−0.5×(0.9,0.8,0.7)) = (0.275,0.300,0.325)`，
**实测 (0.275, 0.298, 0.325)** ✓。

上一版把 texel 烘成 `rgb=0, α=1−m0` ⇒
**贴图透明/半透的地方也被当成实心暗块**：Alice 的影子贴图（浅粉 + α≈0.17）变成"多边形淡影"、
May_NS3 的胸影（`tex.a` 均值只有 0.17）从"淡影"变成"整块胸发黑"、Shirayuri 脸上黑块。

**修法**（`apply_multiply_policy` + `_bake_px`）：

```
槽位颜色 = 000000 + i.color.a（保留它自己的 alpha 时间轴）
texel   := rgb = 0， α = clip(2·_TintColor.a · tex.a · (1 − m0))     # m0 三通道取均值灰化
```

这样"运行时结果 = 槽位α(t)·texelα = src.a(t)·(1−m0)"，与实测公式**逐项对齐**。
样例（Alice 三个影子，`_TintColor` 用内建默认 ⇒ α 倍率 = 1）：烘出来的 α
`max 221 → 34`、`均值 44 → 6.8`，和"略透明影子"对上了；
May_NS3 胸影 α `均值 78 → 13.2`（max 245 → 91）；Shirayuri 三个影子 0/113/31.6；DrM 腿影 0/56/6.0。

### 26.4 加色一侧：**错在查看器**，不在产物

加色的映射本身是对的（表里 ✅），但 `D:\VB\Viewer\Render\v4\renderer_src\SpineRender.py`
的 `_drawSkeleton()` 只给 `blend==2`（multiply）换了混合函数，
`blend==1`（additive）**还在用普通混合** —— 而加色区域的贴图已经按 `tex.a` 预乘过，
用普通混合画就会发暗/糊（用户看到的 Daphne、Scathy "面板看不清"）。

已修：`blend==1 → (ONE, ONE)`，`blend==2 → (DST_COLOR, ONE_MINUS_SRC_ALPHA)`，
其余段沿用全局混合，画完恢复。

**26.4b（用户确认"我这侧 `shader_type=1` 不是 PMA"后补的第二处）**：
加色的映射原本把 `i.color.a` 留在**槽位颜色的 alpha** 上，指望运行时（PMA 约定）把它
乘进 rgb。查看器不是 PMA ⇒ 那部分丢了：Alice 的加色件槽位色 `ff7e7e57`
（`i.color.a=0.34`）会**亮约 3 倍**（就是用户看到的胸/腹两块亮斑，Daphne 233 件同理）。

**修法**：把 `i.color.a` 直接折进槽位 **rgb**（`ff7e7e57 → 572b2bff`），alpha 固定 1；
对应的"alpha 淡入淡出"从 alpha 通道搬到 **rgb 通道**（`color_timeline(fade_rgb_alpha=…)`，
`rgb(t) = rgb0·a(t)/a0`）——这样 PMA / 非 PMA 两种运行时都对。

### 26.4c 两条排除掉的假设（都查过了）

* **skinned 件的顶点色**：工程里 5701 个 mesh 资源含 `m_Vertices`，**含 `m_Colors` 的 0 个**
  ⇒ 这些网格没有逐顶点色，`i.color` 就是白色 ✓ 我们的假设成立（"黑块"不是这里来的）。
* **伽马误差**：工程 `PlayerSettings.colorSpace = Gamma`（探针第一行打印），
  查看器的 GL 也**没有任何 sRGB 处理**（`renderer_src` 里 grep 不到 sRGB/gamma）⇒
  两边都在 gamma 空间做混合，我们的 8bit 烘焙算术与之一致，**没有伽马换算误差**。
  （`sRGBTexture:1` 在 Gamma 工程里不触发转换；贴图的 `alphaIsTransparency:1` 只会把颜色
  扩到 α=0 的区域，而那些区域在乘法里被 `src.a` 项归零，影响可忽略。）

### 26.5 代表角色（每个 shader 一个，改完给用户肉眼过）

| shader | 代表 | 备注 |
| --- | --- | --- |
| `Particles/Multiply`（205） | `2DModel_3P_Alice_NS1`（sprite 影子）、`2DModel_BR_May_NS3`（skinned 影子） | 用户点名 |
| `Particles/Multiply` 其它 | `2DModel_BR_Shirayuri_NS1`、`2DModel_BR_DrM_NS1` | 用户点名 |
| `Particles/Additive`（200） | `2DModel_3P_Daphne_NS1`（233 件）、`2DModel_BR_Scathy_N`（39 件） | 用户点名 |
| `Mobile/Particles/Additive`（10720） | `2DModel_3P_Ran_NS1` | 唯一使用者 |
| `Sprites/Default` / `Alpha Blended` | 其余角色 | 逻辑本就不变 |

---

## 27 2026-10-10（算法线）：IK 验证干净 + DynamicBone **末粒子方向**真 bug 已修

用户指令：**"先不管 shader，继续修算法"**（按约束 30：算法/运动/骨骼必须与 Unity 真值对）。

### 27.1 用的手段（都可复用）

| 工具 | 干什么 |
| --- | --- |
| `_scratch\_csbake\smrbones.txt` + `dump_smr_bones.cs` | 计划文件换角色即可：逐帧导出**指定部件**的渲染器 TRS + 每根骨的世界/局部 TRS（走 MCP） |
| `_scratch\_csbake\t_smr_bones.py` | 转换器回放同样帧数，逐骨比 **local TRS**（世界量在带剪切的层级下不可比） |
| `_scratch\_csbake\t_db_frame_err.py` | 某根骨的误差**随帧**形态（突变 = 事件/夹紧；渐变 = 系统差） |
| `_scratch\_csbake\cmp_db_tree.py` | Unity 的 **DynamicBone 粒子树**（`m_Transform` 名 + `m_ParentIndex`）vs 移植版逐名 diff |
| `_scratch\_csbake\cmp_db_step0.py` | 逐步对拍：Unity dump 的 `pos/prev/target/n` vs 移植版 |
| `dump_db_particles.cs`（本轮加字段） | 现在还会导出**粒子名 + 父索引**，可以直接 diff 粒子树 |

### 27.2 `BR_RoyalArsenal_NS1`（用户报"右腿像镜像翻转"）—— **算法是干净的**

该 rig 有 **4 个 Puppet2D_IKHandle**（Foot_L / Foot_R / Hand_L / Hand_R）+ 46 处零缩放退化节点。
整段 `Lobby`（8s、240 帧@30fps）逐帧对拍腿的蒙皮件
（`parts_019_R_Thigh` / `parts_017_R_Calf` / `parts_018_R_Foot` / L 侧同理）：

```
[0..4] SELF(local) 0.000 px / 0.0000°
       全部腿骨    0.000 px / 0.0000°     ← 整段 0，连一帧都没偏
```

⇒ **"右腿镜像"不在 CS/IK 求解里**（IK 的 Flip / 零缩放退化都对），要往"翻转/写出"那条线查
（sprite/mesh 的 `m_FlipX`、负缩放、UV 朝向）。这一条从"算法待办"改判为"写出/翻转待办"。

### 27.3 `BR_PXSilky_NS1`（用户报"胸口运动很奇怪"）—— 抓到并修掉一个真 bug

先看结构：3 条链 **都是分叉树**（`Bone_Breast_Dynamic` → L/R + cloth；`Bone_Hair_Dynamic`
→ 12 个分支；`Bone_Jacket_Dynamic` → 4 个分支），并且 **Hair/Jacket 带 `m_EndLength=0.5`**、
Breast 带 `m_Exclusions=3`。

对拍结果（改前）：

```
Hair_BR 链  最大 566 px / 169°  (f=9)      ← 用户看到的"头发乱飞"
Jacket 链   最大 267 px                   ← 外套
Breast      位置 0.046px（小），但旋转差 136°
```

而且**误差 f=0 就有 35px** ⇒ 不是数值漂移，是**建链/初值**问题。
逐名 diff 粒子树：**名序列与父索引完全一致**（30 / 5 / 19 三条全对）⇒ 不是树结构。
逐步对拍才看出真凶：**末粒子（end）的位置错了**——

```csharp
// 游戏源码 Assets\Raw\Scripts\DynamicBone.cs L262~278
if (m_EndLength > 0f) {
    Transform parent = transform.parent;
    m_EndOffset = transform.InverseTransformPoint(transform.position*2f - parent.position) * m_EndLength;
} else {
    m_EndOffset = transform.InverseTransformPoint(base.transform.TransformDirection(m_EndOffset) + transform.position);
}
m_Position = m_PrevPosition = transform.TransformPoint(m_EndOffset);
```

* `m_EndLength > 0`：末粒子要**沿链继续往外**（`pos*2 − parentPos` 那个镜像点）× `m_EndLength`；
  我们原来写成"骨头局部 +X × endLength" —— 对 +X 朝上的 rig 会把末粒子甩到骨头上方 100~400px。
* `m_EndLength == 0`：方向要用 **DB 组件自己的 transform**（`base.transform`）旋转，不是骨头的。

已按源码改写 `cs_runtime.DynamicBone._append`（并 `mat4_invert_tolerant` 兜底奇异矩阵）。
效果（同一次对拍）：

```
末粒子位置    73 px → 1.9 px
parts_Hair_F 那两件：8.37 px → 0.040 px（多条骨从 3.7~8.4px 掉到 0.02~0.04px）
```

### 27.4 还没修完的（下一步，按这个顺序）

1. **链根的 22~30px 建立姿态差**（改前就有，不是我这次引入的）：`Bone_Hair_Dynamic` 本身
   f=0 就差 22px，往下分支递减 ⇒ 多半在"链根以上的层级/rest 姿态"（该角色有 1 个
   `同名孪生节点` 不绑曲线）。先把 setup 前的 rest 世界矩阵和 Unity 逐个比。
2. **Hair 的 BL/BR 分支、Jacket 链在中段仍偏**（138~560px，旋转也大）：
   树和末粒子都对上了 ⇒ 嫌疑落在**每粒子参数**（`m_*Distrib` 曲线按 `bone_len/bone_total`
   采样）或**多子节点时的 `ApplyParticlesToTransforms` 分支**。
   现成手段：`cmp_db_step0.py` 比输入（target/n），`t_db_frame_err.py` 看形态。
3. **`BR_RoyalArsenal_NS1` 的"镜像"**：转"写出/翻转"线（IK 已证清白）。

### 27.5 本轮又修掉/查清的四件事（2026-10-10 追加）

1. **`ApplyParticlesToTransforms` 的判据写错了**（真 bug，虽然对当前这个 rig 恰好无影响）：
   源码 `Assets\Raw\Scripts\DynamicBone.cs` L579 判的是
   `particle2.m_Transform.**childCount** <= 1`（**Transform 的子节点数，含渲染件**），
   我们写的是"粒子链里的子粒子数（`pchild`）"。单链 rig 两者都=1（所以 Alice/Alexandra 没暴露），
   骨头下面挂渲染件时才会相反。已按源码改成 `len(self._children[p2.tf])`。
2. **逐粒子参数完全一致**（新探针把 Unity 的 `m_BoneLength/m_Damping/m_Elasticity/
   m_Stiffness/m_Inert` 也 dump 出来）：30 个粒子 **0 处不同**；
   `m_BoneTotalLength` 也逐链一致（0.3387 / 0.2151 / 1.3312）——这是对 27.3 那个
   末粒子修复的**独立验证**（末粒子长度一旦错，boneTotal 立刻会差）。
3. **建链姿态（SetupParticles 的姿态）是"真值口径"的第一嫌疑**，而且 dump 目前**没有
   记录它**：`dump_db_particles.cs` 写的是"跑完第 0 帧之后"的粒子状态（已经过了一步），
   所以拿它当"建链初值"比是**错位一格**的。同一个角色，用三种建链姿态比出来的数字：

   ```
   在 prefab rest 姿态建链      → Hair_BR 559 px / Jacket 267 px
   在 clip t=0 姿态建链         → 848 / 1443 px
   在 Animator 默认状态(Start)t=0 建链 → 与上面几乎相同（说明这两种采样姿态对该 rig 差别不大）
   ```

   ⇒ **这些数字在建链姿态钉死之前不能作为"算法错"的证据**。
   下一步（工具侧）：让 dump 在 `SetupParticles()` **之后、第一次 step 之前**写一帧，
   并把每个粒子的 `m_Position` 与当时骨骼的世界位置一起记下来，这样"建链姿态"就从数据里
   直接读得出来，不用猜。
4. **转换器侧的建链姿态是"按设计"的**：`static_prefab_spine` 选 setup clip 的规则是
   "优先 lobby、排除 start/tep/breast"（§2476），也就是"角色从该 clip 开头起播"这个物理口径；
   和 Unity 运行时"先播 Animator 默认状态"本来就可能不同 —— 这正是 §16 记的
   "启动瞬态口径差异"。**这一点不是本轮要改的东西**，但要写清楚，别把它当 bug 追。

### 27.6 本轮修掉的三个真 bug（都按源码逐行核对 + Unity 实测验证）

| # | 位置 | 错在哪 | 验证 |
| --- | --- | --- | --- |
| ① | `DynamicBone._append`（末粒子） | `m_EndOffset` 的方向/长度：源码是 `InverseTransformPoint(pos*2 − parentPos) * m_EndLength`（**沿链继续往外**） | 建链位置逐粒子 **0.000 px**（三条链、含全部 end 粒子） |
| ② | `DynamicBone._apply` | 判据应是 `particle2.m_Transform.**childCount** <= 1`（Transform 子节点数，**含渲染件**），不是"粒子链子粒子数" | 本 rig 恰好等价；其它 rig（骨头下挂渲染件）会相反 |
| ③ | `DynamicBone._update2` / `_skip`（末粒子骨长） | 源码用 `localToWorldMatrix.**MultiplyVector**(m_EndOffset)`（**含缩放**），我们用了 `_mat_dir`（= `TransformDirection`，只取旋转）⇒ `n` 大 1/缩放≈7.5 倍 | 第一步后逐粒子 **0.00 px / 30 个**（修前最大 656 px、12 个 >1px） |

> ⚠️ 注意 ③ 的坑：`_apply` 里那个 `TransformDirection` **不能**顺手也改成 `MultiplyVector`
> —— 源码在 `_apply` 用的确实是 `TransformDirection`（只取旋转）。同一个名字在两条路径上
> 语义不同，照抄时要逐个核对。

### 27.7 新线索（下一步）：**旋转**这条线

第 ①③ 修完后，粒子/位置已经对齐（第一步 0.00px），但**骨头旋转**仍有差。
在 `parts_Hair_BR` 渲染器上 f=0 逐骨比：

```
Bone_Hair_set       位置差 0.000 px   世界旋转差  7.401°   ← ★ 它**不在 DB 管辖里**！
Bone_Hair_BR_01     位置差 0.001 px   局部 2.707° / 世界 4.680°
Bone_Hair_BR_02     位置差 4.864 px   局部 26.289° / 世界 43.771°
Bone_Hair_BRR_02    位置差 34.235 px  局部 54.255° / 世界 17.263°
```

`Bone_Hair_set` 是 DynamicBone 链根（`Bone_Hair_Dynamic`）**之上**的节点，DB 改不到它
⇒ 这 7.4° 只能来自**采样/层级**（该角色正好有 1 个"同名孪生节点按 Unity 规则不绑曲线"）。
下一步：把这个孪生节点的两条路径（Unity 里绑哪一条、我们绑哪一条）逐条打印对拍，
再决定是 `dedupe_anim_paths` 的规则问题还是 rest 姿态问题。

### 27.8 §27.7 的后续：**采样已排除**，旋转差收敛到 `_apply`

给 `dump_smr_bones.cs` 加了 `nocs=1`（只采 Animator、**不跑任何 CS**），
拿它和转换器的"纯 clip 采样"逐骨比（`pxsilky_smr_pureclip.json`）：

```
全部骨头：0.000 px / 0.0000°   ⇒ **采样（含孪生节点规则）完全正确**
```

顺带纠正一个我自己踩的口径坑：`diag_first_bad_bone.py` 里"纯clip"那一列是拿
*跑过 CS 的真值* 比 *没跑 CS 的我们* —— 那 148px/877px 全是错位，**不是发现**。

同时确认：`Runtime.set_world(quat=)` 里用的**已经是 Unity 的公式**
（`localRot = inverse(父级世界旋转) × 目标世界旋转`，纯四元数、不看父级缩放/剪切），
`_apply` 的调用顺序（i=1..n、先转父再写子位置）也与源码一致。

⇒ 剩下的旋转差（f=0 就有 2.7~54°）**只可能在"给哪些骨头写了旋转、写了多少"这一层**。
下一步（抓手已备好）：
1. 在 Unity 侧插一个探针：**在 `ApplyParticlesToTransforms()` 里逐个粒子**打印
   `p2.m_Transform.name / childCount / quaternion(前后) `，看它到底转了哪些骨、转了多少；
2. 在我们 `_apply` 里打同样的日志，逐行对；
3. 差异只会落在三处之一：**判据**（`childCount`）、**from/to 向量**（`TransformDirection(localPosition)` vs `p.pos−p2.pos`）、
   或**父级非均匀缩放下 `rotation` 的语义**。

---

## 28 2026-10-11：`Transform.rotation` 语义搞错了 —— 四元数链 vs 矩阵分解（**通用修复**）

### 28.1 怎么定位到的

27.6 修完三个 DB bug 后，**粒子位置**已经逐粒子 0.00px，但**骨头的旋转**还差
（f=0 就有 2.7~54°，整段最大 77.9°）。按顺序排除了三件事：

| 排除项 | 证据 |
| --- | --- |
| **采样**（含"同名孪生节点不绑曲线"规则） | 新加 `dump_smr_bones.cs` 的 `nocs=1`（只采 Animator、不跑 CS）→ 与转换器"纯采样"逐骨 **0.000 px / 0.0000°** |
| **`_apply` 的判据** | 新探针 `probe_childcount.cs` 打印 Unity 的 `transform.childCount`（含渲染件）→ 与我们解析的 `_children` **逐骨一致**（含 `cc=0` 的 `Bone_Hair_BL_02`、`cc=3` 的 `Bone_Breast_Dynamic`） |
| **写旋转的方式** | 我们的 `set_world(quat=)` 已经是 Unity 的公式 `localRot = inverse(父级世界旋转) × 目标` |

⇒ 只剩一种可能：**"父级世界旋转"这个量本身取错了**。

### 28.2 量出来（`_scratch\_csbake\probe_quat_from_matrix.cs`）

造"非均匀缩放父级 + 已知子旋转"，每组打印 `子 transform.rotation` 与 `子 worldMatrix.rotation`：

```
parRot=(23,-41,67)  子 localRotation=(11,29,-53)
  scale=(0.1285, 0.1285, 0.00127)   tf.rot=(-0.0227991,-0.1704293,0.1330526,0.9760795)
  scale=(0.00477,0.12501,0.12849)   tf.rot=(-0.0227991,-0.1704293,0.1330526,0.9760795)  ← 逐位相同
  scale=(0.06524,0.12746,0.06557)   tf.rot=(-0.0227991,-0.1704293,0.1330526,0.9760795)  ← 逐位相同
  scale=(1,1,1)                     tf.rot=(-0.0227991,-0.1704293,0.1330526,0.9760795)  ← 逐位相同
  而 Matrix4x4.rotation 在非均匀缩放上分别偏到 (-0.0542,-0.1022,0.1416,0.9831) 等
```

**结论**：

* `Transform.rotation` = **四元数链** `parent.rotation × localRotation`，**与父级缩放/剪切无关**；
* `Matrix4x4.rotation`（= 从世界矩阵分解）**不等**于 `Transform.rotation`（非均匀缩放下差很多）。

我们原来 `Runtime.quat()` 用的就是 `mat4_quat(world)`（矩阵分解）✗ ——
而这些 rig 到处都是非均匀缩放（`Size_root` 的 Z 缩放只有 0.00127），
实测这个量最多偏 **85.7°**，于是 `_apply` 的 `inverse(父旋转)` 全错、整条链歪掉。

### 28.3 改法

`Runtime.world_rot(tfid)`：沿父链把 **local 四元数**乘起来（`parent_rot × local_rot`），
最后归一 —— 这就是 Unity 的 `Transform.rotation`。用它替换三处：

1. `Runtime.quat(tfid)`（世界旋转 getter，IK / DynamicBone `_apply` 都读它）；
2. `set_world(quat=...)` 里算局部旋转用的"父级世界旋转"；
3. 两处 `TransformDirection`：DB `_update1` 的 `m_LocalGravity`、`_apply` 的
   `TransformDirection(子的 localPosition)`（原来走 `_mat_dir(世界矩阵)` ✗）。

局部矩阵仍按 `T·R·S` 走（局部没有剪切，`mat4_quat(local)` 是对的）；
`Matrix4x4` 本身（含剪切）**不改** —— Unity 的世界矩阵也确实带剪切。

### 28.4 验证

| 用例 | 修前 | 修后 |
| --- | --- | --- |
| PXSilky Hair 链（整段 224 帧） | 559.761 px / 77.9° | **0.070 px / 0.0000°** |
| PXSilky Jacket 链 | 267.611 px | **0.081 px / 0.03°** |
| PXSilky Breast / Pelvis / Spine / Head | — | ≤ 0.001 px |
| **回归**：RoyalArsenal IK（整段） | 0.000 / 0.0000° | **0.000 / 0.0000°** ✓ |
| **回归**：Alice DB 逐粒子（481 帧） | ~1e-7 世界单位 | **~1e-7**（≈0.0001px）✓ |

### 28.5 影响面（重要）

这条是**通用**修复：凡是"读 `transform.rotation` / `TransformDirection`"的 CS 代码，
在带剪切（非均匀缩放）的层级上都会偏 —— 而这批 rig **几乎全部**都是
`Size_root` 带 0.001~0.13 的非均匀缩放。
⇒ **157 个产物需要全量重转**（已先重转用户点名的 B 类角色给他看，随后跑全量）。

---

## 29 2026-10-11：**多层 AnimatorController 的"状态配对"**（Ignis 的"多 Clip 挤一个状态"）

用户点名的 `2DModel_PECS_Ignis_NS1`（B6）症状："像多个 Clip 挤在一个状态、动作分离"。

### 29.1 先看清结构（新探针：`probe_animator_default.cs`，改成读 `animstack.txt`，可换角色）

```
Animator 数 = 9
  主控制器 2DModel_PECS_Ignis_NS1（2 层）
     Base Layer   weight=0  7 个状态   （lobbyStart / Lobby_Face_Off/On / Breast_Touch_* / Normal_Touch_*）
     Bresat_Layer weight=1 12 个状态   （Chain_{Lobby,Normal,Breast}_{2Side,1Side,NoChain} / Break / Fall）
  另外 8 个 Animator 都是 1 个 1.00s 的循环 FX
    Dragon_Fire_fx / hand_Fire_fx / arm_Line_fx / Arm_Line_before_fx（各自 weight=0）
```

产物侧：22 条动画（主体两层 19 个状态 + 3 个 FX clip），111 个部件里 **一个有 FX 的都没有**
（那些 FX 渲染件本来就"整段不可见"⇒ 没导出 ✓ 所以不是 FX 的账）。

### 29.2 真凶：叠层时一律用"层的**默认** clip"

旧逻辑（§2434-2463）：每条 entry 叠"其它层的默认 clip"。对 Ignis：

```
Ignis_Breast_Touch_FaceOff 叠 Bresat_Layer 的默认 Chain_Lobby_2Side   ← 摸胸动画里胸链在播 lounge 的链动作 ✗
Chain_* 那 12 条          → 因为它们自己就是 Bresat 层，另一个层(Base)权重=0 被跳过  ← 身体不动、只有链在飘 ✗
```

⇒ 两边都"动作分离"，正是用户看到的样子。

### 29.3 改法：**按名字词元配对**

对每条 entry，从"别的层"里挑一个**与本状态共享词元最多**的状态（lobby↔lobby、breast↔breast、
normal↔normal）；同分时优先取与本层默认同档的变体（`2Side`/`1Side`/`NoChain`/…）；
一个词元都共享不到时才回退到"层的默认 clip"（旧行为）。另外：
**权重≠1 的层只有在"真配上了"时才参与**（Ignis 的 Base Layer authoring weight=0，
运行时由 `Actor` 脚本设回 1，不能因为文件里写 0 就当它不存在）。

配对结果（脚本打印）：

```
lobbyStart / Ignis_Lobby_*        → Chain_Lobby_2Side
Ignis_Breast_Touch_FaceOff/FaceOn → Chain_Breast_2Side      ← 修前错配成 Chain_Lobby_2Side
Ignis_Normal_Touch_*              → Chain_Normal_2Side
反过来：Chain_Breast_2Side → Ignis_Breast_Touch_FaceOff（12 条链动画现在也带主体动作）
```

### 29.4 影响面

全工程 **229 个 controller 里 47 个是多层**（每层至少一个 weight=1）⇒ 这 **47 个角色**要重转
（清单：`_scratch\multilayer_chars_20261011.txt`，含 Ignis）。单层 controller 的角色不受影响。

> 注：用户说"Unity 好像也有些问题，不太靠谱" —— 在 Unity 编辑器里**只播一个状态**时，
> 另一层会停在它的默认状态，看起来同样是"动作分离"；**游戏运行时由 `Actor` 脚本成对切层**才正常。
> 所以这里按"成对"导出是对的：产物里每条动画 = 一对（主体 + 配对链）。

### 29.5 补上"完全不共享词元"的那一半（用户 2026-10-11 指定）

29.3 那版里"权重≠1 的层只有在**按名字真配上了**才参与"，于是**配不上就什么都不叠**。
典型反例（用户点名要修的正是这一类）：

```
2DModel_BR_RoyalArsenal_NS1  BG_start / BG_loop  → 与主体状态 Lobby/Tap_* 不共享词元
   修前：不叠 ⇒ 这两条动画里**身体不动**（只有背景和骨头在动）
   修后：叠 Base Layer 的**默认状态** Lobby ⇒ 身体按 Lobby 动

2DModel_3P_Alice_NS1  3P_Alice_NS1_curtain      → 同理，修后叠 Base Layer 的默认 Start
```

**改法**：把"没有共享词元 → 回退到**该层的默认状态 clip**"这条回退**对所有层生效**
（不再只对 weight=1 的层）。这正是**约束 15**（"非 Base Layer 的状态要带其它层的默认状态"）
的口径，也与当初录制路线验收 Alice `curtain` 时的 `layers=<其它层默认状态>` 完全一致
（那次 0.36px）。

判据顺序（固定）：① 别的层里挑**共享词元最多**的状态（同分优先同变体档）；
② 一个都配不上 → 用该层的**默认状态** clip；③ 该层连默认 clip 都解析不出来 → 不叠。

受影响角色仍是**多层 controller 的那 47 个**（清单同上），已用最终代码重转。

---

## 30 弹簧链"预跑到稳态"：点击动作第 0 帧的头发（2026-10-11）

### 30.1 现象与真值

用户报：`2DModel_3P_Alexandra_NS1` / `2Dmodel_BR_Tomoe_NS1` / `2DModel_PECS_Cerberus_NS1`
的**点击动作**（`Tep_1` / `breast`）里**头发很有问题**，而 idle（`lobby`）看不出问题。

真值口径（**必须按游戏里那样"先播 idle 再切过去"**）：

```
_scratch\_csbake\smrbones.txt :  state=lobby_tep   parts=parts_L_hair,parts_B_hair,parts_F_hair,parts_BR_hair
                                preroll=lobby:2.0      ← 先播 lobby 2s（推进 CS），再切到 Tep_1
_scratch\_csbake\dump_smr_bones.cs   → Unity 侧逐帧逐骨 local/world TRS
_scratch\_csbake\t_smr_bones.py      → 转换器同口径重放，逐骨比 local TRS
```

### 30.2 根因：弹簧链是**有状态的**，我们把它当无状态算了

* 游戏里点 `Tep_1`/`breast` 是**从 idle 切过去**的；切换那一刻 DynamicBone 链已经在
  idle 上跑到**稳态**。
* 转换器原来对**每条动画都从 rest 重新建链**（`SetupParticles`），并且**复用同一个 runtime**
  ⇒（a）每条动画的第 0 帧都是"刚建链"的瞬态；（b）上一条动画的粒子末态还会残留到下一条。

实测（Alexandra `Tep_1`，头发骨最大误差）：

| 口径 | 最大误差 |
| --- | --- |
| 无预跑（改前） | **37 ~ 60 px**（最大都在 `f=0`，"接手那一刻"） |
| 预跑 `lobby` 2s → 再切 `Tep_1` | **0.005 ~ 0.009 px** |

### 30.3 改法

`src\unity2spine\convert\cs_runtime.py`

* `snapshot_dynamics(drv)` / `restore_dynamics(drv, snap)`：存/复原粒子
  `pos`、`prev`、`object_*`、`time_acc`（**不**动骨头的 local/world，那些由逐帧采样给）。

`src\unity2spine\convert\static_prefab_spine.py`（CS 段）

* 建好 runtime 后按 **setup clip**（= `_static_info.setupClip`，本项目是 `lobby`）
  预跑 `U2S_CS_PREROLL` 秒（**默认 2.0，设 0 回退旧行为**）→ `_preroll_snap`；
* 之后每条动画（除第一条）在自己的 `f == 0` 处 `restore_dynamics(_drv, _preroll_snap)`
  ⇒ 每条动画都从"idle 稳态"起跑。

日志会打印 `[cs] 预跑 lobby 2.0s（120 帧）→ 弹簧链稳态快照`，可用它确认预跑生效。

### 30.4 影响面

**所有带 DynamicBone 的角色（87 个）**都要重转（`_scratch\cs_chars_20261011.txt`，90 个带 CS 的角色）。
不依赖 CS 的角色（无弹簧链）不受影响。

---

## 31 "嘴巴自动向上漂"：`±Infinity` 切线（常值段）被当成了插值段（2026-10-11）

### 31.1 现象

用户报：`2DModel_DS_KunoichiKaen_NS1` 的点击动作里**嘴巴会自动向上漂**（最多漂到鼻子），
idle 动作正常。这个角色**没有 DynamicBone/IK/Spline**（只有 `Actor`/`ActorPartsView`），
所以不是 §30 的弹簧瞬态，属"采样/写出"线（老 B4 假设：父控制缺失 / 换装层级）。

### 31.2 怎么定位到代码：先用 Play 真值，别用 `AnimationMode`

1. `U2SFrameDump`（挂到角色根上，`driveAnimator=true, animatorState=breast`，Play 5.2s）
   → `_refshot_u2s\kaen_breast_20261011_125058.jsonl`：每帧每子物体的
   `activeSelf/activeInHierarchy/渲染器enabled/世界 TRS/顶点`。
2. 对比 `Bone_Mouth_ETC` 相对 `Bone_Head` 的世界偏移（px）：

| t | Play 真值（真 Animator） | `PoseFrames`（`AnimationMode`，Animator 关） |
| --- | --- | --- |
| 0.5 | ( -8.8, -16.2) | ( -8.7, -18.3) |
| 1.0 | ( -1.2, -30.4) | ( -1.2, -30.4) |
| 2.0 | ( -2.7, **-30.3**) | ( -2.9, -28.9) |
| 3.0 | ( -3.1, **-30.3**) | ( -4.3, -21.3) |
| 4.0 | ( -2.7, **-30.3**) | ( -6.9, **-2.4**) |
| 4.5 | (-11.7, +8.8) | (-11.7, +8.7) |

**Play 在 1.0~4.2s 之间"冻住"不动，`AnimationMode` 却是一条平滑斜坡** —— 两个"Unity 真值"
自己就不一致。查 `.anim` 原文（`DS_KunoichiKaen_NS1_BreastTouch.anim`）：

```yaml
  # 段 m_PositionCurves, path: .../Bone_Head/Bone_Mouth_Root
  - time: 0.81666666
    value: {x: 0.052, y: -0.3, z: 0}
    outSlope: {x: Infinity, y: Infinity, z: 0}      # ← 常值段（编辑器 Constant 切线）
  - time: 4.2
    value: {x: 0.075, y: 0.038, z: 0}
```

**运行时（Mecanim）按"常值段"求值 = 保持不动 ✓；`AnimationMode` 逐帧采样却是插值。**
所以"运行时语义"才是游戏里的样子（也是用户眼里"Unity 的样子"）。

### 31.3 根因（代码级）

`src\unity2spine\unity\unity_anim2d.py` 里 `read_section` 的关键帧斜率解析：

```python
sm = re.search(r"^        " + key + r": \{(?:x: ([-0-9.eE]+))?,?...\}", kf, re.M)
```

`([-0-9.eE]+)` **匹配不到 `Infinity`** ⇒ 常值段的斜率被当成"没有斜率" ⇒
`ngui_anim.UnityAnimCurve.value_at()` 的**向量分支**（`pos/rot/euler/scale`）走的是
平滑 Hermite ⇒ **把"该停住的 3.4 秒"插成了一条斜线**。
（float 分支早就有 `isinf` 判据 —— 只有**向量曲线**这一支漏了。）

### 31.4 改法

* `unity_anim2d._slope_token()`：`Infinity`/`-Infinity` → `±inf`（新增，供 `_sl()` 用）。
* `ngui_anim.UnityAnimCurve.value_at()`：向量分支里，某个分量
  `inSlope/outSlope == ±inf` ⇒ **该分量取左键值**（常值段），不做 Hermite。
* float 分支同步加 `_comp()` 兜底（防止传进来的是 dict）。

### 31.5 验证

* 转换器重放（`_scratch\_probe\kaen_replay_fixed.py`）：`Bone_Mouth_Root` 位置
  `0.9s→4.18s` **恒为 (0.052, -0.300)**，4.2s 跳到 `(0.075, 0.038)` ✓
  嘴骨相对头骨 = **-30.43px 保持**，4.2s 跳回 +8.86px —— 与 Play 真值（-30.3 / +8.8）一致。
* 产物侧（`_scratch\_probe\kaen_fix_verify2.py`）：重转后的 `Part_Mouth_AA` 顶点质心
  相对嘴骨的偏移在**每个时刻都是同一个常数**（-7.2, +13.6 px）⇒ 写出没有丢这段。
* 影响面：**62/757 个 clip、831 处**常值段 ⇒ **32/157 个角色**要重转
  （清单 `_scratch\redo_step_20261011.txt` + 主批次里尚未跑到的那几个）。

### 31.6 顺带纠正的一条"真值口径"（重要）

**`AnimationMode.SampleAnimationClip` 与运行时（Animator/打包后）在"常值段"上不一致**：
`info\Data\PoseFrames` 这类 `AnimationMode` 真值**会把常值段插值**。
所以：

* 判"常值段/显隐/位置保持"这类问题 → 用 **Play 逐帧真值**（`U2SFrameDump.cs`）；
* 用 `AnimationMode` 真值对拍时，先确认那条曲线**没有 `Infinity` 切线**，
  否则误差里混的是"真值工具自己的插值"，不是我们的 bug。

---

## 32 本轮（2026-10-11 第二轮）重转批次与 QC

三条修复（§29.5 多层配对回退、§30 弹簧链预跑、§31 常值切线段）落地后，用**最终代码**重转：

| 批次 | 范围 | 结果 | 日志 |
| --- | --- | --- | --- |
| 优先代表 | 9 个（Alexandra/Tomoe/Cerberus/Kaen/PXSilky/RoyalArsenal/LRL×3/Alice） | 9/9 OK | `_scratch\batch_cs_20261011_130033.log` |
| 主批次 | 90 个"带 CS"的角色（覆盖所有 DynamicBone/IK/Spline/GlobalControl 角色） | **89/90 OK**，1 个失败是**改代码时的瞬时窗口**（`Labiata_NS1`，已单独重转修好） | `_scratch\batch_cs_20261011_123716.log` |
| 补充批次 | 20 个"有常值段但不在主清单"的角色 | 20/20 OK | `_scratch\batch_cs_20261011_131122.log` |
| 收尾批次 | 13 个在主批次早期跑完、但早于我改解析器的角色（都**不含**常值段，纯为口径一致） | 见 `_scratch\batch_cs_20261011_152*.log` | — |

**QC**：三条批次日志里 **118 行**逐角色静态自检（`动画中引用但未导出 / 静态可见未导出 / 与真值可见性冲突 / 曲线 path 对不上`）
**全部为 0**（`_scratch\_probe\check_fresh.py` 复查"应重转的角色"里已无陈旧产物）。

**清单文件**

* 90 个带 CS 的角色：`_scratch\cs_chars_20261011.txt`
* 32 个含常值段的角色（扫描脚本 `_scratch\_probe\scan_step_chars2.py`）：`_scratch\redo_step_20261011.txt` + 主批次里尚未跑到的那些
* 复跑口径检查：`_scratch\_probe\check_fresh.py`

**交付包**：`D:\VB\Search\New\_Spine待检查_20261011_点击动作修复\`（10 个角色 + README，
重点是**点击动作的头发**与 **KunoichiKaen 的嘴巴**）。

**旧检查包**：`_Spine待检查_20261009`、`_20261010_乘法烘图集`、`_20261011_多层配对`、
`_20261011_算法修复代表` 已移出工作区（`D:\VB\Unity2Spine\delete\_旧检查包_20261011\`，可恢复）；
`_Spine待检查_20261010_代表shader` 保留（用户说过"先归档"）。

---

## 33 头发"还是不对"的真凶：逐 clip 动画的 DynamicBone 字段 + Play 真值链路的四个坑（2026-10-11 第三轮）

### 33.1 根因：clip 里**逐帧覆盖** DynamicBone 字段的曲线，我们整类没导出

`.anim` 的 `m_FloatCurves` 里有一批 `attribute: script_0x...` 的曲线，路径形如
`.../CTRL_Dynamic/Bone_Hair`、`.../Hair_set/bone_Hair/Hair` —— 它们在 Unity 里是
**AnimationClip 直接写在组件字段上**的曲线，运行时**每帧覆盖**组件平值。

字段名怎么定的：用"曲线终值 = 预制体字段值"交叉验证，四只角色逐条对上（`tools/U2S/导出 clip 绑定清单`
能打印绑定，但 Unity 给的自定义字段 propertyName 仍是哈希，所以值是唯一可靠判据）：

| attribute 哈希 | 字段 | 验证实例 |
| --- | --- | --- |
| `script_0xD1FC4FBF_kjIuPVN` | `m_Damping` | HongRyun Hair 0.07 / Breast 0.12 |
| `script_0x2DE5D16F_VWimMWJ` | `m_Elasticity` | HongRyun 0.02 / 0.05；Tomoe `hair_set` 0.01 |
| `script_0x5517B11B_UvNsJTL` | `m_Stiffness` | HongRyun 0.01 / 0.01 |
| `script_0xB255EB_NMQLlTJ` | `m_Inert` | HongRyun 0.01 / 0.05 |

**症状**：骨头级对拍（Play 真值）头发骨差 **0.557 世界单位 ≈ 478px**，
而身体/头/嘴都在 11~18px 内 ⇒ 不是蒙皮、就是弹簧参数。
典型：Cerberus `Hair` 被 clip 从预制体的 (0.05, 0.02) **整段改成 (0.1, 0.08)**；
Alexandra `Hair` 弹性 0.01→0.05→0.01（0.233s 抖一下）、`breast` 里是 0.1。

### 33.2 改法

* `unity_anim2d.parse_clip`：把 `script_*` 曲线收进 `clip["script"] = {路径: {attr: (keys, tans)}}`
  （**keys 必须是 `(time, value)` 成对** —— 只存时间会让 `unity_curve_eval` 抛
  TypeError，而调用方 try/except 一吞就"看着接上了、其实一条没生效"，本轮踩过）；
* `static_prefab_spine`：`SCRIPT_FIELD` 表 + `_wire_script(entry)`，按 **DB 所在物件路径**
  与曲线路径 `endswith` 配对，给每个 DB 挂 `anim_fields = {字段: t→值}`；
  预跑用 setup clip 的曲线、每条动画切自己的曲线；
* `cs_runtime.DynamicBone`：`apply_animated(t)`（值变了才 `_update_params()`），
  `step(rt, dt, t)` / `step_dynamics(..., t)` / `setup_dynamics(..., t)` 透传时间；
  求值异常**必须打日志**（不许静默）。

### 33.3 验证（同一条 Play 真值，改前 / 改后）

| 角色 | 部件 | 改前 最大/平均 (px) | 改后 最大/平均 (px) |
| --- | --- | --- | --- |
| Cerberus `Tep_1` | `parts_hair_RL_54` | **446.8 / 35.7** | **21.9 / 1.7** |
| Cerberus | `parts_Hair_F_52` | 161.4 / 13.5 | **13.8 / 1.0** |
| Cerberus | `parts_hair_LB_Rskirt_53` | 180.9 / 10.7 | **10.6 / 0.5** |
| Cerberus | 全局拟合 | \\|a\\|=0.99893 ∠-0.53° | \\|a\\|=0.999890 ∠0.0009° |
| Alexandra `Tep_1` | `parts_B_hair_23` | 264 / 66 | **195 / 27** |
| Alexandra | `parts_L_hair_08` | 91 / 17 | **40 / 4.5** |
| Alexandra | `parts_F_hair_40` | 53 / 8 | **44 / 2.9** |
| Alexandra | 头/脸 | 14 / 3.8 | **11 / 1.1** |

影响面（判据：**曲线值 ≠ 预制体字段值**，不要求"值随时间变"——Const 曲线也算）：
**44 个角色**（清单 `_scratch\redo_scriptfields3_20261011.txt`），已全量重转。

### 33.4 顺带：Play 真值链路的四个坑（都在 `Assets/Raw/Scripts/` 里修了）

| 坑 | 症状 | 修法 |
| --- | --- | --- |
| `BakeMesh(mesh, false)` + `TransformPoint` | 世界坐标整体小 ~10 倍（二次乘了 rig 根 lossyScale 0.101） | 改 `BakeMesh(mesh, **true**)`（与 `TwoDModelCalibExport` 同口径） |
| 网格 `isReadable=false`（AssetRipper 导入） | 读 `sharedMesh.vertices` **报错并打断整帧写入** ⇒ 7 条录制只剩 1 帧 | 先看 `isReadable`，不可读就 `Mesh.AcquireReadOnlyMeshData`；整帧写入再包 catch |
| 预跑用 `Time.time` | 进 Play 时加载一堆资源、`deltaTime` 被上限压住 ⇒ 2s 预跑拖成 21s | 预跑改 `Time.realtimeSinceStartup` |
| 自动收尾用"跑够 N 秒" | 固定步长时模拟时间比 realtime 慢 ⇒ **中途掐断**录制 | 改成"**所有 dumper 都不在录了**才退出"（+ hardCap 保险丝） |

另外：`U2SFrameDump` 新增 `vertexFilter`（只对这些名字录顶点，省体积）；
队列菜单 `Tools/U2S/按 playqueue 录 Play 逐帧真值` 现在**计划文件驱动**：
`prefab|state|prefix|seconds|vertexFilter|preroll`（如 `lobby:2.0`）。
注意：进 Play 会域重载，**编辑模式实例化的对象会被清掉** ⇒ 实例化必须在 Play 里做
（`U2SPlayQueueRuntime.Boot`）。

**还有一条**：`DynamicBone` 的弹簧对 `dt` 敏感，对拍时真值侧要
`Time.captureFramerate=60` 固定步长（本轮已加进队列）。

---

## 34 头发"还是不对"的第三轮：逐 clip 脚本字段 + 预跑时长 + Play 真值链路（2026-10-11/12）

### 34.1 已修并验证（都用 Unity **Play 运行时真值**逐帧校）

| # | 问题 | 根因 | 修法 | 验证 |
| --- | --- | --- | --- | --- |
| ① | 头发/胸/裙摆"软硬"在动画里不跟着变（Cerberus 头发像纸片） | clip 里 `attribute: script_0x...` 的曲线是**直接写在 DynamicBone 字段上**的动画（`.../CTRL_Dynamic/Bone_Hair` 这类路径），运行时**每帧覆盖**组件平值；转换器整类没导出 | 字段映射靠"曲线终值 = 预制体字段值"交叉验证：`0xD1FC4FBF→m_Damping`、`0x2DE5D16F→m_Elasticity`、`0x5517B11B→m_Stiffness`、`0xB255EB→m_Inert`；`parse_clip` 收 `clip["script"]`（keys 必须 `(time,value)` 成对）；`_wire_script()` 按路径 `endswith` 配对；`DynamicBone.apply_animated(t)` 每步改字段 | Cerberus `hair_RL` **446.8 → 21.9px**（平均 35.7→1.7）；Tomoe 平均 65.9→4.4px；LRL_N 190→14px |
| ② | 点击动作开头头发"跳一下"（idle 切过去的瞬态） | 弹簧链**有状态**：游戏里点动作时链已在 idle 跑到稳态；转换器每条动画都从 rest 建链 | 先按 setup clip **预跑**再拍快照，每条动画从快照起跑 | Alexandra `Tep_1` 头发骨 60.3 → 0.009px |
| ③ | 预跑时长不够（软链没到稳态） | Cerberus（弹性 0.08）2s 已稳；**Tomoe/LRL_N（弹性 0.01）2s 远未稳** | 默认改为 **6s**（`U2S_CS_PREROLL`，`0`=关；`U2S_CS_PREROLL_MAX` 上限） | 同一条真值下 Tomoe 平均 65.9→4.4px、LRL_N 190→14px；四只（Cerberus/Tomoe/LRL_N/Alexandra）头发**平均** 2.7/4.4/5.5/3.7px |

### 34.2 Play 真值链路的四个坑（都修了，脚本在工程 `Assets/Raw/Scripts/`）

| 坑 | 症状 | 修法 |
| --- | --- | --- |
| `BakeMesh(mesh,false)` + `TransformPoint` | 世界坐标整体小 ~10 倍（二次乘 rig 根 lossyScale 0.101） | 改 `BakeMesh(mesh, **true**)`（与 `TwoDModelCalibExport` 同口径） |
| 网格 `isReadable=false`（AssetRipper 导入） | 读 `sharedMesh.vertices` 报错并**打断整帧写入** ⇒ 7 条录制只剩 1 帧 | 先看 `isReadable`，不可读走 `Mesh.AcquireReadOnlyMeshData`；整帧写入再包 catch |
| 预跑用 `Time.time` | 进 Play 加载资源时 `deltaTime` 被上限压住 ⇒ 2s 预跑拖成 21s | 预跑改 `Time.realtimeSinceStartup` |
| 自动收尾用"跑够 N 秒" | 固定步长时模拟时间比 realtime 慢 ⇒ **中途掐断**录制 | 改成"**所有 dumper 都不在录**才退出"+hardCap |

另外：进 Play 会**域重载**，编辑模式实例化的对象会被清掉 ⇒ 实例化必须在 Play 里
（`[RuntimeInitializeOnLoadMethod]` + 标记文件）；弹簧对拍真值侧要 `Time.captureFramerate=60`。
`U2SFrameDump` 新增 `vertexFilter`（只对这些名字录顶点）与 `recordUvs`（查贴图镜像/串图）。

### 34.3 这一轮**排除掉**的假设（省得后面重复怀疑）

| 假设 | 实验 | 结果 |
| --- | --- | --- |
| 真值落后一帧（LateUpdate 帧序） | 产物时间平移 ±1 帧再比 | ✗ 中位误差 0 帧最好 |
| Python float64 vs Unity float32 累积 | `U2S_CS_F32=1`（粒子状态每步落 float32） | ✗ 结果逐位相同 |
| deform 关键帧 20fps 太粗、峰上插值差 | 有 CS 的角色改 60fps 网格重转 | ✗ 最大 52.7→50.3px（5%），体积 +29% ⇒ 已撤 |
| 纯 clip 采样不准 | 关掉 CS 只比 `bone_head` | ✗ 差 0.0032 单位（≈2.7px，且主要是拟合残差） |
| 腿"镜像翻转"（RoyalArsenal） | 腿/IK 骨 + **逐部件 UV 相关性** | ✗ 骨 0.0047 单位；corrU 全 +1.000（corrV −1.000 是 Spine/Unity 的 V 轴约定） |

### 34.4 还剩下的已知差距（**未修完，交接要点**）

Cerberus 这类**多分叉、极软**的发丝链，在**最快摆动的那几帧**仍差几十像素：

* 部件**质心**误差：中位 **0.46px**、最差 11px；
* **逐顶点**误差：中位 **3.0px**、p90 23px、最大 **50.7px**；
* 形态：误差与真值**速度**强相关（真值那根骨 1/20s 能走 **98px**、1/60s 走 25px），
  只有 5/181 帧 >8px ⇒ 是**沿链累积的小相位差**（每步约 0.1~0.5°），不是参数错/精度错/插值错。
* 下一步（已验证有效的方法）：用 `_scratch\_csbake\dump_db_particles.cs` 录**逐帧逐粒子**真值
  （当年 Alice 乳房 DB 就是这样对到 **0.0009px**），逐粒子比 `pos/prev`，定位第几个粒子开始分叉；
  注意 Alice 那条是**线性链**，Cerberus 是**6 分叉树**（`AppendParticles` 遍历顺序 +
  distrib 曲线参数 `t` 在树上的算法要单独核）。

### 34.5 本轮重转批次

| 批次 | 范围 | 结果 |
| --- | --- | --- |
| 90 个带 CS 的角色（含全部 44 个脚本字段角色） | 预跑 6s + 脚本字段 + 常值段 + 多层配对 + 乘法烘图集 | **90/90 OK**（`batch_cs_20261011_222119.log`） |
| 混合窗口回修 | 落在"60fps 网格"实验窗口里的 6 个 | 5/6 已回修（`batch_cs_20261012_083504.log`），第 6 个在跑 |

---

## 35 第四轮（2026-10-12）：把"真值帧率口径"和 dump 工具的坑钉死 ⇒ 弹簧复刻已逐粒子精确

### 35.1 起因

§34.4 还剩一条"多分叉极软发丝链在最快摆动那几帧差几十像素"（质心中位 0.46px、
逐顶点中位 3.0px、最大 50.7px）。用户要求"**至少小于 1**"。本轮把它一路查到根，
结论是：**转换器没有错，错的是"真值怎么录"和"dump 工具怎么跑"**。

### 35.2 发现①：Play 真值一直不是 1/60，而是**实帧率**（≈35fps，dt 0.008~0.097 随机）

`U2SFrameDump.Awake()` 里有 `if (fixedFramerate > 0) Time.captureFramerate = ...`，
而 `U2SPlayQueueRuntime.Run()` 是 `AddComponent` **之后**才 `Set(c, dumpT, "fixedFramerate", 60)` ——
`AddComponent` 会**立刻**跑 `Awake()`，所以字段读到的永远是默认值 **0**，
`Time.captureFramerate` 从来没有设上过。核验：历史 p6 真值的 `dt` 直方图
（`cerb_tep1_p6` 170 个不同值、0.0127~0.0966）。

**影响**：真值按实帧率推进弹簧，转换器按固定 `dt=1/60` 烘 —— 两者的**步数与相位**不同，
极软链在这种"时间离散化"上会累积成几十像素。

**决定性证据**：把**真值自己的 dt 序列**喂给转换器重放（`t_db_pre.py --usedt truth`），
Cerberus 头发骨的误差从 0.377 世界单位（323px）掉到 **1e-5（0.008px）**，
`t>2s` 之后逐位为 0。⇒ **积分器本身是对的，残差全来自 dt 口径。**

### 35.3 发现②：**不能**去固定 `Time.captureFramerate`（本工程 Animator 是 UnscaledTime）

顺着发现①去"修"录真值（真的把 `Time.captureFramerate=60` 设上）之后，真值**反而变差**：
所有 157 个 prefab 的 `Animator.m_UpdateMode = 2`（**UnscaledTime**）—— clip 播放跟的是
**真实时间**，不跟 `Time.deltaTime`。于是时间轴按 1/60 走、动画却按真实 ~11.8ms/帧走。

实测（`_scratch\_probe\t_timemap.py`，把每帧真值在纯 clip 采样的细网格上找"最贴时刻"）：

| 真值 | `bone_head` 最贴时刻 vs 录制时间 | 残差 |
| --- | --- | --- |
| 实帧率（`cerb_tep1_p6`） | Δ ≡ 0 | 0.00~0.28px |
| 固定 captureFramerate（`cerb_tep1_f60`） | **线性漂移到 −1.43s**（动画速率 0.709×） | 0.00~0.28px |

⇒ 第二种真值"时间轴和动画自相矛盾"，**不能用**。

**处理**：`U2SPlayQueueRuntime.Run()` 里显式 `Time.captureFramerate = 0` 并写明原因
（`Set(c, dumpT, "fixedFramerate", 0)`）；把上一轮"弹簧对拍要在真值侧固定
`Time.captureFramerate=60`"的说法**作废**（约束 36 最后一句已改）。
要"和转换器口径一致"就**在转换器侧按真值的 dt 序列推进**，不要去改真值。

### 35.4 发现③：`dump_db_particles.cs` 的 frames 循环**嵌在 per-db 循环里** —— 第 2 条链的"帧 0"其实已经跑了 150 步

这个坑最费时间，也最值得记住：

```csharp
for (int di = 0; di < dbs.Count; di++) {        // ← 按链
    ...
    for (int f = 0; f < nfr; f++) {             // ← 按帧
        restore();                              //   restore() 只复位 transform，
        ...                                     //   **不复位 m_Position**
        for (int i = 0; i < dbs.Count; i++) UpdateDynamicBones(dt);   // ← 每帧推进**所有**链
    }
}
```

⇒ 第 2 条链（Breast）的数据是在"已经被第 1 条链带着跑了 150 帧"之后才开始记的。

**假症状**：Alexandra `Breast` 链"帧 0 就差 28px、t=0.85 差 78px"，
看起来像一条全新的 bug（连 `target`、"父粒子位置"都对不上）。诊断过程中还顺带发现
`inTarget` 那一列本身也只是"更新前快照"，不等于 `UpdateParticles2` 真正用的 `vec`，
不能直接当判据。

**修法**：给 dump 加 `db=<名字>` 键，一次只跑一条链（`dbdump.txt` 里写）。

### 35.5 结论：弹簧链（树 / 参数 / 积分 / 输出）**逐粒子精确**

干净口径：`AnimationMode` 采样 + **固定 1/60** + 每次只跑一条链，
与 `cs_runtime` 用同一个 `rest` 建链、同样 1/60 推进。工具
`_scratch\_probe\t_db_particles.py`（逐粒子比 `pos/prev/骨位/target/n`，并按名字+父索引**校验整条树**）。

| 角色 | 链 | 粒子×帧 | pos 中位 | p99 | 最大 |
| --- | --- | --- | --- | --- | --- |
| Alexandra | `Hair`（28 粒子） | 28×150 | **4.8e-7（0.0004px）** | — | **3.4e-6（0.003px）** |
| Alexandra | `Breast`（6 粒子，三分叉） | 6×150 | **1.8e-7** | — | **2.1e-6（0.0018px）** |
| Cerberus | `Hair`（26 粒子，6 分叉极软） | 26×296 | **4.8e-7** | 1.8e-4（0.16px） | 3.3e-3（**2.8px**） |

（1 世界单位 ≈ 857.78 产物像素 ⇒ 想 <1px 要 <1.17e-3。）

* 树结构、逐粒子参数（`damp/elast/stiff/inert/boneLen`）、`boneTotal` 全部**逐项相同**；
* Cerberus 那条的分布与 §34.4 一致：**中位 0.0004px**，只有极少数帧（最快摆动处）
  到 2.8px —— 那是 float32 舍入噪声在被放大的位置，**不是公式错**；
* ⇒ §34.4 的"下一步：逐粒子对拍"**已完成**，且结论是**不需要再改转换器**。

### 35.6 那 Play 真值剩下的差怎么解释

两条真值口径差异，都与转换器无关：

1. **帧率**：真值按实帧率（≈35fps）推进弹簧，转换器按 1/60 烘。物理上这是
   "同一系统在不同步长下的两条不同轨迹"；产物是固定帧动画，按 1/60 烘是唯一自洽的做法。
   （给转换器喂真值的 dt ⇒ 1e-5。）
2. **指令前的链状态**：游戏在点击那一刻，链处在 idle 摇摆的**某个随机相位**；转换器统一用
   "setup clip（lobby）预跑 6s @1/60"（约束 33/37）。实测把预跑从 6.0s 改成
   6.0167 / 6.05 / 7.0 / 20.0，Alexandra 头发最大误差只在 **0.162~0.184** 之间游走
   ⇒ 这个残差**对初始相位不敏感**、是个稳定量，属于上面第 1 条的必然结果。

### 35.7 本轮新增/修正的工具

| 文件 | 用途 |
| --- | --- |
| `_scratch\_probe\t_db_particles.py` | **逐帧逐粒子**对拍（树校验 + `pos/prev/骨位/target/n` 五项 + 最差帧逐粒子明细）。这是判"弹簧对不对"的**首选工具** |
| `_scratch\_probe\t_db_pre.py` | Play 真值（`obj` 世界 TRS）对拍；带 `--usedt fixed|truth`、`--pre true|false`、`--fields on|off`、`--setup clip|lobby`、`--shift`、`--dbinfo`，专门用来 A/B 这些口径开关 |
| `_scratch\_probe\t_timemap.py` | 把真值的每一帧在"纯 clip 采样细网格"上找最贴时刻 ⇒ 一眼看出真值的**时间轴**对不对 |
| `_scratch\_csbake\dump_db_particles.cs` | **加了 `db=<名字>`**（只跑一条链）与 `clip=<名字>`（状态名≠clip 名时要写）；行尾多了 `driftSelf/driftPar` 两列诊断 |
| `_scratch\_csbake\trace_db.cs` | 逐步追踪 `m_Position[0]` 在"建链 → StartAnimationMode → 复位 → 采样 → GlobalControl → UpdateDynamicBones"各步的值，用来钉"到底谁改了粒子里程" |

Unity 侧改动（工程内 `Assets\Raw\Scripts\`）：

| 文件 | 改动 |
| --- | --- |
| `U2SPlayQueueRuntime.cs` | 显式 `Time.captureFramerate = 0`（**别再固定帧长**，原因见 §35.3）；`fixedFramerate` 传 0 |
| `U2SFrameDump.cs` | `Start()` 里加"字段被设过就兜一次"的保险（队列那边固定 0） |

### 35.8 复现命令

```powershell
cd D:\VB\Unity2Spine
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"

# ① 录逐帧逐粒子真值（先写 _scratch\_csbake\dbdump.txt：prefab/state/clip/fps/maxFrames/db/out）
python tools\bake_cs\mcp_exec.py _scratch\_csbake\dump_db_particles.cs

# ② 逐粒子对拍（树校验 + 五项误差 + 最差帧明细）
python _scratch\_probe\t_db_particles.py `
  --prefab "<工程>\Assets\Prefabs\2DModel_PECS_Cerberus_NS1.uAnim.prefab" `
  --assets "<工程>\Assets" `
  --dump "_scratch\_csbake\partdump\cerberus_db_hair.json"

# ③ Play 真值的口径 A/B（--usedt truth 才和真值的步长一致）
python _scratch\_probe\t_db_pre.py --play-base "<工程>\_refshot_u2s\cerb_tep1_p6_20261011_220551" `
  --prefab "<工程>\Assets\Prefabs\2DModel_PECS_Cerberus_NS1.uAnim.prefab" `
  --assets "<工程>\Assets" --state Tep_1 --bones Bone_hair --usedt truth --preroll "lobby:6.0"

# ④ 真值时间轴体检
python _scratch\_probe\t_timemap.py --play-base "<...>" --prefab "<...>" --assets "<...>" `
  --state Tep_1 --bone bone_head --grid 600
```

### 35.9 ⚠ 本轮新挖出来的**未结**疑点：`EventDynamicBone` 动画事件（下一轮的第一件事）

追 §35.5 的时候顺带挖到一条**可能影响"弹簧参数什么时候生效"**的线索，先记下来：

**事实 A：clip 里带 `EventDynamicBone` 动画事件，`data` 就是 DynamicBone 的名字。**

```
  m_Events:
  - time: 0.05        functionName: EventDynamicBone   data: Breast
  - time: 0.23333333  functionName: EventDynamicBone   data: Hair
```

（`3P_Alexandra_NS1__lobby_tep.anim` 的 `m_Events`；`objectReferenceParameter` 是 0
⇒ 事件发给"挂 Animator 的那个 GameObject"= `size_root`。）

全工程扫描：**244 个 clip、572 个事件**，`data` 取值就是我们 DB 的物件名
（`Hair` 91、`Breast` 39、`Bone_Hair` 33、`Hair_set` 27、`bone_hair_h` 25、
`Bone_Breast` 21、`Bone_LTail01` 8、`Bone_RTail01` 8…），触发时刻集中在
**0.0167~0.1667s**（开头一小段密集）。

这是 DynamicBone 的标准用法：`EventDynamicBone(string name)` 里按名字找到对应组件、
调 `UpdateParameters()`。**换句话说：clip 用"事件"告诉弹簧"现在把参数重新读一遍"**
—— 因为 `RefreshParam` 是 false（见事实 B），逐帧并不会自动刷。

**事实 B：本工程所有 DynamicBone 的 `RefreshParam` 都是 false**（`probe_db_fields.cs`
实测 Cerberus/Alexandra/Tomoe/Kaen/LRL_N 全 false），而反编译出来的
`DynamicBone.Update()` 里那句 `if (this.RefreshParam) this.UpdateParameters();`
是唯一会"逐帧刷新"的入口 ⇒ **理论上是"建链那一刻的值 + 事件时刻刷新"，不是逐帧刷新。**

**事实 C：但在导出的工程里这个事件的接收者丢了** —— 控制台报
`'size_root' AnimationEvent 'EventDynamicBone' ... has no receiver!`，所以导出的工程里
事件什么也不做；参数只可能是 `Start()→SetupParticles()` 那一刻读到的值。

**矛盾（为什么还没动手改）**：拿 Play 真值做 A/B（`t_db_pre.py --fields on|off`，
Alexandra `Tep_1`、头发骨 `Bone_B_hair5_03`）：

| 口径 | 中位 | 平均 | 最大 |
| --- | --- | --- | --- |
| `--fields on`（**逐帧**把 clip 的字段曲线刷进粒子，当前转换器的做法） | **0.0588** | **0.0679** | 0.1815 |
| `--fields off`（不刷，用预制体平值 = 事实 B/C 推出的"冻结"行为） | 0.1314 | 0.1263 | 0.1933 |

⇒ **实测是"逐帧刷新"更贴**，和事实 B/C 的推论相反。可能的原因（下一轮按这个顺序排）：

1. **`Start()` 的时机**：Unity 很可能是在**动画已经写过一次之后**才 `Start()`，所以
   `SetupParticles()` 读到的是 **clip 第 0 帧**的值（而不是预制体的值）。若如此，
   "正确口径"既不是"逐帧刷"也不是"预制体平值"，而是 **"clip 第 0 帧的值 +
   只在 `EventDynamicBone` 时刻刷"**。旁证：Alexandra `Breast` 的预制体
   `m_Damping=0.03`，而 clip 第 0 帧是 `0.05`。
2. Play 真值里 `EventDynamicBone` 也可能**有**接收者（那条警告只确认了
   `__lobby_start` 这一条），需要一条条核。**验证方法**：给真值侧的 `size_root` 挂一个
   `void EventDynamicBone(string)` 探针，记录"谁在什么时候触发了"（只改真值侧，不改产物）。
3. ~~别的脚本在逐帧刷参数~~（`Puppet2D_GlobalControl`/IK 里没找到）。

**建议的下一轮做法**（按顺序，别跳）：

1. 用 `probe_db_fields.cs` 把 157 个角色的 `RefreshParam` 扫一遍，确认是不是**全 false**；
2. 给 `unity_anim2d.parse_clip` 加 `m_Events` 解析（`time/functionName/data`），
   把 `EventDynamicBone(data)` 按名字配到对应的 DynamicBone 上；
3. 转换器里做三档 A/B（建议开关 `U2S_CS_DB_REFRESH=frame|event|off`）：
   `frame`（现状：每步前按曲线值刷）、`event`（只在 setup + 事件时刻刷，
   同时 A/B "建链值取 clip 第 0 帧还是预制体"）、`off`（完全不刷）；
   用 Play 真值（`t_db_pre.py --usedt truth`）在 Cerberus/Alexandra/Tomoe/Kaen 四只上
   比"头发部件质心 + 逐顶点"，取最贴的那一档当默认；
4. 定稿后只重转"含 `EventDynamicBone` 的 244 个 clip 覆盖到的角色"（先扫出清单）。

---

## 37 2026-10-12：用户报的"**Echidna 灯光和 Unity 不一致**"——查清了，**不是 shader**

### 37.1 先排除 shader（用户最初的怀疑）

Echidna（`2DModel_BR_Echidna_NS1`）全 prefab 只引用 4 个材质，**全部指向内建
`Sprites/Default`(10753)**。唯一"像 shader 问题"的地方是 `parts_Shadow` 的材质
`FullbodyIMG_BR_Echidna_NS1_Shadow.mat`：它的 `m_SavedProperties` 里留着
`_AdditionalAlpha / _BlendMode / _Src:2 / _Dst:10 / _AlphaTex / _EnableExternalAlpha /
_Flip / _RendererColor` —— **自定义 shader 的遗留属性**；而 clip 里
**唯一一条"材质属性"曲线就是 `material._AdditionalAlpha`**（绑在 `parts_Shadow` 上）：

| clip | 键值 |
| --- | --- |
| `BR_Echidna_NS1_Lobby` | 0→3.1:0→3.43:**0.627**→4.13:0.618→4.65:0→10.67:0 |
| `BR_Echidna_NS1_Tep_Breast` | 0→3.0:0→3.33:**0.4518**→3.88:0→4.88:**0.5138**→5.87:0 |
| `Lobby_Loop` / `Tep_Normal` | 恒 0 |

但**这条线是死的**：工程里那 4 个带 `_AdditionalAlpha` 的自定义 shader
（`Raw\assetbundleresource\lo_sprite_loby_cha_full3dmeshbase_oneside_addittional_alpha*.shader`）
**没有任何材质引用（0 个）**；221 个带 `_AdditionalAlpha` 属性的材质全部指向内建
（204×Sprites/Default、12×Multiply、5×Additive）。Play 真值也证实 Echidna 的
`parts_Shadow` 全程 `en=1, col=(1,1,1,1)`、`sort=Default:18` 不变。
⇒ **不导出它是对的**（`_static_info.json` 的 `unsupportedChannels` 早就这么记着）。

### 37.2 真凶：`parts_Bg_001_Skinned`（**灯光层**）几何差到 1303px

用 Play 真值 `_refshot_u2s\echidna_lobby_20261011_214752` 逐部件对拍
（`_scratch\_probe\cmp_play_hair.py`，36 个部件）：

| 部件 | 最大误差 |
| --- | --- |
| **`parts_Bg_001_Skinned`** | **1.787 世界单位（1303px）**，平均 637px |
| 其余 35 个 | ≤0.049（35px），大多 ~9px |

`parts_Bg_001_Skinned` 的蒙皮骨 = **`Bone_COM_Skinned/Bone_BG_Light_Skinned`**
（`parts_Bg_000` 是蒙到 `Bone_COM_Skinned` 的背景底，一直正常）⇒ **这就是"灯光"**。
误差随时间 9.7px(t=0) → **620px(t≥1.5)** → 235~625px 来回摆。

### 37.3 定位链（每一步都有实测）

1. **骨头本身没问题**：`t_db_paths.py --contains BG_Light`（**按完整路径**比）⇒ 0.0000。
2. **网格塌了**：产物里 `parts_Bg_001` 的 setup 顶点 15 个全挤在 **0.138×0.068 px** 的点上
   （兄弟件 `parts_Bg_000` 是 1814×1054 px）；源网格
   `Raw\Mesh\parts_Bg_001_Skinned.asset` 是**正常的 15 顶点**（x∈[−10.2,10.2]，
   躺在 XZ 平面，`weights=[]`、`boneIndexRaw=[(0,)]`、`bindposes=1`）。
3. **谁把顶点算塌的**：给 `convert_2dmodel._skin_mesh` 打桩 ⇒ 同一份输入，
   **有的调用输出跨度 1.89、有的 0.0002**；输出 0.0002 时
   **`世界矩阵列范数 = 9.25699e-06`**，正常是 `0.0925699` ⇒ **正好小 1e4 倍**（平移还是对的，
   所以"比骨头位置"那类检查发现不了）。
4. **再往里一层**：给 `_world_matrices` 打桩 ⇒ 退化那次 **`lv[Bone_BG_Light_Skinned]` 自己就是
   `diag = (1e-4, 1e-4, 1e-4)`**（其余 129 个节点全正常，父 `Bone_COM_Skinned` 也正常），
   而该节点在预制体/clip 里的 scale 都是 **1.0**。
5. **不是采样器**：直接 `assignments_for_entry` + 采样那个 `anim_path`
   （`Bone_COM_Skinned/Bone_BG_Light_Skinned`）⇒ **所有时刻 scale 都是 1.0**；
   Lobby clip 的 11 条 `m_ScaleCurves` 里也**没有**这条路径。
   （顺带确认：这批 `m_ScaleCurves` 是**向量格式** `value: {x:1,y:1,z:1}`，
   解析器读得对——`Bone_Mouth_Smile_Skinned`/`Bone_Eye_Close_Skinned` 真的被
   **缩到 0.0001 来隐藏面部件**。）
   ⇒ **1e-4 是在转换过程中被"写回" `lv` 的**，不是从数据里读来的。

### 37.4 结论与下一步

**结论**：某个 CS 写入（`Runtime.set_world` 之后 `_recompute` 重算子树的 local）在
**父矩阵退化/陈旧**的时刻，把 `Bone_BG_Light_Skinned` 的 local 算成了
**均匀 1e-4 缩放 + 180° Y 旋转**（平移不变）；`lv` 又是**就地改写**的那个 dict ⇒
后面每一帧的 `_world_matrices` 都用这个坏 local ⇒ 灯光网格塌成一个点，
真正的形状被塞进 deform 时间轴（0 ↔ −1004 来回跳）⇒ 用户看到"灯光和 Unity 不一致"。

**下一步（工具已备好）**：给 `Runtime.set_world` 打桩时**连子树一起查**
（`trace_bg001_setworld.py` 只查了被写的那个节点本身，漏了 `_recompute` 写进去的子孙），
打印"写完之后 `local[子孙]` 列范数 < 1e-3"的那次调用栈 ⇒ 直接点名是
spline / IK / DynamicBone `_apply` 里的哪一个。

---

## 36 第四轮（续，2026-10-12 下午）：真值 dt 序列 + `m_Events` + **`m_Enabled`（弹簧被关掉）**

§35.9 留下三个疑点，这一轮把事实全部钉下来了，并且**发现了一个真 bug**。

### 36.1 真值侧：把"每帧 dt 序列"也录下来（`<前缀>.dtseq.json`）

`U2SFrameDump` 新增 `recordDtSeq`（默认开）：从 `Start()` 起把**每帧的 `dt`**（**含预跑那
654 帧**）记成 `<前缀>.dtseq.json`（`{prerollFrames, recordedFrames, dt:[...]}`）。
`_scratch\_probe\t_db_pre.py` 新增 `--dtseq <文件>`：**预跑也按真值的 dt 序列推进**。

效果（Cerberus `Tep_1`，同一份真值）：最大误差从"**t≈1.2 处 0.070 且持续**"变成
"**只在 t=0 那一帧 0.0698、之后 ~1e-4**"（中位 0、平均 0.0025）⇒ 帧率混淆基本消掉。
**这是以后判"算法对不对"的标准做法。**

### 36.2 `RefreshParam` 全 false（确认）

87 个 prefab / **228 个 DynamicBone 组件**，`RefreshParam` **全部 = 0**。

### 36.3 clip 的 `m_Events` 已接进转换器（`U2S_CS_DB_REFRESH`）

`unity_anim2d.parse_clip` 现在解析 `m_Events` → `clip["events"] =
[{time, function, data}]`；`static_prefab_spine._wire_script` 把 `EventDynamicBone`/`EventReset*`
按 **`data` = DB 物件名** 配到对应链上（空 `data` = 全都刷）；`cs_runtime` 新增
`refresh_mode`：

| 档 | 行为 |
| --- | --- |
| `frame`（**默认，= 旧口径**） | 每步前按曲线当前值刷参数 |
| `event` | **只在 setup + 事件时刻**刷（Unity 里唯一会走 `UpdateParameters()` 的入口） |
| `off` | 从不刷（参数停在建链那一刻） |

实测（Alexandra `Tep_1`、头发骨，真值用 §36.1 的 dt 序列口径）：

| 口径 | 中位 | 平均 | 最大 |
| --- | --- | --- | --- |
| `frame` | 0.01897 | 0.0666 | 0.1799 |
| `event` | **0.01546** | **0.0618** | 0.1882 |
| `off` | 0.05796 | 0.1018 | 0.2006 |

⇒ `off` 明显错；`frame` / `event` 只差一点点（`event` 中位/平均略好、最大略差）。
Cerberus 上 `frame`/`event` **完全一致**（它那条曲线是常值段）。
**默认保持 `frame`**（产物不变）；`event` 留作实验档。

### 36.4 ★ 真 bug：clip 会把 **DynamicBone 组件自己关掉**（`m_Enabled` 曲线）

**事实**：clip 的 `m_FloatCurves` 里有一批曲线是
`attribute: m_Enabled` + **`classID: 114` + `script: {guid: 905d812f…}`**（= DynamicBone
脚本），路径正是 DB 的物件（`…/bone_Breast/Breast`、`…/hair/Hair`、`…/bone_Skirt_L/Skirt_L`）。
全工程 **327 条**：**62 条恒 0**（整条链被禁用）、**119 条 0/1 切换**。

**语义**（`DynamicBone.cs`）：

| 曲线 | 效果 |
| --- | --- |
| `m_Enabled = 0` | 组件被禁用 ⇒ `Update/LateUpdate` 不跑 ⇒ **弹簧不推进，骨头跟着动画走** |
| `0 → 1` | `OnEnable()→ResetParticlesPosition()` ⇒ **整条粒子链重置成那一刻的骨头位置**（并且首帧才跑 `Start()→SetupParticles()`，建链姿态=那一刻） |

**Play 实测确认**（新加的 `U2SFrameDump.recordDbState`，每帧记每个 DB 的
`enabled/粒子数`）—— Cerberus `Tep_1`：

```
db=[{'n':'Hair','en':1,'np':26}, {'n':'Breast','en':1,'np':7}, {'n':'Skirt_L','en':0,'np':12}]
```

⇒ Unity 里 `Skirt_L` **真的是关的**（链还在、但不跑）。而我们以前**一直在给这条链算物理**。

**修法**（`U2S_CS_DB_ENABLED`，默认 **1**；=0 退回旧行为）：
`unity_anim2d` 把这类曲线单独收进 `clip["enabled_db"]`（要求 classID 114 + 脚本 guid 同时命中，
避免和同路径渲染器的 `m_Enabled` 混淆）；`static_prefab_spine._wire_enabled()` 按路径配到链上；
`cs_runtime.DynamicBone.step()` 里：**禁用就 return（不推进、不 `_apply`）**；
若上一帧是禁用而这一帧启用，则先 `reset_particles(rt)`（= `ResetParticlesPosition`）再推进。
`snapshot/restore_dynamics` 也带上 `was_enabled`。

**受影响范围**（用产物 `_static_info.json` + clip 名单反查，
`_scratch\_probe\find_db_enabled_chars.py`）：

* **整条链被禁用**（至少一条 clip 里恒 0）：**17 个角色**，含
  `2DModel_PECS_Cerberus_NS1`（`Skirt_L` 在 lobby/Tep_1/breast/pose **全部**恒 0）、
  `3P_Daphne_NS1`、`BR_Khan_NS2`、`BR_Marie_N/NS1`、`BR_Miho_NS1`、`BR_Sleipnir_N`、
  `3P_BlackLilith_NS2`、`3P_CSPerrault_NS2`、`BR_Nereid_N`、`BR_Leprechaun_NS1` 等；
* **会 0→1 切换**（= 中途重置链）：**43 个角色**，绝大多数是 `Start` / `lobby_start`
  这类"开场"clip（典型 `[(0,0),(0.4167,1)]` 或 `[(0,0),(0.0167,1)]`）；
* 并集 **45 个角色** → 清单 `_scratch\db_enabled_union_20261012.txt`
  （细分：`db_disabled_chars_20261012.txt` / `db_flip_chars_20261012.txt`）。

**⚠ 待办**：这 45 个角色的产物是**旧口径**出来的，要按新口径重转
（`python tools\batch_cs_convert.py --exact-file _scratch\db_enabled_union_20261012.txt`）。
本轮只做了冒烟导出（Cerberus 一个角色，`_scratch\_probe\cerb_dben_check`）：
`[cs] Tep_1 DynamicBone 的 m_Enabled 曲线：3 条链`、`static_check 全 0` ✓。

### 36.5 ✅ "Cerberus 裙骨差 0.58" —— 两个原因，都已定位（2026-10-12 傍晚）

症状：同一个真值里 `Bone_skirt_R*` 精确到 0.006，而 `Bone_skrit_LF_*` 差 **0.58~0.62**
（≈530px），并且看起来"跟弹簧无关"（DB 接/不接、CS 跑/不跑四种组合一样）。

**原因①：对比工具按名字绑错了节点（假误差）。**
真值里有**两套同名裙骨子树**：

```
…/Skirt_set/Bone_skirt_L_set/bone_Skirt_L/Skirt_L/Bone_skrit_LF_*   ← Skirt_L 这个 DB 的链
…/Skirt_set/Bone_skirt_L_set_R/bone_Skirt_L/Skirt_L/Bone_skrit_LF_* ← 另一套（不在任何链里）
```

`t_db_pre.py` 的 `byname`（按**末段名字**配）会把这两套的 22 个同名节点都绑到同一根骨上 ⇒
两套互相对着比，误差自然大（0.58 里绝大部分是这个）。
**修法**：新写 `_scratch\_probe\t_db_paths.py`，**按完整路径**配（真值 `meta.json` 里有
`path`），逐节点、带层级缩进打印，同名兄弟也能分清。

**原因②：真正的误差 = "我们跑了 Unity 没跑的链"**（约束 44 那个 bug）。
按路径比之后（`Bone_skrit_LF` 那 22 个节点）：

| 节点 | 旧口径（链照跑） | 接上 `m_Enabled` 后 |
| --- | --- | --- |
| `Bone_skrit_LF_1_1` | 0.0149 | **0.0016** |
| `Bone_skrit_LF_2_2` | 0.0336 | **0.0009** |
| `Bone_skrit_LF_1_3` | 0.0648 | **0.0117** |
| `Bone_skrit_LF_2_3` | 0.0872 | **0.0087** |
| `Bone_skrit_LF_3_3` | 0.0686 | **0.0059** |
| 另一套（`_R`，本来不跑） | 0.0016 平 | 0.0016 平 |

⇒ 误差**沿链增长**（0.015→0.025→0.065，越靠链尾越大）正是"弹簧在跑 vs 不跑"的特征；
接上 `m_Enabled`（Unity 里这条链 `en=0`，见 §36.4 的 Play 实测）后 **≤75px → ≤10px**，
多数降到和"不跑的那套"一样的 1.4px 基线。残余 0.006~0.012（最深那几根）留作后续。

**教训**：judging 同名节点多的 rig（Puppet2D 经常有 "…_set" 与 "…_set_R" 两套）
**必须按路径比**，按名字比会造出假误差。

### 36.6 本轮新增/修正的工具与开关

| 东西 | 说明 |
| --- | --- |
| `U2SFrameDump.recordDtSeq` | 写 `<前缀>.dtseq.json`（每帧 dt，含预跑）——**判算法的标准口径** |
| `U2SFrameDump.recordDbState` | 每帧记每个 DynamicBone 的 `enabled/粒子数` —— 核"弹簧到底有没有在跑" |
| `t_db_pre.py --dtseq / --dbenabled / --fields frame|event|off` | 三个口径开关 |
| `_scratch\_probe\scan_db_enabled_all.py` | 全工程扫"绑在 DB 上的 `m_Enabled`"，分恒 0 / 会切换 |
| `_scratch\_probe\scan_enabled_curves.py` | 单 clip 看 `m_Enabled`/`m_IsActive` 的键值与是否绑在 DB 上 |
| `_scratch\_probe\find_db_enabled_chars.py` | 用产物账本反查受影响角色，写清单 |
| `_scratch\_probe\scan_db_events.py` | 看 `EventDynamicBone` 的 `data` 能不能配上 DB 物件名 |
| 转换器开关 | `U2S_CS_DB_ENABLED=1|0`（默认 **1**）、`U2S_CS_DB_REFRESH=frame|event|off`（默认 **frame**） |

### 37.5 再挖一层：多出来的第 4 个 state **`BR_Echidna_NS1_Lobby_Loop`**

给 `Runtime.step_dynamics` 打桩（进/出各量一次灯光骨的 local）⇒ **"进 step 之前就已经是
1e-4"**，时刻是 **t = 0.75, 2.25, 3.75, 5.25, 6.75, 8.25（每 1.5 秒一次）**；
也就是说坏值是**每帧重建 `_lv` 时写进去的**，不是 `_apply` 写的。

而 Echidna 的 entries 比想象的多一个：

```
state=lobby                      clip=BR_Echidna_NS1_Lobby        scale 曲线 11 条  含灯光路径=False
state=breast                     clip=BR_Echidna_NS1_Tep_Breast   scale 曲线 11 条  含灯光路径=False
state=Tep_1                      clip=BR_Echidna_NS1_Tep_Normal   scale 曲线 12 条  含灯光路径=False
state=BR_Echidna_NS1_Lobby_Loop  clip=BR_Echidna_NS1_Lobby_Loop  scale 曲线  1 条  含灯光路径=**True**
```

那条唯一的曲线就是灯光骨，值：`t=0→1.0, 0.5→1.0, **1.0→0.0001**, 2.0→1.0, 3.0→1.0`
—— 这个 clip 会在某一刻把灯光缩到 0.0001（隐藏它）。而"每 1.5 秒一次"很可能就是
`BR_Echidna_NS1_Lobby_Loop` 的时长 ⇒ **那个 sampler 串进了别的 state 的烘焙**。

⚠ 另外：`setup_entry` 的挑选规则是"clip 名里含 lobby 的第一条"，
`lobby`(BR_Echidna_NS1_Lobby) 与 `BR_Echidna_NS1_Lobby_Loop` **都满足**。

### 37.6 交给下一轮的最后一步（已收窄到很小）

已确定：**进 `step_dynamics` 之前**（`_lv` 刚建好那一刻）灯光骨的 local 就已经是 1e-4；
而用 `assignments_for_entry(lobby)[灯光骨]` 直接采样那个 `anim_path`，**所有时刻都是 1.0**。
两边对不上 ⇒ 只剩两条路，下一轮按序测：

1. 在 bake 循环的 `_lv[_tfid] = trs_mat(...)` 前**把 `_tfid` 打出来**
   （本轮的 `trs_mat` 桩只打了 scale/pos、没打 tfid，这是唯一漏掉的信息）⇒
   直接看给灯光骨写值的那一次，`_a`/`_sp` 到底来自哪个 sampler。
2. 若确认是 `BR_Echidna_NS1_Lobby_Loop` 的 sampler 串了进来：查
   `assignments_for_entry` / `rest_by_animator` 的"就近 Animator"分配，
   以及 `enumerate_clips` 为什么会把"state 名 = clip 名"的条目也收进同一批 entries。

**修法方向**：`_lv` 的取值必须严格来自"该节点在**当前 entry** 下的 assignment"，
不能让多出来的 state / 副 Animator 的曲线串进别的 state 的烘焙。
本轮**没有动转换器代码**（只做了定位），避免在没定案前改坏已验证的 157 个产物。

### 37.7 ★ 结案（2026-10-12 深夜）：是**Animator 叠加层（Additive）**把灯光压成了 0.0001

给 bake 循环的 `trs_mat(_sp["pos"], _q, _sp["scale"])` 按 **tfid** 打桩之后，日志尾巴给出了
最后一块拼图：

```
[anim] 层配对：lobby→Dress Layer:BR_Echidna_NS1_Lobby_Loop；breast→Dress Layer:…；Tep_1→Dress Layer:…
[anim] 叠加 Animator 层 2 个：Base Layer(override)，Dress Layer(add)
[anim] 导出动画 4 条：lobby(10.67s)，breast(8.33s)，Tep_1(6.17s)，BR_Echidna_NS1_Lobby_Loop(**1.50s**)
```

再加上 controller 里的层定义（`Raw\AnimatorController\BR_Echidna_NS1.controller`）：

| 层 | `m_BlendingMode` | `m_DefaultWeight` |
| --- | --- | --- |
| Base Layer | 0（Override） | 0 |
| **Dress Layer** | **1（Additive）** | **1（= 生效）** |

而 `BR_Echidna_NS1_Lobby_Loop` 里**只有 1 条缩放曲线**，路径正是灯光骨
`Bone_COM_Skinned/Bone_BG_Light_Skinned`，值 `t=0→1.0, **1.0→0.0001**, 2.0→1.0`
—— 也就是**这个"换装层"会在每个 1.5 秒周期的某一刻把灯光缩到 0.0001（把它藏起来）**。
这和我们观测到的"灯光骨 local 每 1.5 秒变一次 1e-4"**完全吻合**。

**完整因果链**（每一环都有实测）：

1. Animator 有两个层：Base（Override，跑 `lobby`/`Tep_1`/`breast`）+ **Dress（Additive，权重 1，
   永远循环跑 1.5s 的 `BR_Echidna_NS1_Lobby_Loop`）**。
2. `compose_layers()` 把叠加层按 `v(t)=base(t)+(over(t)−over(0))` 合成进 base clip
   （叠加层按自身时长循环，这本身与 Unity 一致）。
3. 于是灯光骨（base 里恒 1.0）被合成成 **每 1.5 秒有一次 0.0001**。
4. bake 时 `lv[灯光骨]` 的缩放就周期性地是 1e-4 ⇒ 它的世界矩阵列范数
   `0.0925699 → 9.25699e-06`（**正好 1e-4**），**位置不变**（所以只比位置查不出来）。
5. `parts_Bg_001_Skinned` 蒙皮到它 ⇒ **网格塌成一个点**；
6. 而形变（deform）是按"世界位置差"烘的 ⇒ 塌掉那些帧把**整条 deform 时间轴**污染成
   `0 ↔ −1004` 来回跳 ⇒ 产物里**灯光到处飞、和 Unity 对不上**（真值里灯光是正常铺开的）。

**结论**：不是 shader、不是骨头、不是网格数据，而是**"换装叠加层"里那条"把灯光缩成
0.0001"的曲线被我们合成进了主动画**。至于 Unity 为什么看起来不受影响（权重 1、
blendingMode=1 的 add 层按理也会把它压成 0.0001），下一轮要**在 Play 里读
`Animator.GetLayerWeight(1)` + 该骨的 `localScale`**（把 `recordDbState` 那种探针
推广到"任意节点 TRS"）来定案；**不管 Unity 那边怎样，产物这条 deform 被污染、
网格塌成点，都是我们必须修的**。

**修法方向**（下一轮）：

1. **先修"形变被污染"**：deform 的世界位置差不能在"网格塌成点/缩放退化"的帧上采
   （要么跳过退化帧、要么用前一有效帧的外插），至少不能让一条时间轴整条报废；
2. **再核"叠加层该不该合这层"**：读 `m_AnimatorLayers` 的 `m_BlendingMode`/`m_DefaultWeight`
   （现在是硬编码/猜的），`m_DefaultWeight=0` 的层必须**跳过**；Additive 层对
   **scale** 的处理要按 Unity 实测（这是本条的争议点）；
3. `BR_Echidna_NS1_Lobby_Loop` 这种"**层专用 clip**"不该被当成主层的一个 state
   导出成独立动画（虽然多导一条无害，但 `setup_entry` 的挑选规则会被它骗到）。

### 37.8 ★ 修法落地（2026-10-12 深夜）：让"瞬时切换"在 deform 上真的变成跳变

用户明确说"**Unity 的效果是灯光闪烁**" ⇒ 目标就是让产物也"闪"。

**先量化两边**（真值 vs 产物，灯光部件 `parts_Bg_001_Skinned` 的顶点跨度）：

| | 波形 |
| --- | --- |
| Unity 真值 | **方波**：只有 `0.00021` / `2.10851` 两个取值；切换点 `0.521, 1.265, 2.007…`（周期 1.49s） |
| 我们的产物（修前） | **三角波**：`0.14 → 1380 → 2 → 1379` 来回**缓慢胀缩**（每 0.75s 一次） |

**根因（两个叠在一起）**：

1. **CS 世界缓存"向上取整"**：缓存填充是
   `while _want[_wi] <= _t: cache[_want[_wi]] = world(_t)` —— 请求时刻落在两个
   1/60 步之间时，被赋成**后一步**的世界。而 `times_of` 里那些 `kt − 1e-3`
   （"切换前补的保持帧"）**正好落在两步之间** ⇒ 拿到的是**切换之后**的值，
   "保持帧"形同不存在。
2. **保持帧被裁剪规则吃掉**：`deform` 只在"相对上一个已写键变化 > `deform_tol`"
   时才落键，而保持帧的值本来就等于前一个键 ⇒ 被整段跳过 ⇒ 时间轴上只剩
   "切换后"的键 ⇒ **跳变被线性插值铺满 0.7 秒** = 三角波。

**改法**（两处，都很小）：

* `static_prefab_spine` 的 CS 缓存填充：加一个 `_prev_world`，把落在两步之间的请求
  时刻按**上一步**（向下取整）填 —— 这才是"切换前"的语义；
* `times_of` 里记一份 `force_of`（所有 `kt ± 1e-3` 的补点），deform 落键时对这些
  时刻**强制落键**，不受 `deform_tol` 裁剪。

**修后实测**（同一份产物对比，跨度单位 = 源图像素）：

| t | 修前 | 修后 |
| --- | --- | --- |
| 0.30 / 0.60 / 0.70 / 0.74 | 886.77 / 294.37 / 96.90 / 17.91 | **1380.45（全亮）** |
| 0.76 / 0.90 / 1.20 / 1.45 | 20.38 / 278.04 / 830.16 / 1290.26 | **0.14（全暗）** |
| 1.52 | 1341.80 | **1380.45（全亮）** |

键序列也从 `0.05 0.749 1.499 2.249 …`（17 个）变成
`0.05 0.749 **0.750** 1.499 **1.500** 2.249 **2.250** …`（33 个）——
**切换前后各一键，插值窗口 1/1000 秒 ≈ 硬跳变** ✓

**受影响范围**：判据 = clip 里有"同一时刻的重复关键帧"（Unity 用同刻两键表达瞬切，
例如眨眼把 `Bone_Eye_*` 的 scale 在 1↔0.0001 瞬切）。
`_scratch\_probe\find_step_chars.py` 扫出 **168 个 clip / 67 个角色**
（清单 `_scratch\step_chars_20261012.txt`）。

**给用户肉眼验看**：`_scratch\_echidna_check\{old,new}\`（同 9 个时刻的渲染图 + README）。

### 37.9 ★ 相位：给叠加层加"循环相位"参数（2026-10-12 深夜）

**性质先说清**：Unity 里**非 Base 层的状态是"一直在跑、跨 base 状态不变"的**
（切 `lobby`→`Tep_1` 只重播 Base 层，Dress 层照跑）。所以真值里那一刻叠加层的相位
= "角色实例化之后过了多久 mod 层 clip 时长" —— **离线转换器原理上不可能知道**，
和"点击动作从 idle 的哪个相位切过去"（约束 33/37）完全同类。

**做法**：加环境变量 **`U2S_LAYER_PHASE=<秒>`**（默认 0 = "叠加层与 base clip 的 t=0 对齐"）。
实现：`compose_layers()` 里把**每条叠加层曲线在 [0, dur_over) 内环形平移** phase 秒
（`_rotate_curve()`），再照旧按自身时长循环铺满。
两个要点：

* **重复关键帧（瞬时切换）平移后仍同刻相邻、顺序不变**（排序用 `(时间, 原下标)`，稳定）
  ⇒ 阶跃语义不丢；
* **加性参考值必须取"未平移"曲线的首值**（`out = base + (layer − layer 状态起点值)`），
  否则整体会多一个常量偏置（第一版就踩了，实测差值正好是 `1 − 0.0001`）。

**验证（Echidna，灯光亮/暗窗口）**：

| | 切换时刻 |
| --- | --- |
| 产物（默认相位 0） | 暗0.00 → **亮0.02** → 暗0.75 → **亮1.50** → 暗2.25 → 亮3.00 |
| 产物（`U2S_LAYER_PHASE=0.521`） | 暗0.00 → **亮0.54** → 暗1.28 → **亮2.03** → 暗2.78 |
| **Unity 真值** | 暗0.000 → **亮0.521** → 暗1.265 → **亮2.007** → 暗2.764 |

⇒ 加上相位后**吻合到 ≈1 帧**（16~23ms；真值本身是 60fps 采样，切换点有 ±1 帧不确定）。

**零回归**：判据是"clip 里有没有同一时刻的重复关键帧"。有瞬切的角色
**168 clip / 67 角色**（清单 `_scratch\step_chars_20261012.txt`）；
`2DModel_PECS_Cerberus_NS1`、`2Dmodel_BR_Tomoe_NS1` **不在**名单里 ⇒
`force_of` 为空、既不补点也不改取整口径 ⇒ **产物逐字节不变**（已实测导出静态自检全 0）。

**已知小瑕疵（记一下，不阻塞）**：产物里灯光在最开头有 **1 帧（0.02s）的"暗"**，
说明 `setup`（deform 的参考姿态）取到的灯光状态与"合并后曲线在 t=0 的值"不一致
（两者差一个相位）。视觉上几乎看不出来，但下一轮可以顺手核：
`world_of(setup_entry, 0.0)` 与 `assign` 采样在同一时刻是否走了同一条（合并后）曲线。

### 37.10 ★ 相位反推 + 出"同步版"（2026-10-12 晚）

**从真值反推最佳相位**（`_scratch\_probe\fit_layer_phase.py`）：真值里灯光只有两档取值
（顶点跨度 0.00021 / 2.10851），拿"我们的方波（`亮 ⟺ (t−phase) mod 1.5 < 0.75`）"
与真值**逐帧**比，扫 phase：

* **零失配平台 = 0.494 ~ 0.504**（取中点 **0.499**）；
* phase=0.499 ⇒ **310 帧 0 失配**；偏出平台 ±0.016s（≈半帧）就 7~16 帧失配。

**交付：`D:\VB\Search\New\_Spine待检查_20261012_相位同步版\`**

* `README.md` —— 这个包是什么、相位怎么来的、对齐精度、复现命令、该看哪几张图；
* `2DModel_BR_Echidna_NS1\` —— 用 `U2S_LAYER_PHASE=0.499` 导出的**标准 skel 产物**
  （`--skel`，账本 `_static_info.json` 里新增 **`layerPhase: 0.499`** 便于溯源）；
* `...\_check\` —— 按真值"该亮/该暗"各 3 张渲染图（0.30/1.30/2.80 暗、0.55/1.20/2.10 亮）。

交付设置的产物窗口（`0.499`）：暗[0,0.5) 亮[0.5,1.25) 暗[1.25,2.0) 亮[2.0,2.75)
vs 真值 暗[0,0.521) 亮[0.521,1.265) 暗[1.265,2.007) 亮[2.007,2.764) ⇒ **≤1 帧**。

## 38 2026-10-12 晚：钉死"参考真值里**没有** DynamicBone 的写回"（用户："Alexandra 头发摆得特别大"）

## 39 2026-10-13：全量重转暴露的三件"口径泄漏"（用户报的 7 条问题）

### 39.1 教训①：**每角色口径必须进批量**，否则修好的会整体回退

用户报 `2DModel_BR_Echidna_NS1` "灯光怎么又出问题了"。实测新产物账本
`_static_info.json` 里 **`layerPhase = 0.0`**（正确值 `0.499`）—— 因为全量重转只带了
一条 Ignis 规则，**没带** `U2S_LAYER_PHASE=0.499`（§37.9 的叠加层相位修复是靠它实现的）。
⇒ 新增 **`tools\per_char_env.txt`**（每行 `名字子串<TAB>K=V[;K=V]`），
`tools\batch_cs_convert.py` 转换前读它并注入子进程环境、并在日志里打印命中项。
以后任何"每角色开关"（相位、`U2S_FORCE_INACTIVE`、preroll…）都写进这张表。

### 39.2 教训②：harness 的"状态在额外层"录不到（剧本口径）

`Chain_Breast_NoChain` / `Chain_Normal_NoChain` 在 **`Bresat_Layer`（层 1）**；
`U2SFrameDump` 原来写死 `Animator.Play(state, 0, 0f)` ⇒ **静默落到 layer 0**
（两次录制的 `fullPathHash`/`length` 完全相同就是证据）。
已给 harness 加支持：`U2SFrameDump.animatorLayer` + `PlayState()`
（`SetLayerWeight(layer,1)` + `Play(name, layer, 0)`），计划行**第 7 段 = 层号**；
`anim` 字段也改成记 `GetCurrentAnimatorStateInfo(animatorLayer)`。
（注意：本工程 Base Layer 的 `m_DefaultWeight = 0`、`Bresat_Layer = 1`，别想当然按 0 猜。）

### 39.3 教训③：**"状态不被驱动"时，clip 里的 `m_IsActive` 从未生效**

Ignis `parts_BP_028_1..5_Skinned`（单骨 `Bone_R_BreastParts_01_Skinned`）：

* 预制体里默认 `m_IsActive = 0`；
* `Chain_*_NoChain` 等 clip 里写 **全程 1**（`AnimationMode` 采样验证过：一采样就 active）；
* 但 controller 里 `Bresat_Layer` 的 12 个 `Chain_*` 状态 **0 条 transition/AnyState**，
  只有默认状态 `Chain_Lobby_2Side` 可达（该 clip 里这根骨 **0 条曲线**）⇒ Unity 里这些状态
  从来没被切进去、`m_IsActive=1` 从未生效 ⇒ 部件保持"默认关"。
* 我们的产物逐状态导出、照 clip 画 1 ⇒ 多出"一块不动、悬在画面上"的件（用户报的 BP_028）。

⇒ 转换器新增开关 **`U2S_FORCE_INACTIVE="<动画名子串>:<部件名前缀>[;…]"`**
（`static_prefab_spine.py` 的 `_forced_off_names()` + `node_visible()` 里强制 `v=0`）：
命中动画里把这些部件按**预制体默认（关）**处理，并在日志打 `[anim] U2S_FORCE_INACTIVE 命中 …`。
Ignis 用 `NoChain:parts_BP_028`（下一步要泛化成"该动画里这族骨有曲线才显示"）。

### 39.4 用户报的 7 条与当前进展（2026-10-13）

| # | 角色 | 问题 | 状态 |
| --- | --- | --- | --- |
| ① | `2DModel_3P_ConstantiaS2_NS1` | `breast` 脸不会变 | ✅ **已修（§39.6）**：`m_PPtrCurves` 解析正则过严（只认 `serializedVersion` 开头）⇒ `pptr` 恒空、换图既不告警也不导出。修后日志 `检测到 Sprite 交换动画…breast face_ani 用 3 张 sprite`，账本 `spriteSwap` = 变体 `face_ani_12__2/__3` |
| ② | `2DModel_3P_Eternity_NS2` | 冰淇淋 `parts_Ice_World_s50` 层级不对 | ✅ **已修（§39.5 + §39.11）**：`m_SortingOrder` 是可动画属性；先按真实语义重写编码器，再由 **min-rank setup + 每动画 t=0 落键** 做到全帧可表达；**真值逐帧顺序 226/226 逆序 0** |
| ③ | `2DModel_BR_BloodyPanther_NS1` | "没有导出" | ✅ **作废**（2026-10-13 用户确认转换出来了；产物核对 NS1 181/180、`excludedParts` 空、未知曲线 0） |
| ④ | `2DModel_BR_Brownie_NS1` | lobby 开始头发乱摇 | ✅ **已修（§39.8）**：弹簧链有历史 ⇒ 新增 `U2S_CS_PREROLL_<动画名>`；扫秒数取 `Start:2.0`（与 `fromStart` 真值最大误差 37px→**18px**） |
| ⑤ | `2DModel_BR_Echidna_NS1` | 灯光又错 | ✅ **已修（§39.1）**：口径泄漏（全量没带 `U2S_LAYER_PHASE=0.499`）⇒ 每角色口径表 + 重转；产物账本实测 `layerPhase=0.499` |
| ⑥ | `2DModel_PECS_Cerberus_NS2` | `Tep_1` 腿中间闪一下 | ✅ **结案（§39.10）**：先修好录制的 `Animator.cullingMode`（否则真值后半段冻结）；用全片有效真值比对 ⇒ Unity 在 0.503s/3.113s **同样**瞬时换腿（237~400px），我们中位 0.1px 对齐、仅切换帧略小 ~20% ⇒ 动作固有，非转换误差 |
| ⑦ | `2DModel_PECS_Ignis_NS1` | 别的动画也有固定块 | ✅ **已修（§39.7）**：这族件在 Animator 绑定子树之外 ⇒ clip 的 `m_IsActive` 运行时是死曲线；规则由 `NoChain` 泛化为 **`*:parts_BP_028`**（全动画不画），已重转并验证 |
| ② | `2DModel_3P_Eternity_NS2` | 冰淇淋 `parts_Ice_World_s50` 层级/位置 | 待查 layerId/sortingOrder + 骨映射 |
| ⑥ | `2DModel_PECS_Cerberus_NS2` | `Tep_1` 腿中间闪一下 | 待查该帧可见性/排序跳变 |
| ④ | `2DModel_BR_Brownie_NS1` | `lobby` 开始头发乱摇 | 待查弹簧链口径（预跑/相位/`m_Enabled`） |

**批量现状**：`tools\batch_cs_convert.py` 全量重转（157 个，日志
`_scratch\batch_cs_20261013_085551.log`），旧产物先搬到 `D:\VB\Search\del\<角色>`；
同时另起一条"单角色批量"只转用户点名的角色（子串过滤命中 13 个），
转一个查一个（用户要求"转出一个检查一个"）。

### 39.5 #2 Eternity 冰淇淋层级：根因在 **drawOrder 编码器**（`draw_order_offsets`）

现象：用户报 `3P_Eternity_NS2_SpecialTouch` 的 `parts_Ice_World_s50`（冰淇淋滑下）**层级不对**。

证据链：

1. **clip 在动渲染排序**：扫全部 13 个 Eternity clip，`m_SortingOrder` 曲线：

| clip | 节点 | 键值 |
| --- | --- | --- |
| `3P_Eternity_NS2_SpecialTouch` | **`parts_Ice_World_s50`** | **50 →（t=2.42）32** |
| 同 | `parts_Forearm_L_s40` | 40 →（0.17）34 |
| `…_noice` / `…NormalTouch` | 同上两件 | 常量 32 / 40↔34 来回 |

2. **转换器确实在生成 drawOrder**，但写不出来：`[drawOrder] 3P_Eternity_NS2_SpecialTouch：
   采样 254 帧 → 写 1 个关键帧（**127 帧表达不了已跳过**）`（`…_noice` 245、`NormalTouch_noice` 308）。
3. 原因：Spine 3.8 的 `offsets` 是**非负**偏移（二进制 unsigned varint），语义为
   "被列出的槽占领 `setupIndex + offset`，**未列出的槽按 setup 升序填进剩下的空位**"。
   旧实现只列"往后挪"的槽，并要求"往前挪"的那批恰好按 setup 升序 ⇒ 冰淇淋这种
   "整段跑到自己 setup 序号之前"的情况**每一帧都编不出来**。

**已做（2026-10-13）**：`draw_order_offsets()` 改成**按真实语义做模拟**——
先试"不列出 = 所有往前挪的槽"，不成就再逐个（n ≤ 40 时还试二元组）把别的槽塞进"不列出"集合，
用模拟结果是否等于目标顺序来判合法性。自测（含 `[5,0,1,2,3,4,…]` 这种"一件跳到最前"）全部通过；
**但**：形如整体逆序 / 多件"往前挪"且彼此次序与 setup 相反（`[3,2,1,0]`）在这个编码下**本质上不可表达**，
这类帧仍会跳过 —— Eternity `SpecialTouch` 的 127 帧就是这一类。

**完整修法（下一步做）**：把**骨架的 setup 顺序**改成"**每件在整条动画集里的最小名次**"
（min-rank order），并给**每条动画都在 t=0 落一个 drawOrder 键**（= 它自己的静态顺序）。
这样对任意帧都有 `rank_T(s) ≥ setup(s)`，所有帧都可表达；代价是这些角色的
**setup 姿态观感**会变成 min-rank 顺序（`_calib` 的 t=0 校验要一起看）。
影响面：全工程 **31 个 clip / 227 条** `m_SortingOrder` 曲线（Draculina 27、Orangeade 24、
Alice_NS2 15、**BloodyPanther 12**、Poi 7 …），所以这条修好对好几个角色都有用。

### 39.6 ✅ #1 ConstantiaS2「breast 脸不会变」：`m_PPtrCurves` 解析正则过严（已修）

真凶在 `unity2spine\unity\unity_anim2d.py` 的 PPtr 解析：

```python
for ent in re.split(r"^  - serializedVersion: \d+\s*$", block, flags=re.M)[1:]:
```

它要求每个 PPtr 条目以 `  - serializedVersion: N` 开头；而本工程这批 clip 的写法是
**`  - curve:` 直接开头**（实测 `3P_ConstantiaS2_NS1_2DModel_Lobby_breast.anim`：
`m_Sprite` 换脸曲线 4 个键，path = `…/Bone_head/face_ani`）⇒ `pptr` 恒为空 ⇒
**换表情的时间轴既不告警也不导出**（账本 `spriteSwap` 一直空）。

已改成两种格式都收：

```python
re.split(r"^  - (?:serializedVersion: \d+|curve:)\s*$", block, flags=re.M)[1:]
```

修后 `2DModel_3P_ConstantiaS2_NS1` 的转换日志：

```
[anim] 检测到 Sprite 交换动画（换贴图/换表情）：导出为「同一 slot 多 attachment + attachment 时间轴」，共 3 条动画
       Start  face_ani 用 2 张 sprite
       breast face_ani 用 3 张 sprite      ← breast 里脸确实会换
       lobby  face_ani 用 2 张 sprite
```

⇒ 这条走的是既有的"同 slot 多 attachment + attachment 时间轴"通路（不是新功能），
只是过去根本进不了这条路。**待用户肉眼确认** `breast` 里表情是否跟着换了。

顺带纠正 §39.4 表格里我先前的两条误判：①"PPtr 换图 0 条 / `spriteSwap` 空 ⇒ 排除换图"
是上面这个正则造成的**假阴性**；②`face` 节点在预制体里是**空节点**（无子物体/渲染器），
它那条 `m_IsActive=0` 对画面没有影响。

### 39.7 ✅ #7 Ignis 固定块：**"绑不上"的 `m_IsActive` 是运行时死曲线**（规则从 NoChain 扩到全部）

上一轮只按 `NoChain` 子串关掉，用户反馈"别的动画也有一样的固定块"。这轮把 9 个 `Chain_*` clip 的
`m_IsActive` 与"这族骨在 clip 里有没有曲线"列成表，发现 8/9 个 clip 都写"1 且骨被动画"，
光看数据判不出来 ⇒ 换成**编辑模式直接问 Unity**（`_scratch\_csbake\probe_ignis_layer1.cs`）：

```
layers=2   layer0 weight=1 len=4.666667   layer1 weight=1 len=4.666667
Play(Chain_Breast_NoChain,1) -> layer1 hash=304453162 len=5.666667     ← 确实切进去了
   parts_BP_028_1..5_Skinned   activeSelf=0  activeInHierarchy=0      ← 曲线没生效！
Play(Chain_Breast_Fall_Down,1) -> layer1 hash=-1139279465 len=5.666667
   parts_BP_028_1..5_Skinned   activeSelf=0  activeInHierarchy=0
```

⇒ 这 5 件在**所有动画里都显示不出来**（她们在 Animator 绑定子树之外：预制体路径双根
`…/2DModel_PECS_Ignis_NS1/parts_BP_028_1_Skinned`，clip 里写单根 `parts_BP_028_1_Skinned`
⇒ 绑不上）。而 `AnimationMode.SampleAnimationClip` 却能把她们置 1 —— **两种路径解析口径不同，
判"运行时可见性"必须以"编辑模式切层 + `animator.Update(0)`"实测为准**。

处理：`U2S_FORCE_INACTIVE` 支持 `*`（= 所有动画），`tools\per_char_env.txt` 改成
`2DModel_PECS_Ignis_NS1  U2S_FORCE_INACTIVE=*:parts_BP_028`，并已重转 Ignis。
函数级自测：`lobby` / `Ignis_Lobby_Face_On` / `Chain_*` 都命中 ✓。

**待做（通用化）**：把"clip 路径在 Animator 子树里绑不上"做成**自动识别**，
替换手工例外表 `dead_active_paths`。

### 39.8 ✅ #4 Brownie「lobby 开始头发乱摇」：弹簧链的**历史**要能按动画配（已实现）

用户判断："这个头发是不是跟之前的状态有关，从 start 开始和从 0 开始不一样" —— **成立**。
录了两条 Unity 真值（同一条 `lobby`，从头录）：

| 真值 | 进 lobby 之前播了什么 |
| --- | --- |
| `brownie_lobby_20261013_125207` | lobby 2s |
| `brownie_lobby_fromStart_20261013_125453` | **Start 3s** |

两条真值 **第 0 帧**的 20 根头发骨世界位置差：**最大 0.061（44.6px）**、中位 0.016（11.6px）
⇒ DynamicBone 是**有状态弹簧**，"上一段是谁"必须建模。

**转换器改动**：新增 `U2S_CS_PREROLL_<动画名>=<预跑状态>[:<秒>]`
（实现点：本转换器**每条动画都重建 runtime**，所以直接在"建 runtime + 预跑"那步换掉
预跑的状态/秒数即可；命中时打 `[cs] <动画>：预跑改用 <状态> <秒>s`）。

**Brownie 的秒数按真值扫**（都对着 `fromStart` 真值）：

| 预跑 | 中位 | p90 | 最大 |
| --- | --- | --- | --- |
| `lobby` 6.0s（旧口径：setup clip 跑到收敛） | 0.00162 | 0.01361 | **0.05112**（37px） |
| `Start` 1.0s | 0.00159 | 0.01282 | 0.04731 |
| **`Start` 2.0s（采用）** | **0.00120** | **0.00623** | **0.02489**（18px） |
| `Start` 3.0s（真值实际口径） | 0.00138 | 0.00778 | 0.03317 |
| `Start` 4.0 / 6.0s | 0.00152 / 0.00162 | — | 0.04993 / 0.05112 |

⇒ 最大误差 **37px → 18px**（剩下的是"预跑时长 + 帧率口径"，约束 39 同一件事）。
已登记 `tools\per_char_env.txt`：`2DModel_BR_Brownie_NS1	U2S_CS_PREROLL_lobby=Start:2.0`，
并用批量脚本单转 Brownie 跑通（日志有 `每角色口径 U2S_CS_PREROLL_lobby=Start:2.0`）。
探针 `t_db_pre.py` 同步支持 `--preroll <状态>:<秒>`（可对任何角色这样扫）。

### 39.9 #7 收口：Ignis 用 `*:parts_BP_028` 重转完成

`--only PECS_Ignis` 重转（587.9s）日志：`每角色口径 U2S_FORCE_INACTIVE=*:parts_BP_028` + `OK`，
产物 `skel 174.3MB` 已落标准目录 ⇒ 那 5 件在**所有动画**里都不再出现。

### 39.10 ✅ #6 Cerberus_NS2「Tep_1 腿中间闪一下」：**动作固有**（先修好真值才判出来）

#### 卡了很久的坑：**真值后半段全是废数据**（根因=Animator 剔除）

现象：两份 `cerb2_full` 录制都在 **t≈1.05s 之后顶点逐帧完全一样**（`rnd` 哈希重复
308/376、328/399、335/412 帧），而同一段 `anim.normalizedTime`/`dt` 一直在推进，
控制台也**没有**任何 `[U2SFrameDump]` 顶点异常 ⇒ 不是异常被吞、不是场景停摆。

试过的两件事都**不是**病因（但顺手留着，去掉混淆项）：
`PlayerSettings.runInBackground=True`、`SkinnedMeshRenderer.updateWhenOffscreen=True`。

**真凶**：`Animator.cullingMode` 默认会在"角色不在任何相机里"时**跳过骨骼 transform 的写入**
（`CullUpdateTransforms`）—— 此时 `normalizedTime` 照常走，但**骨位冻结** ⇒ 顶点自然逐帧相同；
`updateWhenOffscreen` 治不了它（骨根本没被写）。修法（`U2SPlayQueueRuntime.cs`，进 Play 前）：

```csharp
var ani0 = go.GetComponentInChildren<Animator>(true);
if (ani0 != null) ani0.cullingMode = AnimatorCullingMode.AlwaysAnimate;
```

修后：`cerb2_full_20261013_181456` **总帧 385、重复帧 0** ⇒ 全片有效。
**⇒ 这条是通用的：以后所有"Play 真值"都必须 `AlwaysAnimate`，否则后半段全是假数据**
（以前的 `_refshot_u2s` 大概率也踩过，只是没人对后段做逐帧比对）。

#### 用有效真值重判：Unity 自己也是"瞬时换腿"

| 部件 | 真值跳变 top（px） | 产物跳变 top（px） | 质心误差 中位/p90/最大（px） |
| --- | --- | --- | --- |
| `parts_Calf_Untis_003` | **257.2 @3.113**、256.0 @0.503 | 254.9 @0.503、203.4 @3.113 | **0.0** / 2.6 / 54.8 |
| `parts_L_Hand_Untis_018` | 402.5 @0.543、400.1 @3.226 | 417.3 @0.543、407.7 @3.226 | 0.2 / 2.9 / 28.1 |
| `parts_Belt_Untis_004` | 321.1 @3.113、318.0 @0.503 | 315.5 @0.503、253.1 @3.113 | 0.1 / 3.9 / 69.9 |
| `parts_Body_Untis_005` | 237.6 @3.113、235.4 @0.503 | 233.2 @0.503、187.5 @3.113 | 0.1 / 2.3 / 52.0 |

* clip 里 **0.5s / 3.1s** 各有一对"同刻重复键"，把 `Bone_R_Thigh/Calf_Idle` 与 `_Tep`
  两套腿在 **`scale 1 ↔ 0.0001`** 之间互换（这就是 Unity 的"缩到看不见"惯用法）——
  **Unity 真值在那两处同样是瞬时切换**（0.503s 与 3.113s 幅度对称：237~400px）；
* 我们逐帧位置**中位 0.0~0.2px、p90 2~4px** ⇒ 完全对得上；
* 唯一差在**切换那一帧**：我们略小（203 vs 257、253 vs 321、187 vs 237，约 −20%），
  属"1/60 步 vs 1 帧 + 保持帧边界"的量级（最大瞬时差 28~70px，中位 0）。

⇒ **#6 结案：闪是动作固有的瞬时换腿，Unity 也有；我们不是多出来，只是那一帧幅度略小。**

*（过程里还改了一处：`draw_order_offsets` 重写 + `_key_vals_differ`——后者"同刻重复键只有值
真的变了才补保持帧"，对 #6 不生效（本例值确实变了），但能防以后"值相同的重复键"造出假跳变。*）

### 39.11 ✅ #2 Eternity 冰淇淋层级：min-rank setup 方案落地（27 帧→0）

`draw_order_offsets` 重写之后仍有一批帧落不下来（`SpecialTouch` 254 帧只写 1 键、**127 帧跳过**），
因为该帧需要的重排里有"多件同时往前挪、且它们彼此的次序与 setup 相反"——这种在
Spine 的"非负偏移"编码下**无法**表达。完整解按约束 57 落地：

1. 新增 `_min_rank_of_slots()`：对**每条动画 × 每个排序变化时刻**算出该时刻的绘制顺序，
   取每个槽位的**最小名次**；把 setup 顺序按它重排 ⇒ 之后任意帧都能用非负偏移表达；
2. **没有排序曲线的动画**在 t=0 补一个 drawOrder 键（= 它自己的顺序），
   否则 t≥0 会露出 min-rank 顺序；
3. 有排序曲线的动画照旧在变化时刻落键。

**证据**（`2DModel_3P_Eternity_NS2` 重转日志，前 → 后）：

| 动画 | 之前 | 现在 |
| --- | --- | --- |
| `3P_Eternity_NS2_SpecialTouch` | 1 键、**127 帧跳过** | **3 键、0 跳过** |
| `…NormalTouch` | 4 键 | 5 键、0 跳过 |
| `…NormalTouch_noice` | 1 键、**308 跳过** | **5 键、0 跳过** |
| `…SpecialTouch_noice` | 1 键、**245 跳过** | **2 键、0 跳过** |
| `…Lobby_noice` | 1 键 | 1 键、0 跳过 |
| `Lobby` / `Lobby_Start`（无排序曲线） | — | 补 t=0 键（43 槽位） |

另用 `_scratch\_probe\verify_minrank.py` 做**结构性验证**：把编码器写出的 offsets 按
Spine 语义**回放**，与该时刻"由 Unity 排序语义算出的顺序"逐一比对 ——
**25 个 (动画,时刻) 组合，0 个表达不了 ✓**（注意：严格判据必须走编码器回放；
"每个槽名次 ≥ setup"只是充分条件，不能当判据）。

**端到端验证（2026-10-13 18:34 新录真值，harness 已修 `AlwaysAnimate` ⇒ 全片有效）**：
用 `_scratch\_probe\cmp_eternity_order.py` 把 Unity 真值逐帧的绘制顺序
（`so=(排序层,排序号,距离)`）与"转换器由 `sorting_value_of` 算出的顺序"比对
—— **`3P_Eternity_NS2_SpecialTouch` 226 帧，逆序对为 0 的帧 = 226/226 ✓**
（判据细节：真值的 `距离` 只是 1e-9 级噪声，同层同号的**先后在数据里没有信息**，
所以只统计 (层,排序号) 不同的对；第一版没排除同值对，误报成"每帧都有几十个逆序"。）

**影响面与代价**：全工程扫出 **15 个角色**带 `m_SortingOrder` 曲线
（Alice_NS2 / Eternity_NS2 / Poi_NS1 / Vanilla_NS1 / BloodyPanther_N,NS1 / Cheona_NS1 /
Gnome_NS2 / Khan_N,NS2 / KunoichiZero_NS1 / Cerberus_NS3 / Circe_NS1 / Draculina_NS1 /
Orangeade_NS1），已后台重转（`_scratch\batch_draworder_20261013_183102.log`，
脚本自带日志 `batch_cs_20261013_183114.log`）。代价是这些角色的**setup 姿态顺序**
变为 min-rank 顺序（播放时每条动画都有显式顺序键，所以观感与 Unity 一致）。

### 38.1 起因

用户看 `2DModel_3P_Alexandra_NS1` 的 `Tep_1`：
**"有摆动，但我们导出的摆动特别大，最右边头发直接摆没了，而 Unity 只是摆动。"**
（她这条链只有 `parts_B_hair` 一块；prefab 里 `DynamicBone Hair` 28 粒子、`m_Enabled=1`、
`m_Weight=1`、`IsTransFormCalculate=1`，她的 clip 对头发骨**一条曲线都没有**。）

### 38.2 先做的两个对拍（已经把范围锁死）

1. **纯 clip（`t_db_pre.py --nocs`）vs 最新 Play 真值（`alex_dev_20261012_202202`）**：
   32 根 `*hair*` 骨 × 125 帧 ⇒ **中位 0.00000 / 最大 0.00046 世界单位（0.34px）**。
   ⇒ 真值里的头发链 = **纯动画姿态**，一丁点弹簧都没有。
2. **跑 CS（默认）vs 同一条真值**：中位 0.006 / 最大 0.18 世界单位（≈4px / 132px）。
   ⇒ 产物比参考"多出来"的就是**弹簧**，量级 130px —— 正好是用户眼睛看到的"特别大"。

### 38.3 根因：`U2SFrameDump` 的落点在 `DynamicBone.LateUpdate` **之前**

新写了一个 Play 期探针 `Assets\Raw\Scripts\U2SDbProbe.cs`（`RuntimeInitializeOnLoadMethod`
+ 工程根 `u2s_dbprobe.flag` 触发，输出 `<工程根>\_refshot_u2s\dbprobe.txt`），
每帧在 **三个相位** 各记一遍每条 DynamicBone 的内部状态 + 链形状：

| 相位 | 时机 | 实测（`_U2S_alex_dev` / `Hair` / `Tep_1`）|
| --- | --- | --- |
| `U` | Update 相位 | 变换 = **上一帧** Apply 的结果（`shpt == shp`）|
| `L` | 探针的 LateUpdate（在 DB 的 LateUpdate **之前**）| 变换 = 被 `InitTransforms` 钉回 `m_Init*` ⇒ **刚形状**（`shpt≈5e-7`），粒子已偏离（`dev` 中位 0.033 / 最大 **0.2146**）|
| `E` | `WaitForEndOfFrame`（渲染前最后一刻）| 变换 = **Apply 之后**（`shpt == shp`，链真的在动）|

**逐帧精确配对**（真值与探针同一次 Play、同 `Time.time`）：`alex_dev_20261012_202202`
的 `Hair` 骨世界位置 vs 探针三个相位 ——

| 相位 | \|真值−tf(变换)\| 中位/最大 | \|真值−p0(粒子)\| 中位/最大 |
| --- | --- | --- |
| U | 0.002205 / 0.085816 | 0.002205 / 0.085816 |
| **L** | **0.000000 / 0.000000** | 0.002205 / 0.085816 |
| E | 0.000000 / 0.000000 | 0.000000 / 0.000810 |

⇒ **参考录制抓到的正是 `L` 相位**：`DynamicBone.Update()`（`PreUpdate→InitTransforms`）跑过了、
`DynamicBone.LateUpdate()`（物理 + `ApplyParticlesToTransforms`）**还没跑**。
也就是说：**`_refshot_u2s` 的全部录制里，弹簧的写回永远不在里面**；
而**渲染（`E`）里有**（`shpt` 中位 0.0166 / 最大 0.1536）⇒ 实时 Unity 的 Game 视图是有弹簧的。

* 旁证：同一帧里 Cerberus 的参考数据**有**"类弹簧"运动（`Bone_hair_FM_1` 位移 0.365、转角 0.000，
  且该骨在任何 clip 里 0 次）—— 那来自 **Puppet2D_GlobalControl**（它在 dump 之前写骨头），
  **不是** DynamicBone 的；Alexandra 没有 GlobalControl，所以她那边全是纯动画 ⇒ 一眼看出 0。
* 顺带修掉一个工具 bug：`U2SFrameDump` 的 `db[].dev` 一直恒为 0，因为
  `GetField("m_Transform", Instance|NonPublic)` **漏了 `Public`**（`Particle.m_Transform` 是 public）
  ⇒ 已在 `U2SFrameDump.cs` 补上 `| BindingFlags.Public`。

### 38.4 结论与产物口径（**需要用户拍板**）

同一条链的两条口径差这么多：

| 口径 | Alex 头发弹簧 | 我们产的 vs 它的差 |
| --- | --- | --- |
| 参考录制（= 我们一直用来验收的数据）| **0**（纯动画）| 中位 0.006 / 最大 0.18（≈132px）|
| Play 实时渲染（`E` 相位 = 玩家看到的）| 最大 **0.2146** 世界单位（≈157px）| 我们的烘焙 ≈ 同量级 |

⇒ **"摆得特别大"不是转换器算错，而是"参考口径里没有弹簧、产物里有"**。
两条路只能选一条：

* **(A) 产物对齐参考**：DynamicBone 弹簧**不烘**（只烘参考里能看到的那部分 CS，如 GlobalControl）
  ⇒ 头发回到"跟着头转"（就是用户说的"Unity 只是摆动"）。本次已出样例（见下）。
* **(B) 产物对齐实时渲染**：保留弹簧，但**参考数据要重录**（把录制移到 `E` 相位，
  例如给 `U2SFrameDump` 设 `[DefaultExecutionOrder(大值)]` 或改用 `WaitForEndOfFrame`），
  否则以后所有"产物 vs 参考"的验收都会把弹簧算成误差。

**交付样例（A/B，都是标准 `--skel` + `<目录名>.config.json`）：**
`D:\VB\Search\New\_Spine待检查_20261012_去弹簧对照\`

* `2DModel_3P_Alexandra_NS1\` —— **不烘弹簧**（= A 口径）；
* `有弹簧_当前代码\2DModel_3P_Alexandra_NS1\` —— 当前默认（`--cs`，含弹簧）。

### 38.5 本轮工具

| 文件 | 用途 |
| --- | --- |
| `Assets\Raw\Scripts\U2SDbProbe.cs`（工程内，新增）| Play 期逐帧三相位 dump 每条 DynamicBone 的 `en/itc/w/dmp/el/stf/ur/mt/np/dev/shp/shpt/tf` |
| `_scratch\_probe\q1_truth_local.py` | 真值里"骨相对父级的本地量"偏离 ⇒ 判"刚性 vs 有写回" |
| `_scratch\_probe\q2_chain_shape.py` | 链形状（与时间对齐无关）三方对比：Unity 自跑 DB / Play 真值 / |
| `_scratch\_probe\q3_dev.py` / `q4_db_en_seq.py` | 读 `db[]`（dev/en/粒子数）+ `m_Enabled` 逐帧序列 |
| `_scratch\_probe\q5_probe_vs_truth.py` | **逐帧配对**真值与探针三相位 ⇒ 钉"录制落在哪个相位" |
| `_scratch\_probe\q6_tomoe_check.py` | 同一套判据套到别的角色（Tomoe/Cerberus）|

### 38.6 追记：**摆幅 ∝ "动画每步走多远"**（用户："放慢动画就没那么剧烈"）

用户口径确认：**有弹簧的那版是对的（= B 口径）**，并观察到"放慢动画 ⇒ 头发摇得没那么凶"。
这条用转换器自己的弹簧复现（`_scratch\_probe\q7_speed_sweep.py`：物理步长固定 1/60 s、
每步把 clip 时间只推进 `1/60 × speed`）：

| 播放速度 | 弹簧拽离动画姿态（中位 / p90 / 最大，世界单位） | ≈px | 单根骨整段最大位移（中位 / 最大）|
| --- | --- | --- | --- |
| **1.00×** | 0.00628 / 0.05136 / **0.16892** | 5 / 38 / **124** | 0.0935 / 0.2856 |
| 0.50× | 0.00173 / 0.01813 / 0.09342 | 1 / 13 / 68 | 0.0805 / 0.1898 |
| 0.25× | 0.00071 / 0.00369 / 0.06622 | 1 / 3 / 49 | 0.0710 / 0.1343 |

**机制**：这套 DynamicBone 的 `UpdateParticles1/2` **没有 dt 参数**（逐步积分），
`m_UpdateRate=60` 把步长钉在 1/60 s ⇒ **摆幅由"动画每步走多远"决定**。所以：

1. 放慢动画（步长不变）⇒ 每步走得少 ⇒ 摆幅小 ✓（用户看到的现象）；
2. 帧率降低 ⇒ 一帧里最多补 3 步、多余时间被丢掉（`m_Time = 0`）⇒ 弹簧按实时时间变慢，
   观感也变；
3. **烘进动画的弹簧跟着变不了**：产物是固定轨迹，放慢只是把整条轨迹拉长，摆幅不变。
   ⇒ 若在**慢放**状态下比较"产物 vs 实时 Unity"，产物必然显得更大；这不是转换误差。
4. 游戏本身是 1.0×（Alexandra 的 controller：8 个 state 全是 `m_Speed: 1`、无
   `speedParameter`；Animator = UnscaledTime，`timeScale=1` 时与 DynamicBone 的
   `Time.deltaTime` 一致）⇒ 转换器的"1/60 步长 + 1.0× 动画"就是游戏口径 ✓
   （实测同一动作：我们 0.169 vs 实时 Unity 0.2146，同量级）。
