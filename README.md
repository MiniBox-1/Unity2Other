# Unity2Other

Unity 2D 角色工程的**逆向解析 + 转换工具**集合，包含两条互相独立但共享逆向结论的路线：

| 路线 | 输入 | 输出 | 分支 |
| --- | --- | --- | --- |
| Unity → Live2D | `*.uAnim.prefab`（Puppet2D 骨骼 + Sprite/Mesh 部件） | Live2D Cubism `.moc3` + `.model3.json` + motion3 | `work/live2d` |
| Unity → Spine | `*.uAnim.prefab` / BdOne NGUI / 静态 `.Lihui.prefab` | Spine 3.8 JSON + atlas + skel | `work/spine` |
| Unity 机制研究 | — | 逆向笔记（渲染顺序、PPtr、曲线、蒙皮…） | `work/unity-notes` |

## 分支说明

> 约定：**一个工作一个分支**，互不干扰；`main` 只放总览。

| 分支 | 内容 |
| --- | --- |
| `main` | 本说明 + 忽略规则 |
| `work/live2d` | Live2D 转换器源码、工具脚本、测试、文档 |
| `work/spine` | Spine 转换器（单骨骼/多骨骼/静态立绘，Lo 与 BdOne 两条实现）+ 文档 |
| `work/unity-notes` | Unity 运行时机制逆向笔记（最全的一份） |

```bash
git clone https://github.com/MiniBox-1/Unity2Other.git
cd Unity2Other
git checkout work/live2d     # 或 work/spine / work/unity-notes
```

## 仓库边界（刻意不收录）

- Unity 工程本体、查看器、批处理缓存；
- 转换产物（`.moc3`/贴图/atlas/skel/Products）；
- 真值截图、逐帧导出、证据图；
- 第三方 SDK 与虚拟环境（Cubism SDK、Spine runtime、`.venv`）。

需要完整产物时按各分支文档里的命令，用本地 Unity 工程重新生成。

## 快速入口

- Live2D：`docs/06_使用说明.md`、`docs/04_可行性验证记录.md`（E1–E51 的踩坑与验证）
- Spine：`docs/EXAMPLE_INDEX.md`（示例索引）、`docs/PATH_MAP.md`（目录约定）
- Unity 机制：`docs/reverse/Unity运行时逆向报告.md`、`docs/unity-internals/渲染顺序_反汇编研究.md`

## 环境

- Python 3.10+
- Live2D 路线需 Cubism Core 原生库（`Live2DCubismCore.dll`）做 moc3 校验
- Spine 路线依赖 Spine 3.8 Python runtime（见 `work/spine` 内说明）
