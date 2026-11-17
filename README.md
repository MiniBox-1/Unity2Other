# work/unity-notes — Unity 运行时机制逆向笔记

从 Unity 2D 角色工程反推出来的一套「Unity 到底怎么画、怎么算」的结论集合，
可作为 Unity 2D / Spine / Live2D 转换的通用参考。

> **先读 [`docs/SCOPE.md`](docs/SCOPE.md)**：说明这些结论来自哪两个 Unity 工程
> （Unity 2021.3.45f2c1、Built-in 管线、Puppet2D + NGUI + 1150 张静态立绘）、
> 哪些是 Unity 通用机制可以直接搬、哪些是本工程约定必须重测、以及未覆盖的情形（URP/HDRP、UGUI、3D 等）。

## 目录

```text
docs/
├─ reverse/                    从原始逆向资料包整理
│   ├─ MONO_PLAYER_SOURCE.md   Mono 层源码线索
│   ├─ Docs/                   主文档集
│   │   ├─ 渲染顺序_反汇编研究.md      ★ 渲染排序的真实规则
│   │   ├─ 导出指南_Unity运行时数据.md  ★ 运行时数据怎么取
│   │   ├─ 历史问题与修复.md           ★ 长长的问题清单
│   │   ├─ 交接与核查.md
│   │   ├─ 现状与问题.md
│   │   ├─ BdOne_NGUI_转化.md
│   │   ├─ BdOne_交接与后续.md
│   │   └─ _archive_20260917/ . _archive_20260919/ . _archive_lo_uncen2Spine_20261013/
│   ├─ SpineReference/         Spine 骨架数据转换参考
│   └─ UnityEditorScripts/     运行期导出脚本说明
└─ unity-internals/
    ├─ 01_圆圈与骨骼标记.md  … 05_待你导出的参考帧.md   （质量专项结论）
    ├─ 多骨骼_真骨骼树.md
    ├─ 渲染顺序_反汇编研究.md
    ├─ 导出指南_Unity运行时数据.md
    ├─ 历史问题与修复.md
    ├─ 01~03/05 Live2D 侧的 Unity 解析（项目结构 / 资产 / Animator 方法 / Core 逆向）
    └─ REVERSE_ENGINEERING_INDEX.md   ★ 总索引
```

## 核心结论速查

| 主题 | 结论 |
| --- | --- |
| 可见性 | `m_IsActive` 与 `m_Enabled` 决定运行时是否绘制；prefab 里的静态值不等于最终状态（脚本/动画会改） |
| 包围盒 | `Renderer.bounds` 是**膨胀过的剔除盒**，真实范围要逐顶点 LBS 计算 |
| 排序 | `m_SortingOrder` 只是其中一维：renderQueue 分流、SortingGroup 做 tie-break、每帧可能重排 |
| 换图 | PPtr 换图是**阶跃**语义，不是渐变 |
| 曲线 | Hermite 插值，欧拉顺序 ZXY |
| BlendShape | 先形变、后蒙皮 |
| 蒙皮 | 最多 4 骨，与 Spine 3.8 加权顶点格式一一对应 |
| Sprite | alpha 为 Tight mesh，网格按不透明区域裁剪 |
| Animator | Additive 层需要参考姿态，四元数混合，短层循环；多轴加性旋转有限制 |

## 用法

这些是**结论型文档**，配合 `work/live2d` / `work/spine` 的代码一起看：

```bash
git checkout work/unity-notes    # 只读文档
git checkout work/spine          # 看结论怎么落到实现
```

## 说明

`docs/reverse/Docs/_archive_*` 是不同时间点的历史快照，内容有重复但保留了当时的
判断过程（包括走过的弯路），对复现问题有用。
