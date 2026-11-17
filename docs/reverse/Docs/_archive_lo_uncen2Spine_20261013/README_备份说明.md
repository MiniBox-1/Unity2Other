# lo_uncen2Spine —— Mobile-old（Unity 2D 骨骼动画）→ Spine 3.8 转换项目备份

## 0 增量同步（2026-10-11 第二轮，点击动作）

本次增量（细节见 `docs\Mobile-old_CS烘焙_方法与进展.md` §30/§31、`docs\Mobile-old_Spine转换_交接文档.md` 约束 33/34）：

* **代码**：`Unity2Spine\src\`（新）：`unity\unity_anim2d.py`（`_slope_token` 认 `±Infinity`）、
  `ngui\ngui_anim.py`（向量曲线常值段取左键值）、`convert\cs_runtime.py`
  （`snapshot_dynamics/restore_dynamics`）、`convert\static_prefab_spine.py`（CS 预跑到稳态）。
* **文档**：`docs\` 三个 md 已覆盖为今天版本。
* **交付**：新增 `deliverable\_Spine待检查_20261011_点击动作修复\`（10 个角色 + README）。
* **真值/脚本**：`Unity2Spine\_scratch\_probe\`（`kaen_*.py`、`scan_step_*.py`、`step_*.py`）、
  `Unity2Spine\_scratch\_csbake\partdump\kaen_*.json`、`Unity2Spine\info\_refshot_u2s\kaen_breast_*.jsonl`
  （**Play 逐帧真值**，判"常值段"必须用它）。
* **原语料仍是 10/10 版**：`products\` 需要在批次跑完后按新代码整体重刷
  （受影响：90 个带 CS 的角色 + 20 个"有常值段但不在 CS 清单"的角色）。
  → **已于 2026-10-11 15:35 重刷完毕**：批次合计
  优先代表 9/9 + 主批次 89/90（1 个失败是改代码时的瞬时窗口，已单独重转）+ 补充批次 20/20 + 收尾 13/13，
  **逐角色静态自检 118 行全 0**，`_scratch\_probe\check_fresh.py` 复查"应重转的 109 个角色"里
  **0 个陈旧**。批次日志：`Unity2Spine\_scratch\batch_cs_20261011_{130033,123716,131122,151528}.log`。
* **旧检查包**（`_Spine待检查_20261009`、`_20261010_乘法烘图集`、`_20261011_多层配对`、
  `_20261011_算法修复代表`）已从工作区移出；本备份的 `deliverable\` 仍保留历史版本以备查。

## 0.1 增量同步（2026-10-12，全量最终版）

* **代码**：`Unity2Spine\src\`（`convert\cs_runtime.py`：`apply_animated`/`snapshot_restore`、
  `U2S_CS_F32` 实验开关；`convert\static_prefab_spine.py`：**预跑默认 6s**、脚本字段接线
  `SCRIPT_FIELD`/`_wire_script`、常值段 `_slope_token`）、`tools\`、`_scratch\_probe\`（对拍脚本：
  `cmp_play_hair.py`/`cmp_play_bones.py`/`uv_mirror_check.py`/`cmp_hair_truth.py`）、
  `_scratch\_csbake\`（含 `dump_db_particles.cs` 等逐帧真值工具）。
* **文档**：`docs\` 覆盖为 2026-10-12 版：进展文档新增 **§30~§34**，交接文档新增**约束 33~38**。
* **交付**：`deliverable\_Spine待检查_20261012_全量最终\`（15 个角色 + README，按 Sampler.txt 逐条核对）。
* **产物**：`products\_spine_conv_cs_port\`（157 个角色）已按最终代码重刷
  （90 个带 CS 的角色全量重跑：预跑 6s + 脚本字段曲线 + 常值段 + 多层配对 + 乘法烘图集）。
* **Unity 侧工具**（在工程 `proj-Mobile-old\Assets\Raw\Scripts\`，不在本备份里）：`U2SFrameDump.cs`
  （Play 逐帧真值：顶点/UV/颜色/显隐/排序，`vertexFilter`/`recordUvs`/`prerollState`）、
  `U2SPlayQueueRuntime.cs` + `Editor\U2SPlayQueue.cs`（菜单 `Tools/U2S/按 playqueue 录 Play 逐帧真值`）、
  `U2SPlayDumpDriver.cs`（录完自动退出）、`Editor\U2SBindingDump.cs`（导出 clip 绑定清单）。
* **已知差距**（未修完）：多分叉极软发丝链（Cerberus 类）在最快摆动那几帧仍差几十像素
  （质心中位 0.46px、逐顶点中位 3.0px、最大 50.7px）—— 下一步用逐帧逐粒子真值定位，
  见交接文档**约束 38**。

备份时间：2026-10-10（Asia/Shanghai）
来源：`D:\VB\Unity2Spine`（转换器）+ `D:\VB\Search\New`（文档/交付/产物）+ `D:\Code\vs_cpp_code\Spine3.8-py`（绑定）
用途：在另一台机器上继续开发 / 复核 / 重跑转换。

## 1 目录结构

| 目录 | 内容 | 体积 |
| --- | --- | --- |
| `Unity2Spine\` | **转换器本体**：`src\unity2spine\`（转换/CS 运行时/Unity 资源解析/Spine 输出）、`tools\`（含 `bake_cs\` 采集与对账、`batch_cs_convert.py`、`batch_static_check.py`、`check_skel_vs_json.py`、`finalize_skel_only.py`）、`docs\`、`info\`（**游戏侧真值帧** `Data\PoseFrames`/`PlayFrames`、参考截图 `_refshot_*`/`_draworder_*`）、`gui\`、`samples\`、`_reverse\`（逆向件：`UP2022.dll(.i64/.pdb)`、`mono_player`、`UnityPlayer.dll(.pdb)`）、`_scratch\_csbake\`（逐帧真值 dump + 对账脚本 + 批量日志） | 20.9 GB |
| `products\_spine_conv_cs_port\` | **157 个角色的最终产物**（skel-only）：`<角色>.uAnim_static.skel` + `.atlas` + 图集 png + `<角色>.config.json` + `_static_info.json` + `README.md`。其中 **25 个用非普通混合的角色**已按"乘法烘进图集"的新口径重转（`_static_info.json` 里有 `multiply` 账本） | 2.9 GB |
| `products\_spine_conv_cs_port_旧_乘法烘图集前_20261010\` | 上述 25 个角色的**重转前快照**（A/B 对比、`check_multiply_bake.py --base` 用） | 0.68 GB |
| `products\_spine_conv\` | 基线产物（纯 clip、无脚本形变），验收对账的 `--product` 参照 | 151 MB |
| `products\_spine_conv_cs\` | 录制+合并路线的产物（Unity 真值路线，用于 A/B 与交付包） | 92 MB |
| `products\_spine_conv_cs_port_tol001\` | 旧裁剪阈值（0.001）的产物备份，用于对照 | 125 MB |
| `deliverable\_Spine待检查_20261009\` | 交付包：`基线\`、`CS合并后\`(A 精确 multiply)、`CS合并后_B_乘法烘暗\`(B)、`对比图\`、`移植版_离线_逐帧精确\` | 488 MB |
| `deliverable\_Spine待检查_20261010_乘法烘图集\` | **给用户肉眼看的新交付包**（25 个非普通混合角色 + README，说明该看哪些影子/加色件、已知特例）——按用户口径：**观感问题只看眼睛** | 小 |
| `binding\Spine3.8-py\` | 改过的 **spine3.8 pybind11 绑定工程**（含 `修改记录_20261009.md`、`预备修正.md`、`BUG_RangeBuffer_Mesh_OOB.md`） | 64 MB |
| `binding\viewer_patch\` | 查看器侧补丁：`SpineRender.py`（按槽位混合）、`Spine380.pyd`（新绑定）+ 旧版 `.bak_20261009` | 1 MB |
| `docs\` | `Mobile-old_Spine转换_交接文档.md`、`Mobile-old_CS烘焙_方法与进展.md`、`问题记录\` | 小 |

## 2 未备份（可在网上公开获取，或约定不打包）

* `third_party\`、`_reference\`（原始库/参考资料）、`__pycache__`/`*.pyc`
* `_probe50_rt4\`（4 GB 测试输出）、`delete\`（待删件）
* `D:\Libs\`（`spine-runtimes-3.8`、`pybind11-master` 等原始源码）
* Unity 安装、`proj-Mobile-old`（Unity 工程本体）、`.venv`、node_modules

> 说明：`info\Data`（PoseFrames/PlayFrames）虽然是从 Unity 工程导出的，但**网上拿不到**，
> 而验收/标定要用，所以保留了。

## 3 环境依赖（另一台机器上要装的）

* Python：`D:\Anconda\python.exe`（本机用的；任意 3.9+ 皆可，改脚本里的绝对路径）
* 查看器/渲染：`D:\VB\Viewer\Render\v4`（含 venv）；spine-cpp 绑定用 `binding\viewer_patch\Spine380.pyd`
  （编译：`MSBuild Spine380Binding.vcxproj /p:Configuration=Release /p:Platform=x64`，
  工程在 `binding\Spine3.8-py\`，依赖 `D:\Libs\spine-runtimes-3.8` 与 `pybind11`）
* 7-Zip（可选）：`D:\7z\7-Zip-Zstandard\7z.exe`

## 4 从零复现（关键命令）

```powershell
cd <备份>\Unity2Spine; $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
$A="<Unity 工程>\Assets"           # 需要 proj-Mobile-old（未含在本备份里）

# ① 单角色：纯离线转（标准导出=只出 .skel）
python -m ngui2spine.static_prefab_spine "$A\Prefabs\2DModel_3P_Alice_NS1.uAnim.prefab" `
    "<out>\2DModel_3P_Alice_NS1" --assets $A --skel --no-face-check --cs
# 需要 .json（仅 Debug/研究）时加 --json

# ② 全量 157 个（逐角色子进程、失败不中断、可 --skip-done 续跑）
python tools\batch_cs_convert.py --skip-done --no-static-check

# ③ 逐角色 QC（四项计数应全 0）
python tools\batch_static_check.py

# ④ 把旧产物统一成"标准口径"（删 json、config 改名并指向 skel）
python tools\finalize_skel_only.py --dry-run

# ⑤ skel ≡ json 一致性验收（用查看器 venv 的 python，一次一个角色）
& "D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe" tools\check_skel_vs_json.py --dir <产物目录>

# ⑥ 验收对账（需要 Unity 录的 verify json，见 tools\bake_cs\）
python tools\bake_cs\verify_merge.py --product <基线产物> --merged <候选产物> `
    --verify <verify_*.json> --calib <merge_report*.json>
```

## 5 现状与注意（详细见 `docs\` 两份 md）

* **全量 157/157 已转完**，逐角色 QC（`missingAnimated`/`missingStatic`/`visibilityConflicts`/
  `unknownCurvePaths`）**全部为 0**；标准导出为 **skel-only**，配置名为 `<角色>.config.json`。
* 精度：CS 运行时（clip 采样 / IK / DynamicBone / spline）与骨架、蒙皮都已用**逐帧真值**验证；
  Alice 移植版对 Unity 真值 `breast t=1.5` 中位 **0.0029px** / 最大 0.0430px（录制路线 0.0051/0.0533）。
* 已知未决：Alexandra 后发链的前几秒"启动瞬态"（中位 0.04px，最大 ~5.6px，属建链姿态口径差异，见进展文档 §16）；
  `Actor.cs`/`ActorPartsView.cs` 空壳脚本的换肤/部件开关未进链路（建议落成 Spine skins/attachment 时间轴）。
* 坑与约束：交接文档 §4 共 30 条（含关键帧裁剪阈值、零缩放 rig、skel≡json 验收、度量切换、
  `re.split` 的 maxsplit、Distribution 曲线等）——**动手前先读那一节**。
* **shader（2026-10-10 本轮）**：已做全量清点（`tools\shader_inventory.py` 全工程 494 材质/22 shader；
  `tools\shader_usage_inventory.py` 限 157 角色：只用到 6 种，其中 25 个角色用非普通混合）；
  修掉一个真 bug —— `mesh_style()` 以前**永远返回 normal**，蒙皮/静态网格的加色/乘法件全错
  （用户点名的 `2DModel_BR_May_NS3` 乘法阴影已修并验证）；内建 fileID 补齐 `202/206/10720`，
  自定义 shader 改为**读源码 `Blend` 指令自动识别**（含按 guid 定位）。
* **导出设定（2026-10-10 定稿，已落地）**：标准导出**只出 `.skel`**；配置名 `<目录名>.config.json`；
  **乘法件默认"直接对图集处理"** —— 该件 UV 矩形内 texel 改成 `黑 + α=1−m`
  （`m = min(1, i.color·2·_TintColor)·tex.rgb`），槽位写 `normal`，**不依赖运行时的 multiply 混合**；
  原理：普通 alpha 在 `src.rgb=黑` 时是 `out = dst×(1−src.a)`，令 `src.a=1−m` 即 `out = dst×m`，
  与 Unity 的乘法**逐像素等价**（因子为灰时完全等价）。
  "逐槽位 `blend=multiply` + 区域 α=1"归档为**实验口径**（`--multiply-blend` / `U2S_MULTIPLY_BLEND=1`），默认不用。
  受影响角色 = 用到非普通混合的 **25 个**（其余 132 个图集逐字节不变），**已重转两遍**并通过
  `tools\check_multiply_bake.py`（按 `_static_info.json` 的 `multiply` 账本逐条核验）。
  同轮修掉一个真 bug：`_bake_rects` 原来用开区间切片，比账本矩形**少烘 1 行 1 列** ⇒
  乘法件边缘会留 1px 浅粉接缝（加色件老路径同样有）；改闭区间后"改动像素数 = 矩形面积"。
* **验证口径（用户 2026-10-10 指令，别再混）**：
  **观感 / shader / 颜色** → **不跟 Unity 比**，产物丢进
  `deliverable\_Spine待检查_20261010_乘法烘图集\` 由用户**肉眼看**；
  **算法 / 运动 / 骨骼** → **必须与 Unity 导出的真值对照**（`PartDataRecorder.cs` / `verify_cs.cs` /
  `calib_geo.py` / `compare_play_truth.py`），并写清"真值怎么导的"。
* **待做（用户肉眼检查清单，9 条）**：完整列表与逐条初步分析见 `docs\Mobile-old_Spine转换_交接文档.md` §5.5。
  其中 `May_NS3` 阴影已修；其余（Echidna 灯光闪烁、PXSilky 胸口、RoyalArsenal 右腿镜像、
  Tomoe 头发飞、KunoichiKaen 嘴巴上移、Cerberus 头发像纸、Ignis 多 Clip、LRL_N/LRL_N2 头发乱飞）
  尚未动 —— 复现要点见该节末尾。
