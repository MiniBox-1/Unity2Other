# 路径映射

## 正式物理位置

| 内容 | 路径 |
| --- | --- |
| 单骨骼共用代码 | `SingleSpine\Shared\Unity2Spine` |
| 单骨骼自包含 GUI/CLI | `SingleSpine\Shared\lo_uncen2Spine` |
| 单骨骼 Lo 当前产物 | `SingleSpine\LO\Products\Current` |
| 单骨骼 Lo 历史版本 | `SingleSpine\LO\Versions` |
| 单骨骼 Lo 真值 | `SingleSpine\LO\Truth\UnityRuntime` |
| 单骨骼 BD 产物 | `SingleSpine\BD\Products\_bdone_spine` |
| 单骨骼 BD 真值 | `SingleSpine\BD\Truth\_bdone_truth` |
| 多骨骼 Lo 工程/工具 | `MultiSpine\LO\MutiBone` |
| 多骨骼 Lo 157 角色 | `MultiSpine\LO\Products\Current` |
| 多骨骼 Lo 14 精选集 | `MultiSpine\LO\Products\Curated14` |
| 多骨骼验收证据 | `MultiSpine\LO\Evidence` |
| 多骨骼 BD 17 角色/36 产物 | `MultiSpine\BD\Products\Current` |
| 多骨骼 BD 工具 | `MultiSpine\BD\Tools` |
| 多骨骼 BD `manifest.json` | `MultiSpine\BD\Products\Current\manifest.json` |
| 静态立绘全量 1148 | `StaticSpine\LO\Products\Current` |
| 静态立绘回归原型 | `StaticSpine\LO\Products\Prototype` |
| 静态立绘转换工具 | `StaticSpine\LO\Tools\convert_lihui_static.py` |
| 静态立绘验证工具 | `StaticSpine\LO\Tools\validate_lihui_static.py` |
| 示例配置补建/检查 | `MultiSpine\Tools\ensure_example_configs.py` |
| 示例索引 | `EXAMPLE_INDEX.md` |

## 兼容入口（已归档）

| 旧路径 | 新目标 |
| --- | --- |
| `D:\VB\Unity2Spine` | `SingleSpine\Shared\Unity2Spine` |
| `D:\VB\lo_uncen2Spine` | `SingleSpine\Shared\lo_uncen2Spine` |
| `D:\VB\MutiBone\src` | `MultiSpine\LO\MutiBone\src` |
| `D:\VB\MutiBone\tools` | `MultiSpine\LO\MutiBone\tools` |
| `D:\VB\MutiBone\docs` | `MultiSpine\LO\MutiBone\docs` |
| `D:\VB\MutiBone\refs` | `MultiSpine\LO\MutiBone\refs` |
| `D:\VB\MutiBone\out` | 保留目录壳，内部结果通过 Junction/HardLink 对应新位置 |
| `D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv_cs_port_新仓_20261014` | `SingleSpine\LO\Products\Current` |
| 其它 `_spine_conv*` 旧路径 | 对应 `SingleSpine\LO\Versions\<原名>` |

2026-11-05 清理后，以上散乱旧入口已统一移到：

```text
D:\VB_ToDelete
```

正式仓库不再依赖这些 Junction 或旧目录壳。

## 未移动

Unity 源工程按用户要求保留原位：

- `D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old`
- `D:\VB\Search\BdOne`
