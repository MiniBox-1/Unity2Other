# BdOne（NGUI 动态立绘）→ Spine：交接与后续

更新：2026-10-15　｜　**接手这条线先读这份**，细节在
[`BdOne_NGUI_转化.md`](BdOne_NGUI_转化.md)，本轮摘要见
[`../更新摘要_20261014.md`](../更新摘要_20261014.md)。

---

## 0. 三十秒上手

```powershell
cd D:\VB\Unity2Spine; $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"

# 1) 全量转换（15 角色 34 服装，约 65 s，内存 < 1 GB）
python tools\convert_bdone.py --out _bdone_spine

# 2) 与 Unity 真值逐帧对账（期望：34 个产物 0 个需要看）
python _scratch\bdone_check_v2.py _bdone_spine --bad 0.05 `
  --tsv _bdone_spine\_verify_vs_unity.tsv

# 3) 结构自检 + .skel 读回（期望 36/36、36/36）
python -c "import sys;sys.path.insert(0,'src');from unity2spine.validate.validate_spine import validate_tree;print(validate_tree(r'_bdone_spine'))"

# 4) 看图（离线渲染，一次一个进程；渲染器在 Viewer\Render\v4）
& 'D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe' tools\rt_frames.py `
  '_bdone_spine\阿波罗\阿波罗_00_协助' 'Helper154_1' --out _scratch\_bdone_frames --times 0.5 --size 800

# 5) 真值重导（要独占 Unity，先确认没有别的 Unity 开着 BdOne）
& 'D:\Unity\Editor\2021.3.45f2c1\Editor\Unity.exe' -batchmode `
  -projectPath 'D:\VB\Search\BdOne' -executeMethod BdTruthExport.ExportAll `
  -bdOut 'D:\VB\Unity2Spine\_bdone_truth' -bdStep 0.05 `
  -logFile 'D:\VB\Unity2Spine\_scratch\bd_truth_all.log'
```

---

## 1. 现状（一句话）

**BdOne 里"基于 Unity 的动画"已经全量转完并验完**：NGUI `UISprite` + Legacy
`AnimationClip` 的 15 个角色 / **34 个服装** → 34 个 Spine 3.8 骨架；
另外 2 个本来就是 Spine 的角色（法兰、伊斯丽洛克）用多 Spine 合并路线导出到同一目录，
合计 **36 个产物**，与 Unity 真值逐帧对账、结构与 `.skel` 读回全绿。

| 位置 | 内容 | 规模 |
| --- | --- | --- |
| `_bdone_spine\` | **交付产物**（17 个角色目录 / 221 文件） | 65.6 MB（`.skel` 33–279 KB，中位 88 KB；JSON 合计 12.3 MB） |
| `_bdone_truth\` | Unity 真值（每个服装一个 JSON，逐帧 TRS + `drawingDimensions` + region 元数据） | 34 个文件，13.2 MB |
| `src/unity2spine/ngui/bdone_spine.py` | 转换核心（本轮重写的实现） | — |
| `tools/convert_bdone.py` | 全量批量入口 + README/汇总生成 | — |
| `BdOne\Assets\Editor\BdTruthExport.cs` | Unity 侧真值导出（batchmode 可跑），副本在 `tools\unity_validation\` | — |
| `_scratch\bdone_check_v2.py` | 真值对账脚本（TRS/矩形/显隐/颜色 四项） | — |

---

## 2. 本轮完成清单

**转换**：34 个服装（rotate 2455 / translate 240 / scale 30 / attachment 105 /
color 84 条时间线）+ 2 个合并产物；缺件 11 个（见 §4 第 6 条，已逐件确认
Unity 自己也画不出来）。

**修掉的 4 个转换器硬伤**（都是拿真值对出来的，细节见
[`BdOne_NGUI_转化.md`](BdOne_NGUI_转化.md) §1）：

1. 图集页取"同目录第一张 png" → 改走 `UIAtlas.asset → mMaterial → m_Texture`；
2. 部件矩形与 NGUI `UISprite.drawingDimensions` 不一致（奇数尺寸补 1 像素、`pivot`）→
   按 NGUI 源码重写 `sprite_quad()`；
3. 只读 `m_RotationCurves`、漏 `m_EulerCurves`（37/42 个 clip 带它，实测 20+ 件冻结）→
   解析欧拉曲线，按 `Quaternion.Euler`(ZXY) 转角度；
4. `animations[x].slots` 写成 4.x 的"套皮肤名"形状 + 空槽位 `default` 让 `.skel`
   写出器报错 → 改成 3.8 的**扁平**写法、空则不写。

**新加的真值闭环**：`BdTruthExport.cs`（batchmode 一条命令）+ `bdone_check_v2.py`
（四项对账）。**以后改转换器，验收就是重跑这两条**。

**顺带修的工具**（本来就有病）：

* `validate\merge_existing_spine.py`：`from . import spine38_binary` → `..spine`（库化时漏改，
  direct 模式一直 ImportError）；
* `validate\validate_spine.py`：时间线缺 `time` 不再崩；跳过 `.config.json` /
  `_*.json` / `*_merge_info.json` 假失败；mesh 顶点判据支持 3.8 的**扁平加权**编码；
* `ngui\convert_chr.py` 变成薄壳（GUI / `run_cli.py` 与新实现同源）；
* `ngui_model` 的 UISprite 记录补 `pivot / m_Enabled / mDrawRegion`；
* `ngui_anim.parse_clip` 增加 `m_EulerCurves`（**A 路线不受影响**，它不用这个解析器）。

---

## 3. 口径与铁律（改动前必须守）

1. **单位**：NGUI 虚拟像素（1 单位 = 1 像素），Y 向上、不翻转；`scale_factor`
   由转换器算进 `.config.json`；
2. **`.json` 的槽位时间线是 Spine 3.8 的扁平写法** `animations[x].slots.<槽位>`；
   写成 4.x 的"套皮肤名"3.8 读不了（这条踩过，别再改回去）；
3. **部件矩形**只有 `sprite_quad()` 一个出处，必须与 NGUI `UISprite.drawingDimensions`
   逐条对应（含 `mType`/`mFlip`/pivot/奇数补 1 像素）；NGUI 版本若换过要重核；
4. **显隐** = 自身与所有祖先 `m_IsActive` 的与、且 `UISprite.m_Enabled` 为真；
5. **颜色**单独用 0.01 s 细栅格 + 曲线自己的关键帧时刻（0.05 s 会让快速淡入淡出
   差 0.15）；
6. **查不到 region 的件**：跳过并记进 `_bdone_info.json` 的 `excludedParts`。
   这 11 件（`npc256_arm2_4`、`npc258_cape3_200/cape4_1`、`npc_eff3`、`skin105_eff1`、
   `skin80_Fhair3_3/4/5`、`skin80_Fhair4/5`、`skin80_acc1`）在 Unity 真值里
   `hasRegion` 同样为 false ⇒ **跳过是对的，不是丢件**；判据永远是
   "真值有 region、我们却没槽位"才算错（当前 0）；
7. **末帧口径**：真值在 `t = clip.length` 会因 `m_LoopTime` 绕回 0，对账脚本对末帧
   额外按 `t=0` 比一次，别把它当误差；
8. **产物/真值可重生成**，但**改代码后必须重跑 §0 的第 2、3 条**并把
   `_verify_vs_unity.tsv` 更新（`_bdone_spine\README.md` 的数字取自它）。

---

## 4. 验收数字（2026-10-14，全部产物）

| 检查 | 结果 |
| --- | --- |
| 逐节点局部 TRS | 最大位置 **0.0005 px**、最大角度 **0.0000°** |
| 部件矩形（center/宽/高） | 最大 **0.0002 px** |
| 显隐不一致 | **0** 处 |
| 颜色通道差 | ≤ **0.05** |
| "真值能画、我们缺槽位" | **0** 处 |
| 结构自检 `validate_spine` | **36/36** |
| `.skel` 读回 | **36/36** |
| 视觉抽查（`rt_frames` + `vision.js`） | 阿波罗/协助、温蒂：人形完整、无错位断肢 |

---

## 5. 踩过的坑（现象 → 根因 → 处理）

| 现象 | 根因 | 处理 |
| --- | --- | --- |
| 有的件裁到别人服装的图上 | "图集 asset 同目录第一张 png"，`res/<目录>` 一目录多图集 | 走 asset→material→texture |
| 部件位置/尺寸差 1~4 px | 手写换算 ≠ `drawingDimensions`（奇数补 1 px 被算进分母、没管 pivot） | `sprite_quad()` |
| 20+ 件整段不动作 | 漏 `m_EulerCurves` | `parse_clip` 收欧拉曲线 |
| `.skel` 写出器报"不存在的插槽 `default`" | 没有槽位时间线时也写了 `{"default": {}}` | 空则不写 `slots` |
| 末帧差 2285 px（呼噜呼噜的 bg） | 真值末帧是 loop 起点 | 对账脚本末帧按 `t=0` 比 |
| 颜色差 0.15（雅拉娜的 light） | 0.05 栅格线性插值逼近 Hermite 的 S 曲线 | 颜色 0.01 细栅格 + 原关键帧 |
| 合并路线 ImportError | 库化后 `spine38_binary` 换了目录 | 改 `from ..spine import ...` |
| 合并产物被校验器全判错 | 3.8 加权 mesh 是**扁平** `[骨数,骨下标,x,y,权重…]` | `_mesh_vertex_shape()` |
| 校验器报"缺少 atlas" | 把 `.config.json` / `_bdone_info.json` 当骨架 | 跳过元数据文件 |
| Unity 打不开工程 | 版本不一致对话框（工程 2021.3.44f1c1 / 本机 45f2c1）+ 有实例占锁 | 关掉实例，用 batchmode `-executeMethod` |
| 内存 | Unity 编辑器 / GL 渲染各约 1 GB | 一次只跑一个；先看可用内存（AGENTS.md） |

---

## 6. 后续工作清单（按优先级，含"怎么开始 / 判据"）

### A.（需不需要先拍板）一个角色一个文件：多服装合并 / skin 化
现在每个服装是**独立骨架**（和 Unity 里同屏叠放的玩法一致）。若查看器/交付要求
"一个角色一个文件"，就得把同一角色的多套服装合到一个骨架里：
起点是 `ngui\merge_char.py`（多子装配合并）与 `validate\merge_existing_spine.py`
（已有 Spine 的合并）；判据：合并 `.skel` 读回 OK + 逐件几何与分件产物一致 +
各服装动画名不撞。

### B. 实测还没走到的 NGUI 分叉
`mType != Simple`（Sliced/Tiled/Filled）、`mFlip != 0`、`mDrawRegion != 默认`
在 BdOne 这批资源里**全是默认值**，所以 `sprite_quad()` 的这几支只是"照源码写的"，
没有真值背书。做法：在 Unity 里把某个件的 `mType/mFlip` 改掉再导真值对一次，
或新找一个用了这些特性的工程。判据：矩形差 < 0.01 px。

### C.（可选）精度再上一档
当前 rotate/translate 是 0.05 s 线性插值（误差已 5e-4 px），想更贴可以：
① 把 Hermite 段换算成 Spine 的 Bézier 关键帧（`curve/c2/c3/c4`，对旋转是四元数
空间、不一定能逐分量表达，慎用）；② 或把 `--dt` 降到 0.02（体积约 +1.5×）。
判据：`bdone_check_v2` 的 max 再降一个量级，且体积/加载可接受。

### D. 想在 Unity 编辑器里实时迭代 → 给 BdOne 装 MCP
`com.coplaydev.unity-mcp`（10.3.0）在归档工程
`D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Packages\` 下有一份，
拷进 BdOne 的 `Packages\`、用 `uvx` 起 HTTP 服务（`~/.codex/config.toml` 里
`unityMCP` 已指向 `http://127.0.0.1:8080/mcp`），再用
`tools\bake_cs\mcp_exec.py` 那种方式发 `execute_code`。
注意：会再触发一次包解析/重导；本次没装是因为它会改工程 + 当时编辑器卡在版本对话框上。

### E. 换个 NGUI 工程直接复用
```powershell
python tools\convert_bdone.py --assets "<Unity工程>\Assets" --chr "<Assets>\prefab\chr" --out <输出目录>
```
若那批资源的 `res/<目录>` 也一个目录多图集、或有 `mType != Simple`，
先跑 §B 的实测再全量。

### F.（可选）Unity 端视觉对照
目前视觉证据只有"我们的渲染 + vision 抽查"。要更硬，可以在 Unity 里搭
`UIRoot + UIPanel + 正交相机`把 prefab 按同一时刻截图，与 `rt_frames.py`
的输出逐像素比（这一步本次没做，成本和收益都中等）。

### G. 不要做的事
* 别把 `.json` 的 `slots` 改回"套皮肤名"（3.8 读不了）；
* 别只杀 python 留批处理外壳（AGENTS.md，内存会被反复打满）；
* 别拿 `_bdone_truth\` 当"不可再生资源"——它就是 batchmode 一条命令；
* 动 `sprite_quad()` / 颜色栅格 / `BdTruthExport` schema 时，记得同时对账脚本
  也要跟着改（三者的口径是绑在一起的）。

---

## 7. 环境副作用（本轮留下的痕迹）

* `D:\VB\Search\BdOne` 工程：新增 `Assets\Editor\BdTruthExport.cs`（+ `.meta`）；
  Unity 用 2021.3.45f2c1 打开工程时把 `com.unity.collab-proxy` 2.5.1 → 2.5.2
  记进了 `Packages\manifest.json` / `packages-lock.json`（自动行为）；
* 期间为跑 batchmode 关掉了一个卡在"版本不一致"对话框上的 Unity 实例；
  **现在可能还有 Unity 编辑器开着 BdOne**（Hub 启动），要跑 batchmode 前先关掉；
* `_scratch\bdone_baseline\` 是**修改前**老路线的产物（保留作对照），
  `_scratch\bdone_v2\` 是中途 6 个服装的对照版，都可以随时删。

---

## 8. 相关文档

| 文档 | 看什么 |
| --- | --- |
| [`BdOne_NGUI_转化.md`](BdOne_NGUI_转化.md) | 路线、4 个修复的证据、真值导出细节、复现命令、产物形态、已知限制 |
| [`../更新摘要_20261014.md`](../更新摘要_20261014.md) | 本轮摘要（含工具修复清单） |
| [`../_bdone_spine/README.md`](../_bdone_spine/README.md) | 交付物自带的说明（目录结构、口径、验收数字） |
| [`../_bdone_spine/_verify_vs_unity.tsv`](../_bdone_spine/_verify_vs_unity.tsv) | 逐产物对账明细 |
| [`../使用与代码导览.md`](../使用与代码导览.md) | `ngui\*` 与 `tools\convert_bdone.py` 在整仓里的位置 |
| [`_archive_20260917/其他路线与历史.md`](_archive_20260917/其他路线与历史.md) | NGUI 路线的历史方案与"多服装合并"的旧讨论 |
