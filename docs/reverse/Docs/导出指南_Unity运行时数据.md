# 动态导出指南：从 Unity 导出运行时数据 → `D:\VB\Unity2Spine\info`

更新：2026-09-18。这份是**唯一一份"怎么导"的说明书**：落点在哪、菜单怎么点、
命令行怎么跑、**场景里只有一台原始照相机时怎么一步步做**、日志和体检在哪。

> 一句话：**所有 Unity 侧"动态导出"都写到 `D:\VB\Unity2Spine\info`**。
> 开关只有一处 —— Unity 工程里的 `Assets\Script\ExportRoots.cs` 常量 `ExportRoots.Root`。

---

## 1. 落点契约（谁写哪里）

| 产物 | 路径 | 谁写的 | 入口 |
| --- | --- | --- | --- |
| 参考帧（PNG + `_cam.txt` + 同帧逐渲染器 JSON） | `info\_refshot_<角色>\` | `Assets\Editor\PlayRefShot.cs` | 菜单 `Tools/2DModel/运行时采样/参考帧（带相机）…`（或"按内置清单开始"） |
| 渲染顺序（排序键 + 成对实测"谁盖谁"） | `info\_draworder_<角色>\` | `Assets\Editor\ExportDrawOrder.cs` | 菜单 `Tools/2DModel/运行时采样/渲染顺序导出：按内置清单开始` |
| 逐帧骨骼+顶点真值 | `info\Data\PoseFrames\<角色>.json` | `Assets\Editor\TwoDModelCalibExport.cs` | 菜单 `Tools/2DModel/校准数据/全部导出（…）` |
| t=0 真值（含 bones/bindposes） | `info\Data\SceneT0\<角色>.json` | 同上 | 同上 |
| 参考截图（1:1） | `info\Data\Frames\<角色>\*.png` | 同上 | 同上 |
| Play 真值（**显隐**/transform/顶点） | `info\Data\PlayFrames\<角色>@<Animator>@<状态>.json` | `Assets\Editor\PlayModeSamplerRunner.cs` | 菜单 `Tools/2DModel/运行时采样/采样窗口` / `开始采样（不用窗口）` |
| 场景布局（t=0，逐渲染器包围盒） | `info\Data\SceneLayout\<名称>_layout.json` | `TwoDModelSceneLayoutExporter.cs` | 菜单 `Tools/2DModel/Export Scene Layout` |
| 静态绑定元数据（bindposes/boneWeights/局部顶点） | `info\Data\StaticMeta\<角色>.json` | `StaticBindMetaExporter.cs` | 菜单 `Tools/2DModel/Export Static Bind Meta` |
| 选中对象的渲染器信息 | `info\Data\SelectedInfo\<对象名>.json` | `ExportSelectedInfo.cs` | 菜单 `Tools/2DModel/校准数据/导出选中对象的渲染器信息` |
| 选中对象的四张参考图 | `info\Data\Frames\_selected\<对象名>\` | `ExportSelected.cs` | 菜单 `Tools/2DModel/校准数据/导出选中对象（参考图）` |
| 批处理"一次全导"（含逐部件隔离） | `info\_inspect_<角色>\` | `Assets\Editor\ModelInspect.cs` | `-executeMethod ModelInspect.All` |
| 运行时兜底导出（稀疏帧/精灵列表） | `info\Data\PoseFrames\`、`info\RigDebug\` | `Assets\Script\TwoDModelDebugExporter.cs` | 场景里给物体挂组件，Play |
| 探针导出（probe） | `info\Data\PlayFrames\probe_step\` | `Assets\PlayModeProbe\PlayModeProbe.cs` | 挂组件 + Play |
| **日志** | `info\_logs\play_sample.log`（Play 采样/参考帧/渲染顺序共用，Console 也打）<br>`info\_logs\play_probe.log`（运行时探针）<br>`info\_logs\inspect.log` / `calib.log`（批处理自己传 `-logFile`） | — | — |

**为什么这么放**：`info` 在仓库里、**不在 Unity 工程里** ⇒ 导出**不会触发 Asset 导入**
（写 `Assets\Data` 会拖慢 Unity 并产生 `.meta` 垃圾）；同时和 `_probe50_rt4` 等产物同级，
备份/清理时一眼能找到。想换地方只改 `ExportRoots.Root` 一个常量。

> `ExportRoots.cs` 特意放在 `Assets\Script\`（**不是** `Assets\Editor\`），
> 这样**运行时**脚本（`AedaProbeRuntime` / `TwoDModelDebugExporter` / `PlayModeProbe`）
> 也能用同一个根。

---

## 2. 老路径 → 新路径（2026-09-18 已搬，**只挪不删**）

| 旧位置 | 新位置 |
| --- | --- |
| `<工程根>\lastOrign\_refshot_*` | `D:\VB\Unity2Spine\info\_refshot_*` |
| `<工程根>\lastOrign\_draworder_*` | `D:\VB\Unity2Spine\info\_draworder_*` |
| `<工程根>\lastOrign\_inspect_*` | `D:\VB\Unity2Spine\info\_inspect_*` |
| `<工程根>\lastOrign\RigDebug\` | `D:\VB\Unity2Spine\info\RigDebug\` |
| `<工程根>\lastOrign\Assets\Data\{PoseFrames,PlayFrames,Frames,SceneT0,SceneLayout,StaticMeta,SelectedInfo}` | `D:\VB\Unity2Spine\info\Data\…` |
| `<工程根>\lastOrign\Assets\Data\export_config.json` | `D:\VB\Unity2Spine\info\Data\export_config.json` |
| `D:\VB\unity_logs\play_sample.log` | `D:\VB\Unity2Spine\info\_logs\play_sample.log` |
| `<工程根>\lastOrign\play_probe.log` | `D:\VB\Unity2Spine\info\_logs\play_probe.log` |
| 工程根散落的 `_probe_banshee_skin1.json` | `D:\VB\Unity2Spine\info\_misc\` |

搬迁量：**18.71 GB / 7,560 文件**（`Assets\Data` 的 17.9 GB 是主体，
`PoseFrames` 11.4 GB + `PlayFrames` 6.3 GB）。原 `Assets\Data` 只剩 `.meta`，
已挪到 `D:\VB\Unity2Spine\_to_delete_20260918\Assets_Data_meta\`（要回退可原样放回）。
**新导出不会再写进 Assets**，所以 Unity 里 `Assets\Data` 这个目录以后不存在了。

---

## 3. 场景里**只有一台原始照相机**时，怎么导（重要）

**结论：什么都不用准备。** 四个会出图的脚本**各自新建临时正交相机**，采完销毁：

| 脚本 | 临时相机 | 取景方式 |
| --- | --- | --- |
| `PlayRefShot` | `refshot_cam` | 枚举目标的 `SpriteRenderer/SkinnedMeshRenderer/MeshRenderer`，用 `Renderer.bounds` 求包围盒 + 边距 → 定 `orthographicSize` 与中心；透明底 |
| `ExportDrawOrder` | `draworder_cam` | 同上（同帧多张图共用一台，透明底转白底） |
| `ModelInspect` | `inspect_cam` | 同上（批处理，1:1 ppu） |
| `TwoDModelCalibExport` | `calib_cam` | 按"网格 UV 张成 vs 世界张成"自动算 px/unit，做到与源贴图 1:1 |

所以：

* **不用**调主相机的焦距/正交尺寸/位置/背景 —— 它保持原样就行（脚本不碰它）；
* **不用**改 Layer、Sorting Layer、分辨率、Canvas 设置；
* **不用**把角色摆到镜头前 —— 取景按渲染器包围盒自动来；
* 只有两条硬要求：
  1. **目标角色在场景里**（不在也行：`ExportDrawOrderPlan.InstantiateMissing=true` 会从
     `Assets/prefabs/Change50` 临时实例化一份，采完销毁）；角色通常是 **inactive**，脚本会临时激活再还原；
  2. **Play 模式下它要真的被显示出来** —— 参考帧/渲染顺序默认 `TouchMode="observe"`：
     **一个字节都不改场景**，等游戏流程自己把角色显示出来再采（这样画面 = 直接 Play 的样子）。
     如果你的场景流程根本不会显示它，就把 `ExportDrawOrderPlan.TouchMode` 改成 `"force"`
     （脚本自己激活 + 强开渲染器），或先用菜单 `…/给场景里的角色批量挂采样脚本`。

两个出图细节（踩过坑，先知道）：包围盒退化（"严格可见渲染器 0 个"）时脚本会退化为
用全部渲染器取景，并在**日志里写明原因**；`ExportDrawOrder` 的透明底会转成白底。

---

## 4. 逐步导出（编辑器里点菜单，最常用的一条路）

### 第 0 步：准备

1. 用 **Unity 2022.3.3f1c1** 打开工程 `D:\VB\Search\NormalLocal\lastOrign`；
2. 等编译结束，Console **无 `error CS`**；顶部菜单出现 `Tools/2DModel`；
3. 确认场景里目标角色存在（`Assets/Scenes/save.unity` 里那批通常是 inactive，正常）；
4. 先看清内存红线：本机 15.8 GB，`PoseFrames` 全量很大（现有 11.4 GB）——
   **不要**同时开 Unity 批处理 + 编辑器。

### 第 1 步：校准数据（**Edit 模式**，不用进 Play）

菜单 `Tools/2DModel/校准数据/全部导出（PoseFrames + SceneT0 + 参考图）`

产出：`info\Data\PoseFrames\`、`info\Data\SceneT0\`、`info\Data\Frames\`。
只想导一部分时用同菜单下的"只导出 PoseFrames / 只导出 SceneT0 / 只导出参考图（1:1）"。
名单和开关来自 `info\Data\export_config.json`（`names` / `parts` / `autoDiscover` / `scene`）。

### 第 2 步：Play 真值（**必须进 Play**）

菜单 `Tools/2DModel/运行时采样/采样窗口` → 选名单/状态 → `开始采样`；
或者直接 `Tools/2DModel/运行时采样/开始采样（不用窗口）`。

产出：`info\Data\PlayFrames\<角色>@<Animator>@<状态>.json` + `_summary.json`；
日志 `info\_logs\play_sample.log`（菜单 `…/打开日志` 直接开）。采完自动退出 Play。

### 第 3 步：参考帧（带相机）（**必须进 Play**）

菜单 `Tools/2DModel/运行时采样/参考帧（带相机）…`：填「角色名」「状态名」「时刻(秒)」→ `开始（自动进 Play）`。
参数默认取内置清单（`PlayRefShotPlan`），也可用 `参考帧：按内置清单开始（不用窗口）`。

产出：`info\_refshot_<角色>\<角色>__<状态>__t<毫秒>.json` + `frames\*.png` + `*_cam.txt`。

### 第 4 步：渲染顺序（**必须进 Play**）

菜单 `Tools/2DModel/运行时采样/渲染顺序导出：按内置清单开始`
（参数在 `ExportDrawOrderPlan`：目标名单、状态、时刻、`PairScope`、`WriteImages`、`TouchMode`）。

产出：`info\_draworder_<角色>\<角色>__<状态>__t<毫秒>.json`（每渲染器排序键 +
**反射读到的 `Renderer.sortingKey`** + 并列组实测顺序）；`WriteImages=true` 才写 `frames\*.png` 与 `frames\pairs\`。

### 第 5 步：按需的其它导出（Edit 模式）

* `Tools/2DModel/Export Static Bind Meta` → `info\Data\StaticMeta\<角色>.json`
* `Tools/2DModel/Export Scene Layout` → `info\Data\SceneLayout\<名称>_layout.json`
* 选中对象 → `Tools/2DModel/校准数据/导出选中对象（参考图）` / `…导出选中对象的渲染器信息`

### 第 6 步：读结果 + 体检

### 4.7 2026-09-18 下午批次：一次采齐"待判的 5 条"

**背景**：这一批要判的是 ①banshee 手（同名孪生）②beasthunter 丢动作
③draculina `Tep_1` 7~10 s 抓绳子 ④cerberus_skin3 breast 尾部黑帧
⑤constantias2_skin1 breast 扭曲。都只需要"**同帧画面 PNG + 每渲染器信息
（含逐帧 `sortingOrder`）**"，不需要成对实测。

**已在 `ExportDrawOrderPlan` 里设好**（照抄即可，导完还原）：

```csharp
public const string Names =
    "BR_BeastHunter_NS1,2Dmodel_PECS_Cerberus_NS3_FBX,PECS_Draculina_NS1,Size_root";
public const string Times = "0.04,0.12,0.22,0.32,0.42,0.52,0.58,0.64,0.70,0.76,0.84,0.92";
public const string PairScope = "off";     // 只要画面+信息
public const string TouchMode = "force";   // 不等游戏显示，脚本自己激活目标
```

* 名字是**挂 Animator 的 GameObject 名**（匹配**大小写不敏感**）：`Size_root`
  会一起命中 `Size_root`/`size_root` 的 5 个角色（banshee_skin1、constantias2_skin1、
  constantias2_skin1S、constantias2_normal、cerberus_skin1）。
* 时刻表铺满全片（0.04 ≈ banshee 0.5 s；0.58~0.76 = draculina `Tep_1` 的 7.3~9.5 s；
  0.84/0.92 看 cerberus_skin3 尾部黑帧）。预估 **9 个目标 / ~26 条状态 / ~312 帧**。
* **`SceneActivationController` 会被脚本自动临时禁用并还原**（它会改部件 `activeSelf`，
  和导出同时跑会污染真值：实测 `constantias2_normal` 可见渲染器 34→37）；
  日志里会打 `已临时禁用 N 个 SceneActivationController…`。

跑法就是菜单 **`Tools/2DModel/运行时采样/渲染顺序导出：按内置清单开始`**，
采完自动退出 Play。产出在 `info\_draworder_<角色路径>\`（`*.json` + `frames\*.png` + `*_cam.txt`）。

导完把新增的那几个 `info\_draworder_*` 目录告诉我，用
`_scratch\truth_diag.py`（已支持按**归一化时刻**配对，并用文件名而不是 JSON 里的
`t`/`norm`）逐渲染器对账。

```powershell
# 渲染顺序：并列组实测顺序 vs DFS 序、全局逆序对
D:\Anconda\python.exe tools\read_draworder.py "D:\VB\Unity2Spine\info\_draworder_<角色>"
# 哪条排序规则能完全解释实测
D:\Anconda\python.exe tools\check_draworder_rule.py "D:\VB\Unity2Spine\info\_draworder_<角色>"
# 显隐：产物 vs Play 真值
D:\Anconda\python.exe tools\check_play_visibility.py _probe50_rt4\<角色>
# 几何：逐顶点世界误差
D:\Anconda\python.exe tools\calib_geo.py --prefab <prefab> --pose "D:\VB\Unity2Spine\info\Data\PoseFrames\<角色>.json" --only-spine-dir --spine-dir _probe50_rt4\<角色>
```

---

## 5. 命令行（batchmode）——**不能和打开的编辑器同时跑**

`ModelInspect`（一次把"参考图 + 渲染器信息 + 逐帧数据 + 逐部件隔离"全导）：

```powershell
& "D:\Unity\Editor\2022.3.3f1c1\Editor\Unity.exe" -batchmode `
  -projectPath D:\VB\Search\NormalLocal\lastOrign -quit `
  -executeMethod ModelInspect.All `
  -probePrefab Assets/prefabs/lo/banshee/banshee_skin1.prefab `
  -probeName banshee_skin1 `
  -probeStates breast -probeTimes 0,0.2 `
  -probePpu 320 `
  -logFile D:\VB\Unity2Spine\info\_logs\inspect.log
```

产出 `info\_inspect_<角色>\`（`renderers.json` / `dynamic.json` / `frames\` / `manifest.json`）。
`-probeOut <目录>` 仍可覆盖根目录（默认已经是 `info`）。

`TwoDModelCalibExport`（校准数据全量，**出图所以不要加 `-nographics`**）：

```powershell
& "D:\Unity\Editor\2022.3.3f1c1\Editor\Unity.exe" -batchmode `
  -projectPath D:\VB\Search\NormalLocal\lastOrign -quit `
  -executeMethod TwoDModelCalibExport.ExportAll `
  -logFile D:\VB\Unity2Spine\info\_logs\calib.log
```

⚠️ **Play 模式的两个脚本（`PlayRefShot` / `ExportDrawOrder` / `PlayModeSamplerRunner`）
不能在 `-batchmode` 里跑** —— Unity 批处理进不了 Play 模式。它们只能在**打开的编辑器**里点菜单，
或先用 `…/给场景里的角色批量挂采样脚本` 挂好运行时探针再 Play。

---

## 6. 参数从哪改（都在 C# 里，不用手输）

| 想改什么 | 改哪里 |
| --- | --- |
| 导出根目录 | `Assets\Script\ExportRoots.cs` 的 `ExportRoots.Root` |
| 参考帧的目标/状态/时刻/ppu/是否带 mesh | `Assets\Editor\PlayRefShot.cs` 末尾的 `PlayRefShotPlan` |
| 渲染顺序的目标/时刻/是否出图/是否实测成对 | `Assets\Editor\ExportDrawOrder.cs` 末尾的 `ExportDrawOrderPlan` |
| 校准数据的名单/部件/场景 | `info\Data\export_config.json` |
| Unity 批处理一次全导 | `ModelInspect.All` + `-probe*` 参数（见上） |

---

## 7. 常见坑

1. **日志找不到**：Play 采样/参考帧/渲染顺序共用 `info\_logs\play_sample.log`
   （旧文档里的 `D:\VB\unity_logs\play_sample.log` 已作废）。
2. **"导出后画面没变"**：查看器优先读 `.skel`。只更新 JSON 不重写 `.skel` ⇒ 画面不变
   （`python tools\write_all_skel.py _probe50_rt4 --force`）。
3. **批处理导不出图**：加了 `-nographics` 就没渲染；且 `-batchmode` 里**没有 Play 模式**。
4. **编辑器 + 批处理同开**：会抢工程锁，Unity 会报"另一个实例已打开该工程"。
5. **inactive 的 GameObject 采样失败**：Play 模式下 Unity 对 `inactive` 物体**不更新**
   `Animator`/`Renderer`（会提示"无法采样 inactive 的 GameObject"）⇒ 用脚本的临时激活
   （`force` / `activateEarly`），或让游戏流程把它显示出来（`observe`）。
6. **真值也要体检**：场景实例可能被改过、`t=0` 没应用 pose、
   某些渲染器的 `mesh.verts` 会出现 **NaN**（实测 10 帧里 6 帧）——用第 4 节那几行命令先筛。
7. **别让 probe 和导出同时跑**（2026-09-18 实测污染）：`SceneActivationController`
   （挂在 Main Camera 上、名单写死）在 Play 里会**主动开关部件的 `activeSelf`**，
   与 `ExportDrawOrder` 的 `observe` 模式一起跑时，采到的就不是"游戏真实显隐"。
   实测：`constantias2_normal` lobby n0050 的"可见渲染器"从干净的 **34** 变成 **37**。
   ⇒ 采之前把那个组件 **disable**，或把它名单改成你这次要采的角色。
8. **`_draworder_*` JSON 里的 `t`/`norm` 字段含义是反的**：文件名 `n0650` 是
   **归一化 0.65**（`TimesRelative=true` 时的输入比例），而 JSON 里写
   `t=0.65`、`norm=0.0519`（把归一化输入记成 `t`，`norm` 又除了一次时长）。
   对账一律按**文件名/归一化**走（`_scratch\truth_diag.py` 就是这么配的），
   否则会误判成"采的是秒"。（字段含义待修正）
9. **对账工具已支持两种导出格式**：`_scratch\truth_diag.py` 既能读
   `ExportDrawOrder`（`screenBox`，其 y 与 PNG **相反**），也能读 `PlayRefShot`
   （只有 `boundsCenter/boundsSize`，按相机投到 PNG），并按**归一化时刻**配对
   （`--times` 传归一化比例）。
