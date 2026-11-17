# Unity 侧脚本快照（我们自己写的）

这份只是**快照**，用来让"换一台机器"时不用依赖 Unity 工程也能拿到这些脚本。
**真件在 Unity 工程里**（改脚本请改那边，改完再同步回这里）：

```
D:\VB\Search\NormalLocal\lastOrign\Assets\
├── Editor\          15 个 *.cs（+ .meta）  → 本目录 Editor\
├── Script\          ExportRoots.cs / AedaProbeRuntime.cs / TwoDModelDebugExporter.cs
└── PlayModeProbe\   PlayModeProbe.cs / SceneActivationController.cs
```

## 这些脚本各干什么

| 脚本 | 干什么 | 入口 |
| --- | --- | --- |
| `Editor\PlayRefShot.cs` | **参考帧采样**：Play 模式下按 `PlayRefShotPlan` 逐角色/状态/时刻出「PNG + 相机参数 + 同帧逐渲染器 JSON（路径/显隐/排序/世界顶点 `mesh.verts`/`stateTime`/`layers[]`）」；**拍前先把 Animator 冻住**（消除 2~3 帧相位差） | 菜单 `Tools/2DModel/运行时采样/参考帧…` |
| `Editor\ExportDrawOrder.cs` | **渲染顺序导出**：排序键 + 反射读 `Renderer.sortingKey` + 成对隔离渲染实测"谁盖谁"；默认 `observe`（不改场景） | 菜单 `Tools/2DModel/运行时采样/渲染顺序导出…` |
| `Editor\TwoDModelCalibExport.cs` | PoseFrames / PlayFrames / SceneT0 等（老口径真值） | 菜单 `Tools/2DModel/校准数据/…` |
| `Editor\ModelInspect.cs` | 编辑器/批处理真值（`_inspect_*`：每渲染器 dynamic.json） | 菜单 / batchmode |
| `Editor\StaticBindMetaExporter.cs` | 静态绑定元数据（`Data\StaticMeta`） | 菜单 |
| `Editor\TwoDModelSceneLayoutExporter.cs` | 场景布局（`Data\SceneLayout`：sprite 世界包围盒） | 菜单 |
| `Editor\PlayModeSamplerRunner.cs` / `PlayModeSamplerWindow.cs` | Play 模式采样（PlayFrames/playpose）；含 `PlaySampleLog`（统一日志到 `info\_logs\play_sample.log`） | 菜单 |
| `Editor\CalibTargets.cs` | 公共逻辑：按名字找角色、临时激活父链、采完还原（上面这些脚本都调它） | 被引用 |
| `Editor\BakeTailSpline.cs` | 尾巴样条烘焙（早期问题） | 菜单 |
| `Editor\AddPlayModeProbe.cs` / `BatchAttachComponent.cs` / `ExportSelected*.cs` / `remove.cs` | 批量挂组件、按选择导出、清理 | 菜单 |
| `Script\ExportRoots.cs` | **统一导出根**：所有动态导出都写到 `D:\VB\Unity2Spine\info`（只改这一个开关） | 被引用 |
| `Script\AedaProbeRuntime.cs` | aeda 的运行时探针（球体光效那类） | 挂组件 |
| `Script\TwoDModelDebugExporter.cs` | runtime 版调试导出 | 挂组件 |
| `PlayModeProbe\PlayModeProbe.cs` / `SceneActivationController.cs` | 场景逐个激活/还原（避免多角色互相遮挡、污染真值） | 挂在 Main Camera |

## 放到新机器上怎么用

1. 把 `Editor\`、`Script\`、`PlayModeProbe\` 三个目录**连同 `.meta`** 拷进新工程对应的
   `Assets\` 子目录（`.meta` 里的 GUID 要保留，否则场景里挂在这些脚本上的组件会丢引用）。
2. 若导出根要改，改 `Script\ExportRoots.cs`。
3. 这些脚本都**只依赖 Unity 自带 API**（`UnityEditor` / `UnityEngine`），不需要额外包。

> 备注：`.meta` 只对"挂进场景/被 prefab 引用"的脚本（`PlayModeProbe`、
> `SceneActivationController`、`AedaProbeRuntime`、`TwoDModelDebugExporter`）关键；
> 纯 Editor 菜单脚本丢了 GUID 也能重新生成。
