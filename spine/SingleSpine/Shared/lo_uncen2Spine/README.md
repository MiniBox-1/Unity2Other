# lo_uncen2Spine —— Unity 原生数据 → Spine 3.8（PySide6 GUI + 可扩展库）

> **目录位置（2026-11-03）**：本项目物理位于
> `D:\VB\Convert\Spine\SingleSpine\Shared\lo_uncen2Spine`；
> `D:\VB\lo_uncen2Spine` 是兼容旧命令的 Junction。

> **整项目介绍（推荐先读）**：[项目介绍.md](项目介绍.md) —— 是什么、怎么跑、目录结构、
> 两条线路、配置、工具、验证结论、已知坑，一页看全。

把 Unity 工程里的 2D 立绘/模型（Sprite + SkinnedMesh + Animator，含 CS 脚本烘焙）
离线转成 Spine 3.8 骨架。**代码自包含**：不在本文件夹之外读任何*代码*，
外部只有"用户数据 / 别人的工具"，位置集中写在 `config\lo_uncen2Spine.json`。

## 目录约定（一眼看懂）

```
lo_uncen2Spine\
├─ .u2s_root                  ← 项目根标记（代码靠它认根；打包时随 exe 放一份）
├─ main.py                    ← 唯一入口：GUI / CLI（`python main.py --cli list`）
├─ run_gui.bat  run_cli.bat   ← 双击/命令行入口（位置无关）
├─ build_nuitka.bat           ← 打包（→ dist\main.dist\lo_uncen2Spine.exe）
├─ pyproject.toml             ← 依赖声明（Pillow + numpy；GUI 另需 PySide6）
│
├─ src\                       ← ①【项目原代码】全部在这儿
│   ├─ unity2spine\           ←   总项目：公有转化代码 + 插件协议 + GUI + CLI
│   │   ├─ api\plugin.py      ←     Profile / ConvertRequest / discover（扩展协议）
│   │   ├─ gui\main.py        ←     PySide6 GUI
│   │   ├─ convert\ ngui\ spine\ unity\ validate\   ←  公有转化代码
│   │   ├─ paths.py           ←     位置解析（app_root / cfg / cache_dir）
│   │   ├─ env.py             ←     老绝对路径 → 当前位置（历史工具用）
│   │   └─ console.py         ←     控制台编码修正（GBK 不再崩）
│   ├─ ext_lo\  ext_bdone\    ←   ②【两个扩展库】（各自独立包 + entry point，分开放）
│   ├─ unity2spine_compat\  ngui2spine\   ← 老 import 名兼容层
│   └─ tools\                 ←   命令行工具（批量/静态检查/几何自检/渲染对比/CS 烘焙）
│
├─ env\                       ← ③【环境】打包用独立解释器 + 依赖清单（见 env\README.md）
│   ├─ .venv-build\           ←    uv 装的 CPython 3.13 + nuitka + PySide6 + numpy
│   ├─ requirements.txt       ←    运行期依赖
│   └─ requirements-build.txt ←    打包依赖
├─ deps\                      ← ④【其他依赖】（第三方，不改）
│   ├─ third_party\           ←    备用 skel 写出器 exe + spine-cpp 绑定源码 + 查看器补丁
│   └─ reference\             ←    第三方转换器源码参考
├─ config\                    ← ⑤【设定】
│   ├─ lo_uncen2Spine.json    ←    位置配置（唯一"外面在哪"的清单）
│   └─ per_char_env.txt       ←    每角色口径（相位/预跑/死曲线部件）
├─ docs\                      ← ⑥【文档】（结构/位置约定、使用说明、历史研究、tq_report）
├─ misc\                      ← ⑦【杂项】
│   ├─ unity_side\            ←    要拷进 Unity 工程的 C#（逐帧录制/playqueue/绑定导出）
│   ├─ legacy_gui\            ←    老 tkinter GUI（存档，已被新 GUI 取代）
│   └─ verification\          ←    检验结果（一致性对比报告 + 代表角色清单）
├─ examples\                  ← ⑧【例子】跑出来的样例产物（可删）
├─ dist\                      ← 打包产物（build_nuitka.bat 生成）
└─ .cache\                    ← 运行时缓存/日志（guid 索引、批量日志；可随时删）
```

依赖方向只有一条：**扩展库 → 总项目的 `unity2spine.api`**；总项目不反向依赖扩展库
（`discover()` 优先 entry point，冻结后按包名兜底 `FALLBACK_MODULES`）。

## 3 分钟上手

```bat
:: 0) 依赖：Python 3.10+（本机 D:\Anconda\python.exe，已装 PySide6/Pillow/numpy）
D:\Anconda\python.exe main.py --cli list          :: 看有哪几条线路（lo / bdone）

:: 1) 改位置：编辑 config\lo_uncen2Spine.json（Unity 工程、产物目录、真值目录…）
D:\Anconda\python.exe src\tools\selfcheck.py      :: 打印解析结果 + 自包含审计

:: 2) 转一个角色（lo 线路：2DModel 静态 prefab + CS 烘焙）
D:\Anconda\python.exe main.py --cli run lo ^
    --input "D:\...\proj-Mobile-old\Assets\Prefabs\2DModel_3P_Alexandra_N.uAnim.prefab" ^
    --out   "D:\...\_spine_conv_cs_port"

:: 3) 批量（读 config\per_char_env.txt 的每角色口径）
D:\Anconda\python.exe src\tools\batch_cs_convert.py --limit 3

:: 4) GUI（输入选目录 = 批量；"环境变量"框写每角色口径）
run_gui.bat
```

产物（每个角色一个目录）：
`<角色>.uAnim_static.skel`（标准）+ `<角色>.config.json`（查看器配置）+ 图集 `.atlas/.png`
+ `README.md`/`_static_info.json`（自检信息）。`--json` 出骨架 JSON，**仅研究用**。

## 两条线路

| 扩展库 | 输入 | 公有入口 | 说明 |
| --- | --- | --- | --- |
| `ext_lo` | NormalLocal 2DModel 静态 prefab（`*.uAnim.prefab`） | `unity2spine.convert.static_prefab_spine` | 老 GUI 的"路线 A"；支持 CS 烘焙（DynamicBone/GlobalControl） |
| `ext_bdone` | BdOne NGUI 立绘 prefab | `unity2spine.ngui.convert_chr.convert_character` | 老 GUI 的"路线 B"；多套皮肤 + 图集重打包 |

## 铁律（沿用）

* **算法/运动**要与 Unity 逐帧真值对拍（`src\tools\compare_play_truth.py` / `calib_geo.py`）；
  **shader/观感**不跟 Unity 比，交人眼。
* 标准导出只出 `.skel`；`--json` 只用于排查。
* 每角色口径写 `config\per_char_env.txt`：**每条自成一行开头**（粘在注释行尾会被截掉），
  批量脚本会打印 `每角色口径 …` 便于核对。
* 破坏性操作留可回退副本（旧产物先搬 `D:\VB\Search\del\`）。
* 16 GB 内存机器：跑重活前先看可用内存（`src\tools\mem_probe.ps1` 可测峰值），一次只跑一个。

## 文档地图（`docs\`）

| 文档 | 什么时候看 |
| --- | --- |
| [进度与后续](docs/进度与后续.md) | **先看这个**：这轮整理做了什么、验证到哪一步、还剩什么 |
| [自包含与位置约定](docs/自包含与位置约定.md) | 换机器 / 改位置 / 想知道"外面在哪"怎么定 |
| [GUI与CLI使用说明](docs/GUI与CLI使用说明.md) | 日常使用、批量、校验工具、打包 |
| [重构与验证_交接补充](docs/重构与验证_交接补充.md) | 这次目录分区改了什么、一致性对比结论 |
| [路径对照](docs/路径对照.md) | 读历史文档时把旧路径换算成现在的 |
| [Mobile-old_Spine转换_交接文档](docs/Mobile-old_Spine转换_交接文档.md)、[交接与核查](docs/交接与核查.md) | 口径/约束/手段的权威长文（写于旧结构下） |
| [Mobile-old_CS烘焙_方法与进展](docs/Mobile-old_CS烘焙_方法与进展.md) | CS 脚本烘焙（DynamicBone/GlobalControl）怎么做的 |
| [现状与问题](docs/现状与问题.md)、[历史问题与修复](docs/历史问题与修复.md) | 排障、看某个坑以前怎么修的 |
| [tq_report](docs/tq_report/README.md) | 早期画质/错位问题的调查记录 |
| [misc/verification/README.md](misc/verification/README.md) | 检验结果：一致性对比怎么跑、结论 |

## 自包含怎么保证

```bat
D:\Anconda\python.exe src\tools\scan_abspaths.py   :: 0 文件 / 0 处（退出码 0）才算干净
D:\Anconda\python.exe src\tools\selfcheck.py       :: 配置 + 老路径解析 + 上面的审计
```

位置优先级：**命令行参数 → 环境变量 → `config\lo_uncen2Spine.json` → 内置兜底**；
老工具里写死的老绝对路径由 `src\tools\deabs_paths.py` 统一改写成
`_resolve(r"...")`（值不变，只多一层位置解析）。详见
[docs/自包含与位置约定.md](docs/自包含与位置约定.md)。

## 打包（Nuitka，产物 dist\main.dist\lo_uncen2Spine.exe）

```bat
uv venv --python 3.13 --python-preference only-managed env\.venv-build
uv pip install --python env\.venv-build\Scripts\python.exe nuitka PySide6 Pillow numpy
set U2SPINE_PYTHON=%CD%\env\.venv-build\Scripts\python.exe
build_nuitka.bat
```

三个坑（`build_nuitka.bat` 里都已处理）：Anaconda 下 Nuitka 的 pyside6 插件会崩、
本机拒绝按 `msvcp140.dll` 等名字直接建文件、冻结后 `sys.executable` 不能当解释器。
细节见 [docs/GUI与CLI使用说明.md](docs/GUI与CLI使用说明.md)。
