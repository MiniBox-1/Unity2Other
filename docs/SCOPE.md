# 适用范围：这些结论是从哪个 Unity 项目研究出来的

本目录的结论不是教科书式的 Unity 文档，而是**从两个真实的 Unity 2D 手游工程反推**出来的。
知道研究对象长什么样，才能判断哪些结论可以直接搬到你的项目、哪些需要重新验证。

## 1. 研究对象

| 项目 | 用途 | Unity 版本 | 规模 |
| --- | --- | --- | --- |
| **Lo 工程**（大厅 2D 角色） | 骨骼动画角色 | `2021.3.45f2c1` | 157 个 `*.uAnim.prefab`、757 个 `*.anim`、216 个 `.controller`、447 个 `.mat`、1915 张 PNG |
| **BdOne 工程**（NGUI 角色） | 另一种角色实现 | `2021.3.45f2c1` | NGUI 层级 + 区域网格 |
| **静态立绘**（同 Lo 工程内） | 静态 `.Lihui.prefab` | `2021.3.45f2c1` | 1150 个 `*.Lihui.prefab` |

两个工程都是 **Editor 版本 2021.3.45f2c1（8058fe21db2f）**，渲染管线是 **Built-in**（不是 URP/HDRP），
没有 SRP Batcher、没有 Shader Graph。

## 2. 工程特征（决定了研究到的边界）

- **骨架**：Puppet2D 工具链 —— `Puppet2D_Bone` / `Puppet2D_IKHandle` / `Puppet2D_HiddenBone` /
  `Puppet2D_GlobalControl` / `Puppet2D_FFDLineDisplay`；骨骼层级是普通 `Transform`，没有用 Unity 的 2D Animation 包。
- **部件**：三种渲染器混用 —— `SpriteRenderer`（大头）、`SkinnedMeshRenderer`（骨骼蒙皮）、`MeshRenderer`（刚性网格）。
- **材质**：以 `Sprites/Default` 为主，另有 `Legacy Shaders/Particles/{Additive, Multiply, Alpha Blended}`
  与 `Mobile/Particles/Additive` 五类特效材质（341 个特效部件分布在 23 个角色里）。
- **贴图**：图集页（1~11 页/角色），PNG，直通 alpha。
- **动画**：Animator + AnimationClip（757 个），曲线是 Hermite，欧拉顺序 ZXY；
  部分角色用 Animator **Additive 层**；还有 `m_IsActive` / `m_Enabled` 的显隐曲线。
- **显隐与排序**：运行时由脚本（Puppet2D 全局控制、游戏侧 MonoBehaviour）+ 动画共同决定，
  且 `Renderer.bounds` 是膨胀过的剔除盒 —— 所以**不能**用 prefab 的静态字段推断最终画面。
- **UI 层**：BdOne 用 NGUI（`UISprite`/`UITexture`），不是 UGUI Canvas。

## 3. 结论的适用范围

### 可以直接复用（Unity 通用机制）

- `m_IsActive` / `m_Enabled` 的**运行时**语义、以及脚本/动画会在 `Awake` 后改写它们；
- `Renderer.bounds` 是剔除盒、不是真实包围盒；
- 排序是多级决策：`sortingLayer` → `sortingOrder` → renderQueue → SortingGroup tie-break；
- PPtr（`m_Sprite`/`m_Material`/`m_Mesh`）换图/换材质是**阶跃**语义；
- 动画曲线 Hermite 插值 + ZXY 欧拉；Animator 层/Additive 的混合方式；
- BlendShape「先形变、后蒙皮」；
- 4 骨蒙皮与 Spine 3.8 加权顶点格式的对应关系；
- Sprite 的 Tight mesh（按不透明区域裁剪）与 pivot/PPU 换算；
- LBS 公式 `Σ w_i (bone.localToWorldMatrix * bindposes[i]) * v`（与 Unity 逐顶点结果一致，已实测）。

### 依赖本项目约定（换项目要重新验证）

- **Puppet2D 的命名与层级**（`hiddenBone_*`、`*_CTRL`、`Global_CTRL` 组）；
- **`*.uAnim.prefab` / `*.Lihui.prefab` 的命名与结构**；
- **UV 朝向约定**：本工程的 Sprite 自建四边形是左上原点、Mesh/蒙皮是 Unity 左下原点，
  所以转换时「只翻 Sprite」——别的项目如果图集是外部工具导出的，这条要重测；
- **材质 shader 的 fileID 常量表**（`Unity2Spine` 那份 `(fileID, guid) → shader 名` 映射来自本项目用到的内置 shader）；
- **特效件可直接跳过的判断**（moc3 v1 无混合模式）——别的项目如果要保留发光，需要走烘焙或换格式。

## 4. 未覆盖 / 不能保证的情形

- URP / HDRP、Shader Graph、SRP Batcher 的自定义 shader；
- Unity 2D Animation 包（Sprite Skin / IK）路线；
- UGUI Canvas 里的角色（本工程用 NGUI）；
- 3D 角色 / 透视相机 / 非正交渲染；
- 运行时动态生成网格、GPU 蒙皮（`SkinnedMeshRenderer.GPU skinning`）；
- 多相机分层渲染、后处理（Bloom 等）对最终画面的影响。

## 5. 怎么在自己的项目上复核

1. 用 `unity_*.cs` 系列脚本（见 `work/live2d/tools`、`work/spine/spine/**/unity_editor_scripts`）
   在 Editor 里逐部件 dump：`activeSelf` / `enabled` / `sortingLayer` / `sortingOrder` / 逐顶点世界包围盒；
2. 用同一时刻的**截图**与 dump 对齐，避免「以为的可见性」和「实际渲染」不一致；
3. 任何「静态字段 → 最终画面」的推断，都要用一次运行时 dump 验证；
4. 换项目时优先重测三条：**UV 朝向**、**可见性判定**、**排序规则**。

> 一句话：**通用机制可以照搬，工程约定必须重测。**
