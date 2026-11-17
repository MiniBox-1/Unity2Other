# Unity2Live2D

日期：2026-11-06

本目录是「Unity 原生 Animator 动画 → Live2D（Cubism）模型 + 动作」的实现工程。
当前状态：

- 静态模型：`Products\2DModel_3P_Alexandra_N\`（14 部件 / 450 顶点 / 误差 6e-8）；
- **带骨骼链的版本**：`Products\2DModel_3P_Alexandra_N_rig\`（74 变形器 +
  74 参数，静止姿态误差 6e-7，参数驱动已验证）。
- **4 段动作已生成**：`motions\{Start,Tep_1,breast,lobby}.motion3.json`
  （37–63 条参数曲线），Cubism 原生框架可加载并播放；
- **全量批量已跑通**：157/157 个 uAnim 角色 → 158 个包全部通过校验
  （9,099 部件 / 16,251 参数 / 654 段动作 / 17.4 MB moc3），耗时 331 s；
- **P4 第一版已落地**：按动作真值逐顶点选骨 + 三角形分块，
  Alexandra 的误差从 668 px 降到 **51.8 px（-92%）**，Tiamat 从 29 → 1.3 px；
- **标准包收尾**：157 个 `cdi3.json`、SDK schema 校验（model3/motion3/cdi3）、
  分块版在 Cubism Native Framework 中实测加载并播放；
- **多纹理页已支持**：一个角色最多 12 张图集（平均 2.2 张），修复了此前
  「所有部件都贴第一张图」的严重 bug（Alice 曾显示成一张 Logo）；
- 环境限制：本机 Unity 是 2021.3 / 2022.3，而 SDK 5-r.5 要求 Unity 6 + URP，
  无法在本机做 Unity 导入实测（见 docs\04 E18）；
- 复现性已验证：同输入重建，moc3/motion3 的 SHA256 一致；
- 使用说明：[docs\06_使用说明.md](docs/06_使用说明.md)；
- **合成修复（2026-11-07）**：Sprite/静态部件改用世界变换、画布剔除远处碎片、
  多图集页支持；新增 Spine 参照渲染器与剪影 IoU 对比工具（docs\04 E21）。

## 结论先行

1. **Unity 侧的数据已经够用**：`D:\VB\Convert\Spine` 里已有成熟的
   prefab YAML 解析、Animator/AnimationClip 采样、骨骼树与加权网格重建、
   精灵轮廓、渲染顺序，以及 Unity 真值导出（逐帧骨骼 + 顶点）。这些可以直接
   作为 Live2D 转换器的输入层。
2. **Live2D 侧的瓶颈不在 SDK，而在 `.moc3`**：Cubism Core 只读不写，
   官方没有命令行编译器，本机也没装 Cubism Editor。要让转换器真正产出可被
   Cubism 运行时加载的模型，必须自己生成 moc3。
3. **moc3 从零生成已实测可行**：见 `docs\04_可行性验证记录.md`。
   用真实 `Live2DCubismCore.dll` 校验，一个从零拼出的 1 部件 / 1 ArtMesh /
   1 参数模型通过了 `csmHasMocConsistency`，能加载、能随参数形变。
4. **根本性偏差只有一个**：Live2D 没有逐顶点骨骼蒙皮。本工程的 Unity 角色
   多为「骨骼树 + 加权 SkinnedMeshRenderer」，需要靠 WarpDeformer 网格拟合，
   这是误差预算的主要来源。
5. **生成器已覆盖可用的全部结构**：`src\unity2live2d\moc3\builder.py` 支持
   Parts / ArtMesh / 参数 keyform 网格 / **RotationDeformer** / **WarpDeformer**
   / 层级 / 纹理 / 排序，`tests\test_moc3_builder.py` 七组用例全部通过真实
   `Live2DCubismCore` 校验（含 24 ArtMesh、3 参数 8 keyform 的压力用例）。
6. **已用 IDA 逆向 Core 5-r.5**（`docs\05`）：确认 moc 版本 1..6、v<=5 头部
   最小 0x840、SOT 在 +64、上下文在 +704、模型构建链
   `csmInitializeModelInPlace → sub_1800065F0 → sub_180004BD0/1800039C0`；
   并把 **101 段段表**（SOT 顺序 / 元素大小 / 数量）在 Koharu 与 Natori 上
   逐一核对通过，`reverse\section_table.py` 可随时复跑。

## 目录

```text
Unity2Live2D\
  README.md                         本文件
  docs\
    01_Unity动画项目解析.md          输入侧：D:\VB 下与 Unity 动画相关的项目
    02_Live2D资产与SDK解析.md        目标侧：SDK、格式、现有资产、能力边界
    03_Animator转Live2D方法设计.md   转换方法、数据映射、算法、分阶段计划
    04_可行性验证记录.md             已跑过的实验与可复现命令
    05_CubismCore逆向记录.md         IDA 逆向 Live2DCubismCore 5-r.5 的结论
  src\unity2live2d\moc3\
    builder.py                      moc3 生成器（Parts/ArtMesh/参数/Rot/Warp）
    validate.py                     Core 校验与读回（ctypes）
  tests\
    test_moc3_builder.py            生成器回归测试（真实 Core，7 组用例）
  tools\
    core_probe\                      moc3 探针/校验脚本（已实际跑通）
    vendor\py-moc3\                  第三方 moc3 二进制读写（MIT）
  reverse\                          IDA 数据库与查询脚本、反编译输出
```

## 已跑通的流水线

```powershell
# 1) 静态模型（14 部件 → moc3 + model3 + 贴图 + manifest）
python tools\build_alexandra.py

# 2) 骨骼链 + 参数（74 变形器 / 74 参数）
python tools\build_alexandra_rigged.py

# 3) 4 段 AnimationClip → motion3（顺带重建 moc3/model3）
python tools\build_motions.py

# 4) 校验与预览
python tools\check_motions.py Products\2DModel_3P_Alexandra_N_rig\2DModel_3P_Alexandra_N_rig.model3.json
python tools\render_motion_frames.py Products\2DModel_3P_Alexandra_N_rig\2DModel_3P_Alexandra_N_rig.model3.json lobby Products\2DModel_3P_Alexandra_N_rig\motion_lobby.png 4 700
python tools\preview_moc3.py Products\2DModel_3P_Alexandra_N_rig\2DModel_3P_Alexandra_N_rig.moc3 `
    Products\2DModel_3P_Alexandra_N_rig\textures\texture_00.png `
    Products\2DModel_3P_Alexandra_N_rig\preview.png 900
```

## 下一步（P2 收尾）

1. 骨骼树 → RotationDeformer 链：每个骨骼一个旋转变形器（`angle=-localEuler.z`、
   `origin=localPosition`），父链照抄 Transform 层级；
2. 每个 ArtMesh 按主导骨骼挂到对应变形器下（顶点换算到该变形器空间）；
3. 加权网格 → WarpDeformer 拟合（P4 的算法，先在单角色上试）。

## 相关工程

| 工程 | 作用 |
| --- | --- |
| `D:\VB\Convert\Spine` | Unity → Spine 的现有转换器与产物，本工程的算法与代码来源 |
| `D:\VB\Unity2Spine_ReverseEngineering_Full_20261106` | Unity 运行时语义的逆向证据与导出脚本 |
| `D:\VB\Convert\Live2d\Cubism` | Cubism SDK for Unity 5-r.5（Core/Framework/Rendering/Editor） |
| `D:\VB\Viewer\newViwer` | 自研查看器，带 `v3.pyd`（Cubism 原生框架绑定），可做离线渲染校验 |

## 合成正确性修复（2026-11-07，见 docs\04 E21–E27）

已修复（均经全量重建 + 校验）：

1. **Sprite / 静态部件丢失**：分块只处理蒙皮部件，Sprite 部件被整块丢弃；
   现在统一走世界变换并挂到最近的骨（部件数 22,776 → 26,119）。
2. **Unity 不绘制的「备用姿势」部件被收进来**：prefab 里 inactive GameObject /
   disabled renderer 的部件（Khan 有 22/67）现在按 YAML 过滤（→ 23,156 部件）。
3. **画布被远处碎片撑大**：改为「中位点 + MAD 半径」统计主体，Emily 类角色不再缩成小点。
4. **多图集页**：按部件分配纹理页（E19）。

工具：	ools\spine_preview.py（Spine 参照渲染，多图集页/权重与扁平网格/动画采样）、
	ools\compare_render.py（剪影 IoU + 完整性标注）、	ools\fragment_audit.py、
	ools\pose_state_probe.py、	ools\sprite_delta_probe.py。

已知限制：

- Spine 参照里 **Sprite 整体偏 +1 单位**、部分产物缺件、setup pose 有时被烘过，
  所以 IoU 只能做筛查，不能当验收判据；
- BR_Khan_N 这类「部件靠 Animator 摆位」的角色 **bind pose 本身就是散架**，
  目前仍未拼起来（t=0 采样、参照吸附两条路都试过，详见 E25–E27）；
- Unity 真值截图被「工程被运行中的编辑器占用」挡住，未能实施。

## 合成修复完成（2026-11-15，见 docs\04 E21–E33）

用 **MCP 驱动运行中的 Unity 出真值**（自然状态截图 + 逐部件真实蒙皮包围盒），
逐个角色校正后：

- 修掉 5 类问题：Sprite 部件丢失、备用姿势部件误入、画布裁切/撑大、
  **Sprite 与蒙皮网格 UV 的 V 方向混用**、多图集页；
- 157/157 构建成功，validate 160/160；
- 与 Unity 真值剪影 IoU：**中位数 0.964，≥0.9 有 132/157，≥0.5 有 153/157**；
- 残留 4 个角色 <0.5，均为特效/道具差异（不是角色错位）。

工具：unity_http_mcp.py（MCP 客户端）、unity_snap_*.cs（真值截图）、
unity_dump_many.cs（逐部件真值）、unity_iou_audit.py（剪影回归）、
part_visibility.py / uto_drop*.py（可见性分析，默认不启用）。

## 参考无关的最终结果（2026-11-15，见 docs\04 E38–E42）

转换只读 prefab + 资源（不读任何 Unity 真值；真值仅用于评估）：

- 特效件识别：prefab 材质 GUID → .mat 的 m_Shader → 内置 shader id 常量表 → 跳过粒子/叠加件；
- UV 约定：只有 **Sprite** 部件翻转 V（库里自建四边形是左上原点），Mesh/蒙皮保持 Unity 约定。

`	ext
157/157 ok；validate 161/161；20,504 部件
Unity 真值（测试集）剪影 IoU：中位数 0.976，>=0.9 150/157
WarWolf 0.976 / Scathy 0.976 / Eternity 0.993 / RheinRitter 0.917
`

## UI/控制圆环收尾（2026-11-16，见 docs\04 E43）

IK 可视化圆环（RoyalArsenal 的绿圆环、Banshee 的控制件）现在按 **prefab 层级 + 命名**
判定并剔除：祖先含 Global_CTRL/CTRL_IK/Controllers **且** 自身名匹配
IK_/_CTRL/_GRP/_POLE/GIZMO。全程只读 prefab，不依赖 Unity 真值。

`	ext
RoyalArsenal_NS1  0.484 -> 0.967
Banshee_NS1       0.757 -> 0.984
全量：中位数 0.976；>=0.9 153/157；>=0.8 156/157；>=0.7 157/157
`

## 参考图取景修复（2026-11-16，见 docs\04 E50）

快照脚本之前会把**编辑器当前场景**一起拍进参考图；现在实例化的角色放到 layer 31，
相机只拍该 layer。全量 157 张重拍后：

`	ext
min 0.877   median 0.977   >=0.9: 154/157   >=0.8: 157/157
Alice_DL_N 0.435->0.971   Emily_DL_N 0.631->0.987   Aeda 0.749->0.986
`

## 预览分辨率（2026-11-16，见 docs\04 E51）

自测用的 preview.png 统一按 **1024** 高渲染（	ools\render_previews.py 1024），
否则细长角色在 512 下边缘锯齿会把自测分压低 5~10 个点。

`	ext
median 0.986   min 0.949   >=0.9: 157/157
`

