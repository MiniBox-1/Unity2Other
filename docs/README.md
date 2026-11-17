# Unity Animation to Spine

整理日期：2026-11-03

本目录是 Unity 动画转 Spine 的统一工作根。按以下两个维度分开：

```text
SingleSpine\   单 Root + 逐顶点 deform / NGUI 单骨骼路线
MultiSpine\    真骨骼树 + 加权 mesh 路线
StaticSpine\   Mobile-old 无 Animator 的静态立绘多插槽路线

每条路线内部：
  LO\          NormalLocal / Mobile-old 2DModel
  BD\          BdOne NGUI 动态立绘
```

## 正式产物入口

| 路线 | 角色 | 当前正式产物 |
| --- | --- | --- |
| 单骨骼 | Lo | `SingleSpine\LO\Products\Current` |
| 单骨骼 | BD | `SingleSpine\BD\Products\_bdone_spine` |
| 多骨骼 | Lo | `MultiSpine\LO\Products\Current` |
| 多骨骼 | BD | `MultiSpine\BD\Products\Current` |
| 静态多插槽 | Lo `.Lihui` | 1148 个产物在 `StaticSpine\LO\Products\Current` |

单骨骼 Lo 的 `Current` 来自 2026-10-14 最新仓，包含 157 个
`*.uAnim.prefab` 的 skel-only 产物。旧版 `_spine_conv_cs_port`、基线版、
CS 合并版、乘法和 tolerance 实验版都在 `SingleSpine\LO\Versions`。

多骨骼 Lo 的 `Current` 包含 157/157 个最终产物，每角色有 JSON、SKEL、
atlas 和 PNG。原先的 14 角色精选集在 `MultiSpine\LO\Products\Curated14`。

多骨骼 BD 当前包含 17 个角色、36 个产物，共 3,805 根骨、3,348 个槽位、
3,360 个 mesh。34 个常规服装由 region 转成刚性节点 mesh；另有 2 个合并
示例，原有 273 个 mesh 保留，并补齐 30 个隐式 region。全量结构检查
`failures=0`，报告在 `MultiSpine\BD\Products\Current\manifest.json`。

静态立绘全量扫描 1150 个 `*.Lihui.prefab`：1148 个成功，2 个只有占位
Sprite GUID、没有实际美术。全量结构检查为 `failures=0`，产物包含 6,444
根骨和 2,068 个默认开启槽位。

所有正式示例目录均带 `*.config.json`。七个正式示例根当前共 1550 个资源目录，
配置检查结果为 `present=1550 missing=0 invalid=0`。可直接查看
[EXAMPLE_INDEX.md](D:\VB\Convert\Spine\EXAMPLE_INDEX.md)。

## 共用代码

```text
SingleSpine\Shared\Unity2Spine
SingleSpine\Shared\lo_uncen2Spine
```

`Unity2Spine` 是历史主转换库；`lo_uncen2Spine` 是自包含 GUI/CLI，并已在
`src\ext_lo`、`src\ext_bdone` 内部分开 Lo 与 BD 扩展。

## 旧路径兼容

旧路径兼容入口曾保留为 Junction。2026-11-05 清理后，工作根下散乱的旧入口
已移到 `D:\VB_ToDelete` 等待删除；正式源码与产物只保留在
`D:\VB\Convert\Spine`。仍使用历史默认路径的工具应通过环境变量覆盖。

```text
D:\VB\Unity2Spine
D:\VB\lo_uncen2Spine
```

`D:\VB\MutiBone` 旧入口也已移到 `D:\VB_ToDelete`。多骨骼源码位于
`MultiSpine\LO\MutiBone`。

## Unity 源工程

按本次要求，没有移动 Unity 源工程：

```text
D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old
D:\VB\Search\BdOne
```

移动前的目录清单在 `move_inventory_20261103.csv`。

## 迁移验证

- 单骨骼 Lo：157 个目录 / 157 个 SKEL；旧路径与新路径文件 SHA256 一致。
- 单骨骼 BD：17 个角色目录，34 个服装/产物目录。
- 多骨骼 Lo：157/157 个 `uAnim` 产物，manifest `missing=0`。
- 多骨骼精选集：14/14 结构验收通过。
- 多骨骼 BD：17 个角色 / 36 个产物，3,360 mesh，结构失败 0。
- 正式示例配置：400/400 存在且引用文件有效。
- `lo_uncen2Spine` 自检：0 个代码文件含硬编码绝对路径。
- `Unity2Spine`、`MutiBone`、`lo_uncen2Spine` 通过 Python 编译检查。
- 旧路径 Junction 清单：`junction_map_20261103.csv`。

整理时 Unity 编辑器未运行，MCP 当前实例数为 0，因此本轮没有依赖 Unity
Play 模式做额外采集；已有 Unity 真值和产物未移动损坏。

结构复验：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File D:\VB\Convert\Spine\validate_organization.ps1
```

当前结果：

```text
ORGANIZATION_OK single=157 skel=157 versions=13 BD=17/34 BDM=17/36 multi=157 curated=14 configs=400 junctions=26
```
