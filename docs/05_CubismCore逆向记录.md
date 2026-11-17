# 05 Live2DCubismCore 逆向记录（5-r.5）

日期：2026-11-06
目标：`D:\VB\Convert\Live2d\Cubism\Plugins\Windows\x86_64\Live2DCubismCore.dll`（249,800 B，x64）
工具：`D:\Reverse\IDA_Pro_v8.3_Portable\idat64.exe`（8.3，Hex-Rays 可用）
脚本：`reverse\ida_q.py`（通用查询）、`reverse\scan_moc3.py`（字符串/魔数扫描）、
`reverse\decomp.py` / `reverse\deep.py`（强制重分析后反编译）

## 0. 结论速览

| 结论 | 证据 |
| --- | --- |
| moc 版本字节在 `+4`，合法范围 **1..6**，否则直接报错 | `sub_18000B810` |
| v<=5 的头部最小 `0x840`，上下文结构在 `+704`；v6 最小 `0xD40`，上下文在 `+1984` | `sub_18000D070` |
| SOT（160×u32）固定在 `+64`；上下文 `[0]=moc 基址, [1]=SOT, [2]=自身` | `sub_18000D070` |
| `csmHasMocConsistency` → `sub_18000B810`（校验） | 反汇编 tail-jump |
| `csmReviveMocInPlace` → `sub_18000CE30` | 同上 |
| `csmInitializeModelInPlace` → `sub_1800065F0(context, memory, size)` | 同上 |
| 模型需求大小由 `sub_180004BD0` 算出（660 字节布局结构），`sub_1800039C0` 填充 | `sub_1800065F0` |
| 每段的「元素大小/结构体偏移」表在 `0x180038008`，8 字节一项 | `.data` dump |

## 1. 校验入口

`csmHasMocConsistency(address, size)`：

```c
if (size < 0x40) fail("size invalid");
if (memcmp(address, "MOC3", 4)) fail("FileType is invalid");
ver = byte[4];
if (ver == 0) fail("ver invalid");
if (ver > 6)  fail("Core unsupport later than moc3 ver");
ctx = sub_18000D070(moc, size);          // 建上下文
...
sub_180008FE0(ctx, size, &hdr);          // Header section 校验
sub_180007CE0(ctx, size, &hdr);          // Data section 校验
```

错误字符串（`+0x2A4F8` 起）能直接定位失败环节：
`FileType is invalid` / `This moc3 ver is invalid` / `This moc3 size is invalid` /
`Header section is invalid` / `Data section is invalid`。

## 2. 头部与上下文（关键）

`sub_18000D070`：

```c
if (ver <= 5) {
    if (size < 0x840) return 0;          // 2112
    ctx = moc + 704;
    *(moc + 8)   = ctx;
    *(ctx + 0)   = moc;                  // 基址
    *(ctx + 8)   = moc + 64;             // SOT
    *(ctx + 16)  = ctx;                  // 自身
    return ctx;
}
if (size < 0xD40) return 0;              // 3392
ctx = moc + 1984;
...
```

含义：

- **SOT 永远是 `+64` 起的 160 个 u32**；
- v<=5 的上下文在 `+704`（SOT 之后 24 字节），v6 在 `+1984`；
- 段数据位置完全由 SOT 决定（我们自造的 v1 文件把段从 1984 开始，Core 照样接受，
  说明**不要求段从 0x840 开始**，只要求总大小 ≥ 0x840）。

> 这解释了为什么 `py-moc3` 把 `DEFAULT_OFFSET=1984` 当身体起点在 v1 上也成立：
> 1984 恰好是 v6 的上下文偏移，v1 下它只是“段放在哪里”的自由选择。

## 3. 模型构建链

`csmInitializeModelInPlace(moc, memory, size)`：

```c
rcx = *(moc + 8);            // 上下文（D070 写入）
sub_1800065F0(ctx, memory, size);
```

`sub_1800065F0`：

```c
sub_180004BD0(ctx, &layout, &need);   // 660 字节布局：各段 size/offset
if (size < need) return 0;
memset(memory, 0, need);
sub_1800039C0(ctx, memory, &layout, &need);   // 填模型结构
```

`sub_180004BD0` 里逐段计算 `layout[i] = count * elem_size`，元素大小来自
`0x180038008` 的 8 字节描述表（每项 `{u32 elem_size, u32 struct_offset}`），
例如 parts 区首项是 16、其后是 4/4/4/4/88/4/96……

模型结构是“每类对象一组指针/计数”的扁平结构，`csmGetDrawable*` 等导出函数
只是从该结构取字段 —— 所以**段顺序与含义由文件 SOT 决定，导出函数不参与解析**。

## 4. 对我们生成器的影响

1. 目标版本锁定 v1：版本字节 1，总大小 ≥ 0x840，SOT[0] 指向计数区；
2. SOT 顺序沿用已验证的顺序（parts → deformers → …），Core 按 SOT 取段，
   我们用真实 Core 的一致性校验 + 读回做回归；
3. 不需要伪造上下文结构（+704 处的 24 字节是 Core 运行时自己写的，
   我们只要保证文件头 64 字节 + SOT 正确）。

## 5. 由 Core 读回反推的语义（与反汇编互补）

反汇编给结构，读回给数值约定。以下全部用 `csmGetDrawableVertexPositions` 实测：

| 项 | 约定 |
| --- | --- |
| ArtMesh keyform 顶点 | 文件里 **Y 取反**（`stored_y = -model_y`） |
| Warp 网格点 | **不取反**，直接是模型空间坐标（定义绝对位置） |
| RotationDeformer 变换 | `p' = R(angle) · scale · p + origin` |
| RotationDeformer angle | 正角度 = **顺时针**（模型空间 `(x,y) → (y,-x)` = 90°） |
| RotationDeformer origin | 文件里 **Y 取反**（实测 (0,0.1) 写入 -0.1，读回 +0.1 位移） |
| deformer.types | `0 = warp`，`1 = rotation`；`specific_indices` 各自数组的下标 |
| keyform 位置池 | 先 warp 网格块、后 ArtMesh 顶点块；官方导出器每块 64B 对齐（读回只依赖 begin，可不对齐） |
| 父链 | 先子变换、再父变换（`p' = P(child(p))`） |

## 6. 复现

```powershell
$w='D:\VB\Convert\Live2d\reverse'
$env:REQ_JSON="$w\req1.json"; $env:REQ_OUT="$w\res1.json"
& 'D:\Reverse\IDA_Pro_v8.3_Portable\idat64.exe' -A -L"$w\ida.log" `
  -S"$w\ida_q.py" "$w\Live2DCubismCore.dll"
```

请求示例见 `reverse\req1.json` ~ `req8.json`；反编译输出在
`reverse\dec1.txt`、`deep_model.txt`、`deep2.txt`。

## 7. 未完成

- `sub_180008FE0`（10 KB，Header 校验）：已重分析，未逐条读完。
- `sub_180007CE0`（4.8 KB，Data 校验）：已重分析并反编译到
  `reverse\deep_data.txt`（1422 行）。快速判读结论：它按 counts 算出每段
  长度、与 SOT 偏移比对（不直接调用日志函数，失败由上层
  `csmHasMocConsistency` 报 `Data section is invalid`）。
  实测我们带 64B 对齐填充的 keyform 位置池也能通过，说明它**不要求**
  段内块严格紧排，只要求段起点/长度合法。
- v6 新增段（quad transforms、新的 draw order group 语义）未展开 —— 当前用不到。

## 8. moc3 v1 段表（实测，101 段）

用 `reverse\section_table.py` 把 SOT 跨度与「counts × 元素大小」逐一对照，
在 Koharu（17 部件）与 Natori（32 部件、11 个 glue）上**全部吻合**，
可以确认段顺序就是下表（SOT[0]=计数区、SOT[1]=画布，其余从 SOT[2] 开始）。

规则：

- SOT 每项是该段在文件内的**字节偏移**；段按 **64 字节对齐**；
- `runtime_space` 段是 8 字节/元素（核心运行时自用，生成时可清零）；
- 布尔数组按 4 字节（i32）存；字符串 64 字节定长；
- 段长度 = counts[count_idx] × 元素大小（下表最后一列，Koharu 实测）。

```text
SOT  段名                                              元素  数量    字节
  0  <count_info>                                        -     -     128
  1  <canvas>                                            -     -      64
  2  part.runtime_space                                   8    17     136
  3  part.ids                                            64    17    1088
  4  part.keyform_binding_band_indices                    4    17      68
  5  part.keyform_begin_indices                           4    17      68
  6  part.keyform_counts                                  4    17      68
  7  part.visibles                                        4    17      68
  8  part.enables                                         4    17      68
  9  part.parent_part_indices                             4    17      68
 10  deformer.runtime_space                               8    81     648
 11  deformer.ids                                        64    81    5184
 12  deformer.keyform_binding_band_indices                4    81     324
 13  deformer.visibles                                    4    81     324
 14  deformer.enables                                     4    81     324
 15  deformer.parent_part_indices                         4    81     324
 16  deformer.parent_deformer_indices                     4    81     324
 17  deformer.types                                       4    81     324
 18  deformer.specific_indices                            4    81     324
 19  warp_deformer.keyform_binding_band_indices           4    63     252
 20  warp_deformer.keyform_begin_indices                  4    63     252
 21  warp_deformer.keyform_counts                         4    63     252
 22  warp_deformer.vertex_counts                          4    63     252
 23  warp_deformer.rows                                  4    63     252
 24  warp_deformer.cols                                  4    63     252
 25  rotation_deformer.keyform_binding_band_indices       4    18      72
 26  rotation_deformer.keyform_begin_indices              4    18      72
 27  rotation_deformer.keyform_counts                     4    18      72
 28  rotation_deformer.base_angles                        4    18      72
 29  art_mesh.runtime_space_0                             8    91     728
 30  art_mesh.runtime_space_1                             8    91     728
 31  art_mesh.runtime_space_2                             8    91     728
 32  art_mesh.runtime_space_3                             8    91     728
 33  art_mesh.ids                                        64    91    5824
 34  art_mesh.keyform_binding_band_indices                4    91     364
 35  art_mesh.keyform_begin_indices                       4    91     364
 36  art_mesh.keyform_counts                              4    91     364
 37  art_mesh.visibles                                    4    91     364
 38  art_mesh.enables                                     4    91     364
 39  art_mesh.parent_part_indices                         4    91     364
 40  art_mesh.parent_deformer_indices                     4    91     364
 41  art_mesh.texture_indices                             4    91     364
 42  art_mesh.drawable_flags                              1    91      91
 43  art_mesh.position_index_counts  ← 真正的顶点数        4    91     364
 44  art_mesh.uv_begin_indices                            4    91     364
 45  art_mesh.position_index_begin_indices                4    91     364
 46  art_mesh.vertex_counts         ← 真正的索引数        4    91     364
 47  art_mesh.mask_begin_indices                          4    91     364
 48  art_mesh.mask_counts                                 4    91     364
 49  parameter.runtime_space                              8    52     416
 50  parameter.ids                                       64    52    3328
 51  parameter.max_values                                 4    52     208
 52  parameter.min_values                                 4    52     208
 53  parameter.default_values                             4    52     208
 54  parameter.repeats                                    4    52     208
 55  parameter.decimal_places                             4    52     208
 56  parameter.keyform_binding_begin_indices              4    52     208
 57  parameter.keyform_binding_counts                     4    52     208
 58  part_keyform.draw_orders                             4    17      68
 59  warp_deformer_keyform.opacities                      4   309    1236
 60  warp_deformer_keyform.keyform_position_begin_indices 4   309    1236
 61  rotation_deformer_keyform.opacities                  4    60     240
 62  rotation_deformer_keyform.angles                     4    60     240
 63  rotation_deformer_keyform.origin_xs                  4    60     240
 64  rotation_deformer_keyform.origin_ys                  4    60     240
 65  rotation_deformer_keyform.scales                     4    60     240
 66  rotation_deformer_keyform.reflect_xs                 4    60     240
 67  rotation_deformer_keyform.reflect_ys                 4    60     240
 68  art_mesh_keyform.opacities                           4   389    1556
 69  art_mesh_keyform.draw_orders                         4   389    1556
 70  art_mesh_keyform.keyform_position_begin_indices      4   389    1556
 71  keyform_position.xys                                 4 50624  202496
 72  keyform_binding_index.indices                        4    62     248
 73  keyform_binding_band.begin_indices                   4    49     196
 74  keyform_binding_band.counts                          4    49     196
 75  keyform_binding.keys_begin_indices                   4    52     208
 76  keyform_binding.keys_counts                          4    52     208
 77  keys.values                                          4   151     604
 78  uv.xys                                               4  3968   15872
 79  position_index.indices                               2  7815   15630
 80  drawable_mask.art_mesh_indices                       4     0       0
 81  draw_order_group.object_begin_indices                4     1       4
 82  draw_order_group.object_counts                       4     1       4
 83  draw_order_group.object_total_counts                 4     1       4
 84  draw_order_group.min_draw_orders                     4     1       4
 85  draw_order_group.max_draw_orders                     4     1       4
 86  draw_order_group_object.types                        4    91     364
 87  draw_order_group_object.indices                      4    91     364
 88  draw_order_group_object.group_indices                4    91     364
 89  glue.runtime_space                                   8     0       0
 90  glue.ids                                            64     0       0
 91  glue.keyform_binding_band_indices                    4     0       0
 92  glue.keyform_begin_indices                           4     0       0
 93  glue.keyform_counts                                  4     0       0
 94  glue.art_mesh_index_as                              4     0       0
 95  glue.art_mesh_index_bs                              4     0       0
 96  glue.info_begin_indices                             4     0       0
 97  glue.info_counts                                     4     0       0
 98  glue_info.weights                                   4     0       0
 99  glue_info.position_indices                           2     0       0
100  glue_keyform.intensities                             4     0       0
```

注意：

1. 第 43/46 段的名字是反的（公开库如此命名）——**43 = 顶点数、46 = 索引数**，
   这一点由 `csmGetDrawableVertexCounts/IndexCounts` 读回确认；
2. `keyform_binding_index` 的数量（62）与 binding 数（52）不相等，
   说明它**不是**「每个 binding 一个参数下标」；实测我们的模型按
   「binding 数 = index 数」写也能正确解析参数键，说明运行时主要走
   band → binding → keys 这条链，该数组更像编辑器元数据；
3. v6 会追加 `additional.quad_transforms` 等段，且头部偏移变为 +1984 —— 当前不用。

## 9. 「Cubism SDK for Unity」的逆向边界

5-r.5 的 Unity 侧（`Core`/`Framework`/`Rendering`/`Editor`）是**C# 源码**，
不需要 IDA；真正的二进制只有 `Plugins/<平台>/Live2DCubismCore.*`
（各平台是同一套 C API）。所以：

- 用 IDA 检查的对象 = `Live2DCubismCore.dll`（已完成，本文 1–8 节）；
- 用源码阅读的对象 = `Core\Unmanaged\CubismCoreDll.cs`（P/Invoke 全表）、
  `Editor\Importers\*`（资产导入语义）、`Framework\Json\*`（motion3 解析）；
- 两者交叉验证的点：`csmReadCanvasInfo` 的 5 个 float、`csmHasMocConsistency`
  的 64 字节对齐要求、`csmGetParameterKeyValues` 的每参数键数组。