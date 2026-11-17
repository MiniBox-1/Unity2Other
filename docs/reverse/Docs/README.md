# docs 索引（2026-10-31 更新：**常读 6 份**）

> **2026-11-03 目录归位**：单骨骼代码和共用工具现位于
> `D:\VB\UnityAnimation2Spine\SingleSpine\Shared\Unity2Spine`；
> `D:\VB\Unity2Spine` 是兼容旧命令的 Junction。Lo 正式产物在
> `..\..\LO\Products\Current`，BD 产物在 `..\..\BD\Products\_bdone_spine`。

> **2026-10-31 更新**：**多骨骼分支（真骨骼树 + 加权 mesh）已完成 14 角色最终交付**，
> 代码、工具、产物和文档统一在
> `D:\VB\UnityAnimation2Spine\MultiSpine\LO\MutiBone`。最终数据位于
> `out\_reg_final`，`validate_final.ps1` 返回 `FINAL_VALIDATION_OK roles=14`；
> 14 角色从 prefab/deform 重导后的 JSON/SKEL 与最终产物 SHA256 **14/14 逐字节一致**；
> SKEL 相对 JSON 的 14 角色累计加载时间约 **75×** 加速。
> 主交付 `_probe50_rt4` 的单根 Root + deform 路线仍未改动。

把 Unity 工程里的 **2DModel prefab**（`SpriteRenderer` + `SkinnedMeshRenderer` + `Animator`）
**离线**转成 **Spine 3.8**（`Root` + 每部件一个 mesh + `deform` 时间线），并给出可复现的校验闭环。
**只用磁盘静态资源**；Unity 编辑器/运行态导出的 PoseFrames / PlayFrames / `_refshot_*` 等
**只做校准，不进成品**。

---

> **想先看"这份代码是干什么的 / 这条命令怎么抄"** → 看仓库根目录的
> [`../使用与代码导览.md`](../使用与代码导览.md)（人读版，按"想干什么 → 抄哪条"组织）。

## 常读 6 份

| 文档 | 什么时候看 |
| --- | --- |
| [**交接与核查.md**](交接与核查.md) | ★**接手先读这份**：环境与目录地图、问题闭环总表、真值/反汇编/四层校验手段、标准流程、铁律与坑、命令和后续架构决策 |
| [现状与问题.md](现状与问题.md) | 产物与验收数字、A~J 问题闭环证据、后续架构决策 |
| [历史问题与修复.md](历史问题与修复.md) | **现象→根因→修法→数字**（14 节，含"改了又被推翻"的记录）；动手前先在这里搜一遍 |
| [导出指南_Unity运行时数据.md](导出指南_Unity运行时数据.md) | 要**重新采真值**时：Unity 菜单怎么点、落点契约、常见坑 |
| [渲染顺序_反汇编研究.md](渲染顺序_反汇编研究.md) | 排序规则的证据链（成对实测 + 反汇编 + 反射读 `sortingKey`） |
| [**多骨骼_真骨骼树.md**](../../../../MultiSpine/LO/MutiBone/docs/多骨骼_真骨骼树.md) | **多骨骼分支最终交接**：157 角色全量产物、14 角色精选验证、3.8 加权 mesh/residual/多 Animator 修复和加载性能 |

## 另一条线（不在这 5 份里）：Mobile-old 的 CS 脚本烘焙

`归档-proj-Mobile-old`（157 个 `*.uAnim.prefab`）要把 **CS 脚本的运行态影响**
（Puppet2D 样条/IK、DynamicBone 弹簧）一起转进 Spine。这条线的完整交接**不在本目录**，
在用户工作区：

* 接手先读 → [`D:\VB\Search\New\Mobile-old_Spine转换_交接文档.md`](../../../../../Search/New/Mobile-old_Spine转换_交接文档.md)
  （现状 / 两条路线 / **必看约束 42 条**（§4 + §4.7 + §4.8）/ 待办 / 复现命令）
* 过程与逐轮排查 → [`D:\VB\Search\New\Mobile-old_CS烘焙_方法与进展.md`](../../../../../Search/New/Mobile-old_CS烘焙_方法与进展.md)
* 仓库内的入口摘要 → [`../使用与代码导览.md`](../使用与代码导览.md) **§7 / §8**

**这条线 2026-10-10 已收官**：157/157 转完、逐角色 QC 四项全 0、产物 skel-only；
**乘法件改成默认"直接对图集处理"**（烘成 `黑 + α=1−m`、槽位 `normal`，不依赖运行时
multiply 混合），实验口径 `--multiply-blend` 归档保留。详见交接文档 §5.1.8 / 约束 20、29，
进展文档 §25，以及 `../更新摘要_20261010.md`。

**2026-10-12 补一轮（算法侧结案）**：上一轮遗留的"头发还差 21.9px / 逐顶点最大 50.7px"
查清是**对拍口径**问题、**不是转换器的错** —— ① 历史 Play 真值其实一直是**实帧率**
（≈35fps；`U2SFrameDump.Awake()` 读 `fixedFramerate` 时队列还没 `Set`，所以
`Time.captureFramerate` 从未生效）；② 也不能去固定它（本工程 Animator 是
`m_UpdateMode=2` **UnscaledTime**，固定帧长会让时间轴与动画速率分叉到 0.709×）；
③ `dump_db_particles.cs` 的 `frames` 循环嵌在 per-db 循环里、每帧又推进所有链
⇒ 第 2 条链的"帧 0"其实已经跑了 150 步（假 bug），已加 `db=<名字>`。
改成**逐帧逐粒子**验收（新工具 `_scratch\_probe\t_db_particles.py`，
`AnimationMode` + 固定 1/60 + 一次一条链）后：Alexandra `Hair` 最大 **0.003px**、
`Breast` **0.0018px**、Cerberus `Hair` 中位 **0.0004px**（最大 2.8px 只在最快摆动几帧）
⇒ **弹簧链（树/参数/积分/输出）逐项精确，算法侧没有待修项**。
新增口子只有一条：clip 里的 **`EventDynamicBone` 事件**（244 clip / 572 事件，
`data` = DB 名）与 `RefreshParam=false` 的关系未定论（交接约束 42 / §5.6、进展 §35.9）。
详见交接文档 §4.8 / 进展 §35，以及 `../更新摘要_20261012.md`。

相关的仓库内新增物：`src/unity2spine/convert/cs_runtime.py`（CS 的离线复刻，
`static_prefab_spine --cs` 用）、`tools/bake_cs/`（录制+合并+对账 27 支）。

## 第三条线：BdOne 的 NGUI 动态立绘（2026-10-14 全量转完）

BdOne（`D:\VB\Search\BdOne`）的"动态立绘"是 **NGUI `UISprite` 层级 + Legacy
`AnimationClip`**（不是 Animator/2DModel），走的是仓库里的 **B 路线**。
这一轮把 15 个角色 / **34 个服装**全量转成 Spine 3.8，并与 Unity 真值逐帧对账；
另外 2 个本来就是 Spine 的角色用多 Spine 合并导出，合计 36 个产物。

* 产物 → `_bdone_spine\`（65.6 MB / 221 文件，一个服装一个可打开的目录）
* 真值 → `_bdone_truth\`（`BdOne\Assets\Editor\BdTruthExport.cs` batchmode 导出）
* **接手先读** → [`BdOne_交接与后续.md`](BdOne_交接与后续.md)
  （现状 / 口径与铁律 / 验收数字 / 踩过的坑 / 后续工作清单 / 环境副作用）
* 路线与 4 个硬伤的证据 → [`BdOne_NGUI_转化.md`](BdOne_NGUI_转化.md)
* 本轮摘要 → [`../更新摘要_20261014.md`](../更新摘要_20261014.md)

一句话验收：`python tools\convert_bdone.py --out _bdone_spine` 之后跑
`python _scratch\bdone_check_v2.py _bdone_spine --bad 0.05`，期望
**34 个产物 0 个需要看**（位置 ≤0.0005 px、角度 0.0000°、矩形 ≤0.0002 px、
显隐 0 处不一致），结构自检与 `.skel` 读回 36/36。

## 归档（内容已压缩进上面 5 份，留着考古）

| 目录 | 内容 |
| --- | --- |
| `_archive_20260919/` | 本轮合并掉的：`交接必看.md`（上手版）、`综述.md`（项目全景）、`总正确转化.md`（规则清单+全部命令）、`分骨骼_体积试验.md`（已搁置的瘦身试验） |
| `_archive_20260917/` | 更早的交接长文（`交接_20260917_晚/深夜.md`）、逆向笔记、脚本 API、已知问题… |
| `data/` | 早期探针结果 JSON（`playframes_audit.json`、`probe50_rt2_convert.json`、`mouth_probe_20260915.json`） |

## 三十秒上手

```powershell
cd D:\VB\Unity2Spine; $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"

# 单角色重导（自带静态检查；期望结尾 [static_check] … 0/0/0/0）
python -m ngui2spine.static_prefab_spine `
  "D:\VB\Search\NormalLocal\lastOrign\Assets\prefabs\Change50\audrey_normal.prefab" `
  samples\2DModel\audrey\static_spine --assets D:\VB\Search\NormalLocal\lastOrign\Assets `
  --scene D:\VB\Search\NormalLocal\lastOrign\Assets\Scenes\save.unity --skel --no-face-check

# 显隐校验 / 几何对账 / .skel 审计
python tools\check_clip_visibility.py --spine-root _probe50_rt4 audrey_normal
python _scratch\geom_vs_refshot.py _probe50_rt4\bheur_skin1 `
  info\_refshot_bheur_skin1\bheur_skin1__breast__t0500.json breast 0.5
& "D:\VB\Viewer\Render\.venv\Scripts\python.exe" _scratch\q3_audit_load.py _probe50_rt4 --bin --max 12

# GUI（两条路线 + 校验/预览/交付）
python gui\gui.py
```

> **内存红线**：本机 15.8 GB，同时跑的峰值之和 ≤ 10 GB；重活先用 `tools\mem_probe.ps1` 量
> 进程树峰值；**大产物走 `.skel`，别直接读 JSON**。

## 仓库结构（2026-09-19 整理后）

```
src/unity2spine/     转换库（unity/ ngui/ convert/ spine/ validate/）
ngui2spine/          老 import 名的兼容层（只剩 __init__.py，指向 src/unity2spine_compat/）
tools/               命令行：批量/校验/渲染/内存探针
_scratch/            对账与探针脚本（26 个）+ 3 个已结案问题的证据件
gui/                 Tkinter 界面
_probe50_rt4/        当前全量产物（50 角色，含 .skel）
info/                Unity 侧动态导出根（Data 真值 + _refshot_*/_draworder_* + _logs）
_reverse/            反汇编工作区（UP2022.dll.i64 + ida_q.py 的结果）
_reference/          spine-cpp 参考源码；third_party/ samples/ tq_report/
_待删除_20260919/     本轮挪出来的中间件（15 GB / 9.6k 文件，**只挪不删**）
docs/                本目录（常读 5 份 + 两个归档目录）
```
