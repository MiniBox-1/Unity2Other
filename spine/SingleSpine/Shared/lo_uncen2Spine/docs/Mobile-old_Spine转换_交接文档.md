# Mobile-old → Spine（含 CS 脚本影响烘焙）· 交接文档

> **路径对照（2026-10-14 目录分区后补注）**：本文写于旧目录结构（老主仓 `D:\VB\Unity2Spine`）。**正文的结论/数据/手段仍然有效**，只是路径要换算 —— 对照表见 [路径对照.md](路径对照.md)（工具现在在 `src\tools\`，配置在 `config\`，第三方在 `deps\`）。

> 2026-10-12（第四版：在 10-10 收官基础上，把**算法/弹簧链**按"逐帧逐粒子"验到
> **0.0004~0.003px** 并结案 —— 结论是**转换器不需要再改**，残差来自"真值帧率口径"
> 与"dump 工具一次跑多条链"这两个对拍口径问题，见 §4.8 / 进展 §35。
> 上一版 2026-10-10（第三版：**157/157 全量已收官**，导出设定定稿为"只出 `.skel`"，
> 乘法件改成**默认直接对图集处理**）。**给接手人看的**：现状、交付物在哪、
> 必看约束、待办。
> 过程与逐轮排查记录在 [`Mobile-old_CS烘焙_方法与进展.md`](Mobile-old_CS烘焙_方法与进展.md)；
> 开工前的条件快照在 [`Mobile-old_转Spine_条件与目的.md`](Mobile-old_转Spine_条件与目的.md)。

---

## 0 三十秒速览

| 项 | 内容 |
| --- | --- |
| **目标** | 把 `归档-proj-Mobile-old\proj-Mobile-old` 里 157 个 `*.uAnim.prefab` 转成 Spine 3.8，**并把 CS 脚本的运行态影响（Puppet2D 样条/IK、DynamicBone 弹簧）烘进去** |
| **已完成** | ① CS 烘焙管线（录制+合并）打通并逐顶点验收；② 把 CS 逻辑**离线复刻进转换器**（`--cs`），不再依赖 Unity；③ 两个样例角色端到端交付；④ 尾巴在 `curtain`/`Tep_1` 上的离群**已定位并修掉**（§5.1）；⑤ **影子/备选件的显隐与淡入淡出**修好（§5.1.6）；⑥ **影子"不透明粉色"**定位为 Unity 乘法混合材质，**现在默认把乘法直接烘进图集**（§5.1.7/§5.1.8）；⑦ 查看器 spine3.8 绑定加了**按槽位混合**并支持分批绘制（§5.1.7、`修改记录_20261009.md`）；⑧ `.config.json 加载失败` 查出是 `slots` 被写成带皮肤层，已回退（§4 约束 19）；⑨ **157/157 全量 + 逐角色 QC 全 0**（§23），产物 **skel-only**（§22.1），整项目备份在 `D:\VB\lo_uncen2Spine\`（§23.4） |
| **可直接看的交付物** | `D:\VB\Search\New\_Spine待检查_20261009\`（Alexandra / Alice，含基线+合并+对比图+README） |
| **精度（对独立 Unity 真值）** | 合并版：Alexandra `Start` 最大 0.039px；Alice `Tep_1` **0.83px**、`curtain`（层感知）**0.36px**、`breast` **0.053px**。`--cs` 移植版：`Tep_1` 1.66px、`curtain` 2.18px；**乳房弹簧一段偏大**（`breast t=1.5` 中位 0.95 / 最大 19.8px，见 §5.1.4） |
| **下一步** | ① **按新口径重转 45 个角色**（弹簧会被 clip 关掉，见 §5.6.B，命令照抄）；② 用户肉眼检查的 9 条角色问题（`Sampler.txt`，A2 已修；其余见 §5.5/B 类）；③ 查 Cerberus 裙骨 `Bone_skrit_LF_*` 差 0.58（§5.6.C，怀疑同名兄弟节点）；④ 两条老悬留：Alexandra 后发链"启动瞬态"（§16）、空壳脚本的换肤/部件开关（§5.3）；⑤ 若要"全量重出"，跑 `tools\batch_cs_convert.py`（157 个 ≈ 6~8h）。⑥ **2026-10-12 结论**：算法/弹簧一路已按"逐帧逐粒子"验到 **0.0004~0.003px**（约束 39/40/41、进展 §35）⇒ 弹簧本身没有待修项了 |

---

## 0.1 任务与成果总览（截至 2026-10-10 收官）

一句话：**Unity 的 2D 骨骼动画已能被"纯离线"地转成 Spine 3.8 骨架/动画；157 个角色全部转完、
逐角色 QC 全 0；转换器不依赖 Unity、不需要录制数据。** 下面这张表是全部任务与状态（细节都在
`Mobile-old_CS烘焙_方法与进展.md` 对应小节）。

| # | 任务 | 状态 | 关键数字 / 证据 | 位置 |
| --- | --- | --- | --- | --- |
| T1 | 静态 prefab → Spine 3.8（批量、离线） | ✅ | **157/157**，产物 skel-only | `src\unity2spine\`、`_spine_conv_cs_port\` |
| T2 | CS 脚本（Puppet2D spline/IK/GlobalControl、DynamicBone）在转换器里离线复刻 | ✅ 逐帧真值验证 | DB 逐粒子 **0.0009px / 0.0041px**；IK **0.000**；5 个部件每根骨局部 TRS **0.000**；蒙皮位移场拟合残差 **0.000000** | §9 / §15 / §17 / §18 / §19 |
| T3 | 尾巴在 `curtain`/`Tep_1` 上离群 | ✅ | 97px → **0.83px**（合并网格=产物键∪录制键 + 叠层采集） | §5.1.2/§5.1.3/§11 |
| T4 | 影子部件显隐/位置不对 | ✅ | 显隐**逐条吻合**；位置 0.05~0.2px（`m_FloatCurves` 整段没解析 + `slots` 皮层层级） | §5.1.6 / §12 |
| T5 | 影子"不透明粉色"（Unity 乘法混合材质） | ✅ A/B 两版 | 识别内建 shader 205 → `blend=multiply`；A=精确版(α=1)，B=烘暗兼容版 | §5.1.7 / §14 |
| T6 | 乳房弹簧最大 ~20px | ✅ | 三个 bug（`curves` 误放 IKHandle／`re.split` 的 maxsplit／"Uniform 度量"）⇒ 19.76 → **0.62px(max)**、p90 **0.0014px** | §15 |
| T7 | 剩余 0.4px | ✅ 定位并消掉 | 真凶=**关键帧裁剪阈值** `DEFORM_TOL_WORLD`（0.8px→0.096px）：p90 0.4272 → **0.0014px** | §20 |
| T8 | 删 JSON 前的一致性验收 | ✅ | 6 个角色（3.8/7/16/37/90/124 MB）setup+每条动画各时刻 **VBO max|Δ|=0.000e+00**、IBO/blendRanges 一致 | §22.2 |
| T9 | 导出设定定稿 | ✅ | 标准=**只出 `.skel`**；配置名 **`<文件夹名>.config.json`**；`.json` 仅 `--json`（Debug/研究） | §22.1 |
| T10 | 零缩放退化 rig 让整条转换崩 | ✅ | 6/157 个 prefab 含零缩放；容错伪逆（丢轴）+ Unity 实测行为一致 | §22.3 |
| T11 | 全量 157 + 逐角色 QC | ✅ | 两轮批量（60/1 + 补跑）；完整性 0 缺；QC **157/157 四项为 0**（62.3 分钟） | §23 |
| T12 | 项目备份 | ✅ | `D:\VB\lo_uncen2Spine\` **24.19 GB**（排除可公开获取的资料/源码/软件） | §23.4 |
| T13 | **shader 清点 + 自动识别** | ✅ | 494 材质 / 22 种 shader；157 角色只用到 6 种；**25 个角色**用非普通混合；修掉 `mesh_style()` 永远 normal 的真 bug；内建 fileID 补齐 `202/206/10720`；自定义 shader 改为**读源码 `Blend` 指令**自动识别 | §24 |
| T14 | 导出设定指令（默认**对图集直接处理**、把 `blend=multiply` 等特殊设定**归档为实验性**） | ✅ 2026-10-10 | 默认把乘法**烘进图集**（texel = `黑 + α=1−m`）、槽位写 `normal`；`blend=multiply` 归到实验开关 `--multiply-blend` / `U2S_MULTIPLY_BLEND=1`；**25 个受影响角色已重转**并通过 `check_multiply_bake.py` | §5.1.8 / §24.4 / 进展 §25 |
| T15 | 用户新检查出的 9 条角色问题（`Sampler.txt`） | ⏳ 待做（**A2 已修**） | 清单与初步分析见 §5.5 / §24.5 | — |
| T16 | 本轮（2026-10-10 傍晚）的"直接对图集处理"落地 + 25 角色重转 + 校验工具 | ✅ | `tools\check_multiply_bake.py` 四查全过：产物 0 个 `blend=multiply`；两个乘法件的 UV 框 **rgb_max=0**、α 均值 157/78；逐页比对**矩形外 0 像素被改**；`skel ≡ json` 仍 **max\|Δ\|=0** | §5.1.8 |
| T17 | **弹簧链"还差几十像素"**（Cerberus/Alexandra/Tomoe 头发、Kaen 嘴、Ignis 多层…） | ✅ 2026-10-12 结案 | 查到根：**不是转换器的错**，是"**真值帧率口径**"+"**dump 工具一次跑了多条链**"两个对拍口径问题。改成"逐帧逐粒子"验收后：Alexandra `Hair` 最大 **0.003px**、`Breast` **0.0018px**、Cerberus `Hair` 中位 **0.0004px**（最大 2.8px 仅在最快摆动几帧） | 约束 39/40/41 / 进展 §35 |
| T18 | **clip 会把 DynamicBone 组件自己关掉**（`m_Enabled`） | 🔧 2026-10-12 已实现，**产物待重转** | 全工程 **327 条**绑在 DB 上的 `m_Enabled` 曲线（62 条恒 0 = 整条链被禁用、119 条 0/1 切换 = 中途重置链）；Play 实测确认 `Skirt_L.en=0` ⇒ 以前一直在给"Unity 根本没在跑的链"算物理。转换器已按"禁用不推进 / 0→1 重置链"实现（`U2S_CS_DB_ENABLED`，默认 1）；**受影响 45 个角色要重转**（清单 `_scratch\db_enabled_union_20261012.txt`） | 约束 44/45 / 进展 §36.4 / §5.6.B |
| T19 | 真值口径升级：**dt 序列 + 组件状态** | ✅ 2026-10-12 | `U2SFrameDump` 新增 `recordDtSeq`（写 `<前缀>.dtseq.json`，含预跑）与 `recordDbState`（每帧记每个 DB 的 `enabled/粒子数`）；对拍侧 `t_db_pre.py --dtseq/--dbenabled`。Cerberus 最大误差从"t≈1.2 持续 0.070"→"只在 t=0 一帧 0.0698、之后 ~1e-4" | 约束 43 / 进展 §36.1 |
| T20 | `EventDynamicBone` 事件（参数何时刷新） | ⏳ 已实现档位，未定论 | `parse_clip` 解析 `m_Events`；`U2S_CS_DB_REFRESH=frame|event|off`（默认 `frame` = 产物不变）。Alexandra 头发骨：`frame` 0.0190 / `event` 0.0155 / `off` 0.0580 | 约束 42 / 进展 §36.3 / §5.6.A |
| T21 | Cerberus 裙骨 `Bone_skrit_LF_*` 差 **0.58** | ✅ 2026-10-12 结案 | ① 主因是**对拍按名字绑错**（真值里有两套同名子树 `…_set` / `…_set_R`）⇒ 改**按路径**比后输入段只有 0.0017；② 真误差只剩 DB 链那套、沿链增长（0.015→0.025→0.065）= "弹簧在跑 vs 不跑" ⇒ 接上 `m_Enabled` 后 **0.087 → 0.0117** | 约束 46 / 进展 §36.5 / §5.6.C |

**两条已知的、与本轮交付无关的悬留项**：
1. **Alexandra 后发链"启动瞬态"**：中位 0.04px、前几秒最大 ~5.6px，属"粒子链建链姿态"口径差异
   （§16，含已否掉的 `rest` 方案）。
2. **空壳脚本**（`Actor.cs`/`ActorPartsView.cs`）：换肤/部件开关这类**离散**影响没进链路，
   应落成 Spine 的 `skins`/attachment 时间轴（§5.3）。

## 1 交付物 / 产物在哪

| 路径 | 是什么 |
| --- | --- |
| `归档-proj-Mobile-old\_spine_conv_cs_port\<角色>\` | **当前标准产物**（157 个，skel-only；2026-10-10 已用"乘法烘进图集"的新口径重转过 25 个非普通混合角色） |
| `归档-proj-Mobile-old\_spine_conv_cs_port_旧_乘法烘图集前_20261010\<角色>\` | 上述 25 个角色的**重转前快照**（A/B 对比与 `check_multiply_bake.py --base` 用） |
| `D:\VB\Search\New\_Spine待检查_20261010_乘法烘图集\<角色>\` | **给用户肉眼看影子的交付包**（25 个用非普通混合的角色，含 README 说明该看哪几个部件） |
| `D:\VB\Search\New\_Spine待检查_20261009\` | **给人检查的包**：`<角色>\{基线, CS合并后, 对比图}` + README（含逐部件标定残差） |
| `归档-proj-Mobile-old\_spine_conv\<角色>\` | **基线产物**（`static_prefab_spine` 纯静态转换，不含脚本形变） |
| `归档-proj-Mobile-old\_spine_conv_cs\<角色>\` | **CS 合并后产物**（录制+合并路线；2026-10-09 已换成"合并网格 = 产物键 ∪ 录制键"的修后版，逐顶点验收见 §5.1） |
| `归档-proj-Mobile-old\_spine_conv_cs_port\3P_Alice_NS1\` | **移植版产物**（`convert_static(--cs)` 离线自算，不依赖 Unity；现在 157 个角色都在这套路线下） |
| `D:\VB\Unity2Spine\delete\_spine_conv_cs_oldgrid\` | **已废弃**：修网格之前的合并产物（保留备查，确认不需要可删） |
| `D:\VB\Unity2Spine\_scratch\_csbake\` | 采集脚本、plan/verify txt、bake.json、partdump、对比图等**中间件**（可删可重生） |

每个产物目录里：`*_static.skel`（**标准产物**，二进制，查看器优先读）+ `*.atlas` + 图集 PNG +
`<目录名>.config.json` + `_static_info.json`（对账手册，`multiply` 段记录乘法件的处理口径）；
只有加了 `--json` 才有 `*_static.json`（Debug/研究用）。

---

**2026-10-10 补充（必读）**：
* **标准导出 = 只出 `.skel`**（`.json` 仅在 `--json` 时输出，供 Debug/研究）；查看器配置文件名 =
  **`<文件夹名>.config.json`**（不再是 `.config.json`）；老产物用 `tools\finalize_skel_only.py` 一次性归一。
* **全量结果**：157/157 转完、逐角色 QC 四项全 0、`skel ≡ json` 已逐位验收（§22/§23）。
* **整项目备份**：`D:\VB\lo_uncen2Spine\`（24.19 GB）——`Unity2Spine\`（转换器，含 `info` 真值帧、
  `_reverse` 逆向件）、`products\`（157 个 skel 产物 + 基线/录制/tol001）、`deliverable\`、
  `binding\`（spine3.8 pybind11 工程 + 查看器补丁）、`docs\`、`qc\`（逐角色 QC 报告）+ `README_备份说明.md`；
  已排除可公开获取的资料/源码/软件（`third_party`/`_reference`/`_probe50_rt4`/`delete`/`D:\Libs`/Unity 本体…）。

## 2 两条路线（都要知道）

| | **A 录制 + 合并**（已交付） | **B 移植版 `--cs`**（离线自算） |
| --- | --- | --- |
| 原理 | Unity 里逐帧跑「采样 clip 姿态 A → 跑 CS → 姿态 B」，取 `B−A`；标定映射后加到产物 deform 上 | 把 CS 逻辑用 Python 逐行复刻（`src\unity2spine\convert\cs_runtime.py`），转换器自己算出脚本效果 |
| 依赖 | **需要 Unity 每角色跑一次** | **只读磁盘资源** |
| 精度 | 对 Unity 真值：Alexandra 最大 0.039px；Alice `Tep_1` 0.83px、`curtain` 0.36px、`breast` 0.053px | 对 Unity 真值：`Tep_1` 1.66px、`curtain` 2.18px；`breast t=1.5` 19.8px（乳房弹簧，待收） |
| 产物 | `_spine_conv_cs\` | `_spine_conv_cs_port\` |
| 状态 | ✅ 可用于交付（§5.1 的两个 bug 已修） | ✅ 已接进转换器（`--cs`），只剩乳房弹簧几 px |

**两条路线都保留**：A 是已被逐顶点验证的"黄金参照"，B 是"不依赖 Unity"的将来主线；B 的每次改动都拿 A 的产物当靶子比（`tools\bake_cs\cmp_products.py`，产物空间逐顶点，无需任何跨坐标系换算）。

---

## 3 工具清单

### 3.1 转换器

```powershell
cd D:\VB\Unity2Spine
python -m ngui2spine.static_prefab_spine <prefab> <输出目录> `
  --assets <工程>\Assets --skel --no-face-check [--cs]
```

`--cs` 会：解析 prefab 上的 CS 组件 → 对每条动画**按 1/60 顺序**跑一遍
（采样 → `GlobalControl.Run` → `DynamicBone`）→ 把结果填进 `_world_cache`，
下游一行不改。见 `src\unity2spine\convert\cs_runtime.py`。

### 3.2 `tools\bake_cs\`（录制+合并路线与对账）

| 脚本 | 干什么 |
| --- | --- |
| `run_bake.py` | 驱动端：从产物取"候选部件+关键帧时刻"，逐 state 调 Unity 采集，拼 `bake.json` |
| `merge_cs_bake.py` | 标定 `S=unit_k/\|lossyScale\|` + 把 `B−A` 加进 deform + 重建 `.skel` |
| `verify_merge.py` | 独立验收：另起一次 Unity 运行取真值，与基线/合并产物逐顶点对 |
| `mcp_exec.py` | 把 `.cs` 片段文件丢给 Unity MCP 的 `execute_code`（避开 PowerShell 吃引号） |
| `prefab_cs_report.py` | **离线**列一个 prefab 挂了哪些脚本、DynamicBone 管辖哪些骨骼、会动到哪些渲染器 |
| `render_cmp.py` | 离线渲染基线 vs 合并后的三联图（用 `D:\VB\Viewer\Render\v4`） |
| `cmp_products.py` | **两份产物在产物空间逐顶点比**（最终验收口径） |
| `diag_curtain.py` | 三条产物（基线/合并/移植）在指定动画·槽位上的 deform 逐帧对照 |
| `diag_port_vs_unity.py` | 产物 Δ 与录制 Δ 直接对拍（含 2×2 线性拟合，判"位移场方向是否一致"） |
| `splice_bake.py` | 用重采的片段替换 `bake.json` 里的同名 state（只重采要修的 state） |
| `validate_cs_port.py` | 移植版对拍：转换器算的脚本位移 vs Unity 真实 `B−A` |
| `check_part_S.py` | 检验 `产物 = S*世界+T` 里 S 该取哪个 |
| `cmp_tail_motion.py` | 产物的形变变化量 vs Unity 纯 clip 实际位移 |
| `inspect_bake.py` | bake.json 体检（规模/每帧 delta 幅度） |
| `diag_*`（8 支） | 单点排查：`diag_space`(空间口径) `diag_part_err`(偏差形状) `diag_delta_match` `diag_trace` `diag_T_bug` `diag_tail_*` `diag_db_step`(单步隔离) `diag_db_formula`(纯公式) |
| `package_review.py` | 把产物打包成 `_Spine待检查_*` |

### 3.3 Unity 侧（装在 `proj-Mobile-old\Assets\`）

| 文件 | 干什么 |
| --- | --- |
| `Raw\Scripts\PartDataRecorder.cs` | **挂上去就能用**：Inspector 设字段、Play 里按 F9 逐帧导出各部件数据（顶点/矩阵/骨骼/显隐） |
| `Editor\PartDataExport.cs` | 菜单 `Tools/2DModel/逐帧部件数据导出/`：编辑模式**精确到帧**导出 A（纯clip）+B（脚本生效），同帧对齐 |
| `Raw\Scripts\U2SFrameDump.cs` | **2026-10-09 新增**：挂到角色**根物体**上，运行时**每帧**把整棵子树导成 JSONL——每个物体的 `activeSelf/activeInHierarchy/渲染器 enabled/世界位置·旋转·缩放/localToWorldMatrix`、`sortingLayer+Order`、`SpriteRenderer.color`/材质 `_Color`、可选顶点（BakeMesh）。默认输出 `<项目根>/_refshot_u2s/`，`F9` 开始/停止，`fixedFramerate=60` 时用 `Time.captureFramerate` 固定步长（帧号=时间×fps，便于对齐）。 |
| `Editor\FrameDumpMenu.cs` | **2026-10-09 新增**：菜单 `Tools/2DModel/逐帧状态导出/`——挂到选中根物体 / 挂进 prefab 资源 / 批量给 `Assets/Prefabs/*.uAnim.prefab` 的根都挂上 |
| `tools\bake_cs\read_framedump.py` | **2026-10-09 新增**：读上面那份 JSONL。`--grep Shadow` 列某帧的可见性/alpha；`--spine <产物> --anim <动画>` 直接**逐槽位对显隐**（Unity 的 activeInHierarchy+enabled+alpha vs 产物的 attachment/颜色时间轴），是"影子该显示却没显示"这类问题的判据 |
| `tools\bake_cs\framedump_to_verify.py` | **2026-10-09 新增**：把 dump 的一帧转成 `verify_merge.py` 的 verify.json（世界顶点→局部用 l2w 逆），于是这套 dump 也能做**逐顶点位置对账**（产物像素） |
| `tools\bake_cs\diag_shadow_pos.py` / `diag_shadow_product.py` / `probe_sprite_mode.py` | **2026-10-09 新增**：静态vs播放位置对比（找"是摆放错还是动画没跟"）/ 产物·Unity播放·Unity静态三点对比（含最近邻、镜像判别）/ 读 prefab 的 `m_DrawMode·m_Size·m_FlipX` |
| `tools\bake_cs\bake_multiply_opaque.py` | **2026-10-10 新增**：把 `blend=multiply` 槽位 UV 区域内的 α 置 1（Spine 的 multiply 要求 `src.a=1` 才等于 Unity 的纯乘法）——A 版必需 |
| `tools\bake_cs\bake_multiply_dark.py` | **2026-10-10 新增**：把乘法槽位烘成"黑 + 保留 alpha + normal"（B 版，任何查看器都能看到暗影子） |
| `tools\bake_cs\fix_slots_flat.py` | **2026-10-10 新增**：把误写成 `slots.default.<槽位>` 的产物 JSON 拉平成 `slots.<槽位>`（8 个文件已修） |
| `tools\bake_cs\diag_db_trace.py` / `diag_db_f32.py` / `diag_db_ablate.py` / `diag_db_split.py` | **2026-10-10 新增**：移植版 DynamicBone 与 Unity dump 的整段逐帧对拍 / float32 舍入对照 / update2 逐项消融 / 用 Unity 拆开的中间态定位（**最终靠它找到了 Distribution 曲线根因**） |
| `tools\bake_cs\read_framedump.py` 等（见上） | Unity 逐帧导出的读取与对账 |

### 3.4 MCP 片段（`_scratch\_csbake\*.cs`）

`runner_bake2.cs`（采集主程序，**支持 `layers=` 叠层**）、`verify_cs.cs`（独立验收）、
`verify_layers.cs`（**层感知**的独立验收：`layers=Start` 之类的叠层 + 主 clip）、
`dump_db_particles.cs`（反射导出 DynamicBone 粒子状态+每步输入）、
`probe_layers.cs` / `probe_curtain.cs`（读 AnimatorController 的层/默认状态/曲线绑定，
并列出 CS 组件的 `enabled` 状态）、`call_part_export.cs`；配套 `.txt` 是它们的参数文件。

### 3.5 查看器（`D:\VB\Viewer\Render\v4`）与 spine3.8 绑定 —— 2026-10-10 改

为了让查看器能画**按槽位混合**（乘法影子），改了绑定源码
（`D:\Code\vs_cpp_code\Spine3.8-py`，spine 原码 `D:\Libs\spine-runtimes-3.8`）：

| 文件 | 改动 |
| --- | --- |
| `GLArray.h` | 新增 `std::vector<int> blendRanges`（三连一组：ibo 起始/个数/混合模式） |
| `CustomSkeleton.cpp` | 新增**单遍** `BuildMeshData38()`（落地 `预备修正.md` 的越界写隐患）+ 记 `blendRanges` + 空 region 保护 |
| `AssemblyBinding.cpp` | 暴露 `.def_readonly("blendRanges", …)` |
| `renderer_src\SpineRender.py` | 新增 `_drawSkeleton()`：**默认仍是一次 `vao.render`**；只有存在 multiply 段才按段绘制（只有 multiply 段换 `(DST_COLOR, ONE_MINUS_SRC_ALPHA)`），画完恢复 |

构建：`D:\VS\MSBuild\Current\Bin\MSBuild.exe Spine380Binding.vcxproj /p:Configuration=Release /p:Platform=x64`
→ `Spine380.pyd`（538KB）。**兼容性**：API 只增不改；旧 pyd 备份
`Spine380.pyd.bak_20261009`（原始）/`.bak_20261009_blend`（中间版）。
完整改动与验证见 **`D:\Code\vs_cpp_code\Spine3.8-py\修改记录_20261009.md`**。

---

### 3.6 2026-10-10 新增 / 改动的工具

| 工具 | 作用 |
| --- | --- |
| `tools\batch_cs_convert.py` | 批量转换（逐角色**子进程**、失败不中断、实时日志 + 汇总；`--skip-done` 可续跑；`--exact-file <清单>` 只转清单里的角色，清单由 `shader_usage_inventory.py --out-txt` 生成） |
| `tools\batch_static_check.py` | 批量 QC（对每个角色跑 `static_check.py`，汇总四项计数；`_scratch\qc\*.json` 逐角色报告） |
| `tools\check_skel_vs_json.py` | **`.skel` ≡ `.json`** 一致性验收（spine-cpp 两边各加载，比 setup+每条动画各时刻的 VBO/IBO/blendRanges）。⚠️ 一次一个角色、别喂超大 JSON |
| `tools\finalize_skel_only.py` | 把旧产物统一成标准口径（删 `.json`、config 改名成 `<目录名>.config.json` 并指向 `.skel`、`excludeParts`/`json` 字段同步） |
| `tools\shader_inventory.py` | 清点工程里**所有** `.mat` 引用的 shader（内建 fileID / 自定义 guid → 名字） |
| `tools\shader_usage_inventory.py` | 清点**157 个 prefab 实际引用**的 shader，并按 shader 源码 `Blend` 归类 normal/additive/multiply/screen；`--out-txt <文件>` 直接写出"用到非普通混合的角色"清单 |
| `tools\check_multiply_bake.py` | **乘法件口径验收**：产物里还有没有 `blend=multiply`、`_static_info.json` 的 `multiply` 段、每个乘法件 UV 框内是否 `rgb=0 / α=1−m`（或实验口径的 α=255）、`--base <旧产物>` 逐页确认**矩形外 0 像素被改** |
| `_scratch\_csbake\t_db_frames.py` / `t_ik_frames.py` / `t_ik_local.py` / `t_smr_bones.py` / `t_skin.py` / `t_step_replay.py` / `t_probe_step.py` / `t_port_vs_rec.py` / `t_matrix.py` / `t_singular_match.py` | 各类**逐帧真值对拍**（DB 粒子 / IK / 骨头矩阵 / 蒙皮 / 单步回放 / 退化矩阵） |
| `_scratch\_csbake\dump_db_particles.cs` / `dump_ik_chain.cs` / `dump_smr_bones.cs` / `dump_skin.cs` / `probe_unity_singular.cs` / `probe_shader_names.cs` | Unity 侧探针：录逐帧粒子/IK/骨头/蒙皮真值，实测退化矩阵与 shader 名字 |

### 3.7 2026-10-12 新增 / 改动的工具（弹簧链结案那一轮）

| 工具 | 作用 |
| --- | --- |
| `_scratch\_probe\t_db_particles.py` | **逐帧逐粒子对拍（首选）**：按名字+父索引逐项校验整条粒子树，再比 `pos / prev / 骨位 / target / n` 五项，最后给"最差帧的逐粒子明细 + 参数对照"。口径：`AnimationMode` 采样 + 固定 1/60 + **一次一条链** |
| `_scratch\_probe\t_db_pre.py` | Play 真值（`obj` 世界 TRS）对拍，带口径开关：`--usedt fixed|truth`（**truth 才和真值同步长**）、`--pre true|false`（`InitTransforms`）、`--fields on|off`（clip 的脚本字段曲线）、`--setup clip|lobby`、`--shift <帧>`、`--pre/--dbinfo/--series-bone` |
| `_scratch\_probe\t_timemap.py` | **真值时间轴体检**：把真值每一帧在"纯 clip 采样细网格"上找最贴时刻 ⇒ 一眼看出真值的时间轴对不对（`Δ` 应恒为 0；线性漂移就说明时间轴与动画不同速率） |
| `_scratch\_csbake\trace_db.cs` | 逐步追踪 `m_Position[0]` 在"建链 → StartAnimationMode → 复位 → SampleAnimationClip → GlobalControl.Run → UpdateDynamicBones"各步的值 |
| `_scratch\_probe\probe_db_fields.cs` / `dump_db_params.cs` | 打印每个 DynamicBone 的 `RefreshParam / IsTransFormCalculate / 平值参数 / 逐粒子参数 / boneTotal / 粒子树`（用来核"是不是参数错"） |

## 4 ⚠️ 必看约束（全是踩出来的，按重要性排）

| # | 坑 | 症状 | 修法 |
| --- | --- | --- | --- |
| 1 | **顶点必须带局部 z** | 2D 模型的渲染器绕 X 转 90°，局部网格躺在 **XZ 平面**；只取 x,y 会丢掉整个纵向 | 导出/对账一律 3 分量 |
| 2 | **"clip 没动画它" ≠ "它是静止的"** | 对比 A/B 前不把整棵树复位到预制体姿态，上一帧脚本写进去的值会**残留** → A 不是纯 clip、`B−A` 只剩逐帧增量（实测残差从 0.004px 顶到 27px） | 每帧先恢复全部 Transform 到初始姿态，再采样 |
| 3 | 探测与正式采集**不能用同一实例** | 探测会把 DynamicBone 粒子状态搅乱，之后即使重新 `SetupParticles` 仍偏 ~8px | 探测单独跑一次（`bake=0`）写 `picked.txt`，正式采集用全新实例 |
| 4 | 只能在**产物自己的关键帧时刻**取样做标定 | 在任意时刻线性插值产物 deform ≠ 真值（残差 0.004px→100px） | 由 `run_bake.py` 从产物导出关键帧表交给采集器 |
| 5 | `S` 是**逐部件**的 `unit_k/\|lossyScale\|` | 用"全局 S"会让 lossy 差 8 倍的部件（Alice `parts_Body` 0.124 vs 四肢 0.99）假偏 159px | 逐部件用解析式；全局拟合只当旁证 |
| 6 | **粒子链要按 Unity 的 `m_Children` 兄弟顺序**建 | `ApplyParticlesToTransforms` 是顺序相关的，dict 顺序会让粒子顺序与 Unity 不一致 | `cs_runtime.parse_transform_child_order()` |
| 7 | `Transform.TransformDirection` **只取旋转**（长度不变，实测确认） | 用完整线性部分（含缩放）会把方向扭掉 | Gram-Schmidt 正交化后再作用 |
| 8 | `mat4_scale` 取**列**范数 | `mat4_from_trs` 建的是 `M=R·S`（缩放落在列上）；用行范数在"均匀缩放/90°换轴"时碰巧相等，一旦真旋转就返回**非单位四元数**（模长 272！）→ 缩放平方放大炸到 1e8 | 用列范数 + `mat4_quat` 先正交化 |
| 9 | `set_world` 要走 **local** | "用(pos,quat,scale) 重建 world"会丢掉父级非均匀缩放带来的**剪切**，静止姿态就偏 0.039 世界单位 | 算 local 再 `parent×local`（Unity 语义） |
| 10 | `SpineRender.SetAnimationTime` 收**归一化时间**不是秒 | 传秒会让所有 ≥1 的时刻绕回 0（t=2/4/6/8 渲得一模一样） | 从 `_static_info.json` 取时长再换算 |
| 11 | MCP `execute_code` 约 **50s 超时** | 返回 null 但 Unity 其实还在跑 | **一次只采一个 state** |
| 12 | 帧循环必须在**外层** | 反过来写是 O(渲染器×帧)：Alice 那次跑了 5min、写出 266MB | 帧在外、渲染器在内；只在关键帧读顶点 |
| 13 | `AnimationMode` 的告警 | `Could not register property modification ...` 是脚本直接写 Transform 造成，实例用完即毁 | 采集期间 `Debug.unityLogger.logEnabled=false` |
| 14 | `m_Time` 子步累加器 | `SetupParticles` 不清它 | 重设时手动置 0（`cs_runtime` 已处理） |
| 15 | **非 Base Layer 的状态："采 A 只采它自己那条 clip"会漏掉基底层** | Alice 的 `curtain` 层 clip 只有 24 条曲线（0 条尾巴/样条/IK），只采它 ⇒ A 的尾巴是静止姿态 ⇒ `B−A` **精确恒等于 0**，合并产物白丢一次修正（对 Unity 真值差 20px） | 采集/验收都带 `layers=<其它层默认状态>`：先按各自时长采这些 clip，再采主 clip（`runner_bake2.cs` / `verify_layers.cs` / `run_bake.py --overlay`）。**探测那一步也要带** |
| 16 | **合并时不能只按"产物已有的关键帧"取值** | 产物对"纯 clip 几乎不动"的部件会裁得很稀（`Tep_1` 的 `parts_Tail_B` 在 1.55→7.95s 一个键都没有），而脚本形变那段时间一直在变 ⇒ 被插成一条斜线，t=4.0 处尾巴偏 **97px** | `merge_cs_bake.py`：合并网格 = **产物关键帧 ∪ 录制关键帧**，用 `interp_frames()` 在任意时刻取产物值（修后 0.83px） |
| 17 | `cmp_products.py` 的口径是"并集时刻 + 各产物自己线性插值" | 两边关键帧网格不同时，差值反映的是**真实播放差异**（粗网格那一边会滑），不是工具噪声；所以"中位很小、最大很大"要先看两边的键表（`diag_curtain.py`/直接列出 `time` 列表）再下结论，别当成算法误差 |
| 18 | **本项目 clip 的 `m_FloatCurves` 条目写作 `- curve:`（字段序与老工程相反）** | 解析器只按 `- serializedVersion: N` 切条目 ⇒ **整段 FloatCurves 一条都读不到** ⇒ `m_IsActive`（SetActive 显隐）、`m_Color`（淡入淡出）、`blendShape`、`m_SortingOrder` 全丢。症状：预制体里静态关掉、靠 clip 打开的部件（影子/备选表情）被判"始终禁用"**直接不导出**；该淡出的部件一直不透明 | `unity_anim2d.parse_clip` 的条目起始正则两种写法都认：`^  - (?:curve:|serializedVersion: \d+)\s*$`。排查脚本 `tools\bake_cs\diag_clip_active.py` |
| 19 | **`animations.x.slots` 必须写成扁平的 `slots.<槽位名>`**（**不是**皮肤层！只有 `deform` 才带皮肤层） | 2026-10-09 我一度按"和 deform 一样"写成 `slots.default.<槽位>` ⇒ **JSON 直接加载失败**：spine-cpp 3.8 的 `SkeletonJson.cpp` 是把 slots 的键直接 `findSlotIndex()` 当槽位名，找不到就报 `Slot not found: default`。`.skel` 走槽位下标、不受影响，所以**只测 `.skel` 会漏掉** | 写扁平；已生成的 JSON 用 `tools\bake_cs\fix_slots_flat.py` 拉平过（8 个文件）；查看器的 spine-cpp 实测 JSON/`.skel` 均可加载。读端仍可用 `spine_out.anim_slots()`（兼容两种形状） |
| 20 | **Unity 的乘法混合材质（内建 shader fileID 205 = `Particles/Multiply`）不能按普通 alpha 导出** | 影子会变成"不透明的浅粉一块"（贴图本身是浅粉 + α≈0.29）。工程里 19 个材质用 205、12 个角色受影响 | **默认口径（2026-10-10 定稿）：把乘法烘进图集** —— 转换器识别 205/206 → 槽位颜色取"黑 + 原 alpha"、`blend=normal`，图集里该件 UV 区域的 texel 写成 `黑 + α=1−m`（`m = 2·i.color·_TintColor·tex.rgb`），因为普通 alpha 混合在 `src.rgb=黑` 时正是 `out = dst×(1−a)` ⇒ **与乘法逐像素等价**（因子为灰时完全等价），产物不依赖运行时的 multiply 支持。**实验口径**（`--multiply-blend`）：`blend=multiply` + 该区域 α 置 1（Spine 的 multiply 是 `dst×src.rgb + src.rgb×(1−src.a)`，只有 `src.a=1` 才等于纯乘法），需要查看器/运行时支持按槽位混合（§3.5）。验收：`tools\check_multiply_bake.py` | 
| 21 | **DynamicBone 的逐粒子参数来自 `m_*Distrib` 曲线** | 移植版用组件上的平值（0.07/0.03）⇒ 每步差 0.2px，在 7 粒子链里累积成乳房处最大 ~20px | ✅ 已修（2026-10-10）：`cs_runtime._parse_curve/_curve_eval` 按 `骨长/总长` 逐粒子覆盖。**两个配套 bug 一并修掉**，见 §5.1.4 |
| 22 | **`re.split(pattern, s, re.M)` 是错的写法** | `re.split` 第 3 个参数是 **maxsplit**，不是 flags！`re.M`(=8) 被当成"最多切 8 次"、而 `flags=0`（没有 MULTILINE）⇒ `^`/`$` 只按整串锚定 ⇒ **一段都切不出来**（`_parse_curve` 因此永远返回 0 键，曲线形同不存在） | 必须写 `re.split(p, s, flags=re.M)`。**只有 `re.split/re.sub/re.subn` 的第 3 个参数是 maxsplit/count**，`re.search/findall/finditer` 的第 3 个才是 flags —— 改这类代码先数参数位置 |
| 23 | **不要用"子树世界尺度 D"当度量换算去推进 DynamicBone / IK**（`Runtime.begin_metric`） | 转换器的 world 矩阵**本来就是 Unity 世界度量**（实测骨位/骨长与 Unity 差 1e-7），不需要任何换算；而 DynamicBone 的更新式（`|Δ|`、投影、`FromToRotation`）在**非均匀**缩放下不协变（这个 rig 的子树世界尺度是 `(0.1224, 0.1257, 0.0034)`）⇒ 切进去每步引入 1.87e-4 系统误差，481 帧累积 2.6e-3（2.1px）。**IK 同理**（`acos`/`LookRotation`/`AngleAxis` 不协变，偏 0.4px 量级）；spline 是仿射协变的，换不换一样 | `cs_runtime.STEP_IN_METRIC` / `GC_IN_METRIC` 默认 **0（关闭）**；要用旧行为对照就设 `U2S_CS_STEP_METRIC=1` / `U2S_CS_GC_METRIC=1`。两处关闭后：DB 逐粒子 481 帧最大偏差 **1.1e-6 世界单位（0.0009px）** |
| 24 | **改 DynamicBone/IK 的精度必须拿"逐帧逐粒子真值"对拍，不能只看产物顶点差** | 产物顶点差里混了标定矩阵 S、关键帧重采样、其它部件的误差，看不出"哪一项错" | 现成真值：`_scratch\_csbake\partdump\alice_db_particles.json`（`breast` 481 帧 × 7 粒子的 pos/prev/骨位/target/n/父索引）。对拍脚本：`_scratch\_csbake\t_db_frames.py`（整体逐帧）、`t_step_replay.py`（单步隔离）、`t_probe_step.py`（一步拆项）、`t_db_pchild_ab.py`（A/B 变体） |
| 25 | **DynamicBone 的"建链姿态"决定前几秒的起振瞬态，且三个真值来源各不相同** | Unity `Start()→SetupParticles()` 用的是"那一刻的姿态"；`runner_bake2.cs`（录制）在**探测阶段之后** `resetDyn()`、`verify_cs.cs`（验收）在**静态姿态** `SetupParticles()`、转换器用 **clip t=0**。对慢收敛的链（Alexandra 后发 28 粒子）前 3~5s 能差 5~7px | 转换器**保持 clip 第 0 帧建链**（= 角色从该 clip 开头起播，物理上正确）；改成静态姿态建链实测**恒定偏 34.7px**、更差。要"与录制真值逐像素一致"就继续用录制+合并路线。真值自检：`_scratch\_csbake\t_db_frames.py`（Alice 0.0009px / Alexandra 0.004px） |
| 26 | **产物关键帧的裁剪阈值原来是"按像素"给的，比验收阈值大 16 倍** | `DEFORM_TOL_WORLD=0.001` ⇒ `deform_tol = 0.001×unit_k ≈ **0.8px**`；而消费端（查看器 / `verify_merge`）在没写帧处**线性插值** ⇒ 中间时刻最大偏到 0.43px(p90)/0.60px(max)。原来那句注释"比验收阈值 0.05 低 50 倍"是**反的** | ✅ 2026-10-10 默认改成 **0.00012（≈0.096px）**：Alice `breast t=1.5` 从 0.4272 → **0.0014px(p90)**、`并合 vs Unity B` **0.0029/0.0430**（录制路线是 0.0051/0.0533），体积只 +23%。回退：`U2S_DEFORM_TOL_WORLD=0.001`（旧）或 `=0`（逐帧不裁剪）。**不要**再把这条残差误判成"尺度/标定口径"（走过一次弯路，见进展文档 §20.1） |
| 27 | **导出设定（2026-10-10 定稿）**：① 配置文件叫 **`<文件夹名>.config.json`**（不再是 `.config.json`）；② **标准导出只出 `.skel`**；③ 需要 `.json` 时显式加 **`--json`**（仅 Debug/研究，体积是 skel 的 4~5 倍） | 老名字（`.config.json`、`<prefab基名含.uAnim>.config.json`）与残留 `.json` 用 `tools\finalize_skel_only.py` 一次性归一/清理 | 删 `.json` 之前**必须**先过一致性验收：`tools\check_skel_vs_json.py`（用查看器 spine-cpp 两个文件各加载一遍，比 setup+每条动画各时刻的**顶点缓冲逐元素**、索引、blendRanges）。实测 6 个角色（3.8/7/16/37/90/124 MB）**max\|Δ\|=0.000e+00（逐位一致）**。⚠️ 一次只跑一个角色，别拿超大 JSON 喂 cpp（124 MB 那个要 434s，不是死锁） |
| 28 | **零缩放的退化 rig**（`m_LocalScale` 某轴=0，整块压进 Z=0 平面）会让"矩阵求逆"炸掉整条转换 | 157 个里 6 个含零缩放（`BR_RoyalArsenal_NS1` 46 处、`AGS_Aeda_N` 16 处，另 4 个各 1 处）；它们的世界矩阵 `|det|=0`，IK 写 `poleVector` 时 `set_world` 要对父矩阵求逆 → 旧版 `ValueError("矩阵不可逆")` 直接崩 | ✅ `unity_mesh.mat4_invert_tolerant()`（奇异方向在逆里置 0）+ `Runtime.set_world` try/except 兜底。**已用 Unity 实测确认行为一致**：零缩放父级下 Unity 设 `position` 不抛异常、只丢不可恢复的轴（Z），控制台 0 条 error；我们的容错逆反解出的 local 与 Unity 返回值**数值完全相同**（`[0.234247,-0.062972,0]` vs `[0.23425,-0.06297,0]`）。而且 `poleVector` 在 Unity 源码里**只写不读**（`Puppet2D_IKHandle.cs` L32 唯一一次赋值），所以丢轴不影响 IK 解与产物。探针：`_scratch\_csbake\probe_unity_singular.cs`、`t_singular_match.py` |
| 29 | **默认导出设定不要再动**（2026-10-10 收官）：① 乘法件**烘进图集**（槽位 `normal`），其它设定一律走**实验开关**；② 想回到"逐槽位混合"就加 `--multiply-blend`（或 `U2S_MULTIPLY_BLEND=1`）；③ 乘法件的槽位颜色恒为 `000000xx`（rgb 全 0），颜色时间轴只保留 alpha —— **rgb 曲线在烘焙口径下无法表达**（乘以彩色因子时按三通道均值灰化，见进展 §25.3） | 若把烘好的产物再喂给"支持 multiply 的查看器"，影子会**双倍变暗**（图集已经含暗化，运行时又乘一次）；反过来，实验口径的产物在**不支持 multiply 的查看器**里会泛白（贴图直通 + 区域 α=1） | 两种口径的产物**不要混用**：目录里 `_static_info.json` 的 `multiply.mode` 写着是哪种（`baked-into-atlas (default)` / `blend-multiply (experimental)`），`tools\check_multiply_bake.py` 会按它检查。改口径后**只需重转有非普通混合的 25 个角色**（用 `shader_usage_inventory.py --out-txt` + `batch_cs_convert.py --exact-file`），其余 132 个角色的图集逐字节不变 |
| 30 | **"用什么当判据"分两类，别混**（用户 2026-10-10 指令） | 拿"内部自洽"当验证，或者拿另一条路线的产物当真值 | **观感 / shader / 颜色**类：**不看 Unity**，产物丢进 `_Spine待检查_*\` 由用户肉眼看；**算法 / 运动 / 骨骼**类：**必须与 Unity 导出的真值对照**（`PartDataRecorder` / `verify_cs.cs` / `calib_geo.py` / `compare_play_truth.py`），并说清"真值是怎么导出来的" |
| 31 | **shader 语义必须实测，不许猜源码**；换算到 Spine 时**每个 shader 单独核** | 2026-10-10 第一轮把乘法件烘成 `α=1−m0`，结果 25 个角色一片错（多边形淡影 / 胸变黑 / 脸上黑块）—— 真实语义是 `out = dst·(1 − src.a·(1−m0))`，**alpha 是乘暗强度的调制** | 用 `_scratch\_csbake\probe_shader_blend.cs`（Unity 里渲染一像素读回）量公式，再一条条对映射；6 个 shader 的实测公式见 §5.1.8 与进展 §26。**另外：查看器必须同时支持 `blend=1(additive)→ONE/ONE` 与 `blend=2(multiply)→DST_COLOR/ONE_MINUS_SRC_ALPHA` 的分段绘制**，否则加色件会发暗（`SpineRender._drawSkeleton`，已修） |
| 32 | **`Transform.rotation` = 四元数链，不是矩阵分解**（2026-10-11 实测） | 我们原来 `Runtime.quat()` 用 `mat4_quat(world)`（从世界矩阵 Gram-Schmidt 取旋转）⇒ 带非均匀缩放/剪切的父级下与 Unity 差到 **85.7°**；而 CS 脚本（DynamicBone 的 `_apply` 对齐、IK、`TransformDirection`）读的全是 `transform.rotation` ⇒ 整条链歪（PXSilky 头发 559px / 77.9°） | `Runtime.world_rot(tfid)` = 沿父链把 **local 四元数**连乘（`parent.rotation × localRotation`），末端归一；`quat()`、`set_world(quat=)` 的"父级世界旋转"、两处 `TransformDirection` 都改用它。**局部**矩阵仍走 `T·R·S`（局部无剪切，`mat4_quat(local)` 是对的）。证据：`probe_quat_from_matrix.cs`（同 `parRot` 下 4 组非均匀缩放，`transform.rotation` 逐位相同，而 `Matrix4x4.rotation` 不同）。修后 PXSilky 559.761→**0.070 px / 0.0000°**；回归：RoyalArsenal IK 仍 **0.000**、Alice DB 仍 ~1e-7 世界单位 |

## 4.7 约束表（续，2026-10-11 第二轮）

| # | 约束 | 症状 / 为什么踩 | 做法与证据 |
| --- | --- | --- | --- |
| 33 | **弹簧链（DynamicBone）是有状态的：每条"点击动作"必须从 idle（setup clip）的稳态起跑** | 游戏里点 `Tep_1`/`breast` 是从 idle **切过去**的，那一刻弹簧链已经跑到稳态；我们原来对**每条动画都从 rest 重新建链**、而且复用同一个 runtime（上一条动画的末态还会残留）⇒ 动画第 0 帧的头发/胸/尾巴误差 **37~60px**（"接手那一刻"最大），idle 动作看不出来 | `static_prefab_spine` 的 CS 段：runtime 建好后先按 **setup clip（lobby）预跑 `U2S_CS_PREROLL` 秒（默认 2.0，0 = 关）**，`snapshot_dynamics()` 存下粒子 `pos/prev`+`object_*`+`time_acc`；每条动画（除第一条）在 `f==0` 时 `restore_dynamics()` 复原该快照。证据：Alexandra `Tep_1`，Unity 侧 `dump_smr_bones.cs` 带 `preroll=lobby:2.0` 对拍 ⇒ 头发骨最大误差 **37~60px → 0.005~0.009px** |
| 34 | **`outSlope/inSlope = ±Infinity` 的段是"常值段"（阶跃），不是插值段** —— transform 曲线（`m_RotationCurves/m_EulerCurves/m_PositionCurves/m_ScaleCurves`）同样适用 | 解析器的斜率正则写成 `([-0-9.eE]+)`，**匹配不到 `Infinity`** ⇒ 常值段的斜率被静默当 0，整段被 Hermite 插成一条斜线。典型：KunoichiKaen 的 `Bone_Mouth_Root` 位置曲线在 `0.8167s→4.2s` 本该**保持不动**（Unity 运行时就是这个行为），产物里成了一条 **3.4 秒的斜线** ⇒ 用户看到的"**嘴巴自动向上漂**（最多漂到鼻子）"。全工程 **62/757 个 clip、831 处**，**32/157 个角色**受影响 | `unity_anim2d._slope_token()` 认 `±Infinity`；`ngui_anim.UnityAnimCurve.value_at()` 的向量分支遇到 ±inf 就**取左键值**（与已有的 float 分支同一口径）。验证：Play 真值（`U2SFrameDump`，真 Animator 在跑）里嘴骨相对头骨 `1.0~4.0s` 稳定在 **-30.3px**，修后转换器重放同样是 `-30.4→-30.3` 然后 4.2s 跳回（修前是 3.4s 的线性斜坡）。⚠ 真值口径：`AnimationMode`（`PoseFrames`）**会插值**，与运行时不一致 —— 判这类段必须用 **Play 逐帧真值** |
| 35 | **clip 里 `attribute: script_0x...` 的曲线 = 直接写在组件字段上的动画，必须逐帧接进 CS 运行时** | 这批曲线（本项目全是 DynamicBone 的 `m_Damping/m_Elasticity/m_Stiffness/m_Inert`，路径如 `.../CTRL_Dynamic/Bone_Hair`）Unity 运行时**每帧覆盖**组件平值；我们原来整类丢掉 ⇒ 头发/胸/裙摆的"软硬"在动画里不跟着变。症状：**身体/头/嘴都在 11~18px，头发骨却差 0.557 世界单位（≈478px）** | 字段映射靠"曲线终值 = 预制体字段值"交叉验证（`0xD1FC4FBF→m_Damping`、`0x2DE5D16F→m_Elasticity`、`0x5517B11B→m_Stiffness`、`0xB255EB→m_Inert`，HongRyun/Tomoe/Alexandra/Cerberus 逐条对上）。`unity_anim2d.parse_clip` 收 `clip["script"]`（**keys 必须 `(time,value)` 成对**，只存时间会 TypeError 且被 try/except 吞掉）；`static_prefab_spine._wire_script()` 按路径 `endswith` 配对挂 `anim_fields`；`cs_runtime.DynamicBone.apply_animated(t)` 在每步前改字段并 `_update_params()`。验证（同一条 Play 真值）：Cerberus `hair_RL` **446.8→21.9px**（平均 35.7→1.7）、`Hair_F` 161→13.8、`hair_LB_Rskirt` 181→10.6；Alexandra 各头发部件平均掉到 1/2~1/4。**判据是"曲线值 ≠ 预制体值"，常数曲线也算** ⇒ 44 个角色要重转（`_scratch\redo_scriptfields3_20261011.txt`） |
| 36 | **Play 真值链路的四个坑**（`Assets\Raw\Scripts\U2SFrameDump.cs` / `U2SPlayQueueRuntime.cs` / `U2SPlayDumpDriver.cs`） | ① `BakeMesh(mesh,false)`+`TransformPoint` ⇒ 世界坐标小 ~10 倍（二次乘 rig 根 lossyScale）；② 网格 `isReadable=false`（AssetRipper 导入）时读 `sharedMesh.vertices` **报错并打断整帧** ⇒ 7 条录制只剩 1 帧；③ 预跑用 `Time.time` ⇒ 进 Play 加载资源时 `deltaTime` 被压住，2s 预跑拖成 21s；④ 自动收尾用"跑够 N 秒" ⇒ 固定步长时模拟时间比 realtime 慢，**中途掐断**录制 | ①改 `BakeMesh(mesh, **true**)`；②先看 `isReadable`、不可读走 `Mesh.AcquireReadOnlyMeshData`，并给整帧写入包 catch；③预跑改 `Time.realtimeSinceStartup`；④收尾判据改"**所有 dumper 都不在录**才退出"（+hardCap）。另外：**进 Play 会域重载**，编辑模式实例化的对象会被清掉 ⇒ 实例化必须在 Play 里（`[RuntimeInitializeOnLoadMethod]` + 标记文件）。⚠ **2026-10-12 更正**：原先写的"弹簧对拍要在真值侧固定 `Time.captureFramerate=60`"是**错的**，见约束 39 —— 真值一律按**真实时间**录，对拍时反过来让**转换器**用真值的 dt 序列 |
| 37 | **弹簧链的"预跑"要有足够时长：默认 6s**（`U2S_CS_PREROLL`，`0`=关；上限 `U2S_CS_PREROLL_MAX`） | 游戏里点击动作是从 idle **稳态**切过去的，预跑不到稳态 ⇒ 动画开头几秒整条链都错。实测（同一条 Play 真值）：Cerberus（弹性 0.08）2s 已稳，**Tomoe / LRL_N（弹性 0.01）2s 远未稳** —— Tomoe 头发平均误差 2s→**65.9px**、6s→**4.4px**；LRL_N 190px→**14px** | `static_prefab_spine` 的 CS 段：先按 setup clip 预跑 `U2S_CS_PREROLL`（默认 **6.0s**）拍快照，每条动画开始前 `restore_dynamics()`。取 6s 时四只角色（Cerberus/Tomoe/LRL_N/Alexandra）头发**平均**误差 2.7/4.4/5.5/3.7px。⚠ 别指望"跑到静止"——idle 本身一直在动，粒子永不静止（试过收敛判据，判据不成立） |
| 38 | **判"算法/运动"必须用 Play 运行时真值**（`Tools/U2S/按 playqueue 录 Play 逐帧真值`）；`AnimationMode`（`PoseFrames`）在"常值段/脚本字段"上和运行时不一致 | 两边都是**确定性**系统 ⇒ 任何差值都是真实差异（"混沌"只是放大它）。已排除：真值落后一帧（±1 帧平移无改善）、float64 vs float32（`U2S_CS_F32=1` 结果逐位相同）、关键帧 20fps 插值（改 60fps 网格只 5% 改善、体积 +29% ⇒ 已撤）、纯 clip 采样（关 CS 后 `bone_head` 差 0.0032 单位）。**2026-10-12 已结案**：多分叉极软发丝链那几十像素的残差**不是转换器的错** —— 用 `AnimationMode`+**固定 1/60**+**一次只跑一条链**录逐帧逐粒子真值，`cs_runtime` 与 Unity 吻合到 **0.0004px(中位) / 0.003~2.8px(最大)**，树/参数/积分/输出逐项相同（见约束 39/40/41、进展 §35） |

---

## 4.8 约束表（续，2026-10-12 上午：对拍口径）

这三条都是"**怎么对拍**"的约束——本轮为了追"头发还差 21.9px / 50.7px"踩出来的，
结论是**转换器不用改**，改的是对拍口径。（过程见进展 §35。）

| # | 约束 | 症状 / 为什么踩 | 做法与证据 |
| --- | --- | --- | --- |
| 39 | **真值一律按"真实时间"录，不要去固定 `Time.captureFramerate`**；要步长一致就**在转换器侧按真值的 dt 序列推进** | ① 历史 Play 真值其实一直是**实帧率**（≈35fps，dt 0.008~0.097 随机）：`U2SFrameDump.Awake()` 读 `fixedFramerate`，而队列是 `AddComponent` **之后**才 `Set` ⇒ 永远读到默认 0，`Time.captureFramerate` 从未生效。② 顺着这条去"修"（真把 captureFramerate 设上）**反而更差**：157 个 prefab 的 `Animator.m_UpdateMode = 2`（**UnscaledTime**）= clip 播放跟**真实时间**走、不跟 `Time.deltaTime` ⇒ 时间轴按 1/60 走、动画按真实 ~11.8ms/帧走，动画速率只有 **0.709×**（`t_timemap.py` 一测：真值每帧在纯 clip 细网格上的"最贴时刻"线性漂移到 **−1.43s**） | `U2SPlayQueueRuntime.Run()` 里显式 `Time.captureFramerate = 0` 并写明原因。对拍用 `_scratch\_probe\t_db_pre.py --usedt truth`（用真值自己的 dt 喂转换器）：Cerberus 头发骨 **0.377 世界单位(323px) → 1e-5(0.008px)**，t>2s 逐位为 0 ⇒ 积分器本身没有偏差。真值时间轴体检工具：`t_timemap.py` |
| 40 | **`dump_db_particles.cs` 一次只跑一条链（`db=<名字>`）** | 它的 `frames` 循环**嵌在 per-db 循环里**，而每帧都 `for (i<dbs.Count) UpdateDynamicBones` —— 第 2 条链的"**帧 0**"其实已经被第 1 条链带着跑了 150 步（`restore()` 只复位 transform，**不复位 `m_Position`**）。假症状：Alexandra `Breast` 链"帧 0 就差 28px、t=0.85 差 78px"，看着像一条全新 bug | `dbdump.txt` 里加 `db=Hair` / `db=Breast`，分开录。顺带：那一版 dump 的 `inTarget` 列只是"**更新前快照**"，不等于 `UpdateParticles2` 真正用的 `vec`，别拿它当判据（真正的判据是最终 `pos/prev`）。另外 `state` 名和 `clip` 名不一定一样（Alexandra `Tep_1` → `3P_Alexandra_NS1__lobby_tep`），要写 `clip=` |
| 41 | **弹簧链的验收工具首选 `t_db_particles.py`（逐帧逐粒子）**，并且口径必须是 **`AnimationMode` 采样 + 固定 1/60 + 一次一条链** | 产物顶点差里混了标定矩阵 S、关键帧重采样、其它部件的误差，看不出"哪一项错"（约束 24）。Play 真值则永远带"帧率口径"这个混淆项（约束 39） | `_scratch\_probe\t_db_particles.py`：按**名字+父索引逐项校验整条树**，再比 `pos/prev/骨位/target/n` 五项，并给出最差帧的逐粒子明细。2026-10-12 实测：Alexandra `Hair` 28×150 ⇒ 中位 **4.8e-7**、最大 **3.4e-6** 世界单位（**0.003px**）；Alexandra `Breast` 6×150 ⇒ 最大 **2.1e-6**（**0.0018px**）；Cerberus `Hair` 26×296 ⇒ 中位 **4.8e-7（0.0004px）**、p99 1.8e-4（0.16px）、最大 3.3e-3（**2.8px**，只在最快摆动那几帧）。**⇒ 弹簧链到此结案，不需要再改转换器** |
| 42 | ⚠ **未结**：clip 里的 **`EventDynamicBone` 动画事件**（`m_Events` 的 `data` = DynamicBone 的名字）很可能就是"**弹簧参数什么时候生效**"的开关 —— 全工程 **244 个 clip / 572 个事件**，时刻集中在 0.0167~0.1667s；而所有 DynamicBone 的 `RefreshParam` 都是 **false**（= 逐帧不会自动刷），导出工程里事件接收者又丢失了（`has no receiver!`） | 现在的做法是"**每步前**把 clip 的字段曲线刷进粒子"（约束 35），但这只是**近似**：理论上应是 "**建链那一刻的值 + 只在事件时刻刷**"。实测 A/B 反而支持"逐帧刷"（Alexandra 头发骨：`--fields on` 中位 0.0588/平均 0.0679 vs `--fields off` 0.1314/0.1263），与"冻结"推论矛盾 ⇒ 机制还没定论 | **下一轮第一件事**：① 扫 157 个角色的 `RefreshParam`；② `unity_anim2d.parse_clip` 解析 `m_Events` 并把 `EventDynamicBone(data)` 按名字配到 DB；③ 转换器加 `U2S_CS_DB_REFRESH=frame|event|off` 三档 A/B（`event` 档同时 A/B "建链值取 clip 第 0 帧还是预制体"），用 Play 真值取最贴的当默认；④ 只重转受影响的角色。细节见进展 §35.9 |

## 4.9 约束表（续，2026-10-12 下午：`m_Enabled` / `m_Events` / dt 序列）

| # | 约束 | 症状 / 为什么踩 | 做法与证据 |
| --- | --- | --- | --- |
| 43 | **判算法要"真值 dt 序列"对齐**：`U2SFrameDump.recordDtSeq` 写 `<前缀>.dtseq.json`（每帧 dt，**含预跑**），对拍侧 `t_db_pre.py --dtseq <文件>` **连预跑都用同一串 dt** | 真值按实帧率推进（预跑 ≈654 帧 / 5.76s），转换器按 1/60 ⇒ 两边步数与相位都不同，软链上会累计成几十像素，且**分不清是"算法错"还是"步长不同"**（约束 39 只解决了主循环，预跑还没解决） | Cerberus `Tep_1` 同一真值：最大误差从"**t≈1.2 处 0.070 且持续**"变成"**只在 t=0 一帧 0.0698、之后 ~1e-4**"（中位 0、平均 0.0025）⇒ 混淆项基本消掉。**以后判"算法对不对"一律走这个口径** |
| 44 | **clip 会把 DynamicBone 组件自己关掉**（`attribute: m_Enabled` + `classID: 114` + 脚本 guid = DynamicBone）；关掉 ⇒ **弹簧不跑、骨头跟着动画走**；`0→1` ⇒ `OnEnable→ResetParticlesPosition()` **重置整条链** | 转换器原来**完全不看这条曲线** ⇒ 给"Unity 里根本没在跑的链"算物理（骨头会被弹簧拖着走）。全工程 **327 条**这样的曲线：**62 条恒 0**、**119 条 0/1 切换**；受影响**45 个角色**（17 个有"整条链恒 0"，43 个有"中途 0→1"，多在 `Start`/`lobby_start`） | **Play 实测确认过**：新加的 `U2SFrameDump.recordDbState` 每帧记每个 DB 的 `enabled/粒子数`，Cerberus `Tep_1` 读到 `Skirt_L.en=0, np=12` ⇒ Unity 里它真的是关的。修法：`unity_anim2d` 把这类曲线单独收进 `clip["enabled_db"]`（必须 classID 114 + DB 脚本 guid 同时命中，避免和同路径**渲染器**的 `m_Enabled` 混淆）；`_wire_enabled()` 按路径配链；`cs_runtime.DynamicBone.step()` 里禁用就 `return`（不推进、不 `_apply`），由禁转启时先 `reset_particles()`。开关 `U2S_CS_DB_ENABLED=0` 可退回旧行为（默认 1） |
| 45 | **`m_Enabled`/`m_Events` 这类"组件级"曲线要用 `classID + script guid` 认，不能只按 `path` + attribute** | `m_FloatCurves` 的 `path` 只到 GameObject，**同一条路径上可能有多个组件**（渲染器 `m_Enabled` = 显隐、DynamicBone `m_Enabled` = 关弹簧，语义完全不同）。只按 path 认会互相污染 | 解析时要求条目里同时出现 `classID: 114` 与 DB 脚本 guid（`905d812fdcfac0b284dc07ceaad98046`）。工具：`scan_db_enabled_all.py`（全工程扫）、`scan_enabled_curves.py`（单 clip 看键值） |
| 46 | **同名节点多的 rig 必须按"完整路径"对拍，按名字比会造出假误差** | Puppet2D 的 rig 经常有 **`…_set` 与 `…_set_R` 两套同名子树**（Cerberus：`Skirt_set/Bone_skirt_L_set/…/Skirt_L/Bone_skrit_LF_*` 与 `Bone_skirt_L_set_R/…` 22 个同名节点）。按末段名字配（`byname`）会把两套绑到同一根骨 ⇒ 两套互相比 ⇒ 假误差 **0.58（530px）**，还误判成"跟弹簧无关" | 真值 `meta.json` 里有 `path`；用 `_scratch\_probe\t_db_paths.py`（**按路径**配、带层级缩进逐节点打印）。按路径之后：输入段 `Skirt_set/bone_Skirt_L/Skirt_L` 只有 **0.0017**，`_R` 那套 0.0016 平，真误差只在 DB 链那套、且**沿链增长**（0.015→0.025→0.065）= 典型"弹簧在跑 vs 不跑" |

## 4.10 约束表（续，2026-10-12 晚：Echidna 灯光）

| # | 约束 | 症状 / 为什么踩 | 做法与证据 |
| --- | --- | --- | --- |
| 47 | **"哪个部件坏了"要用"逐部件对真值"先锁死，再往骨头/网格/CS 里查** | 用户报"Echidna 灯光和 Unity 不一致"，第一反应是 shader（材质里确实留着自定义 shader 的 `_AdditionalAlpha` 属性、clip 也在动它）——但**那条线是死的**：工程里那 4 个自定义 shader **没有任何材质引用（0/221）**，221 个带该属性的材质全指内建 ⇒ Play 真值里一切恒定 | `_scratch\_probe\cmp_play_hair.py` 逐部件对 Play 真值 ⇒ 36 个部件里**只有 `parts_Bg_001_Skinned`（灯光层，蒙皮到 `Bone_COM_Skinned/Bone_BG_Light_Skinned`）差 1303px**，其余 ≤35px ⇒ 立刻从"shader"改判成"几何/驱动" |

## 4.11 约束表（续，2026-10-12 深夜：叠加层相位）

| # | 约束 | 症状 / 为什么踩 | 做法与证据 |
| --- | --- | --- | --- |
| 50 | **叠加层（非 Base 层）的循环相位在游戏里是任意的，要逐帧对齐必须显式给相位**；默认口径 = "叠加层与 base clip 的 t=0 对齐" | Unity 的非 Base 层状态**一直在跑、跨 base 状态不变**（切 `lobby`→`Tep_1` 只重播 Base 层），所以真值里那一刻的相位 = "角色实例化后过了多久 mod 层 clip 时长"，**离线转换器不可能知道**（同约束 33/37 的"idle 相位"）。实测 Echidna 灯光：真值亮段从 **0.521s** 起，我们默认从 **0** 起 ⇒ 差 0.521s | 开关 **`U2S_LAYER_PHASE=<秒>`**（默认 0）：`compose_layers()` 把每条叠加层曲线在 `[0, dur_over)` 内**环形平移**。两个坑：① 重复关键帧（瞬时切换）平移后必须仍**同刻相邻且顺序不变**（排序键用 `(时间, 原下标)`）；② **加性参考值要取"未平移"曲线的首值**，否则整体多一个常量偏置。验证：`U2S_LAYER_PHASE=0.521` ⇒ 亮/暗窗口与真值**吻合到 ≈1 帧**。详见进展 §37.9 |
| 48 | **"骨头位置对"不等于"骨头对"** —— 缩放塌了位置照样对 | 灯光那根骨**世界位置**与真值差 **0.0000**，但它的**世界矩阵列范数是 9.257e-06**（正常 0.0925699，**正好 1e-4**）⇒ 蒙皮网格塌成一个点，真形状被塞进 deform 时间轴（0 ↔ −1004 来回跳）⇒ 看起来像"灯光乱飞"。只比位置的对拍工具（`t_db_paths.py`/`cmp_play_bones.py`）**发现不了** | 对拍要**同时比"世界矩阵列范数/缩放"**，或直接比蒙皮顶点；定位工具：`_scratch\_probe\trace_bg001_*.py`（给 `_skin_mesh` / `_world_matrices` / `set_world` / `_recompute` / `step_dynamics` 逐个打桩） |
| 49 | **多出来的第 4 条"动画"其实是 Animator 的叠加层 clip；"瞬时切换"（同刻两键）必须在 deform 上体现成跳变** | Echidna 第 4 个 entry `BR_Echidna_NS1_Lobby_Loop`（1.5s）是 **Dress Layer（`m_BlendingMode=1` Additive、`m_DefaultWeight=1`）** 的循环 clip，它把**灯光骨**的缩放压到 **0.0001**（= 隐藏）⇒ Unity 里就是"**灯光闪烁**"（1.5s 周期、亮/暗各 0.75s、**瞬间**亮灭）。我们的产物却是**三角波**：跨度 0.14→1380→2→1379 来回缓慢胀缩 | ✅ **已修**（2026-10-12）。两个叠加的根因：① CS 世界缓存"**向上取整**"（落在两步之间的请求时刻被赋成后一步的世界）⇒ `kt − 1e-3` 这个"切换前的保持帧"拿到的是**切换后**的值；② 保持帧的值本来就等于前一个键，被 `deform_tol` 裁剪跳过 ⇒ 只剩"切换后"的键 ⇒ 跳变被线性插值铺满 0.7s。改法：缓存按**上一步**（向下取整）填 + `times_of` 的 `force_of` 补点**强制落键**。修后实测：`0.30/0.60/0.70/0.74` 全亮 1380.45、`0.76/0.90/1.20/1.45` 全暗 0.14、`1.52` 全亮 ⇒ **方波** ✓。受影响 **168 clip / 67 角色**（清单 `_scratch\step_chars_20261012.txt`）⇒ **要重转**。验看图 `_scratch\_echidna_check\{old,new}\`。详见进展 §37.5~§37.8 |

## 5 待办 / 下一步（按优先级）

### 5.1 ✅ 尾巴在 `curtain` / `Tep_1` 上的离群 —— 已定位并修掉（2026-10-09）

**结论：不是移植版错，是"录制+合并"这条路有两个 bug**（详细推导见
`Mobile-old_CS烘焙_方法与进展.md` §11）。判责靠新起的 Unity 运行取真值
（`verify_cs.cs` / `verify_layers.cs`），不看任何一条产物的脸色。

#### 5.1.1 症状

`cmp_products` 里移植版 vs 合并版中位只有 0.056px，但列表里挂着：
`curtain` 的 `parts_Tail_F/B` 中位 20.4/17.2px、`Tep_1` 的 `Tail_B` 最大 101px。

#### 5.1.2 bug①：合并网格用了"产物自己的稀疏关键帧"（⇒ Tep_1 的 101px）

产物对"纯 clip 几乎不动"的部件裁得很稀（`Tep_1` 的 `parts_Tail_B` 在 1.55→7.95s
**一个关键帧都没有**），而脚本形变那段时间一直在变；`merge_cs_bake.py` 逐帧只遍历
产物已有的键，于是把形变插成一条斜线。

* **修法**：合并网格改成 **产物关键帧 ∪ 录制关键帧**，用 `interp_frames()` 在任意时刻
  取产物 deform 值（`merge_cs_bake.py`）。
* **复验**（`Tep_1 t=4.0` vs Unity 真值）：旧合并 **97.09px** → 修后 **0.83px**（移植版 1.66px）。
  键数 Alice 8130→9016（+10.9%）。

#### 5.1.3 bug②：非 Base Layer 的状态，采 A 时漏了基底层（⇒ curtain 的 20px）

Alice 的 `curtain` 层 clip 只有 **24 条曲线**（`tail=0 spline=0 ik=0 ctrl=0`，用
`probe_curtain.cs` 数的），只采它 ⇒ A 的尾巴是静止姿态 ⇒ `B−A` **精确恒等于 0**
（105 帧 × 13 渲染器的 delta 全 0.0）。而转换器是把基底层默认 clip 合成进这条 state 的，
所以产物的 A 姿态 ≠ 录制的 A 姿态，合并版白丢一次修正。

* **修法**：采集器/验收器支持 `layers=`（先按各自时长采其它层的 clip，再采主 clip）；
  `run_bake.py` 加 `--overlay`；用 `splice_bake.py` 只重采 curtain 这一条 state。
* **复验**（`curtain t=1.75` vs 层感知 Unity 真值）：基线姿态 **0.079px**（证明转换器的
  多层合成本身是对的）、合并修后 **0.36px**、移植版 **2.18px**。

#### 5.1.4 残留：移植版的乳房弹簧还差几 px（**下一步**）

修完后移植版 vs 合并版（Alice）：中位 0.0638px / p90 1.554px / **最大 37.4px**，
最大项换成了乳房组。对 `breast t=1.5` 取真值判责：

| | 中位 | p90 | 最大 |
| --- | --- | --- | --- |
| 合并（修后） vs Unity B | 0.0051px | 0.031 | **0.0533** |
| 移植版 vs Unity B | 0.9544px | 4.545 | **19.763** |

⇒ 这一段是**移植版的 `DynamicBone`（`Bone_Breast` 有状态弹簧）偏**，不是合并版的锅
（`Bone_Hair` 在预制体里 `enabled=false`，采集会列进 `skipped:`）。
排查入口：`_scratch\_csbake\dump_db_particles.cs`（反射导出粒子状态与每步输入）、
`tools\bake_cs\diag_db_step.py`（单步隔离）、`diag_db_formula.py`（纯公式对照）。
其余取样点上移植版都在 2.2px 以内。

**2026-10-10 定案（根因已确认，转换器已改，解析器还差一个小 bug）**：

用 `_scratch\_csbake\db_step_trace.cs`（把一步拆成 `UpdateParticles1/2` 分别 dump →
`partdump\alice_db_split.json`，工具 `tools\bake_cs\diag_db_split.py`）拿到 Unity 的
**逐粒子真实参数**：

```
#0 damping=0.035075 elasticity=0.030025      ← 不是 0.07 / 0.03
#5 damping=0.070000 elasticity=0.017829
0.07 × 0.5010706(m_DampingDistrib@ratio=0)    = 0.035075 ✓
0.03 × 1.0008217(m_ElasticityDistrib@ratio=0) = 0.030025 ✓
```

即 **`DynamicBone.UpdateParameters()` 会用 `m_*Distrib` 曲线按「该粒子骨长/总长」
求值、再乘组件平值** 覆盖每颗粒子的 damping/elasticity/stiffness/inert/radius。
移植版一直用平值 ⇒ 每步 0.2px、链式累积成 ~20px。同一份 dump 还证明
**update1 与 Unity 完全一致（~5e-9）**；`diag_db_ablate.py` 的 9 种 update2 语义变体
也都不解释（都停在 1e-4~1e-3）—— 因为错的不是公式而是**参数**。

**已改** `src\unity2spine\convert\cs_runtime.py`（纯离线）：新增
`_parse_curve()` / `_curve_eval()`（Unity 三次 Hermite；空曲线返回 1.0 ⇒ 向后兼容）、
`DynamicBone.__init__` 解析 5 条曲线、`_update_params()` 逐粒子 `平值 × curve(骨长/总长)`。

**✅ 2026-10-10 已修完（三个 bug，全在 `cs_runtime.py` 里）**

| # | bug | 症状 | 修法 |
| --- | --- | --- | --- |
| ① | `self.curves = {...}` 那段被**误粘贴进 `IKHandle.__init__`** | `DynamicBone` 根本没有 `self.curves` ⇒ `_update_params` 直接 `AttributeError` ⇒ 曲线等于没接（移植版一直在用平值 0.07/0.03） | 挪回 `DynamicBone.__init__`，并给类加 `curves = {}` 兜底 + `_update_params` 用 `.get()` |
| ② | `re.split(r"^...", seg, re.M)` —— 第 3 个参数是 **maxsplit** 不是 flags | `_parse_curve` 永远返回 0 键（同一条曲线在交互式里能解出 2 键、函数里是空，就是这里） | 改 `flags=re.M`，见约束 22 |
| ③ | `step_dynamics` 把 DB 搬进"Uniform 度量"再推进 | 非均匀子树尺度下公式不协变 ⇒ **每步 1.87e-4** 系统误差，481 帧累积 2.6e-3 = 2.1px | 改由 `STEP_IN_METRIC` 开关控制、**默认关闭**，见约束 23 |

**验收（用 Unity 自己录的 481 帧 × 7 粒子真值，不依赖任何 Unity 现跑）**：

```
_scratch\_csbake\t_db_frames.py  --dump partdump\alice_db_particles.json
  修前：逐帧粒子误差 中位 1.87e-4 / 最大 2.57e-3 世界单位（= 2.06 px）
  修后：逐帧粒子误差 中位 2.18e-7 / 最大 1.10e-6 世界单位（= 0.0009 px）  ← float32 精度
```

**产物层验收**（`tools\bake_cs\verify_merge.py`，Alice 移植版 `_spine_conv_cs_port\3P_Alice_NS1`）：

| 取样点 | 修前 中位/最大 | 修后 中位/最大 | （对照）录制合并路线 |
| --- | --- | --- | --- |
| `breast t=1.5` | 0.9544 / **19.7630** | **0.0031 / 0.6198** | 0.0051 / 0.0533 |
| `Tep_1 t=4.0` | 0.1658 / 0.5856 | 0.1050 / 0.5578 | 0.0062 / 0.8310 |
| `curtain t=1.75` | 22.56 / 59.71 | 22.56 / 59.71（与录制路线完全相同，见下） | 22.56 / 59.71 |

**Alexandra 另有一个既有问题（不是上面三个 bug 引起的，已定案为"启动瞬态"，见 §5.4）**：

| 取样点 | 移植版 中位/最大 | 录制合并路线 |
| --- | --- | --- |
| Alexandra `Start t=3.0` | 0.0309 / **5.6339** | 0.0029 / 0.0052 |
| Alexandra `lobby t=2.0` | 0.2549 / **6.2622** | 0.0030 / 0.2126 |

* `curtain t=1.75` 两条路线都一样，是因为**基线产物本身对 Unity 的 A 就差 15.88px**
  （`基线 vs Unity A 中位 15.8790`）—— 与 CS 烘焙无关，是基线产品在那条 state 上的
  独立问题，别混进这一项里看。
* **剩下的残差在腿部（IK）**：`breast t=1.5` 的 p90/最大值 0.44/0.62px 全部来自
  `parts_Body` / `parts_Gatherbelt_Neck` / `parts_leg_*`；这些部件在同一时刻的 CS 位移
  有 290~323px，即相对误差 ~0.14%。`M*local`/骨位/骨长都已对到 1e-7，说明**输入没问题**，
  差在 IK 解算本身（下一步，见 §5.4）。

#### 5.1.5 复现命令

```powershell
cd D:\VB\Unity2Spine\tools\bake_cs
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
# ① 判责：先取 Unity 真值（先改 verify.txt：prefab/state/time/out[/layers]）
python mcp_exec.py ..\..\_scratch\_csbake\verify_cs.cs        # 单层状态
python mcp_exec.py ..\..\_scratch\_csbake\verify_layers.cs    # 非 Base Layer 状态
python verify_merge.py --product <基线> --merged <候选产物> --verify <verify_*.json> --calib <merge_report*.json>
# ② 只重采一条 state 再合并
python run_bake.py --product <基线> --prefab <prefab> --outdir <新目录> `
    --states 3P_Alice_NS1_curtain --overlay "3P_Alice_NS1_curtain=Start"
python splice_bake.py --base <原 bake.json> --replace <新目录>\bake.json --out <bake_layers.json>
python merge_cs_bake.py --product <基线> --bake <bake_layers.json> --out <合并产物> --report <r3.json>
```

#### 5.1.6 ✅ 影子部件"显隐/位置不对"——两个静默丢数据的 bug（2026-10-09 第三轮）

用户报告 Alice 的 `parts_Tail_Shadow` / `Bone_Tail_Shadow2` / `bone_Arm_L_Shadow` 影子
Enable 与位置不对。查出来是**两条与 CS 脚本无关**的解析/写出 bug（详见方法与进展 §12）：

1. **`m_FloatCurves` 整段没被解析**（本项目 clip 的条目写作 `- curve:`，与老工程字段序相反）⇒
   `m_IsActive` / `m_Color` / `blendShape` / `m_SortingOrder` 全丢 ⇒ "预制体里关掉、靠 clip
   打开"的影子被判**始终禁用直接不导出**，该淡出的影子一直不透明。
   修：条目起始正则两种写法都认（约束 18）。**排查脚本 `tools\bake_cs\diag_clip_active.py`。**
2. **`animations.x.slots` 少了皮层层级**（写成扁平 `slots.<槽位名>`）⇒ Spine 编辑器/读 JSON
   的运行时会把它当皮肤名，附件（显隐）/颜色时间轴**被静默忽略**。修：写
   `{"default": ...}`，读端统一 `spine_out.anim_slots()`（约束 19）。

附带修了"连续 `None` 逐点重复写"（影子一直不可见的时段会写 80+ 个废键）与
`ApplyParticlesToTransforms` 的判据（Unity 看**粒子链**子节点数，不是 Transform 全部子节点）。

**结果**：Alice 部件数 41→**55**、Alexandra 22→**47**，静态检查仍全 0；影子时间轴逐条对齐
clip 曲线（`Bone_Tail_Shadow2` 0.067s 打开、`bone_Arm_L_Shadow` 0.533s、`Bone_arm_R_shadow`
0.433s，`parts_Tail_Shadow` 在 0.27s 淡出）。CS 精度无回归（Tep_1 1.66px / curtain 2.18px）。
两个角色的基线/移植版/合并产物都已用修后代码重生成到 `_spine_conv\`、`_spine_conv_cs_port\`、
`_spine_conv_cs\`（旧的挪到 `D:\VB\Unity2Spine\delete\_pre_shadowfix\`）。

**位置也复核过了**（2026-10-09 第四轮，Play 中逐帧导出 + `verify_merge` 口径）：
五个影子对 Unity 的逐顶点误差 **中位 0.053px / 最大 0.206px**（基线）、移植版 0.058/0.226px。
中途出现的"两个影子差 126/161px"是**导出脚本**漏了 `m_FlipX`（`sprite.vertices` 不含翻转），
补上后归零 —— 产物本身没问题。详见方法与进展 §13。

#### 5.1.7 ✅ 影子"不透明粉色" + 查看器按槽位混合（2026-10-10）

**根因**：这几个影子用的是 Unity 的**乘法混合**材质（`multiply_5.mat`，
内建 shader fileID 205 = `Particles/Multiply`）——效果是 `out = 背景 × 贴图`
把背景压暗；而贴图本身是"浅粉 + α≈0.29"，按普通 alpha 导出就成了粉色挡在画面上。
工程里 **19 个材质**用 205（36 个文件名带 multiply）。

**两个版本都交付**（包里并排）：

| 版本 | 做法 | 验证 |
| --- | --- | --- |
| **A 精确** | 转换器写 `blend=multiply`（`SHADER_MULTIPLY={205}`）+ 乘法件 UV 区 **α 置 1**（`bake_multiply_opaque.py`，Spine 的 multiply 只有 `src.a=1` 才等于 Unity 的纯乘法）+ 查看器按槽位分批混合（§3.5） | 旧 pyd(粉) vs 新 A：差异只在影子 732 px，**亮度 196.8 → 160.5（变暗）**；与 B 的观感接近 |
| **B 兼容** | `bake_multiply_dark.py` 烘成"黑 + 保留 alpha 动画 + normal"（不动图集） | 与 A 差异**只在影子 408 px**；A 那些像素 (205,171,165) 浅粉 → B (123,106,103) 中性暗（亮度 −69.7） |

包目录：`CS合并后\` = A、`CS合并后_B_乘法烘暗\` = B（`对比图\` 仍是早期渲染）。
**注意**：A 需要**新版查看器**；B 在任何查看器都能看到暗影子。

#### 5.1.8 ✅ 收官：乘法件改成"默认直接对图集处理"（2026-10-10 傍晚）

用户指令：**"默认对图集直接处理，把其他导出设定为实验性的方法，默认转换的方式不用实验性的方法。"**
落地成"**转换时就把乘法烘进图集**"，产物不再依赖运行时的 multiply 支持。

**做法（`convert\static_prefab_spine.py`）**

| 环节 | 默认（`baked-into-atlas`） | 实验（`--multiply-blend` / `U2S_MULTIPLY_BLEND=1`） |
| --- | --- | --- |
| 槽位 | `blend` 省略（= `normal`）、颜色 **`000000xx`**（黑 + 原 alpha） | `blend=multiply`，颜色 = `min(1, i.color·2·_TintColor)` |
| 图集 | 该件 UV 矩形内 texel 改成 **`rgb=0`、`α = 1 − m`**（`m = min(1, i.color·2·_TintColor)·tex.rgb` 三通道均值） | 该件 UV 矩形内 **`α = 255`**（贴图 rgb 直通） |
| 理由 | 普通 alpha 混合在 `src.rgb = 黑` 时是 `out = dst×(1−src.a)`；令 `src.a = 1−m` ⇒ **`out = dst×m`，与 Unity 的乘法逐像素等价**（因子为灰时完全等价） | Spine 的 multiply = `DstColor OneMinusSrcAlpha`，只有 `src.a=1` 才退化成纯乘法 |
| 贴图共用 | 该矩形若还被别的部件采样 → 自动裁成一张**独立小页**（`*_static_N_mul.png`），UV 重映射 | 同 |
| 附带好处 | 白底 → 乘 1 → `α=0` 自然不可见；α 掩码贴图也自动正确（不用再管贴图是不是"浅粉 + α≈0.29"） | — |

**清点与重转**（受影响角色 = 用到非普通混合的 **25 个**，其它 132 个的图集逐字节不变）：

```powershell
cd D:\VB\Unity2Spine
# ① 生成"用到非普通混合"的角色清单（25 个）
python tools\shader_usage_inventory.py --out-txt _scratch\non_normal_chars_20261010.txt
# ② 只重转这些角色（默认口径；产物直接覆盖 _spine_conv_cs_port\<角色>）
python tools\batch_cs_convert.py --exact-file _scratch\non_normal_chars_20261010.txt
```

**验收（`tools\check_multiply_bake.py`，样例 `BR_May_NS3`）**

```
模式: baked-into-atlas (default)   乘法件 2 个
非普通混合的槽位: 0 个
parts_Machine_Shadow_Multiple_012_Skinned_32  页 …_static_0_mul.png  框(2,2,479,495)
    rgb_max=0（应 0）  α 0/255/均值 157.1  ⇒ 乘法因子 m ∈ [0.000, 1.000]
parts_Breast_Shadow_Multiple_015_Skinned_02   页 …_static_2.png      框(1726,1541,2002,1777)
    rgb_max=0（应 0）  α 0/245/均值 78.2   ⇒ 乘法因子 m ∈ [0.039, 1.000]
与旧产物逐页比对：…_static_1.png 改动 0 像素；…_static_2.png 改动 65136 像素、
                其中矩形外 0 个 ⇒ PASS
```

`tools\check_skel_vs_json.py` 也复跑过：改动后 **VBO `max|Δ| = 0.000e+00`**、`blendRanges`
全 0（没有残留的混合段）—— 说明"换成一般化混合"没有把骨架数据写歪。

**这一轮又补了三件事（同一批代码，25 个角色重转两遍）**

1. **账本**：`_static_info.json` 的 `multiply.parts` 每条记 `factor / page / rects（闭区间，
   源图像素）/ uvMap / pageSize`。校验器不再靠"槽位名 ↔ 部件名"猜、也不靠 JSON 里被
   四舍五入过的 UV 反推矩形（那会差 1px），而是**按账本逐条核验**。
2. **修掉 1px 接缝**：`_bake_rects` 原来写 `arr[y0:y1, x0:x1]`（右/下**开**区间），比账本
   矩形少烘 1 行 1 列 ⇒ 乘法件边缘会留一条"原贴图"的浅粉细线。改成**闭区间**后，
   `May_NS3` 的改动像素数 65136 → **65649 = 矩形面积 277×237，完全相等**。
3. **校验器重写**：`tools\check_multiply_bake.py` 现在查四件事 —— ① 产物里还有没有
   `blend=multiply`；② 每条账本矩形内 `rgb=0 / α=1−m`；③ 裁剪页整页只应是"黑 + α"；
   ④ `--base` 逐页比对"改动只发生在这些矩形里"。样例：

```
模式: baked-into-atlas (default)   乘法件 2 个
  parts_Machine_Shadow_Multiple_012_Skinned_32   裁剪页 …_static_0_mul.png 481×497
     矩形 (2,2)-(478,494)   rgb_max=0  α 0/255/157.1  ⇒ m ∈ [0.000, 1.000]
  parts_Breast_Shadow_Multiple_015_Skinned_02    页 …_static_2.png
     矩形 (1726,1541)-(2002,1777)  rgb_max=0  α 0/245/78.2  ⇒ m ∈ [0.039, 1.000]
  …_static_2.png ≈旧 …_static_1.png 改动 65649 像素，矩形外 0 个
PASS：乘法件的图集口径正确（与转换器账本逐条吻合）
```

**一个"看着像 bug、其实是忠实"的例子**（用户复核时可以不管）：
`PECS_Babariana_NS1` 的 `parts_004_shadow acc_skinned_21` 烘出来是**全透明页**
（α 全 0）。查证：该件 UV 落在贴图的**纯白**区域，材质是内建 205、`.mat` 里**没有**
`_TintColor` ⇒ 因子 = 1，`m = tex.rgb = 1` ⇒ Unity 里 `dst×1` 本来就不改画面。
同角色另外 3 个影子正常烘出 α ≤ 255。⇒ 不是烘错，是那件在 Unity 里本来就"什么都不做"。

**验证口径（用户 2026-10-10 指令，务必照办）**

* **观感 / shader / 颜色**这类问题：**不看 Unity**，直接把产物丢进交付文件夹由用户**肉眼看**
  （这轮就是：`_Spine待检查_20261010_乘法烘图集\`）；
* **算法 / 运动 / 骨骼**这类问题：**必须和 Unity 导出的真值对照**（`PartDataRecorder`/`verify_cs.cs`/
  `caly_geo.py`/`compare_play_truth.py` 这一套），不许只拿"另一条路线的产物"当判据。

**第二轮（用户肉眼过完 25 个角色后）—— 乘法烘法错了，已按实测语义重做**

用户反馈：Alice_NS1 `breast` 原先对、现在错（多边形淡影）、Daphne 同样、DrM_NS1 腿上多色块、
May_NS3 整个胸变黑、Scathy_N 面板看不清、Shirayuri_NS1 脸上黑块。
指令：**"取各含不同 shader 的模型各一个为代表，修复转化，然后我来看是否正确"**。

做法：写下 `_scratch\_csbake\probe_shader_blend.cs`，**在 Unity 里把 6 个 shader 一个个量出来**
（自建 quad + 1×1 贴图 + 顶点色 + 已知背景，渲染一像素读回；工程是 Gamma 空间）。

| shader | 实测公式 | 结论 |
| --- | --- | --- |
| `Sprites/Default`(10753)、`Particles/Alpha Blended`(203) | `out = src.rgb·src.a + dst·(1−src.a)` | ✅ 原映射就对 |
| `Particles/Additive`(200)、`Mobile/Particles/Additive`(10720) | `out = dst + src.rgb·src.a`（`src.rgb=2·i.color.rgb·_TintColor.rgb·tex.rgb`、`src.a=2·i.color.a·_TintColor.a·tex.a`） | ✅ 原映射对；**错在查看器**（见下） |
| `Particles/Multiply`(205) | **`out = dst·(1 − src.a·(1−m0))`**，`m0=2·i.color.rgb·_TintColor.rgb·tex.rgb` | ❌ 原来烘 `α=1−m0`（漏了 `src.a` 调制）→ **已修** |
| `Standard`(46) | 不透明、无 alpha 混合 | ⚠️ 仅 `BR_Andvari_NS2`，件 α=1 时等价，待单独核 |

**根因**：乘法件的 alpha 是"乘暗强度"的调制 —— `src.a = 0` 什么都不改、`src.a` 小影子就淡。
上一版把 texel 烘成 `rgb=0, α=1−m0`，于是**贴图半透/透明的地方也被画成实心暗块**
（Alice 的多边形淡影、May_NS3 的"整块胸发黑"、Shirayuri 脸上黑块全是这个）。

**修法**：`槽位颜色 = 000000 + i.color.a`（保留它的 alpha 时间轴）、
`texel := rgb=0, α = clip(2·_TintColor.a·tex.a·(1−m0))`。⇒ 运行时结果 = `src.a(t)·(1−m0)` ✓ 逐项对上。
实测效果（`_TintColor` 用内建默认 ⇒ α 倍率 1）：Alice 三个影子烘出来的 α `max 221 → 34`、`均值 44 → 6.8`；
May_NS3 胸影 α `均值 78 → 13.2`（max 245 → 91）；Shirayuri 三个影子 0/113/31.6；DrM 腿影 0/56/6.0。

**加色那侧错在查看器**：`D:\VB\Viewer\Render\v4\renderer_src\SpineRender.py` 的 `_drawSkeleton()`
原来只给 `blend==2`(multiply) 换混合函数，`blend==1`(additive) 仍在用普通混合
—— 加色区域贴图已按 `tex.a` 预乘，普通混合就会发暗/糊（Daphne、Scathy "面板看不清"）。
已修：`additive → (ONE, ONE)`。

**代表角色**（每个 shader 一个，交用户肉眼过）：`Alice_NS1`/`May_NS3`/`Shirayuri_NS1`/`DrM_NS1`（multiply）、
`Daphne_NS1`/`Scathy_N`（additive）、`Ran_NS1`（Mobile Additive）。

### 5.2 157 个角色批量

* **路线 A（录制+合并）**：每角色「探测 1 次 + 每 state 1 次 + 合并」，Alice 规模约 2–3 分钟；中间 `bake.json` 合计 3–5 GB（**合并完即删**）。
  **铺之前必须先读该角色的 AnimatorController 层**（`probe_layers.cs`）：只要有
  Base Layer 之外的层，就要给那些 state 加 `--overlay "<state>=<基底层默认状态>"`
  —— 否则那些动画的脚本修正会整个丢掉（§5.1.3 / 约束 15）。
* **路线 B（`--cs`）**：每角色一次转换（Alice 约 3 分钟，其中 CS 预跑占大头），**不需要 Unity**。
  建议：**先在 3–5 个角色上用 `cmp_products.py` 对比 A/B**，确认离群比例可接受，再铺；
  `cmp_products` 的最大值要先排掉"关键帧网格不同"造成的滑移（约束 17）。

  **✅ 2026-10-10 已全量跑完（157/157）**：
  * 第 1 轮（旧设定，带 `.json`）跑了 98 个后按用户要求停；第 2 轮 `--skip-done` + 新设定（skel-only）
    跑 61 个：**成功 60 / 失败 1**，69.5 分钟；失败那个 `BR_RoyalArsenal_NS1` 是零缩放 rig（约束 28），
    修完重转 66s 成功。单角色最快 17.3s / 中位 56.9s / 最慢 320.2s。
  * 全量完整性：`prefab 157 / 产物目录 157`，**缺目录 0、缺 skel 0、有 json 0、缺 atlas 0、config 名不对 0**。
  * 逐角色 QC（`tools\batch_static_check.py` → `static_check.py`）：**157 个角色的
    `missingAnimated` / `missingStatic` / `visibilityConflicts` / `unknownCurvePaths` 全部为 0**
    （62.3 分钟；首轮标红 2 个，查完都是工具侧保守误报：`BR_Phoenix_NS1` 的 4 个
    `hiddenBone_*` 用的是被屏蔽的编辑器辅助图 `BoneJoint_8`；`PECS_ElvenForestmaker_NS1_DL_N`
    的 `parts_Eyebrow_Normal`/`parts_Milk5` 是转换器有意排除的"始终 SetActive=0"备选件 ——
    `static_check` 已按这两类口径修好，复查均 0/0/0/0）。
  * 产物：`归档-proj-Mobile-old\_spine_conv_cs_port\<角色>\`（`.skel` + `.atlas` + 图集 png +
    `<角色>.config.json` + `_static_info.json` + `README.md`）。
  * 批量脚本 `tools\batch_cs_convert.py`（逐角色子进程、失败不中断、实时日志 + 汇总），
    日志 `_scratch\batch_cs_<时间戳>.log` 与 `..._summary.txt`。
  * **整项目备份：`D:\VB\lo_uncen2Spine\`**（跳过可公开获取的资料/源码/软件）：
    `Unity2Spine\`（转换器含 `info`/`_reverse`，排除 `third_party`/`_reference`/`delete`/`_probe50_rt4` 与
    `_scratch` 里的实验件）、`products\`（157 个 skel 产物 2.9GB + 基线/录制/tol001 0.37GB）、
    `deliverable\`（0.49GB）、`binding\`（spine3.8 pybind11 工程 + 查看器补丁）、`docs\`。
  **批量产出要求（2026-10-10 起）**：每角色出**两版** ——
  ① 正常版（`blend=multiply` + 用 `bake_multiply_opaque.py` 把乘法件贴图 α 置 1，即"精确版"）；
  ② 兼容版（再用 `bake_multiply_dark.py` 烘成黑+alpha，任何查看器都能看到暗影子）。
  两版只差那几个 multiply 槽位的颜色/混合，其余完全一致。
  跑之前先确认 `cs_runtime._parse_curve()` 的 bug 已修（约束 21 / §5.1.4），否则乳房这类
  Distribution 驱动的弹簧仍会差 ~20px。

### 5.3 空壳脚本的功能（换肤/部件开关）

`Actor.cs`（157/157 引用）、`ActorPartsView.cs`（56）、`CameraBoundary.cs`（2）仍是 AssetRipper 空壳。
这类**离散**影响更适合落成 Spine 的 `skins` / attachment 时间轴（"②移植"），不是逐帧烘焙。
转换中若发现"缺了换肤/部件开关"，再回头处理；**不影响动画放映**。

### 5.4 移植版的收尾项

* **DynamicBone：已完成**（逐粒子 481 帧最大 0.0009px，见 §5.1.4）。
* **spline（尾巴）：已完成**（`Catmull-Rom` 是仿射协变的，换不换度量都一样；
  `breast t=1.5` 的 `parts_Tail_B/F` 残差 0.0007/0.0012px）。
* **DynamicBone 的"启动瞬态"（Alexandra 后发链）：待对齐** —— 三个真值来源建粒子链的
  姿态不一样：录制 `runner_bake2.cs` 在**探测阶段之后** `resetDyn()`、验收 `verify_cs.cs`
  在**预制体静态姿态** `SetupParticles()`、转换器用 **clip t=0**。差别只在前几秒
  （Alexandra `B_hair`：`t=2.5` 差 6.6px → `t=5.0` 0.31 → `t=7.5` 0.015 → `<0.4px`）。
  **2026-10-10 已补录真值并定案**：`partdump\alexandra_db_particles.json`（lobby，
  200 帧，Hair 28 粒子 + Breast 6 粒子）证明移植版的 DynamicBone **逐帧逐粒子吻合到
  0.004px**（Alice 那条 7 粒子链是 0.0009px）⇒ **动力学没有偏差**。剩下的差就是
  "建链姿态"这一个约定：真值 dump 里 `particles[0].m_PrevPosition` 是**静态位置**、
  `m_Position` 是 clip t=0 骨位；而三个产物的 t=0 deform 是
  `基线 0.000 / 移植 0.000 / 录制 34.680` —— 说明这条 clip 的 t=0 姿态**就是绑定姿势**
  （所以"静态建链"与"clip 建链"在 t=0 等价），录制那份 34.68px 只能来自
  "探测阶段那个中间姿态"。实测改成静态建链更差（`移植-合并` 恒定 34.677px）。
  **⇒ 不改转换器（保持 clip 第 0 帧建链，对应"角色从该 clip 开头起播"）**；
  需要与录制真值逐像素一致时走录制+合并路线。已否掉：静态姿态建链、`pchild` 换
  `Transform.childCount`（逐位不变）、曲线/`m_Enabled`/IK 挂点（都不适用）。
* **IK（腿）：已排除（2026-10-10）** —— 补录了逐帧真值
  `_scratch\_csbake\partdump\alice_ik_breast.json`（Alice `breast`，200 帧 × 2 个 IK，
  每帧含**输入 pre** 与**输出 post** 的世界+局部 TRS；脚本 `dump_ik_chain.cs` + `ikdump.txt`），
  用 `t_ik_frames.py` / `t_ik_local.py` 对拍：**位置与旋转、输入与输出全部 0.000**
  ⇒ `Puppet2D_IKHandle.CalculateIK` 的移植版逐帧逐位正确。再加上
  `_ParentControls=0`、`_ffdControls=0`、`AimDirection` 已按 `FaceCamera` 复刻
  ⇒ **`GlobalControl.Run()` 里没有漏项**。
  ⚠️ 两个坑记一下：`GetAngle()` 单独调会 NRE（它读 `IK_CTRL`，而那个字段在
  `CalculateIK()` 里才赋值，见 `probe_ik.cs`）；`GlobalControl.Run()` 必须放在**帧循环外层**
  ——我第一版写在内层，于是第 2 个 IK 的 "pre" 采到"第 1 个 IK 已跑完"的值，
  表现为"右腿 pre 局部旋转差 17~22°"的假 bug（`probe_hidden.cs` 一句话戳破）。
  ⇒ `breast t=1.5` 剩的 p90/最大 **0.43/0.62px** 落在 `parts_leg_*`/`parts_Body`/
  `parts_Gatherbelt_Neck`。
* **骨头级已验完（2026-10-10）**：`dump_smr_bones.cs` + `t_smr_bones.py` 导出这 5 个部件
  的蒙皮骨头清单与每根骨的**世界+局部 TRS**（200 帧，跑法与 `postStep` 一致，真值
  `partdump\alice_smr_bones.json`）⇒ **每根骨的局部位置/旋转/缩放全 0.000px / 0.0000°**
  （乳房那两根 DB 骨 0.004~0.007px）⇒ **骨头输入没有错**。
  ⚠️ 比"骨头对不对"**只能用局部量**：世界矩阵上提取旋转（`mat4_quat` 的 Gram-Schmidt）
  和 Unity 的 `Transform.rotation`（层级四元数相乘）在 `Size_root` Z 缩放 0.001 造成剪切时
  本来就不等，用世界量比会看到 6~84° 的假差异。
* **蒙皮/绑定也验完了（2026-10-10）**：`dump_skin.cs` + `t_skin.py`（真值
  `partdump\alice_skin.json`）在 A=纯 clip 与 P=A+`GlobalControl.Run()` 两种姿态下，
  对 5 个部件查三层：①`sharedMesh` 顶点/bindposes/bones/boneWeights 与 Unity **逐项一致**
  （顶点 ~1e-7、bindpose ~5e-8、骨头逐名对应）；②把 Unity 的位移场 `u=P−A` 最小二乘映射到
  移植版的位移场 `p` ⇒ **拟合残差全部 0.000000**（`p = k·u`，`k` 就是逐部件的
  `1/|lossyScale|`：Body 8.037、Gatherbelt/leg_L 1.0101、leg_R 1.000000）。
  ⇒ **`_skin_mesh`（蒙皮/绑定）与骨架都精确**。
  ⇒ 剩余 ≤0.43px 的唯一去处是 **"逐部件单位换算/标定"**：移植版用理想
  `unit_k / |lossyScale|`，而 `merge_report*.json` 的 `S` 是从录制数据最小二乘拟合的，
  两者差 ~0.1%，在 290px 位移上即那 0.4px。**这是"口径"问题，不是 CS 运行时的错。**
  ⚠️ 对拍脚本两个坑：`rt.local = lv` 是同一 dict，`run_global_control` 会就地改写它
  （必须传 `dict(lv)` 副本，否则下一个部件的 A 姿态被污染）；移植版 `_skin_mesh` 输出在
  "转换器空间"，和 Unity 世界差一个**逐部件**的 `1/|lossyScale|`，所以只有 (P−A) 差值或
  拟合残差才有意义。

---

### 5.5 ⏳ 用户新检查出的 9 条（`Sampler.txt`，2026-10-10）—— 当前待办清单

用户按肉眼检查给的清单；分两类，逐条附**目前的分析**（未修的都在这里排队）：

**A. 怀疑 shader（用户要求：检查所有引用的 shader、转换器能自动识别不同部件的 shader、可指定特殊 shader 的识别如 uuid）**

| # | 角色 | 症状 | 目前分析 |
| --- | --- | --- | --- |
| A1 | `2DModel_BR_Echidna_NS1` | 灯光闪烁特效 | 清点过：Echidna **没有**用非普通混合材质 ⇒ 不是混合模式问题。嫌疑是**特效靠材质属性/α 动画闪烁**，而当前链路不导出"颜色时间轴"（§14.4 的历史结论是"这批曲线在 Unity 里没生效"，但对 Echidna 要单独核）。待查：它的 clip 里这些件的曲线类型（`m_FloatCurves` / `m_Color`） |
| A2 | `2DModel_BR_May_NS3` | `parts_Breast_Shadow_Multiple_015_Skinned` 的阴影 | ✅ **已修两轮**：① `mesh_style()` 以前**永远返回 normal**，蒙皮/静态网格的乘法件全被当普通透明（同类的还有 `parts_Machine_Shadow_Multiple_012_Skinned`）；② 按 T14 指令改成**默认把乘法烘进图集**（槽位 `normal`、texel = 黑+α=1−m），**不依赖运行时的 multiply 支持**，逐像素验收见 §5.1.8 |
| A3 | （可能还有别的） | — | 已做全量清点：157 个角色只用到 6 种 shader（`Sprites/Default` 157、`Particles/Additive` 14、`Particles/Multiply` 12、`Particles/Alpha Blended` 2、`Mobile/Particles/Additive` 1、`Standard` 1），其中 **25 个角色**用到非普通混合。工具：`tools\shader_usage_inventory.py` |

**B. 怀疑算法/转换**

| # | 角色 | 症状 | 目前分析（待逐条验证） |
| --- | --- | --- | --- |
| B1 | `2DModel_BR_PXSilky_NS1` | 胸口运动很奇怪 | 嫌疑：胸前那条 DynamicBone 链（`m_Children` 顺序 / `bone_total` / `_apply` 分支） |
| B2 | `2DModel_BR_RoyalArsenal_NS1` | 右腿像镜像翻转 | 这个 rig **Z 局部缩放 = 0**（§22.3 的退化 rig），且 IK 的 `Flip` 会决定 `num=±1` 与 `AngleAxis(±90,UpDirection)`；嫌疑在"退化 rig + Flip 分支"的组合 |
| B3 | `2Dmodel_BR_Tomoe_NS1` | `breast` 的头发整个飞出去 | ✅ **已修（2026-10-11）**：根因是**弹簧链状态**（点击动作要从 idle 的稳态起跑），**不是** spline 写飞。真值口径 `preroll=lobby:2.0`：改前最大 **916px**（另有 272/244/43.8px），改后 **≤1.50px**。见约束 33 / 进展 §30 |
| B4 | `2DModel_DS_KunoichiKaen_NS1` | `breast` 嘴巴相对上移（最多移到鼻子） | ✅ **已修（2026-10-11）**：根因是 **`±Infinity` 切线（常值段）被当成插值段** —— `Bone_Mouth_Root` 的位置曲线 `0.8167→4.2s` 本该"保持不动"，被插成了 3.4s 的斜线。与 HiddenBone/换装无关。见约束 34 / 进展 §31 |
| B5 | `2DModel_PECS_Cerberus_NS1` | 头发飘得像纸一样翻转折叠 | ✅ **已修（2026-10-11）**：同 B3（弹簧链状态）。真值口径 `preroll=lobby:2.0`：改前最大 **27.2px**，改后 **≤0.98px**。见约束 33 / 进展 §30 |
| B6 | `2DModel_PECS_Ignis_NS1` | 像多个 Clip 挤在一个状态（动作分离） | 这是 FX 重的角色（16 normal + 6 additive 材质）。先核 **Animator 层**（多层要用 `--overlay`，§5.1.3/约束 15）与该 state 的 clip 数量；用户建议"必要时写 json 配置读取" |
| B7 | `2DModel_PECS_LRL_N` / `LRL_N2` | `Tep_1`/`Head` 头发乱飞、像纸片露头皮 | ✅ **已修（2026-10-11）**：同 B3/B5（弹簧链状态）；已随 90 个带 CS 的角色一起重转。见约束 33 / 进展 §30 |

> 复现要点：每条都先用 **`tools\bake_cs\verify_merge.py`** 或 `_scratch\_csbake\t_*.py` 拿"Unity 真值 vs 产物"
> 定位是**算法**（CS 解算）还是**产物写出**（deform/attachment/混合）的问题，再动代码；不要凭感觉改。

### 5.6 ✅/⏳ 2026-10-12 的口子：`EventDynamicBone`（已实现，未定论）+ **重转 45 个角色**

**A. ✅ 已实现、待定论：`EventDynamicBone` 事件 + 参数刷新档**（约束 42 / 进展 §35.9、§36.3）

`unity_anim2d.parse_clip` 已解析 `m_Events`；转换器加了
`U2S_CS_DB_REFRESH=frame|event|off`（**默认 `frame` = 旧口径，产物不变**）。
Alexandra 头发骨实测：`frame` 中位 0.0190 / `event` **0.0155** / `off` 0.0580
⇒ `off` 明显错、`frame` 与 `event` 只差一点点（机制仍未定论）。
**要换成 `event` 之前先把 §36.3 的表在更多人身上复一遍。**

**B. ⏳ 待办（优先级最高）：按"弹簧会被 clip 关掉"的新口径重转 45 个角色**（约束 44 / 进展 §36.4）

`m_Enabled` 曲线这次真的接上了（默认 `U2S_CS_DB_ENABLED=1`），
但产物还是旧口径。清单：

```
_scratch\db_enabled_union_20261012.txt      # 45 个（并集）
_scratch\db_disabled_chars_20261012.txt     # 17 个：某条 clip 里整条链恒 0
_scratch\db_flip_chars_20261012.txt         # 43 个：某条 clip 里 0→1（= 中途重置链）
```

重转（照抄，逐角色子进程、可续跑）：

```powershell
cd D:\VB\Unity2Spine
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
python tools\batch_cs_convert.py --exact-file _scratch\db_enabled_union_20261012.txt
```

只做了冒烟导出（Cerberus）：`[cs] Tep_1 DynamicBone 的 m_Enabled 曲线：3 条链`、
`static_check` 全 0 ✓。回退：`$env:U2S_CS_DB_ENABLED="0"`。

**C. ✅ 已结案：Cerberus 裙骨 `Bone_skrit_LF_*` 差 0.58**（约束 46 / 进展 §36.5）

两个原因，都已定位并解决：

1. **假误差（主因）**：真值里有**两套同名裙骨子树**（`Bone_skirt_L_set/…` 与
   `Bone_skirt_L_set_R/…`，22 个同名节点）。对拍脚本按**末段名字**配 ⇒ 两套互相比 ⇒
   0.58（530px）。改用**按完整路径**配（新工具 `_scratch\_probe\t_db_paths.py`）后，
   输入段 `Skirt_set/bone_Skirt_L/Skirt_L` 只有 **0.0017**，`_R` 那套 0.0016 平。
2. **真误差**：只剩 DB 链（`Skirt_L` 链）那套，且**沿链增长**（0.0149→0.0252→0.0648）
   = 典型的"弹簧在跑 vs 不跑" ⇒ 正是约束 44 那个 bug（Unity 里 `Skirt_L.en=0`）。
   接上 `m_Enabled` 后：最大 **0.087 → 0.0117**，多数降到 `_R` 那套的 1.4px 基线。

---

### 5.7 2026-10-12 第一轮的口子（已归档）：`EventDynamicBone` 原始记录

**唯一还值得动的算法项**。已知：clip 里有 **244 个 clip / 572 个 `EventDynamicBone` 事件**
（`data` = DB 名），而所有 DB 的 `RefreshParam=false`、导出工程里事件接收者又丢了。
现在的"逐帧刷字段曲线"是近似做法，且实测比"完全不刷"更贴 Play 真值，但机制没定论。

**动手顺序**（别跳，每步都能单独验收）：

1. `probe_db_fields.cs` 扫 157 个角色的 `RefreshParam`（确认是否全 false）；
2. `unity_anim2d.parse_clip` 加 `m_Events` 解析 → 把事件按 `data` 名配到 DynamicBone；
3. 转换器加三档开关 `U2S_CS_DB_REFRESH=frame|event|off`，在
   Cerberus/Alexandra/Tomoe/Kaen 上对 Play 真值（`t_db_pre.py --usedt truth`）比
   "头发部件质心 + 逐顶点"，取最贴的当默认；
4. 定稿后重转受影响角色（先扫清单）。

⚠ 不要在那之前先改默认口径：现在 Cerberus/Alexandra 的**逐帧刷**版本在
"逐粒子口径"下已经验到 0.0004~0.003px（约束 41），别为了这条把已验收的东西推翻。

## 6 复现命令（照抄）

```powershell
cd D:\VB\Unity2Spine
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"

# ① 基线
python -m ngui2spine.static_prefab_spine <prefab> _spine_conv\<角色> `
  --assets <工程>\Assets --skel --no-face-check

# ② 路线 B：转换器自己算 CS（不依赖 Unity）
python -m ngui2spine.static_prefab_spine <prefab> _spine_conv_cs_port\<角色> `
  --assets <工程>\Assets --skel --no-face-check --cs

# ③ 路线 A：采集 -> 合并 -> 验收
cd tools\bake_cs
python run_bake.py   --product <基线产物> --prefab <prefab> --outdir <bake 目录>
python merge_cs_bake.py --product <基线产物> --bake <bake 目录>\bake.json `
  --out <合并产物> --report <bake 目录>\merge_report.json
#    验收：先在 _scratch\_csbake\verify.txt 填 prefab/state/time/out/parts
python mcp_exec.py ..\..\_scratch\_csbake\verify_cs.cs
python verify_merge.py --product <基线产物> --merged <合并产物> `
  --verify <verify.json> --calib <merge_report.json>

# ④ 两条路线的产物对比（最终验收）
python cmp_products.py --a <移植版产物> --b <合并产物>

# ⑤ 离线渲染对比（要用 v4 的 venv）
& "D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe" render_cmp.py `
  --base <基线产物> --merged <合并产物> --anim <动画名> `
  --times 0.5,2.0,4.0 --out <图片目录>

# ⑥ MCP 起服务（若没在跑）
#   uvx --from mcpforunityserver==10.3.0 mcp-for-unity --transport http --http-port 8080
#   Unity 里 Window -> MCP for Unity 点 Connect
```

---

## 7 文件地图（关键路径速查）

```
D:\VB\Unity2Spine\
    src\unity2spine\convert\static_prefab_spine.py     主转换器（--cs 开关在这里）
    src\unity2spine\convert\cs_runtime.py              CS 离线复刻（样条/IK/DynamicBone）
    src\unity2spine\convert\convert_2dmodel.py         几何/蒙皮工具（_skin_mesh/_world_matrices）
    src\unity2spine\unity\unity_mesh.py                矩阵工具（mat4_mul/invert/vec）
    tools\bake_cs\                                     录制+合并+对账全套（见 §3.2）
    tools\rt_frames.py                                 单进程多帧渲染（RENDER_ROOT 已指向 v4）
    _scratch\_csbake\                                  MCP 片段 + plan/verify + 中间数据

D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\
    Assets\Raw\Scripts\                                游戏脚本（DynamicBone/Puppet2D 等）
    Assets\Raw\Scripts\PartDataRecorder.cs             逐帧导出组件（挂上去按 F9）
    Assets\Editor\PartDataExport.cs                    编辑模式逐帧导出（A/B）

D:\VB\Search\New\
    Mobile-old_Spine转换_交接文档.md                   ← 本文
    Mobile-old_CS烘焙_方法与进展.md                    过程记录（逐轮排查/证据表）
    Mobile-old_转Spine_条件与目的.md                   开工前条件快照
    _Spine待检查_20261009\                             给人检查的包

D:\VB\Viewer\Render\v4\                                离线渲染器（venv 在同目录 .venv）
```

---

## ★ 2026-10-12 晚 追加：参考真值里**没有** DynamicBone 的写回（判"摆幅"前必读）

### 约束 51：`_refshot_u2s\*.jsonl` 的落点是 `DynamicBone.LateUpdate` **之前**

* 事实（逐帧精确配对，`_scratch\_probe\q5_probe_vs_truth.py`，同一次 Play 的 `Time.time`）：
  真值里的 `Hair` 骨世界位置 **= 弹簧写回之前**的变换（121/121 帧差 **0.000000**），
  与"写回之后"的粒子位置差到 **0.0858**（根粒子）/**0.2146**（整条链）。
* ⇒ **`Update()` 里的 `PreUpdate→InitTransforms`（把粒子骨钉回 `m_Init*`）跑过了，
  `LateUpdate()` 里的物理 + `ApplyParticlesToTransforms` 还没跑**。
  参考数据里**永远看不到弹簧**；而**渲染前最后一刻（`WaitForEndOfFrame`）能看到**。
* 因此：
  1. **不要**用参考真值去判"弹簧对不对" —— 弹簧只能与"编辑模式驱动 Unity 自己的
     DynamicBone"（`dump_db_particles.cs` / `PartDataExport` 的 B 档）对拍（约束 41）。
  2. 同理，其他 CS（`Puppet2D_GlobalControl`）在 dump 之前写骨头，所以**参考里能看到**
     （Cerberus 的类弹簧运动就来自它，不是 DynamicBone）。
  3. 判"产物摆动是否过大"**必须先说清口径**：参考（无弹簧）还是实时渲染（有弹簧）。

### 约束 52：判"摆动太大"的口径数字（Alexandra `Tep_1`，`parts_B_hair`）

| 口径 | 头发链弹簧量 | 我们产的 vs 它 |
| --- | --- | --- |
| `_refshot_u2s` 参考（= 现有验收基准）| **0**（纯动画；`--nocs` 复刻 0.00046 世界单位 = 0.34px）| 中位 0.006 / 最大 **0.18**（≈132px）|
| Play 实时渲染（探针 `E` 相位）| 最大 **0.2146** 世界单位（≈157px），中位 0.033 | ≈ 同量级 |

⇒ 用户说的"我们导出摆得特别大、Unity 只是摆动"，**差值就是弹簧本身**；不是算错。
**待用户拍板**：(A) 产物对齐参考（不烘弹簧，样例已出）还是
(B) 保留弹簧、把参考重录到"渲染前一刻"。

### 新增/变更的工具（工程内）

| 文件 | 说明 |
| --- | --- |
| `Assets\Raw\Scripts\U2SDbProbe.cs` | **新增**：Play 期三相位（Update / LateUpdate / WaitForEndOfFrame）逐帧 dump 每条 DynamicBone 的运行时状态 + 链形状；工程根放 `u2s_dbprobe.flag` 才启动，输出 `_refshot_u2s\dbprobe.txt` |
| `Assets\Raw\Scripts\U2SFrameDump.cs` | 修 `db[].dev` 恒 0 的工具 bug：`GetField("m_Transform", Instance|NonPublic)` 漏了 `Public`（`Particle.m_Transform` 是 public 字段）|
| `_scratch\_probe\q1..q6_*.py` | 判"真值里有没有写回 / 录制落在哪个相位"的一套判据（见进展 §38.5）|

### 样例产物

---

## ★ 2026-10-13 追加（全量重转暴露的口径泄漏）

### 约束 54：**每角色口径必须写进 `tools\per_char_env.txt`，否则批量重转会回退**

`batch_cs_convert.py` 会读 `tools\per_char_env.txt`（每行 `名字子串<TAB>K=V[;K=V]`）注入子进程，
并在日志打印命中项。已登记：

```
2DModel_BR_Echidna_NS1	U2S_LAYER_PHASE=0.499          # 叠加层相位（进展 §37.9）
2DModel_PECS_Ignis_NS1	U2S_FORCE_INACTIVE=NoChain:parts_BP_028
```

证据：2026-10-13 全量重转后 Echidna 账本 `layerPhase` 变成 **0.0**（用户报"灯光又坏了"）。

### 约束 55：**`U2S_FORCE_INACTIVE`** —— "状态不被驱动 ⇒ clip 的 `m_IsActive` 不算数"

判据链（Ignis `parts_BP_028_*`）：预制体默认 `m_IsActive=0` + clip 写 1 + **该状态在状态机里
0 条 transition（只能靠脚本 `Play(state, layer)` 切）而 Unity 从未切进去** ⇒ 曲线的 1 从未生效
⇒ 产物必须按"预制体默认（关）"处理，否则多出"不动、悬浮"的部件。

开关：`U2S_FORCE_INACTIVE="<动画名子串>:<部件名前缀>[;…]"`（转换器 `node_visible()` 里强制 v=0）。

### 约束 56：harness **状态在额外层时录不到**（已修）

`Bresat_Layer` = 层 1（`m_DefaultWeight=1`；Base Layer 权重是 **0**）。
`U2SFrameDump` 现在支持 `animatorLayer`（计划行第 7 段 = 层号）、
`SetLayerWeight(layer,1)` + `Play(name, layer, 0)`，`anim` 记 `GetCurrentAnimatorStateInfo(animatorLayer)`。

### 用户 2026-10-13 报的 7 条问题清单（进展 §39.4 有逐条进展）

`ConstantiaS2_NS1`(breast 脸不变) / `Eternity_NS2`(冰淇淋层级) / ~~`BloodyPanther_NS1`(说没导出
—— 用户 2026-10-13 确认转换出来了，本条作废)~~
/ `Brownie_NS1`(头发乱摇) / `Echidna_NS1`(灯光) / `Cerberus_NS2`(腿闪) / `Ignis_NS1`(固定块)

### 约束 58：PPtr（`m_Sprite` 换图）条目的**两种写法**都要能解析

`m_PPtrCurves` 的条目有两种开头：`  - serializedVersion: N`（旧）与 **`  - curve:`**（本工程这批）。
解析只用前者 ⇒ `pptr` 恒空 ⇒ **换表情时间轴既不上报也不导出**（用户报的
`ConstantiaS2_NS1`"breast 脸不会变"）。已改成两种都收（`unity_anim2d.py`）。
判据：转换日志出现 `[anim] 检测到 Sprite 交换动画（换贴图/换表情）…` 且账本 `spriteSwap` 非空。

### 约束 59：**"绑不上"的 `m_IsActive` 曲线 = 运行时死曲线**（判据：编辑模式切层实测）

Ignis `parts_BP_028_1..5_Skinned` 在预制体里默认 `m_IsActive=0`，而 `Chain_*` 的 clip 把它们写成 1。
**但运行时它们从不显示** —— 用 `_scratch\_csbake\probe_ignis_layer1.cs`（编辑模式
`Instantiate` + `SetLayerWeight(1,1)` + `Play("Chain_Breast_NoChain",1,0)` + `animator.Update(0)`）
实测：layer 1 确实切到了目标状态（`len=5.666667`），而这 5 件仍然
**`activeSelf=0 / activeInHierarchy=0`**（`Chain_Breast_Fall_Down` 同样）。

* 原因：它们在 **Animator 的绑定子树之外** —— 预制体路径是双根
  `…/2DModel_PECS_Ignis_NS1/parts_BP_028_1_Skinned`，而 clip 里写的是单根
  `parts_BP_028_1_Skinned` ⇒ Animator 绑不上 ⇒ **曲线是死的**（对比：
  `AnimationMode.SampleAnimationClip` 却会把它们置 1 —— 两种路径解析口径不同，
  **判"运行时可见性"一律以编辑模式切层/Play 实测为准**）。
* 处理：`U2S_FORCE_INACTIVE="*:parts_BP_028"`（`*` = 所有动画）；已在
  `tools\per_char_env.txt` 登记。
* 通用启示：这类"路径绑不上"的可见性曲线应当**自动识别**（比对 clip 路径与
  Animator 子树的真实路径），而不是靠手工例外表（`dead_active_paths`）——
  待做；目前先用每角色口径顶着。

### 约束 60：弹簧链"有历史"⇒ 预跑必须**按动画可配**，秒数要按真值扫

* 开关：`U2S_CS_PREROLL_<动画名>=<预跑状态>[:<秒>]`（写进 `tools\per_char_env.txt`）。
  实现点在 `static_prefab_spine.py` 的"建 runtime + 预跑"那步（本转换器每条动画都重建
  runtime，所以直接换预跑来源即可，无需快照缓存）。
* 证据（Brownie `lobby`）：两条 Unity 真值（先播 lobby vs 先播 Start）**第 0 帧头发差 44.6px**；
  预跑 `lobby` 6s → 与 `fromStart` 真值最大差 **37px**，`Start` 2s → **18px**（扫过 1/2/3/4/6s）。
* 判据：日志 `[cs] <动画>：预跑改用 <状态> <秒>s（U2S_CS_PREROLL_<动画>）`。
* 结论：**任何"入场/点击"类动画的上游状态不同，都要单独配预跑**；扫秒数的成本很低
  （`_scratch\_probe\t_db_pre.py --preroll <状态>:<秒>` 每次 ~20s）。

### 约束 61：录 Play 真值前必须 `Animator.cullingMode = AlwaysAnimate`（否则后半段是假数据）

* 症状：`rnd` 顶点从某一时刻起**逐帧完全一样**（实测 t≈1.05s 起重复 300+ 帧），
  但 `anim.normalizedTime`/`dt` 一直在走、控制台**没有**顶点异常告警。
* 真凶：`Animator` 默认 cullingMode 在"角色不在任何相机里"时**跳过骨骼 transform 写入**
  ⇒ 骨位冻结 ⇒ 顶点冻结（`normalizedTime` 照样推进）。
  `runInBackground`、`SkinnedMeshRenderer.updateWhenOffscreen` **都治不了它**。
* 修法（`U2SPlayQueueRuntime.cs` 实例化后）：
  `ani.cullingMode = AnimatorCullingMode.AlwaysAnimate;`（另开 `runInBackground` 更稳）。
* 判据：录制完算一次"`rnd` 相邻帧哈希重复数"= **0** 才算全片有效；
  `_scratch\_probe\` 下用一条 10 行的哈希统计即可（本次：修前 308/376 重复、修后 0/385）。
* 影响面：**以前所有 `_refshot_u2s` 真值的后半段都可能是冻结的**，凡"后段逐帧比对"的结论
  都要用新口径重录复核（例：#6 原先"我们 3.1s 多一闪"就是这么来的假结论）。

### 约束 62：**批量产物只带"批次启动那一刻"的代码** ⇒ 改完代码要按影响面补转

* 教训（2026-10-13）：5 小时全量（08:55 启动）跑完后才发现，它**没有**带上 12:00 之后
  实现的所有修复（`m_PPtrCurves` 解析、每角色口径表、min-rank drawOrder、
  `_key_vals_differ`、`_scale_collapsed`）—— 判据是**全量日志里一条 `每角色口径` 都没有**。
  被全量覆盖掉的单转还有一次：Ignis（`[145/157]` 把它 12:59 的修复冲掉了）。
* 正确做法：改完代码后**扫影响面再按名补转**，不要以为"全量=最新"。本次扫描结果：

| 晚修项 | 扫描判据 | 影响面 | 处理 |
| --- | --- | --- | --- |
| `m_PPtrCurves` 换图 | clip 里有 `m_PPtrCurves` + `m_Sprite` | **3 个角色**（ConstantiaS2_N/NS1、CoCoWhiteShell_N） | 已补转全 OK |
| 每角色口径表 | 全量日志无 `每角色口径` 行 | Echidna/Brownie 已单转过 ✔；**Ignis 被覆盖** | 已补转 |
| min-rank drawOrder | clip 里有 `m_SortingOrder` | **15 个角色** | 17 名批量重转中 |
| `_key_vals_differ` | clip 里"同刻两键、值相同" | **28 clip / 15 角色**（6 个与上一条重合） | 余 9 个已补转 |
| `_scale_collapsed` | 祖先链上有塌缩 scale | **未观察到命中**：Cerberus_NS2 已证不命中（锚点/零件不在那条链上），
  且文本扫描全工程 `.anim` **没有** `m_LocalScale` 塌缩曲线（该 rig 的塌缩是**蒙皮 scale**，
  由骨的世界矩阵带入，不走父链） | 暂不补转，留观察 |

* 附带：`SkinnedMeshRenderer.updateWhenOffscreen` / `runInBackground` 都**治不了**
  "骨位冻结"那类真值坑（见约束 61），只有 `Animator.cullingMode = AlwaysAnimate` 有效。

### 约束 63：`per_char_env.txt` 的**格式坑**：条目必须自成一行的开头，**不要粘在注释行末尾**

* 2026-10-13 踩到：前几次改表时，条目被追加到了 `#` 注释行的末尾（变成
  `# ……注释……2DModel_PECS_Ignis_NS1<TAB>U2S_FORCE_INACTIVE=…`），而读表逻辑是
  `line.split("#", 1)[0]` ⇒ **整条口径被当注释截掉** ⇒ 表现是"批量日志里一条
  `每角色口径` 都没有"，很难一眼看出（那次还白跑了 Ignis 610s 一次）。
* 判据：每次改完表，跑
  `python -c "import io;print([l.split(chr(9),1) for l in io.open(r'tools\per_char_env.txt',encoding='utf-8-sig') if l.split('#',1)[0].strip() and chr(9) in l.split('#',1)[0]])"`
  —— 必须打出**每一条**规则；批量日志里必须出现 `每角色口径 …` 行才算生效。
* 现在表里 3 条（Echidna 相位 / Ignis `*:parts_BP_028` / Brownie `Start:2.0`）已确认可解析，
  Ignis 已按此重转。

### 约束 64：**交付件必须是"—最新代码转出来的那一份"**（验证写 scratch 的坑）

* 2026-10-13 用户反馈"ConstantiaS2_NS1 breast 脸还是不变"：数据其实早已修好（带 `--json` 抽查，
  `breast` 的 slot 上有 `face_ani_12 → __2(0.117s) → __3(1.55s) → 原脸(2.27s)` 的时间轴），
  但**交付目录里那份是修前导出的** —— 当初"验证修好"的那次写进了 `_单角色检查_…\`（scratch），
  没覆盖 `_spine_conv_cs_port\`。
* 规矩：**验证用产物也要写进交付目录**，或验证通过后**立刻覆盖交付件**；交付件只看
  `<角色>\<角色>.uAnim_static.skel` 的**时间戳**与账本内容。
* 2026-10-13 收尾时按用户要求：清掉所有旧检查件（搬到 `D:\VB\Search\del\`，可回退）
  + **重新全量转一份**（157 个角色，当前代码与口径表）⇒ 从此不再有"新旧混装"。

### 约束 57：`m_SortingOrder`（渲染排序）是可动画的 ⇒ 必须写成 Spine `drawOrder` 时间轴

* 全工程 **31 个 clip / 227 条** `m_SortingOrder` 曲线（Draculina 27、Orangeade 24、Alice_NS2 15、
  BloodyPanther 12、Poi 7、**Eternity `SpecialTouch` 冰淇淋 50→32** …）。
* Spine 3.8 的 `offsets` **只能非负**：列出的槽占领 `setupIndex + offset`，未列出的槽按 setup
  升序填空位。⇒ "某件跑到自己 setup 序号之前"必须靠"把挡它的那些槽往后挪"来编码。
* `draw_order_offsets()` 已按真实语义改成**模拟式**编码（2026-10-13）；仍有"整体逆序/多件交错
  往前挪"这类**无法表达**的帧会被跳过（Eternity `SpecialTouch` 127 帧）。
* **完整解法**：骨架 setup 顺序取"每件在整条动画集里的**最小名次**（min-rank order）"，
  且**每条动画 t=0 落一个 drawOrder 键**；这样任意帧都满足 `rank ≥ setup` 可表达。
  代价：这些角色的 setup 姿态观感变化，需连 `_calib` 一起复验。
* ✅ **2026-10-13 已实现**（进展 §39.11）：`_min_rank_of_slots()` + setup 重排 +
  "无排序曲线的动画补 t=0 键"。Eternity_NS2 由"SpecialTouch 1 键/127 跳过、
  NormalTouch_noice 1 键/308 跳过"变为**全部 0 跳过**；
  `_scratch\_probe\verify_minrank.py` 回放校验 25 个 (动画,时刻) **0 个表达不了**。
  **判据提醒**：只能"用编码器 offsets 回放 == 目标顺序"来判；"每件名次 ≥ setup"
  只是充分条件（编码器允许把挡路的槽往后挪）。
* 受影响并已重转的 **15 个角色**：Alice_NS2、Eternity_NS2、Poi_NS1、Vanilla_NS1、
  BloodyPanther_N/NS1、Cheona_NS1、Gnome_NS2、Khan_N/NS2、KunoichiZero_NS1、
  Cerberus_NS3、Circe_NS1、Draculina_NS1、Orangeade_NS1。
* 判据日志：`[drawOrder] <动画>：采样 N 帧 → 写 M 个关键帧（K 帧表达不了已跳过）`；
  `[layer] x/y 个部件相对层级会变（当前未启用多 drawable…）`。K>0 就说明还有层级没表达出来。

`D:\VB\Search\New\_Spine待检查_20261012_去弹簧对照\`

* `2DModel_3P_Alexandra_NS1\` —— 不烘弹簧（口径 A）；
* `有弹簧_当前代码\2DModel_3P_Alexandra_NS1\` —— 当前默认（`--cs`）。

### 约束 53：弹簧摆幅 ∝ "动画每步走多远"（放慢动画 ⇒ 摆幅变小）；烘进动画的弹簧**不会**跟着变

* 机制：`DynamicBone.UpdateParticles1/2` **没有 dt**（逐步积分），`m_UpdateRate=60`
  把步长钉在 1/60 s ⇒ 驱动量是"每步动画走多远"。放慢动画（步长不变）⇒ 摆幅按比例变小；
  帧率变低（一帧最多补 3 步、余数丢弃）⇒ 弹簧按实时时间变慢。
* 复现工具 `_scratch\_probe\q7_speed_sweep.py`（Alexandra `Tep_1`，步长 1/60）：
  **1.00× max 0.169（124px）/ 0.50× 0.093 / 0.25× 0.066**；单根骨整段最大位移
  0.286 / 0.190 / 0.134。
* 后果：产物是**固定轨迹**，放慢播放只是拉长时间、**摆幅不变**；而实时 Unity 的弹簧会变弱。
  ⇒ 在慢放状态下比较"产物 vs Unity"会系统性显得产物偏大，**不是转换误差**。
* 游戏本身是 1.0×（Alexandra controller 8 个 state 全 `m_Speed: 1`、无 speedParameter）
  ⇒ 转换器"1/60 + 1.0×"就是游戏口径（实测 0.169 vs 实时 0.2146，同量级）。
* 用户口径已定：**取 B（保留弹簧）**；参考数据的录制口径待改（见约束 51 的 (B)）。
