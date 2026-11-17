# BdOne（NGUI 动态立绘）全量转 Spine 3.8

更新：2026-10-14

把 `D:\VB\Search\BdOne` 里**基于 Unity 的动画**（NGUI `UISprite` 层级 +
Legacy `AnimationClip`）**全量**转成 Spine 3.8：

* 15 个角色 / **34 个服装子装配** → 34 个骨架（每个服装一个，可单独打开）；
* 另 2 个角色（`法兰`、`伊斯丽洛克`）本来就是 Spine 资源（多 `SkeletonAnimation`
  叠放），走 **多 Spine 合并**路线导出到同一目录；
* 每个服装都用 Unity 真值逐帧对过账（见下"校验"）。

产物根：`D:\VB\Unity2Spine\_bdone_spine\`

---

## 1. 为什么不是"直接跑老工具"

老的 NGUI 路线（`ngui.convert_chr`，2026-09 那套）在 BdOne 上跑得出东西，
但拿 Unity 真值一对，有 **4 个硬伤**（这一轮全部修掉，改在
`src/unity2spine/ngui/bdone_spine.py`，老入口 `convert_chr` 变成薄壳）：

| # | 症状（实测） | 根因 | 修法 |
| --- | --- | --- | --- |
| 1 | 有的件整个裁错图（阿波罗/协助的 `NpcGUI624` 被裁到了 `NpcGUI621` 上） | 老代码取"图集 asset **同目录第一张 png**"；`res/<目录>` 里一个目录放好几套图集 | 走 `UIAtlas.asset → mMaterial → m_Texture` 链路拿本图集自己的页 |
| 2 | 部件位置/尺寸差 **1~4 像素** | 手写的 NGUI 换算与 `UISprite.drawingDimensions` 不一致：① 奇数尺寸时把"补 1 像素"也算进了分母；② 没管 widget 的 `pivot` | 按 NGUI 源码（`UISprite.drawingDimensions` + `NGUIMath.GetPivotOffset`）重写，含 `mType`/`mFlip` |
| 3 | **20 多个部件整段不动作**（安洁利卡/原皮、库玛丽…） | 只读了 `m_RotationCurves`（四元数），**漏了 `m_EulerCurves`（欧拉角）**——BdOne 42 个 clip 里 37 个带这个字段，很多件只写在欧拉曲线里 | 解析 `m_EulerCurves`，按 Unity 的 `Quaternion.Euler`（ZXY）转角度 |
| 4 | JSON 的槽位时间线读不出来 / `.skel` 写出器报错 | ① `animations[x].slots` 写成了 **4.x** 的"套一层皮肤名"形状（3.8 的 spine-csharp/cpp 是**扁平**的）；② 没有槽位时间线时会写一个空壳槽位 `default` | 改成 3.8 的扁平写法；没有时间线就不写 `slots` |

另外补了两条：图集 region 名跨页重名时加后缀消歧；某条曲线/图集找不到时
**跳过并记账**（`_bdone_info.json` 的 `excludedParts`），不再静默丢件。

---

## 2. Unity 真值怎么来的（batchmode，不需要 MCP）

真值导出脚本：`D:\VB\Search\BdOne\Assets\Editor\BdTruthExport.cs`（本轮新增到工程里）。
它对 `Assets/prefab/chr` 下每个角色 prefab：

1. 实例化 prefab（`Object.Instantiate`）；
2. 对每个 `Animation` 组件的默认 clip，用 `AnimationClip.SampleAnimation` 按 0.05 s 步长采样；
3. 逐帧记录：每个 Transform 的 `localPosition / rotationZ / localScale / activeSelf`、
   `UISprite` 的 `color / width / height / depth / mType / mFlip / enabled`、
   **`drawingDimensions`（NGUI 真正用来画这张图的局部矩形）**、
   以及该 `UISprite` 解析到的 atlas region 元数据；
4. 每个 (角色, 服装) 一个 JSON → `D:\VB\Unity2Spine\_bdone_truth\<角色>__<clip>.json`。

复现命令（Windows PowerShell，Unity 关掉后跑；一次 1~2 分钟）：

```powershell
& 'D:\Unity\Editor\2021.3.45f2c1\Editor\Unity.exe' -batchmode -projectPath 'D:\VB\Search\BdOne' `
  -executeMethod BdTruthExport.ExportAll `
  -bdOut 'D:\VB\Unity2Spine\_bdone_truth' -bdStep 0.05 `
  -logFile 'D:\VB\Unity2Spine\_scratch\bd_truth_all.log'
```

> 注意：同一时刻只能有一个 Unity 实例持有该工程。跑之前先确认没有别的
> Unity 开着 BdOne（否则会 "another Unity instance is running with this project open"）。
> 工程保存版本是 2021.3.44f1c1，本机装的是 2021.3.45f2c1；batchmode 会直接
> 升级/重导（第一次跑会把 `com.unity.collab-proxy` 等包升一下）。

---

## 3. 校验：与 Unity 真值逐帧对账

对账脚本：`_scratch\bdone_check_v2.py`（读我们的产物 + `_bdone_info.json` 的
`pathToBone` 映射 + Unity 真值 JSON），比四件事：

1. 每个节点的**局部 TRS**（我们 setup + 时间线线性插值 vs 真值逐帧）；
2. 每个 sprite 部件的**矩形**（我们的 region attachment `x/y/width/height`
   vs 真值 `UISprite.drawingDimensions`）；
3. **显隐**（我们的 attachment 时间线 vs 真值 `activeSelf` 链 + widget enabled）；
4. **颜色**（我们的 color 时间线 vs 真值 `UISprite.color`）。

2026-10-14 结果（34 个服装 + 2 个合并产物，共 2000+ 帧 × 4000+ 节点对）：

| 指标 | 结果 |
| --- | --- |
| 局部位置差 | 最大 **0.0005 px**（中位 0.0000） |
| 局部角度差 | 最大 **0.0000°** |
| 部件矩形差（中心/宽/高） | 最大 **0.0002 px** |
| 显隐不一致 | **0** 处 |
| 颜色通道差 | ≤ **0.05**（细栅格采样后；修前最大 0.15） |
| "真值能画、我们缺槽位" | **0 处**（10 个在 Unity 里也解析不到 region 的部件除外） |
| 结构自检（`validate_spine`） | **36/36 通过** |
| `.skel` 读回 | **36/36 通过** |

细节表：`_bdone_spine\_verify_vs_unity.tsv`

**唯一的口径说明**：每个 clip 的**最后一帧**（t = clip.length）Unity 有
`m_LoopTime` 会绕回 0 秒，真值那一帧其实是循环起点，所以对账脚本对最后一帧
额外按 t=0 比一次（否则 4 个产物会各报 1 个"假差"）。

视觉抽查（离线渲染 `tools\rt_frames.py` + `vision.js`）：
`阿波罗/协助`、`温蒂` 渲染出的人形完整、无部件错位/断开。

### 被跳过的部件（不是丢件）

导出的 `UIAtlas.asset` 里有 10 个部件名查不到 region：
`skin80_Fhair3_3/4/5`、`skin80_Fhair4`、`skin80_Fhair5`、`skin80_acc1`（斐杰/圣诞新娘）、
`npc258_cape3_200`、`npc258_cape4_1`（阿波罗/原皮）、`npc256_arm2_4`（温蒂）、
`npc_eff3`（拉格瑞斯/呼噜呼噜，其图集整份缺失）。
**Unity 真值里这 10 件的 `hasRegion` 同样是 false**（`GetAtlasSprite()` 返回 null，
NGUI 根本不画）⇒ 我们"跳过并记进 `_bdone_info.json` 的 `excludedParts`"与 Unity
一致，不是转换丢件。对账脚本把这条当成一条**正向检查**：
凡是"真值有 region、我们却没有槽位"的才算错——本次 34 个产物的结果是 **0**。

---

## 4. 复现（全量）

```powershell
cd D:\VB\Unity2Spine
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"

# 全量转换（15 角色 34 服装，约 70 s，内存 < 1 GB）
python tools\convert_bdone.py --out _bdone_spine

# 单个角色 / 单步长
python tools\convert_bdone.py --chars 阿波罗,安洁利卡 --out _scratch\bdone_v2
python tools\convert_bdone.py --no-skel                      # 只出 json/atlas/png

# 与 Unity 真值对账（先跑 §2 的导出）
python _scratch\bdone_check_v2.py _bdone_spine --bad 0.05 `
  --tsv _bdone_spine\_verify_vs_unity.tsv

# 老入口（GUI / run_cli.py）现在也走同一套实现
python run_cli.py "D:\VB\Search\BdOne\Assets\prefab\chr\安洁利卡.prefab" <输出目录> 0.05
```

---

## 5. 产物形态

```
_bdone_spine\
├── <角色>\<角色>_<序号>_<服装>\
│   ├── <tag>.json          骨架（骨骼/槽位/皮肤/动画）—— 3.8 扁平 slots
│   ├── <tag>.skel          同一份的二进制（查看器优先读它）
│   ├── <tag>.atlas + <tag>.png   重打包的图集（只用到的裁切块）
│   ├── <tag>.config.json   查看器配置（文件名 = 目录名）
│   └── _bdone_info.json    对账手册（clip/时间线统计/缺件/region 来源/路径→骨骼）
├── 法兰\法兰_合并.*、伊斯丽洛克\伊斯丽洛克_合并.*   （多 Spine 合并产物）
├── convert_summary.csv
├── _verify_vs_unity.tsv
└── README.md
```

单位是 **NGUI 虚拟像素**（1 单位 = 1 像素、Y 向上、不翻转），与老 NGUI 路线口径一致。
查看器里 `scale_factor` 由转换器按骨架跨度自动写进 `.config.json`。

---

## 6. 已知限制 / 没做的

* **一个服装一条动画**：BdOne 的每个服装 prefab 只挂一个 clip（`m_Animations`
  只有一项），所以产物里每个骨架就一条动画；游戏里多套服装是**同屏叠放**播放的，
  产物也保持"一个服装一个骨架"（想合成一个骨架得先做 skin 化，见
  `_archive_20260917/其他路线与历史.md` §6 的讨论）；
* **`mType != Simple` / `mFlip != 0` / `mDrawRegion != 默认`**：`sprite_quad()`
  已按 NGUI 源码实现这几支（翻转换边距、Sliced/Filled 用 border 的 `pixelSize`
  仍假定为 1，因为 prefab 里没有 panel）；BdOne 这批资源里 `mType` 全是 0
  （Simple）、`mFlip` 全 0，所以实测没有走到这些分支；
* **点/触发的运行时动作**：游戏里由代码驱动的额外表现（不写进 clip 的）不在
  转换范围内——只能转磁盘上的 clip；
* `_bdone_truth\`（真值，约 6 MB）与 `_bdone_spine\`（产物，约 66 MB）都在
  Unity2Spine 仓库内，重跑会覆盖。
