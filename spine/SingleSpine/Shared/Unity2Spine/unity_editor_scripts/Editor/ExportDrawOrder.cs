// ExportDrawOrder.cs —— 导出**运行时绘制顺序** + 排序所需的一切信息。
//
// 为什么需要它：离线转换要按 Unity 的规则排槽位（决定"谁盖谁"）。Unity 透明件的
// 排序键是 `(sortingLayer, m_SortingOrder, 到相机的深度)`；2D 角色所有部件的 z
// 几乎相同（实测同角色 103 个渲染器里 101 个 camDepth 完全一致），所以**同一
// sortingOrder 内的先后**由"提交顺序"决定 —— 那个顺序没有公开 API 可读，只能测。
//
// 本脚本做两件事（`PairScope` 控制是否做第二件）：
//   ① **导出信息**：每个渲染器一条 —— 路径 / 类型 / 枚举序 / 层级 DFS 序 /
//      sortingLayer / sortingOrder / sortingFudge / rendererPriority / renderQueue /
//      材质与 shader / 混合因子 / 世界包围盒 / camDepth（包围盒中心）与 nodeDepth
//      （节点位置）/ distToCam / 屏幕包围盒 / sprite / 贴图 / mesh / 显隐 / instanceID，
//      外加相机与 graphics 的排序设置 ⇒ 离线一侧可以**自己重算排序键**。
//   ② **实测顺序**：对"排序键完全并列"的渲染器（`PairScope="all"` 时对所有互相
//      重叠的可见渲染器）做**成对隔离渲染**，用真实像素判定谁在谁之上，再拓扑排序
//      得到绘制顺序。**不依赖 Unity 内部 API，也不改材质**。
//
// 判定原理（每对 a、b）：
//     A  = 只开 a 渲一张（其它渲染器全关）      B  = 只开 b 渲一张
//     AB = a、b 都开渲一张
//   · 证据一（不建模型，最硬）：在 a 不透明（α≈255）的像素上，若 AB 与 A 几乎相同
//     而明显不同于 B ⇒ a 盖住了 b。反向同理，统计票数。
//   · 证据二（模型）：按 `Top over Bottom` 分别预测 "a 上" / "b 上"，与实际 AB 的
//     平均误差小者胜。模型两种都算（存储预乘 / 存储 straight），取解释得更好的那个
//     —— 因为 Sprites/Default 是 `Blend One OneMinusSrcAlpha`（预乘），其它材质未必。
//   两条证据一致才下结论；只有一条时在 verdict 后缀 `?votes` / `?model` 标出来。
//
// 输出（默认写 **D:\VB\Unity2Spine\info**，**不写进 Assets**，否则会触发导入）：
//   <outRoot>/_draworder_<角色>/           （<outRoot> = D:\VB\Unity2Spine\info）
//       <角色>__<状态>__t<毫秒>.json         渲染器信息 + 并列组 + 实测顺序
//       frames/<角色>__<状态>__t<毫秒>.png   同帧渲染图（带相机；透明底转白底）
//       frames/<角色>__<状态>__t<毫秒>_cam.txt
//       frames/pairs/...                     隔离图/成对图（只有 WriteImages=true 才写）
//
// 用法：菜单 `Tools/2DModel/运行时采样/渲染顺序导出：按内置清单开始`
//   （参数在 ExportDrawOrderPlan 里**硬编码**，不用窗口输入）
// 日志：D:\VB\Unity2Spine\info\_logs\play_sample.log（与 PlayRefShot 同一条）
//
// 目标怎么来（`Names` 的三种写法）：
//   · `"a,b,c"` = 按名字找；场景里**没有**的名字，只要 `InstantiateMissing=true`，
//     就从 `PrefabDir`（默认 `Assets/prefabs/Change50`）临时实例化一份来采，采完销毁。
//   · `""` 或 `"*"` = **场景里所有**带 Animator+Renderer 的根（**含 inactive**）。
//   · 场景里 inactive 的角色：脚本会把它**整条父链临时激活**再采，采完恢复原状
//     （`CalibTargets.Activate`；`ActivateInactive=false` 可以关掉这个行为）。
//   为什么必须激活：inactive 的 Animator 不跑，`m_IsActive` 这类曲线不会落到物体上，
//   渲染器也不会被提交 —— 不激活就采不到真实顺序（PlayRefShot 里已踩过这个坑）。
//
// 约定：协程里不在带 catch 的 try 中 yield（沿用 PlayRefShot 的写法）。

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>内置清单：要改参数只改这里（不用在窗口里输入）。</summary>
public static class ExportDrawOrderPlan
{
    /// <summary>
    /// 角色根物体名（逗号分隔）。留空或写 `*` = **场景里所有**带 Animator+Renderer 的根
    /// （**inactive 的也算**）。默认 `"*"`：把场景里那批（当前是 50 个）**逐个**导出。
    /// 会在场景里找不到某名字时，从 `PrefabDir` 临时实例化一份（见 `InstantiateMissing`）。
    /// </summary>
    // 2026-09-18 下午批次：只采"要判的这几条"。名字 = **挂 Animator 的 GameObject 名**
    // （从 save.unity 实测；匹配大小写不敏感）：
    //   BR_BeastHunter_NS1            → beasthunter_skin1（丢动作，要全片密集点）
    //   2Dmodel_PECS_Cerberus_NS3_FBX → cerberus_skin3（breast ≥0.85 整帧黑）
    //   PECS_Draculina_NS1            → draculina_skin1 + _fix（Tep_1 抓绳子 7~10 s）
    //   Size_root                     → 大小写不敏感，会一起采到 Size_root/size_root 的 5 个：
    //                                  banshee_skin1(手)、constantias2_skin1(breast 扭曲)、
    //                                  constantias2_normal / constantias2_skin1S / cerberus_skin1（回归用）
    // 导完还原成 "*"。
    // 2026-09-18 深夜（第 4 批）：一次采 #7 draculina 与 #5 constantias2_skin1 两条。
    //   PECS_Draculina_NS1      → draculina_skin1：①表情重叠 ②Tep_1 姿势
    //                             ③**7~10 s 抓绳子**（Tep_1 = 12.53 s ⇒ 0.55~0.80 就是 6.9~10.0 s）
    //   ConstantiaS2_NS1 系     → constantias2_skin1：**breast 动画的表情重叠/扭曲**
    //   （场景里挂 Animator 的名字，大小写不敏感；两个都带上，一次 Play 全采完）
    // ⚠️ 名字必须是**场景里挂 Animator 的 GameObject 名**（大小写不敏感，找不到会回退
    // 到 `PrefabDir` 里同名 prefab）。上一批写 `ConstantiaS2_NS1` **采不到**：日志
    // `找不到 prefab：Assets/prefabs/Change50/ConstantiaS2_NS1.prefab（跳过）`。
    // 实测：constantias2_skin1 的 Animator 宿主叫 **`size_root`**（我们产物
    // `_static_info.json` 的 `animations[].animator` 就是这个），所以名单写成
    // `size_root`（会顺带命中 banshee/constantias2_normal/constantias2_skin1S/
    // cerberus_skin1 等同名宿主，States 过滤后数据无害、还能当回归用）。
    public const string Names = "size_root,PECS_Draculina_NS1";
    /// <summary>Animator 状态名（逗号分隔；**留空 = 该 Animator 的所有状态**，默认全状态）。</summary>
    // draculina 只要 Tep_1（抓绳子那条）；constantias2_skin1 要 breast + Lobby（复验表情重叠）。
    public const string States = "Tep_1,breast,Lobby,lobby";
    /// <summary>
    /// 采样时刻（逗号分隔）。`TimesRelative=true` 时是**归一化比例**：
    /// 按每条 clip 自己的时长折算，长短不一的（2 s~12 s）都能采到同样节奏的点。
    /// 默认 5 个点；要更细就往前/中间再插。
    /// </summary>
    // 2026-09-18 下午：时刻多一点、铺满全片（归一化比例）。
    // 0.04 ≈ banshee 0.5 s；0.58~0.76 = draculina Tep_1 的 7.3~9.5 s（抓绳子那段）；
    // 0.84/0.92 用来看 cerberus_skin3 的 breast 尾部黑帧。导完还原成 5 个点。
    // 第一个点 0.04 = banshee 的 0.50 s（用户截图那个时刻），其余保留默认 5 点节奏。
    // 时刻（归一化比例）。7~10 s 段加密：draculina Tep_1（12.53 s）⇒ 0.55/0.60/0.65/0.70/0.75/0.80
    // 就是 6.9/7.5/8.1/8.8/9.4/10.0 s；另外保留 A2 那个 0.04 与一个中段点。
    // 常数项：0.05/0.25 用于 constantias2_skin1 的 breast（2.32 s）与 Lobby（7.07 s）抽样。
    public const string Times = "0.05,0.25,0.55,0.60,0.65,0.70,0.75,0.80";
    /// <summary>上面的时刻是"比例"（true）还是"秒"（false）。</summary>
    public const bool TimesRelative = true;
    /// <summary>取景分辨率（像素/世界单位）。主帧用。</summary>
    public const float Ppu = 512f;
    /// <summary>取景留白。</summary>
    public const float Margin = 1.05f;
    /// <summary>
    /// 成对实测范围：
    ///   "tie" = 只测**排序键完全并列**的组（快；直接回答"同 order 谁盖谁"）；
    ///   "all" = 测**所有互相重叠的可见渲染器**（完整经验绘制顺序，n² 量级，慢）；
    ///   "off" = 不做实测，只导出信息与"规则顺序"。
    /// </summary>
    // 这一批：#7/#5 都是"表情/手指**重叠**（谁盖谁）"⇒ 要并列组的成对隔离实测；
    // "tie" 只测排序键完全并列的组（快、直接回答"同 order 谁盖谁"）。
    // 想拿完整经验顺序就把下面改成 "all"（n² 慢很多，先看预检那行的时间估计）。
    public const string PairScope = "tie";
    /// <summary>成对实测的渲染分辨率（小一点快很多；512 足够分辨 1px 级差异）。</summary>
    public const int PairPpu = 384;
    /// <summary>
    /// 单帧成对实测的**上限**：`PairScope="all"` 时重叠对可能上千，乘上"50 目标 ×
    /// 全状态 × 5 时刻"就是几十万次渲染。超过就按「同并列组优先」截断，并写日志。
    /// 想跑全量就把这个调大（但先算时间：每对约 3 次 384px 渲染 ≈ 5~10 ms）。
    /// </summary>
    public const int PairCap = 800;
    /// <summary>是否把隔离图/成对图写到 frames/pairs（几百张 PNG，默认不写）。</summary>
    public const bool WriteImages = false;
    /// <summary>
    /// 是否写每个采样帧的 PNG + `_cam.txt`（白底，和 Unity 帧同机位）。
    /// 全状态 × 5 时刻会有一千多张（约 0.5~1 GB），只想拿顺序数据可以关掉。
    /// </summary>
    public const bool SaveFramePng = true;
    /// <summary>采完自动退出 Play 模式。</summary>
    public const bool ExitAfter = true;
    /// <summary>场景里 inactive 的角色也要采样（先临时激活，采完恢复）。</summary>
    public const bool ActivateInactive = true;
    /// <summary>
    /// `Names="*"`（或留空）时，**只取当前 inactive 的根** —— 也就是"场景里那批
    /// 摆着没启用的角色"（当前是 50 个）。场景里已经激活的（可能有别的东西在跑）
    /// 不算，避免把无关对象卷进来；被排除的会在日志里列出。
    /// </summary>
    public const bool OnlyInactive = true;
    /// <summary>
    /// 采样时把目标自己的 Renderer **临时 `enabled = true`**（采完还原）。
    /// 为什么需要：这批角色在场景里是"Renderer 级 disabled"（`activeInHierarchy=true`
    /// 但 `enabled=false`，游戏运行时会按需开），只 `SetActive(true)` 是画不出来的
    /// —— 2026-09-17 16:5x 那次每帧 `可见 0` 就是这个原因。
    /// </summary>
    public const bool ForceEnableRenderers = true;
    /// <summary>
    /// **碰不碰场景**：
    ///   `"observe"`（默认）= **什么都不改** —— 等游戏自己把角色显示出来（正常 Play 的样子）
    ///      再采；没出现的目标等 `ObserveWaitSeconds` 秒后跳过。这样采到的画面
    ///      **就是直接 Play 模式看到的样子**。
    ///   `"force"` = 老做法：脚本自己 `SetActive` + 强开 `Renderer.enabled` 再采
    ///      （游戏自己显示不出来时才用）。
    /// </summary>
    // 2026-09-18 傍晚（用户要求）：**自己在 Unity 里激活**，脚本不碰场景。
    //   "observe" = 一个字节都不改场景：脚本每帧看哪个目标"被显示出来了"
    //   （根 active 且有 enabled 的渲染器）就采谁，采完立刻采下一个；
    //   `ObserveWaitSeconds/ObserveTotalSeconds` 是等待上限（默认 8s / 900s）。
    //   注意：这批角色很多是 **Renderer 级 disabled**（activeInHierarchy=true 但
    //   enabled=false），只 SetActive 是"看不见"的 ⇒ 要么在 Inspector 里把角色
    //   的 Renderer 也打开，要么让游戏流程/probe 把它显示出来。
    //   （脚本仍会临时禁用 SceneActivationController，防止它改 activeSelf 污染真值，采完还原。）
    public const string TouchMode = "observe";
    /// <summary>`observe` 模式下，等一个目标出现的秒数（超时就跳过并记账）。</summary>
    public const float ObserveWaitSeconds = 8f;
    /// <summary>`observe` 模式的**总**时限（秒）：这段时间内游戏显示多少就采多少，到点收工。</summary>
    public const float ObserveTotalSeconds = 900f;
    /// <summary>
    /// 主帧（那张 PNG）要不要**也把别的角色关掉**。
    /// `false`（默认）= 主帧就是"正常 Play 的画面"（可能同时有别的角色）；
    /// `true` = 主帧只画这一个目标（干净，但不是 Play 的样子）。
    /// 成对隔离渲染**永远**会把别的角色临时关掉（只影响判定，不影响主帧）。
    /// </summary>
    public const bool IsolateFrame = false;
    /// <summary>
    /// 旧的"**进 Play 之前**就把所有目标全部激活"（PlayRefShot 的老做法）。
    /// 默认 **关**：现在改成 Play 里**逐个** 激活 → 采样 → 立刻关回去，
    /// 同一时刻场景里只有 1 个角色是活的，减少互相干扰/重叠。
    /// </summary>
    public const bool ActivateBeforePlay = false;
    /// <summary>名单里的名字**场景里没有**时，从 PrefabDir 临时实例化一份来采（采完销毁）。</summary>
    public const bool InstantiateMissing = true;
    /// <summary>临时实例化用的 prefab 目录（Assets 相对路径）。</summary>
    public const string PrefabDir = "Assets/prefabs/Change50";

    public static ExportDrawOrder.Cfg ToCfg()
    {
        return new ExportDrawOrder.Cfg
        {
            names = Names,
            states = States,
            times = Times,
            timesRelative = TimesRelative,
            ppu = Ppu,
            margin = Margin,
            pairScope = PairScope,
            pairPpu = PairPpu,
            pairCap = PairCap,
            writeImages = WriteImages,
            saveFramePng = SaveFramePng,
            exitAfter = ExitAfter,
            activateInactive = ActivateInactive,
            onlyInactive = OnlyInactive,
            forceEnableRenderers = ForceEnableRenderers,
            touchMode = TouchMode,
            observeWaitSeconds = ObserveWaitSeconds,
            observeTotalSeconds = ObserveTotalSeconds,
            isolateFrame = IsolateFrame,
            activateBeforePlay = ActivateBeforePlay,
            instantiateMissing = InstantiateMissing,
            prefabDir = PrefabDir,
        };
    }
}

public static class ExportDrawOrder
{
    public class Cfg
    {
        public string names = "";
        public string states = "";
        public string times = "0";
        public bool timesRelative = true;
        public float ppu = 512f;
        public float margin = 1.05f;
        public string pairScope = "tie";
        public float pairPpu = 384f;
        public int pairCap = 800;
        public bool writeImages = false;
        public bool saveFramePng = true;
        public bool exitAfter = true;
        public string outRoot = "";
        public bool activateInactive = true;
        public bool onlyInactive = true;
        public bool forceEnableRenderers = true;
        public string touchMode = "observe";
        public float observeWaitSeconds = 8f;
        public float observeTotalSeconds = 900f;
        public bool isolateFrame = false;
        public bool activateBeforePlay = false;
        public bool instantiateMissing = true;
        public string prefabDir = "Assets/prefabs/Change50";
    }

    private static Cfg _pending;
    private static IEnumerator _routine;
    private static bool _running;
    private static readonly List<GameObject> _activated = new List<GameObject>();

    // ---------------------------------------------------------- 待跑配置（跨 Domain Reload）
    // 进 Play 模式时静态字段会被 Domain Reload 清掉，所以配置要落到 EditorPrefs
    // （PlayRefShot 2026-09-17 第一次实测就丢过请求）。
    private const string PEND = "ExportDrawOrder.pending";
    private const string K_N = "ExportDrawOrder.pend.names";
    private const string K_S = "ExportDrawOrder.pend.states";
    private const string K_T = "ExportDrawOrder.pend.times";
    private const string K_TR = "ExportDrawOrder.pend.timesRelative";
    private const string K_P = "ExportDrawOrder.pend.ppu";
    private const string K_M = "ExportDrawOrder.pend.margin";
    private const string K_PS = "ExportDrawOrder.pend.scope";
    private const string K_PZ = "ExportDrawOrder.pend.pairppu";
    private const string K_PC = "ExportDrawOrder.pend.paircap";
    private const string K_WI = "ExportDrawOrder.pend.images";
    private const string K_FP = "ExportDrawOrder.pend.framePng";
    private const string K_X = "ExportDrawOrder.pend.exit";
    private const string K_O = "ExportDrawOrder.pend.out";
    private const string K_AI = "ExportDrawOrder.pend.actInactive";
    private const string K_OI = "ExportDrawOrder.pend.onlyInactive";
    private const string K_FE = "ExportDrawOrder.pend.forceEnable";
    private const string K_TM = "ExportDrawOrder.pend.touchMode";
    private const string K_OW = "ExportDrawOrder.pend.observeWait";
    private const string K_OT = "ExportDrawOrder.pend.observeTotal";
    private const string K_IF = "ExportDrawOrder.pend.isolateFrame";
    private const string K_AB = "ExportDrawOrder.pend.actBeforePlay";
    private const string K_IM = "ExportDrawOrder.pend.instMissing";
    private const string K_PD = "ExportDrawOrder.pend.prefabDir";

    private static void SavePending(Cfg c)
    {
        EditorPrefs.SetString(K_N, c.names);
        EditorPrefs.SetString(K_S, c.states);
        EditorPrefs.SetString(K_T, c.times);
        EditorPrefs.SetBool(K_TR, c.timesRelative);
        EditorPrefs.SetFloat(K_P, c.ppu);
        EditorPrefs.SetFloat(K_M, c.margin);
        EditorPrefs.SetString(K_PS, c.pairScope);
        EditorPrefs.SetFloat(K_PZ, c.pairPpu);
        EditorPrefs.SetInt(K_PC, c.pairCap);
        EditorPrefs.SetBool(K_WI, c.writeImages);
        EditorPrefs.SetBool(K_FP, c.saveFramePng);
        EditorPrefs.SetBool(K_X, c.exitAfter);
        EditorPrefs.SetString(K_O, c.outRoot);
        EditorPrefs.SetBool(K_AI, c.activateInactive);
        EditorPrefs.SetBool(K_OI, c.onlyInactive);
        EditorPrefs.SetBool(K_FE, c.forceEnableRenderers);
        EditorPrefs.SetString(K_TM, c.touchMode);
        EditorPrefs.SetFloat(K_OW, c.observeWaitSeconds);
        EditorPrefs.SetFloat(K_OT, c.observeTotalSeconds);
        EditorPrefs.SetBool(K_IF, c.isolateFrame);
        EditorPrefs.SetBool(K_AB, c.activateBeforePlay);
        EditorPrefs.SetBool(K_IM, c.instantiateMissing);
        EditorPrefs.SetString(K_PD, c.prefabDir);
        EditorPrefs.SetBool(PEND, true);
        PlaySampleLog.W("[draworder] 已登记待跑配置：" + c.names + " / " + c.states
                        + " / " + c.times + " / scope=" + c.pairScope);
    }

    private static Cfg TakePending()
    {
        if (!EditorPrefs.GetBool(PEND, false)) return null;
        EditorPrefs.SetBool(PEND, false);
        return new Cfg
        {
            names = EditorPrefs.GetString(K_N, ""),
            states = EditorPrefs.GetString(K_S, ""),
            times = EditorPrefs.GetString(K_T, "0"),
            timesRelative = EditorPrefs.GetBool(K_TR, true),
            ppu = EditorPrefs.GetFloat(K_P, 512f),
            margin = EditorPrefs.GetFloat(K_M, 1.05f),
            pairScope = EditorPrefs.GetString(K_PS, "tie"),
            pairPpu = EditorPrefs.GetFloat(K_PZ, 384f),
            pairCap = EditorPrefs.GetInt(K_PC, 800),
            writeImages = EditorPrefs.GetBool(K_WI, false),
            saveFramePng = EditorPrefs.GetBool(K_FP, true),
            exitAfter = EditorPrefs.GetBool(K_X, true),
            outRoot = EditorPrefs.GetString(K_O, ""),
            activateInactive = EditorPrefs.GetBool(K_AI, true),
            onlyInactive = EditorPrefs.GetBool(K_OI, true),
            forceEnableRenderers = EditorPrefs.GetBool(K_FE, true),
            touchMode = EditorPrefs.GetString(K_TM, "observe"),
            observeWaitSeconds = EditorPrefs.GetFloat(K_OW, 8f),
            observeTotalSeconds = EditorPrefs.GetFloat(K_OT, 900f),
            isolateFrame = EditorPrefs.GetBool(K_IF, false),
            activateBeforePlay = EditorPrefs.GetBool(K_AB, false),
            instantiateMissing = EditorPrefs.GetBool(K_IM, true),
            prefabDir = EditorPrefs.GetString(K_PD, "Assets/prefabs/Change50"),
        };
    }

    // ------------------------------------------------------------------ 入口
    public static void Start(Cfg cfg)
    {
        _pending = cfg;
        SavePending(cfg);
        if (cfg.activateBeforePlay && !EditorApplication.isPlaying)
        {
            // 与 PlayRefShot 一致：**进 Play 之前**就在 edit 模式激活角色，
            // 否则 Animator 可能在 inactive 状态建绑定，部分曲线会静默失效。
            // 注意：这会让所有目标同时是活的（干扰大）；默认关，改成 Play 里逐个来。
            foreach (var root in FindRoots(cfg))
            {
                var changed = CalibTargets.Activate(root);
                if (changed.Count > 0)
                {
                    _activated.AddRange(changed);
                    PlaySampleLog.W("[draworder] （进 Play 前）激活 " + root.name
                                    + " 的 " + changed.Count + " 个上级/自身节点");
                }
            }
        }
        if (EditorApplication.isPlaying) Begin(cfg);
        else EditorApplication.EnterPlaymode();
    }

    private static void Begin(Cfg cfg)
    {
        if (_running) { PlaySampleLog.W("[draworder] 已经在跑，忽略重复请求"); return; }
        _running = true;
        _routine = Run(cfg);
        EditorApplication.update += Pump;
        PlaySampleLog.W("[draworder] 开始：names=" + cfg.names + " states=" + cfg.states
                        + " times=" + cfg.times + " ppu=" + cfg.ppu
                        + " scope=" + cfg.pairScope);
    }

    [InitializeOnLoadMethod]
    private static void Install()
    {
        EditorApplication.playModeStateChanged += s =>
        {
            // 退出/切换走 Play：立刻停（不然协程会在 edit 模式继续跑）
            if (s == PlayModeStateChange.ExitingPlayMode
                || s == PlayModeStateChange.EnteredEditMode)
            {
                if (_routine != null) StopRunning("Play 模式结束（" + s + "）");
                return;
            }
            if (s != PlayModeStateChange.EnteredPlayMode) return;
            var c = _pending != null ? _pending : TakePending();
            if (c != null)
            {
                _pending = null;
                PlaySampleLog.W("[draworder] EnteredPlayMode → 开始采样");
                Begin(c);
            }
        };
        EditorApplication.update += () =>
        {
            if (_running || !EditorApplication.isPlaying) return;
            var c = _pending != null ? _pending : TakePending();
            if (c != null)
            {
                _pending = null;
                PlaySampleLog.W("[draworder] update 轮询 → 开始采样");
                Begin(c);
            }
        };
    }

    /// <summary>常用的那条：直接用文件里硬编码的清单开始。</summary>
    [MenuItem("Tools/2DModel/运行时采样/渲染顺序导出：按内置清单开始", false, 0)]
    public static void MenuStartPlan()
    {
        Start(ExportDrawOrderPlan.ToCfg());
    }

    /// <summary>用上一次登记的配置开始（含 EditorPrefs 里的）。</summary>
    [MenuItem("Tools/2DModel/运行时采样/渲染顺序导出：用上次参数开始", false, 1)]
    public static void MenuStartLast()
    {
        var c = TakePending();
        if (c == null)
        {
            PlaySampleLog.W("[draworder] 没有登记过的配置，改用内置清单");
            c = ExportDrawOrderPlan.ToCfg();
        }
        Start(c);
    }

    [MenuItem("Tools/2DModel/运行时采样/渲染顺序导出：只诊断（不进 Play）", false, 2)]
    public static void MenuDiagnose()
    {
        PlaySampleLog.W("[draworder] 诊断:\n" + Diagnose(ExportDrawOrderPlan.ToCfg()));
    }

    public static string Diagnose(Cfg cfg)
    {
        var sb = new StringBuilder();
        var roots = FindRoots(cfg).ToArray();
        if (roots.Length == 0) return "没找到角色（名字写对了吗？场景里有没有？）";
        foreach (var root in roots)
        {
            var rends = root.GetComponentsInChildren<Renderer>(true);
            var ans = root.GetComponentsInChildren<Animator>(true);
            sb.AppendLine(root.name + "：Renderer " + rends.Length
                          + " / Animator " + ans.Length
                          + " / activeInHierarchy=" + root.activeInHierarchy);
            foreach (var an in ans)
            {
                var ctrl = an.runtimeAnimatorController as AnimatorController;
                if (ctrl == null) { sb.AppendLine("   " + an.name + "：无 controller"); continue; }
                var list = CollectStates(ctrl);
                sb.AppendLine("   " + an.name + "：状态 " + list.Count + " → "
                              + string.Join(",", list.Take(20).Select(x => x.name).ToArray()));
            }
            var groups = rends.Where(r => r.enabled && r.gameObject.activeInHierarchy
                                          && r.bounds.size.sqrMagnitude > 1e-10f)
                              .GroupBy(TieKey)
                              .Where(g => g.Count() > 1)
                              .OrderByDescending(g => g.Count());
            sb.AppendLine("   可见渲染器的并列组（同 layer + order + 深度）：");
            foreach (var g in groups.Take(12))
            {
                var arr = g.ToArray();
                sb.AppendLine("      x" + arr.Length + "  layer=" + arr[0].sortingLayerName
                              + " order=" + arr[0].sortingOrder + "  → "
                              + string.Join(",", arr.Take(8)
                                    .Select(r => r.transform.name).ToArray()));
            }
        }
        return sb.ToString();
    }

    private static void Pump()
    {
        if (_routine == null) return;
        // **退出 Play 就自动停**：不加这一条，协程会继续在 edit 模式下 MoveNext，
        // 于是它还会去激活/渲染/写文件，甚至把场景改坏。
        if (!EditorApplication.isPlaying)
        {
            StopRunning("已退出 Play 模式");
            return;
        }
        try
        {
            if (!_routine.MoveNext())
            {
                StopRunning("跑完");
                PlaySampleLog.W("[draworder] 完成");
            }
        }
        catch (Exception e)
        {
            StopRunning("异常");
            PlaySampleLog.E("[draworder] 异常", e);
        }
    }

    /// <summary>
    /// 停止当前协程并**还原现场**：`Dispose()` 会让迭代器里所有 `finally` 立刻执行
    /// （各目标自己的"关回 inactive / 还原渲染器"就写在那里）。
    /// </summary>
    private static void StopRunning(string why)
    {
        var it = _routine;
        _routine = null;
        _running = false;
        EditorApplication.update -= Pump;
        if (it != null)
        {
            var d = it as IDisposable;
            if (d != null)
            {
                try { d.Dispose(); }
                catch (Exception e) { PlaySampleLog.E("[draworder] 停止时还原失败", e); }
            }
        }
        // 兜底：`Run` 的 finally 已经会做这些，这里再确认一次（防 Dispose 没跑到）
        foreach (var go in _activated) if (go != null) go.SetActive(false);
        _activated.Clear();
        PlaySampleLog.W("[draworder] 已停止（" + why + "）");
    }

    // ------------------------------------------------------------------ 数据结构
    private class StateEntry
    {
        public string name;
        public int hash;
        public int layer;
        public AnimatorState state;
        public AnimatorController ctrl;
    }

    /// <summary>每个渲染器的信息（导出用 + 缓存实测顺序）。</summary>
    private class RInfo
    {
        public Renderer r;
        public int idx;                 // 枚举序（GetComponentsInChildren<Renderer>）
        public int dfs;                 // 层级 DFS 序（自算，用来对拍枚举序）
        public string path = "";
        public string type = "";
        public string sprite = "";
        public string texture = "";
        public string mesh = "";
        public int verts = -1;
        public bool activeSelf, activeInHier, enabled, isVisible;
        public int layerId, order, priority, queue = -1;
        public Vector3 center, size;
        public float camDepth, nodeDepth, dist;
        public string[] mats = new string[0];
        public string[] shaders = new string[0];
        public int srcBlend = -1, dstBlend = -1, zWrite = -1;
        public Vector2 sMin, sMax;      // 屏幕像素包围盒（左下原点）
        public string tieKey = "";
        public int tieGroup = -1;
        public int tieRank = -1;        // 组内实测顺序（0 = 最先画）
        public long uKey = -1;          // Unity 自己的 sortingKey（反射读；-1 = 读不到）
        public int groupId = -1, groupOrder = -1;
    }

    private class PairResult
    {
        public int a, b;
        public string verdict = "no-overlap";
        public int votesA, votesB;
        public float errA, errB;
        public string model = "";
        public int overlap;
    }

    /// <summary>一次渲染用的相机 + RT + 缓冲（主帧一套、成对实测一套）。</summary>
    private class Ctx
    {
        public Camera cam;
        public RenderTexture rt;
        public Texture2D tex;
        public Renderer[] all;
        /// <summary>进入本次采样时各渲染器的 enabled（场景里本来就关掉的不许被打开）。</summary>
        public bool[] baseEnabled;
        /// <summary>
        /// 目标**之外**的渲染器（别的角色/道具）：只在"成对隔离渲染"时临时关掉、
        /// 渲完立刻还原。**主帧不关**（主帧要跟游戏正常 Play 的画面一致）。
        /// </summary>
        public List<Renderer> extraOff = new List<Renderer>();

        public Color32[] RenderOnly(ICollection<Renderer> keep)
        {
            var set = keep as HashSet<Renderer> ?? new HashSet<Renderer>(keep);
            var extraPrev = new bool[extraOff.Count];
            for (int i = 0; i < extraOff.Count; i++)
            {
                var r = extraOff[i];
                if (r == null) continue;
                extraPrev[i] = r.enabled;
                r.enabled = false;
            }
            for (int i = 0; i < all.Length; i++)
                all[i].enabled = baseEnabled[i] && all[i].gameObject.activeInHierarchy
                                 && set.Contains(all[i]);
            cam.Render();
            RenderTexture.active = rt;
            tex.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0);
            tex.Apply();
            RenderTexture.active = null;
            Restore();
            for (int i = 0; i < extraOff.Count; i++)
                if (extraOff[i] != null) extraOff[i].enabled = extraPrev[i];
            return tex.GetPixels32();
        }

        /// <summary>把渲染器的 enabled 恢复成采样开始时的样子。</summary>
        public void Restore()
        {
            for (int i = 0; i < all.Length; i++) all[i].enabled = baseEnabled[i];
        }

        public void Dispose()
        {
            Restore();
            if (cam != null)
            {
                cam.targetTexture = null;
                UnityEngine.Object.DestroyImmediate(cam.gameObject);
            }
            if (rt != null) { rt.Release(); UnityEngine.Object.DestroyImmediate(rt); }
            if (tex != null) UnityEngine.Object.DestroyImmediate(tex);
        }
    }

    // ------------------------------------------------------------------ 主流程
    private static IEnumerator Run(Cfg cfg)
    {
        // 统一导出根（D:\VB\Unity2Spine\info），见 ExportRoots.cs
        string outRoot = string.IsNullOrEmpty(cfg.outRoot)
            ? ExportRoots.Root
            : cfg.outRoot;
        float[] times = ParseFloats(cfg.times, new[] { 0f });
        var wantStates = Split(cfg.states);
        var roots = FindRoots(cfg).ToList();
        var made = new List<GameObject>();      // 从 prefab 临时实例化的（采完销毁）
        // 被我们临时禁掉的运行时探针（收尾还原）——见下面"屏蔽探针"那段
        var probesOff = new List<Behaviour>();
        try
        {

        // ---- 场景里没有的：从 PrefabDir 临时实例化一份（能在场景里采就不用这份）----
        if (cfg.instantiateMissing)
        {
            var found = new HashSet<string>(roots.Select(r => r.name), StringComparer.OrdinalIgnoreCase);
            foreach (var name in Split(cfg.names))
            {
                if (name == "*" || found.Contains(name)) continue;
                var path = (cfg.prefabDir.TrimEnd('/') + "/" + name + ".prefab");
                var pf = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (pf == null)
                {
                    PlaySampleLog.W("[draworder] 找不到 prefab：" + path + "（跳过 " + name + "）");
                    continue;
                }
                var go = UnityEngine.Object.Instantiate(pf);
                go.name = name;      // 保持路径与场景实例一致（对账要用）
                SceneManager.MoveGameObjectToScene(go, SceneManager.GetActiveScene());
                go.SetActive(true);
                roots.Add(go);
                made.Add(go);
                found.Add(name);
                PlaySampleLog.W("[draworder] 场景里没有 " + name
                                + " → 已从 prefab 临时实例化（采完销毁）：" + path);
            }
        }
        if (roots.Count == 0) { PlaySampleLog.E("[draworder] 没有找到角色"); yield break; }
        int nInactive = roots.Count(r => r != null && !r.activeInHierarchy);
        PlaySampleLog.W("[draworder] 角色 " + roots.Count + " 个（其中 inactive "
                        + nInactive + " 个，会临时激活）"
                        + (made.Count > 0 ? "；临时实例化 " + made.Count + " 个" : "")
                        + "：" + string.Join(",", roots.Select(r => r.name).ToArray()));

        // ---- 预检：先算"要采多少帧"，别等到跑一半才发现量太大 ----
        // （此时目标都还是 inactive，但 `GetComponentsInChildren(true)` 拿得到组件。）
        int estStates = 0, estFrames = 0;
        foreach (var rt in roots)
        {
            if (rt == null) continue;
            foreach (var an0 in rt.GetComponentsInChildren<Animator>(true))
            {
                var c0 = an0 != null ? an0.runtimeAnimatorController as AnimatorController : null;
                if (c0 == null) continue;
                foreach (var s0 in CollectStates(c0))
                {
                    if (wantStates.Count > 0 && !wantStates.Contains(s0.name)) continue;
                    var cl0 = s0.state.motion as AnimationClip;
                    if (cl0 == null) continue;
                    estStates++;
                    estFrames += NormsFor(cfg, times, cl0).Count;
                }
            }
        }
        bool pairsOn = scopeOf(cfg) != "off";
        bool observe = (cfg.touchMode ?? "observe").Trim().ToLowerInvariant() == "observe";
        PlaySampleLog.W("[draworder] 模式 = " + (observe ? "observe（不改场景，画面=正常 Play）"
                                              : "force（脚本自己激活+强开渲染器）"));
        PlaySampleLog.W("[draworder] 预检：目标 " + roots.Count + " 个 / 状态 " + estStates
                        + " 条 / 共 **" + estFrames + " 帧**（状态过滤 \"" + cfg.states + "\"）"
                        + "；PairScope=" + scopeOf(cfg) + "（每帧上限 " + cfg.pairCap
                        + " 对）⇒ 估计 " + (estFrames * (pairsOn ? 30 : 1))
                        + "~" + (estFrames * (pairsOn ? 200 : 2)) + " 次渲染，"
                        + "约 " + Mathf.RoundToInt(estFrames * (pairsOn ? 2f : 0.2f) / 60f)
                        + " 分钟。要减量：States 写成具体状态 / Times 少几个 / "
                        + "PairScope=\"tie\" 或 \"off\"。");

        // ---- 屏蔽"会改场景显隐"的运行时探针，避免污染真值（2026-09-18）----
        // `SceneActivationController`（Assets\PlayModeProbe\，通常挂在 Main Camera 上）
        // 在 Play 里会逐个激活角色，而且会**额外打开/关回部件的 activeSelf**
        // （它自己会打日志："额外打开了 N 个原本 inactive 的部件（会改写它们的
        // activeSelf 真值）"）。它和本导出同时跑时，采到的就不是"游戏真实显隐" ——
        // 实测 `constantias2_normal` lobby n0050 的可见渲染器从 34 变成 37。
        // 这里临时把它禁掉，收尾还原；用**类型名**匹配（不直接引用类型），
        // 免得哪天两边 asmdef 一改就编译不过。
        // 只在 **force** 模式禁它：那时脚本自己在激活，probe 会跟它抢。
        // **observe** 模式下 probe 就是"让角色显示出来"的那个游戏流程（以往那批
        // 就是这么采的），禁了反而什么都采不到 ⇒ 不动它。
        if (!observe)
            foreach (var mb in UnityEngine.Object.FindObjectsByType<MonoBehaviour>(
                         FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (mb == null || !mb.enabled) continue;
                if (mb.GetType().Name == "SceneActivationController")
                {
                    mb.enabled = false;
                    probesOff.Add(mb);
                }
            }
        if (probesOff.Count > 0)
            PlaySampleLog.W("[draworder] 已临时禁用 " + probesOff.Count
                            + " 个 SceneActivationController（它会改场景显隐、污染真值），收尾还原");

        // ---- 逐个目标：激活这一个 → 采样 → **立刻关回去** → 下一个 ----
        if (observe)
        {
            // ============ observe：**不碰场景**，跟着游戏走 ============
            // 每帧扫一遍还没采的目标：谁被游戏"正常显示"出来（根 active 且渲染器 enabled）
            // 就采谁 —— 顺序由游戏决定，不替它激活、不替它强开渲染器。
            var pending = new List<GameObject>(roots);
            int done = 0;
            double deadline = EditorApplication.timeSinceStartup
                              + Mathf.Max(30f, cfg.observeTotalSeconds);
            while (pending.Count > 0 && EditorApplication.timeSinceStartup < deadline)
            {
                if (!EditorApplication.isPlaying)
                {
                    PlaySampleLog.W("[draworder] observe：Play 已退出 → 停止");
                    yield break;
                }
                bool any = false;
                for (int i = pending.Count - 1; i >= 0; i--)
                {
                    var rt = pending[i];
                    if (rt == null) { pending.RemoveAt(i); continue; }
                    if (!TargetVisible(rt)) continue;
                    pending.RemoveAt(i);
                    any = true;
                    done++;
                    var others = OthersOf(roots, rt);
                    PlaySampleLog.W("[draworder] (" + done + "/" + roots.Count + ") observe 采 "
                                    + TargetLabel(rt) + "：游戏显示中，可见渲染器 "
                                    + CountVisible(rt) + " 个（不改场景）");
                    var sub0 = SampleTarget(rt, outRoot, wantStates, times, cfg,
                                            done, roots.Count, others, true);
                    while (sub0.MoveNext()) yield return sub0.Current;
                }
                if (!any) yield return null;
            }
            foreach (var g in pending)
                PlaySampleLog.W("[draworder] 未采到（游戏一直没显示它，observe 不替它打开）："
                                + TargetLabel(g));
            PlaySampleLog.W("[draworder] observe 结束：采到 " + done + "/" + roots.Count
                            + " 个目标");
        }
        else
        {
        // ---- force：脚本自己激活 → 采 → 立刻关回去 ----
        // 为什么不一上来全激活：50 个角色同时活着会互相遮挡/互相影响（相机取景、
        // 成对隔离渲染、以及"别的角色的脚本还在跑"），采出来的顺序会被污染。
        for (int ri = 0; ri < roots.Count; ri++)
        {
            if (!EditorApplication.isPlaying)
            {
                PlaySampleLog.W("[draworder] force：Play 已退出 → 停止（还剩 "
                                + (roots.Count - ri) + " 个目标）");
                yield break;
            }
            var root = roots[ri];
            if (root == null) continue;
            var openedChain = new List<GameObject>();   // 这次被我们打开的节点（含父链）
            var offRoots = new List<GameObject>();      // 这次被我们关掉的**其它角色根**
            var offRend = new List<Renderer>();         // 以及被关掉的它们的渲染器
            var offRendPrev = new List<bool>();
            var othersAll = new List<Renderer>();       // 目标之外的全部渲染器（成对隔离用）
            PlaySampleLog.W("[draworder] (" + (ri + 1) + "/" + roots.Count + ") → " + root.name);
            try
            {
                // ① 其它角色**整根关掉**（比只关渲染器更干净：脚本/Animator 也停），
                //    它们的渲染器顺带也关掉并记下原值。
                foreach (var other in roots)
                {
                    if (other == null || other == root) continue;
                    // 只处理**与目标没有父子关系**的目标：否则会把目标自己的
                    // 子/父节点关掉（那样这一帧就是空的）。
                    if (root.transform.IsChildOf(other.transform)
                        || other.transform.IsChildOf(root.transform)) continue;
                    foreach (var rd in other.GetComponentsInChildren<Renderer>(true))
                    {
                        offRend.Add(rd);
                        offRendPrev.Add(rd.enabled);
                        rd.enabled = false;
                    }
                    if (other.activeSelf) { other.SetActive(false); offRoots.Add(other); }
                }
                // 名单外的场景根（道具、别的模型）：只关渲染器，不动它的逻辑
                foreach (var go in SceneManager.GetActiveScene().GetRootGameObjects())
                {
                    if (go == root || go.transform.IsChildOf(root.transform)) continue;
                    if (root.transform.IsChildOf(go.transform)) continue;   // 目标的祖先也别关
                    if (roots.Any(r => r == go)) continue;      // 上面处理过了
                    foreach (var rd in go.GetComponentsInChildren<Renderer>(true))
                    {
                        offRend.Add(rd);
                        offRendPrev.Add(rd.enabled);
                        rd.enabled = false;
                    }
                }

                // ② **只激活这一个**（含父链），并给它一点时间（Awake/Start/Animator 绑定）
                if (cfg.activateInactive) openedChain.AddRange(CalibTargets.Activate(root));
                else if (!root.activeInHierarchy) CalibTargets.Activate(root);
                PlaySampleLog.W("   " + (openedChain.Count > 0
                                ? "激活了 " + openedChain.Count + " 个上级/自身节点（原本 inactive）"
                                : "目标本来就 active"));
                yield return null;
                yield return new WaitForEndOfFrame();
                othersAll.AddRange(offRend);

                // ③ 采样
                var sub = SampleTarget(root, outRoot, wantStates, times, cfg,
                                       ri + 1, roots.Count, othersAll, false);
                while (sub.MoveNext()) yield return sub.Current;
            }
            finally
            {
                // ④ 恢复现场：**这个角色关回去**（只关我们打开的那几个节点），
                //    其它角色的渲染器/根还原。
                for (int k = openedChain.Count - 1; k >= 0; k--)
                    if (openedChain[k] != null) openedChain[k].SetActive(false);
                for (int k = 0; k < offRend.Count; k++)
                    if (offRend[k] != null) offRend[k].enabled = offRendPrev[k];
                foreach (var g in offRoots) if (g != null) g.SetActive(true);
                PlaySampleLog.W("[draworder] (" + (ri + 1) + "/" + roots.Count
                                + ") 已恢复：" + root.name + " 关回 inactive，其它角色还原");
            }
        }
        }   // end else (force)
        if (cfg.exitAfter && EditorApplication.isPlaying) EditorApplication.ExitPlaymode();
        }
        finally
        {
            // 收尾：正常跑完 / 中途 yield break / 退出 Play 被 Dispose —— 三种情况都走到这里
            foreach (var go in _activated) if (go != null) go.SetActive(false);   // 只在 activateBeforePlay 时有内容
            _activated.Clear();
            // 临时实例化的角色：采完销毁（场景是"借来用一下"，不留在里面）
            foreach (var go in made)
                if (go != null && go.scene.IsValid()) UnityEngine.Object.DestroyImmediate(go);
            // 把临时禁用的探针还原
            foreach (var b in probesOff) if (b != null) b.enabled = true;
            if (probesOff.Count > 0)
                PlaySampleLog.W("[draworder] 已还原 " + probesOff.Count + " 个探针组件");
            PlaySampleLog.W("[draworder] 收尾完成（已还原临时改动）");
        }
    }

    /// <summary>
    /// 采一个目标：把它的每条状态 × 每个归一化时刻都出帧（两模式共用）。
    /// 里面**不改变场景的 activeSelf / enabled**（force 模式的开关在外面做）。
    /// </summary>
    private static IEnumerator SampleTarget(GameObject root, string outRoot,
                                            List<string> wantStates, float[] times,
                                            Cfg cfg, int targetIndex, int targetCount,
                                            List<Renderer> othersForPairs, bool observe)
    {
        string label = TargetLabel(root);
        string dir = Path.Combine(outRoot, "_draworder_" + label);
        Directory.CreateDirectory(Path.Combine(dir, "frames"));
        var animators = root.GetComponentsInChildren<Animator>(true);
        // 先把"要采哪些状态 × 哪些归一化时刻"列清楚（**全状态**时条数很多，
        // 先打一行预算出来，方便判断要跑多久）。
        var jobs = new List<KeyValuePair<StateEntry, AnimationClip>>();
        var animReenabled = new List<Animator>();     // 原本 disabled、被我们打开的 Animator
        for (int ai = 0; ai < animators.Length; ai++)
        {
            var an = animators[ai];
            if (an != null && !an.enabled)
            {
                an.enabled = true;
                animReenabled.Add(an);
                PlaySampleLog.W("   " + an.name + "：Animator 原本 disabled，已临时打开");
            }
            var ctrl = an != null ? an.runtimeAnimatorController as AnimatorController : null;
            if (ctrl == null) continue;
            foreach (var st in CollectStates(ctrl))
            {
                if (wantStates.Count > 0 && !wantStates.Contains(st.name)) continue;
                var clip = st.state.motion as AnimationClip;
                if (clip == null) { PlaySampleLog.W("   跳过 " + st.name + "：没有 clip"); continue; }
                jobs.Add(new KeyValuePair<StateEntry, AnimationClip>(st, clip));
            }
        }
        int framePlan = 0;
        foreach (var j in jobs) framePlan += NormsFor(cfg, times, j.Value).Count;
        PlaySampleLog.W("   计划：状态 " + jobs.Count + " 条，共 **" + framePlan
                        + " 帧**（时刻表 " + cfg.times + "，按"
                        + (cfg.timesRelative ? "归一化比例" : "秒") + "）");
        foreach (var job in jobs)
        {
            if (!EditorApplication.isPlaying)
            {
                PlaySampleLog.W("[draworder] Play 已退出 → 中止 " + root.name + " 的采样");
                yield break;
            }
            var st = job.Key;
            var clip = job.Value;
            var owner = animators.FirstOrDefault(a => a != null
                            && a.runtimeAnimatorController == st.ctrl) ?? animators[0];
            foreach (float norm in NormsFor(cfg, times, clip))
            {
                if (!EditorApplication.isPlaying) yield break;
                if (!StepRoot(animators, st, norm))
                {
                    PlaySampleLog.W("   " + st.name + "：步进失败，跳过");
                    continue;
                }
                yield return null;
                yield return new WaitForEndOfFrame();
                float shown = cfg.timesRelative ? norm : norm * Mathf.Max(1e-4f, clip.length);
                // 文件名整体压到 80 字符以内（含状态名/时刻），否则 Windows 路径会超 260
                string tag = ShortenTag(
                    label + "__" + Sanitize(st.name) + "__"
                    + (cfg.timesRelative ? "n" : "t")
                    + Mathf.RoundToInt(shown * 1000f).ToString("D4"), 80);
                ShotFrame(dir, root, owner, st, clip, shown, tag, cfg,
                          targetIndex, targetCount, othersForPairs, observe);
                yield return null;
            }
        }
        PlaySampleLog.W("[draworder] " + root.name + " 完成 → " + dir);
        foreach (var an in animReenabled)                       // 还原：不改场景的承诺
            if (an != null) an.enabled = false;
    }

    /// <summary>目标**之外**的全部渲染器（成对隔离时临时关，渲完还原）。</summary>
    private static List<Renderer> OthersOf(List<GameObject> roots, GameObject root)
    {
        var outList = new List<Renderer>();
        foreach (var go in SceneManager.GetActiveScene().GetRootGameObjects())
        {
            if (go == null || go == root) continue;
            if (go.transform.IsChildOf(root.transform)) continue;
            if (root.transform.IsChildOf(go.transform)) continue;
            foreach (var rd in go.GetComponentsInChildren<Renderer>(true)) outList.Add(rd);
        }
        return outList;
    }

    /// <summary>
    /// 该 clip 要采的**归一化时刻**（去重、升序）：
    /// `TimesRelative=true` 时 `times` 本身就是比例（0~1，按每条 clip 自己的时长折算），
    /// 这样长短差很多的 clip（2 s~12 s）都能采到同样节奏的 5 个点；
    /// 否则按**秒**换算，越界的会被夹到 1（可能重复，去重后自然变少）。
    /// </summary>
    private static List<float> NormsFor(Cfg cfg, float[] times, AnimationClip clip)
    {
        var set = new SortedSet<float>();
        float dur = Mathf.Max(1e-4f, clip.length);
        foreach (float t in times)
        {
            float n = cfg.timesRelative ? Mathf.Clamp01(t) : Mathf.Clamp01(t / dur);
            set.Add(Mathf.Round(n * 10000f) / 10000f);
        }
        return set.ToList();
    }

    /// <summary>把这台 Animator（以及同根其它 Animator 按各自默认状态）步进到目标时刻。</summary>
    private static bool StepRoot(Animator[] animators, StateEntry st, float norm)
    {
        try
        {
            foreach (var an in animators) an.Rebind();
            foreach (var an in animators)
            {
                if (an == null) continue;
                if (an.runtimeAnimatorController == st.ctrl) an.Play(st.hash, st.layer, norm);
                else an.Update(0f);
            }
            foreach (var an in animators) an.Update(0f);
            return true;
        }
        catch (Exception e)
        {
            PlaySampleLog.E("[draworder] 步进失败", e);
            return false;
        }
    }

    // ------------------------------------------------------------------ 出帧 + 导出
    private static void ShotFrame(string dir, GameObject root, Animator animator,
                                  StateEntry st, AnimationClip clip, float t,
                                  string tag, Cfg cfg,
                                  int targetIndex, int targetCount,
                                  List<Renderer> othersForPairs, bool observe)
    {
        Ctx main = null, small = null;
        try
        {
            var rends = root.GetComponentsInChildren<Renderer>(true)
                            .Where(r => r is SpriteRenderer || r is SkinnedMeshRenderer
                                        || r is MeshRenderer)
                            .ToArray();
            // 这批角色在场景里是 **Renderer 级 disabled**（游戏运行时按需开），
            // 光 SetActive(true) 画不出来 ⇒ 采样期间临时打开，采完在 finally 还原。
            var forced = new List<KeyValuePair<Renderer, bool>>();
            if (cfg.forceEnableRenderers && !observe)
            {
                foreach (var r in rends)
                {
                    if (r.enabled) continue;
                    forced.Add(new KeyValuePair<Renderer, bool>(r, r.enabled));
                    r.enabled = true;
                }
            }
            if (forced.Count > 0)
                PlaySampleLog.W("   " + tag + "：临时打开 " + forced.Count + "/" + rends.Length
                                + " 个原本 disabled 的渲染器（采完还原）");
            try
            {

            // 取景：只算"真的会画"的渲染器
            var b = new Bounds();
            bool has = false;
            foreach (var r in rends)
            {
                if (!r.enabled || !r.gameObject.activeInHierarchy) continue;
                if (r.bounds.size.sqrMagnitude < 1e-10f) continue;
                b.Encapsulate(r.bounds);
                has = true;
            }
            if (!has)
            {
                foreach (var r in rends)
                {
                    if (r.bounds.size.sqrMagnitude < 1e-10f) continue;
                    b.Encapsulate(r.bounds);
                    has = true;
                }
            }
            if (!has) { PlaySampleLog.W("[draworder] " + tag + "：没有可用包围盒，跳过"); return; }

            float halfH = Mathf.Max(1e-3f, b.extents.y) * cfg.margin;
            float halfW = Mathf.Max(1e-3f, b.extents.x) * cfg.margin;
            int w = Mathf.Clamp(Mathf.RoundToInt(halfW * 2f * cfg.ppu), 64, 4096);
            int h = Mathf.Clamp(Mathf.RoundToInt(halfH * 2f * cfg.ppu), 64, 4096);
            float aspect = (float)w / h;
            float size = Mathf.Max(halfH, halfW / aspect);
            Vector3 centre = b.center;

            main = MakeCtx(rends, centre, size, aspect, w, h, new Color(1f, 1f, 1f, 1f));

            // ---- ① 信息收集（枚举序 + DFS 序 + 排序键 + 屏幕包围盒）----
            var dfsIndex = BuildDfsIndex(root);
            var infos = new List<RInfo>();
            for (int i = 0; i < rends.Length; i++)
            {
                var r = rends[i];
                var info = new RInfo
                {
                    r = r,
                    idx = i,
                    dfs = dfsIndex.ContainsKey(r.transform) ? dfsIndex[r.transform] : -1,
                    path = RelPath(root, r.transform),
                    type = r.GetType().Name,
                    activeSelf = r.gameObject.activeSelf,
                    activeInHier = r.gameObject.activeInHierarchy,
                    enabled = r.enabled,
                    isVisible = r.isVisible,
                    layerId = r.sortingLayerID,
                    order = r.sortingOrder,
                    priority = r.rendererPriority,
                    center = r.bounds.center,
                    size = r.bounds.size,
                };
                info.tieKey = TieKey(info);
                // Unity 自己的排序键（内部属性，反射读；读不到就是 -1）
                info.uKey = SortingKeyOf(r);
                info.groupId = ReflectedInt(r, "sortingGroupID", ref _pGroupId);
                info.groupOrder = ReflectedInt(r, "sortingGroupOrder", ref _pGroupOrder);
                var sr = r as SpriteRenderer;
                if (sr != null && sr.sprite != null)
                {
                    info.sprite = sr.sprite.name;
                    info.texture = sr.sprite.texture != null ? sr.sprite.texture.name : "";
                }
                var smr = r as SkinnedMeshRenderer;
                if (smr != null && smr.sharedMesh != null)
                {
                    info.mesh = smr.sharedMesh.name;
                    info.verts = smr.sharedMesh.vertexCount;
                }
                var mf = r.GetComponent<MeshFilter>();
                if (mf != null && mf.sharedMesh != null)
                {
                    info.mesh = mf.sharedMesh.name;
                    info.verts = mf.sharedMesh.vertexCount;
                }
                var mats = r.sharedMaterials;
                info.mats = mats.Where(m => m != null).Select(m => m.name).ToArray();
                info.shaders = mats.Where(m => m != null && m.shader != null)
                                   .Select(m => m.shader.name).ToArray();
                var m0 = mats.FirstOrDefault(m => m != null);
                if (m0 != null)
                {
                    info.queue = m0.renderQueue;
                    try
                    {
                        if (m0.HasProperty("_SrcBlend")) info.srcBlend = (int)m0.GetFloat("_SrcBlend");
                        if (m0.HasProperty("_DstBlend")) info.dstBlend = (int)m0.GetFloat("_DstBlend");
                        if (m0.HasProperty("_ZWrite")) info.zWrite = (int)m0.GetFloat("_ZWrite");
                    }
                    catch (Exception) { /* 有些 shader 读不到属性，忽略 */ }
                }
                info.camDepth = Vector3.Dot(info.center - main.cam.transform.position,
                                            main.cam.transform.forward);
                info.nodeDepth = Vector3.Dot(r.transform.position - main.cam.transform.position,
                                             main.cam.transform.forward);
                info.dist = Vector3.Distance(info.center, main.cam.transform.position);
                var c0 = info.center - new Vector3(info.size.x, info.size.y, 0f) * 0.5f;
                var c1 = info.center + new Vector3(info.size.x, info.size.y, 0f) * 0.5f;
                var p0 = main.cam.WorldToScreenPoint(c0);
                var p1 = main.cam.WorldToScreenPoint(c1);
                info.sMin = new Vector2(Mathf.Min(p0.x, p1.x), Mathf.Min(p0.y, p1.y));
                info.sMax = new Vector2(Mathf.Max(p0.x, p1.x), Mathf.Max(p0.y, p1.y));
                infos.Add(info);
            }
            var allRend = infos.Select(x => x.r).ToArray();
            main.all = allRend;
            // 主帧默认**不**做隔离（= 正常 Play 的样子）；要干净参考帧就开 IsolateFrame
            if (cfg.isolateFrame && othersForPairs != null && othersForPairs.Count > 0)
                main.extraOff = othersForPairs;

            // 安全网：这一帧到底有几个渲染器是"真的会画"的？0 个 = 目标没被真正激活
            // （或者被别的目标关掉了），这种帧是废的，要立刻喊出来而不是静默出空图。
            int nVis = infos.Count(x => x.enabled && x.activeInHier);
            if (nVis == 0)
                PlaySampleLog.E("[draworder] " + tag + "：可见渲染器 **0** 个"
                                + "（目标 activeInHierarchy=" + root.activeInHierarchy
                                + "，渲染器 " + infos.Count + " 个）—— 这帧是空的，检查目标选择");

            // ---- ② 真实帧 ----
            main.RenderOnly(allRend);
            if (cfg.saveFramePng)
            {
                SavePng(main.tex, Path.Combine(dir, "frames", tag + ".png"));
                File.WriteAllText(Path.Combine(dir, "frames", tag + "_cam.txt"),
                    "cx=" + F(centre.x) + "\ncy=" + F(centre.y) +
                    "\nsize=" + F(size) + "\naspect=" + F(aspect) +
                    "\nw=" + w + "\nh=" + h + "\nppu=" + F(cfg.ppu) + "\n");
            }

            // ---- ③ 并列分组 ----
            var groups = new List<KeyValuePair<string, List<RInfo>>>();
            var byKey = new Dictionary<string, List<RInfo>>();
            foreach (var info in infos)
            {
                if (!byKey.ContainsKey(info.tieKey)) byKey[info.tieKey] = new List<RInfo>();
                byKey[info.tieKey].Add(info);
            }
            foreach (var kv in byKey.OrderBy(k => k.Value.Min(i => i.idx)))
            {
                if (kv.Value.Count < 2) continue;
                groups.Add(kv);
            }
            for (int g = 0; g < groups.Count; g++)
                foreach (var info in groups[g].Value) info.tieGroup = g;

            // ---- ④ 成对实测 ----
            string scope = scopeOf(cfg);
            var pairs = new List<PairResult>();
            if (scope != "off")
            {
                var visibles = infos.Where(i => i.enabled && i.activeInHier
                                                && i.size.sqrMagnitude > 1e-10f).ToList();
                var todo = new List<int[]>();
                if (scope == "all")
                {
                    for (int i = 0; i < visibles.Count; i++)
                        for (int j = i + 1; j < visibles.Count; j++)
                            if (Overlap(visibles[i], visibles[j]))
                                todo.Add(new[] { visibles[i].idx, visibles[j].idx });
                }
                else
                {
                    foreach (var kv in groups)
                    {
                        var mem = kv.Value.Where(i => i.enabled && i.activeInHier
                                                      && i.size.sqrMagnitude > 1e-10f)
                                          .OrderBy(i => i.idx).ToList();
                        for (int i = 0; i < mem.Count; i++)
                            for (int j = i + 1; j < mem.Count; j++)
                                if (Overlap(mem[i], mem[j]))
                                    todo.Add(new[] { mem[i].idx, mem[j].idx });
                    }
                }
                string pairsDir = Path.Combine(dir, "frames", "pairs");
                if (cfg.writeImages) Directory.CreateDirectory(pairsDir);
                if (todo.Count > 0)
                {
                    // 上限保护：`all` 时重叠对可能上千；同并列组的最有用，优先保留。
                    if (cfg.pairCap > 0 && todo.Count > cfg.pairCap)
                    {
                        var gOf = new Dictionary<int, int>();
                        foreach (var x in infos) gOf[x.idx] = x.tieGroup;
                        int before = todo.Count;
                        todo = todo
                            .OrderBy(pr => (gOf[pr[0]] >= 0 && gOf[pr[0]] == gOf[pr[1]]) ? 0 : 1)
                            .ThenBy(pr => pr[0]).ThenBy(pr => pr[1])
                            .Take(cfg.pairCap).ToList();
                        PlaySampleLog.W("   " + tag + "：成对实测 " + before + " 对超过上限 "
                                        + cfg.pairCap + "，按「同并列组优先」截断到 "
                                        + todo.Count + "（要全量就调大 PairCap）");
                    }
                    small = MakeCtx(rends, centre, size, aspect,
                                    Mathf.Clamp(Mathf.RoundToInt(cfg.pairPpu * aspect), 64, 2048),
                                    Mathf.Clamp(Mathf.RoundToInt(cfg.pairPpu), 64, 2048),
                                    new Color(0f, 0f, 0f, 0f));
                    // 注意：小 RT 用**透明底**，隔离图才能直接当"覆盖蒙版"看。
                    // 成对判定时把**别的角色**也临时关掉（只影响判定，渲完立刻还原），
                    // 否则别的角色的像素会污染"谁盖谁"。
                    if (othersForPairs != null && othersForPairs.Count > 0)
                        small.extraOff = othersForPairs;
                    PlaySampleLog.W("[draworder] " + tag + "：成对实测 " + todo.Count
                                    + " 对（scope=" + scope + "，可见 " + visibles.Count
                                    + " 个，分辨率 " + small.rt.width + "x" + small.rt.height + "）");
                    var isoCache = new Dictionary<int, Color32[]>();
                    for (int k = 0; k < todo.Count; k++)
                    {
                        var pr = todo[k];
                        var A = GetIso(pr[0], small, isoCache, cfg, pairsDir, tag);
                        var B = GetIso(pr[1], small, isoCache, cfg, pairsDir, tag);
                        var AB = small.RenderOnly(new HashSet<Renderer>
                                                  { allRend[pr[0]], allRend[pr[1]] });
                        if (cfg.writeImages)
                            SavePng32(AB, small.rt.width, small.rt.height,
                                      Path.Combine(pairsDir, tag + "__pair_"
                                                   + pr[0] + "_" + pr[1] + ".png"));
                        pairs.Add(Classify(A, B, AB, pr[0], pr[1]));
                    }
                }
            }

            // ---- ⑤ 组内实测顺序 + 全局顺序 ----
            foreach (var kv in groups)
            {
                var mem = kv.Value.Where(i => i.enabled && i.activeInHier).ToList();
                var idxSet = new HashSet<int>(mem.Select(m => m.idx));
                var rel = pairs.Where(p => idxSet.Contains(p.a) && idxSet.Contains(p.b)).ToList();
                var order = TopoOrder(mem.OrderBy(m => m.idx).Select(m => m.idx).ToList(), rel);
                for (int k = 0; k < order.Count; k++)
                {
                    var info = mem.FirstOrDefault(m => m.idx == order[k]);
                    if (info != null) info.tieRank = k;
                }
            }
            var visibleAll = infos.Where(i => i.enabled && i.activeInHier
                                              && i.size.sqrMagnitude > 1e-10f).ToList();
            var globalOrder = visibleAll
                .OrderBy(i => i.layerId)
                .ThenBy(i => i.order)
                .ThenByDescending(i => i.camDepth)
                .ThenBy(i => i.tieRank < 0 ? i.idx : i.tieRank)
                .ThenBy(i => i.idx)
                .Select(i => i.idx).ToArray();

            // ---- ⑥ 写 JSON ----
            string path = Path.Combine(dir, tag + ".json");
            WriteJson(path, root, animator, st, clip, t, main.cam, w, h, size, aspect,
                      infos, groups, pairs, globalOrder, scope,
                      targetIndex, targetCount);
            int groupsWithTies = groups.Count(g => g.Value.Count(i => i.enabled && i.activeInHier) > 1);
            int matched = groups.Count(g =>
            {
                var vis = g.Value.Where(i => i.enabled && i.activeInHier).ToList();
                var dfs = vis.OrderBy(i => i.dfs).Select(i => i.idx).ToList();
                var emp = vis.OrderBy(i => i.tieRank < 0 ? 9999 : i.tieRank)
                             .ThenBy(i => i.idx).Select(i => i.idx).ToList();
                return dfs.Count == emp.Count && dfs.SequenceEqual(emp);
            });
            PlaySampleLog.W("[draworder] " + tag + " → " + path
                            + "（渲染器 " + infos.Count + "，可见 " + nVis
                            + "，含并列的组 " + groupsWithTies
                            + "，实测对 " + pairs.Count + "，与 DFS 序一致的组 " + matched + "）");
            }
            finally
            {
                // 还原"临时打开的渲染器"
                for (int i = 0; i < forced.Count; i++)
                    if (forced[i].Key != null) forced[i].Key.enabled = forced[i].Value;
            }
        }
        catch (Exception e)
        {
            PlaySampleLog.E("[draworder] " + tag + " 出帧失败", e);
        }
        finally
        {
            if (small != null) small.Dispose();
            if (main != null) main.Dispose();
        }
    }

    private static Ctx MakeCtx(Renderer[] rends, Vector3 centre, float size, float aspect,
                               int w, int h, Color bg)
    {
        var camObj = new GameObject("draworder_cam");
        var cam = camObj.AddComponent<Camera>();
        cam.orthographic = true;
        cam.orthographicSize = size;
        cam.transform.position = new Vector3(centre.x, centre.y, -10f);
        cam.transform.LookAt(new Vector3(centre.x, centre.y, 0f));
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = bg;
        cam.nearClipPlane = 0.01f;
        cam.farClipPlane = 100f;
        var rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32);
        cam.targetTexture = rt;
        return new Ctx
        {
            cam = cam,
            rt = rt,
            tex = new Texture2D(w, h, TextureFormat.RGBA32, false),
            all = rends,
            baseEnabled = rends.Select(r => r.enabled).ToArray(),
        };
    }

    private static Color32[] GetIso(int idx, Ctx ctx, Dictionary<int, Color32[]> cache,
                                    Cfg cfg, string pairsDir, string tag)
    {
        Color32[] img;
        if (cache.TryGetValue(idx, out img)) return img;
        img = ctx.RenderOnly(new HashSet<Renderer> { ctx.all[idx] });
        cache[idx] = img;
        if (cfg.writeImages)
            SavePng32(img, ctx.rt.width, ctx.rt.height,
                      Path.Combine(pairsDir, tag + "__iso_" + idx + ".png"));
        return img;
    }

    // ------------------------------------------------------------------ 判定
    /// <summary>用"不透明投票 + 两种混合模型的误差"判定这一对谁在上面。</summary>
    private static PairResult Classify(Color32[] A, Color32[] B, Color32[] AB, int ia, int ib)
    {
        var res = new PairResult { a = ia, b = ib };
        double sumPremulA = 0, sumPremulB = 0, sumStraightA = 0, sumStraightB = 0;
        int both = 0, vA = 0, vB = 0;
        for (int p = 0; p < AB.Length; p++)
        {
            var a = A[p];
            var b = B[p];
            // 只在**两个件都覆盖**的像素上判定：只覆盖一个的像素上，
            // "a 在上"和"b 在上"给出的预测完全相同 —— 那里没有信息，
            // 而且拿它投票会让"面积大但不重叠"的件产生假票（2026-09-17 修）。
            if (a.a < 8 || b.a < 8) continue;
            both++;
            if (a.a > 250)
            {
                int dA = Dist(AB[p], a), dB = Dist(AB[p], b);
                if (dA <= 6 && dB > 24) vA++;
            }
            if (b.a > 250)
            {
                int dA = Dist(AB[p], a), dB = Dist(AB[p], b);
                if (dB <= 6 && dA > 24) vB++;
            }
            var pA = Over(a, b, true);   // a 在上（存储预乘）
            var pB = Over(b, a, true);
            var sA = Over(a, b, false);  // a 在上（存储 straight）
            var sB = Over(b, a, false);
            sumPremulA += Diff(pA, AB[p]);
            sumPremulB += Diff(pB, AB[p]);
            sumStraightA += Diff(sA, AB[p]);
            sumStraightB += Diff(sB, AB[p]);
        }
        res.overlap = both;
        res.votesA = vA;
        res.votesB = vB;
        if (both < 8) { res.verdict = "no-overlap"; return res; }
        double cnt = Math.Max(1, both);
        double premulA = sumPremulA / (3 * cnt), premulB = sumPremulB / (3 * cnt);
        double straightA = sumStraightA / (3 * cnt), straightB = sumStraightB / (3 * cnt);
        double bestA = Math.Min(premulA, straightA);
        double bestB = Math.Min(premulB, straightB);
        res.errA = (float)bestA;
        res.errB = (float)bestB;
        res.model = (premulA <= straightA) && (premulB <= straightB) ? "premul"
                  : (premulA > straightA) && (premulB > straightB) ? "straight" : "mixed";

        string byVotes = null;
        if (vA > vB * 1.2 && vA >= 20) byVotes = "a-above-b";
        else if (vB > vA * 1.2 && vB >= 20) byVotes = "b-above-a";

        // 注意方向：errA 是"a 在上"那张预测图的误差 ⇒ errA 小 = 实际就是 a 在上。
        string byModel = null;
        if (bestA < bestB * 0.5 && bestA < 12.0) byModel = "a-above-b";
        else if (bestB < bestA * 0.5 && bestB < 12.0) byModel = "b-above-a";

        if (byVotes != null && byModel != null && byVotes == byModel) res.verdict = byVotes;
        else if (byVotes != null && byModel == null) res.verdict = byVotes + "?votes";
        else if (byVotes == null && byModel != null) res.verdict = byModel + "?model";
        else if (byVotes != null && byModel != null) res.verdict = "conflict";
        else res.verdict = "ambiguous";
        return res;
    }

    private static int Dist(Color32 x, Color32 y)
    {
        return Math.Max(Math.Abs(x.r - y.r),
               Math.Max(Math.Abs(x.g - y.g), Math.Abs(x.b - y.b)));
    }

    private static double Diff(double[] pred, Color32 actual)
    {
        return Math.Abs(pred[0] - actual.r) + Math.Abs(pred[1] - actual.g)
             + Math.Abs(pred[2] - actual.b);
    }

    /// <summary>
    /// `top over bottom`。`storedPremultiplied=true` 时输入/输出都是**已预乘**的颜色
    /// （Sprites/Default 是 `Blend One OneMinusSrcAlpha` + fragment 里 `c.rgb *= c.a`）；
    /// 否则按 straight alpha 进出。
    /// </summary>
    private static double[] Over(Color32 top, Color32 bottom, bool storedPremultiplied)
    {
        double ta = top.a / 255.0;
        double ba = bottom.a / 255.0;
        double oa = ta + ba * (1 - ta);
        if (oa <= 1e-6) return new double[] { 0, 0, 0 };
        double tr = top.r, tg = top.g, tb = top.b;
        double br = bottom.r, bg = bottom.g, bb = bottom.b;
        if (!storedPremultiplied) { tr *= ta; tg *= ta; tb *= ta; br *= ba; bg *= ba; bb *= ba; }
        double r = tr + br * (1 - ta);
        double g = tg + bg * (1 - ta);
        double b = tb + bb * (1 - ta);
        if (!storedPremultiplied) { r /= oa; g /= oa; b /= oa; }
        return new double[] { r, g, b };
    }

    private static bool Overlap(RInfo x, RInfo y)
    {
        return !(x.sMax.x < y.sMin.x || y.sMax.x < x.sMin.x
                 || x.sMax.y < y.sMin.y || y.sMax.y < x.sMin.y);
    }

    /// <summary>把"谁盖谁"的关系拓扑排序，返回 **先画 → 后画** 的下标表。</summary>
    private static List<int> TopoOrder(List<int> nodes, List<PairResult> rel)
    {
        var mustBefore = new Dictionary<int, HashSet<int>>();   // mustBefore[x]：必须在 x 之前画
        var followers = new Dictionary<int, HashSet<int>>();
        foreach (var n in nodes) { mustBefore[n] = new HashSet<int>(); followers[n] = new HashSet<int>(); }
        foreach (var p in rel)
        {
            if (!mustBefore.ContainsKey(p.a) || !mustBefore.ContainsKey(p.b)) continue;
            int top, bot;
            if (p.verdict != null && p.verdict.StartsWith("a-above-b")) { top = p.a; bot = p.b; }
            else if (p.verdict != null && p.verdict.StartsWith("b-above-a")) { top = p.b; bot = p.a; }
            else continue;
            mustBefore[top].Add(bot);
            followers[bot].Add(top);
        }
        var indeg = new Dictionary<int, int>();
        foreach (var n in nodes) indeg[n] = mustBefore[n].Count;
        var ready = nodes.Where(n => indeg[n] == 0).OrderBy(n => n).ToList();
        var outList = new List<int>();
        while (ready.Count > 0)
        {
            int n = ready[0];
            ready.RemoveAt(0);
            outList.Add(n);
            foreach (var m in followers[n])
            {
                indeg[m]--;
                if (indeg[m] == 0) { ready.Add(m); ready.Sort(); }
            }
        }
        foreach (var n in nodes) if (!outList.Contains(n)) outList.Add(n);   // 有环时兜底
        return outList;
    }

    /// <summary>并列键：同 layer + 同 sortingOrder + 同深度（按 1e-3 世界单位归并）。</summary>
    private static string TieKey(Renderer r)
    {
        return TieKey2(r.sortingLayerID, r.sortingOrder, r.bounds.center.z);
    }

    private static string TieKey(RInfo x)
    {
        return TieKey2(x.layerId, x.order, x.center.z);
    }

    private static string TieKey2(int layerId, int order, float z)
    {
        return layerId + "|" + order + "|" + Mathf.RoundToInt(z * 1000f);
    }

    private static Dictionary<Transform, int> BuildDfsIndex(GameObject root)
    {
        var map = new Dictionary<Transform, int>();
        int n = 0;
        // 父 → 子，按 siblingIndex（= Unity 的 m_Children 顺序）深度优先
        Action<Transform> walk = null;
        walk = tr =>
        {
            map[tr] = n++;
            for (int i = 0; i < tr.childCount; i++) walk(tr.GetChild(i));
        };
        walk(root.transform);
        return map;
    }

    // ------------------------------------------------------------------ JSON
    private static void WriteJson(string path, GameObject root, Animator animator,
                                  StateEntry st, AnimationClip clip, float t,
                                  Camera cam, int w, int h, float size, float aspect,
                                  List<RInfo> infos,
                                  List<KeyValuePair<string, List<RInfo>>> groups,
                                  List<PairResult> pairs, int[] globalOrder, string scope,
                                  int targetIndex, int targetCount)
    {
        var sb = new StringBuilder();
        sb.Append("{\n");
        sb.Append("  \"character\": ").Append(Str(root.name)).Append(",\n");
        sb.Append("  \"animator\": ").Append(Str(animator != null ? animator.name : "")).Append(",\n");
        sb.Append("  \"state\": ").Append(Str(st.name)).Append(",\n");
        sb.Append("  \"clip\": ").Append(Str(clip.name)).Append(",\n");
        sb.Append("  \"clipLength\": ").Append(F(clip.length)).Append(",\n");
        sb.Append("  \"t\": ").Append(F(t)).Append(",\n");
        sb.Append("  \"norm\": ").Append(F(t / Mathf.Max(1e-4f, clip.length))).Append(",\n");
        sb.Append("  \"unityVersion\": ").Append(Str(Application.unityVersion)).Append(",\n");
        sb.Append("  \"pairScope\": ").Append(Str(scope)).Append(",\n");
        sb.Append("  \"targetIndex\": ").Append(targetIndex)
          .Append(", \"targetCount\": ").Append(targetCount)
          .Append(", \"isolated\": true")
          .Append(", \"isolationNote\": ")
          .Append(Str("采样这一帧时，场景里只有本角色是 active 的：脚本逐个激活目标 → "
                      + "采完立刻把它的父链关回 inactive、其它角色还原。"))
          .Append(",\n");
        sb.Append("  \"explain\": ")
          .Append(Str("drawOrderFirstToLast = 先画→后画（后面的盖前面的）。"
                      + "sortKey = [sortingLayerID, sortingOrder, -camDepth]，升序=先画。"
                      + "camDepth = 包围盒中心沿相机视线方向的深度（nodeDepth 是节点位置的），"
                      + "越大 = 离相机越远 = 越先画。"
                      + "tieGroup>=0 表示与同组其它渲染器的排序键完全并列，先后只能由提交顺序"
                      + "决定，本文件用成对隔离渲染实测给出 tieRank。"
                      + "pairs[].verdict：a-above-b = a 画在 b 之后（a 盖住 b）；带 ?votes/?model "
                      + "表示只有一条证据成立；conflict = 两条证据打架；ambiguous = 都没结论。"
                      + "votes* 是不透明像素投票数，err* 是两种混合模型里最好的平均误差。"))
          .Append(",\n");
        sb.Append("  \"camera\": { \"cx\": ").Append(F(cam.transform.position.x))
          .Append(", \"cy\": ").Append(F(cam.transform.position.y))
          .Append(", \"z\": ").Append(F(cam.transform.position.z))
          .Append(", \"size\": ").Append(F(size))
          .Append(", \"aspect\": ").Append(F(aspect))
          .Append(", \"w\": ").Append(w).Append(", \"h\": ").Append(h)
          .Append(", \"ppu\": ").Append(F(h / (2f * size)))
          .Append(", \"pos\": [").Append(F(cam.transform.position.x)).Append(",")
          .Append(F(cam.transform.position.y)).Append(",")
          .Append(F(cam.transform.position.z)).Append("]")
          .Append(", \"forward\": [").Append(F(cam.transform.forward.x)).Append(",")
          .Append(F(cam.transform.forward.y)).Append(",")
          .Append(F(cam.transform.forward.z)).Append("]")
          .Append(", \"transparencySortMode\": ").Append(Str(cam.transparencySortMode.ToString()))
          .Append(", \"transparencySortAxis\": [")
          .Append(F(cam.transparencySortAxis.x)).Append(",")
          .Append(F(cam.transparencySortAxis.y)).Append(",")
          .Append(F(cam.transparencySortAxis.z)).Append("]")
          .Append(", \"graphicsTransparencySortMode\": ")
          .Append(Str(UnityEngine.Rendering.GraphicsSettings.transparencySortMode.ToString()))
          .Append(" },\n");

        sb.Append("  \"rendererCount\": ").Append(infos.Count).Append(",\n");
        sb.Append("  \"renderers\": [\n");
        for (int i = 0; i < infos.Count; i++)
        {
            var x = infos[i];
            sb.Append("    { \"i\": ").Append(x.idx)
              .Append(", \"path\": ").Append(Str(x.path))
              .Append(", \"node\": ").Append(Str(x.r.transform.name))
              .Append(", \"type\": ").Append(Str(x.type))
              .Append(", \"enumIndex\": ").Append(x.idx)
              .Append(", \"dfsIndex\": ").Append(x.dfs)
              .Append(", \"instanceID\": ").Append(x.r.GetInstanceID())
              .Append(", \"activeSelf\": ").Append(B(x.activeSelf))
              .Append(", \"activeInHierarchy\": ").Append(B(x.activeInHier))
              .Append(", \"enabled\": ").Append(B(x.enabled))
              .Append(", \"isVisible\": ").Append(B(x.isVisible))
              .Append(", \"sortingLayerID\": ").Append(x.layerId)
              .Append(", \"sortingLayerName\": ").Append(Str(x.r.sortingLayerName))
              .Append(", \"sortingOrder\": ").Append(x.order)
              .Append(", \"rendererPriority\": ").Append(x.priority)
              .Append(", \"renderQueue\": ").Append(x.queue)
              .Append(", \"blend\": { \"src\": ").Append(x.srcBlend)
              .Append(", \"dst\": ").Append(x.dstBlend)
              .Append(", \"zWrite\": ").Append(x.zWrite).Append(" }")
              .Append(", \"materials\": [")
              .Append(string.Join(",", x.mats.Select(Str).ToArray())).Append("]")
              .Append(", \"shaders\": [")
              .Append(string.Join(",", x.shaders.Select(Str).ToArray())).Append("]")
              .Append(", \"boundsCenter\": [").Append(F(x.center.x)).Append(",")
              .Append(F(x.center.y)).Append(",").Append(F(x.center.z)).Append("]")
              .Append(", \"boundsSize\": [").Append(F(x.size.x)).Append(",")
              .Append(F(x.size.y)).Append(",").Append(F(x.size.z)).Append("]")
              .Append(", \"camDepth\": ").Append(F(x.camDepth))
              .Append(", \"nodeDepth\": ").Append(F(x.nodeDepth))
              .Append(", \"distToCam\": ").Append(F(x.dist))
              .Append(", \"screenBox\": [").Append(F(x.sMin.x)).Append(",")
              .Append(F(x.sMin.y)).Append(",").Append(F(x.sMax.x)).Append(",")
              .Append(F(x.sMax.y)).Append("]")
              .Append(", \"sprite\": ").Append(Str(x.sprite))
              .Append(", \"texture\": ").Append(Str(x.texture))
              .Append(", \"mesh\": ").Append(Str(x.mesh))
              .Append(", \"meshVerts\": ").Append(x.verts)
              .Append(", \"sortKey\": [").Append(x.layerId).Append(",")
              .Append(x.order).Append(",").Append(F(-x.camDepth)).Append("]")
              .Append(", \"unitySortingKey\": ").Append(x.uKey)
              .Append(", \"sortingGroupID\": ").Append(x.groupId)
              .Append(", \"sortingGroupOrder\": ").Append(x.groupOrder)
              .Append(", \"tieKey\": ").Append(Str(x.tieKey))
              .Append(", \"tieGroup\": ").Append(x.tieGroup)
              .Append(", \"tieRank\": ").Append(x.tieRank)
              .Append(" }");
            if (i + 1 < infos.Count) sb.Append(",");
            sb.Append("\n");
        }
        sb.Append("  ],\n");

        sb.Append("  \"tieGroups\": [\n");
        for (int g = 0; g < groups.Count; g++)
        {
            var mem = groups[g].Value.OrderBy(x => x.idx).ToList();
            var vis = mem.Where(x => x.enabled && x.activeInHier).ToList();
            var dfsOrder = vis.OrderBy(x => x.dfs).Select(x => x.idx).ToList();
            var empirical = vis.OrderBy(x => x.tieRank < 0 ? 9999 : x.tieRank)
                               .ThenBy(x => x.idx).Select(x => x.idx).ToList();
            bool match = dfsOrder.Count == empirical.Count && dfsOrder.SequenceEqual(empirical);
            sb.Append("    { \"id\": ").Append(g)
              .Append(", \"tieKey\": ").Append(Str(groups[g].Key))
              .Append(", \"sortingLayerID\": ").Append(mem[0].layerId)
              .Append(", \"sortingOrder\": ").Append(mem[0].order)
              .Append(", \"camDepth\": ").Append(F(mem[0].camDepth))
              .Append(", \"members\": [")
              .Append(string.Join(",", mem.Select(x => x.idx.ToString()).ToArray()))
              .Append("], \"visibleMembers\": [")
              .Append(string.Join(",", vis.Select(x => x.idx.ToString()).ToArray()))
              .Append("], \"dfsOrder\": [")
              .Append(string.Join(",", dfsOrder.Select(x => x.ToString()).ToArray()))
              .Append("], \"empiricalOrder\": [")
              .Append(string.Join(",", empirical.Select(x => x.ToString()).ToArray()))
              .Append("], \"matchesDfs\": ").Append(B(match))
              .Append(" }");
            if (g + 1 < groups.Count) sb.Append(",");
            sb.Append("\n");
        }
        sb.Append("  ],\n");

        sb.Append("  \"pairs\": [\n");
        for (int i = 0; i < pairs.Count; i++)
        {
            var p = pairs[i];
            sb.Append("    { \"a\": ").Append(p.a)
              .Append(", \"b\": ").Append(p.b)
              .Append(", \"verdict\": ").Append(Str(p.verdict))
              .Append(", \"model\": ").Append(Str(p.model))
              .Append(", \"votesA\": ").Append(p.votesA)
              .Append(", \"votesB\": ").Append(p.votesB)
              .Append(", \"errA\": ").Append(F(p.errA))
              .Append(", \"errB\": ").Append(F(p.errB))
              .Append(", \"overlapPx\": ").Append(p.overlap)
              .Append(" }");
            if (i + 1 < pairs.Count) sb.Append(",");
            sb.Append("\n");
        }
        sb.Append("  ],\n");

        sb.Append("  \"drawOrderFirstToLast\": [")
          .Append(string.Join(",", globalOrder.Select(x => x.ToString()).ToArray()))
          .Append("]\n");
        sb.Append("}\n");
        File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
    }

    // ------------------------------------------------------------------ 小工具
    private static string scopeOf(Cfg cfg)
    {
        return (cfg.pairScope ?? "tie").Trim().ToLowerInvariant();
    }

    /// <summary>是不是"观察模式"（不改场景，等游戏自己显示）。</summary>
    private static bool IsObserve(Cfg cfg)
    {
        return (cfg.touchMode ?? "observe").Trim().ToLowerInvariant() == "observe";
    }

    /// <summary>目标"现在是不是游戏正常显示的样子"：根 active 且有渲染器 enabled。</summary>
    /// <summary>
    /// Unity **自己的排序键**（`Renderer.sortingKey`，内部属性，公开 API 读不到）。
    /// 反汇编（`ForwardShaderRenderLoop::RenderObjectSorter<0>::operator()` @0x180440CC5）
    /// 显示排序第一顺位就是它，所以能读到就直接拿它当第一判据；读不到就返回 -1。
    /// 另外顺带读 `sortingGroupID/Order`（SortingGroup 相关）。
    /// </summary>
    private static PropertyInfo _pKey, _pGroupId, _pGroupOrder;

    private static long SortingKeyOf(Renderer r)
    {
        try
        {
            if (_pKey == null)
                _pKey = typeof(Renderer).GetProperty(
                    "sortingKey", BindingFlags.Instance | BindingFlags.Public
                                  | BindingFlags.NonPublic);
            if (_pKey == null) return -1;
            object v = _pKey.GetValue(r, null);
            return v == null ? -1 : Convert.ToInt64(v);
        }
        catch (Exception) { return -1; }
    }

    private static int ReflectedInt(Renderer r, string name, ref PropertyInfo cache)
    {
        try
        {
            if (cache == null)
                cache = typeof(Renderer).GetProperty(
                    name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (cache == null) return -1;
            object v = cache.GetValue(r, null);
            return v == null ? -1 : Convert.ToInt32(v);
        }
        catch (Exception) { return -1; }
    }

    private static bool TargetVisible(GameObject root)
    {
        if (root == null || !root.activeInHierarchy) return false;
        foreach (var r in root.GetComponentsInChildren<Renderer>(true))
            if (r.enabled) return true;
        return false;
    }

    private static int CountVisible(GameObject root)
    {
        int n = 0;
        foreach (var r in root.GetComponentsInChildren<Renderer>(true))
            if (r.enabled && r.gameObject.activeInHierarchy) n++;
        return n;
    }

    /// <summary>
    /// 目标的"标签"：从场景根到它自己的**完整路径**（用 `__` 连接）。
    /// 为什么不能只用 `name`：这批场景里有多个角色的子节点同名（`size_root`、
    /// `ch_root`…），只用名字会让不同角色的产物互相覆盖。
    /// ⚠️ 但路径太长会撞 Windows 260 字符限制（实测 18:26 那批
    /// `bloodypanther_skin1__…__BR_BloodyPanther_NS1_Back` 就写 `_cam.txt` 失败），
    /// 所以太长时退化成"首段 + 末段 + 路径哈希"。
    /// </summary>
    private static string TargetLabel(GameObject go)
    {
        var parts = new List<string>();
        for (Transform t = go.transform; t != null; t = t.parent) parts.Add(t.name);
        parts.Reverse();
        string full = Sanitize(string.Join("__", parts.ToArray()));
        if (full.Length <= 44) return full;
        string head = Sanitize(parts[0]);
        string tail = Sanitize(parts[parts.Count - 1]);
        return (head.Length > 16 ? head.Substring(0, 16) : head) + "__"
               + (tail.Length > 12 ? tail.Substring(0, 12) : tail) + "_"
               + Hash8(full);
    }

    /// <summary>把整体标签压到 `max` 字符以内（超了保留前缀 + 哈希），防路径超长。</summary>
    private static string ShortenTag(string s, int max)
    {
        if (s == null) return "";
        if (s.Length <= max) return s;
        return s.Substring(0, Mathf.Max(1, max - 9)) + "_" + Hash8(s);
    }

    private static string Hash8(string s)
    {
        int h = 17;
        foreach (char c in s) h = unchecked(h * 31 + c);
        return (h & 0x7fffffff).ToString("x8");
    }

    private static void SavePng(Texture2D tex, string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.WriteAllBytes(path, tex.EncodeToPNG());
    }

    private static void SavePng32(Color32[] px, int w, int h, string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        var t = new Texture2D(w, h, TextureFormat.RGBA32, false);
        t.SetPixels32(px);      // ReadPixels 与 Texture2D 都是左下原点，直接写
        t.Apply();
        File.WriteAllBytes(path, t.EncodeToPNG());
        UnityEngine.Object.DestroyImmediate(t);
    }

    private static IEnumerable<GameObject> FindRoots(Cfg cfg)
    {
        var names = Split(cfg.names);
        if (names.Count == 1 && names[0] == "*") names.Clear();     // "*" = 全场景
        var all = new List<GameObject>();
        foreach (var go in SceneManager.GetActiveScene().GetRootGameObjects())
            foreach (var tr in go.GetComponentsInChildren<Transform>(true))
                all.Add(tr.gameObject);
        if (names.Count == 0)
            // 注意：`GetComponentsInChildren<Transform>(true)` 已经包含 inactive，
            // 所以"场景里所有角色"是**含 inactive 的**（这在采 inactive 目标时正是要的）。
            {
            var cand = all.Where(g => g.GetComponent<Animator>() != null
                                      && g.GetComponentsInChildren<Renderer>(true).Any()
                                      && !g.name.StartsWith("_"))
                          .Distinct().ToList();
            // ⚠️ 只取"候选集合里的根"：不再把角色内部的子物体（size_root / ch_root /
            // bone_*_wing / GameObject…）也当独立目标 —— 否则导出真角色时会把它的
            // 子节点当"别的目标"整根 SetActive(false)，采出来是全空的帧
            // （2026-09-17 16:41 那次 60 目标 842 帧就是这么废掉的）。
            var roots0 = cand.Where(g => !cand.Any(o => o != g
                                            && g.transform.IsChildOf(o.transform)))
                             .ToList();
            var nested = cand.Where(g => !roots0.Contains(g))
                             .Select(g => g.name).ToArray();
            if (nested.Length > 0)
                PlaySampleLog.W("[draworder] 候选 " + cand.Count + " 个里有 "
                                + nested.Length + " 个是**角色内部子物体**，不作为独立目标："
                                + string.Join(",", nested.Take(12).ToArray()));
            cand = roots0;
            // 注意：observe 模式**不能**按"当前 inactive"筛 —— 那时我们要的正
            // 是"游戏把它显示出来的那一刻"，所以只在 force 模式下筛。
            if (cfg.onlyInactive && !IsObserve(cfg))
            {
                var activeOnes = cand.Where(g => g.activeInHierarchy)
                                     .Select(g => g.name).ToArray();
                cand = cand.Where(g => !g.activeInHierarchy).ToList();
                if (activeOnes.Length > 0)
                    PlaySampleLog.W("[draworder] OnlyInactive=true，跳过已经激活的 "
                                    + activeOnes.Length + " 个根："
                                    + string.Join(",", activeOnes.Take(10).ToArray()));
            }
            return cand.ToArray();
            }
        var want = new HashSet<string>(names, StringComparer.OrdinalIgnoreCase);
        return all.Where(g => want.Contains(g.name)).Distinct().ToArray();
    }

    private static List<StateEntry> CollectStates(AnimatorController ctrl)
    {
        var outList = new List<StateEntry>();
        for (int li = 0; li < ctrl.layers.Length; li++)
        {
            var sm = ctrl.layers[li].stateMachine;
            if (sm == null) continue;
            Walk(sm, li, ctrl, outList, 0);
        }
        return outList;
    }

    private static void Walk(AnimatorStateMachine sm, int layer, AnimatorController ctrl,
                             List<StateEntry> outList, int depth)
    {
        if (sm == null || depth > 6) return;
        foreach (var cs in sm.states)
        {
            if (cs.state == null) continue;
            outList.Add(new StateEntry
            {
                name = cs.state.name,
                hash = cs.state.nameHash != 0 ? cs.state.nameHash
                                              : Animator.StringToHash(cs.state.name),
                layer = layer,
                state = cs.state,
                ctrl = ctrl,
            });
        }
        foreach (var sub in sm.stateMachines)
            Walk(sub.stateMachine, layer, ctrl, outList, depth + 1);
    }

    private static string RelPath(GameObject root, Transform tr)
    {
        if (tr == root.transform) return root.name;
        var parts = new List<string>();
        var cur = tr;
        while (cur != null)
        {
            parts.Add(cur.name);
            if (cur == root.transform) break;
            cur = cur.parent;
        }
        parts.Reverse();
        return string.Join("/", parts.ToArray());
    }

    private static List<string> Split(string s)
    {
        var list = new List<string>();
        if (string.IsNullOrEmpty(s)) return list;
        foreach (var p in s.Split(new[] { ',', '，', ';', ' ' },
                                  StringSplitOptions.RemoveEmptyEntries))
            list.Add(p.Trim());
        return list;
    }

    private static float[] ParseFloats(string s, float[] def)
    {
        var list = new List<float>();
        foreach (var p in Split(s))
        {
            float v;
            if (float.TryParse(p, NumberStyles.Float, CultureInfo.InvariantCulture, out v))
                list.Add(v);
        }
        return list.Count > 0 ? list.ToArray() : def;
    }

    private static string Sanitize(string s)
    {
        if (string.IsNullOrEmpty(s)) return "x";
        var sb = new StringBuilder();
        foreach (char c in s)
            sb.Append(char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '.' ? c : '_');
        return sb.ToString();
    }

    private static string F(float v)
    {
        return v.ToString("0.#####", CultureInfo.InvariantCulture);
    }

    private static string B(bool v) { return v ? "true" : "false"; }

    private static string Str(string s)
    {
        if (s == null) return "\"\"";
        var sb = new StringBuilder("\"");
        foreach (char c in s)
        {
            if (c == '"' || c == '\\') sb.Append('\\').Append(c);
            else if (c == '\n') sb.Append("\\n");
            else if (c == '\r') sb.Append("\\r");
            else if (c == '\t') sb.Append("\\t");
            else if (c < 32) sb.Append("\\u").Append(((int)c).ToString("x4"));
            else sb.Append(c);
        }
        return sb.Append("\"").ToString();
    }
}
