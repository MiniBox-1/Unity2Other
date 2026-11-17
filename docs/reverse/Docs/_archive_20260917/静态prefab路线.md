# 静态 prefab 路线（当前路线，唯一必读）

更新：2026-09-12

本文合并了原 `10_静态prefab路线与动态校准` / `11_交接文档_静态prefab路线` /
`12_静态路线根因修复与校准方法`，是当前转换路线的完整说明：

- **第 2 节 = 整体技术路线**（数据流 / 五个阶段 / 模块地图 / 输入输出契约 / 校验闭环）
- 第 3 节 = 根因清单（面罩朝向、光晕、部件分离等，每条都有现象→根因→修法）
- 第 4~9 节 = 光晕与颜色、图集页数、Alpha 与 Shader 依赖、静态检查器、校准工具、产物与单位（**9.3 = 二进制 `.skel` 导出**）
- 第 10~12 节 = 遗留事项 / 常用命令 / 相关文件

docs 目录索引见 `README.md`；验证报告与角色记录见 `报告与校验.md`；
NGUI / 多 Spine 合并等其它路线见 `其他路线与历史.md`。

## 0. 状态

交接时列出的三大问题（面罩朝向/镜像、光晕与颜色、运动中部件分离）已定位为
解析/数学 bug 并修复，全部有量化校准数据：

| 指标 | 结果 |
| --- | --- |
| 三个主力角色 部件顶点 vs Unity 帧真值 | aeda **0.00001** / blacklilith **0.00000** / audrey 0.00122（= 关键帧裁剪阈值级） |
| 单脸 vs Unity 单脸参考帧（aeda） | IoU **0.973~0.982**（镜像变体仅 0.68~0.75） |
| 整角色 vs Unity 整图参考（2026-09-13 重导后） | aeda **0.9988** / blacklilith **0.9927** / audrey **0.9974** |
| 光晕层 vs Unity 精灵参考帧（aeda） | IoU **0.856(t=0) / 0.816(t=1.5)**；关掉加色只有 0.34 |
| 面罩/光点 323 帧绕向（aeda） | Unity 真值 0 次翻转，导出同样 0 次 |
| 50 角色泛用性批量 | 静态检查全 0；逐顶点 **48/50 通过**（2 个因“我们与 Unity 选的主 clip 不同”跳过），平均 **0.0416** / 最大 0.321 |
| 二进制导出（`--skel`，9.3） | 与 `SpineSkeletonDataConverter.exe` 输出**逐字节一致**（三主力 + 安洁利卡 + 合并样本 + atalanta）；读回差异 0；与 `.json` 渲染逐像素一致 |

泛用性抽样的范围、50 个样本名单、图像级复核见 `报告与校验.md`。

## 1. 目标与硬性规则

- 导出只允许使用磁盘静态资源（prefab / Mesh / Material / Sprite / .anim /
  AnimatorController；必要时可用磁盘 `save.unity` 的实例姿态）；
- Unity 编辑器/运行时导出的 PoseFrames / SceneT0 / StaticMeta 等一律
  **只用于校准**，不参与成品导出；
- 每次输出图片前必须先用 `D:\VB\vision.js` 校验一致性；
- 每次转换后自动截取"单脸"并交给 vision 校验（`tools/face_check.py`）；
- **重活不许并行跑**（2026-09-17 起）：每件重活先用 `tools/mem_probe.ps1` 量
  进程树峰值，**同时跑的峰值之和 ≤ 10 GB**（本机物理内存 15.8 GB）；
  大产物必须先 `python tools\write_all_skel.py <产物根>`，否则查看器会去读
  大 JSON（实测单帧 >11 GB，见 `工具链与命令.md` 0.5）；
- 每次转换自动跑**静态检查**（`tools/static_check.py`），查"动画/场景引用
  但导出里没有"的资源；
- 强烈建议带 `--calib` 做几何自检（对比 Unity 帧真值）；
- 渲染尺寸尽量按参考原图尺寸；部件保持原始比例，不额外缩放；
- 询问用户前先读取 `D:\VB\询问前规则.md`。

路线原则：setup 姿态不采用 prefab 纯 rest（部分角色 rest 畸形，如 audrey
多臂），而采用所选 clip 的 t=0 采样；动画 = 同一 clip 逐帧采样骨骼局部
T/R/S → 世界矩阵 → 蒙皮 → Spine mesh deform。

## 2. 整体技术路线

一句话：**把 Unity 磁盘上的 2DModel prefab 离线解析成 Spine 3.8 的
JSON/atlas/png——骨架只有一个 `Root`，每个部件是一个 mesh attachment，
动画是逐帧采样 Unity 蒙皮结果写进 mesh 的 `deform` 时间线**。
Unity 编辑器/运行态导出的帧数据只用于校准，不参与成品。

### 2.1 数据流

```text
   磁盘（只读）                             ① 解析        内存模型 / 产物
──────────────────────────────────────────────────────────────────────────
prefab（或 --scene 指定 save.unity 实例）
  GameObject / Transform（层级 + m_Children 顺序）       TwoDModel
  Animator + AnimatorController 引用                      ├ transforms  层级/父子/顺序
  SkinnedMeshRenderer / SpriteRenderer / 材质引用         ├ gameobjects 名字 + m_IsActive
Mesh .asset（positions/uvs/三角/bindposes/权重）          ├ renderers   部件（蒙皮/sprite）
Sprite .asset（rect/pivot/ppu/贴图）                      └ animators   控制器 + 所在物体
Material .asset（_Color / _TintColor / shader）
AnimationClip .anim（path + 关键帧曲线）
        │
        │ ② 角色对齐：按 prefab 名筛子树 → 选主 Animator → 重算 anim_path
        ▼
   rest 表 + clip 曲线
        │
        │ ③ 姿态与蒙皮：局部 T/R/S（列缩放 TRS）→ 累乘世界矩阵
        ▼
   骨骼世界矩阵
        │
        │    bindposes + boneWeights + bone 矩阵 → 顶点世界坐标
        ▼
   每部件每帧的顶点世界坐标
        │
        │ ④ 写 Spine：每部件一个 slot/attachment；顶点 = deform 时间线；
        │           材质颜色/混合 = slot 颜色 + blend；SetActive = attachment 切换
        ▼
   <角色>_static.json / .atlas / _0.png / .config.json / _static_info.json / README.md
   （加 --skel 时再出一份同数据的 <角色>_static.skel，见 9.3）

真值（只读、只用于校准）：Unity Editor 导出 info/Data/{PoseFrames,Frames,SceneT0}
        │
        ▼  ⑤ 校验闭环：static_check → calib_geo → 图像 IoU → face_check(vision)
```

### 2.2 五个阶段

| 阶段 | 输入 | 输出 | 实现 | 关键点 |
| --- | --- | --- | --- | --- |
| ① 解析磁盘资源 | prefab / .unity / .asset / .anim | `TwoDModel` + Mesh/Sprite/Clip 对象 | `unity_parse` `unity_2dmodel` `unity_mesh` `unity_anim2d` | Unity YAML 折行、顶点流 16 字节对齐、blend 索引两种存放方式、曲线 path 换行续写 |
| ② 角色对齐 | `TwoDModel` | 本角色子树 + 主 Animator + `anim_path` | `static_prefab_spine.load_character` `unity_2dmodel.pick_main_animator` `rel_path_in` | 多角色共用场景；主 Animator 必须对齐 Unity 的 `GetComponentInChildren<Animator>(true)`；相对路径按宿主**全路径**截断 |
| ③ 姿态与蒙皮 | rest 表 + clip | 每帧顶点世界坐标 | `unity_anim2d.AnimSampler/trs_mat` `convert_2dmodel._world_matrices/_skin_mesh` | TRS 必须按列缩放（`T·R·S`）；null 骨骼占位保留；缩放/镜像完全由矩阵决定 |
| ④ 写 Spine 产物 | 部件 + 每帧顶点 | json / atlas / png / 配置（可选 `.skel`） | `static_prefab_spine.convert_static` `spine_out` `spine38_binary_writer` | 一次导出所有 Animator 的所有 clip；颜色/混合按 Unity 材质；排序按 sortingOrder；图集按需预乘；`--skel` 时同一份数据再写二进制骨架 |
| ⑤ 校验闭环 | 产物 + Unity 真值 | 报告 / IoU / 截图 | `tools/static_check.py` `calib_geo(_batch)` `calib_full/calib_sprites/compare_frames` `face_check` | 先“有没有漏件”，再“像不像”，最后“人眼/vision 复核” |

### 2.3 落地步骤（六步）

转换入口：`ngui2spine/static_prefab_spine.py`（GUI 里是 A 面板）

1. 解析磁盘 prefab（或 `--scene` 指定磁盘场景实例，用于补齐 prefab 缺失的
   覆盖姿态 / sprite 引用）；多角色共用一个场景时，会**按本角色子树重新
   挑选 Animator**并按它重算动画曲线路径；
   **默认只保留 Animator 子树下的部件**（`--animated-only`，audrey 这类
   "静态立绘 + 动态立绘"双根角色会排除静态立绘整图；`--no-animated-only`
   可导出全部）；
2. **一次导出该角色所有 Animator 的所有 clip**：setup 取主控制器 lobby 一类
   clip 的 t=0；每条 clip 生成一条同名 Spine 动画，其它 Animator 在同一时间轴
   上循环播放（见 3.7）；后续帧逐帧采样骨骼局部 T/R/S；
   *个别部件在 setup 那帧尺寸为 0 时，参考帧自动挪到它最大的那一帧*；
3. 蒙皮：离线解析 mesh（positions/uvs/triangles/bindposes/boneWeights）后按
   Unity 蒙皮公式求世界坐标；
4. 输出 Spine 3.8 JSON/atlas：Root + unweighted mesh + deform 时间线；
   颜色/混合按 Unity 材质；部件朝向完全由世界矩阵决定，**没有任何按名字的
   翻转**；
5. 排序：按 prefab sortingOrder 升序（= Unity 绘制顺序），同值保持稳定序；
6. 自动跑静态检查 → 几何自检（`--calib`）→ 单脸/整体渲染比对。

### 2.4 模块地图

| 模块 | 职责 | 关键函数 |
| --- | --- | --- |
| `unity_parse.py` | Unity 文本 YAML（`!u!` 文档）专用解析 | `load_unity_docs` |
| `unity_2dmodel.py` | prefab/场景 → `TwoDModel`（层级/激活态/部件/Animator） | `TwoDModel.build`、`pick_main_animator`、`rel_path_in` |
| `unity_mesh.py` | Mesh / Sprite / 顶点流解析、蒙皮 | `parse_mesh`、`_pick_bone_indices`、`mat4_vec` |
| `unity_anim2d.py` | `.anim` 曲线解析与采样 | `parse_clip`、`AnimSampler`、`trs_mat`、`euler_to_quat` |
| `convert_2dmodel.py` | 部件构建、世界矩阵、蒙皮公式 | `build_character_model`、`_world_matrices`、`_skin_mesh`、`_asset_path` |
| `static_prefab_spine.py` | **A 路线入口**：角色对齐 → 分配 → 输出 → 自检 | `load_character`、`enumerate_clips`、`assignments_for_entry`、`convert_static` |
| `spine_out.py` | Spine 3.8 JSON / atlas / 查看器配置 | `atlas_text`、`fnum`、`write_viewer_config` |
| `spine38_binary.py` / `spine38_binary_writer.py` | Spine 3.8 `.skel` 二进制读 / 写（见 9.3） | `read_skeleton_json`、`write_skeleton_binary`、`compare_models` |
| `tools/static_check.py` | 静态检查器（漏件 / 曲线 path / 可见性冲突） | `build_report`、`print_report` |
| `tools/check_skel.py` | `.skel` 产物校验（与 .json 互校 / 与转换器逐字节比对） | — |
| `tools/calib_geo.py` | 逐顶点几何校准（可直接校验产物文件） | `compare_spine_dir`、`compare_parts` |
| `tools/spine_raster.py` | 最小 Spine 光栅器（deform/颜色/加色/PMA），供 IoU 比对 | — |
| `frame_baked.py` `single_frame_spine.py` `merge_*` | 历史路线（帧烘焙 / 单帧 / 多装配合并） | 见 `其他路线与历史.md` |

### 2.5 输入输出契约

| 路径 | 角色 | 谁用 |
| --- | --- | --- |
| `Assets/prefabs/lo/<角色>/<角色>.prefab` | 主角：结构 / 材质 / 引用 | 导出 |
| `Assets/Scenes/save.unity`（`--scene`） | 多角色实例摆放、prefab 缺失的覆盖姿态 | 导出（可选） |
| `info/Data/PoseFrames/<角色>.json` | 每帧 Transform + BakeMesh 真值 | 校准（**不**参与导出） |
| `info/Data/{Frames,SceneT0,SelectedInfo}/` | 参考图 / 场景 t0 几何 / 部件信息 | 校准 |
| `info/Data/export_config.json` | Unity 侧批量导出配置（names / parts / autoDiscover） | Unity 菜单 |
| `<out>/<角色>_static.json` | Spine 3.8 骨架 + 动画 | 运行时 |
| `<out>/<角色>_static[_pma].skel` | 同一份数据的 Spine 3.8 二进制骨架（`--skel`，见 9.3） | 运行时 |
| `<out>/<角色>_static.atlas` + `_N.png` | 图集 | 运行时 |
| `<out>/.config.json` | 查看器配置（重导时保留用户改过的参数） | Viewer / 编辑器 |
| `<out>/_static_info.json` | 原点 / 单位 / 部件元数据（校准和自检都读它） | 工具 |
| `<out>/_calib/static_check.json` | 本次导出的静态检查报告 | 自查 |

### 2.6 校验闭环（四层）

| 层 | 回答什么问题 | 工具 | 合格判据 |
| --- | --- | --- | --- |
| 1 结构 | 动画/场景引用到的资源导出里有没有？曲线 path 对不对得上节点？ | `tools/static_check.py` | 四项计数全 0 |
| 2 几何 | 每个部件每个时刻的顶点，和 Unity 真值差多少？ | `tools/calib_geo.py`（批量 `tools/calib_geo_batch.py`） | 世界单位误差（50 角色平均 **0.0252**，最大 0.281） |
| 3 图像 | 轮廓 / 光晕层像不像？ | `tools/calib_full.py`、`tools/calib_sprites.py`、`tools/compare_frames.py` | IoU ≥ 0.97 |
| 4 视觉 | 脸和朝向对不对？ | `tools/face_check.py` + `D:\VB\vision.js` | 人工 / vision 复核 |

第 1 层完全离线，随时可跑；第 2~4 层要 Unity 侧先导出真值
（`info\Data\PoseFrames|Frames|SceneT0`，菜单 `Tools/2DModel/校准数据/...`）。
**真值只用于第 2~4 层，永远不写进产物。**

### 2.7 关键设计决策（为什么这么做）

| 决策 | 本路线的选择 | 备选方案的代价 |
| --- | --- | --- |
| 骨骼表示 | **顶点烘焙**：骨架只有 `Root`，每个部件一个 mesh attachment，顶点逐帧写进 `deform` 时间线 | 还原 Spine 骨骼 + weights：Spine 每顶点权重上限 4 根骨、对非均匀/负缩放支持有限，还要过一遍 bindpose 换算，必然引入误差。顶点烘焙 = 与 Unity 逐帧结果**逐点相同**；代价是文件大（最重的 draculina 单个 JSON 600MB+）、在 Spine 编辑器里不能直接拖骨骼 |
| setup 姿态 | 取主 clip 的 **t=0** 采样 | 直接用 prefab rest：部分角色 rest 畸形（如 audrey 多臂），第一帧就错 |
| 部件朝向 | 完全由**世界矩阵**决定，没有任何按名字的翻转 | 按名字硬编码镜像：换个角色/换个缩放就失效（3.1 里是两个错误互相抵消） |
| 主 Animator | Unity 的 `GetComponentInChildren<Animator>(true)`：层级 DFS 第一个，没挂 Controller 的跳过 | 取 YAML 文档顺序：prefab 与 scene 顺序不同，会选到辅助 Animator（3.12） |
| 多 Animator | 全部导出；非当前动画的 Animator 在同一时间轴上循环播自己的默认 clip | 只导主控制器：球体光效 / 备用部件不会动（3.7、3.8） |
| 颜色与混合 | 直接读材质（`_Color`、`_TintColor`、shader 判断加色） | 手挑光晕部件：颜色、强度、混合全凭猜 |
| 图集预乘 | 加色区**就地预乘**；只有与普通混合共用像素时才另开一页并裁剪到实际区域 | 一律整页复制预乘：白多一张 2048²（第 5 节） |
| 坐标单位 | 默认**源图像素**（1 单位 = 1 像素） | Unity 世界单位：还要乘 px/unit，和多数组件坐标对不上 |
| 静态立绘 | 默认排除（`--animated-only`），只留 Animator 子树 | 全导：audrey 那种双根角色会把整张立绘当部件导出去 |

### 2.8 开关速查

| 开关 | 作用 |
| --- | --- |
| `--scene <save.unity>` | 用磁盘场景实例补 prefab 缺失的覆盖姿态；多角色时按角色子树重挑 Animator |
| `--dt <秒>` | 采样步长（默认 0.05；曲线的关键帧时刻会自动补采，见 3.11） |
| `--clip <名>` | 指定 setup 用的 clip（默认自动选 lobby 一类） |
| `--units px\|world` | 坐标单位，默认 px（源图像素） |
| `--pma` | 全局预乘 alpha 图集（配 spine-unity 默认材质；见第 6 节） |
| `--animated-only` / `--no-animated-only` | 只导 Animator 子树下的部件（默认开） |
| `--secondary-anim` / `--no-secondary-anim` | 是否同时采样角色内其它 Animator（默认开） |
| `--flip-x` | 左右翻转（一般不用，朝向由矩阵决定） |
| `--skip-texture NAME` / `--skip-texture-file TXT` | 屏蔽用某张贴图的部件（默认已屏蔽 Unity 编辑器助手贴图，见 3.15） |
| `--place X,Y` | 把整棵角色子树平移 X,Y 世界单位。**角色不在场景里时用它对齐参考帧**：aeda `--place=-20,0`、blacklilith `--place=5,0`（负值要写成 `--place=-20,0`） |
| `--skel` | 除 `.json` 外再输出同数据的 Spine 3.8 二进制骨架 `<角色>_static[_pma].skel`（见 9.3） |
| `--calib` | 导出后用 PoseFrames 真值做几何自检 |
| `--active-step` | **显隐退回老口径**（一律阶跃 + `v>=0.5`）。默认按 Unity 运行时语义（按关键帧切线插值 + `|v|>1e-3`，见 3.22）；只在旧产物对拍时用 |
| `--no-static-check` | 跳过导出后的静态检查 |
| `--no-face-check` | 跳过单脸 vision 校验 |

## 3. 关键修复（根因清单）

### 3.1 TRS 缩放顺序（面罩朝向/镜像的直接原因）

`unity_anim2d.trs_mat` 旧实现按**行**缩放（等价 `M = T·S·R`），Unity 的
`Matrix4x4.TRS` 按**列**缩放（`M = T·R·S`）。两者只在"非均匀或带负号缩放
**且**该节点自身有旋转"时结果不同——正好命中：

| 节点 | 局部缩放 | 局部旋转 | 后果 |
| --- | --- | --- | --- |
| `ch_root` | `[-1, 1, 0.1508]` | ≈0 | 整棵树镜像基准 |
| `parts_head`（面罩） | `[-1, 1, 1]` | Z 轴 89.6° | 顶点顺序被转 180°，朝向/镜像反复出错 |
| `bone_leg_l_up` 等腿骨 | `[-0.9, 0.9, 0.14]` | 有 | 腿部世界矩阵错 → 运动中"分离" |

修法：按列缩放（`m[r*4+c] *= scale[c]`）。

> 旧实现"有时看起来是对的"：面罩用了按名字硬编码的 u 镜像
> （`_part_uv_tri` 里的 `parts_head`/`face` 分支）去**抵消**这个 180°，
> 属于两个错误互相抵消；换角色/换缩放就失效并再次镜像，这就是
> "多次转换错误（包括镜像）"的来源。新实现删掉了所有按名字的翻转。

### 3.2 Mesh blend 索引存放方式

`m_VertexData.m_Channels[13]`（blendIndices，format=10）在不同资源里
既可能是**原始整数**（`0x00000002` = 索引 2），也可能是 **float 位模式**
（`0x3F800000` = 1.0f = 索引 1）。旧实现写死第二种，遇到第一种时索引全变 0
（每个顶点都绑到第 0 根骨骼），静止看不出、一动就散架。
修法：`unity_mesh._pick_bone_indices` 按"非零权重对应的索引必须落在骨骼数
范围内"自动判定。

### 3.3 动画曲线 path 换行续写

Unity 序列化超长字符串会折行：

```yaml
    path: bone_pelvis_01/bone_spine_01/.../bone_arms_03/parts_glow_body_star_1
      (6)
```

旧解析 `^(\s*)path:\s*(.*?)\s*$` 只取第一行 → 曲线套到"少了 ` (6)`"的另一个
节点上（实测偏差最大 2.4 世界单位）。修法：`unity_anim2d._read_path_field`
把缩进更深的续行拼回。修复后 aeda 主 clip 的 58 条路径 **100% 命中**节点。

### 3.4 null 骨骼占位

黑莉莉丝 `BL_parts_hair_4` 的 `m_Bones` 有 16 项、**第 5 项为 null**；
旧代码 `[b for b in bones if b]` 把它过滤掉，后面 10 根骨骼索引整体前移
→ 头发在动画里飞出去（最大 2.4 单位）。修法：原样保留长度与顺序，
`_skin_mesh` 遇到空骨骼按 Unity 规则跳过。

### 3.5 多角色场景拿错 Animator

`save.unity` 里同时有 aeda / 黑莉莉丝 / 奥黛丽。`TwoDModel.build` 会把场景里
**第一个** Animator（aeda 的 `ch_root`）当控制器，导致黑莉莉丝/奥黛丽套用了
aeda 的 clip。修法：`static_prefab_spine.load_character` 筛出本角色子树后
**重新选**子树内的 Animator，并按它重算 `anim_path`。
（“本角色自身就有多个 Animator”的情况见 3.12。）

### 3.6 动画中才出现的光晕被误删（补充修复）

旧实现用 **t=0 单帧尺寸**判断部件退化并直接丢弃。aeda 有一批光晕在 t=0 尺寸
恰好为 0、要等动画中段才放大出现，于是被整段删掉（用户实测"由下往上的蓝色
光晕"和"球后面的橙色光晕"消失）。修法：

1. 退化判断改为**整段动画的最大尺寸**；
2. t=0 尺寸为 0 的部件，把 setup 参考帧挪到它尺寸最大的那帧；
3. deform 关键帧写出条件从"偏移≈0 就跳过"改成"与上一个已写关键帧不同"，
   否则参考帧挪到中段后"回到参考姿态"那帧会被跳过，部件会被一直压扁。

被误删、之后补回的 4 个（Unity 真值里都可见）：

| 部件 | Unity 最大尺寸 | 首次可见 |
| --- | --- | --- |
| `bone_pelvis_01/bone_glow_1/parts_glow_1` | 1.086 | t=0.05 |
| `bone_pelvis_01/bone_glow_leg/parts_glow_1` | 0.866 | t=9.25 |
| `bone_pelvis_01/bone_glow_L_Arm/parts_glow_1` | 0.603 | t=6.5 |
| `bone_pelvis_01/bone_glow_L_Arm (2)/parts_glow_1` | 0.600 | t=1.7 |

### 3.7 多 Animator / 多 Clip：一次全转

aeda 有**两个** Animator：

| Animator 所在物体 | Controller / Clip | 驱动内容 |
| --- | --- | --- |
| `ch_root`（主） | `AGS_Aeda_N_2DModel.controller` → `lobby`（16.1s） | 全身骨骼、面罩、身体上的光点 |
| `aeda_ball_glow` | `bone_glow_ball_star_1.controller` → `star_deco`（4.75s） | **球体光晕的位移与缩放**（x -1.9~+1.8、z -2.0~+1.9，缩放 0.62~2.52） |

旧实现只采样主控制器，球体光晕停在 rest，于是**在 Unity 里会绕着球飘动/呼吸，
导出后却不动**。

修法（`enumerate_clips` + `assignments_for_entry` + `_sample_world_multi`）：

1. 枚举本角色子树里**每个 Animator 的每个 state/clip**（同名 clip 用 Animator
   名做前缀），逐 clip 建采样器；
2. 每个 Transform 归属"最近的 Animator 祖先"；**每个 clip 生成一条 Spine
   动画**，该 clip 驱动自己的 Animator，其它 Animator 播各自默认 clip（循环）；
   动画时长取驱动 clip 的时长（aeda：lobby 16.1s / Tep_1 4.18s /
   star_deco 4.75s，共 3 条动画、323+85+96 帧关键帧）；
3. **曲线 path 按各自宿主物体重算**（`star_deco` 里是 `bone_glow_1 (2)`，而不是
   `body/AE_ring/.../bone_glow_1 (2)`）——这一步不做的话位移曲线永远匹配不上；
4. 副动画按自身时长**循环**（4.75s 对主 16.1s ⇒ 主循环内跑 3.39 个周期），
   与 Unity 播放时一致。

默认全转；只想导出 setup clip 一条动画时用 `--no-secondary-anim`，
只想导出某一条 clip 时加 `--clip <名字片段>`。

实测（三个角色）：

| 角色 | Animator | 导出动画（帧数） |
| --- | --- | --- |
| aeda | 2（`ch_root` + `aeda_ball_glow`） | lobby(323)、Tep_1(85)、star_deco(96，副) |
| blacklilith | 1 | Start(289)、breast(74)、lobby(289) |
| audrey | 1 | lobby(227)、Tep_1(132)、breast(127) |

> 校准注意：Unity 的 PoseFrames 真值只推进了主控制器，所以副 Animator 驱动的
> 部件（球体光晕 4 个）在几何自检里会被自动排除，避免误报。

导出后实测（读导出 JSON 还原）：球体光晕相对球心的距离在
**0.08~1.75 世界单位**之间变化、尺寸在 **0.27~0.73** 之间脉动；
t=0 与 rest 一致。

### 3.8 副 Animator 的 rest 参考表（"橙光消失"的真凶）

多 Animator 采样必须**逐 Animator 建 rest 表**（`rest_by_animator`）：曲线 path
是相对各自宿主的，rest 也必须按同一口径。否则副 Animator 宿主节点
（相对路径是空串 `""`）会命中主控制器的 `""` 条目 → 拿到 `ch_root` 的
`scale [-1, 1, 0.151]`，整条球体光晕链被**在 Y 方向压成一条线**，
渲染出来就是"球后面的橙色光晕不见了"。

症状与判据：

| 现象 | 数值特征 |
| --- | --- |
| 橙色光晕看不见 | 该部件 4 个顶点 **y 尺寸 = 0**（x 尺寸仍正常），t=0 时尤其明显 |
| 光晕层 IoU 掉档 | 0.94 → 0.77（对照 Unity 精灵参考帧） |
| 真值比对却"正常" | 几何自检对主控制器部件仍 0.00001（问题只在副 Animator 子树） |

修法：`make_samplers()` 为每个 Animator 用 `rest_by_animator(mdl)[go]` 建采样器，
`convert_static`、`static_check`、`_run_calib` 共用它。修好后 aeda 光晕层
IoU 回到 **0.938**（比修复前还高，因为新增的 7 个部件也一起对了）。

### 3.9 只有骨骼索引、没有权重通道的小网格（audrey 的固定偏移）

audrey 的 `parts_Flush_020`、`parts_R_Hand_Added_018`、`parts_Eyebrow_Mouth_019`
等小网格在磁盘资源里是 `m_Channels[12].dimension = 0`（**没有 blend 权重通道**），
只有骨骼索引。Unity 对这种情况隐含"第一个索引权重 1.0"；旧实现退化成
"用渲染器所在 GO 的世界矩阵"→ 整块相对骨架有固定偏移（实测 0.11~0.19 世界单位，
约 70~120 px）。

修法（`convert_2dmodel._skin_mesh`）：没有权重但有骨骼索引时，合成
`(1.0, 0, 0, 0)` 权重后照常按骨骼蒙皮。修好后 audrey 逐顶点误差 **0.00000**。

> 排查方法：用 `calib_geo` 做"隔离姿态"对比——代入 Unity 真值世界矩阵后误差
> 仍不为 0，就说明是网格/绑定数据问题；再检查 `bones/bindposes/weights/索引`
> 是否与真值一致。

### 3.10 Unity 的 SetActive 表情切换（slot attachment 时间轴）

**现象**：blacklilith 导出后"两个眉毛""眼睛中间多一道"。

**原因**：这类角色的眼/眉/嘴有多组备选件（`BL_parts_eyebrow_2`、
`BL_parts_eye_l_2/r_2/l_3/r_3`、`BL_parts_mouse_2`），prefab 里默认
`m_IsActive: 0`，靠 AnimationClip 里的 **`m_IsActive` 曲线**在动画中切换
（同一时刻只启用一组）。旧实现只解析 T/R/S 曲线，这些备选件就被当成"常显"
全部导出了。

**做法**：

1. `unity_anim2d.parse_clip` 解析 `m_FloatCurves` 中 `attribute: m_IsActive`
   的曲线（阶跃，取最后一个 `time <= t` 的关键帧值），得到
   `clip["active"] = {anim_path: [(t, 0/1), ...]}`；
2. `unity_2dmodel` 记录 GameObject 的 `m_IsActive` 并算出 `activeInHierarchy`；
3. 转换时：**整段动画始终不可见的部件不导出**；部分时段可见的部件保留，
   并写成 Spine 的 slot attachment 时间轴：

   ```json
   "slots": {
     "BL_parts_eye_l_2_48": {
       "attachment": [
         {"time": 0.0, "name": null},
         {"time": 3.7, "name": "BL_parts_eye_l_2_48"},
         {"time": 5.4, "name": null}
       ]
     }
   }
   ```

   **`name` 必须显式写 `null`**：省略该字段会让 Viewer 的 Spine runtime
   崩溃（访问冲突），写成 `null` 才是"该时刻没有附件"。
4. `tools/spine_raster.py` 同步支持 attachment 时间轴，这样离线校准渲染
   的 t=0 与 Unity 一致。

**验证**：blacklilith 头部可见部件 t=0 由 11 个降到 5 个；lobby 在
3.7~5.4s 仍会切到第二组眼睛/嘴，`breast` 在 0.25~3.1s 切第三组。
aeda 也有一个 `AE_parts_hand_l_2_16` 属于同类（备用手）。

### 3.11 关键帧对齐与"瞬时切换"（眨眼生硬/闪烁）

**现象**：audrey 的眨眼在 Unity 里干脆利落，导出后在 Spine 里过渡僵硬、有闪烁感。

**原因**（两件事叠在一起）：

1. audrey 的眨眼不是补间，而是**骨骼 scale 的瞬时切换** ——
   `Bone_Eye_Nor` / `Bone_Eye_Close` / `Bone_Eye_Wink` 这几根眼球骨骼的 scale
   在 `1` ↔ `0.0001` 之间跳，Unity 用"**同一时刻两个关键帧**"来表示这种瞬切；
2. 采样是按 `--dt`（默认 0.05s = 20fps）均匀打点的，这些跳变点往往不在网格上
   （如 4.9333s、8.0333s），于是瞬切被拉成 0.05s 的线性渐变 —— 看着又硬又闪。

**做法**（`convert_static` 里构建采样时间轴时）：

- 采样时刻 = `--dt` 网格 ∪ **全部 T/R/S 曲线的关键帧时刻** ∪ `m_IsActive` 关键帧时刻；
- 遇到"同一时刻的重复关键帧"（Unity 的瞬切写法），额外补一个 `t - 1ms`
  的采样点，这样切换前后各有关键帧，Spine 里就是真正的瞬切。

**验证**（audrey `lobby`，眼睛部件 `parts_R_Arm_Units_018`）：

| | 眨眼关键帧 | 表现 |
| --- | --- | --- |
| 旧 | 4.900 → 4.950（跨 50ms，顶点差 138.8） | 线性渐变，僵硬/闪烁 |
| 新 | 4.9323 → 4.9333 → 4.9333（差 132.8） | 1ms 内完成瞬切 |

> 注意：audrey 的眼睛 mesh 在 prefab 里叫 `parts_R_Arm_Units_018`（名字有误导性），
> 它绑定 `Bone_Eye_Nor/Close/Wink/Flush/Smile/LookRight` 六根眼球骨骼。

### 3.12 主 Animator 的判定（多 Animator 角色的显式失败 / 隐性丢件）

3.5 只解决了“场景里第一个 Animator 不是本角色的”。本角色**自己有多个 Animator**
时仍会选错：旧逻辑取 `animators[0]`，也就是“组件在 prefab / scene YAML 文档里的
先后顺序”，而 Unity 侧真值用的是 `root.GetComponentInChildren<Animator>(true)`
——**按层级深度优先**取第一个。两个顺序不一致就会踩到辅助 Animator：

| 角色 | 辅助 Animator | 旧逻辑的后果 |
| --- | --- | --- |
| blacklilith_skin1 | `3P_BlackLilith_NS1_Chair_Only`（没挂 Controller） | controller=None → `没有可用 AnimatorClip`，导出直接失败 |
| daika_skin1_dl | `BR_Daika_NS1_Chair_Only`（部件全 `SetActive=0`） | 主角色子树被当成“次要 Animator 驱动”整段排除 → 校准 0 样本，批次判“未校准” |

修法：`unity_2dmodel.pick_main_animator()` 解析 `m_Children` 做层级 DFS，
没挂 Controller 的 Animator 优先跳过；`TwoDModel.build` 与
`load_character` 都改用它。0 样本时 `tools/calib_geo.py` 现在会明确报原因，
不再静默（以前只打印表格表头，批次脚本把它当成“解析异常”）。

50 个角色里“DFS 第一个 Animator 的 clip 集合包含真值 clip 名”**50/50 命中**，
主 Animator 判定发生变化的只有 3 个（babariana_skin1 / beasthunter_skin1 /
daika_skin1_dl）。

### 3.13 相对路径的宿主截断与“共用 Controller”的去重

曲线 path / rest 表都是**相对各自 Animator 所在物体**的，截断必须按**全路径分段**。
以前有 5 处用 `path.find(宿主名)` / `path.rfind(宿主名)`，两种情况必错：
节点重名（carolina 有 4 个 `GameObject`）、以及**一个宿主名是另一个宿主名的前缀**
（babariana 的 `Char_PECS_Babariana_NS1` 与 `..._Bg_Only`）。
统一改用 `unity_2dmodel.rel_path_in(宿主全路径, 节点全路径)`。

另外，`_all_clips` / `build_anim_assignments` 原来按 `controllerGuid` 去重：
**同一个 Controller 挂在两个 Animator 上时，第二个会被整条丢掉**，它的部件拿不到
曲线。改用 `(controllerGuid, Animator 所在物体)` 做 key，两个宿主各建一个采样器。

静态检查器随之修正：一份 clip 拷贝里指向**另一个 Animator 子树**的曲线，
在 Unity 里同样解析不到（只打 warning、不生效），不算导出缺陷，
现在单列为 `otherAnimatorCurves` 提示。

效果：`carolina_normal` 最大误差 0.363 → **0.000**；
`babariana_skin1` 静态检查的 64 条“path 对不上” → 0。

### 3.14 “场景里没有这个角色”的回退分支

`load_character` 在 `save.unity` 里找不到本角色时会退回 prefab 解析。
以前这条分支**直接 return**，跳过了公共收尾，于是：

- 没设 `mdl.excluded_parts` → 后续直接抛 `AttributeError`（重导 audrey /
  blacklilith 主力样例时暴露）；
- 没做“只保留 Animator 子树”过滤 → audrey 那种“静态立绘 + 动态立绘”双根角色
  会把整张立绘也当部件导出去。

改成 if/else 让两条路走同一段收尾即可。
另外，回退时导出的是 **prefab 坐标**，而真值是**场景坐标**，两者差一个常量平移
（blacklilith 5.0、aeda 20.0）：`tools/calib_geo.py` 现在会估出并扣除这个全局
平移、单独打印，避免把它误读成“运动中部件分离”。

### 3.15 渲染器自身的 `m_Enabled`（viewer 里的“圆环 / 针 / 骨骼标记”）

Unity 的 2D Animation / IK 会把骨骼、关节、样条控制点做成 **`m_Enabled=0` 的
SpriteRenderer**，贴图是 `BoneJoint.png` / `BoneNoJoint.png` / `BoneScaled.png` /
`IKControl.png` / `splineControl.png` / `splineMiddleControl.png` / `icon-*`。
它们在 Unity 里只在 Scene 视图当 gizmo 显示，**游戏里不渲染**。

旧实现判断显隐时只看 `m_IsActive` 曲线和父链，**没有回落到渲染器自己的静态
`m_Enabled`**，于是把这些 gizmo 一起导了出去：viewer 里就是人物身上多出
“圆环、针、关节标记”（tq.txt 第 1 类）。

修法两处：

1. `part_visible()` 在**没有 `m_Enabled` 曲线**时回落到该渲染器的静态
   `m_Enabled`（`_renderer_enabled()`，同 GO 多渲染器取“或”）；
2. 新增**贴图屏蔽表**：内置上述助手贴图名单，另外可用
   `--skip-texture NAME`（可重复/逗号分隔）或 `--skip-texture-file TXT`
   追加，命中的部件记入 `excludedParts`（原因：Unity 编辑器助手贴图）。
   屏蔽的部件不进图集，所以**图集页数也跟着减少**（加载更快）。

实测（2026-09-13，`_probe50` 15 个角色重导）：

| 角色 | 部件 | 图集页 | 轮廓 IoU（修前 → 修后） |
| --- | --- | --- | --- |
| amy_normal | 30 → **15** | 5 → **2** | 0.997 → **1.000** |
| alice_skin1_dl_idle | 129 → **49** | 8 → **2** | 0.893 → **0.911** |
| banshee_skin1 | 66 → **57** | 3 → **1** | 0.902 → **0.982** |
| csperrault_skin2 | — | — | 0.953 → **0.997** |
| alice_skin1_fix | 135 → **55** | 7 | 1.000 |

### 3.16 `m_FloatCurves` 的 path 也要拼折行（显隐错乱、表情消失）

3.3 修的是 `m_EulerCurves` 等“骨骼曲线”的 path 折行；**`m_FloatCurves`
（`m_IsActive` / `m_Enabled` / `m_Color`）当时还是只读第一行**。后果比 3.3 更隐蔽：

```yaml
    path: .../Bone_L_arm_hand/parts_L_arm_hand
      (1)                      ← 续行，真身是另一个节点 parts_L_arm_hand (1)
```

两条曲线被折叠成同一个 path，**后者覆盖前者**，于是“该隐藏的一直显示、
该显示的一直隐藏”。受影响角色（同一 clip 里至少两条曲线折叠）：
brownie_skin1(4) / banshee_skin1(14) / constantias2_normal(46) / bheur_skin1(65)。
症状就是 tq.txt 第 2 类那几条：右手少一块、眨眼只消失上眼眶、breast 时表情消失。

修法：`unity_anim2d.parse_clip` 里 `m_FloatCurves` 也用 `_read_path_field()`
读 path（与其它段一致）。验证：brownie_skin1 用新增的
`tools/check_visibility.py` 逐帧比对 Unity 真值的 `activeInHierarchy`，
修前 1 个 slot 不一致、修后**全部一致**。

> 注意：真值里 `activeInHierarchy` 是**采样 clip 之后又调了 `animator.Update(0)`
> 写出来的**，Animator 状态机会把采样值覆盖掉，所以对 `m_IsActive` 驱动的部件，
> 真值并不可靠（bheur 的 `Bone_Close_Eye` 曲线明明把它打开，真值里子件却始终
> 未激活）。这类差异要用“运行时渲染对照”判定，不能只看真值。

### 3.17 SpriteRenderer 的静态 `m_FlipX / m_FlipY`（贴图镜像）

Unity 的 `m_FlipX / m_FlipY` **只翻贴图（UV），不动几何矩阵**。旧实现完全没读这两个
字段，于是带翻转的部件渲染出来是镜像的——constantias2_skin1 的 `face` / `face_ani`
（`m_FlipX=1`）就是“眼镜和眼睛方向相反”的原因。

修法：`unity_2dmodel` 采集 `m_FlipX/m_FlipY` → `convert_2dmodel` 挂到 Part 上 →
`_part_uvs()` 在 [BL, BR, TR, TL] 顶点顺序下把左右角的 u（或上下角的 v）对调。

验证：constantias2_skin1 与 Unity 参考图的**颜色**误差 7.0 → **5.1**（轮廓 IoU 不变，
因为镜像不改变轮廓）；逐顶点误差保持 0.00000。

### 3.18 deform 关键帧裁剪与精度（加载速度）

第 1 类修好后，加载慢的主因就是 JSON 体积：旧实现**几乎每帧都写关键帧**
（判据是 1e-6），draculina 这种角色的单个 JSON 到 **609MB**。

改法（`DEFORM_TOL_WORLD = 0.001`、`DEFORM_PRECISION = 3`）：

1. 关键帧只在“相对上一个已写关键帧”的偏差超过 **0.001 世界单位**
   （≈0.7 源图像素，比验收阈值 0.05 低 50 倍）时才写；
2. deform 数值精度 6 → **3 位小数**（像素单位下误差 ≤0.0005px）。

实测（draculina_skin1）：

| 产物 | 修前 | 修后 |
| --- | --- | --- |
| JSON | 609 MB | **233 MB** |
| `.skel`（`--skel` 二进制） | — | **51 MB** |
| 逐顶点误差 | 0.01922 | 0.01923（无变化） |
| 轮廓 IoU / 颜色误差 | 0.9938 / 5.2 | 0.9938 / 5.2（完全一致） |

> 加载速度的两个杠杆：**先用裁剪后的 JSON**（体积 -62%）；spine-unity 场景里
> 改用 `--skel` 产出的二进制骨架（再小一个量级，51MB）。这两个都不改画质。

### 3.19 动画时长被关键帧裁剪截断（补末尾保持帧）

3.18 的关键帧裁剪会让“最后一帧之后就没再动过”的部件**停在动画中段**：Spine 的
动画时长 = 最后一个关键帧，于是 12.5s 的 clip 在产物里只剩 3.5s
（`_static_info` 记的是 12.5s，JSON 里却到 3.5s 就结束了）——运行时循环节奏与
Unity 不一致，校准工具也会因为“时长对不上”而拒绝比对。

修法：每条动画写完 deform 后，给**每个有键的部件**补一帧“保持帧”到 clip 末尾
（值取最后一帧，代价是每部件 1 个键）。

顺带修正校准工具的两个口径问题：

1. 用 `_static_info.setupClip` 选动画，而不是“JSON 里第一条”（多 Animator 角色
   的动画顺序一变就会拿错动画、算出假误差——daika_skin1_dl 曾被误报 0.232，
   实际是 0.0007）；
2. 两边时长差超过 0.35s 时明确打印“不是同一条动画，跳过比对”，不再给假数字。

### 3.20 真值里“Unity 没激活的渲染器”不参与几何比对

Unity 侧的 PoseFrames 是**连未激活渲染器一起导出**的（`includeInactiveRenderers`），
这些条目的 `BakeMesh` 结果是**未蒙皮的姿势**——拿它们比几何会得到“单部件恒定偏移”
的假误差。2026-09-13 的 50 角色校准里，C 档 6 个角色的最大误差全部来自这种条目：

| 角色 | 修前 | 修后 |
| --- | --- | --- |
| constantias2_normal | 0.262 | **0.00000** |
| constantias2_skin1S | 0.262 | 已回到 A 档 |
| cheona_skin1 | 0.321 | **0.033** |
| banshee_skin1 | 0.281 | 0.281（其中 3 个 Hand 条目无效，剩下的是下面那条数据问题） |

修法：`calib_geo.compare_spine_dir` 跳过 `activeInHierarchy == False` 的真值样本，
并在末尾打印跳过的数量。**注意**：真实显隐是否正确由
`tools/check_visibility.py` 单独判定，两者不要混。

### 3.21 网格 bindposes 数与 SMR 骨骼数不一致（个别部件）

`banshee_skin1 / parts_Hand_R`（`.../Global_CTRL/parts/parts_Hand_R`）与
`darkelf_skin1 / parts_Bg_Whistle_Head_006` 有**单个部件**的恒定偏移
（0.28 / 0.21 世界单位），排查结论：

- 该部件所在骨骼链的 local TRS 与真值**逐级一致**，渲染器世界矩阵与真值
  `localToWorld` 也**完全一致**；
- 差的是 `BakeMesh` 出来的顶点：Unity 的 baked-local ≠ `bindpose[i] · v`；
- banshee 的这个部件还有数据不一致：网格 `m_Skin` 里 **4 个 bindpose**，
  而 SMR 的 `m_Bones` 只有 **3 项**（另一份同名部件是 4/4，误差只有 0.0137）。

Unity 对这种“骨骼数与 bindpose 数对不上”的网格会给出未定义但确定的结果
（编辑器里也会打 warning），静态路线无法反推出唯一解；影响面是**单个小装饰件**，
暂按已知限制记录（真要还原需要修 Unity 工程里的绑定，或由美术重新绑一次）。

### 3.22 `m_IsActive` / `m_Enabled` 的运行时判据是 `|v| > 1e-3`（不是 `v >= 0.5`）

**现象**：表情消失 / 一个表情只显示一半（`tq.txt` 第 2 类：
"banshee_skin1 breast 动作的时候表情消失"、"bheur_skin1 Lobby 有眨眼，但在
Spine 只是上眼眶消失"）；同时 Play 真值里**互补的眼/眉部件会同时 ON**
（banshee breast 202 帧里 130 帧）。

**根因**（反汇编 + 同版本 Unity 实测，详见
[`Unity运行时逆向报告.md`](Unity运行时逆向报告.md)）：

1. Unity 把 `GameObject` 的 `m_IsActive` 绑成 **type 7**，写入时执行
   `if (v > 0.001 || v < -0.001) GameObject::Activate(go); else Deactivate(go)`
   —— 判据是 **`|v| > 1e-3`**；`m_Enabled`（bool，type 6）用同一阈值。
2. 曲线**是不是阶跃**由关键帧切线决定：编辑器 Constant 写成
   `inSlope/outSlope = ±Infinity`，其余是 Hermite 插值。
3. 工程里的 `m_IsActive` **6191/6505 条是插值曲线**（slope=0），段内取值在 0~1 之间
   ⇒ 运行时"刚离开 0 就显示"，只在"恰好等于 0"的极短窗口里隐藏。

于是旧实现（一律当阶跃 + `v >= 0.5`）把**大段本该显示的窗口整段藏起来**，
表现为"表情消失"；而 Play 真值里的"同时 ON"是**运行时的真实行为**，
不是采样器把值粘住了（8.1.8 的因果解释已作废，见 8.1.8 的更正框）。

**修法**：

- `unity_anim2d.parse_clip` 额外解析 `inSlope/outSlope`（认得 `Infinity`），
  产出 `active_tan` / `enabled_tan`；
- `static_prefab_spine` 新增 `unity_curve_eval()` / `active_is_on()` /
  `active_flip_times()`，`node_visible` / `part_visible` 改按运行时语义求值，
  `probe_times` 补上"翻转时刻"（否则短可见窗会被 0.05 网格跳过）；
- 开关 `--active-step` 回到老口径（只用于新旧对拍）；
- `tools/check_clip_visibility.py` 与 `tools/static_check.py` 同步口径。

**验证数字**（与 Play 真值 `activeSelf && activeInHierarchy` 在 0.05 网格上逐格比）：

| 角色 / 动画 | 旧口径不一致格子 | 新口径 |
| --- | --- | --- |
| banshee breast | 656 | **0** |
| banshee Tep_1 | 745 | **1**（10.05s 尾帧，属 3.19） |
| banshee lobby | 322 | **0** |
| banshee Start | 0 | **0** |
| bheur breast | 274 | **10** |
| bheur Tep_1 | 549 | **10** |
| bheur Lobby | 51 | **45**（残留，疑 clip 选择，见报告第 6 节） |

**回归安全**：`skeleton` / `skins` / 每个动画的 `bones` / `deform` **逐字节不变**
（只动 `probe_times` 不动 `times_of`），三主力"逐顶点误差 ≤1e-5"的基线不受影响；
aeda 44 部件、banshee 57 部件的**导出集合也不变**（`visible_anywhere` 等价：
全 0 关键帧的曲线在新口径下仍是全 0）。

**顺带修掉一个"假理由丢弃"**：`csperrault_skin2` 的
`.../Eye_C/Eye_smile/parts_Eye_smile_L` 原来被以"Unity 里始终禁用（SetActive=0）"
整段丢掉（`static_check` 报"动画中引用但未导出 1"）；新口径导出，计数归 0
（51 → 52 个部件）。成因见 `报告与校验.md` 7.6。

**19 个有 Play 真值的角色全量重转 + 真值审计**（产物在 `_verify_rt/`）：
96 个真值文件里 **11 个是废数据**（整段 transform 没变 = 采样没驱动 Animator，
包括 bheur `Lobby` —— 7.2 里那 45 格"残留"就是它）；83 个可用真值里 **65 个
逐格完全一致**，16 个只有 1~3 格边界噪声（合计 68 格），2 个大块差异
（blackwyrm `Lobby_BG` 686、circe `Drone` 126）经查也是"transform 在动但
没有任何 `activeSelf` 变化"的采样侧问题。受控 A/B：banshee 1723→1、
bheur 884→75、csperrault 1049→**0**。详见 `Unity运行时逆向报告.md` 第 8 节。

### 3.23 Sprite 交换的变体附件没有 deform（"两张脸 / 两个嘴 / 两个上眼框"）

**现象**（用户 2026-09-15 点名的截图之一）：`constantias2_skin1` 的 `breast`
里，角色的脸**裂成两张** —— 一张跟着身体动、另一张停在原地；`qustion.txt` 里
写成"breast 两张完整脸，在运动时一张不变一张清晰可见"。

**定位过程**（可复现的排查链）：

1. 逐顶点几何比对 `tools\calib_geo.py --only-spine-dir` → **0.00000 世界单位**，
   几何没问题；
2. 显隐比对 `tools\check_play_visibility.py` → **逐帧全对**，显隐也没问题；
3. 于是把 `parts_Head_15` / `face_ani_21` 分别单独渲染（复制产物目录、把另一个
   槽位的 `attachment` 置空）→ `parts_Head` 正常，**`face_ani` 明显偏大/错位**；
4. 再看运行时实际缓冲区：用查看器的 Spine 3.8 运行时 dump 每帧 VBO，
   `face_ani` 那一组的 4 个顶点**在任何时刻都等于 setup 值**（其余 591 个顶点
   都在动）—— 也就是说这个部件**根本没被 deform 时间线驱动**。

**根因**：`m_Sprite`（PPtr）交换导出成 **一个 slot 多 attachment + attachment
时间轴**（3.10）。Spine 3.8 的 `deform` 时间线路径是 `slot/attachment`，
**只在"当前挂的附件 == 时间线绑定的附件"时生效**；只写基础附件名
（`face_ani_21`）时，动画切到 `face_ani_21__2 / __3` 的那段时间里形变整段失效
⇒ 该部件冻在初始姿势。头部一动，静止的那张脸就和跟着动的头部分开成了"两张脸"。

**修法**（`ngui2spine/static_prefab_spine.py`）：建槽位时记录每个 slot 的
**交换变体附件名**（`variants_by_slot`，只收顶点数与基础附件一致的），
写 deform 时对同一份关键帧**给每个变体附件名各写一份**：

```python
smap = dd.setdefault("default", {}).setdefault(nm, {})
smap[nm] = frames
for alt in variants_by_slot.get(nm, ()):
    smap[alt] = frames          # 变体期间也必须有形变
```

**验证数字**：

| 检查 | 结果 |
| --- | --- |
| `constantias2_skin1` breast t=0.2 / 0.463 / 1.7 离线渲染 | 单张脸，表情按 `face_ani_21 → __2 → __3` 正常切换（`_scratch\c2s1_fixed\`） |
| `tools\check_skel.py _probe50_rt3\constantias2_skin1 --convert --ref-exe` | 与第三方转换器**逐字节一致**（2 539 777 字节），往返 0 差异 ⇒ 一个 slot 多个 deform 附件名，JSON/`.skel` 两条路都正确 |
| 受影响面 | 全库 50 个抽样角色里只有 **1 个**（`constantias2_skin1`）用到 Sprite 交换（`_static_info.json.spriteSwap` 非空的只有它），回归面很小 |
| 三主力回归（改后重导 + `calib_geo --only-spine-dir --times 0,1,2,4,5`） | audrey 0.00114 / aeda 0.00013 / blacklilith 0.00047 世界单位（都远低于 0.05 验收线），静态检查四项全 0 |

### 3.24 "多口 / 多眼 / 多手"是**工程数据本身**的行为，不是转换缺陷（2026-09-15 下午实测）

**现象**：`qustion.txt` 里一大类投诉 —— andvari_skin2 "所有动画的口，有一个小口
怎么没有消失"、bloodypanther_skin1 "一个圆口一个条口"、banshee_skin1 "手也有重叠"、
cerberus / cheona / constantias2 / csperrault 的"眼口重叠"。都是**同一时刻两组
备选件都被画出来**。

**先把"是不是我们多导了部件"排除掉**：

- 导出集合与 Unity 真值**逐个 renderer 对齐**。例：banshee 的
  `parts/parts_Hand_R`（组节点自己挂着 SMR）与 `parts/parts_Hand_R/parts_Hand_R`
  （子节点的 SMR）在 Unity `PoseFrames` 里**两个都是
  `activeSelf=true, activeInHierarchy=true, enabled=true, sortingOrder=45`**
  ⇒ Unity 自己就画两层手。
- andvari 的嘴：`Part_Mouth_Idle_36`（小实心口）与 `Part_Mouth_Smile_36`（细线）
  在 clip 里是互补的，但**两条都是零切线长斜坡**：
  `Idle (0,1)→(4.6833,0)→(6.1,1)`、`Smile (0,0)→(4.6833,1)→(6.1,0)`，
  斜率全 0（工程里 `inSlope/outSlope` **没有一条是 ±Infinity**，即没有 Constant
  阶跃）。按运行时判据 `|v|>1e-3`，Smile 从 **t≈0.086** 就离开 0 变 ON ——
  两条**几乎整段都可见**。

**再用同版本 Unity 实测（决定性）**：`_verify_animator\Assets\Editor\MouthProbe.cs`
把上面两条真实曲线做成 clip + AnimatorController，`animator.Update(0.05)` 自然步进：

| 时刻 | Idle 曲线值 | Smile 曲线值 | 实测 activeSelf |
| --- | --- | --- | --- |
| 0.00 | 1 | 0 | Idle ON / Smile off |
| **0.05** | 0.99966 | **0.00034** | **Idle ON / Smile ON** |
| 4.55 | 0.00239 | 0.99761 | Idle off / Smile ON |
| 6.10 | 1 | 0 | Idle ON / Smile off |

（原始记录 `docs/data/mouth_probe_20260915.json`；Unity 2022.3.3f1c1。）

**结论**：**Unity 自己就会把两组备选件同时画出来**（阈值极低，曲线一离开 0 就
激活）。旧的 `v>=0.5` 口径反而"看起来正常"，但那与运行时行为不符（见 3.22）。
所以这一类的差异是**工程数据 vs 用户看到的成品**之间的差异（很可能是资源在提取/
移植时把编辑器 Constant 切线抹成了零切线），**不是转换器漏掉或多余导出部件**。

**给用户的三条可选口径**（默认仍是"忠实于数据"）：

1. **保持现状**（推荐）：产物与 Unity 语义一致，静态检查四项全 0；
2. **同一父组内"只留曲线值最大的那个"**：能压掉 andvari 的"小口没消失"等，
   但需要更准的分组规则（实测过两版启发式：按"名字去尾号"会把左右脚
   `Part_Foot_0/Part_Foot_3` 误判成一组；按"同一父节点"会把整条
   `Global_CTRL/parts` 下面所有部件算成一组，**都不安全**，已撤回，
   没有改动随代码提交）；要做就得用"同一父组 **且** AABB 高度重叠 **且**
   尺寸同量级"三条同时成立，并且只在**互补曲线**（一条升一条降、区间重合）
   上生效；
3. **改 Unity 工程本身**：把那些互补件的 `m_IsActive` 改回 Constant 切线
   （`inSlope/outSlope = Infinity`，`tangentMode = 103`），转换器立刻跟着变对，
   不用给转换器加特例 —— 这是"从数据源头修"的正路。

**排查工具**：`tools\overlap_report.py <产物目录> [动画…]` 会列出"同一族
（名字去掉尾部编号）里同时可见、且 AABB 明显重叠"的部件对与持续帧数，
用来快速判断某个"多手/多口"属于哪一类。

### 3.25 `m_FlipX / m_FlipY` 是**绕 pivot 镜像几何**，不是"换 UV"（alice_skin2 的伞）

**现象**：用户报 `alice_skin2`"手里伞反了 / 位置不对，应该拿的是伞柄"。产物里伞整体
比 Unity 运行时高 **1.752 世界单位（1144 源图像素）**。

**根因**：`SpriteRenderer.m_FlipX = 1` 时 Unity 把四边形**绕 pivot 镜像**
（几何跟着动、UV 不变）；旧实现是"**只把左右两角的 u 对调**、几何不动"。
pivot 居中的精灵两种做法**完全等价**（所以绝大多数部件一直是对的），
但 **pivot 不居中 + 精灵细长**时就会落到 pivot 的另一侧 —— 这个伞的 sprite 是
`m_Rect {1226.99 × 152}`、`m_Pivot {x: 0.0318, y: 0.5132}`（pivot 贴着左端），
于是差了整整一个伞长。

| | 伞的世界中心 | 相对节点的偏移 |
| --- | --- | --- |
| Unity 运行时（`ModelInspect` 真状态机） | `(0.7033, **-0.9507**)` | 中心在 pivot **下方** 0.877 |
| 旧产物 | `(0.7162, **+0.8015**)` | 中心在 pivot **上方** 0.876 |

幅度一模一样、**符号相反** —— 就是镜像没做对。

**修法**（两处都要改，缺一不可）：

1. `ngui2spine/convert_2dmodel.py`（建四边形处）：flip 时把局部四角
   `x → -x` / `y → -y`，UV 保持原样；只翻一个轴时把三角形绕序也反一下
   （`[0,1,2,0,2,3]` → `[0,2,1,0,3,2]`），免得面朝向翻掉。
2. `ngui2spine/static_prefab_spine.py` 的 `_part_points()`：**它并不用上一步的
   四边形**，而是从 sprite 资源里重新拼一遍局部四角 —— 这里也要做同样的镜像。
   `_part_uvs()` 里那段"按 flip 对调 u/v"要**删掉**（否则等于翻两次）；
   `_part_tris()` 改成用四边形自带的那份绕序。

**验证数字**：

| 检查 | 结果 |
| --- | --- |
| `alice_skin2` `lobby` t=0 伞的中心/尺寸 | 产物 `(0.7033, -0.9507)` / `(0.2456, 1.8728)`，与 Unity 运行时**逐位相同** |
| 离线渲染 | 手握着伞柄、伞面朝下（`_scratch\al2fix\`） |
| 影响面 | `Assets/prefabs/lo/**/*.prefab` 1940 个里 **82 个**含 `m_FlipX/m_FlipY: 1`（含用户点名的 `csperrault_skin2`，2 个） |
| `csperrault_skin2` 的两个 flip 精灵 | `parts_arm_L_up2` / `parts_arm_L_hand2` 的中心与运行时真值 **Δ = 0.0000**（修前会落在另一侧） |
| 三主力回归 | audrey / aeda / blacklilith 静态检查**四项全 0**（不含 flip 的角色行为不变） |

> **排查方法值得复用**：先看"我们和运行时差多少"（`rt_frames` + 真值），再用
> `Assets/Editor/ModelInspect.cs` 的 `dynamic.json`（真状态机，含 `isVisible`）
> 与 `-probeChain <节点>`（逐帧 dump 父链 local TRS + 世界位置）做正运动学验算，
> 一次就能分清"几何错 / 显隐错 / 根本没被驱动 / 四边形放错边"。

### 3.26 Sprite 用 Unity 的 **Tight 网格**（多边形），不是四边形（2026-09-16）

**现象**：`alice_skin1_dl_idle` 右上角飘着一个小黑三角（用户截图
`Question/alice_skin1_dl_idle小黑点.png`）；Unity 自己渲染同一帧没有。

**定位链**（详见 `已知问题.md` 1.6，这里只记结论）：

1. 渲染图小块分析 → 反解到源图像素 `(214.7, 607.4)` → 只有 `parts_Horn_L` 覆盖；
2. 但该部件的 AABB 与 Unity 运行时**几乎逐位相同**（差 ≤0.003）⇒ 不是几何/显隐；
3. 裁出它的 sprite 贴图区一看：矩形右上角混进了**邻居图素**（109 px 的孤立小岛）；
4. 从 Unity 侧导出 `Sprite.vertices/triangles`：`parts_Horn_L` 是 **9 顶点 / 7 三角形**，
   而我们是 **4 / 2** ⇒ Unity 用的是 **Tight 网格**（该角色 111 个 sprite 里 110 个都是），
   小岛被它切在外面。

**逆向**（2022.3.3f1c1 的 `UnityPlayer.dll` + PDB，走 `tools/ida_q.py`）：

```text
SpriteUtility.GenerateSpriteOutline(tex, ppu, rect, pivot, extrude, meshType, …)
  └─ SpriteMeshGenerator::MakeShape(pixels, w, h, alphaCutoff, dilate, …, budget, …)
       mask::initialize : 位掩码 = (alpha > alphaCutoff)，再按 dilate(extrude) 膨胀
       contour          : 方向链码（45/43）走轮廓
       path::select     : 选主路径
       path::simplify   : 容差是**归一化到 [0,1]** 的（`fminf(1.0, a2)`）
       MakeShape 的迭代  : `while (w*h*0.25 > 顶点预算 && 方向码==45) 重提轮廓`
                          （顶点预算驱动的迭代放松 ⇒ 网格面积会明显大于 alpha 面积，
                            小的孤立小岛被切在外面）
```

**实现**：新增 `ngui2spine/sprite_outline.py`（掩码 → 膨胀 → 轮廓 → **按相对面积
丢掉过小的孤立岛**（默认 1% of 最大岛）→ 归一化容差 RDP → 顶点预算内迭代放松 →
耳切三角化）；`convert_2dmodel.build_character_model` 的 sprite 分支改为优先用它，
任何一步失败回落四边形；`static_prefab_spine` 的 `_part_points()/_part_uvs()` 改为
**直接用部件自己的网格**（原来这里会按 rect/pivot 重新拼四边形，是这次差点漏掉的一处）；
Sprite 交换的**变体**不共用基础网格（`vp.outline=False` + `vp.mesh=None`）。

**交叉验证（对 `alice_skin1_dl_idle` 的 110 个 sprite，与 `Sprite.vertices` 对拍）**：

| 归一化容差 | 我们顶点均值 | Unity 顶点均值 | 顶点差均值 | 我们比 Unity 多的比例 |
| --- | --- | --- | --- | --- |
| 0.07 | 6.1 | 12.3 | -5.82 | 4% |
| 0.15 | 4.7 | 12.3 | +2.81 | 0% |

小样本（20 个同族 sprite）上 tol=0.05~0.1 时**顶点数逐 sprite 一致（±1）**；
全局我们是**偏保守**（顶点更少），不会画出 Unity 不画的东西。
单部件核对：`parts_Horn_L` → 我们 **9 顶点 / 7 三角形**，Unity 同样 **9 / 7**，
局部范围差 ≤0.03 世界单位。

**验收数字**：

| 检查 | 结果 |
| --- | --- |
| `alice_skin1_dl_idle` lobby t=0 渲染 | 原来 `x[613,620] y[168,173]` 的 24 px 小块**已消失**（视觉 + 连通块分析双确认） |
| 三主力静态检查 | audrey / aeda / blacklilith **四项全 0** |
| 16 个点名角色重转 + `check_clip_visibility` | **15/16 全动画一致**（只剩 `babariana_skin1` 的既有 2 个 slot） |
| JSON 体积 | `alice_skin1_dl_idle` 107 MB → **109 MB（+2%）**，没有膨胀 |
| `calib_geo` | 顺手修好"我们顶点数 ≠ 真值 4 角 ⇒ 报 inf/nan"：sprite 一律走 AABB 比。该角色最大误差仍是尾巴 0.12358（既有取舍），`parts_Horn_L` 0.0085 |

### 3.27 主 clip 的兜底顺序：要按状态机的 `m_ChildStates`，不是"文件里对象的先后"

**现象**：`alice_skin1_dl_idle` / `alice_skin1_fix` 这类角色，`calib_geo` 直接
**拒绝比对**：

```text
clip=breast  部件=138  transform=324  真值帧=51
== 跳过端到端比对：我们的 setup clip 是 'breast'（8.00s），
   真值是 '3P_Alice_NS1_start'（2.50s）==
```

也就是说我们和人家的**姿态原点 / 参考动画根本不是同一条**，所有几何结论无效。

**根因**：`_choose_clip` 的规则是"按 **clip 资源名**找 lobby → 退一步找含 lobby
的 → 否则取 `cands[0]`"，而 `cands` 的顺序来自 `parse_animator_controller()`。
旧实现是**用正则扫全文**，得到的是**动画状态对象在文件里的先后**；Unity 的
`AnimatorController.animationClips`（`TwoDModelCalibExport.MainClip` 兜底取的
就是 `clips[0]`）是**按状态机 `m_ChildStates` 的排列顺序**遍历的。两者不一样的
典型：

```text
3P_Alice_NS1.controller
  文件对象顺序      : breast, Tep_1, Start, curtain, lobby   → 旧实现取 breast
  m_ChildStates 顺序: Start,  breast, Tep_1, lobby, Start     → Unity 取 Start ✓
```

**修法**：`ngui2spine/unity_2dmodel.py: parse_animator_controller()` 改成按块解析，
先收 `AnimatorState`(1102)，再按**第一个 `AnimatorStateMachine`(1107) 的
`m_ChildStates` / `m_ChildStateMachines`** 递归展开（子状态机也进），最后把没被
列进去的按文件顺序补上。返回值结构不变。

**验证数字**：

| 角色 | 修前 | 修后 |
| --- | --- | --- |
| `alice_skin1_dl_idle` | `clip=breast`，`calib_geo` 拒绝比对 | **`clip=Start`（两边一致）**，可逐顶点比：最大 0.12358 世界单位，集中在 `parts_Tail_F` 0.124 / `parts_Tail_B` 0.036，其余 ≤0.0002 |
| 三主力回归 | — | audrey / aeda / blacklilith 静态检查**四项全 0**（主 clip 挑选规则没变，有 lobby 的角色产物内容不变） |

> 这个改动也把 JSON 里 `animations` 的**顺序**换成了状态机顺序（更贴近 Unity），
> 但**主 clip 的挑选规则本身没变**（仍优先含 lobby 的那条）。

### 3.28 同一个 controller 挂在两个 Animator 上 ⇒ 每个动作导两份

**现象**（`babariana_skin1`，用户原话"**所有导出的动作几乎一模一样**"）：
产物里有 **22 条**动画，其中每个动作出现两次、且每一份只驱动**一部分**部件
（`Lobby` 的 deform 只有 80 个槽位，而整角色不止这些）。

**根因**：`Char_PECS_Babariana_NS1_Bg_Only` 与主 rig **共用同一个 controller**
（`PECS_Babariana_NS1.controller`），`enumerate_clips()` 按"宿主 Animator × state"
各导一份 ⇒ 同一 state 导两遍，两遍各引用自己的宿主、部件集不同。Unity 里它们
确实是两个各自播放的状态机，但对"用户看到的动作"来说就是一个 state。

**修法**（`ngui2spine/static_prefab_spine.py: enumerate_clips()`）：每条 entry 带上
`ctrl`（controller guid）与 `desc`（该宿主子树的节点数），按 **`(controller, state)`**
去重、只留**部件树更大**的那个宿主；另一个宿主交给 `assignments_for_entry()`
按"播自己的默认 state"驱动（与 Unity 一致）。

**验证数字**：

| 项 | 修前（`_probe50_rt2`） | 修后（`_probe50_rt3`） |
| --- | --- | --- |
| 动画条数 | **22** | **11** |
| 槽位 | 80（只有小宿主那部分） | **85**（整角色，deform 覆盖全部 85 槽） |
| `check_clip_visibility` | 2 个 slot 报假阳性（拿第二个宿主的曲线比第一个宿主的 clip） | **✓ 全部动画与 clip 关键帧一致（11 条）** |
| `static_check` | — | `unknownCurvePaths 0 / visibilityConflicts 0 / missingAnimated 0 / missingStatic 0 / extraInExport 0 / invisibleAllTime 0` |

> 顺带消掉了 `parts_L_finger_00_24` 那条"21 帧显隐变化但 clip 里没有曲线"的
> 假阳性 —— 它本来就是"拿第二个宿主的曲线去比第一个宿主的 clip"比出来的。
> 公共代码回归：audrey 静态检查四项全 0。

### 3.29 一个网格多个材质：按子网格拆部件（背包上的棕色小块）

**现象**（`babariana_skin1`）：背包上有一块**棕色小方块**，外加一条白色斜条。

**定位**：把嫌疑槽位逐个刷成不同纯色再渲染 ⇒ 那块被染成**橙色** ⇒ 来自
`parts_004_upperarm_L_skinned`（实际蒙皮挂在 chocolate 背景链上）。

**根因**：这个部件的 `SkinnedMeshRenderer` 的 Mesh 带**两个子网格 / 两个材质**
（`part1` + `part2`，索引 306 + 30）。Unity 按子网格分段画、每段用自己的材质；
我们原来把**整个索引缓冲**都贴第一个材质的贴图 ⇒ 第二个子网格（30 个索引）
被贴错图。

**修法**：

1. `ngui2spine/unity_mesh.py`：解析 Mesh 的 `m_SubMeshes`，得到
   `[(firstByte/2, indexCount), …]`，多段时存成 `mesh["submeshes"]`
   （`firstByte` 是字节偏移；索引 16 位 ⇒ `/2` 换算成下标）；
2. `ngui2spine/convert_2dmodel.py`：`len(subs) > 1 and len(mats) > 1` 时按子网格
   **拆成多个 `Part`**，每个只取自己那段 `triangles`、用自己那个材质的贴图
   （顶点 / uv / 权重 / 骨骼沿用整份，所以蒙皮不受影响）。

**验证数字**：

| 项 | 结果 |
| --- | --- |
| 拆出的索引段 | **306 + 30**，材质 `part1` + `part2`（与 Unity 的材质列表一致） |
| 重转 + 渲染 | 背包上的**棕色小块**与那条**白色斜条都消失**（vision 复核 `_scratch\bab2_bag.png`） |
| 公共代码回归 | audrey 重导（`samples\2DModel\audrey\static_spine`）：`unknownCurvePaths 0 / visibilityConflicts 0 / missingAnimated 0 / missingStatic 0` |

> 多材质的网格在整个库里很少见，但一旦遇到就是"整块贴错图"，所以这条修的是
> **通用**缺陷（`unity_mesh.py` + `convert_2dmodel.py` 都是公共模块）。

### 3.30 `ModelInspect` 的 `meshMin/meshMax` 少乘了一层世界缩放（工具口径 bug）

**现象**：`_inspect_<角色>\dynamic.json` 里的 `meshMin/meshMax` 是**极小且偏移**的框
（例：`babariana_skin1` 的 `parts_001_back_hiar` 给 宽 0.186，而同一行的
`boundsSize` 是 1.344）。2026-09-16 上午排查 B1b 时就是被这个错值带偏过一次。

**根因**：`ModelInspect.cs` 用了不带 `useScale` 的 `smr.BakeMesh(mesh)` ——
这个重载已经把**渲染器的世界缩放**乘进顶点，再乘一次
`r.transform.localToWorldMatrix` 就等于把缩放**平方** ⇒ 框小 |lossyScale| 倍。
而 `TwoDModelCalibExport.cs`（PoseFrames / SceneT0）用的是
`BakeMesh(baked, true)`，两边口径不一致。

**证据**：`babariana_skin1` 的 75 个 skinned 部件，逐个拿
"PoseFrames 真值（`localToWorld × positions`）÷ dynamic 错值" ⇒
**6.101 ~ 6.165**，正好是 1/0.16367（该渲染器的世界缩放）。

**修法**：`Assets/Editor/ModelInspect.cs` 两处（`WriteDynamic` / `WritePart`）改成
`smr.BakeMesh(mesh, true)`。

**验证数字**（重跑 `banshee_skin1`，与 PoseFrames 的 `banshee_skin1@…_breast` 第 0 帧比）：

| 分类 | 条数 | 差值 |
| --- | --- | --- |
| 逐位一致 | **29 / 43** | ≤ 0.0011 世界单位 |
| 手 / 手指 / 前臂 | 13 / 43 | 0.007 ~ 0.011（运行时步进 vs clip 采样的相位差，非本 bug） |
| `parts/parts_Hand_R` | 1 | 仍是垃圾值（PoseFrames 本身 `|pos|` 到 3640，运行时 1e22）—— 就是 **3.21** 那条 "4 个 bindpose / 3 根骨" 的数据不一致部件 |

> 结论：工具口径修好后，`meshMin/meshMax` 可以直接和 PoseFrames / 我们的产物逐位对账；
> 唯一还要绕开的是 3.21 那个坏部件。

### 3.31 Sprite 的渲染网格**直接读精灵资产**（"头上/脸上的碎块"）

**现象**（`banshee_skin1`，用户截图 `banshee_skin1头上异常块与多手.png`）：
额头正上方、双兽耳之间、刘海上多出一块**灰色的破碎块**，腿/肩附近也有灰白块。

**根因**：3.26 改成 Tight 网格之后，网格还是**按矩形内的全部 alpha** 现算的
（掩码 → 膨胀 → 轮廓 → 简化）。可 Unity 的精灵网格是"**只属于这个 sprite 自己
的那块形状**"，矩形里混进来的邻居图素要切在外面；大 sprite 上两者差得离谱：

| 部件 | 我们的多边形 / 矩形面积 | Unity 的网格 / 矩形面积 | 我们多盖且**不透明**的像素 |
| --- | --- | --- | --- |
| `parts_Head` | 76 011 / 103 509 = **73%** | 38 727 = **37%** | **39 454** |
| `parts_Hand_R1` | 13 691 = 61% | 6 943 = 31% | 8 714 |
| `FullbodyIMG_BR_Nymph_NS1_part_2`（左袖口） | 9 136 = 63% | 4 261 = 29% | 5 527 |
| `parts_Foot_L` / `Eye_normal` / `Cheek` / `Hair_acc` / `Bell` | — | — | 5 282 / 4 198 / 3 400 / 2 275 / 1 964 |
| `parts_Eyebrow_normal` / `_sed` | 12 159（**回落四边形**） | 2 304 / 1 917 | 182 / 189 |

（拿"我们多边形"和"Unity 精灵多边形"都投到**贴图像素网格**上比面积 ——
`_scratch/b3_sprite_probe.py`；Unity 那几个数来自 `ModelInspect` 导出的
`spriteVerts/Uvs/Tris`。20 个 sprite 里 **17 个**我们盖得比 Unity 多。）

**修法（关键发现：不用复刻算法）**：Unity 导入精灵时就把
"alpha → 轮廓 → 简化"的结果**存进了资产**：

```
Assets/rawLo/<角色>/<皮肤>/Sprite/<精灵名>.asset
  m_RD.m_VertexData    顶点（position 通道，sprite 局部空间，pivot 在原点）
  m_RD.m_IndexBuffer   16 位索引
  m_RD.uvTransform     (ppu, 图集内 pivot 像素 x, ppu, 图集内 pivot 像素 y)
  m_RD.textureRect     在图集里的矩形（算 uv 用）
```

uv **不进顶点流**（那一通道是 0），按 `uvTransform` 现算：
`u = (x·uvT.x + uvT.y) / 图集宽`、`v_std = (y·uvT.z + uvT.w) / 图集高`
（`v_std` 自底边算，落到本链路要 `1 − v_std`）。

落点：

1. `ngui2spine/unity_mesh.py`：`parse_sprite()` 多返回一份 `renderMesh`
   （`_parse_sprite_render_mesh()` 解 `m_RD`），并提供
   `sprite_mesh_from_sprite()`（含 flip 的镜像/绕序处理）；
2. `ngui2spine/convert_2dmodel.py`：新增 `sprite_part_mesh()` ——
   **① 精灵资产网格 → ② 按 alpha 复刻的轮廓（`sprite_outline.py`，保留）→
   ③ 四边形**；sprite 分支改调它，并把来源记进
   `_static_info.json.partsMeta[].meshSource`（`asset` / `outline` / `quad`）；
3. `ngui2spine/static_prefab_spine.py`：Sprite 交换的**变体附件**同样按
   "变体自己的精灵资产"取网格（原来无条件回四边形）。

**验证数字**：

| 检查 | 结果 |
| --- | --- |
| 资产网格解码（对运行时 `Sprite.vertices/uv/triangles`） | `banshee_skin1` **35/35**、`alice_skin1_dl_idle` **111/111** 逐位一致（位置/uv 差 ≤ 5e-6，索引个数相同；探针 `_scratch/sprite_asset_mesh.py`） |
| 重转 `banshee_skin1` 后的网格来源 | 20 个 sprite **全部 `asset`**，顶点数与 Unity 逐个相同（`parts_Head` 21、眉毛 15/14、`Nymph_NS1_part_2` 26…） |
| 多盖且不透明的像素（20 个 sprite） | `parts_Head` **39 454 → 0**；其余 17 个也是 0，只有两个 4 顶点的眼件还剩 14 / 8 px（栅格化边界）；`alice_skin1_dl_idle` 23 个 sprite 最大 **192 px** |
| 渲染复核（`breast` t=0.2） | 额头上方那块**灰色碎块消失**，腿/肩上的灰白块消失；与 Unity 同帧渲染（`_inspect_banshee_skin1\frames\breast_t200.png`）对着看**头脸干净、无多余块** |
| 回归（本轮只挑一个主力） | audrey 重导：`calib` 最大顶点误差 **0.00000** 世界单位，静态检查**四项全 0** |
| 16 个点名角色重转 | **16/16 成功、9 分钟**；`check_clip_visibility` → **16/16 角色全动画一致、0 个 slot 有问题** |
| `.skel` 写出器 | `check_skel.py _probe50_rt3\banshee_skin1 --convert --ref-exe`：与第三方转换器**逐字节一致**（15 304 625 字节）、drawOrder 往返通过 |
| `check_clip_visibility`（banshee / constantias2_skin1） | **✓ 4 条 / ✓ 3 条**，0 个 slot 有问题 |
| 连带：sprite 网格来源统计（16 个角色） | **324 个 sprite 全部 `asset`、0 `outline`、0 `quad`** —— 顺手把 B6（"18% 回落四边形"）在这批角色上清零 |

> 保留 `sprite_outline.py`（按 alpha 复刻的 `GenerateSpriteOutline`）**作为兜底**：
> 精灵资产里没有 `m_RD` 网格、或顶点流不是 float32、或
> `downscaleMultiplier ≠ 1` 时，仍然走它；再不行才回落四边形。
> 统计口径：`partsMeta[].meshSource`。
>
> 对账工具的两个坑（`_scratch/b3_sprite_probe.py` 都已修）：
> ① 必须**按三角形**栅格化 —— 我们产物里顶点顺序是三角形序、不是边界序，
> 按"顶点环"填会自交、把面积算错（`alice_skin1_dl_idle` 的
> `parts_Tail_Shadow` 一度虚报 12 035 px）；
> ② 不能拿两边 uv 投**同一张贴图** —— 我们产物会重打包图集、加色件还有单独的
> `_add` 页，uv 与源贴图不同空间（`alice_skin1_fix` 的
> `FullBodyIMG_3P_Alice_NS1_part1_26` 因此虚报 280 万像素）。
> 现在的口径是**与贴图无关的 fill = 多边形面积 / 包围盒面积**：
> `banshee_skin1` 20 个 sprite 里 18 个 `dFill = 0.0000`（顶点逐位相同），
> 另两个（`parts_Hand_R1` / `Nymph_NS1_part_1`）差值来自渲染器**非均匀缩放**
> （比的是未变换的精灵网格），这类部件以 `calib_geo` 的 AABB 口径为准。

### 3.32 `calib_geo` 的"整层排除"：上层 Animator 层驱动的部件不能进单 clip 比对

**现象**：`alice_skin1_fix` 端到端比对里 `parts_curtain` 一直报
**0.26236** 世界单位（B4 那条"疑似假阳性"），`parts_Tail_F` 0.063 也在表里。

**根因**：`PoseFrames` 真值是"**只推进一条 clip**"（编辑器 `SampleAnimationClip`），
而转换器是按主 Animator 各层的**默认状态**把上层 clip **叠**上去的
（`static_prefab_spine.compose_layers`：`3P_Alice_NS1.controller` 的
`curtain` 层默认就在播）。两边口径不同 ⇒ 被上层驱动的部件必然对不上。
 `tools/calib_geo.py` 原来只排"**副 Animator**"（`secondary_paths`），
同一 controller 的**第 2 层及以上**没排。

**修法**（`tools/calib_geo.py`）：新增 `layer_paths(mdl)` ——
对主 controller 的 `layer index ≥ 1`，取各层**默认 clip** 的全部曲线路径，
映射成角色根下的全路径；蒙皮件的形变跟着骨骼走，所以**骨骼命中这些节点的
渲染器**也算进来（`parts_curtain` 自己身上没有曲线，动的是 `Bone_curtain_*`）。
结果并入 `secondary_paths()` 的排除集合，`compare_parts` / `compare_spine_dir`
统一按它跳过。

**验证数字**（`alice_skin1_fix`，`--only-spine-dir --times 0,1,2,3`）：

| 项 | 修前 | 修后 |
| --- | --- | --- |
| 被排除的节点/部件 | 0 | **25**（22 个 `Bone_curtain_*` + `parts_curtain` + tail spline 命中项） |
| top1 误差 | `parts_curtain` **0.26236** | `parts_Tail_end` **0.03745**（B5 那条**既有取舍**，不是新问题） |
| 端到端最大误差 | 0.26236 | **0.03745** |

> `parts_Tail_*` 仍会出现在表里：真值本身是坏的（`尾巴修复记录.md`，
> 变形骨链的运行时脚本在 ripoff 工程里丢了），**别再当回归失败去修**。

### 3.33 槽位颜色时间轴丢「保持段」关键帧 ⇒ 部件整段半透明（2026-09-16 夜）

**现象**：`alice_skin1_fix` 的"右眼下粉条"追查过程中，发现一大批部件的
**透明度整段不对**：例如 `bloodypanther_skin1` 的 `parts_Thigh_L_Weter_01`
在 `breast` 里应该是"0.12 秒后消失、17 秒才回来"，产物里却变成
**从 0.12 秒一路慢慢浮上来**，整段叠在角色上像一层水痕；
`banshee_skin1` 的 `parts_Cheek`、`csperrault_skin2` 的 `parts_cheek` 同理。

**根因**：`color_timeline()`（`static_prefab_spine.py`）生成 slot 颜色关键帧时，
用的是"**值等于上一个有效值就丢掉**"的去重（`if hexv != prev`）。Unity 的
曲线里"**保持段**"的两个端点值相同，去掉中间那个点，Spine 的**线性插值**就会
把"保持"变成"匀速爬升"：

```text
Unity  parts_Thigh_L_Weter_01.a = (0,1) (0.117,0) (16.417,0) (16.75,0) (17,1)
旧产物                        = (0,1) (0.117,0) (17,1)      ← 中间两个 0 被吃掉
                                        ⇒ 0.117→17 是一条斜坡（半透明浮上来）
```

**修法**：去重口径改成"**只丢与前后线性插值共线的点**"（共线判据取
`0.5/255`，量化到 8 位后本来就看不出差）。同一条曲线现在保留成
`(0,1) (0.117,0) (16.75,0) (17,1)` —— 保持段完整，且冗余点仍然被去掉。

**量化**（`_scratch/hold_probe.py`，复刻两版去重逻辑，逐 0.05 s 采样比 Unity
原曲线的 alpha 偏差）：

| 范围 | 颜色曲线 | 偏差 > 0.05 | 最大偏差 |
| --- | --- | --- | --- |
| 16 个点名角色（改前口径） | 179 条 | **129 条** | **0.98**（`bloodypanther` 的湿身件） |
| 同上，改成"共线才丢"后 | 179 条 | 0（全部 ≤ 0.002） | 0.002（量化残差） |

**回归**：`audrey_normal` 重转：`calib` 最大顶点误差 **0.00000** 世界单位、
静态检查四项全 0；16 个点名角色重转 **16/16 成功**（`_scratch\rt3_reconv5.json`）、
`check_clip_visibility` **16/16 一致、0 个 slot 有问题**；
`check_skel --ref-exe`（banshee）**逐字节一致**（15 304 688 字节）。

> 残留差异（已知、可接受）：Unity 的零切线关键帧之间是 **smoothstep** 形状，
> 我们仍用**线性**分段（同一段内最多差 ~0.15 的 alpha）。要更贴近得按帧采样，
> 那会把 JSON 再放大，暂不做。

### 3.34 B4 收口：右眼下"粉条"是**源资源里就有的** + 渲染对账的正确口径

**结论**：`alice_skin1_fix`"右眼下粉条"**不是转换缺陷**。用户截图用的是
`_probe50_rt2/Question/_render_cfg.json` 的 `time_norm = 0.2`，即 breast 的
**1.6 秒**；用 `ModelInspect` 按**秒**采到同一时刻（`-probeTimes 1.6`）后，
Unity 自己的渲染在那只眼睛下面**也有同一道粉红斜条**：

| 量（眼下方同位置小方块） | 我们 | Unity 真值 |
| --- | --- | --- |
| 最大"粉度" `R-(G+B)/2` | 120 | **132** |
| 最红像素 RGB | (202, 82, 83) | (232, 89, 105) |
| 2 s / 3 s / 4 s | 都没有 | 2 s / 4 s 也都没有 |

而且**归因**是 `parts_cheek`（腮红）在 `breast` 里 0→1→0 的淡入淡出
（`(0,0) (1.78,1) (5.43,1) (7.87,0)`），那道粉条就是腮红贴图上的像素；
它在 1.6 s 出现、2 s 之后消失，两个渲染器**完全同步**。

**顺带修掉的坑（工具口径）**：

1. **`rt_frames.py` 的 `--times` 是"归一化比例"不是秒**
   （`SpineRender.SetAnimationTime` → `animationState.SetAnimationTime(track,
   normalizeTime)`，GUI 里也是 `0.00 / 1.00`）。所以 `--times 0.2` 在 8 秒的
   `breast` 上是 **1.6 秒**；要采"某秒"得换算 `秒 / 时长`。
   之前拿 `--times 0.2` 和 `-probeTimes 0.2`（秒）对图，是**两个不同时刻**。
2. **Unity 真值每帧取景都不一样**（`ModelInspect` 的相机按当前姿态自适应，
   同一动画 t=0 的图和 t=1.6 的图尺寸都不同）⇒ **不能按"非白包围盒"对齐**，
   要按 `frames/<状态>_t<毫秒>_cam.txt` 的 `cx/cy/size/ppu` 反解世界坐标
   （新工具 `_scratch/cmp_truth.py`：我们的像素 → 模型坐标 → 世界坐标 → 真值像素）。
3. `_scratch/align_cmp.py` / `cmp_crop.py`（按内容包围盒对齐）**只适合同一姿态**，
   跨时刻对比请用 `cmp_truth.py`。

### 3.35 显隐口径一度改成「按关键帧」：互补表情件不再同时 ON（2026-09-16 夜）

> ⚠️ **本节已被 3.37 取代**：改成阶跃口径后，Play 参考帧实测把一批
> “只在插值窗口里出现的件”整段藏掉了（draculina 181 处 / banshee 57 处不一致）。
> 最终口径是**运行时（插值 + `|v|>1e-3`）+ 正确的 alpha 时间轴**，见 3.37。
> 本节保留，作为“为什么一度改成阶跃”的记录；`--active-step` 仍是可选开关。

**现象**（`tq.txt` 第 2/3 类问题的总根因）：查看器里**同一个位置出现好几个
口 / 眼 / 眉 / 手**，用户的原话是"中间似乎有一个小嘴""脸上有不会动的多余的眉毛块"。

**根因**：工程里的表情/口/眼/眉是**互补开关**（一个 ON 另一个就 OFF），
但关键帧的切线是 **0**（不是编辑器 Constant）。"按切线插值 + 运行时判据 `|v|>1e-3`"
求值时，曲线在关键帧两侧各留一段 0<v<1，于是**几个备选件同时算 ON**：

```text
draculina_skin1 breast t=3.0s：
  Mouth_Close 0.788  Mouth_EE 0.795  Mouth_Smile 0.996  Mouth_Open 0.004
  ⇒ 运行时口径下四个都 >1e-3；Play 采样的 activeInHierarchy 也四个全 True
  ⇒ 画出来就是"嘴里多一个小嘴"、眼睛串成心形瞳孔
banshee_skin1 breast：Eyebrow_normal/sed、Mouth_normal/sed/angry 在 0.05~0.29s
  这种窗口里两两同时 ON，而真值里该显示的 normal 反而被我们算成 OFF（"表情消失"）
```

**修法**：`USE_RUNTIME_ACTIVE` 默认 **False** —— 显隐（`m_IsActive` / `m_Enabled`）
按**关键帧（阶跃 + v≥0.5）**求值；`--active-runtime` 可切回旧口径（只和 Play 采样对拍时用）。
几何、形变、颜色时间轴**不受影响**。

**验证**：

| 检查 | 结果 |
| --- | --- |
| `draculina_skin1` breast t=3.0s 渲染 | 只剩**一张**张开带尖牙的嘴 + 正常红瞳，与 `ModelInspect` 同帧一致（修前是"心形瞳孔 + 小嘴"） |
| `banshee_skin1` breast 显隐时间轴 | Mouth_normal/angry/sed、Eyebrow_normal/sed、Eye_normal/Smile **全部互补**，任意时刻只有一套 |
| `constantias2_normal` breast | 眼睛/眉毛按 0.05~1.9s 一组组切换，不再出现"两组同时 ON / 两组都 OFF" |
| `tools/check_clip_visibility.py` | 判据改成**跟随转换器**后，16 个点名角色 **16/16 一致、0 个 slot 有问题**（判据写死运行时口径时会误报 261 个） |
| 重转 | 16 个点名角色 + `tq.txt` 另外 6 个（amy_normal / bheur_skin1 / brownie_skin1 / blackwyrm_skin1 / circe_skin1 / draculina_skin1_fix）**22/22 成功** |

> **配套发现（很重要）**：`ModelInspect` 的 `dynamic.json` 里 `activeSelf /
> activeInHierarchy / enabled` **不随动画变化**（banshee 17 帧 0 次变化），
> 所以它**不能当显隐真值**用（只能当"静态姿态"和渲染图用）。
> 显隐真值用 Play 采样（`PlayFrames`）；编辑器/预览的观感用**渲染图**。
> 另外 `rt_frames.py --times` 是**归一化比例**（`秒/时长`），不是秒。

### 3.36 clip 曲线路径是 **CRC32 哈希**（`path_0x…`）——必须还原（2026-09-17）

**现象**：`alice_skin2` 的 `face`、`parts_Mouth_a` 等到点该显示的件一直不显示；
同一批 clip 里还有十几条**骨骼旋转曲线**我们从来没读到过。

**根因**：游戏里打包过的 `.anim` 有一部分曲线把节点路径**换成了哈希**，
真实路径根本没写在文件里：

```yaml
  - serializedVersion: 2
    curve: ...
    attribute: m_IsActive
    path: path_0xAC28B92_sMUTMHJ        # ← 只有哈希，没有 "…/Bone_head/face"
```

我们只能拿到 `path_0x…` 这个字符串，任何节点都绑不上 ⇒ 这些
`m_IsActive` / 位姿曲线被**静默丢掉**（"该显示的表情/手一直不显示"）。

**哈希算法（离线破译，唯一命中）**：`CRC32(路径字符串)`（IEEE 标准反射式，
UTF-8 字节），路径是**相对该 Animator 宿主**的那串（和曲线本来写成字符串时一致）。
`_scratch/hash_probe.py` 拿模型里所有节点的相对路径去撞哈希：

| 算法 | alice_skin2 的 4 条哈希 |
| --- | --- |
| **`crc32`** | **4/4 命中且每条唯一**：`face` / `CTRL_Dynamic` / `parts_BikiniString_patch_Sprite_s82` / `parts_Mouth_a` |
| hash33 / hash33(lower) / fnv1a / sdbm / crc32(lower) / crc_hqx | 0/4 |

**修法**（`ngui2spine/static_prefab_spine.py`）：新增
`path_hash()`、`hashed_path_table(mdl, host_go)`（按 `(mdl, 宿主)` 缓存）、
`remap_hashed_paths(clip, table)`、`resolve_clip_paths()`，在**四处 clip 加载点**
就地还原：`_choose_clip`、`_all_clips`、`build_anim_assignments`、
`enumerate_clips`（外加"其它 Animator 层默认 clip"那处；legacy
`convert_2dmodel.py` 也接了一份）。还原对 `active/active_tan/enabled/
enabled_tan/sorting/sorting_tan/color/material/morph/morph_tan/pptr`
以及 `curves[].path` 都生效；解不出来的记进 `clip["_unresolved_paths"]` 供对账。

**验证**：

| 检查 | 结果 |
| --- | --- |
| 50 角色扫描（`tools/hash_path_scan.py --json _scratch/hash_scan50.json`） | 有哈希路径的**只有 2 个**：`alice_skin2`（显隐/排序等 8 条 + 位姿 59 条）、`draculina_skin1_fix`（位姿 7 条）；还原后未解出 **0** |
| 显隐对账（`_scratch/truth_chain_probe.py` 对 Play 参考帧） | `alice_skin2` **13 → 0 处**不一致 |
| 位姿影响（`_scratch/hash_effect.py`） | `alice_skin2` / `draculina_skin1_fix`：开/关还原**逐节点世界坐标差 0**（那些哈希旋转曲线与已有的 euler 曲线重复） |
| 回归（只挑一个主力） | audrey 重导产物 vs "关掉还原"再跑一遍：**逐字节一致**；静态检查四项全 0（31 渲染器 / 29 部件） |

### 3.37 显隐口径终局 + 参考帧真值的四个陷阱（2026-09-17）

**口径**：`USE_RUNTIME_ACTIVE = True` —— **插值 + `|v|>1e-3`**（3.22 那套，依据
`Unity运行时逆向报告.md` 的反汇编 + 同版本实测）**再叠加 m_Color 的 alpha 时间轴**
（3.33 修的）。理由：Play 参考帧（7 角色 × 3 状态 × 10 时刻，共 240 帧）按这个
口径对账只剩个位数不一致，且每条都能归到下面四个陷阱；换回阶跃口径则会整段藏掉
draculina 181 处 / banshee 57 处（3.35 那一版）。

**陷阱 1：参考帧采自"场景实例"，而场景里的 `m_IsActive` 可能被改过。**
`_scratch/scene_flags.py` 把 `Assets/Scenes/2.unity`（用户采样用的那个场景，2.18 MB、
对象已展平、`PrefabInstance` 对象 0 个）解析成 `{角色: {路径: m_IsActive}}`，
再用 `_scratch/scene_vs_prefab.py` 与 prefab 逐节点比：

| 角色 | 场景 ≠ prefab 的节点 |
| --- | --- |
| `draculina_skin1` | 场景里**开着** 10 个 prefab 里是关的：`Bone_Cheek`、`Bone_Heart_L/R`、`Bone_Mouth_1/2/3`、`Part_Arm_Shade`、`Part_Finger_L02_5`、`Part_Finger_L210_12`、`Part_Hand_L2_7` —— 正是 Tep_1/breast 两条 clip 会动画的那些 |
| `constantias2_skin1` | 场景把 `face` **关了**（prefab 是开的） |
| banshee / bheur / brownie / cerberus / alice_skin2 | 除角色根（摆放时 disabled）外**完全一致** |

⇒ 显隐真值要用 **prefab + clip**（= 游戏实例化那套），场景里那几个节点是运行时快照
/手工改过的。draculina 的 84 处、constantias2 的 10 处不一致**全部**由这一条解释。
另外那条旧猜测（"场景解析器没处理 `PrefabInstance.m_Modifications`"）**不成立**：
`save.unity` / `2.unity` / `main.unity` 里 `propertyPath: m_IsActive` 出现 **0 次**，
2.unity 里连 `m_SourcePrefab` 都没有（对象是展平的）。

**陷阱 2：采样时刻越过 clip 时长 ⇒ 状态机已经切走。** `brownie_skin1` 的 breast
clip 只有 **2.5 s**，参考帧却采到 t=2.6/2.73/3.0/3.4：那时 Animator 已退出该状态、
写了默认值，真值里的 `face` 显示属于"另一个状态"。
⇒ 采样只在 `[0, clip 时长)` 里取（改 `PlayRefShotPlan.Times`）。

**陷阱 3：每个状态的"第一帧"混着进入 Play 的过渡。** 所有 `breast t=0` 的差异
都是这一类（banshee 4 条、cerberus 4 条、bheur 的手指 Open/Normal 互换各 1 条）：
`animator.Play(state, 0, 0)` 之后两帧内仍在与默认状态混合。
⇒ 首帧改在 t≈0.05~0.1 采，或每个状态重新进一次 Play。

**陷阱 4：同名孪生节点，曲线在 Unity 里只绑到其中一个。** `brownie_skin1` 有
**两个路径完全相同**的 `parts_L_arm_finger`（一个 prefab 开、一个关），clip 里那条
常量 0 的 `m_IsActive` 只作用于 Unity 选中的那个，另一个保持 prefab 的"显示"；
我们按路径查表会把曲线同时套给两个 ⇒ 丢掉 Unity 还画着的孪生件
（`parts_L_arm_finger(×2)` 20 帧全不一致）。两个孪生件网格/位置完全相同，
**画面上没有差别**，暂按现状记录（要修得给节点引入"同名序号"维度）。

**7 角色现状（Play 参考帧 240 帧对账，修后）**：

| 角色 | 不一致 | 归类 |
| --- | --- | --- |
| `alice_skin2` | **13 → 0** | 3.36 哈希路径修好 |
| `banshee_skin1` | 4 | 陷阱 3（breast t=0） |
| `cerberus_skin3` | 4 | 陷阱 3（breast t=0） |
| `bheur_skin1` | 20 | 陷阱 3（手指两套互换各 1 帧）+ 死绑定例外表（转换器已按 `ACTIVE_DEAD_BY_ROLE` 处理，探针对账时未套例外表，故仍计 5 条） |
| `brownie_skin1` | 24 | 陷阱 4（20 帧）+ 陷阱 2（`face` 4 帧） |
| `constantias2_skin1` | 10 | 陷阱 1（场景把 `face` 关了） |
| `draculina_skin1` | 84 | 陷阱 1（场景开了 10 个节点） |

## 4. 光晕与颜色

旧实现只保留手挑的 4~6 个 `parts_glow*`、全部按普通 alpha 混合、没折算材质
tint。新实现完全按 Unity 材质数据导出：

| 项 | 取值来源 | 说明 |
| --- | --- | --- |
| 顶点色 | `SpriteRenderer.m_Color` | 有些光晕是红/蓝染色，必须保留 |
| 混合模式 | 材质 shader fileID `200`（Legacy Particles/Additive）→ `blend: additive` | 其余 `normal` |
| 材质 tint | `_TintColor`（add.mat = 0.5,0.5,0.5,0.5） | 加色片元是 `2*color*_TintColor*tex`，混合 `SrcAlpha One` |
| 贴图 | 加色区域按 alpha 预乘 | Spine 的 `additive` 是 `(ONE, ONE)`，预乘后才与 Unity 等价 |

折算公式：`slot.rgb = 4 * _TintColor.rgb * _TintColor.a * m_Color.rgb * m_Color.a`
（对 `_TintColor=0.5`、`m_Color.a=1` 即等于 `m_Color.rgb`）。
全黑 `m_Color` 的光晕（Unity 里本来不发光）加色后自然不可见，不再需要手挑。

## 5. 图集页数（为什么有时 2 张、以及简化）

**原因**：Spine 的 `additive` 是 `(ONE, ONE)`，Unity 的加色是
`Blend SrcAlpha One`；两者等价的前提是**那片贴图的 rgb 已按 alpha 预乘**。
早期实现为稳妥起见整页复制一份预乘副本，于是多出一张 2048² 的图。

**现在的做法**（`static_prefab_spine.py` 图集打包部分）：

1. 按源贴图分组，算出"需要预乘"的部件实际用到的像素矩形；
2. 用三角形覆盖测试判断这些像素**有没有被普通混合的部件采样**：
   - 没有 → **就地预乘，只输出一张 PNG**（aeda 属于这类：那片 44×45 点光区
     只有加色光晕在用）；
   - 有共用 → 才退回两张，且第二张**裁剪到实际用到的小区域**并重映射 UV；
3. 导出后清理上一次留下的图集页残留（日志 `[clean] 删除旧图集页`）。

验证（aeda 单页化后）：点光区之外 alpha>0 的像素与源贴图**逐像素一致**；
点光区内与预乘结果一致；光晕 IoU、整角色 IoU 与两张页时相同。

当前页数：aeda 1 张、blacklilith 1 张；audrey 2 张是因为源资源本身就是
**两张不同贴图**（`FullbodyIMG_PECS_Audrey_N.png` 供 body sprite、
`..._Parts.png` 供 23 个蒙皮件），不是重复导出。

> 2026-09-10 更新：audrey 的 `body` 其实是**静态立绘**（与动态立绘并列的
> 另一个根 `2DModel_PECS_Audrey_N_root`），不属于动画内容。现在默认
> `--animated-only` 会把它排除，audrey 也变成 **1 张 PNG / 23 个部件**；
> 用角色自带的静态立绘做参照，动态部件渲染出的轮廓与其 IoU **0.994**
> （1516×1944 vs 1474×1891），说明去掉静态立绘后仍然是完整人物。

## 6. Alpha 约定与 Shader 依赖

### 6.1 为什么会有依赖

Spine 运行时 `blend: additive` = `Blend One One`（源色不再乘 alpha），Unity 的
加色是 `Blend SrcAlpha One`；等价前提是那片像素已预乘。所以加色光晕天然要求
对应像素预乘，这不是额外发明的约束。

### 6.2 三种自洽配置

| 图集 | 普通 slot | 加色 slot | 适用 |
| --- | --- | --- | --- |
| **A. 直通图集 + 加色区预乘**（默认产物） | `SrcAlpha / OneMinusSrcAlpha` | `One / One` | 本项目校准光栅器；"直通 alpha + One/One 加色"的运行时 |
| **B. 全局预乘 `--pma`** | `One / OneMinusSrcAlpha` | `One / One` | **spine-unity 默认材质**、任何 PMA 管线 |
| C. 全直通 + `SrcAlpha / One` 加色 | `SrcAlpha / OneMinusSrcAlpha` | `SrcAlpha / One` | 只做普通混合的预览器；Spine 官方 additive 不是这个 |

### 6.3 本项目 spine-unity（3.8）实测

`Assets/Spine/Runtime/spine-unity/Shaders/`：

| Shader | 混合 | 说明 |
| --- | --- | --- |
| `Spine/Skeleton` | `Blend One OneMinusSrcAlpha` | 带 `_StraightAlphaInput` 开关，**默认关 = 贴图按预乘处理** |
| `Spine/Blend Modes/Skeleton PMA Additive` | `Blend One One` | 同一开关，默认关 = 预乘 |

结论：**Unity 里推荐用 `--pma` 产物**（默认材质直接可用）；用默认产物则两个
材质都要勾 "Straight Alpha Texture"，而加色区已预乘 → 光晕会偏暗。

### 6.4 两种产物实测等价

| 指标 | 默认产物 | `--pma` 产物 |
| --- | --- | --- |
| Viewer 渲染平均 RGB | (191.7, 189.0, 183.4) | (191.7, 189.0, 183.3) |
| 两者像素差异 | 1,656 像素（0.3%，集中在光晕） | 同左 |
| 光晕层 IoU（对 Unity 参考） | 0.959 | 0.959 |
| 整角色 IoU（对 Unity 参考） | 0.9803 | 0.9803 |

> Viewer 的 PMA 自动识别只认 **atlas 文件名是否含 "pma"**，所以 `--pma` 产物
> 的 atlas 命名为 `<角色>_static_pma.atlas`，`_static_info.json` 里也记
> `"pma": true`。该 Viewer 一次 draw call 只有一个混合状态、无法按 slot 切
> 加色，属预览器限制，与导出数据无关。

## 7. 静态检查器 `tools/static_check.py`

专门回答"**动画/场景里引用的资源，有没有在导出里漏掉**"，转换时自动跑
（`--no-static-check` 跳过），报告写到 `<导出目录>/_calib/static_check.json`。

| 分类 | 含义 | 处理 |
| --- | --- | --- |
| ① 动画会改变、但导出里没有 | **最隐蔽**：静止看不出、播放时才少东西 | 必须修 |
| ② 静态可见、但导出里没有 | 不动的装饰件漏导 | 建议修 |
| ③ 场景里有但导不出 | 附原因：`m_Sprite=0` / 贴图或 Mesh 找不到 / 渲染器禁用 | 按原因处理 |
| ④ 整段动画尺寸为 0 | Unity 里也不可见（会同时列出 Unity 真值尺寸佐证） | 可忽略 |
| ⑤ 导出里有、场景里没有 | 产物异常 | 必须修 |
| ⑥ 与 Unity 帧真值不一致 | 真值里可见、静态管线算成不可见 | 必须修 |
| 曲线 path 解析 | 每条动画曲线 path 能否落到场景节点 | 必须修 |

"动画会改变"的判定：按 `--dt` 采样整段 clip，比较世界包围盒尺寸变化与中心
位移（阈值 1e-3）。

**覆盖范围**：检查器会枚举**所有 Animator 的所有 clip**（不只主控制器）：

- 每条 clip 的曲线 path 都按**它自己的宿主物体**解析后比对；
- "动画会改变"按所有 clip 一起判断（只在副动画里动过的部件也会被算进来）；
- 对不上节点的曲线会区分两类：末段与某个导出部件同名 → **报错**（真的漏了）；
  否则视为**组件/粒子曲线**（Unity 对组件用 `path_xxxx` 这类哈希路径，例如
  `Particle System` 的位移曲线），只作提示，不判失败。

回归演示（把已补回的 4 个光晕从清单里删掉后运行，检查器精确报出）：

```text
== ① 动画会改变、但导出里没有（4）
   - bone_pelvis_01/bone_glow_1/parts_glow_1   最大 1.0859 / t=0 尺寸 0.0 / 位移 9.99
   - bone_pelvis_01/bone_glow_leg/parts_glow_1 最大 0.8665 / t=0 尺寸 0.0 / 位移 6.74
   - bone_pelvis_01/bone_glow_L_Arm (2)/parts_glow_1 最大 0.5995 / t=0 尺寸 0.0 / 位移 2.50
   - bone_pelvis_01/bone_glow_L_Arm/parts_glow_1     最大 0.6033 / t=0 尺寸 0.0 / 位移 3.44
```

当前结果（均退出码 0）：

| 角色 | 场景渲染器 | 导出部件 | ①缺失 | ③导不出 | ④全时不可见 | 曲线 path |
| --- | --- | --- | --- | --- | --- | --- |
| aeda | 44 | 37 | 0 | 0 | 7（真值也是 0 尺寸） | 58/58 |
| blacklilith | 35 | 34 | 0 | 1（`face` 的 `m_Sprite=0`） | 0 | 31/31 |
| audrey | 25 | 24 | 0 | 1（`face` 的 `m_Sprite=0`） | 0 | 65/65 |

## 8. 校准工具

| 工具 | 作用 |
| --- | --- |
| `tools/static_check.py` | 静态检查：动画/场景引用但未导出、曲线 path、真值可见性冲突 |
| `tools/calib_geo.py` | 逐帧对比局部 T/R/S 与部件顶点；`--only-spine-dir` 可**直接校验导出文件**（读 setup+deform 还原）；无 renderer 真值时用 `--scenet0` |
| `tools/spine_raster.py` | 最小 Spine 光栅器：deform / slot 颜色 / normal·additive / PMA，相机可与 Unity 对齐 |
| `tools/calib_face.py` | 单脸单独渲染 + 与 Unity 单脸参考做 IoU，并对照 4 种 UV 变体判定朝向 |
| `tools/calib_sprites.py` | 光晕层与 Unity 精灵参考帧对比，并给出"关掉加色"的对照 |
| `tools/calib_full.py` | 反推 Unity 参考帧相机，整角色轮廓 IoU + 左右对照图 |
| `tools/make_calib_evidence.py` | 把对照图整理到产物目录的 `_calib/` |
| `tools/face_check.py` | 单脸截出 + vision.js 校验（转换后自动执行） |
| `tools/check_calib_data.py` | 检查 Unity 侧 `info/Data` 是否完整（逐个解析 PoseFrames，标出截断/残留的坏文件） |
| `tools/diff_ascii.py` | 把参考图与我们的渲染图摊成 ASCII，并分别画出"我们多出的"和"我们缺的"区域 |
| `tools/check_skel.py` | `.skel` 二进制产物校验：`--convert` 由 `.json` 生成、`--ref-exe` 再与第三方转换器逐字节对拍（见 9.3） |
| `tools/check_visibility.py` | 逐帧比显隐：导出的附件时间线 vs `PoseFrames` 的 `activeInHierarchy`（state→clip 自动配对） |
| `tools/check_play_visibility.py` | 同上，但用 **Play 模式真值**（`info/Data/PlayFrames/`，带 `activeSelf`/`enabled`），能指出“父链禁 / 自己禁 / 渲染器禁用” |
| `tools/check_render_diff.py` | 把“我们的渲染”与 Unity 参考图的差异**聚类**，并列出覆盖该区域的部件（查“多出一小块/缺一块”） |

> 分层参考图（`01_dynamic` / `02_sprites_white` / `03_sprites_dark`）必须是**真的分层**：
> Unity 侧 `CaptureSet()` 在渲染前要按集合禁用非目标渲染器（否则 sprites 层里会混进
> 整个角色，光晕层比对会得出"完全对不上"的假结论——这个问题在 2026-09-10 修掉）。

### 8.1 Play 模式运行时采样（判定显隐问题的最终手段）

`TwoDModelCalibExport` 用的是 `AnimationMode.SampleAnimationClip`（编辑器采样），
它不跑 Animator 状态机；采样后那句 `animator.Update(0)` 还会把刚采到的
`m_IsActive / m_Enabled` 覆盖掉。所以“表情消失 / 眨眼看不对”这类问题**不能只靠
PoseFrames 判定**，需要在 Play 模式下按状态机采一次。

脚本：`Assets/Editor/PlayModeSamplerRunner.cs`（采样实现）+ 
`Assets/Editor/PlayModeSamplerWindow.cs`（编辑器窗口）+
`tools/check_play_visibility.py`（比对）

> Unity 要求**文件名与类名一致**，所以拆成两个文件（曾经合成一个
> `PlayModeSampler.cs` 导致 `missing the class attribute 'ExtensionOfNativeClass'`）。

```text
Unity 里：菜单 Tools/2DModel/运行时采样/采样窗口
  · 角色名留空 = 自动扫描场景里所有 2DModel 角色（含 disabled）
  · 先点「只打印诊断（不进 Play）」：日志里会列出扫到几个角色、
    每个角色有几个 Animator、每个 Animator 有几个状态（排查"点了没反应"用这个）
  · 点「开始采样（进入 Play 模式）」→ 脚本逐个 **角色 × Animator × 状态**
    Play + Update(0)，逐帧记录
  · 完成后自动退出 Play 模式，写到 info/Data/PlayFrames/<角色>@<状态>.json

离线：python tools\check_play_visibility.py _probe50\<角色> --top 20
```

> **日志文件：`D:\VB\Unity2Spine\info\_logs\play_sample.log`**（同时打 Console）。每一步都写：
> 按钮按下、配置、扫到几个角色、每个 Animator 的状态清单、每个状态文件、
> 异常堆栈、最终汇总。菜单 `Tools/2DModel/运行时采样/打开日志` 可直接打开。
>
> 触发通道有两条：`playModeStateChanged` 与 `EditorApplication.update` 轮询——
> 即使 Project Settings 里关了 Domain Reload（静态构造不重跑），也能挂上运行器。
> 输出文件名是 `<角色>@<Animator>@<状态>.json`，另外写一份 `_summary.json` 汇总。
> 副 Animator（如 aeda 的 `star_deco`）也在遍历范围内。
>
> 采样器**不是 MonoBehaviour**：放在 `Assets/Editor/` 的脚本不能
> `AddComponent` 到 GameObject（Unity 会报 "Can't add script behaviour ...
> because it is an editor script"），所以改成用 `EditorApplication.update`
> 手动推进自己的 `IEnumerator`（每编辑器帧推进；配合“一帧连采 25 个点”的批处理，
> 19 个角色约 1~2 分钟跑完）。
>
> 两个坑（都踩过）：
> 1. 手动推进时 `yield return <IEnumerator>` **不会自动展开**（那是 MonoBehaviour
>    协程调度器的能力），必须自己维护迭代器栈 —— 否则内层协程不执行，
>    会出现“报成功 104 个状态但一个文件都没写”。
> 2. 采样前必须 `animator.Rebind()`：否则**上一个状态打开过的部件会留着**
>    （babariana 的 `Start` 被 `breast` 污染，凭空多出 51 个“Unity 显示而我们隐藏”）。
>
> 打开「写全量 BakeMesh」时会额外产出 `<角色>@<Animator>@<状态>.playpose.json`，
> 结构与 PoseFrames 完全一致（`frames[].transforms / skinned / sprites` + 全量
> positions/uvs/triangles + localToWorld + `activeSelf/activeInHierarchy/enabled`），
> 可直接 `python tools\calib_geo.py --pose <该文件> --only-spine-dir --spine-dir <产物>`
> 做逐顶点比对；建议用「只给这些角色写全量 BakeMesh」限制范围（体积大）。

#### 8.1.1 运行时组件版（推荐给"批量挂到场景里的角色"）

编辑器驱动的采样器不能挂到 GameObject（Editor 脚本），所以另有一套**运行时组件**方案：

| 文件 | 类型 | 作用 |
| --- | --- | --- |
| `Assets/PlayModeProbe/PlayModeProbe.cs` | **普通 MonoBehaviour**（非 Editor） | 挂到角色上，Play 时自己在游戏循环里采样；状态表由编辑器预先写进字段，运行时零 Editor 依赖 |
| `Assets/Editor/AddPlayModeProbe.cs` | 编辑器工具 | **批量挂载 / 移除 / 刷新状态表** |

菜单（`Tools/2DModel/运行时采样/`）：

```text
· 给场景里的角色批量挂采样脚本        （扫 root：子树里有 Animator + SkinnedMeshRenderer）
· 给选中的物体挂采样脚本
· 给 prefabs-main 名单里的角色挂采样脚本（按名字匹配场景 root）
· 从场景里移除采样脚本
· 刷新所有采样脚本的状态表            （把 controller 的状态名/hash/层/时长写进组件）
· 批量设置采样选项窗口               （模式 / 步长 / 全量 BakeMesh / 记录时长 → 一次性写进所有组件）
```

组件两种模式：

- `AllStates`：逐状态 `Rebind` + `Play` + `Update(0)` 采样（**会切换动画**，只适合单独跑）；
- `FollowRuntime`：**完全不干扰播放**，按帧记录“当前在播什么 + 各渲染器显隐”，
  持续 `followSeconds` 秒（用于记录玩家实际操作时的动态表现）。

输出同样写到 `info/Data/PlayFrames/`（`<角色>@<Animator>@<状态>.json`，
勾 `bakeMeshes` 时另出 `.playpose.json`），日志在**工程根目录** `play_probe.log`。
在 Inspector 里手动加的组件，面板上有「刷新状态列表」按钮。

每帧记录：所有 Transform 的 local TRS、**每个渲染器的 `activeSelf` /
`activeInHierarchy` / `enabled`**、Sprite 的 worldCorners、当前状态与归一化时间
（可选 `bake` 再写 BakeMesh 前 8 个顶点）。

比对输出会把每一处不一致标上原因：

| 标签 | 含义 |
| --- | --- |
| `ours` | 真值三件套都开着、我们却隐藏了 → **我们这边的问题** |
| `self(Unity SetActive=0)` | Unity 自己把该节点关了 |
| `parent(父链 inactive)` | 父链某层 inactive |
| `renderer(m_Enabled=0)` | 渲染器被禁用（3.15 那类助手贴图） |

#### 8.1.2 通用批量挂 / 卸组件 `Assets/Editor/BatchAttachComponent.cs`

场景里几十个角色（还大多是 disabled 的），手工一个个拖脚本不现实。
`AddPlayModeProbe` 只解决 `PlayModeProbe` 一个组件，所以另有一个**通用**工具：
任意 MonoBehaviour 都能批量挂 / 卸，还能按"筛选组件"反选目标。

菜单：`Tools/2DModel/批量组件/批量挂卸组件窗口`

```text
· 搜索框筛类型（可勾"包含 Unity 自带组件"，默认只列工程脚本）
· 列表每行两个按钮：要挂（设为动作组件） / 筛选（设为目标筛选组件）
· 目标范围：选中物体 / 场景角色根（有 Animator + SkinnedMeshRenderer）/
            场景所有根物体 / 场景所有物体（含子物体、disabled）/
            场景里挂了【筛选组件】的物体
· 批量挂载 / 批量卸载 / 实时预览命中数量
```

要点：

- **只改场景实例**，不写 prefab 资源（`EditorUtility.IsPersistent` 过滤）；
- 全部走 `Undo.AddComponent / Undo.DestroyObjectImmediate`，可 `Ctrl+Z`；
- 默认**跳过已挂过的**（关掉开关可强制重挂）；
- 挂 `PlayModeProbe` 时会自动调 `AddPlayModeProbe.FillStateTable` 填状态表；
- 类型目录扫描 `AppDomain` 程序集，排除 `Unity*` 编辑器类型与编译器生成类；
- 日志与运行时采样共用 `D:\VB\Unity2Spine\info\_logs\play_sample.log`。

> 全量 BakeMesh 与批量挂组件是**两条独立通道**：全量 BakeMesh 决定"采多细"，
> 批量挂组件决定"哪些物体参与采样"。先批量挂 `PlayModeProbe`
> （勾 `bakeMeshes`、限制角色），再进 Play 模式即可。

#### 8.1.3 多角色/多 Animator 会不会互相干扰

先把结论分两层：

**数据层面不干扰。** `BakeMesh` 是每个 `SkinnedMeshRenderer` 用自己的骨骼 +
自己的 `localToWorldMatrix` 算出来的，角色在世界空间重合、重叠渲染，都不会
改变任何顶点数据；我们不截图、不读 framebuffer，所以"画面叠在一起"不影响真值。

**工具层面有三处真实干扰**（都已加防护）：

| 干扰 | 现象 | 防护 |
| --- | --- | --- |
| 一个 Animator 被多个 probe 驱动 | 几十个 probe 同时 `Play`/`Rebind` 同一个 Animator，状态互相覆盖、抢着写同一批文件、编辑器卡死 | `PlayModeProbe.OwnsAnimator()`：同一个 Animator 只让**层级最浅**的 probe 跑，其余跳过并写日志；批量工具"角色根"范围固定只挂根节点 + "同一分支只挂一个"（父级已有则子物体跳过） |
| 一个角色有多个 Animator | `GetComponentInChildren<Animator>` 只返回**第一个**，可能采到副 Animator（例如 babariana 的 `Char_PECS_Babariana_NS1_Bg_Only`） | `PlayModeProbe.animatorPath`（相对角色根）；`FillStateTable` 在多 Animator 时会列出全部并取**状态最多**的当主，把路径写进 `animatorPath`；其余 Animator 需另挂一个 probe 并手填 `animatorPath` |
| 输出文件名撞名 | 命名是 `TopName()@<Animator>@<状态>.json`；角色若被塞进同一个容器下，`TopName()` 会全部变成容器名 | 批量工具的"角色根"按 **Animator 归属**判定（父级子树里有别的 Animator 就说明父级还装着别的角色），不受容器影响；`PlayModeProbe` 追加文件名占用表，撞名时后缀 `__2/__3` 并写日志 |

> 本工程 `Assets/Scenes/save.unity` 实测：20 个场景根 = 19 个角色 + `Main Camera`，
> 4376 个 Transform，20 个 Animator 分属 19 个角色（babariana 占 2 个），
> 1592 个渲染器。每个角色都是**独立场景根**，所以 `TopName()` 天然唯一，
> 撞名那条不会触发；但换场景/加容器时前面的防护仍然生效。

> 另一个"看起来像干扰"的坑：全量 BakeMesh 的体积。20 角色 × 每角色 N 个状态 ×
> 每状态上千帧 × 每帧全量顶点，很容易写出几十 GB。**一定要用
> `bakeChars` / 逐个 probe 的 `animatorPath` 限制范围**，别一次性全开。

#### 8.1.4 运行时组件版的操作清单（"然后直接 Play 是吗？"）

**不能直接 Play。** 场景里默认没有任何 `PlayModeProbe`（本工程 `save.unity` 实测
MonoBehaviour 数为 0），不挂就没有任何东西在采样。正确顺序是：

```text
1. 确认角色根是 ACTIVE
   —— MonoBehaviour 挂在 inactive 的物体上时 Start() 不执行，采样直接不会跑。
   （save.unity 实测：19 个角色根全 ACTIVE，只有内部 215/4376 个物件是 disabled，正常）
2. Tools/2DModel/运行时采样/给场景里的角色批量挂采样脚本
   —— 挂的同时会填状态表；日志里会逐条列出每个角色认到几个状态
3. Tools/2DModel/运行时采样/批量设置采样选项窗口
   —— 模式 / 步长 / 全量 BakeMesh / 输出子目录，一次性写进所有 probe
   —— 建议先把"输出子目录"填个名字（例如 probe），否则会和编辑器采样器的
      info/Data/PlayFrames/<角色>@<Animator>@<状态>.json **同名覆盖**
4. 进 Play，等日志出现"完成 AllStates"（日志：工程根目录 play_probe.log，Console 打 [PlayProbe]）
5. **手动退出 Play** —— 运行时组件版不会自己退出（编辑器驱动版才会）
```

预期现象（别被吓到）：

- `AllStates` 会真的 `Rebind` + `Play`，19 个角色的动画会**同时乱跳**，这是采样本身；
- 所有角色都在 `(0,0,0)`，画面完全重叠，但**不影响顶点真值**（见 8.1.3）；
- 全量 BakeMesh 很慢：每个采样点要对角色下 ~100 个渲染器逐个 `BakeMesh`，
  单状态就可能几十秒。**先只给 1~2 个角色开**，别 19 个一起；
- 采样期间在 `Assets/` 下写文件会触发资源导入，可能有卡顿。

`check_play_visibility.py` 比对时用 `--play-dir` 指到子目录：

```text
python tools\check_play_visibility.py _probe50\<角色> --play-dir "info\Data\PlayFrames\probe" --top 20
```

#### 8.1.5 逐个（串行）导出：`SceneActivationController`

19 个角色全在场景里、还都在 `(0,0,0)`。如果所有 probe 在 `Start()` 里一起跑：
19 个动画同时乱跳、帧率崩、全量 BakeMesh 慢到不可用、日志糊成一团。
所以做了一个挂在 **Camera** 上的调度器，把流程改成**串行**：

```text
【角色 1】激活 → 唤醒它的 probe → 等采样完成 → 关回 inactive
【角色 2】激活 → 唤醒它的 probe → 等采样完成 → 关回 inactive
…
全部跑完 → 把所有场景根的激活状态恢复成"进 Play 之前的样子"
```

文件：`Assets/PlayModeProbe/SceneActivationController.cs`（运行时脚本，能挂到 Camera）

菜单：

```text
Tools/2DModel/运行时采样/给摄像机挂逐个导出控制器
Tools/2DModel/运行时采样/把所有采样脚本设为：等外部唤醒
Tools/2DModel/运行时采样/把所有采样脚本设为：自己跑
```

关键机制：`PlayModeProbe.waitForExternalStart`。控制器在 **Awake**（一定早于所有
`Start()`）里把场景里所有 probe 设成"等外部唤醒"，probe 因此在 `Run()` 里挂起，
只被控制器一个一个放行 —— 这样就不会出现"19 个一起跑"。

主要开关（Inspector）：

| 开关 | 默认 | 说明 |
| --- | --- | --- |
| `gateAllProbes` | 开 | 把场景里所有 probe 改成等外部唤醒 |
| `oneAtATime` | 开 | 同时只让一个角色激活，其余先关掉，跑完恢复原状 |
| `activateDescendants` | 开 | 连角色下面原本 disable 的部件也一起打开 |
| `perTargetTimeoutSeconds` | 600 | 单个角色等待上限，超时跳过继续下一个 |
| `startKey / skipKey / abortKey` | None | 手动开始 / 跳过当前 / 中止 |

> **`activateDescendants` 的取舍**：probe 采样本身**不需要**部件是打开的
> （`BakeMesh` / 读网格都与激活状态无关）。强行打开的作用是让"渲染/截图类"
> 导出能看到所有部件，代价是这些部件的 `activeSelf` 真值会被改写 ——
> 有 `m_IsActive` 曲线的部件在采样时仍会被曲线覆盖回正确状态，但没有曲线、
> 本来就该关着的部件会被当成"显示的"采进数据。只想要干净真值就把它关掉。

#### 8.1.6 Mesh 的 Read/Write 关闭导致读顶点报错

```
Not allowed to access vertices on mesh 'CS_parts_gun' (isReadable is false;
Read/Write must be enabled in import settings)
```

`Mesh.vertices / .uv / .triangles` 只在 Mesh **导入设置勾了 Read/Write Enabled**
时才可读；`CS_parts_gun` 这类模型没勾。现在两条采样路径都做了降级处理：

- 先查 `mesh.isReadable`，不可读就**只记** `readable:false` + `vertexCount:0` +
  `localToWorld` + 排序 + 显隐三件套，位置/UV/三角形留空；
- 同一个 Mesh 只在日志里点名**一次**（`WarnOnce`），不会刷屏；
- `SkinnedMeshRenderer.BakeMesh` 也包了 try/catch，同样降级。

要拿真实顶点，二选一：

1. 用 `tools/fix_mesh_readable.py` 打开（推荐，一次到位）：
   它只改"场景里 MeshFilter 真正引用到、且 `m_IsReadable: 0`"的那些 Mesh asset，
   不会去动全工程一万多个网格。

   ```text
   python tools\fix_mesh_readable.py            # 只扫描并打印（dry-run）
   python tools\fix_mesh_readable.py --apply    # 真改；回 Unity 自动 Reimport
   ```

   `save.unity` 实测：**MeshFilter 只有 1 个**，引用的就是
   `rawLo/constantias2/constantias2_normal/Mesh/CS_parts_gun.asset`（一个四边形），
   已改为 `m_IsReadable: 1`。也就是说那 818 条"读不到顶点"其实全是这一个
   四边形在逐帧重复。
2. 保持现状，静态网格只参与"显隐 + 变换"比对，不参与逐顶点比对。

#### 8.1.7 补跑流程（只补指定角色）

`SceneActivationController` 有 `onlyNames`（逗号分隔的子串），留空=全部。
补跑两个角色不用重跑 19 个：

```text
1. 回 Unity，等编译 + CS_parts_gun 的 Reimport 完成
2. 菜单 Tools/2DModel/运行时采样/给多 Animator 的角色自动补挂 probe
   （给"没被任何 probe 覆盖"的 Animator 补挂，并自动填好 animatorPath；
     日志会写明补了哪个 Animator、宿主是哪个物体）
3. 场景根 active 状态不用管（控制器会自己开关）
4. 选中 Main Camera 上的 SceneActivationController：
   onlyNames = babariana,constantias2_normal
5. 进 Play，等日志出现"全部完成"，再手动退出 Play
```

补 babariana 第二个 Animator 之后，产物会多出
`babariana_skin1@Char_PECS_Babariana_NS1_Bg_Only@<状态>.json` 这一族文件，
不会和主 Animator 的文件重名。

全量重跑：把 `onlyNames` 清空再进 Play（19 个角色约 7 分钟，全量 BakeMesh ≈ 5.5 GB）。

#### 8.1.8 跳帧采样会把 `m_IsActive` 粘住（真值不可信的真凶）

> **2026-09-14 更正（本节因果解释作废，现象与数字保留）**：
> 反汇编 + 同版本 Unity（2022.3.3f1c1）实测证明，"互补的眼/眉同时 ON"**不是**
> 跳帧采样造成的 —— 在隔离工程里 `Seek`（逐点 `Play+Update(0)`）与
> `NaturalStep`（连续推进）**结果完全相同**。真正的原因是**运行时的判据**：
> `m_IsActive` 按 `|v| > 1e-3` 判"显示"，而工程里 6191/6505 条 `m_IsActive` 是
> **插值曲线**（slope=0），段内值一离开 0 就算显示，于是两个互补部件会长时间同时 ON。
> 也就是说 **Play 真值是可信的**（它就是运行时行为），旧口径下"真值与 clip 对不上"
> 是**两边判据不同**。转换器已按运行时语义矫正（见 3.22 与
> [`Unity运行时逆向报告.md`](Unity运行时逆向报告.md)）：
> banshee 四段动画与真值的不一致格子 **1723 → 1**。
> 下面保留原始记录备查。

做完 19 个角色的 Play 真值之后，用它去核对显隐，报了 13 个角色不一致。查下来
**是采样方式错了，不是转换器错了**。

判据：banshee 的 breast 里，clip 中 `parts_Eye_normal` 与 `parts_Eye_Smile` 是
**互补对**（`(0,0)(0.3,1)(0.683,0)(5.683,1)(6.867,0)(8,0)` 这种，永不同时显示）。
但采出来的真值让它们 **202 帧里 130 帧同时 ON**；编辑器 AnimationMode 那条通道
（PoseFrames）也是同样的错法 —— 两条独立通道一起错，说明是"读动画"的方式有问题。

根因：旧的 `AllStates` 是**逐点跳帧**——

```text
animator.Play(hash, layer, t / dur);   // 每个采样点都 Play 一次并给定归一化时间
animator.Update(0f);
```

Unity 的 `GameObject.SetActive` 是**离散**属性，靠状态机**连续推进**时跨过关键帧
来写入；跳帧取值时它只会被"打开"，之后一直保持 ON —— 表现就是真值里 ON 区段
被拉长、off 区段被压成一两帧。连续曲线（Transform）不受影响，所以位移/缩放
的比对一直是准的，只有显隐错。

**修法**：`PlayModeProbe.advance` 新增 `NaturalStep`（默认）——

```text
animator.Play(hash, layer, 0f);
animator.Update(0f);
for (...) { 记录; animator.Update(step); }     // 连续推进，中间不让出帧
```

要点：推进过程中**不能 `yield return`** —— 让出的那一帧 Unity 自己也会 Update 这个
Animator，连续时间就被打断。所以 `yieldEvery` 默认 0（不让出，整个状态在一帧内跑完）。
`BakeMesh` 打开时单状态可能卡住几秒到几十秒，日志会提示；实在受不了再临时设 25。
旧的 `Seek` 行为保留下来做 A/B，产物 JSON 头部会写 `"advance"` 字段区分。

**新增离线校验器** `tools/check_clip_visibility.py`：直接拿 clip 的 `m_IsActive`
关键帧当基准查产物，不用进 Unity。它比真值可靠（真值只适合查"Unity 里没被动画管、
但被父链或渲染器开关"的显隐）。踩过并修掉的坑：

- `*.playpose.json` 被当成真值文件读进去（它没有 `state` 字段）；
- Unity 序列化的 `path:` **折行续写**不拼接，会把 `parts_xxx` 与 `parts_xxx (1)`
  折叠成同一个节点（转换器早就处理了，校验器必须一致）；
- clip 里连续同值的冗余关键帧（转换器会合并，这是合理优化，不能算差异）；
- 两边都是"恒定值"时去比关键帧时刻（时间无意义）；
- 同一个绑定出现多条曲线时取哪条 —— 取**后者**（和转换器和 Unity 求值顺序一致）。

#### 8.1.9 完整运行流程（重采显隐真值）

默认输出子目录已改成 **`probe_step`**（`PlayModeProbe.outSubDir`），
不会再和旧的 seek 采样结果（直接躺在 `PlayFrames/` 下的 5.8 GB）互相覆盖。

```text
① 回 Unity，等编译完成

② 挂采样脚本（场景里已有的话这步会刷新，不会重复挂）
   Tools/2DModel/运行时采样/给场景里的角色批量挂采样脚本
   —— 多 Animator 的角色（babariana）再补一条：
   Tools/2DModel/运行时采样/给多 Animator 的角色自动补挂 probe

③ 给摄像机挂调度器（逐个角色跑，不一起炸）
   Tools/2DModel/运行时采样/给摄像机挂逐个导出控制器

④ 批量设采样选项（会写进场景里所有 probe）
   Tools/2DModel/运行时采样/批量设置采样选项窗口
       推进方式 = NaturalStep        ← 关键，显隐正确性靠它
       每采 N 点让出一帧 = 0          ← 关键，让出会让时间轴错位
       采样步长 = 0.05
       写全量 BakeMesh = 勾（要逐顶点比对时）
       输出子目录 = probe_step
       模式 = AllStates
   → 点「应用到场景里所有采样脚本」

⑤ 进 Play 模式，自动逐个角色跑
   看日志：工程根目录 play_probe.log（Console 里打 [PlayProbe]）
   等出现「全部完成」，再手动退出 Play（运行时组件版不会自己退）

⑥ 校验（离线，不用 Unity）
   python tools\check_clip_visibility.py --all-in-probe50
   —— 拿 clip 关键帧当基准查产物；这个才是"转换器有没有漏"的判据

   python tools\check_play_visibility.py _probe50\<角色>
   —— 拿 Play 真值查；解析器会自动往子目录找 probe_step
   （只对"Unity 里没被动画管、但被父链/渲染器开关"的显隐可信）
```

只想重跑某几个角色：在 `SceneActivationController` 上填
`onlyNames = babariana,constantias2_normal`，第 ⑤ 步就只跑这两个。

时间参考：19 个角色、0.05 步长、全量 BakeMesh ≈ 7 分钟 / 5.5 GB；
不勾 BakeMesh 只要几十秒。

## 9. 产物与命名

```text
samples/2DModel/<角色>/static_spine/        # A. 直通 alpha（加色区预乘）
samples/2DModel/<角色>/static_spine_pma/    # B. 全局预乘（Unity 推荐）
  ├── <角色>_static[_pma].json / .atlas / *_0.png
  ├── <角色>_static[_pma].skel     # 可选：Spine 3.8 二进制（--skel；三主力样例已带）
  ├── .config.json           # 查看器配置（见第 9.1 节）
  ├── _static_info.json      # 部件清单（名称/类型/混合/颜色/排序/来源节点）
  ├── README.md              # 本次导出的摘要 + 校验命令
  ├── _calib/                # 校准证据：对照图 + 报告
  └── _face_check/           # 单脸 vision 校验结果
```

### 9.1 `.config.json`（查看器直接打开）

每次导出都会在产物目录写一份 `.config.json`，schema 与本项目查看器
（Live2D 编辑器同款）一致，打开该目录即可直接查看：

```json
{
  "type": 9,                       // 9 = Spine
  "controllers": { "eye_blink": {...}, "lip_sync": {...}, ... },
  "options": { "scale_factor": 5.4, "tex_type": 0,
               "edge_padding": false, "shader_type": 1 },
  "skeleton": "<角色>_static.json",
  "atlases": [ { "atlas": "<角色>_static.atlas",
                 "tex_names": ["<角色>_static_0"],
                 "textures": ["<角色>_static_0.png"] } ]
}
```

- `atlases[].tex_names / textures` 会按实际页数列出（audrey 是 2 页）；
- `options.scale_factor` 由骨架跨度估算（`100 / max(宽,高)`，夹在
  0.01~10000），只影响打开时的初始缩放；
- **再导出时不会覆盖你在查看器里调好的参数**：`write_viewer_config(merge=True)`
  只更新 `skeleton` 与 `atlases`，保留已有的 `controllers` / `options`；
- 已有老产物可用 `tools/refresh_viewer_config.py` 批量补写/刷新：

```bat
python tools\refresh_viewer_config.py samples            :: 保留已有设置，只更新引用
python tools\refresh_viewer_config.py samples --force    :: 完全重写为默认值
```

### 9.2 坐标单位：默认**源图像素**（1 单位 = 1 像素）

Unity 里三个角色的世界尺度差了约 8 倍（贴图都是 ~2048²，但 aeda 高 18.5 单位、
黑莉莉丝只有 2.44 单位），按"单位"取景时后者会显得特别小；按 1:1 渲染也会因为
缩放带来重采样。因此导出**默认使用像素单位**：

| 角色 | px/unit（自动估算） | 角色跨度 | 换算后 |
| --- | --- | --- | --- |
| aeda | 102.8 | 18.47 单位 | **1899 px**（贴图 2048） |
| blacklilith | 728.2 | 2.44 单位 | **1775 px** |
| audrey | 627.8 | 2.88 单位 | **1808 px** |

- `px/unit` 由网格部件的 "UV 像素范围 ÷ 世界范围" 中位数估算
  （`pixels_per_unit`；精灵部件自带局部缩放，不用它）；
- 三个角色的导出跨度都在 1800~1900 px，与源贴图同量级——打开就"不小"了；
- **按源图尺寸渲染就是 1:1**（2048² 画布、1 单位=1 像素），不会有下采样/插值；
- `_static_info.json` 里记录 `units: "px"`、`unitScale`、`sourceSizes`，
  校准工具据此把 Unity 相机/真值换算到本坐标空间（无需手工改命令）；
- `.config.json` 的 `options.scale_factor = 1.0`（1:1）。想让角色占满画布可自行
  放大；旧行为可用 `--units world` 导出。

渲染尺寸约定（不再用 768 之类的小尺寸预览）：

| 工具 | 默认尺寸 |
| --- | --- |
| `tools/face_check.py` | 源贴图原尺寸（读取 `_static_info.json` 的 `sourceSizes`） |
| `tools/calib_sprites.py` / `calib_full.py` | 与 Unity 参考帧同尺寸（本来就是） |
| Viewer 离线渲染 | 建议 `--size <源贴图尺寸>`，例如 aeda 用 `2048x2048` |

- aeda：37 部件 = 13 蒙皮 + 16 sprite + 8 static，其中 15 个加色光晕；
- blacklilith：34 部件（14 蒙皮 + 20 sprite，无加色）；
- audrey：24 部件（23 蒙皮 + 1 全身 sprite；`face` 子节点磁盘资源
  `m_Sprite=0`，但 body sprite 与 `parts_Head_Units_013` 已覆盖面部）。

### 9.3 二进制产物 `.skel`（Spine 3.8，`--skel`）

`.json` 与 `.skel` 是**同一份数据的两种容器**：写出器直接吃内存里的
skeleton dict，先写 `.json`，再把同一份 dict 写成二进制。产物目录里两者并存，
`.atlas` / `.png` 共用。

怎么出：

| 场景 | 做法 |
| --- | --- |
| 导出时就要 | `--skel`（GUI：A 面板勾"同时输出 .skel"） |
| 事后给已有产物补 | `python -m ngui2spine.spine38_binary_writer <角色>_static.json`（GUI："补写 .skel"按钮） |
| 多 Spine 合并 | `merge_existing_spine --skel`，写出顺序 `--skel-writer auto\|python\|exe`（默认 auto＝原生写出器，失败才退转换器） |

实现与依据：

- `ngui2spine/spine38_binary_writer.py` —— 依据
  [SpineSkeletonDataConverter](https://github.com/wang606/SpineSkeletonDataConverter)
  的 `src/SkeletonData38BinaryWriter.cpp`，并与官方 spine-runtimes 3.8
  （spine-csharp `SkeletonBinary.cs` / `SkeletonJson.cs`）逐条对齐：
  varint 编码、字符串表（stringRef 索引）、`nonessential`（fps / images /
  audio / 骨骼颜色 / mesh 的 edges+width+height）、mesh 的 `hull`（= JSON
  顶点个数）、曲线（linear / stepped / bezier 四控制点）、deform 帧的
  `(count, offset, floats)` 全部同构；attachment type 0~6、骨骼 0~3、
  槽位 0~2、IK / transform / path / drawOrder / events 也都覆盖。
- 写出顺序默认与参考实现一致（皮肤附件、动画内条目按名字排序；骨骼 / 插槽 /
  动画**列表**保持 JSON 顺序），因此与 `third_party\SpineSkeletonDataConverter.exe`
  的输出**逐字节一致**；`--keep-json-order` / `--sort-animations` 可改。
- 体积约为 JSON 的 1/5（audrey 18.4MB→3.4MB、atalanta_skin1 62.8MB→11.8MB，
  都是 0.18~0.19 倍；aeda 类 600MB 级 JSON 同理）；加载也更快——同一角色同一帧离线渲染
  （1024²，热缓存）`.json` 19.7s / `.skel` 10.9s。

验证（2026-09-12，命令见下）：

| 用例 | 结果 |
| --- | --- |
| 三主力样例（aeda / blacklilith / audrey）+ 安洁利卡（B 路线）+ 法兰·伊斯丽洛克（合并）+ atalanta_skin1 | 与转换器输出**逐字节一致** 7/7 |
| atalanta_skin1（62.8MB→11.8MB） | 生成 + 读回 + 逐字节比对全过，约 16s |
| audrey `.skel` vs `.json`，离线 Render（spine 运行时，1024²） | **逐像素一致**：差异像素 0 / 1048576 |
| 读回校验（写→`spine38_binary.py` 读回→逐字段比对） | 骨骼 1 / 插槽 23 / 附件 23 / 动画 3 全部一致 |

```bat
:: 校验：由 .json 生成 .skel + 读回比对 + 与第三方转换器逐字节比对
python tools\check_skel.py samples\2DModel\audrey\static_spine --convert --ref-exe
```

两个坑（都已处理，别再踩）：

1. **`hull` 不是一半**：3.8 二进制里的 mesh `hull` 就是 JSON 的顶点个数
   （spine-csharp `SkeletonBinary.cs` 读时 `<<1`、`SkeletonJson.cs` 读 JSON
   时 `*2`）。本项目读回器原来多右移了一位，直接读 `.skel` 会把 hull 砍半
   （法兰合并样本里 120 个 mesh 都偏小一半，`skin147_eye1_2` 应为 9 却是 4），
   2026-09-12 已修，并与游戏里原始 Spine 编辑器导出的
   `skin133.skel.bytes`（hull 57/14/16/5）逐个对齐。
2. **第三方 exe 不能反着用**：它的 `skel→json` 在 `nonessential=true` 且
   images/audio 为空时会崩（`Bad optional access`）——我们的产物正是这种
   （fps=60）。读回请用本项目 `spine38_binary.py`（详见 `已知问题.md`）。

## 10. 遗留事项

1. 本项目 Viewer 一次 draw call 只有一个混合状态，预览加色光晕会偏暗/偏实；
   导出的 Spine 数据本身正确（像素级验证用 `tools/calib_sprites.py`）；
2. blacklilith 的球体光效由第二个 Animator（`star_deco`）驱动，需要时加
   `--secondary-anim` 一并采样；
3. blacklilith 参考图中的背景/十字浮游物等特效层不在静态导出范围内；
4. 输出尺寸即源贴图尺寸（aeda 2048²、blacklilith 2028x1915、
   audrey 1475x1891），部件不做额外缩放；
5. ~~两个 Animator 共用同一个 Controller 时第二个被丢掉~~ —— 已修（3.13）。
   babariana 那 64 条“path 对不上”也确认是**检查器误报**（Unity 里那些曲线同样空转），
   不是导出缺陷。
6. C 档只剩 3 个（见 3.21）：都是单个小部件，根因在 Unity 侧数据/姿势
   （bindpose 与骨骼数不一致、或该部件在 clip 里没有曲线），最大
   `banshee_skin1 0.281`。

## 11. 常用命令

```bat
:: 导出 + 几何自检 + 静态检查 + 单脸 vision 校验
python -m ngui2spine.static_prefab_spine ^
  <prefab> samples\2DModel\<角色>\static_spine ^
  --scene <save.unity> --calib            :: 默认 --units px（1 单位=1 像素）

:: B. 全局预乘（推荐给 spine-unity）
python -m ngui2spine.static_prefab_spine ^
  <prefab> samples\2DModel\<角色>\static_spine_pma ^
  --scene <save.unity> --pma

:: 需要旧的 Unity 世界单位坐标时
python -m ngui2spine.static_prefab_spine <prefab> <out> --scene <save.unity> --units world

:: 同时输出 Spine 3.8 二进制骨架（.skel，见 9.3）
python -m ngui2spine.static_prefab_spine <prefab> <out> --scene <save.unity> --skel
python -m ngui2spine.spine38_binary_writer <out>\<角色>_static.json      :: 事后补写
python tools\check_skel.py <out> --convert --ref-exe                     :: 读回 + 与转换器逐字节比对

:: 校准 / 检查
python tools\static_check.py <prefab> --scene <save.unity> --spine-dir <spine目录>
python tools\calib_geo.py --prefab <prefab> --scene <save.unity> --clip lobby ^
  --only-spine-dir --spine-dir <spine目录> --times 0,1.5,2,6.5,9.3,12,16
:: 单脸朝向（vision，推荐）
python tools\face_check.py <spine目录>
:: 光晕/颜色层（参考图用 Unity 的 sprites 层截图；--ref 必须显式给）
python tools\calib_sprites.py <spine目录> ^
  --ref <Assets>\Data\Frames\<角色>_normal\03_sprites_dark.png ^
  --cam <Assets>\Data\Frames\<角色>_normal\03_sprites_dark_cam.txt ^
  --bg 10,10,10,255 --time 0
:: 整角色轮廓（反推相机，只需参考图）
python tools\calib_full.py <spine目录> ^
  --ref <Assets>\Data\Frames\<角色>_normal\00_full.png --time 0
:: 旧 probe_face 单脸对比（历史脚本，参考图是固定的）
python tools\calib_face.py <spine目录> --times 0,8,16

:: 离线渲染（Viewer）
D:\VB\Viewer\Render\.venv\Scripts\python.exe D:\VB\Viewer\Render\render_offline.py ^
  <spine目录> --only spine --size <WxH> --background 255,255,255,255 --output <out>
```

### 11.1 GUI（`python gui.py`）

A 路线面板（置顶）把上面的命令都做成了按钮，参数与命令行一一对应：

| 界面控件 | 对应命令 |
| --- | --- |
| Assets 目录 / 角色 prefab / 场景 / 输出根目录 | `--assets` / 位置参数 / `--scene` / 输出目录 |
| clip / dt / 单位 | `--clip` / `--dt` / `--units px\|world` |
| 全部 Animator / 只导 Animator 子树 / 几何自检 / 单脸 vision 校验 | `--secondary-anim` / `--animated-only` / `--calib` / `--no-face-check` |
| 同时输出 .skel / 补写 .skel | `--skel`（见 9.3）/ 给已有 `<角色>_static[_pma].json` 生成同名 `.skel` |
| 导出当前角色 / 导出三个主力角色 / 导出+PMA / 三主力+PMA | 跑 `static_prefab_spine`，产物落 `<输出根>\<角色>\static_spine[_pma]` |
| 几何(逐顶点) / 单脸 / 光晕层 / 整角色轮廓 | `calib_geo.py` / `face_check.py` / `calib_sprites.py` / `calib_full.py` |
| 静态检查 / 静态检查(3主力) / 刷新 .config.json / 补写 .skel / 离线渲染(1:1) | `static_check.py` / `refresh_viewer_config.py` / `spine38_binary_writer` / `render_offline.py` |

要点：

- 产物目录名会自动把 prefab 名去掉 `_normal`（`aeda_normal` → `aeda`），
  与既有产物目录一致；找不到 `static_spine` 时校准/检查会回退到 `static_spine_pma`；
- "导出三个主力角色"只跑 aeda / blacklilith / audrey：这个 Assets 下有 1900+ 个
  prefab，全量导出会跑飞；
- 光晕层 / 整角色轮廓的参考图直接取 Unity 侧
  `info\Data\Frames\<角色>_normal\03_sprites_dark.png`、`00_full.png`
  （脚本默认值是旧的 `probe_face`，所以命令行手跑时要显式传 `--ref`）；
- 自检：`python tools\gui_selftest.py`（构建界面 + 干跑所有按钮 + 校验命令）。

## 12. 相关文件

- 规则：`D:\VB\询问前规则.md`
- 转换：`ngui2spine/static_prefab_spine.py`、`unity_mesh.py`、
  `unity_anim2d.py`、`convert_2dmodel.py`、`unity_2dmodel.py`
- 二进制：`ngui2spine/spine38_binary_writer.py`（写 `.skel`）、
  `ngui2spine/spine38_binary.py`（读 `.skel`）、`tools/check_skel.py`（校验）
- 二进制依据（只读参考副本）：`_reference/SpineSkeletonDataConverter/`
  （`src/SkeletonData38BinaryWriter.cpp`、官方 3.8 `SkeletonBinary.cpp` /
  `SkeletonJson.cpp`）、`third_party/SpineSkeletonDataConverter.exe`（对拍基线）
- 工具：`tools/`（见第 8 节），GUI 自检 `tools/gui_selftest.py`
- 校准真值：`samples/Data/`（SceneT0 副本）、
  `D:\VB\Unity2Spine\info\Data\`（PoseFrames/SceneLayout）
- Unity 侧脚本：`Assets\Editor\{TwoDModelCalibExport,CalibTargets,ExportSelected,
  ExportSelectedInfo,StaticBindMetaExporter,TwoDModelSceneLayoutExporter}.cs`
- 文档：本文件、`README.md`（docs 索引）、`报告与校验.md`（三主力 + 50 角色
  + clip 属性扫描 + aeda 记录 + 历史快照）、`其他路线与历史.md`；
  数据在 `docs/data/`
