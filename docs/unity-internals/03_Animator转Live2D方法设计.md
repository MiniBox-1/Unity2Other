# 03 Unity 原生 Animator → Live2D 方法设计

日期：2026-11-06
前置：`01_Unity动画项目解析.md`、`02_Live2D资产与SDK解析.md`、`04_可行性验证记录.md`

## 0. 目标与前提

**目标**：输入一个 Unity 2D 角色 prefab（Transform 层级 + SpriteRenderer /
SkinnedMeshRenderer + Animator Controller + AnimationClip），输出一个可被
Cubism 运行时（Cubism SDK for Unity / 自研查看器 v3.pyd）直接加载的 Live2D 模型包：

```text
<Name>.moc3 + <Name>.model3.json + textures/*.png + motions/*.motion3.json
```

**前提**（本轮已确认）：

1. 没有 Cubism Editor，没有官方 moc3 编译器 ⇒ **moc3 必须由我们生成**；
2. Core 5-r.5 接受 moc v1，且 `csmHasMocConsistency` 可做硬校验；
3. Unity 侧的解析、采样、真值导出已经现成（见 01 文档第 5 节）。

**不在本轮范围**：语义化重绑（把骨骼动画改写成 `ParamAngleX` 这类美术参数）、
物理/摇摆自动生成、表情系统、Cubism Editor 可编辑性（.cmo3）。

## 1. 总体架构

```text
[输入层]  prefab / controller / clip / 贴图 / 真值 JSON
    │      （复用 unity2spine.src.unity2spine）
    ▼
[模型层]  Hierarchy → Part / Deformer 树 / ArtMesh / 参数空间
    │      （新写：model/）
    ▼
[动画层]  Animator 采样 → 参数曲线 → motion3
    │      （新写：motion/；真值可选）
    ▼
[拟合层]  加权网格 → WarpDeformer 关键帧（最小二乘）
    │      （新写：fit/）
    ▼
[序列化]  moc3 writer / model3 / motion3 / cdi3
    │      （新写：moc3/、io/）
    ▼
[校验层]  一致性 → 读回 → 逐顶点 → 渲染
```

分层原则：**模型层只依赖几何，不依赖动画**；动画层只产出参数曲线，不碰 moc3；
这样静态模型（StaticSpine 那 1148 个）可以先跑通，再叠动作。

## 2. 模型层：Unity → Live2D 对象映射

### 2.1 对象映射

| Unity | Live2D | 说明 |
| --- | --- | --- |
| 骨骼 Transform（`Bone_*` 链） | `RotationDeformer` | 父子关系照抄：`deformer.parent_deformer_indices` |
| 纯位移/无旋转的 Transform | `RotationDeformer`（angle 恒 0） | 少一种类型就少一类 bug |
| 需要非等比缩放/剪切的节点 | `WarpDeformer`（2×2 起） | RotationDeformer 只支持等比 scale |
| 部件 SpriteRenderer / 一个 SMR | `Part` + 1 个 `ArtMesh` | Part 管显隐/排序，ArtMesh 管几何 |
| ArtMesh 顶点 | SMR/Sprite 的本地顶点（bindpose） | 单位换算见 2.4 |
| 图集 | 纹理页 `texture_00.png`… | 每页 ≤ 2048/4096，按部件打包 |
| UV | `uv.xys`（0..1，左上原点） | 注意 Vulkan/GL 的 y 方向，实现时用 Core 读回比对 |
| 三角形 | `position_index.indices`（i16） | 顶点数 > 32767 才需要拆 |
| `sortingOrder` / 层级顺序 | **ArtMesh 构造顺序**（draw order group 的 indices） | 现阶段可控的只有构造顺序；`part_keyform.draw_orders` 未验证出对 render order 的影响（见 04 文档 E9），动态排序留到 P2 |
| `m_IsActive` / 透明度 | Part/ArtMesh `opacity` 关键帧 | 阶跃段 |
| 换脸 `m_Sprite` | 多个 ArtMesh + opacity 切换 | 运行时不能换纹理 |

**硬约束**：Live2D 一个 ArtMesh 只能属于一个 Part 和一个 Deformer；
Unity 一个 SMR 若跨多骨且权重均匀，必须拆成多个 ArtMesh 或退化为 Warp 网格。

### 2.2 参数设计（两种策略，建议先 A 后 B）

**A. 逐通道参数（保真优先，默认）**

每个被动画的骨骼本地通道一个参数：

```text
P_<BoneId>_Rz   该骨骼本地 Z 旋转（度）
P_<BoneId>_Tx   本地 X 位移（模型单位）
P_<BoneId>_Ty   本地 Y 位移
P_<BoneId>_S    等比缩放
```

- 一个骨骼的 RotationDeformer 挂 2~4 个参数，每个参数取 **2 个键**
  （min / max），keyform 数 = 2^k（k=参数个数，最多 8~16，可接受）；
- 线性通道（角度、平移、等比缩放）在**多线性插值**下是**精确**的：
  Live2D 的 keyform 网格按参数张量积插值，而 Unity 的本地 TRS 对通道是线性的；
- 默认值（参数 = default）对应的 keyform 必须是 bind pose，所有 motion 从 0 开始。

**B. 语义参数（可编辑优先，后期）**

`ParamAngleX/Y/Z`、`ParamBodyAngleX`、`ParamEyeLOpen`、`ParamMouthOpenY`…
需要从骨骼运动**反解**（见 4.2 拟合），误差可控但不精确。
用一张 `config/param_map.yaml` 把「骨骼 → 语义参数 + 权重」写成可编辑映射，
不改变转换器主体。

> 建议：A 先落地，保证“画面一致”；B 作为可选的第二遍优化，
> 只对头/眼/嘴/呼吸这些美术关心的部位做语义化。

### 2.3 keyform 组织

- 每个可形变对象一条 **band**；band 里对每个参数一条 binding，binding 引用
  参数下标与键值；
- 对象的 `keyform_begin/counts` 指向自己的 keyform 数组，顺序是参数键的
  张量积（**最右参数变化最快**，实现时以 Core 读回为准标定，见 04 文档 E3）；
- 无参数的静态对象：band 里 binding 数 = 0，keyform 数 = 1（Koharu 的部件就是这个形态）。

### 2.4 坐标、画布与 ppu

- 采用 `ppu = 画布宽（px）`，画布 = 角色 bind pose 的 AABB 外扩 10%；
- 模型坐标 = 像素 / ppu，原点在画布中心（`origin_x = w/2, origin_y = h/2`）；
- 已验证：ppu/画布可自选（E5 用 1000×1000、顶点 ±0.25 通过校验）；
- Unity 与 Live2D 画布都是 Y 向上，但 **moc3 里 keyform 顶点按 Y 取反存储**
  （已实测，见 04 文档 E7）；UV 的 v 方向另行用 Core 读回 `csmGetDrawableVertexUvs`
  对齐，不要把两件事混成一个符号。

## 3. 动画层：Animator → 参数曲线

### 3.1 两条输入路径

| 路径 | 数据源 | 用途 |
| --- | --- | --- |
| 静态解析 | `.controller` + `.anim`（YAML） | 可批量、无需开 Unity；能拿到 clip 原始曲线 |
| 真值烘焙 | `PlayFrames\<角色>@<Animator>@<状态>.json` | 已含层/加性/状态机混合后的最终本地 TRS，**推荐作为主路径** |

原因：Live2D 没有加性层，Animator 的多层混合必须在转换期塌缩成一条参数曲线。
静态解析要自己实现层混合/参考姿态/循环，成本高且容易错；真值烘焙直接拿到结果。
建议：**真值优先，静态解析只用于没有采样数据的资产**。

### 3.2 流程

```text
状态 s（如 lobby / breast / Tep_1）
  → 逐帧 (30 fps) 取最终本地 TRS（真值或静态求值）
  → 换算成模型空间（世界矩阵 → 相对 bindpose 的局部增量）
  → 写入对应参数
  → 参数曲线压缩（见 3.3）
  → motion3.json（Meta.Duration/Fps/Loop/FadeIn/FadeOut）
```

### 3.3 曲线压缩

- 旋转/位移：默认 **Linear**，误差阈值内做 Douglas–Peucker 抽点；
  需要更顺滑时用 **Bezier**（控制点取相邻弦长 1/3，与 Unity Hermite 的
  切线语义对齐，参考 `CubismMotion3Json.ConvertCurveSegmentsToKeyframes`）；
- 显隐/换图/排序：**Stepped**（段类型 2）；
- 每个 clip 的首尾：若 loop，首尾值必须一致；
- `FadeInTime/FadeOutTime`：按源状态过渡时长设定（Live2D 用它做 motion 交叉淡入）。

### 3.4 与 Unity 语义的对齐点

| Unity 语义 | 转换处理 |
| --- | --- |
| Hermite 切线 | 采样后重新拟合，不直接搬切线；用 30 fps 采样 + 误差驱动抽点即可 |
| 欧拉顺序 ZXY | 2D 角色主要是 Z；若出现 X/Y，只取其在屏幕平面的投影（或走 Warp） |
| 四元数优先于欧拉 | 统一先化四元数再取 Z 轴角 |
| `m_IsActive` 阈值 0.001 | 采样时用同一阈值，输出 0/1 阶跃 |
| 加性层 | 真值烘焙后自然消失 |
| 层循环（短层按自身时长） | 真值烘焙后自然消失 |

## 4. 拟合层：加权网格 → WarpDeformer

这是唯一无法 1:1 映射的部分，也是误差预算的主体。

### 4.1 问题

Unity 的 SMR 顶点 `v = Σ w_i · M_i · v_bind`（最多 4 骨）。
Live2D 的 ArtMesh 顶点 `v = D_parentchain · v_bind`（只受 Deformer 层级影响）。
一个 ArtMesh 无法表达“顶点 A 跟骨 1、顶点 B 跟骨 2”。

### 4.2 方案：主骨 + Warp 残差

1. **主骨**：按权重和最大的骨骼把 SMR 划成若干块（每块一个 ArtMesh），
   每块挂到该骨的 RotationDeformer 下；
2. **残差**：块内顶点相对主骨的运动差异，用一张 2×2 ~ 4×4 的 WarpDeformer
   表达（网格越密，拟合越好，但 keyform 数量按 rows×cols 增长）；
3. **求解**：对每个采样帧，已知 ArtMesh 顶点的目标位置（Unity 真值），
   求 Warp 网格点的位置，使双线性插值后的顶点最接近目标 —— 线性最小二乘，
   可直接解（每个网格点只影响局部 4 个顶点，稀疏系统）；
4. **keyform 化**：把逐帧解出的网格点，按参数轴（骨骼角度）取 2~3 个代表值，
   写成 keyform；帧间由运行时插值。

### 4.3 误差评估

- 逐顶点：`RMS`、`max`，单位换算回 px（`× ppu`）；
- 逐帧：最差帧、95 分位；
- 逐部件：找出误差最大的部件（通常是肘/膝/长发端）；
- 渲染层：v3.pyd 渲染同帧 vs Unity refshot 的 alpha 差。

建议验收线（1:1 画布）：**95 分位 ≤ 0.6 px，max ≤ 1.5 px**；
超过就把该部件网格加密一级或拆块。

## 5. moc3 生成器设计

> 状态：`src\unity2live2d\moc3\builder.py` 已实现 Parts / ArtMesh / 参数 /
> keyform 网格 / UV / 三角形 / 排序，并通过 `tests\test_moc3_builder.py`
> 的四组用例（含 24 ArtMesh、3 参数 8 keyform 的压力用例）。
> **尚未实现**：WarpDeformer / RotationDeformer（P2）。

### 5.1 模块

```text
src/unity2live2d/moc3/
  layout.py      段表（名称/类型/对齐/count 索引），标定过的真实顺序
  builder.py     ModelBuilder：add_part/add_deformer/add_artmesh/add_param/
                 add_keyform，最后 build() 产出 counts + 各段数组
  writer.py      按 layout 序列化（复用 py-moc3 的 BinaryWriter/对齐逻辑）
  validate.py    ctypes 绑定 Live2DCubismCore.dll：一致性 + 读回
```

### 5.2 生成顺序（必须严格）

1. 分配 Parts（含父子、visible/enable、band）；
2. 分配 Deformers（warp 在前、rotation 在后，按 Core 的 count 分区）；
3. 分配 ArtMesh（顶点、UV、索引、纹理、mask、父 Part/Deformer）；
4. 分配 Parameters（id/min/max/default/repeats/decimal）；
5. 生成 bands → bindings → keys；
6. 按对象写 keyform 值（art/joint 顶点、opacity、draw order、angle/origin/scale）；
7. 汇总 counts（23 个）→ 序列化；
8. **闸门**：`csmHasMocConsistency == 1`，否则回退到 `builder` 的中间态 dump。

### 5.3 关键注意

- `art_mesh` 的「顶点数 / 索引数」两个数组在公开解析库里是**反的**（实测，见 04 文档 E3），
  以 Core 读回为准；
- **keyform 顶点位置按 Y 取反存储**（`stored_y = -model_y`，实测见 E7）；
  `keyform_position_begin_indices` 单位是 float 下标；写模型时统一在序列化层
  做一次 `flip_y()`，并用 Core 读回断言；
- `keys` 段与 `keyform_binding_band` 是共享池，索引必须全局连续；
- 段间 64 字节对齐，`counts[10]`（keyform 位置）是 **float 个数**不是顶点数；
- 先只写 v1；`additional.quad_transforms` 留到需要乘算时再加。

## 6. 输出与命名

```text
Products\<Char>\<Char>.moc3
Products\<Char>\<Char>.model3.json
Products\<Char>\textures\texture_00.png
Products\<Char>\motions\<State>.motion3.json
Products\<Char>\<Char>.cdi3.json        （参数/部件的可读名，建议总输出）
Products\<Char>\manifest.json           （转换报告：计数、误差、告警）
```

- 参数 id 用 ASCII，避免空格；`P_` 前缀自建参数，语义参数用 `Param` 前缀；
- 部件 id 用 Unity 原始名字（去掉非法字符），保留可追溯性；
- manifest 记录：moc 版本、ppu、画布、部件/变形器/ArtMesh/参数数量、
  每段动作的帧数与曲线数、逐部件拟合误差。

## 7. 校验链（四级，缺一不可）

| 级别 | 手段 | 通过条件 |
| --- | --- | --- |
| L1 结构 | `csmHasMocConsistency` | == 1 |
| L2 读回 | `csmGetParameter*/Part*/Drawable*` | id、数量、范围、顶点数、纹理号、render order 与构建计划一致 |
| L3 几何 | 设参数 → `csmUpdateModel` → 读顶点 → 与 Unity 真值比 | 见 4.3 验收线 |
| L4 视觉 | v3.pyd 或 Unity Cubism SDK 渲染 vs refshot | alpha 差 / 逐像素 ≤ 阈值，肉眼无结构错位 |

L1/L2 是硬门槛（毫秒级），L3 是主指标（逐帧），L4 是抽样回归。

## 8. 分阶段计划

| 阶段 | 内容 | 产出 | 验收 |
| --- | --- | --- | --- |
| **P0** ✅ | 可行性验证 | 04 文档 + `tools\core_probe` | 最小 moc3 通过 Core 校验并能随参数形变 |
| **P1** | moc3 Builder + 静态模型 | 一个角色（14 部件、无动作） | L1+L2 通过，v3.pyd 能显示 |
| **P2** | Transform 树 → Deformer 树 + 参数 | 同一角色带 bind pose 与参数 | L3 在 bind pose 下误差 ≈ 0 |
| **P3** | 动作转换 | 该角色 4 段 motion3 | 静态解析与真值烘焙两条路径一致 |
| **P4** | Warp 拟合 | 加权部件的误差报告 | 达到 4.3 验收线 |
| **P5** | 批量 | 157 个 uAnim 角色 + manifest | 全量 L1/L2 通过、L3 抽样通过 |

里程碑建议：**P1 完成前不写批量逻辑**；P2 完成前不接动作；P4 完成前不做全量。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| moc3 语义细节未完全标定（keyform 网格顺序、band、draw order group） | 模型能过校验但形变错 | 用 Core 读回做逐项标定；先做 1 参数、2 参数、3 参数三级用例 |
| 公开库 v5 写回有损 | 若必须 v5 会产出坏文件 | 锁死 v1；需要新特性时自己补段，不依赖第三方 |
| 加权网格无法精确表达 | 关节/长发误差大 | 主骨拆块 + Warp 加密；误差超线就拆 |
| 非等比缩放/剪切 | 形变错 | 该节点强制走 WarpDeformer |
| 动画层混合复杂（多层/加性/状态机） | 曲线与原游戏不一致 | 真值烘焙优先，静态解析仅兜底 |
| 纹理页数与尺寸限制 | 大角色放不下 | 按部件分组打包，必要时拆多页；Core 读回纹理号校验 |
| 内存（本机 16 GB，已多次被渲染吃满） | 批量转换崩 | 逐角色流式处理，不并发；真值按帧读；见根目录 AGENTS.md |
| 源资产 inactive / 同名孪生 | 采错对象 | 用 fileID 定位，不用名字；Play 模式采样 |

## 10. 代码骨架（建议新建）

```text
Unity2Live2D\
  src\unity2live2d\
    unity\         ← 从 Unity2Spine 移植（parse/2dmodel/anim2d/mesh）
    model\         parts.py  deformers.py  artmesh.py  params.py  texture.py
    motion\        sampler.py  layer_bake.py  curve_compress.py  motion3.py
    fit\           warp_fit.py  kinematics.py  error_report.py
    moc3\          layout.py  builder.py  writer.py  validate.py
    io\            model3.py  cdi3.py  physics3.py
    cli\           convert_one.py  convert_batch.py  validate_product.py
  tools\core_probe\  ← 已存在（moc3 校验/标定）
  Products\         ← 产物
  docs\             ← 本套文档
```

移植时保留 `unity2spine` 的 import 路径，避免复制两份解析器：

```python
sys.path.insert(0, r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
from unity2spine.unity import unity_2dmodel, unity_anim2d
```

## 11. 待用户确认

1. **首个目标角色**：建议先取 `2DModel_3P_Alexandra_N`（14 部件、4 段动作、结构简单）；
2. **产物用途**：只在自己查看器里看，还是要进 Unity（决定是否需要 URP 工程与
   SDK 导入链）；若要进 Unity，需确认目标工程管线是否为 URP；
3. **参数策略**：先逐通道保真（A），还是直接上语义参数（B）。
