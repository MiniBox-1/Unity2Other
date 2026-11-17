# work/spine — Unity / BdOne → Spine 3.8 转换器

三条并行的转换路线，共用一个 Unity 资源解析库。

| 路线 | 输入 | 输出策略 |
| --- | --- | --- |
| SingleSpine Lo | `*.uAnim.prefab` | 单根骨 + 逐帧顶点形变 |
| SingleSpine BD | BdOne NGUI 层级 | 保留节点层级 + 区域附件 |
| MultiSpine Lo | `*.uAnim.prefab` | 真实骨骼树 + 加权网格 |
| MultiSpine BD | BdOne NGUI 层级 | 逐节点刚性加权网格 |
| StaticSpine Lo | `*.Lihui.prefab` | 骨骼树 + 默认可见部件槽位 |

## 目录

```text
spine/
├─ SingleSpine/
│   ├─ Shared/Unity2Spine/      共享解析库（prefab/动画/网格/图集 → Spine 写出）
│   ├─ Shared/lo_uncen2Spine/   GUI/CLI 与 Lo·BdOne 扩展
│   ├─ LO/Docs/                 Lo 路线交接与算法文档
│   └─ BD/Docs/                 BdOne 路线交接文档
├─ MultiSpine/
│   ├─ LO/MutiBone/             真骨骼树转换器 + 验证工具
│   └─ BD/Tools/                BdOne 区域→网格转换
├─ StaticSpine/LO/Tools/        静态 `.Lihui` 转换与校验
├─ packaging/github/            发布模板与说明
docs/                           示例索引、路径对照、打包报告、逆向索引
```

## 快速上手

```bash
# 单骨骼 Lo
python spine/SingleSpine/Shared/Unity2Spine/convert_2dmodel.py <prefab> <out>
# 多骨骼 Lo
python spine/MultiSpine/LO/MutiBone/src/convert_bones.py …
# 静态立绘
python spine/StaticSpine/LO/Tools/convert_lihui.py …
```

具体命令与参数见各子目录 README 与 `docs/`。

## 文档

| 文件 | 内容 |
| --- | --- |
| `docs/EXAMPLE_INDEX.md` | 示例产物索引（各路线数量与推荐样例） |
| `docs/PATH_MAP.md` | 目录约定与历史搬迁对照 |
| `docs/PACKAGING_REPORT_20261105.md` | GitHub 打包完整性报告 |
| `docs/REVERSE_ENGINEERING_INDEX.md` | 逆向结论索引（Unity 机制） |
| `docs/REVERSE_PACKAGING_REPORT_20261106.md` | 逆向资料打包报告 |
| `spine/SingleSpine/Shared/Unity2Spine/docs/` | 解析库细节、坐标系、渲染顺序 |
| `spine/SingleSpine/Shared/Unity2Spine/tq_report/` | 质量专项：圆圈、运动错位、图片错位… |

## 实现要点

- Unity 的 `m_IsActive`/`m_Enabled` 只决定**运行时**可见性，`Renderer.bounds` 是膨胀过的剔除盒，
  真实包围盒要用逐顶点 LBS 计算；
- 排序不是单一 `sortingOrder`，而是 renderQueue 分流 + SortingGroup tie-break；
- 曲线是 Hermite + ZXY 欧拉；BlendShape 是「先形变、后蒙皮」；
- 蒙皮最多 4 骨，与 Spine 3.8 加权顶点格式一致。
