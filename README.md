# work/live2d — Unity Animator → Live2D Cubism 转换器

把 Unity 2D 角色（Puppet2D 骨骼 + Sprite/Mesh 部件 + `.uAnim.prefab`）转成
Live2D Cubism 可用的 `.moc3` 模型包。

## 目录

```text
live2d/
├─ src/unity2live2d/
│   ├─ convert/        prefab 解析、分块、UV、motion、图片合成
│   ├─ moc3/           moc3 v1 生成器 + Cubism Core 校验（ctypes）
│   └─ …               画布、参数、deformer 等
├─ tools/              批量转换 / 审计 / 对比脚本（含 Unity 侧 dump 用的 .cs）
└─ tests/              单元测试（pytest）
docs/                  设计、资产解析、逆向记录、可行性验证（E1–E51）、使用说明
```

## 快速上手

```bash
pip install -r requirements.txt      # 见 docs/06_使用说明.md
python -m pytest tests -q            # 7 个测试
python tools/convert_batch.py --names <角色名> --out Products
```

moc3 校验需要 Cubism Core 原生库（`Live2DCubismCore.dll`），
路径在 `src/unity2live2d/moc3/validate.py` 里可改。

## 文档

| 文件 | 内容 |
| --- | --- |
| `docs/01_Unity动画项目解析.md` | 目标工程结构、prefab 组成 |
| `docs/02_Live2D资产与SDK解析.md` | moc3/model3 格式、SDK 校验方式 |
| `docs/03_Animator转Live2D方法设计.md` | 转换总体设计 |
| `docs/04_可行性验证记录.md` | **E1–E51** 全部踩坑、根因、验证数据 |
| `docs/05_CubismCore逆向记录.md` | Core 的调用与坑 |
| `docs/06_使用说明.md` | 实际操作步骤 |

## 实现要点（踩坑总结）

- **LBS 与 Unity 一致**：`Σ w_i (bone.localToWorldMatrix * bindposes[i]) * v`，与 Unity 逐顶点结果相同；
- **UV 只翻 Sprite**：库里自建四边形是左上原点，Mesh/蒙皮部件保持 Unity 左下原点；
- **moc3 v1 无混合模式**：粒子/叠加/正片叠底部件按材质 shader 识别后跳过（内置 shader id 常量表）；
- **控制件剔除**：`Global_CTRL` 下的 IK 圆环等按「控制组 + 命名」剔除；
- **分块**：多帧动作真值聚类，部件跨帧联动则合并为同一段。
