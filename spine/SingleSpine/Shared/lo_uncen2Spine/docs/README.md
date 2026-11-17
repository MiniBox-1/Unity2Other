# docs 索引（2026-09-19 整理后：**常读 5 份**）

> **路径对照（2026-10-14 目录分区后补注）**：本文写于旧目录结构（老主仓 `D:\VB\Unity2Spine`）。**正文的结论/数据/手段仍然有效**，只是路径要换算 —— 对照表见 [路径对照.md](路径对照.md)（工具现在在 `src\tools\`，配置在 `config\`，第三方在 `deps\`）。

> **2026-10-08 更新**：**多骨骼分支（真骨骼树 + 加权 mesh）已重新开工**并整理成
> [`多骨骼_真骨骼树.md`](多骨骼_真骨骼树.md)：格式层（3.8 加权打包、骨表、槽位、
> `hull`/`path` 硬约束）已全部对齐并通过自检，体积实测 **19.2 MB vs 现产物 JSON 72.5 MB**；
> **唯一卡点**是"查看器里骨链渲染塌"（根骨探针正常、深骨探针无墨迹 ⇒ 链组合有出入），
> 下一步按**链深度二分**定位。该分支**新增文件只有 `tools/convert_bones.py`**，
> `_probe50_rt4` 全部仍是 9-18 时间戳，**主交付不受影响**。

把 Unity 工程里的 **2DModel prefab**（`SpriteRenderer` + `SkinnedMeshRenderer` + `Animator`）
**离线**转成 **Spine 3.8**（`Root` + 每部件一个 mesh + `deform` 时间线），并给出可复现的校验闭环。
**只用磁盘静态资源**；Unity 编辑器/运行态导出的 PoseFrames / PlayFrames / `_refshot_*` 等
**只做校准，不进成品**。

---

> **想先看"这份代码是干什么的 / 这条命令怎么抄"** → 看仓库根目录的
> [`../使用与代码导览.md`](../使用与代码导览.md)（人读版，按"想干什么 → 抄哪条"组织）。

## 常读 5 份

| 文档 | 什么时候看 |
| --- | --- |
| [**交接与核查.md**](交接与核查.md) | ★**接手先读这份**：环境与目录地图（§0）、现在的问题（§1）、手段（§2 真值/反汇编/四层校验/决策树）、标准 6 步（§3）、**铁律与坑（§4，含 18 条已定案规则 §4.3）**、五分钟命令（§5）、其它文档（§6）、下一步（§7） |
| [现状与问题.md](现状与问题.md) | 产物与验收数字、**未闭环清单**、建议顺序 |
| [历史问题与修复.md](历史问题与修复.md) | **现象→根因→修法→数字**（14 节，含"改了又被推翻"的记录）；动手前先在这里搜一遍 |
| [导出指南_Unity运行时数据.md](导出指南_Unity运行时数据.md) | 要**重新采真值**时：Unity 菜单怎么点、落点契约、常见坑 |
| [渲染顺序_反汇编研究.md](渲染顺序_反汇编研究.md) | 排序规则的证据链（成对实测 + 反汇编 + 反射读 `sortingKey`） |
| [**多骨骼_真骨骼树.md**](多骨骼_真骨骼树.md) | **要接着做"瘦身/真骨骼树"这条分支时先读**：本轮修掉的三个真 bug（3.8 加权打包格式、顶点组不能少写、宿主节点不能当骨）、已验证/未通过清单、三条"会让查看器崩"的硬约束、工具与按链深度二分的下一步 |

## 另一条线（不在这 5 份里）：Mobile-old 的 CS 脚本烘焙

`归档-proj-Mobile-old`（157 个 `*.uAnim.prefab`）要把 **CS 脚本的运行态影响**
（Puppet2D 样条/IK、DynamicBone 弹簧）一起转进 Spine。这条线的完整交接**不在本目录**，
在用户工作区：

* 接手先读 → [`Mobile-old_Spine转换_交接文档.md`](../../../LO/Docs/Mobile-old_Spine转换_交接文档.md)
  （现状 / 两条路线 / **必看约束 42 条**（§4 + §4.7 + §4.8）/ 待办 / 复现命令）
* 过程与逐轮排查 → [`Mobile-old_CS烘焙_方法与进展.md`](../../../LO/Docs/Mobile-old_CS烘焙_方法与进展.md)
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
