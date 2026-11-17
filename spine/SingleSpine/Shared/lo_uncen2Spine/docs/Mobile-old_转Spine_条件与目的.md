# Mobile-old：Unity Animation → Spine 转换 · 条件与目的

> **路径对照（2026-10-14 目录分区后补注）**：本文写于旧目录结构（老主仓 `D:\VB\Unity2Spine`）。**正文的结论/数据/手段仍然有效**，只是路径要换算 —— 对照表见 [路径对照.md](路径对照.md)（工具现在在 `src\tools\`，配置在 `config\`，第三方在 `deps\`）。

> 写于 2026-10-08。本文是**开工前的现状快照**：把"手上有什么条件、已知什么问题、要达成什么目的"钉死，
> 免得中途重查。数字都是本次实测。

---

## 1 目的（要做什么）

把 **`D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old`** 里
**以 Unity Animator 驱动的 2DModel 动画模型（`*.uAnim.prefab`，共 157 个）**
用 **`D:\VB\Unity2Spine`** 的离线转换器转成 **Spine 3.8**（`Root` + 每部件 mesh + `deform` 时间线，含 `.skel`），
并**清掉不再需要的旧文件**。

为什么是这批：

| prefab 类型 | 数量 | 说明 | 是否本次目标 |
| --- | --- | --- | --- |
| `*.uAnim.prefab` | **157** | Unity `Animator` + `AnimatorController` 驱动的立绘（Sprite + SkinnedMesh） | ✅ **本次转这批** |
| `*.Lihui.prefab` | 1150 | 静态立绘（整图） | ❌ 不转 |
| `*.Spine.prefab` | 13 | 已经是 Spine（4.1 导出） | ❌ 不转（另有更全的 PC-new 版） |

参照物：**`归档-proj-PC-new\proj-PC-new`**——同一款游戏的新版工程，**已经有 102 个 Spine 模型包**
（`Assets\Spine\2dmodel_*`，Spine 导出器 4.2.43），可以当"转出来应该长什么样"的对照。

---

## 2 条件（手上的资源与技术栈）

### 2.1 两个工程的版本差

| 项 | Mobile-old（本次要动的） | PC-new（参照） |
| --- | --- | --- |
| 路径 | `D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old` | `D:\VB\Search\New\归档-proj-PC-new\proj-PC-new` |
| Unity | **2021.3.45f2c1** | 6000.0.84f1 |
| spine-unity 运行时 | **4.1.43**（`Assets\Spine\{Runtime,Editor}`） | 4.2.120（`Assets\Spine\Packages\…`） |
| Spine 导出器版本（json 内 `skeleton.spine`） | **4.1.08** | 4.2.43 |
| 模型包数（`Assets\Spine\2dmodel_*`） | 13 | 102 |
| prefab 数 | 1320（uAnim 157 / Lihui 1150 / Spine 13） | 313 |
| 资源根 | `Assets\Raw\{Mesh,Sprite,Material,AnimatorController,AnimationClip,Texture2D,Avatar}` | 同左（结构不同层级） |
| 场景 | `Assets\Sences\save.unity`（注意目录名是 **Sences**） | `Assets\Scenes\…` |

> 两边 Spine 数据对照结论（`Spine对照-BR_Alvis_NS2\README.md`，已实测）：
> 骨架 bones/slots/skins/animations = 209/177/9/6 **两边一致**；atlas **逐字节相同**；
> **唯一实质差异**是 4.2 导出器把 slot 名里的 `/` 改写成 `-`（22 个，形如 `face/parts_face_shy` → `face-parts_face_shy`）；
> 另有一处 page2 声明 `1404²` 而实图 `1024²`（等比 0.7293 缩放，**游戏自身管线所为，非缺陷**，只影响清晰度）。

### 2.2 转换器（已就绪）

| 项 | 值 |
| --- | --- |
| 工具 | `D:\VB\Unity2Spine`（`python -m ngui2spine.static_prefab_spine`，兼容层指向 `src\unity2spine\`） |
| 用法 | `python -m ngui2spine.static_prefab_spine <prefab> <输出目录> --assets <工程>\Assets [--scene <save.unity>] --skel --no-face-check` |
| 已知能力 | 单角色 1.26 GB 内存；50 角色全量跑过（`_probe50_rt4`）；自带 `static_check` 四项判据 |
| 相关文档 | `D:\VB\Unity2Spine\使用与代码导览.md`、`docs\交接与核查.md` |

### 2.3 试转结果（✅ 管线在这工程上已验证可通）

```
输入  Assets\Prefabs\2DModel_3P_Alexandra_NS1.uAnim.prefab
输出  D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv\3P_Alexandra_NS1\
结果  动画 4 条：Start(12.50s) / breast(4.67s) / Tep_1(2.48s) / lobby(12.50s)
      导出部件 36；.skel 4.6 MB
      [static_check] 场景渲染器 50 / 导出部件 36 /
                    动画中引用但未导出 0 / 静态可见未导出 0 / 与真值可见性冲突 0 / 曲线 path 对不上 0
```

清单已生成：`D:\VB\Search\New\归档-proj-Mobile-old\_uAnim_prefabs.txt`（157 行，prefab 文件名）。

---

## 3 已知问题（现状 + 处理态度）

### 3.1 ✅ 已修：脚本是空壳导致动画事件找不到接收者

- **原症状**：`'size_root' AnimationEvent 'EventDynamicBone' on animation '3P_Alexandra_NS1__lobby_start' has no receiver!`
- **根因**：Mobile-old 的游戏脚本是 **AssetRipper 的 `Dummy class` 空壳**（只有类名，没有方法体），
  而动画事件要调 `ActorAnimator.EventDynamicBone(string)`。
- **修法**：从 PC-new 拷入**真实实现**（保留 Mobile-old 原 `.meta`/GUID，引用不断）：
  `ActorAnimator` / `DynamicBone` / `DynamicBoneCollider` / **新增** `DynamicBoneColliderBase`、`DynamicBonePlaneCollider` /
  `Puppet2D_{Bone,GlobalControl,HiddenBone,IKHandle,SplineControl}`；
  并把 `Puppet2D_SplineControl.cs` 的 `FindObjectsByType(..., FindObjectsSortMode.None)`（Unity 2022+）
  改成 `FindObjectsOfType(...)` 以适配 2021.3。
- **验证**：编译 0 错（`Assembly-CSharp.dll` 已更新）；`unity_reflect` 确认 `ActorAnimator` 有 `EventDynamicBone`/`IsDynamicBone`；
  全工程扫描 **825 个 clip / 575 个动画事件 → 全部是 `EventDynamicBone`，574/574 都有接收者 `size_root:ActorAnimator`** ⇒ 该类警告整体消失。
- **备份**：`D:\VB\Search\New\归档-proj-Mobile-old\_backup_scripts_before_fix_20261008\`

### 3.2 🔶 暂时不管（按你的指示）：仍然是空壳的脚本

这些脚本**两个工程里都是空壳**，无法从 PC-new 拿到真实体：

| 脚本 | 被多少 uAnim prefab 引用 | 备注 |
| --- | --- | --- |
| `Raw\Scripts\Actor.cs` | **157（全部）** | 每个动画模型都挂它 |
| `Raw\Scripts\ActorPartsView.cs` | 56 | 部件显隐/换装相关（推测） |
| `Raw\Scripts\CameraBoundary.cs` | 2 | 镜头边界 |
| `ActorSpinePartsView.cs` / `ActorSpineSkinController.cs` / `Actor_Spine.cs` / `ActorUILocationChangeTrans.cs` | 0（uAnim 不引用） | 主要给 Spine 模型用 |

**当前判断**：动画放映本身（clips / 事件 / 蒙皮）**不依赖**它们 ⇒ **转换不受阻**。
**约定**：转换过程中若发现"缺了某项功能（例如换肤、部件开关、镜头跟随）"，再回头处理这批脚本。

若要补，可用的源码来源（按可靠性）：
1. 游戏 mono 版 `Assembly-CSharp.dll`（上一轮用过的路径 `G:\vfun\LAST ORIGIN R+\LAST ORIGIN R+_Data\Managed\Assembly-CSharp.dll`，**现在该盘不在**）；
2. `D:\Reverse\Build\local_Data\Managed\Assembly-CSharp.dll` —— **只有 6 KB，是空壳，不可用**；
3. `D:\VB\Reverse_tools\Il2CppDumper-6.7.46\`：`dump.cs`（6.5 MB）+ `DummyDll\Assembly-CSharp.dll`（636 KB）
   —— 能拿到**类/字段/方法签名**（够还原"能认回 prefab 序列化字段"的空实现），**没有方法体**。

### 3.3 ⚠️ 工具/环境坑（本轮踩过，转换时要遵守）

| 坑 | 现象 | 处理 |
| --- | --- | --- |
| Unity MCP 的 WebSocket 重连风暴 | Unity 内存 5.4 → **7.8 GB**、无响应、可用内存掉到 0.7 GB | **同一时间只用一个 MCP 客户端**（别同时开 CLI + 裸 HTTP）；发现内存涨就停 |
| 内存红线 | 本机 15.8 GB | 重活前先看可用内存（经验值：单角色转换 ~1.3 GB；157 个串行 ≈ 2 小时量级） |
| 外部改文件后 Unity 不自动导入 | 新脚本没有 `.meta`、不编译（窗口未聚焦时 Unity 会挂起刷新） | 用 MCP `refresh_unity` 强制刷新，或点进 Unity 窗口 |
| `--scene` 路径 | Mobile-old 场景目录是 **`Sences`**（拼写如此） | 命令里别写 `Scenes` |

---

## 4 转换方案（待执行）

1. **批量转换**：对 `_uAnim_prefabs.txt` 里 157 个 prefab 逐个跑
   `static_prefab_spine … --assets <proj>\Assets --skel --no-face-check`
   → 输出到 `D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv\<角色>\`
   （建议 `--jobs 2`；每个角色跑完看 `static_check` 四项是否为 0）
2. **逐角色验收**：`static_check` 四项 0 → `.skel` 加载审计（`_scratch\q3_audit_load.py --bin`，分片）→ 抽查渲染帧。
3. **与 PC-new 对照**：对已经在 PC-new 有 Spine 版角色的（102 个里与 uAnim 同名的），
   对比骨架/动画条数/slot 命名（注意 4.2 的 `/`→`-` 差异），确认转换结果语义一致。
4. **清理旧文件**（只挪不删，见 §5）。

---

## 5 清理清单（"旧文件"）

| 位置 | 内容 | 处理 |
| --- | --- | --- |
| `proj-Mobile-old\Assets\Editor\Mobile2021Diag.cs` / `Diag2` / `Diag3` / `Mobile2021FixVerify.cs` / `MobileOldVerify.cs` / `MobileOldVerify2.cs` / `MobileOldSpineCheck.cs` / `FieldRoundTrip.cs` | 上一轮为"atlas/材质/shader 修复"临时写的编辑器诊断脚本（不是运行时资产，不被 prefab 引用） | 挪到 `归档-proj-Mobile-old\_cleanup_20261008\` |
| `归档-proj-Mobile-old\_backup_scripts_before_fix_20261008\` | 本次修脚本前的空壳备份 | **保留**（出问题可回退） |
| ~~`D:\VB\Unity2Spine\_待删除_20260919\`~~ | 上一轮整理出来的中间件（15 GB） | ✅ 已被用户删除（2026-10-08 确认已不在） |
| `D:\VB\_mcp_dl\` | 装 MCP 时的源码副本（`unity-mcp-main\`、`clone_test\`、tar，68 MB） | ✅ 已移入 `Unity2Spine\delete\mcp_dl_cleanup_20261008\` |
| `D:\VB\Unity2Spine\_scratch\_bones{,2..6}` + `_anc.txt` | **09-21 那轮"分骨骼/加权 mesh"实验留下的中间件（206 MB）** | ✅ 已移入 `Unity2Spine\delete\scratch_分骨骼中间件_*\` |
| 各目录里的 `__pycache__`（8 个） | Python 缓存 | ✅ 已移入 `Unity2Spine\delete\pycache__*\` |

> **垃圾归置约定（2026-10-08 起）**：所有"待删"统一放到 **`D:\VB\Unity2Spine\delete\`**
> （只挪不删；确认没用后整目录删除）。当前 `delete\` = 275 MB / 4830 文件。
> 注：`_spine_conv\`（本次产物）、`_scratch\` 里 3 个已结案证据件（`_fix_spriteswap_before` / `_c_exp_before` / `_alice2_multi`）
> 与 30 个对账脚本**都不是垃圾**，不往 `delete\` 放。

---

## 6 下一步（主线）：把 CS 脚本功能的影响**添加/烘焙**进转换

> 这是"转完能看"之后的**主要工作**。当前转换器 `static_prefab_spine` **只读磁盘静态资源**
> （Mesh / Sprite / Material / 动画曲线），**运行态由脚本产生的效果一律不在产物里**。

> **2026-10-08 晚更新：本条已落地并逐顶点验证**，详细方法/坑/实测数字见
> [`Mobile-old_CS烘焙_方法与进展.md`](Mobile-old_CS烘焙_方法与进展.md)。
> 一句话：Unity 逐帧跑「clip 姿态 A → 跑 CS → 姿态 B」取 B-A，
> 标定出「Unity 世界 → 产物坐标」的线性映射后加到产物 deform 上。
> Alexandra NS1 验收：合并后产物 vs Unity 真值 **中位 0.022 px**（与基线同）。

### 6.1 哪些脚本功能会影响"看到的动画"

| 脚本（Mobile-old 里的路径） | 运行态影响 | 对产物的含义 |
| --- | --- | --- |
| `ActorAnimator` + `DynamicBone`(+`DynamicBoneCollider`/`ColliderBase`/`PlaneCollider`) | 动画事件 `EventDynamicBone` 在 clip 的固定时刻（实测 `t=0.05 / 2.783 / 5.05 …`）调 `DynamicBone.EventReset()`；**DynamicBone 本身是逐帧弹簧/惯性跟随**（头发、裙摆、胸、尾巴的滞后摆动） | 产物的 deform 只含"曲线 + 蒙皮"的结果，**没有 DynamicBone 的物理形变** |
| `ActorPartsView`（56 个 prefab 用） | 部件显隐 / 换装（脚本按状态开关渲染器） | 产物只含 clip 的 `m_IsActive` 曲线；**脚本额外开/关的部件会缺或多** |
| `ActorSpineSkinController` / `Actor_Spine` / `ActorSpinePartsView` | Spine 皮肤切换、部件控制 | 应映射成 Spine 的 `skins` / 附件切换 |
| `CameraBoundary`（2 个） | 镜头跟随/边界 | 与"模型动画"关系小，多半不改产物 |
| `Actor.cs`（**157/157 全用**，空壳） | 未知（角色总控） | 需要真实代码才能判定（见 §3.2） |

### 6.2 三类处理方式（先分类，再动手）

| 类别 | 适用 | 做法 |
| --- | --- | --- |
| **① 烘焙（bake）** | 运行态**逐帧形变**，主要是 DynamicBone 及其 collider | 在 Unity 里用**真实脚本**跑起来（Play 模式、固定时间步）→ 逐帧抓骨骼/顶点世界坐标 → 算出"脚本造成的形变"与"纯 clip 采样"的**差值** → 写进 Spine 的 deform 时间线 |
| **② 移植（port）** | 换肤 / 部件开关 / 事件驱动的动画切换 | 不需要逐帧烘：在产物里生成 `skins`、slot 的 attachment/alpha 时间线、或动画切换；但必须先把脚本的**判定条件**复刻出来 |
| **③ 宿主实现（不改产物）** | 交互输入、镜头、UI、局外逻辑 | 转换不负责，写清"由宿主实现"即可 |

### 6.3 已有地基（可以直接用）

| 件 | 位置 | 用途 |
| --- | --- | --- |
| 静态转换器 | `D:\VB\Unity2Spine`（`static_prefab_spine`） | 出骨架/动画/deform/skel |
| 帧烘焙路线 | `src\unity2spine\convert\frame_baked.py` | 把"逐帧顶点/矩阵"烘成 Spine 动画（正是①需要的形态） |
| Play 采样器 | Unity 侧 `PlayModeSamplerRunner.cs` / `TwoDModelCalibExport.cs`（PoseFrames/PlayFrames） | 逐帧抓骨骼局部 TRS / 顶点 |
| **Unity MCP**（2026-10-08 装好） | `packages\com.coplaydev.unity-mcp` + `mcpforunityserver` | 自动开 Play、逐帧抓数据、读控制台、改脚本——**不必手点 Unity** |
| prefab→脚本 依赖清单工具 | `D:\VB\_mcp_dl\prefab_scripts.py` | 列出每个 prefab 挂了哪些脚本、是否空壳 |
| 动画事件清单 | 本轮实测：**825 clip / 575 事件，全部 `EventDynamicBone`** | 烘焙时要按这些时刻触发 reset |

### 6.4 每个角色的判定流程（建议固定下来）

1. `prefab_scripts.py` 列出该 prefab 挂的脚本 → 对照 §6.1 表分到 ①②③。
2. **①**：Play 采样 → 差值 → 写 deform；**②**：在 Spine 里补 skin/附件时间线；**③**：记录不处理。
3. **验收**：把"Unity Play 真值"（逐帧顶点）与"Spine 产物渲染帧"逐帧比，
   阈值沿用现网标准（中位差 ≤1e-3 世界单位 / 或像素级同帧比对）。
4. 结论写回本文档与 `Unity2Spine\docs\历史问题与修复.md`。

### 6.5 风险与依赖（必须先想清楚）

| 风险 | 说明 | 对策 |
| --- | --- | --- |
| DynamicBone **非确定性** | 它依赖帧率、更新顺序、初始姿态；同样输入两次跑出来不一样 | 烘前固定 `Time.fixedDeltaTime`、固定初始姿态、单线程顺序更新；把参数一起记进产物说明 |
| 事件的 reset 会改初始状态 | `EventDynamicBone` 在 t=0.05/2.783/5.05… 重置弹簧 | 采样/烘焙必须**在相同时刻触发同一个事件**（事件表已拿到） |
| 空壳脚本的功能未知 | `Actor.cs`(157/157)、`ActorPartsView.cs`(56)、`CameraBoundary.cs`(2) 都是空壳 | 见 §3.2 的源码来源；实在拿不到就"行为反推"（Play 里对比开/关脚本的差异） |
| 内存 | Play 采样 + 逐帧顶点是重活（单角色 km 级顶点 × 帧） | 遵守 `D:\VB\AGENTS.md`：单进程、先量峰值、可用内存 <3 GB 不开新活 |
| 转换与烘焙的顺序 | 先烘后转（烘完再转，产物就是最终形态）还是先转后补（转完再把差值 patch 进 deform） | 建议**先转出基线 → 用基线做验收参照 → 再烘差值补进去**，便于回归 |

---

## 7 一页速查（命令）

```powershell
# 单角色试转（已验证）
cd D:\VB\Unity2Spine
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
python -m ngui2spine.static_prefab_spine `
  "D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets\Prefabs\2DModel_3P_Alexandra_NS1.uAnim.prefab" `
  "D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv\3P_Alexandra_NS1" `
  --assets "D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets" `
  --skel --no-face-check

# Unity 侧（工程已打开时）：刷新外部改动
#   MCP: refresh_unity   （或点回 Unity 窗口触发导入）

# 检查"动画事件有没有接收者"（MCP execute_code，已验证）
#   clip events 全为 EventDynamicBone → 接收者 size_root:ActorAnimator
```
