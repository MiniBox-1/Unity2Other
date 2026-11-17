# Unity 逆向资料索引

日期：2026-11-06

## 目标

逆向资料用于核对转换器的算法语义，而不是替代 Unity 运行时真值：

- Unity 真值回答“实际画面和数值是什么”；
- IDA/Mono 资料回答“运行时为什么这样计算”；
- 转换器最后用同帧渲染、逐顶点几何和 Spine 读回校验。

## 主要输入

| 资料 | 路径 | 用途 |
| --- | --- | --- |
| Unity 2022 Mono 播放器 | `_reverse\UP2022.dll` / `UnityPlayer.dll` | 同名 UnityPlayer 拷贝，行为分析对象 |
| 官方 PDB | `_reverse\UP2022.pdb` / `UnityPlayer_Win64_player_mono_x64.pdb` | 符号、函数名和行号 |
| IDA 数据库 | `_reverse\UP2022.dll.i64` | 已分析库，避免重复建库 |
| Mono 运行时 | `_reverse\mono_player\MonoBleedingEdge` | mono-2.0-bdwgc 等运行时 |
| 托管程序集 | `_reverse\mono_player\local_Data\Managed` | 97 个游戏/Unity 托管 DLL，dnSpy/ILSpy 使用 |
| IDA 查询器 | `tools\ida_q.py` | info/names/strings/xrefs/disasm/decompile/funcs/calls/bytes |
| 请求与结果 | `_reverse\req_*.json`、`res_*.json`、`ida*.log` | 每轮反汇编证据和可复现参数 |
| Spine 参考实现 | `_reference\SpineSkeletonDataConverter` | `.skel` 格式与读写语义 |
| Unity 侧采集脚本 | `unity_editor_scripts` | 参考帧、渲染顺序、运行时探针 |

## 已用汇编确认的算法

### 1. 显隐与属性曲线

- `Animation::SetBoundCurveFloatValue` 的 `m_IsActive` case 使用
  `abs(v) > 0.001`，不是 `v >= 0.5`。
- `m_Enabled` 使用同一绝对阈值。
- `m_SortingOrder` 是浮点动画写入整数，带半整数和负数截断规则。
- `m_Sprite`/PPtr 换图是直接引用写入，不做插值，因此转换时按阶跃处理。

### 2. 曲线、TRS 与欧拉顺序

- AnimationClip 使用 Hermite 切线求值。
- 工程中 `m_EulerCurves` 的 `m_RotationOrder: 4` 对应 ZXY。
- 同一对象同时存在四元数和欧拉曲线时，运行时旋转通道以四元数为准。

### 3. BlendShape

- BlendShape 在蒙皮之前应用到局部顶点。
- `fullWeights` 是按帧的阈值，不是简单的 `weight / 100 × fullWeight / 100`。
- 多帧权重按阈值空间插值，非单调阈值在实际数据中存在。

### 4. 蒙皮

- Mecanim/Unity 走 `BakeMesh → SkinMeshCPU`，每顶点最多 4 骨影响。
- 转换器逐顶点使用骨骼局部坐标和权重，Spine 3.8 加权 mesh 使用打包顶点组。
- `vertices` 与 `uvs` 等长时才按无权 mesh 读取；否则读取
  `[boneCount, (boneIndex,x,y,weight)…]`。

### 5. Sprite 轮廓

- Unity 默认使用贴图 alpha 生成的 Tight mesh，而非四顶点矩形。
- 参考链：`GenerateSpriteOutline → MakeShape → mask/contour/select/simplify`。
- 转换器优先读 Sprite 资产自带 render mesh，缺失时才按 alpha 轮廓复刻。

### 6. 渲染顺序

`RenderObjectSorter::operator()` 的比较链：

1. packed `GlobalLayeringData`（层 + sortingOrder）；
2. renderQueue；
3. 相机深度；
4. SortingGroup 数据；
5. 若干内部稳定化字段。

`renderQueue <= 2500` 和 `> 2500` 是两套列表。非并列关系最终由 Unity 的
`Renderer.sortingKey` 与深度解释；同键真实并列仍需层级 DFS 规则。

### 7. Animator 多层

- Additive 层参考姿态来自 clip 的 `m_AdditiveReferencePoseTime`（工程中为 0）。
- 加性增量是 `clip(t) - clip(reference)`。
- 运行时旋转混合是四元数乘；本项目已测层均为单 Z 轴，当前欧拉实现等价。
- 层短于主 clip 时按自身时长循环。

## 重要结论与限制

- 显隐、属性写入、换图、BlendShape、蒙皮顺序、多层参考姿态和
  `Write Defaults` 来源均已与汇编核对。
- 加性层的多轴旋转应改为四元数乘，但当前工程未命中。
- `material._AdditionalAlpha` 等自定义 shader 属性依赖 shader，未导出。
- 任意 `m_SortingOrder` 置换不能全部改写为 Spine drawOrder 的 unsigned 偏移。
- `draculina` 手部排序和无索引绘制顺序的旧争议参见
  `docs\历史问题与修复.md` 与 `docs\渲染顺序_反汇编研究.md` 的勘误部分。

## 复现流程

```powershell
# 1. 复制 IDA 数据库，避免改写原库
Copy-Item .\_reverse\UP2022.dll.i64 .\_reverse\UP2022.work.i64

# 2. 设置查询
$env:REQ_INLINE='{"op":"decompile","ea":"0x180B39180"}'
$env:REQ_OUT='.\_reverse\res_check.json'

# 3. 运行 IDA
& '<IDA>\idat64.exe' -A -L'.\_reverse\ida_check.log' `
  -S'.\tools\ida_q.py' '.\_reverse\UP2022.work.i64'
```

每次查询应同时保存 `req_*.json`、`res_*.json` 和 `ida*.log`。结论必须优先
用同版本 Unity 实测复核，不能只凭函数名或单条控制流下结论。

## 分层打包

### GitHub 主快照

包含：

- 本索引；
- `tools\ida_q.py`；
- 全部 `req_*.json`、`res_*.json` 和 `ida*.log`；
- 逆向结论文档；
- mono_player 来源说明；
- `_reference` Spine 参考源码；
- Unity 侧采集脚本；
- 大型二进制文件的 SHA256 与大小清单。

### 完整逆向附件包

包含：

- `UP2022.dll` / `UnityPlayer.dll`；
- 两个 PDB；
- `UP2022.dll.i64`；
- 完整 MonoBleedingEdge；
- 97 个 Managed DLL；
- 同样的查询器、证据和文档。

完整附件包因单个 IDA 数据库超过 GitHub 普通文件限制，应作为 GitHub Release
附件或 Git LFS 对象发布。
