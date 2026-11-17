# GUI / CLI 使用说明

## 0. 准备

* Python：`D:\Anconda\python.exe`（3.13，已装 **PySide6 / Pillow / numpy**）。
* 位置：编辑 `config\lo_uncen2Spine.json`（Unity 工程、产物目录、真值目录…），
  然后 `D:\Anconda\python.exe src\tools\selfcheck.py` 确认解析结果。

## 1. 启动 GUI

```bat
run_gui.bat
:: 等价于
D:\Anconda\python.exe main.py
:: 指定解释器
set U2SPINE_PYTHON=D:\Anconda\python.exe && run_gui.bat
```

界面从上到下：

1. **线路（扩展库）**：`lo`（NormalLocal 2DModel 静态 prefab）/ `bdone`（BdOne NGUI 立绘）。
   换线路会自动带出该线路的默认 Assets、输出目录与专属参数。
2. **输入 / 输出 / Assets**：
   * 输入**单个 prefab** → 转一个；
   * 输入**目录** → **批量**：目录里所有 `*.uAnim.prefab`、`*.prefab` 按名字顺序逐个转，
     进度显示在按钮右边（`3/157 角色名`）。
3. **线路参数**：由该扩展库的 `options_schema` 动态生成
   （`lo`：`cs` 带 CS 烘焙、`json` 出 debug JSON；`bdone`：`sample_dt`、`max_atlas`）。
4. **环境变量（每角色口径）**：一行一条 `KEY=VAL`，与 `config\per_char_env.txt` 同义：

   ```
   U2S_LAYER_PHASE=0.499
   U2S_FORCE_INACTIVE=*:parts_BP_028
   U2S_CS_PREROLL_lobby=Start:2.0
   ```

5. **开始转换** → 后台线程跑、日志实时回显；**打开输出目录** 直接开产物目录。

> GUI 与 CLI 都只调 `Profile.run(ConvertRequest)`；**出问题先用 CLI 复现**，再把同样的参数搬回 GUI。

## 2. CLI

```bat
run_cli.bat list
::   bdone    BdOne（NGUI 动态立绘）        input=prefab
::   lo       lo（NormalLocal 2DModel …）  input=prefab

run_cli.bat run lo --input "D:\...\2DModel_3P_Alexandra_N.uAnim.prefab" ^
    --out "D:\...\_spine_conv_cs_port" --assets "D:\...\proj-Mobile-old\Assets" ^
    --env U2S_LAYER_PHASE=0.499

run_cli.bat run lo --input <prefab> --json        :: 研究用：同时出 debug JSON
run_cli.bat run lo --input <prefab> --no-cs       :: 不带 CS 烘焙
run_cli.bat gui                                   :: 等于 run_gui.bat
```

退出码：`0` 成功、`2` 找不到线路、`3` 线路返回失败。

## 3. 产物长什么样（标准导出）

```
<输出目录>\<角色名>\
     <角色名>.uAnim_static.skel            ← 二进制骨架（标准）
     <角色名>.config.json                  ← 查看器配置（与 .skel 同名同目录）
     <角色名>.uAnim_static.atlas + *_0.png ← 图集
     README.md / _static_info.json         ← 自检信息
     _calib\static_check.json              ← 静态检查报告（自动跑的）
```

* **标准导出只出 `.skel`**；`.json` 骨架仅研究/排查时用 `--json` 生成，别进产线目录。
* 批量转之前，旧产物会被搬到 `lo.del_dir`（默认 `D:\VB\Search\del\`）保留可回退。

## 4. 批量（推荐用脚本）

```bat
D:\Anconda\python.exe src\tools\batch_cs_convert.py                  :: 全量
D:\Anconda\python.exe src\tools\batch_cs_convert.py --limit 3        :: 冒烟
D:\Anconda\python.exe src\tools\batch_cs_convert.py --exact-file misc\verification\chars.txt
```

* 读 `config\per_char_env.txt` 的**每角色口径**，命中时会打印 `每角色口径 …`；
* 日志/汇总写在 `.cache\logs\`；
* 表里每条**必须自成一行开头**（粘在注释行末尾会被当注释截掉）。

## 5. 校验工具（`src\tools\`）

| 工具 | 用途 |
| --- | --- |
| `static_check.py` | 场景渲染器 / 导出部件 / 动画引用 / 可见性冲突 / 曲线 path 对不上 |
| `calib_geo.py` | 与 Unity 逐帧真值的几何误差（px） |
| `compare_play_truth.py`、`check_play_visibility.py` | 运动/显隐对拍真值 |
| `check_skel_vs_json.py` | `.skel` 与 `.json` 是不是同一份数据（用自带 Spine380 绑定） |
| `compare_products.py` | **新旧两批产物逐文件比 MD5**（重整/改码后的回归） |
| `batch_static_check.py` | 整目录静态检查 |
| `selfcheck.py` / `scan_abspaths.py` | 配置自检 / 硬编码绝对路径审计（退出码 0 = 干净） |
| `mem_probe.ps1` | 量整棵进程树的峰值内存（超限直接杀，防把机器跑崩） |

渲染对比（`rt_frames.py`、`bake_cs\render_cmp.py`）需要**外部查看器**，
位置来自配置 `external.viewer_*`（转换本体不需要它）。

## 6. 打包（Nuitka）——本机实测步骤

产物：`dist\main.dist\lo_uncen2Spine.exe`（约 130 MB 目录，双击即开；
`lo_uncen2Spine.exe --cli list` 也能当命令行用）。

```bat
:: ① 用**非 conda** 的独立解释器（关键！）
uv venv --python 3.13 --python-preference only-managed env\.venv-build
uv pip install --python env\.venv-build\Scripts\python.exe nuitka PySide6 Pillow numpy
:: ② 让脚本用这个解释器
set U2SPINE_PYTHON=%CD%\env\.venv-build\Scripts\python.exe
build_nuitka.bat
```

踩过的坑（都已在 `build_nuitka.bat` / `env\README.md` 里处理）：

1. **别用 Anaconda 的 python 跑 Nuitka**：`--enable-plugin=pyside6` 读 conda-meta
   会崩（`KeyError: 'files'`）。
2. **MSVC 运行库**：本机策略拒绝"按 `msvcp140.dll` / `vcruntime140*.dll` 这些名字直接建文件"
   （`EACCES`；写别的名字可以、rename 过去也可以）→ 构建时 `--noinclude-dlls=` 排除，
   构建后 `src\tools\fix_dist_runtime_dlls.py` 用"临时名 + 改名"补回。
3. **两个扩展库必须显式带上**：`--include-package=ext_bdone --include-package=ext_lo`
   ——冻结后没有 entry point 的 dist-info，`discover()` 会按包名兜底 import。
4. **Nuitka standalone 不设 `sys.frozen`** → 统一用 `unity2spine.paths.is_frozen()`
   （认 `__compiled__`）。
5. **`numpy` 是真实依赖**（开发机 Anaconda 自带，容易漏）。

随 exe 一起带的数据文件（bat 里已写）：`.u2s_root`、`config\lo_uncen2Spine.json`、
`config\per_char_env.txt`、`src\tools\{static_check,face_check}.py`。

## 7. 常见问题

| 症状 | 原因 / 处理 |
| --- | --- |
| `list` 空 / GUI 没线路 | `ext_bdone`、`ext_lo` 不在 `sys.path`（打包时少 `--include-package`） |
| `gbk codec can't encode` | 脚本开头跑 `unity2spine.console.fix_console()`（工具模板已含） |
| 找不到 Assets / 真值 / CS 烘焙 | 看 `docs\自包含与位置约定.md` 的配置键表，跑 `src\tools\selfcheck.py` |
| 转换很慢 / 卡住 | 16 GB 机器一次只跑一个；先看可用内存，`mem_probe.ps1` 可测峰值 |
| `.config.json` 加载失败 | 用 `--json` 出一次对照，确认 joints/slots 扁平化与皮肤层级（历史坑） |
| 改了代码怕输出变了 | `src\tools\compare_products.py` 与老产物逐文件比 MD5 |
