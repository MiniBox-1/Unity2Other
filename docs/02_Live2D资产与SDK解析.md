# 02 Live2D 资产与 SDK 解析（目标侧）

日期：2026-11-06
范围：`D:\VB\Convert\Live2d`、`D:\VB\Viewer` 里的 Live2D 运行时，以及 `D:\VB\EC` 下已有的 Live2D 资产。

## 1. SDK 概况（实测）

`D:\VB\Convert\Live2d\Cubism` 是 **Cubism SDK for Unity 5-r.5**（`cubism-info.yml`: id 14，
version `5-r.5`，created 2026-04-01）。

| 项 | 值 |
| --- | --- |
| 渲染管线 | **仅 URP**（Built-in / HDRP 不支持） |
| 开发工程版本 | Unity `6000.0.68f1` |
| 输入 | 期望 `com.unity.inputsystem` |
| Core 原生库 | `Plugins\Windows\x86_64\Live2DCubismCore.dll`（249,800 B） |
| Core 版本 | `csmGetVersion()` = 100663297（0x06000001） |
| 支持的最新 moc | `csmGetLatestMocVersion()` = **6** |

目录职责：

| 目录 | 内容 | 与转换器的关系 |
| --- | --- | --- |
| `Core` | `CubismModel` / `CubismMoc` / `CubismPart` / `CubismParameter` / `CubismDrawable`，以及 `Core\Unmanaged\CubismCoreDll.cs`（P/Invoke 全表） | **权威校验接口**：一致性、读回参数/部件/顶点 |
| `Framework` | Motion / Expression / Physics / Pose / LookAt / MouthMovement / Json | 生成 `motion3.json` / `physics3.json` 时要对齐它的解析器 |
| `Rendering` | `CubismRenderController`、URP 自定义 Pass、Mask/Offscreen | 渲染校验 |
| `Editor` | `Importers`（model3/motion3/physics3/pose3/cdi3 的导入器）、`Inspectors` | 生成的资产必须能被这些导入器吃下 |
| `Plugins` | 各平台原生 Core | Windows x86_64 可直接给 Python `ctypes` 用 |
| `Samples\Models` | `Koharu` / `Mao` / `Natori` / `Ren` / `Rice` / `Clipping` | 结构参照与回归样本 |

## 2. 模型资产形态

一个 Live2D Cubism 3/4/5 模型包：

```text
<Name>/
  <Name>.moc3              编译后的模型（二进制，Core 只能读）
  <Name>.model3.json       清单：Moc / Textures / Motions / Expressions / Physics / Pose / DisplayInfo
  textures/texture_00.png  图集页（可多页，ArtMesh 用 texture index 引用）
  motions/*.motion3.json   参数曲线
  <Name>.physics3.json     物理（可选）
  <Name>.pose3.json        部件跟随（可选）
  exp/*.exp3.json          表情（可选）
  <Name>.cdi3.json         显示名（参数/部件的可读名称，可选）
```

`model3.json` 关键字段（SDK `CubismModel3Json`）：`Version: 3`、
`FileReferences.{Moc,Textures,Physics,Pose,DisplayInfo,Motions,Expressions}`、
`Groups`（EyeBlink / LipSync 参数组）、`HitAreas`。

`motion3.json` 关键字段（SDK `CubismMotion3Json`）：`Meta.{Duration,Fps,Loop,
FadeInTime,FadeOutTime}`、`Curves[].{Target,Id,Segments,FadeInTime,FadeOutTime}`。
`Segments` 是扁平数组：`[t0, v0, type, …]`，段类型 `0=Linear / 1=Bezier /
2=Stepped / 3=InverseStepped`（SDK 里 stepped 判定为 `==2`，bezier 为 `==1`）。

> 注意：SDK 的 motion3 导入器会把它转成 Unity `AnimationClip`（“MonoBehaviour 模式”），
> 也就是说 motion 最终是驱动 `CubismModel` 上的参数组件，而不是直接写顶点。

## 3. `.moc3` 结构（实测）

```text
[0, 64)      Header: "MOC3" + version(u8) + endian(u8) + padding
[64, 704)    Section Offset Table: 160 × u32
[704, 832)   Count Info: 23 × i32（parts/deformers/artmeshes/params/keyforms/…）
[832, 1984)  reserved
[1984, …)    Body: 约 100 个类型化数组，逐段 64 字节对齐
```

- body 是 **struct-of-arrays**：`art_mesh.ids`、`art_mesh.texture_indices`、
  `parameter.min_values`、`keyform_position.xys`…… 每段只存一种属性。
- 关键对象与关系：
  - `Part → ArtMesh`（`parent_part_indices`）、`Deformer → ArtMesh`
    （`parent_deformer_indices`）；
  - 每个可形变对象有一条 **keyform band**（`keyform_binding_band_indices`），
    band 指向若干 keyform binding，binding 指向参数（`keyform_binding_index`）
    与参数值（`keys.values`）；
  - 对象自身的 `keyform_begin_indices / keyform_counts` 在该对象的 keyform 数组
    里定位“每个参数键组合”的一组值（顶点、角度、透明度、draw order）。
- RotationDeformer 的 keyform 字段是 `angle / origin_x / origin_y / scale /
  reflect_x / reflect_y`；WarpDeformer 的 keyform 是一张网格的顶点位置。
  这正是 Unity 骨骼本地 TRS 可以落地的位置。
- **UV 原点在左上（v 向下）**：官方样例（Koharu）用 `(1-v)` 采样才正确；
  Unity 网格 UV 是 v 向上，转换时必须写 `v' = 1 - v`（实测，见 04 文档 E11）。

版本：`1=V3.00, 2=V3.03, 3=V4.00, 4=V4.02, 5=V5.00`，Core 5-r.5 还认 **6**。
v3.03 起追加 `additional.quad_transforms`（乘算/屏幕色相关）。

## 4. 样例模型实测

| 模型 | moc 版本 | 部件 | 变形器（warp/rot） | ArtMesh | 参数 | keyform 位置 | UV | 索引 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Koharu | 1 | 17 | 81 (63/18) | 91 | 52 | 50,624 | 3,968 | 7,815 |
| Natori | 1 | 32 | 180 (128/52) | 176 | 96 | 146,352 | 10,454 | 20,856 |
| Mao | 5 | 32 | 178 (118/60) | 262 | 132 | 143,920 | 12,040 | 23,829 |

Koharu 的 canvas = 1600×2000 px，`pixelsPerUnit` = 1600，顶点坐标落在
约 `x∈[-0.34,0.35], y∈[-0.60,0.61]`，即 **模型单位 = 画布像素 / ppu**，
画布宽 ≈ 1.0 单位。转换器可以自选 ppu（已验证 ppu=1000、画布 1000×1000 可用）。

## 5. 现有 Live2D 资产（可直接当参照/回归集）

| 资产 | 路径 | 内容 |
| --- | --- | --- |
| YA2（Yokai Art 1/2）14 个模型 | `D:\VB\EC\_work\f2_unpack\unity_probe\YA2_l2d_name\Live2DOutput` | 每个含 `.moc3`（15–732 KB）、`.model3.json`、`motions\*.motion3.json`、`.export_info.json` |
| ExSim03 | `D:\VB\EC\Total\Is this Really a Massage!\Live2D驱动\model` | 5.8 MB moc3 + 6 张纹理 + `cubism4.min.js`/Pixi 网页驱动 |
| SDK 样例 | `D:\VB\Convert\Live2d\Cubism\Samples\Models` | Koharu/Mao/Natori/Ren/Rice/Clipping，含 motion3、physics3、pose3 |

YA2 的 `export_info.json` 记录了导出参数（`MotionMode: MonoBehaviour`、
`ForceBezier`、`Moc.Parsed/SDKVersion`），可以作为“别人怎么从 Unity 资产提取
Live2D 模型”的格式参照，但它只做**提取**，不生成新模型。

## 6. 自研查看器（离线校验的关键）

`D:\VB\Viewer\newViwer\cWidgets\Render\Live2d\`：

| 组件 | 能力 |
| --- | --- |
| `v2.pyd` | Cubism 2 绑定：`LAppModel.LoadModelJson / StartMotion / SetExpression / Resize / Update / Draw` |
| `v3\v3.pyd` | Cubism 3/4/5 原生框架绑定：`model.LoadModelJson / LoadFromJsonString / UpdateManually / Draw / CreateRender / LoadExtraMotion / LoadExtraExpression / StartMotion`，OpenGL 渲染 |
| `Live2dLoader.py` | 目录扫描/模型清单解析（v2/v3 自动识别） |

含义：**不需要 Unity 也能离线渲染生成的模型**（v3.pyd + `LoadExtraMotion`
可以直接播放我们生成的 motion3）。这给转换器提供了第二条独立验证链。

## 7. 能力边界（决定方法）

| 能力 | 是否具备 | 说明 |
| --- | --- | --- |
| 读取 moc3、校验一致性 | ✅ | `csmHasMocConsistency` / `csmMoc` |
| 读取参数/部件/ArtMesh/顶点 | ✅ | `csmGetParameter*` / `csmGetDrawable*` |
| 运行时改参数 | ✅ | `csmGetParameterValues` 指针直写 |
| **写出 moc3** | ❌ | Core 没有编译器 API，必须自己拼 |
| Cubism Editor | ❌ 本机未安装 | 注册表与默认路径均未发现（也意味着不能“导出”moc3） |
| 官方 moc3 编译 CLI | ❌ | 不存在 |
| 第三方 moc3 读写库 | ⚠️ | `py-moc3`（MIT，纯 Python）：v1 读写字节级一致；**v5 写回有损**（Mao 879,680 → 796,032 B，一致性校验失败） |

结论：**方法必须以“自己生成 moc3”为前提**。第一条落地目标定在
**moc 版本 1（Cubism 3.0 基础格式）**——Core 5-r.5 向后兼容，且是字段最少、
最容易验证的一版；等需要乘算/屏幕色时再升到 v3.03。

## 8. 与 Unity 侧的根本差异（必须写进设计）

| Unity | Live2D |
| --- | --- |
| SkinnedMeshRenderer 逐顶点最多 4 骨权重 | **没有蒙皮**；ArtMesh 顶点只受 Deformer 层级变换 |
| Transform 任意 TRS（含非等比、剪切） | RotationDeformer 只有 angle/origin/**等比** scale |
| Animator 多层 + 加性混合 | 只有 motion 淡入淡出，无叠加层 |
| 运行时换 Sprite | 运行时不能换纹理，只能靠多 ArtMesh + opacity |
| BlendShape | 无对应概念，只能曲线拟合 |
| 渲染顺序 signed int sortingOrder | Part keyform `draw_order`（浮点）+ mask |

这几条不是“配置问题”，是模型表达力的硬边界，必须在误差预算里显式记账。
