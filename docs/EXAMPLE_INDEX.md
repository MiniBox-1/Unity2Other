# 示例产物索引

整理日期：2026-11-03

## 直接查看

| 路线 | 示例位置 | 数量 |
| --- | --- | --- |
| 单骨骼 Lo | `D:\VB\Convert\Spine\SingleSpine\LO\Products\Current` | 157 角色 |
| 单骨骼 BD | `D:\VB\Convert\Spine\SingleSpine\BD\Products\_bdone_spine` | 17 角色 / 34 常规服装，另有 2 个合并示例 |
| 多骨骼 Lo 全量 | `D:\VB\Convert\Spine\MultiSpine\LO\Products\Current` | 157 角色 |
| 多骨骼 Lo 精选 | `D:\VB\Convert\Spine\MultiSpine\LO\Products\Curated14` | 14 角色 |
| 多骨骼 BD | `D:\VB\Convert\Spine\MultiSpine\BD\Products\Current` | 17 角色 / 36 产物 |
| 静态立绘全量 | `D:\VB\Convert\Spine\StaticSpine\LO\Products\Current` | 1148 成功 / 2 无美术 |
| 静态立绘原型 | `D:\VB\Convert\Spine\StaticSpine\LO\Products\Prototype` | 2 回归示例 |
| Lo 历史版本 | `D:\VB\Convert\Spine\SingleSpine\LO\Versions` | 13 个版本目录 |
| 多骨骼验证图 | `D:\VB\Convert\Spine\MultiSpine\LO\Evidence` | 角色/批次证据 |
| BD 本轮对账图 | `D:\VB\Convert\Spine\MultiSpine\BD\Products\_mesh_check` | 安洁利卡、阿波罗、温蒂、伊斯丽洛克 |

每个正式示例目录都应有与 skeleton 对应的 `*.config.json`。当前七个正式示例根
共 1550 个资源目录，检查结果：

```text
EXAMPLE_CONFIG total=1550 present=1550 created=0 missing=0 invalid=0
```

## 推荐先看的例子

```text
SingleSpine\LO\Products\Current\2DModel_3P_Alexandra_NS1
SingleSpine\BD\Products\_bdone_spine\安洁利卡\安洁利卡_01_原皮
MultiSpine\LO\Products\Curated14\alice
MultiSpine\BD\Products\Current\安洁利卡\安洁利卡_01_原皮
MultiSpine\BD\Products\Current\伊斯丽洛克\伊斯丽洛克_合并
StaticSpine\LO\Products\Prototype\2DModel_3P_Ajax_N.Lihui
StaticSpine\LO\Products\Current\2DModel_3P_Ajax_N.Lihui
```

BD 多骨骼的 `manifest.json`：

```text
D:\VB\Convert\Spine\MultiSpine\BD\Products\Current\manifest.json
```

## 配置检查与补建

只检查，不写文件：

```powershell
D:\Anconda\python.exe `
  D:\VB\Convert\Spine\MultiSpine\Tools\ensure_example_configs.py --check
```

给缺失配置的示例生成 `<skeleton名>.config.json`：

```powershell
D:\Anconda\python.exe `
  D:\VB\Convert\Spine\MultiSpine\Tools\ensure_example_configs.py
```

脚本不会覆盖已有配置，并会检查配置引用的 skeleton、atlas 和所有贴图是否真实存在。

## BD 多骨骼对账

单帧离线渲染示例：

```powershell
& 'D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe' `
  'D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\tools\rt_frames.py' `
  'D:\VB\Convert\Spine\MultiSpine\BD\Products\Current\安洁利卡\安洁利卡_01_原皮' `
  'Npc30_1' `
  --out 'D:\VB\Convert\Spine\MultiSpine\BD\Products\_mesh_check\view' `
  --times 0 --size 720
```

渲染前先确认可用内存大于 3 GB，并且只运行一个 GL 渲染进程。
