# 01 Unity 动画相关项目解析（输入侧）

日期：2026-11-06
范围：`D:\VB` 下所有与「Unity 原生 Animator / AnimationClip / 骨骼 2D 角色」相关的工程与产物。

## 1. 项目清单

| 项目 | 路径 | 性质 | 规模（实测） |
| --- | --- | --- | --- |
| Unity→Spine 统一工作根 | `D:\VB\Convert\Spine` | 现有转换器 + 产物 + 文档 | 三条路线，见下 |
| GitHub 快照 | `D:\VB\Unity2Spine_GitHub_20261105` | 上述工程的可发布快照 | 含 manifest/SHA256 |
| 逆向资料包 | `D:\VB\Unity2Spine_ReverseEngineering_Full_20261106` | Unity 运行时语义、IDA/Mono 证据、Unity 侧导出脚本 | docs 20+ 篇、tools 80+ 个 |
| Unity 源工程（LO/Mobile-old） | `D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old` | Unity 2022.3.3f1 工程 | 1320 prefab / 811 anim / 229 controller |
| Unity 源工程（BD/NGUI） | `D:\VB\Search\BdOne` | Unity 工程（NGUI 动态立绘） | 296 prefab / 65 anim |
| Unity 探针工程（多游戏） | `D:\VB\EC\_work\f2_unpack\unity_probe` | 解包/探针现场 | 含 YA2 的 Live2D 产物 |
| 查看器 | `D:\VB\Viewer\newViwer` | 自研 Python 查看器（Spine/Live2D/序列帧） | 含 `v2.pyd` / `v3.pyd` |

判定标准：能被 Animator/AnimationClip 驱动、且是 2D 角色立绘形态的工程；
纯静态图集、纯 CG、纯 Spine 资产不在此列。

## 2. 三条已跑通的 Spine 路线（决定了 Live2D 的输入形态）

`UnityAnimation2Spine\README.md` 把源资产分成三类，这个分类对 Live2D 同样成立：

| 路线 | 源形态 | 产物规模 | 对 Live2D 的意义 |
| --- | --- | --- | --- |
| `SingleSpine` | 单 Root + 逐顶点 deform / 单骨骼 | LO 157 个 `*.uAnim.prefab`；BD 17 角色 | 最接近 Live2D：层级浅、每部件刚性绑定 |
| `MultiSpine` | 真骨骼树 + 加权 mesh | LO 157/157；BD 17 角色/36 产物（3805 骨、3348 槽、3360 mesh） | **主要难点**：Live2D 无逐顶点蒙皮 |
| `StaticSpine` | 无 Animator 的静态立绘多插槽 | 1150 个 `*.Lihui.prefab` → 1148 成功 | 只需部件树，不需要动作 |

## 3. Unity 源工程的资产统计（Mobile-old）

以 `2DModel_3P_Alexandra_N.uAnim.prefab` 为例（120 KB YAML，3976 行）：

| 项 | 实测值 |
| --- | --- |
| Transform (`!u!4`) | 93 |
| GameObject (`!u!1`) | 93 |
| SkinnedMeshRenderer (`!u!137`) | 14 |
| Animator (`!u!95`) | 1 |
| SpriteRenderer (`!u!212`) | 1（换脸/表情用） |
| MonoBehaviour (`!u!114`) | 1（游戏侧 actor 脚本：`actor_name` / `spriteFace` / `_faceNameList`） |
| 转成 Spine 后 | 77 骨、14 槽、14 个加权 mesh、4 段动画（Start / Tep_1 / breast / lobby） |

也就是说：**一个角色 ≈ 90~100 个 Transform、14 个部件、1 张图集页、4 段左右动作**。
这个量级对 Live2D 完全在合理范围（样例 Koharu：17 部件、81 变形器、91 ArtMesh、52 参数）。

## 4. 动画数据形态

- Animator Controller 在 `Assets\Raw\AnimatorController\`，IAB/分层状态机：
  例如 `2DModel_3P_BlackWyrm_NS1.controller` 有 `Base Layer` 与 `BG_Leaf` 两层，
  状态 `lobby` / `breast` / `Tep_1`。
- AnimationClip 在 `Assets\Raw\AnimationClip\`，单文件 300 KB~800 KB YAML，
  动画对象是 Transform 的 localPosition/localRotation/localScale/MonoBehaviour 字段/
  SpriteRenderer 属性。
- 曲线语义（已与汇编核对，见 `REVERSE_ENGINEERING_INDEX.md`）：
  - Hermite 切线求值；
  - `m_EulerCurves` 的 `m_RotationOrder: 4` = ZXY；
  - 同对象同时有四元数/欧拉曲线时以四元数为准；
  - `m_IsActive` / `m_Enabled` 阈值是 `abs(v) > 0.001`；
  - `m_SortingOrder` 浮点写整数带截断规则；
  - `m_Sprite` 换图是阶跃，不插值；
  - 加性层增量 = `clip(t) - clip(reference)`，参考姿态时间取自
    `m_AdditiveReferencePoseTime`（本工程为 0），层短于主 clip 时按自身时长循环。

## 5. 可复用的代码模块

以下是 `SingleSpine\Shared\Unity2Spine\src\unity2spine\` 下可直接搬到
Live2D 转换器的模块（Python）：

| 模块 | 职责 | Live2D 用途 |
| --- | --- | --- |
| `unity\unity_parse.py` | Unity YAML（`!u!` 文档）解析器 | 直接复用：prefab/anim/controller 读取 |
| `unity\unity_2dmodel.py` | 构建 2DModel：Transform DFS、Animator 选择、controller/layer 解析、GUID 索引 | 直接复用：Hierarchy 与状态机 |
| `unity\unity_anim2d.py` | AnimationClip 解析 + 采样（TRS、四元数/欧拉、Hermite 斜率） | 直接复用：参数曲线来源 |
| `unity\unity_mesh.py` | SMR 网格、骨骼权重、bindpose、BlendShape | 复用：ArtMesh 顶点与权重 |
| `spine\sprite_outline.py` | Sprite 轮廓（Tight mesh）复刻 | 复用：取 ArtMesh 三角形 |
| `validate\validate_spine.py` | 结构校验 | 改写成 moc3 校验 |
| `convert\convert_2dmodel.py` | 世界矩阵、蒙皮、AABB 归一化 | 复用几何部分 |

另外 `Unity2Spine_ReverseEngineering_Full_20261106\tools\unity_validation\` 下的
C# 导出器（`TwoDModelDebugExporter.cs`、`UnityAnimationExporter.cs`、`PlayModeSamplerRunner.cs`）
已经在产出**逐帧骨骼 + 顶点真值**（`info\Data\PoseFrames\<角色>.json`、
`PlayFrames\<角色>@<Animator>@<状态>.json`）。这套真值正是 Live2D 形变拟合的
监督数据，不需要重做。

## 6. 对 Live2D 转换的关键判断

| 问题 | 结论 |
| --- | --- |
| Transform 层级能不能直接映射 | **能**。Unity 骨树 → Live2D RotationDeformer 树，父子链一一对应 |
| 骨骼本地 TRS 能不能直接映射 | **大部分能**：Z 旋转 → keyform `angle`；XY 位移 → keyform `origin`；等比缩放 → keyform `scale`；**非等比缩放/剪切不能**，要用 WarpDeformer |
| 加权网格能不能直接映射 | **不能**。Live2D 没有骨骼权重，ArtMesh 只受 Deformer 变换；只能用 Warp 网格逼近，或用「主骨刚性 + Warp 残差」两段式 |
| 显隐 / 排序 / 换图 | 显隐→Part/AritMesh opacity 关键帧；排序→Part keyform `draw_order`；换图→拆成多个 ArtMesh 用 opacity 切换（Live2D 运行时不换纹理） |
| Animator 多层加性 | **不能**原样表达。Live2D 只有 motion 淡入淡出，没有叠加层，必须在转换期把层烘焙进参数曲线 |
| BlendShape | Live2D 无 BlendShape；用 WarpDeformer 关键帧拟合，或按权重拆 ArtMesh |
| 一个角色多大 | ≈14 部件 / 100 Transform / 1 图集页 / 4 段动作，规模安全 |

## 7. 已知坑（沿用 Spine 路线踩过的）

- prefab 里的角色通常是 inactive 的，运行时真值必须在 Play 模式采；
- 同名孪生部件（如 banshee 手）要靠 fileID 而不是名字区分；
- `m_Sprite` 换图是直接引用写入、不插值，转换时必须按阶跃处理；
- 排序不是简单的 sortingOrder 排序，`RenderObjectSorter` 有 packed
  `GlobalLayeringData`、renderQueue、深度、SortingGroup 多级比较；
- 内存红线：全量 `PoseFrames` 有 11.4 GB，转换期不要一次性加载全部真值，
  按角色逐帧流式读取（见根目录 `AGENTS.md`）。
