# Unity2Spine 多骨骼分支

正式物理位置：
`D:\VB\Convert\Spine\MultiSpine\LO\MutiBone`。  
`D:\VB\MutiBone` 是兼容旧脚本的入口；两者内容由 Junction/HardLink 对应。

多骨骼转换的代码、工具、产物和交接文档均在本目录。主交付
`SingleSpine\Shared\Unity2Spine` 只作为解析库和共享渲染工具使用，本目录的修改不改变
“单根 Root + deform”主路线。

## 入口

- 转换器：`src\convert_bones.py`
- 当前交接：[docs\多骨骼_真骨骼树.md](docs/多骨骼_真骨骼树.md)
- 批量 A/B：`tools\batch_ab.py`
- 抽稀回归：`tools\test_simplify.py`
- 结构校验：`tools\validate_multibone.py`
- 最终一键验收：`tools\validate_final.ps1`（同时生成 `out\_reg_final\manifest.json`）
- 最终产物可重现性：`tools\reproduce_final.ps1`（14 角色重导并逐文件比 SHA256）
- JSON/SKEL 加载基准：`tools\benchmark_load.py`
- 全 Prefab 批量转换：`tools\convert_all_prefabs.py`
- 全 Prefab 清单生成：`tools\make_all_prefabs_manifest.py`
- 双帧对比：`tools\compare_frames.py`
- Unity 运行时几何对账：`tools\compare_runtime_geom.py`
- Unity 运行时逐骨对账：`tools\compare_runtime_bones.py`
- 运行真值时间扫描：`tools\scan_runtime_geom_time.py`
- Unity/Spine 逐槽位显隐对账：`tools\inspect_runtime_slots.py`
- Unity 原始权重诊断：`tools\inspect_part_weights.py`
- 共享网格骨表/bindpose 审计：`tools\audit_shared_skins.py`
- 共享网格回归：`tools\test_shared_skin_audit.py`（由最终验收自动执行）
- 多 Animator/dedupe 宿主诊断：`tools\diagnose_animators.py`
- deform/多骨骼逐槽位几何对账：`tools\compare_skel_geometry.py`
- `.skel` 摘要/差异：`tools\skel_summary.py`、`tools\diff_skel_slots.py`
- 颜色/层/显隐诊断：`tools\probe_color.py`
- slot 颜色隔离对照：`tools\make_color_variant.py`
- 兼容产物入口：`out\`（其中正式入口指向 `..\Products`）

当前 157 角色全量产物正式位置：

```text
D:\VB\Convert\Spine\MultiSpine\LO\Products\Current
```

14 角色精选验证集正式位置：

```text
D:\VB\Convert\Spine\MultiSpine\LO\Products\Curated14
```

旧脚本入口 `out\_reg_final\` 和 `out\_all_prefabs\` 仍可访问。带 residual 的 Alice 对照帧在
`out\_alice_fix_fr\`；`out\_reg_final_fr\` 是 residual 修复前的对照帧。
修复前完整数据保留在 `out\_reg_before_residual\`。

**全部可转换 2DModel 动画 Prefab** 已输出到：

```text
D:\VB\Convert\Spine\MultiSpine\LO\Products\Current
```

工程中共有 1320 个 `.prefab`，其中 157 个是当前转换器支持的
`*.uAnim.prefab`，现已全部转换并通过结构校验；1163 个
`.Lihui/.Spine/辅助` Prefab 不是本转换器类型的输入，清单在
`Products\Current\non_uAnim_prefabs.csv`。全部产物约 962.6 MB。

转换器默认剔除“骨表短于共享网格 bindpose 且权重下标越界、同网格另有完整骨表”
的坏重复件。当前资产只命中 Banshee `parts_Hand_R_66`，最终 Banshee 由
57 槽位降为 56 槽位；需要复现旧问题时加 `--keep-degenerate-shared-skins`。

Unity 运行真值统一放在 `out\_refshot_u2s\`。多骨骼的 Babariana `/`
Banshee 采集已从 Unity 工程根目录迁到这里：

```text
out\_refshot_u2s\mb_bab_lobby_20261030_235739.jsonl
out\_refshot_u2s\mb_bab_lobby_20261030_235739.meta.json
out\_refshot_u2s\mb_bab_lobby_20261030_235739.dtseq.json
out\_refshot_u2s\mb_banshee_start_20261031_011203.jsonl
out\_refshot_u2s\mb_banshee_start_20261031_011203.meta.json
out\_refshot_u2s\mb_banshee_start_20261031_011203.dtseq.json
```

## 运行

先导出 deform 同源基准（需要 `--json`，多骨骼会读取每个 slot 的真实图集页）：

```powershell
$MB = 'D:\VB\MutiBone'
$PROJ = 'D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old'
$ASSETS = Join-Path $PROJ 'Assets'
$SCENE = Join-Path $ASSETS 'Sences\save.unity'
$PREFAB = Join-Path $ASSETS 'Prefabs\2DModel_BR_Banshee_NS1.uAnim.prefab'
$DEFORM = Join-Path $MB 'out\_deform_banshee'
$MULTI = Join-Path $MB 'out\banshee_multi'

Push-Location 'D:\VB\Unity2Spine'
D:\Anconda\python.exe -m ngui2spine.static_prefab_spine `
  $PREFAB $DEFORM --assets $ASSETS --scene $SCENE `
  --json --no-face-check
Pop-Location

D:\Anconda\python.exe "$MB\src\convert_bones.py" `
  $PREFAB $MULTI --assets $ASSETS --scene $SCENE `
  --reuse-from $DEFORM --simplify 0.05 --deform-residual 0.005
```

`--simplify 0` 是逐帧基线。`--simplify 0.05` 只删除能被线性插值表示的
骨键；如需排查动画差异，先用 0。

转换器默认同时生成标准 Spine 3.8 `.skel` 和调试 JSON。查看器会优先加载
`.skel`；只有用 `--no-skel` 才会退化为只写 JSON。多根 prefab 会自动增加
`__multi_root`，这是 Spine 3.8 二进制格式的必需约束。

骨变换口径：`translate/rotate` 写相对 setup 的增量，`scale` 写
`采样值 / setup` 的倍率。副 Animator 层按主转换器规则合成。建议始终使用
`--simplify 0.05` 控制完整动画内存。

转换器默认导出附件显隐时间轴。需要排除 slot 时间线问题时可用
`--no-slot-anims`；正常导出不要关闭。

`--deform-residual 0.005` 用于 Unity rig 中少量离面蒙皮骨：这些骨不能用
Spine 2D TRS 精确表达，转换器只对受影响的部件追加逐影响点 deform 校正。
传 `0` 可关闭。Alice 的胸翼/翅膀和 ConstantiaS2 SS1 的头发/围巾依赖该功能；
其余十二个已测角色未触发。

存在共享 controller 的多 Animator 角色时，可用 `--deduped-default` 让被
去重 Animator 播放自身默认状态，并用 `--secondary-phase` 指定该状态在动作
开始时已经播放的秒数。Beasthunter 当前按 playqueue 的 2 秒预跑导出：

```powershell
--deduped-default --secondary-phase 2.0
```

该组合不要直接用于 Babariana：它是三层 Animator，采集器只驱动 Base 层，
颜色/毛发/break 层必须继续走主转换器的层配对规则。

最终产物结构检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\validate_final.ps1
```

校验器还会检查 deform 引用的附件、时间顺序和 weighted-mesh deform
帧长度。`out\_reg_complete`、`out\_reg_true_scale` 和
`out\_reg_before_residual` 只是修复过程中的对照，不要作为交付输入。

当前验收：

- 十四个角色结构校验全部通过；
- Alice `Tep_1` 动作为 0.5 s 时，胸翼/翅膀中位几何差
  `0.01276~0.03284 → 0.00023~0.00094` 世界单位；
- 同帧 360 px 强差 `363 → 9`，平均差 `1.3990 → 1.2213`；
- Banshee `Start` setup 回归仍为平均差 `0.0366`、强差 `0`。
- Babariana 剩余差异已排除 slot 颜色、黑色阴影和 PMA：全白槽位与基线
  逐像素相同，移除阴影更差，强制 PMA 会把 IoU 降到 `0.41293`。
- Brownie 同名孪生节点验证：setup 平均差 `0.0008`、强差 `0`；
  `lobby` 动作中段平均差 `0.2097`、强差 `5`。
- Beasthunter 的去重 Animator 已改为播放自身默认 `lobby`；相对 Unity
  真值，最差槽位中位差由 `0.1301` 降到 `0.00336` 世界单位。
- Bheur 的 Base + Drone 多层动画已通过 Unity 真值：110 个匹配槽位
  最大中位差 `0.0519`，drone 两件为 `0.0136 / 0.0407`。
- Blackwyrm：setup `mean 0.0051 / gt32 0`，`breast` 中段
  `mean 0.2179 / gt32 190 / IoU 0.99933`。
- Circe：setup `mean 0.0197 / gt32 4`，`BreastTouch` 中段
  `mean 1.5077 / gt32 1617 / IoU 0.99522`。
- Cerberus NS3：历史 `breast` 黑剪影在 0.80/0.85/0.90 三个相位均未复现，
  平均差 `0.1279~0.4003`，inventory 34–37k ink。
- ConstantiaS2 SS1：`Tep_1` setup `mean 0.0053 / gt32 0`，动作中段
  `mean 0.1326 / gt32 4 / IoU 0.99940`；9 个 hair/scarf/chest 件触发 residual。

## 安全约束

- 运行转换、渲染或批处理前检查可用物理内存；低于 3 GB 不启动。
- 渲染器使用 `D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe`。
- 所有重任务串行执行；批处理外壳和 Python 子进程都必须能一起终止。
- 场景目录拼写是 `Sences`，不是 `Scenes`。
- 不要复制旧产物的 `.config.json` 到变体目录，否则查看器可能指向不存在的骨架。
