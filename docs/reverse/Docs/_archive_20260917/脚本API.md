# 脚本分类与 API 说明（2026-09-15）

分三类：**① 转换核心**（产出 Spine 产物）、**② 批量与编排**、**③ 验证/辅助**
（只读，用来证明产物对不对，不参与成品）。

所有命令都在 `D:\VB\Unity2Spine` 下执行；带 `$env:PYTHONUTF8=1` 更稳（中文路径/输出）。

---

## ① 转换核心

### `ngui2spine/static_prefab_spine.py` —— 磁盘静态解析 → Spine 3.8 产物

只读磁盘资源（prefab + clip + scene），**不使用 Unity 编辑器动态数据**。

```text
python -m ngui2spine.static_prefab_spine <prefab> <out_dir> --scene <save.unity>
       [--units px|world]   # 默认 px：1 单位 = 1 源图像素（按图片原尺寸渲染）
       [--pma]              # 全局预乘（给 spine-unity 用）
       [--skel]             # 额外写同数据的 Spine 3.8 二进制骨架
       [--clip <名>]        # 指定 setup clip（默认按 clip 资源名挑主 clip）
       [--skip-texture <子串>] [--skip-texture-file <清单>]   # 屏蔽编辑器助手贴图
       [--place X,Y]        # 对齐参考图的平移
```

**输出**（每个角色一个目录）：`<角色>_static.json`、`<角色>_static.atlas`、
`<角色>_static_N.png`、`_static_info.json`（部件表/动画表/屏蔽清单）、
`.config.json`（查看器直开）、`<角色>_static.skel`（带 `--skel`）、`README.md`。

**关键内部函数**（改代码时看这些）：

| 函数 | 作用 |
| --- | --- |
| `convert_static()` | 主入口：加载模型 → 选 setup clip → 收集部件 → 写产物 |
| `part_visible()` / `node_visible()` | 某一时刻部件是否可见。`node_visible` 沿父链走 Unity 的 `SetActive` 语义 |
| `_curve_lookup(curves, anim_path, prefix)` | 曲线查表。**副 Animator 的曲线 path 是相对它自己的**，要用 `prefix` 换算后再查 |
| `enumerate_clips()` | 列出本角色**所有 Animator 的所有 clip**，给每条 entry 挂 `_prefix` |
| `_active_at(keys, t, tans=None)` | 曲线求值。带 `tans`（关键帧切线）时按 **Unity 运行时语义**：`±Infinity` 段是常值段，其余 Hermite 插值；`tans=None` 退回老的"取最后一个 `time <= t`" |
| `unity_curve_eval()` / `active_is_on()` | Unity 的曲线求值 + 显隐判据（**`|v| > 1e-3`**，不是 `v>=0.5`）。依据见 [`Unity运行时逆向报告.md`](Unity运行时逆向报告.md) |
| `active_flip_times()` | 算"开/关"翻转时刻，插进 `probe_times`（插值曲线的可见窗从"离开 0"开始，不在关键帧上） |
| `unity_int_round()` / `sorting_change_times()` / `draw_order_offsets()` | `m_SortingOrder`（int 属性）的取整、生效值变化时刻，以及"目标顺序 → Spine drawOrder 偏移"的编码（偏移**非负**，不可表达时整条不导） |
| `compose_layers()` | 把其它 Animator 层合成进当前 clip：Override 覆盖、Additive 按 `v(t)=base+(over−over0)` 且短 clip **循环**；配合 `unity_2dmodel.parse_animator_layers()` |
| `color_timeline()` | `m_Color.*` / `material._Color.*` → Spine **slot 颜色时间轴**（只处理 classID 212/137） |
| `morph_positions()` | blendShape（`m_Shapes` + `blendShape.*` 曲线）在**蒙皮之前**加到局部顶点 |
| `pptr_value_at()` | PPtr 曲线（`m_Sprite` 换图）求值：阶跃，取最后一个 `time <= t` |

> ⚠️ `_curve_lookup` **不要**用"全局后缀匹配"兜底（第一版那样做过）：链上不该命中
> 曲线的祖先会命中，`node_visible` 里"整条链从头 inactive 就当场景摆放"的逃生口
> 被误触发，显隐会**极性反转**。只能按显式前缀换算。

### `ngui2spine/unity_anim2d.py` / `unity_2dmodel.py` / `unity_mesh.py`

底层解析：AnimationClip（含 `m_FloatCurves` 的折行 `path:` 拼接）、
prefab/scene 的 Transform 与 `m_IsActive`、Mesh 的 bindpose/权重。

> **折行坑**：Unity 序列化超长路径会折行，续行处**原本是一个空格**：
> `parts_Eye_normal` + `\n      (2)` == `parts_Eye_normal (2)`。
> 用 `"".join()` 拼会少一个空格，和节点真实路径对不上，整条曲线被静默忽略。
> 必须用 `" ".join()`（见 `unity_anim2d._read_path_field`）。

`parse_clip()` 现在把"除变换之外"的通道也一并解析出来（都按 path 索引）：

| 键 | 内容 |
| --- | --- |
| `active` / `active_tan` | `m_IsActive` 曲线 + 逐关键帧切线（判断显隐用） |
| `enabled` / `enabled_tan` | `m_Enabled` |
| `morph` / `morph_tan` | `blendShape.<通道名>`（百分比权重） |
| `pptr` | `m_PPtrCurves`（就 `m_Sprite`：换贴图/换表情） |
| `sorting` / `sorting_tan` | `m_SortingOrder`（int 排序值动画） |
| `color` / `color_cls` | `m_Color.*`、`material._Color.*` + 绑定组件的 classID |
| `material` | 其它 `material.*`（自定义 shader 属性，只做统计/告警） |

> `unity_2dmodel.parse_animator_layers()` 解析 AnimatorController 的**层**
> （名字/权重/混合模式/默认状态 clip），供 `compose_layers()` 做多层合并用。
> `unity_anim2d.quat_to_euler()` 是 Unity 的 ZXY 分解（归一化到 `[0,360)`），
> 加性层要把 prefab 的四元数姿态还原成欧拉再叠加。

### `ngui2spine/sprite_outline.py` —— Sprite 的 Tight 网格（2026-09-16 新增）

```python
build(tex_path, rect, pivot, ppu, extrude=0, alpha_cutoff=0, tol=0.07,
      min_island_px=64, max_verts=96, flip_x=False, flip_y=False, cache=None)
```

按 Unity 的 `SpriteUtility.GenerateSpriteOutline` 语义生成 sprite 的多边形网格：
掩码（`alpha > alpha_cutoff`）→ 按 `extrude` 膨胀 → 取轮廓 → **丢掉过小的孤立岛**
（默认 1% of 最大岛）→ **归一化容差**（`tol` ∈ [0,1]，与 Unity 的 `path::simplify`
同义）的折线简化 → 顶点预算内迭代放松 → 耳切三角化。返回
`{"positions","uvs","triangles",…}`（sprite 局部空间，pivot 在原点），失败返回
`None`，调用方回落四边形。

**逆向依据**（`_reverse/`，2022.3.3f1c1 的 `UnityPlayer.dll` + PDB，用
`tools/ida_q.py` 查）：`GenerateSpriteOutline` (0x180475360) →
`SpriteMeshGenerator::MakeShape` (0x18045C923) → `mask::initialize` / `contour` /
`path::select` / `simplify` / `opt` / `fit`。详见 `静态prefab路线.md` **3.26**。

### `ngui2spine/spine38_binary_writer.py`

Spine JSON → Spine 3.8 `.skel`。`write_skeleton_binary(dict, path)` 是转换器
`--skel` 与 `tools/write_all_skel.py` 共用的实现。

### 验证 / 逆向相关脚本（2026-09-14 整理进 `tools/`）

| 脚本 | 用途 | 典型用法 |
| --- | --- | --- |
| `tools/check_skel.py` | **二进制产物校验**：JSON → `.skel` → 本项目读回逐帧比对 →（加 `--ref-exe`）与 `third_party\SpineSkeletonDataConverter.exe` **逐字节对拍** | `python tools\check_skel.py <产物目录> --ref-exe` |
| `tools/compare_play_truth.py` | 产物 slot 显隐时间轴 vs **Play 真值**（`activeSelf && activeInHierarchy`）逐格比 | `python tools\compare_play_truth.py <产物json> <PlayFrames\…json> <状态名>` |
| `tools/audit_playframes.py` | **Play 真值质量审计**：transform 全程没变的文件是废数据（`info/Data/PlayFrames/` 里 11/96 个），顺带与产物比对 | `python tools\audit_playframes.py [--old]` |
| `tools/ida_q.py` | **IDA 批处理查询器**（`info/names/strings/xrefs_to/disasm/decompile/…`），逆向 UnityPlayer 用；`REQ_INLINE` 可传请求数组，一次加载跑多条 | 见 `docs\汇编核对清单.md` 第 6 节 |
| `tools/convert_all_2dmodel.py --scene <save.unity>` | 批量转换时可带 `--scene`（用场景实例姿态；要和 Play 真值比对时建议带上） | — |

---

## ② 批量与编排

### `tools/collect_convertible.py` —— 扫描"可转换清单"

```text
python tools\collect_convertible.py --json _convertible.json [--copy-to <目录>] [--include-main]
```

扫 `Assets/prefabs/lo/*/*.prefab`，产出可转换清单（本工程 412 / 413）。
**批量转换前必须先跑它**：目录里混着没有 Animator 的模型，直接批量跑会整批失败。

### `tools/convert_all_2dmodel.py` —— 批量转换

```text
python tools\convert_all_2dmodel.py --names-from _convertible.json \
       --out _probe50 --jobs 5 --json _probe50_report.json [--limit N]
```

- `--names-from` 只转清单里的（不传就会把 `prefabs/lo/*` 下**所有** prefab 全扫进来）
- 内部调 `probe_generality.run_one()`，后者 `subprocess` 调 `static_prefab_spine`
- **不透传 `--skel`** → 转完要用 `write_all_skel.py` 补

### `tools/write_all_skel.py` —— 批量补 `.skel`

```text
python tools\write_all_skel.py _probe50 [--force]
```

扫 `<root>/*/*_static.json`，用 `write_skeleton_binary` 写同名 `.skel`。
**JSON 变了之后必须 `--force` 重写**，否则会跳过已存在的旧 `.skel`（新旧不同步）。

### `tools/probe_generality.py`

`convert_all_2dmodel.py` 依赖的 `run_one()`；单独跑可以做泛用性抽样。**不要删**。

### `tools/fix_mesh_readable.py`

把"场景里 MeshFilter 真正引用到、且 `m_IsReadable: 0`"的 Mesh asset 打开
Read/Write（否则读 `.vertices` 会抛 `isReadable is false`）。
默认 dry-run，加 `--apply` 才改；`--all-rawlo` 放宽到 rawLo 全量。

---

## ③ 验证 / 辅助（只读）

### `tools/check_clip_visibility.py` —— **显隐的第一判据**

拿 **clip 的 `m_IsActive` 关键帧**当基准，逐帧比对产物的 slot 时间轴。
**不依赖 Unity**，离线可跑。

```text
python tools\check_clip_visibility.py <角色> [--top 6]
python tools\check_clip_visibility.py --all-in-probe50
```

内部要点：

| 函数 | 作用 |
| --- | --- |
| `parse_clip_isactive()` | 解析 clip 的 `m_IsActive`，路径用 `read_path_field()` **拼折行** |
| `effective_clip_curve()` | 把"节点自己的曲线 + 祖先的曲线"合成一条**有效**曲线（父链语义） |
| `states_by_animator()` | prefab 里每个 Animator → 它的控制器 → 状态表。多 Animator 角色必须按这个选 clip |
| `keys_match()` | 在 **0.05 采样网格**上比可见性，不是比关键帧列表 |

> 判定原则：**比"每个采样时刻可见/不可见"，不要比关键帧列表**。
> 阶跃曲线的首关键帧时刻无意义（3.0 秒前也保持首值）、转换器会合并连续同值的
> 冗余帧、关键帧还会吸附到采样网格 —— 比列表会大量假阳性。

### `tools/check_play_visibility.py` —— 用 Play 真值查"非动画驱动的显隐"

```text
python tools\check_play_visibility.py _probe50\<角色> [--play-dir <目录>] [--top 20]
```

只能用来查"Unity 里没被动画管、但被父链或渲染器开关"的显隐。

> ⚠️ **不要拿 Play 真值的 `activeSelf` 当显隐判据**：实测它会把 `m_IsActive`
> 粘在 ON（banshee 互补的眼/眉部件会 202 帧里 130 帧同时 ON），换成连续推进
> （`PlayModeProbe.advance = NaturalStep`）也修不好。详见主文档 8.1.8。

### `tools/static_check.py` —— 导出完整性静态检查

```text
python tools\static_check.py <prefab> --scene <save.unity> --spine-dir <产物目录>
```

输出一行关键指标：`场景渲染器 / 导出部件 / 动画中引用但未导出 / 静态可见未导出 /
与真值可见性冲突 / 曲线 path 对不上`。后两项应为 0。

### `tools/calib_geo.py` —— 逐顶点几何校准

```text
python tools\calib_geo.py --prefab <prefab> --scene <save.unity> --clip lobby \
       --only-spine-dir --spine-dir <产物目录> --times 0,1.5,2,6.5
```

和 Unity 的 `BakeMesh` 真值比逐顶点误差（世界单位）。真值来源是
Unity 工程里的 `info/Data/PoseFrames/` 或 `PlayFrames/*.playpose.json`。

### `tools/face_check.py`

单脸朝向的 vision 复核，产出渲染图对比。参考图用 Unity 截的 sprites 层。

### `tools/layer_report.py` —— 渲染顺序（相对层级）诊断（2026-09-15 新增）

```text
python tools\layer_report.py <角色名> [...]
```

一次打印：部件数 / 有排序曲线且值会变 / **全局 rank 会变** / **相对层级会变** /
需要的槽位数 / **有重叠邻居的部件数（平均邻居数）**。

- "全局 rank 会变"不等于"画面上会变"——单个部件跨过一堆**不重叠**的部件也会让
  rank 抖动；真正决定画面的是**重叠邻居内的相对次序**（相对层级）。
- **别把"0 变层"当结论**：先看"有重叠邻居"是不是非零（曾因为把部件字典传给了
  `order_at()`，导致排序值恒为 0、全库假报 0 变层）。

### `tools/rt_frames.py` —— 同进程多帧渲染（2026-09-15 新增）

```text
python tools\rt_frames.py <产物目录> <动画名> --out <目录> --times 0,0.25,0.5 --size 900
```

`render_offline.py` 的 `spine.time_norm` 只支持一个标量，逐帧核对要反复起进程
（每次都重建 GL 上下文，几秒）。这个工具复用同一个 GL 会话把一条动画的多个时刻
各渲一张，输出 `<产物名>__<动画>__t<毫秒>.png`，用来和 Unity 参考帧 / 用户截图逐帧对。

### `tools/overlap_report.py` —— "同族重复件"诊断（2026-09-15 新增）

```text
python tools\overlap_report.py <产物目录> [动画名…]
```

列出**同一族**（部件名去掉尾部编号后相同）里**同时可见、且 AABB 明显重叠**
（交集 ≥ 小件面积 60%、尺寸同量级）的部件对与持续帧数。用来快速判断用户报的
"多手 / 多口 / 多眼"属于哪一类：**同族互斥曲线**（主文档 3.24，Unity 自己也这么画）
还是**真重复导出的部件**。

---

## ④ Unity 侧脚本（不在本仓库）

在 `D:\VB\Search\NormalLocal\lastOrign\Assets\`：

| 文件 | 作用 |
| --- | --- |
| `PlayModeProbe/PlayModeProbe.cs` | 运行时采样组件（普通 MonoBehaviour，可挂场景角色）。`advance`：`NaturalStep`（新，默认）/ `Seek`（旧）；`outSubDir` 默认 `probe_step` |
| `PlayModeProbe/SceneActivationController.cs` | 挂在 Camera 上**逐个角色**跑：激活 → 唤醒 probe → 等采样完 → 关回去。`onlyNames` 可只跑指定角色 |
| `Editor/AddPlayModeProbe.cs` | 批量挂/卸 probe、刷新状态表、批量设置采样选项、给多 Animator 角色补挂 probe |
| `Editor/PlayModeSamplerRunner.cs` + `Window.cs` | 编辑器驱动版采样（`EditorApplication.update` 手推协程） |
| `Editor/ModelInspect.cs`（2026-09-15 新增） | **"查看一个角色"统一成一个命令**：一次跑出 `renderers.json`（静态清单：显隐/层序/材质/网格统计/贴图区）、`dynamic.json`（**真推进 Animator** 的逐状态逐帧运行时数据，含 `isVisible`、`Renderer.bounds`、`BakeMesh` 世界 AABB）、`frames/<状态>_t<毫秒>.png`（正交 1:1 渲染）、`part_<名>.json/.png`（单部件隔离 + 顶点/骨骼/贴图区）、`manifest.json`。菜单 `Tools/2DModel/查看/一键导出（全部）`；批处理 `-executeMethod ModelInspect.All -probePrefab … -probeName … [-probeStates a,b] [-probeTimes 0,1] [-probePart 名] [-probePpu 320]`。⚠️ 批处理无相机 ⇒ `isVisible` 恒 false；跑前要关掉编辑器（工程锁）。详见 [`待跑数据清单.md`](待跑数据清单.md) |

---

## 常见坑速查

| 现象 | 原因 |
| --- | --- |
| 曲线整条不生效 | Unity YAML 折行 `path:` 拼接少了空格 |
| 特效部件该亮不亮 / 被报"始终禁用" | 副 Animator 的曲线 path 相对它自己，要用 `_prefix` 换算 |
| 显隐极性反转 | 用了全局后缀匹配兜底，污染了 `node_visible` 的 `seen_active` 逃生口 |
| `isReadable is false` | Mesh 的 Read/Write 没开（`fix_mesh_readable.py`） |
| 批量转换整批失败 | 没先跑 `collect_convertible.py`，扫进了没有 Animator 的模型 |
| `.skel` 和 JSON 不同步 | 改了 JSON 后没 `write_all_skel.py --force` |
| 校验器大量假阳性 | 比了关键帧列表而不是采样网格；或没建模父链语义 |
