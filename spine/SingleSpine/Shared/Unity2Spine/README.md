# Unity2Spine

把 Unity 里的 **2DModel 动态立绘**（`SpriteRenderer` + `SkinnedMeshRenderer` + `Animator`）
**离线**转成 **Spine 3.8**（JSON / atlas / `.skel`），并给出可复现的校验闭环。
**只用磁盘静态资源**；Unity 编辑器/运行态导出的 PoseFrames / PlayFrames / 参考帧
**只做校准，不进成品**。

> **新人先看这两份**：
> ① [使用与代码导览.md](使用与代码导览.md) —— **每个代码文件干什么、每条命令怎么抄**（人读版）
> ② [docs/交接与核查.md](docs/交接与核查.md) —— 手段 / 铁律 / 四层校验 / 坑 / 下一步（接手入口）

---

## 两条路线

| 路线 | 适用资源 | 入口 | 状态 |
| --- | --- | --- | --- |
| **A. 静态 prefab 路线** | NormalLocal 的 `SpriteRenderer + SkinnedMeshRenderer + Animator`（当前交付的 50 个角色） | `python -m ngui2spine.static_prefab_spine` | 当前主线 |
| B. NGUI 路线 / 多 Spine 合并 | BdOne 的 NGUI `UISprite` + Legacy `Animation`；已有多个 `SkeletonAnimation` 的合并 | `python tools\convert_bdone.py`（全量）；`gui\gui.py`、`run_cli.py`（单角色）；合并走 `ngui2spine.merge_*` | **2026-10-14 已全量跑通**：BdOne 15 角色 34 服装 + 2 个合并角色 → `_bdone_spine\`，与 Unity 真值逐帧对账通过（见 [docs/BdOne_NGUI_转化.md](docs/BdOne_NGUI_转化.md)） |

## 产物契约（一个角色一个目录）

| 文件 | 内容 |
| --- | --- |
| `<角色>_static.skel` | **标准产物**：1 根 `Root` 骨 + 每部件一个 slot/mesh + `deform` 时间线（逐帧蒙皮已烘进顶点）的二进制；查看器优先读它（快 7 倍、内存 1/15） |
| `<角色>_static.json` | 同一份数据的 JSON；**只在 `--json` 时写**（Debug/研究，体积是 skel 的 4~5 倍） |
| `<角色>_static.atlas` + `_0.png`… | 图集（加色件单独一页；**乘法件默认烘进图集**，必要时多出一张 `_mul` 小页） |
| `_static_info.json` | 对账手册：prefab/scene/clip/dt/units/origin/flipX/partsMeta…，含 `multiply` 段说明乘法件口径 |
| `<目录名>.config.json` / `README.md` | 查看器配置（**文件名 = 产物目录名**） / 可读摘要 |

单位默认是**源图像素**（`units:"px"`，1 单位 = 1 像素）；加色件按 alpha 预乘；
**乘法件（Unity `Particles/Multiply` 影子）默认"直接对图集处理"** —— 把乘法烘成
`黑 + α=1−m` 的 texel、槽位写 `normal`，产物不依赖运行时的 multiply 混合
（实验口径 `--multiply-blend` 才输出 `blend=multiply`）。

## 技术路线（A 路线）

```text
磁盘 prefab / save.unity / .asset / .anim
   │ ① 解析        unity/unity_parse · unity_2dmodel · unity_mesh · unity_anim2d
   ▼
TwoDModel（层级 / 部件 / Animator / 层）
   │ ② 对齐        筛角色子树 · 选主 Animator ·（副层按 weight 合并）· 重算 anim_path
   ▼
rest 表 + clip 曲线
   │ ③ 姿态与蒙皮  逐帧局部 TRS（M = T·R·S）→ 世界矩阵 → 蒙皮顶点
   ▼
每部件每帧的顶点世界坐标
   │ ④ 写 Spine    每部件一个 mesh attachment，顶点走 deform 时间线
   ▼
<角色>_static.json / .atlas / .png / .config.json /（--skel 时另出）<角色>_static.skel
   │ ⑤ 校验闭环    static_check → calib_geo / geom_vs_refshot → 显隐校验 → 渲染同帧对照
```

骨架只有一根 `Root`（不做骨骼还原），所以与 Unity 的逐帧蒙皮结果**逐点一致**；
代价是文件偏大、Spine 编辑器里不能直接拖骨骼（"分骨骼瘦身"试过，已搁置，
见 [docs/_archive_20260919/分骨骼_体积试验.md](docs/_archive_20260919/分骨骼_体积试验.md)）。

## 快速开始

```powershell
cd D:\VB\Unity2Spine
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"

# 单角色（自带静态检查；--skel 同时写二进制）
python -m ngui2spine.static_prefab_spine `
  "D:\VB\Search\NormalLocal\lastOrign\Assets\prefabs\Change50\audrey_normal.prefab" `
  samples\2DModel\audrey\static_spine `
  --assets "D:\VB\Search\NormalLocal\lastOrign\Assets" `
  --scene  "D:\VB\Search\NormalLocal\lastOrign\Assets\Scenes\save.unity" `
  --skel --no-face-check

# 批量 / 补 .skel（重活：先量内存，见 tools\mem_probe.ps1）
python tools\convert_all_2dmodel.py --prefab-dir "...\Assets\prefabs\Change50" `
  --out _probe50_rt4 --jobs 2 --scene "...\Assets\Scenes\save.unity"
python tools\write_all_skel.py _probe50_rt4 --force

# 校验 / 对账 / 看图 / 界面
python tools\static_check.py "...\Change50\audrey_normal.prefab" --assets "...\Assets" --spine-dir samples\2DModel\audrey\static_spine
python tools\check_clip_visibility.py --spine-root _probe50_rt4 audrey_skin1
python _scratch\geom_vs_refshot.py _probe50_rt4\bheur_skin1 info\_refshot_bheur_skin1\bheur_skin1__breast__t0500.json breast 0.5
& "D:\VB\Viewer\Render\.venv\Scripts\python.exe" tools\rt_frames.py _probe50_rt4\banshee_skin1 lobby --out _scratch\_frames --times 0.1,0.5 --size 900
python gui\gui.py
```

> 两套 import 名都行：`python -m ngui2spine.static_prefab_spine …`（兼容层，仓库根即可）
> 或 `set PYTHONPATH=%CD%\src` + `python -m unity2spine.convert.static_prefab_spine …`（新库）。

## 目录（2026-09-19 整理后）

```text
D:\VB\Unity2Spine\
├── 使用与代码导览.md         ★ 人读版：每个代码干什么 + 每条命令怎么抄
├── README.md                 本文件
├── src\unity2spine\          转换库（真实现）
│   ├── unity\                prefab/场景/Transform/Mesh/Clip 解析
│   ├── ngui\                 老 NGUI 路线（图集打包、Legacy 动画、多 Spine 合并）
│   ├── convert\              static_prefab_spine（主）/ convert_2dmodel（公用几何）
│   │                         / frame_baked / single_frame_spine
│   ├── spine\                spine_out（JSON/atlas）、spine38_binary_writer（.skel）、
│   │                         spine38_binary（读回）、sprite_outline
│   └── validate\             validate_spine（自检）、merge_existing_spine（合并）
├── src\unity2spine_compat\   + ngui2spine\__init__.py   老 import 名的兼容层
├── tools\                    命令行：批量 / 校验 / 渲染 / 内存探针 / IDA 查询（24 个）
├── _scratch\                 对账与探针脚本（26 个）+ 3 个已结案问题的证据件
├── gui\gui.py + run_gui.bat  Tkinter 界面（两条路线 + 校验/预览/交付/对账）
├── docs\                     ★常读 5 份 + _archive_20260917/ + _archive_20260919/
├── _probe50_rt4\             当前全量产物（50 角色，4.0 GB，含 .skel）
├── info\                     Unity 侧动态导出根：Data\（真值）+ _refshot_* / _draworder_*
│                             / _inspect_* / _logs\      （怎么导见 docs\导出指南…）
├── _reverse\                 反汇编工作区（UP2022.dll.i64 + ida_q.py 的结果）
├── _reference\               spine-cpp 参考源码（写 .skel 时对着看）
├── samples\                  历史三主力样本（audrey / aeda / blacklilith）与 B 路线示例
├── third_party\              SpineSkeletonDataConverter.exe（对拍基线）
├── tq.txt + tq_report\       用户问题清单 / 逐条答复
├── _待删除_20260919\         2026-09-19 整理时挪出的中间件（15 GB，**只挪不删**）
└── pyproject.toml / run_cli.py / .gitignore
```

## 文档

| 文档 | 看什么 |
| --- | --- |
| [使用与代码导览.md](使用与代码导览.md) | **每个代码文件干什么、每条命令怎么抄**、出问题先看哪 |
| [docs/交接与核查.md](docs/交接与核查.md) | ★接手入口：环境与目录地图、手段、四层校验、铁律与坑、18 条已定案规则、下一步 |
| [docs/现状与问题.md](docs/现状与问题.md) | 产物与验收数字、未闭环清单 |
| [docs/历史问题与修复.md](docs/历史问题与修复.md) | 现象→根因→修法→数字（14 节） |
| [docs/导出指南_Unity运行时数据.md](docs/导出指南_Unity运行时数据.md) | Unity 菜单怎么把真值导到 `info\` |
| [docs/渲染顺序_反汇编研究.md](docs/渲染顺序_反汇编研究.md) | 排序规则证据链（实测 + 反汇编 + 反射 `sortingKey`） |
| [docs/README.md](docs/README.md) | docs 索引与归档说明 |
| [docs/BdOne_NGUI_转化.md](docs/BdOne_NGUI_转化.md) | **BdOne（NGUI 动态立绘）全量转 Spine**：4 个硬伤与修法、Unity 真值导出（batchmode）、逐帧对账数字、复现命令 |
| [docs/BdOne_交接与后续.md](docs/BdOne_交接与后续.md) | ★ **接 BdOne 这条线先读这份**：现状 / 口径与铁律 / 验收数字 / 踩过的坑 / 后续工作清单 / 环境副作用 |
| [更新摘要_20261014.md](更新摘要_20261014.md) | 上面这轮的摘要（产物在 `_bdone_spine\`，真值在 `_bdone_truth\`） |

## 铁律（违反过的都出过事）

1. **只用磁盘静态资源**转；真值不进成品。
2. **内存红线**：本机 15.8 GB，重活先量进程树峰值，同时跑的峰值之和 ≤ 10 GB；
   **大产物走 `.skel`，别读 JSON**。
3. 改完**只回归一个主力角色**（默认 audrey）；改了 JSON 必须**补 `.skel`**。
4. **判断"谁对"之前先怀疑真值**（采样口径坑见 `docs\交接与核查.md` §4.2）。
5. **导出设定不要乱动**（2026-10-10 定稿）：标准导出**只出 `.skel`**；配置名
   `<目录名>.config.json`；乘法件**烘进图集**、槽位 `normal`（`--multiply-blend` 才是实验口径）；
   改口径后只需重转"用到非普通混合"的角色（`shader_usage_inventory.py --out-txt` +
   `batch_cs_convert.py --exact-file`），并用 `tools\check_multiply_bake.py` 验收。
