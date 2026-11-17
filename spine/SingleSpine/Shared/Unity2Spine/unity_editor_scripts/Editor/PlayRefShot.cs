// PlayRefShot.cs —— Play 模式下的"参考帧"取样：**带相机的 PNG + 同帧数据 JSON**。
//
// 为什么必须 Play 模式（也是本文件存在的理由）：
//   `m_IsActive` / `m_Enabled` 这类曲线，只有在 **Animator 真的在跑**（Play 模式）
//   时才会落到 GameObject / Renderer 上。`TwoDModelCalibExport`（AnimationMode
//   编辑器采样）和 `ModelInspect`（batchmode）都不会改 `activeSelf`
//   —— 实测 `ModelInspect` 的 dynamic.json 在 17 帧里 `activeSelf/activeInHierarchy/
//   enabled` **0 次变化**，所以它只能当"静态姿态 + 渲染图"，不能当显隐真值。
//
// 输出（默认写 **D:\VB\Unity2Spine\info**，和 `_inspect_*` 同级，**不写进 Assets**，否则会触发导入）：
//   info/_refshot_<角色>/frames/<角色>__<状态>__t<毫秒>.png     带相机的渲染帧
//   info/_refshot_<角色>/frames/<角色>__<状态>__t<毫秒>_cam.txt 相机参数（cx/cy/size/aspect/w/h/ppu）
//   info/_refshot_<角色>/<角色>__<状态>__t<毫秒>.json           同帧逐渲染器数据
//
//   同帧数据里每个渲染器一条：
//     path / activeSelf / activeInHierarchy / enabled / isVisible / sortingOrder /
//     sortingLayerName / sprite / texture / boundsCenter / boundsSize /
//     camDepth（沿相机视线方向的深度，**同 order 的透明件就是按它排序**）/
//     distToCam（欧氏距离）/ mesh（可选：世界坐标顶点 + 三角形）
//
// 用法（菜单）：Tools/2DModel/运行时采样/参考帧（带相机）…
//   1) 填「角色名」「状态名」「时刻(秒)」→ 2) 点「开始（自动进 Play）」
//   采样完自动退出 Play 模式（可关）。日志同 PlayModeSampler：info\_logs\play_sample.log
//
// 注意：协程里不能在带 catch 的 try 中 yield —— 有风险的步骤都放在不带 yield 的 helper 里。

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public class PlayRefShotWindow : EditorWindow
{
    // 初值直接取「内置清单」（见文件末尾 PlayRefShotPlan）——不用手输
    private string charNames = PlayRefShotPlan.Names;
    private string stateNames = PlayRefShotPlan.States;
    private string times = PlayRefShotPlan.Times;
    private float ppu = PlayRefShotPlan.Ppu;
    private float margin = PlayRefShotPlan.Margin;
    private bool withMesh = PlayRefShotPlan.Mesh;
    private bool exitAfter = PlayRefShotPlan.ExitAfter;
    private bool activateEarly = PlayRefShotPlan.ActivateEarly;
    private string outRoot = "";
    private string info = "";

    [MenuItem("Tools/2DModel/运行时采样/参考帧（带相机）…")]
    public static void Open()
    {
        var w = GetWindow<PlayRefShotWindow>("参考帧取样");
        w.minSize = new Vector2(560, 380);
    }

    private void SavePrefs(PlayRefShot.Cfg c)
    {
        EditorPrefs.SetString("PlayRefShot.names", c.names);
        EditorPrefs.SetString("PlayRefShot.states", c.states);
        EditorPrefs.SetString("PlayRefShot.times", c.times);
        EditorPrefs.SetFloat("PlayRefShot.ppu", c.ppu);
        EditorPrefs.SetString("PlayRefShot.out", c.outRoot);
    }

    private void OnGUI()
    {
        EditorGUILayout.HelpBox(
            "Play 模式下按「状态 + 时刻」出参考帧：一张带相机的 PNG + 同帧逐渲染器 JSON。\n" +
            "· 角色名留空 = 场景里所有 2DModel 角色\n" +
            "· 状态名留空 = 该 Animator 的所有状态\n" +
            "· 时刻是**秒**（不是归一化比例），逗号分隔\n" +
            "· 会临时新建一台正交相机（不动你的主相机），采样完自动删除",
            MessageType.Info);

        charNames = EditorGUILayout.TextField("角色名（逗号分隔）", charNames);
        stateNames = EditorGUILayout.TextField("状态名（逗号分隔）", stateNames);
        times = EditorGUILayout.TextField("时刻/秒（逗号分隔）", times);
        ppu = EditorGUILayout.FloatField("分辨率 ppu（像素/世界单位）", ppu);
        margin = EditorGUILayout.FloatField("取景留白 margin", margin);
        withMesh = EditorGUILayout.Toggle("同时写网格顶点（几何对账用，文件大）", withMesh);
        activateEarly = EditorGUILayout.Toggle(
            "先激活角色再进 Play（推荐；与游戏一致，避免绑定丢失）", activateEarly);
        exitAfter = EditorGUILayout.Toggle("采样完自动退出 Play 模式", exitAfter);
        outRoot = EditorGUILayout.TextField(
            "输出根目录（空=D:\\VB\\Unity2Spine\\info）", outRoot);

        var cfg = new PlayRefShot.Cfg
        {
            names = charNames,
            states = stateNames,
            times = times,
            ppu = Mathf.Max(64f, ppu),
            margin = Mathf.Max(1f, margin),
            mesh = withMesh,
            exitAfter = exitAfter,
            activateEarly = activateEarly,
            outRoot = outRoot,
        };

        EditorGUILayout.LabelField("日志", PlaySampleLog.LogPath);
        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("开始（自动进 Play 模式）", GUILayout.Height(34)))
        {
            SavePrefs(cfg);
            PlayRefShot.Start(cfg);
            info = "已提交采样请求，请看日志";
        }
        if (GUILayout.Button("只打印诊断（不进 Play）", GUILayout.Height(34)))
            info = PlayRefShot.Diagnose(cfg);
        EditorGUILayout.EndHorizontal();
        if (GUILayout.Button("打开日志文件")) EditorUtility.RevealInFinder(PlaySampleLog.LogPath);
        EditorGUILayout.Space();
        EditorGUILayout.LabelField(info, EditorStyles.wordWrappedLabel);
    }

    private void OnInspectorUpdate() { Repaint(); }
}

public static class PlayRefShot
{
    public class Cfg
    {
        public string names = "";
        public string states = "";
        public string times = "0";
        public float ppu = 640f;
        public float margin = 1.08f;
        public bool mesh = false;
        public bool exitAfter = true;
        public string outRoot = "";
        /// <summary>进 Play **之前**就在 edit 模式激活角色（和游戏一致：角色一直是活的，
        /// Animator 绑定不会因为"进 Play 时才被激活"而丢）。</summary>
        public bool activateEarly = true;
    }

    private static Cfg _pending;
    private static IEnumerator _routine;
    private static bool _running;
    private static readonly List<GameObject> _activated = new List<GameObject>();

    // ---------------------------------------------------------- 待跑配置（跨 Domain Reload）
    // 进 Play 模式时如果 Project Settings 开着 Domain Reload，静态字段会被清空，
    // 只靠内存里的 `_pending` 会**丢请求**（2026-09-17 第一次实测就是这样：
    // 日志里只有诊断、没有 `[refshot] 开始`）。所以配置必须落到 EditorPrefs。
    private const string PEND = "PlayRefShot.pending";
    private const string K_N = "PlayRefShot.pend.names";
    private const string K_S = "PlayRefShot.pend.states";
    private const string K_T = "PlayRefShot.pend.times";
    private const string K_P = "PlayRefShot.pend.ppu";
    private const string K_M = "PlayRefShot.pend.mesh";
    private const string K_X = "PlayRefShot.pend.exit";
    private const string K_O = "PlayRefShot.pend.out";

    public static void SavePending(Cfg c)
    {
        EditorPrefs.SetString(K_N, c.names);
        EditorPrefs.SetString(K_S, c.states);
        EditorPrefs.SetString(K_T, c.times);
        EditorPrefs.SetFloat(K_P, c.ppu);
        EditorPrefs.SetBool(K_M, c.mesh);
        EditorPrefs.SetBool(K_X, c.exitAfter);
        EditorPrefs.SetString(K_O, c.outRoot);
        EditorPrefs.SetBool(PEND, true);
        PlaySampleLog.W("[refshot] 已登记待跑配置：" + c.names + " / " + c.states + " / " + c.times);
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
            ppu = EditorPrefs.GetFloat(K_P, 640f),
            mesh = EditorPrefs.GetBool(K_M, false),
            exitAfter = EditorPrefs.GetBool(K_X, true),
            outRoot = EditorPrefs.GetString(K_O, ""),
        };
    }

    // ------------------------------------------------------------------ 入口
    public static void Start(Cfg cfg)
    {
        _pending = cfg;
        SavePending(cfg);              // 双保险：内存 + EditorPrefs
        if (cfg.activateEarly && !EditorApplication.isPlaying)
        {
            // 关键：在 **edit 模式**先把角色激活，再进 Play。
            // 否则 Animator 可能在角色 inactive 时建绑定，部分 m_IsActive / 变换曲线
            // 会静默失效（实测：这样采出来的显隐和编辑器/游戏不一致）。
            foreach (var root in FindRoots(cfg))
            {
                var changed = CalibTargets.Activate(root);
                if (changed.Count > 0)
                {
                    _activated.AddRange(changed);
                    PlaySampleLog.W("[refshot] （进 Play 前）激活 " + root.name
                                    + " 的 " + changed.Count + " 个上级/自身节点");
                }
            }
        }
        if (EditorApplication.isPlaying)
            Begin(cfg);
        else
            EditorApplication.EnterPlaymode();
    }

    private static void Begin(Cfg cfg)
    {
        if (_running) { PlaySampleLog.W("[refshot] 已经在跑，忽略重复请求"); return; }
        _running = true;
        _routine = Run(cfg);
        EditorApplication.update += Pump;
        PlaySampleLog.W("[refshot] 开始：names=" + cfg.names + " states=" + cfg.states
                        + " times=" + cfg.times + " ppu=" + cfg.ppu);
    }

    [InitializeOnLoadMethod]
    private static void Install()
    {
        EditorApplication.playModeStateChanged += s =>
        {
            if (s != PlayModeStateChange.EnteredPlayMode) return;
            var c = _pending != null ? _pending : TakePending();
            if (c != null)
            {
                _pending = null;
                PlaySampleLog.W("[refshot] EnteredPlayMode → 开始采样");
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
                PlaySampleLog.W("[refshot] update 轮询 → 开始采样");
                Begin(c);
            }
        };
    }

    /// <summary>菜单入口：不进窗口，直接用上一次登记的参数开始（含 EditorPrefs 里的）。</summary>
    [MenuItem("Tools/2DModel/运行时采样/参考帧：用上次参数开始")]
    public static void MenuStartLast()
    {
        var c = new Cfg
        {
            names = EditorPrefs.GetString(K_N, EditorPrefs.GetString("PlayRefShot.names", "")),
            states = EditorPrefs.GetString(K_S, EditorPrefs.GetString("PlayRefShot.states", "breast")),
            times = EditorPrefs.GetString(K_T, EditorPrefs.GetString("PlayRefShot.times", "0")),
            ppu = EditorPrefs.GetFloat(K_P, EditorPrefs.GetFloat("PlayRefShot.ppu", 640f)),
            mesh = true,
            exitAfter = true,
            outRoot = EditorPrefs.GetString(K_O, EditorPrefs.GetString("PlayRefShot.out", "")),
        };
        PlaySampleLog.W("[refshot] 菜单触发：" + c.names + " / " + c.states + " / " + c.times);
        Start(c);
    }

    /// <summary>⭐ 常用的那条：直接用**文件里硬编码的清单**开始，不用在窗口里输入。</summary>
    [MenuItem("Tools/2DModel/运行时采样/参考帧：按内置清单开始（不用窗口）", false, 0)]
    public static void MenuStartPlan()
    {
        Start(PlayRefShotPlan.ToCfg());
    }

    private static void Pump()
    {
        if (_routine == null) return;
        try
        {
            if (!_routine.MoveNext())
            {
                _routine = null;
                _running = false;
                EditorApplication.update -= Pump;
                PlaySampleLog.W("[refshot] 完成");
            }
        }
        catch (Exception e)
        {
            _routine = null;
            _running = false;
            EditorApplication.update -= Pump;
            PlaySampleLog.E("[refshot] 异常", e);
        }
    }

    // ------------------------------------------------------------------ 诊断
    public static string Diagnose(Cfg cfg)
    {
        var sb = new StringBuilder();
        foreach (var root in FindRoots(cfg))
        {
            var ans = root.GetComponentsInChildren<Animator>(true);
            sb.AppendLine(root.name + "：Animator " + ans.Length + " 个");
            foreach (var an in ans)
            {
                var ctrl = an.runtimeAnimatorController as AnimatorController;
                if (ctrl == null) { sb.AppendLine("   " + an.name + "：没有 AnimatorController"); continue; }
                var states = CollectStates(ctrl);
                sb.AppendLine("   " + an.name + "：状态 " + states.Count + " 个 → "
                              + string.Join(",", states.Take(20).Select(x => x.name).ToArray()));
            }
        }
        if (sb.Length == 0) sb.Append("没找到角色（角色名是否写对？场景里有没有？）");
        PlaySampleLog.W("[refshot] 诊断:\n" + sb);
        return sb.ToString();
    }

    // ------------------------------------------------------------------ 主流程
    private class StateEntry
    {
        public string name;
        public int hash;
        public int layer;
        public AnimatorState state;
        public AnimatorController ctrl;
    }

    private static IEnumerator Run(Cfg cfg)
    {
        // 默认写到统一导出根（`ExportRoots.Root` = D:\VB\Unity2Spine\info），
        // 不是 Unity 工程根 —— 那是 2026-09-18 改的，见 ExportRoots.cs。
        string outRoot = string.IsNullOrEmpty(cfg.outRoot)
            ? ExportRoots.Root
            : cfg.outRoot;
        float[] times = ParseFloats(cfg.times, new[] { 0f });
        var wantStates = Split(cfg.states);
        var roots = FindRoots(cfg).ToList();
        if (roots.Count == 0) { PlaySampleLog.E("[refshot] 没有找到角色"); yield break; }

        foreach (var root in roots)
        {
            // 场景里的角色通常是 disabled（几十个一起放着）⇒ 采样前把整条父链
            // 临时激活，采完恢复（用工程里现成的 CalibTargets.Activate）。
            // 若配置了 activateEarly，这一步在进 Play 之前就做过了。
            try
            {
                var changed = cfg.activateEarly ? new List<GameObject>()
                                                : CalibTargets.Activate(root);
                _activated.AddRange(changed);
                if (changed.Count > 0)
                    PlaySampleLog.W("[refshot] 临时激活 " + root.name + " 的 "
                                    + changed.Count + " 个上级/自身节点");
            }
            catch (Exception e) { PlaySampleLog.E("[refshot] 激活失败", e); }
            yield return null;
            if (!root.activeInHierarchy)
                PlaySampleLog.W("[refshot] 注意：" + root.name
                                + " 激活后仍然 activeInHierarchy=false（父链可能被别的脚本又关回去了）");
            string dir = Path.Combine(outRoot, "_refshot_" + Sanitize(root.name));
            Directory.CreateDirectory(Path.Combine(dir, "frames"));
            var animators = root.GetComponentsInChildren<Animator>(true);
            for (int ai = 0; ai < animators.Length; ai++)
            {
                var an = animators[ai];
                if (an != null && !an.enabled)
                {
                    an.enabled = true;      // 场景里有时把 Animator 也关了
                    PlaySampleLog.W("   " + an.name + "：Animator 原本 disabled，已临时打开");
                }
                var ctrl = an.runtimeAnimatorController as AnimatorController;
                if (ctrl == null) continue;
                var states = CollectStates(ctrl);
                foreach (var st in states)
                {
                    if (wantStates.Count > 0 && !wantStates.Contains(st.name)) continue;
                    var clip = st.state.motion as AnimationClip;
                    if (clip == null) { PlaySampleLog.W("   跳过 " + st.name + "：没有 clip"); continue; }
                    foreach (float t in times)
                    {
                        float dur = Mathf.Max(1e-4f, clip.length);
                        float norm = Mathf.Clamp01(t / dur);
                        if (!StepRoot(root, animators, st, norm))
                        {
                            PlaySampleLog.W("   " + st.name + "：步进失败，跳过");
                            continue;
                        }
                        // 以前是"直接等两帧再取"，等的时候 Animator 还在走，
                        // 真值姿态比标称时刻晚 2~3 帧（docs 11.7⑤）。
                        // 现在先冻住 Animator（speed=0）再等帧：JSON 与 PNG
                        // 一定是同一姿态，并把真实时刻写进 JSON（stateTime）。
                        // 只 yield null（不用 WaitForEndOfFrame）：本协程由
                        // EditorApplication.update 驱动，null 是已验证的写法。
                        float speed0 = an.speed;
                        an.speed = 0f;
                        float stateTime = StateTimeOf(an, st.layer, clip);
                        yield return null;
                        yield return null;
                        string tag = Sanitize(root.name) + "__" + Sanitize(st.name)
                                     + "__t" + Mathf.RoundToInt(t * 1000f).ToString("D4");
                        ShotFrame(dir, root, an, st, clip, t, tag, cfg, stateTime);
                        an.speed = speed0;
                        yield return null;
                    }
                }
            }
            PlaySampleLog.W("[refshot] " + root.name + " 完成 → " + dir);
            if (!cfg.activateEarly)
            {
                // 恢复：这个角色的父链改动还回去（避免下一个角色/后续操作被影响）
                foreach (var go in _activated)
                    if (go != null) go.SetActive(false);
                _activated.Clear();
            }
        }
        foreach (var go in _activated)
            if (go != null) go.SetActive(false);
        _activated.Clear();
        if (cfg.exitAfter && EditorApplication.isPlaying)
            EditorApplication.ExitPlaymode();
    }

    /// <summary>把**这台 Animator**（以及同根的其它 Animator，按各自默认状态）步进到目标时刻。</summary>
    private static bool StepRoot(GameObject root, Animator[] animators, StateEntry st, float norm)
    {
        try
        {
            foreach (var an in animators) an.Rebind();
            foreach (var an in animators)
            {
                if (an == null) continue;
                if (an.runtimeAnimatorController == st.ctrl)
                    an.Play(st.hash, st.layer, norm);
                else
                    an.Update(0f);       // 副 Animator 保持自己的默认状态
            }
            foreach (var an in animators) an.Update(0f);
            return true;
        }
        catch (Exception e)
        {
            PlaySampleLog.E("[refshot] 步进失败", e);
            return false;
        }
    }

    // ------------------------------------------------------------------ 出帧 + 同帧数据
    private static void ShotFrame(string dir, GameObject root, Animator animator,
                                 StateEntry st, AnimationClip clip, float t,
                                 string tag, Cfg cfg, float stateTime)
    {
        var camObj = new GameObject("refshot_cam");
        RenderTexture rt = null;
        Texture2D tex = null;
        var old = RenderTexture.active;
        try
        {
            var rends = root.GetComponentsInChildren<Renderer>(true)
                            .Where(r => r is SpriteRenderer || r is SkinnedMeshRenderer
                                        || r is MeshRenderer)
                            .ToArray();
            // 取景：只用"真的会画"的渲染器算包围盒
            var b = new Bounds();
            bool has = false;
            int nOn = 0, nIn = 0;
            foreach (var r in rends)
            {
                if (r.enabled) nOn++;
                if (r.gameObject.activeInHierarchy) nIn++;
                if (!r.enabled || !r.gameObject.activeInHierarchy) continue;
                if (r.bounds.size.sqrMagnitude < 1e-10f) continue;
                b.Encapsulate(r.bounds);
                has = true;
            }
            if (!has)
            {
                // 退化：把"渲染器被关/父链 inactive/包围盒为 0"的也拿来取景，
                // 至少把画面和同帧数据出出来（并写清退化原因）。
                int n = 0;
                foreach (var r in rends)
                {
                    if (r.bounds.size.sqrMagnitude < 1e-10f) continue;
                    b.Encapsulate(r.bounds);
                    n++;
                }
                if (n > 0)
                {
                    has = true;
                    PlaySampleLog.W("[refshot] " + tag + "：严格可见 0 个（enabled "
                                    + nOn + "/" + rends.Length + "，activeInHierarchy "
                                    + nIn + "/" + rends.Length
                                    + "）→ 退化为用全部 " + n + " 个渲染器取景");
                }
            }
            if (!has)
            {
                PlaySampleLog.W("[refshot] " + tag + "：连包围盒都没有（渲染器 "
                                + rends.Length + " 个，enabled " + nOn
                                + "，activeInHierarchy " + nIn
                                + "，root.activeInHierarchy " + root.activeInHierarchy
                                + "）→ 跳过截图");
                return;
            }

            float halfH = Mathf.Max(1e-3f, b.extents.y) * cfg.margin;
            float halfW = Mathf.Max(1e-3f, b.extents.x) * cfg.margin;
            int w = Mathf.Clamp(Mathf.RoundToInt(halfW * 2f * cfg.ppu), 64, 4096);
            int h = Mathf.Clamp(Mathf.RoundToInt(halfH * 2f * cfg.ppu), 64, 4096);
            float aspect = (float)w / h;
            float size = Mathf.Max(halfH, halfW / aspect);
            Vector3 centre = b.center;

            var cam = camObj.AddComponent<Camera>();
            cam.orthographic = true;
            cam.orthographicSize = size;
            cam.transform.position = new Vector3(centre.x, centre.y, -10f);
            cam.transform.LookAt(new Vector3(centre.x, centre.y, 0f));
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(1f, 1f, 1f, 1f);
            cam.nearClipPlane = 0.01f;
            cam.farClipPlane = 100f;

            rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32);
            cam.targetTexture = rt;
            cam.Render();
            RenderTexture.active = rt;
            tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
            tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
            tex.Apply();
            RenderTexture.active = old;
            string frames = Path.Combine(dir, "frames");
            Directory.CreateDirectory(frames);
            File.WriteAllBytes(Path.Combine(frames, tag + ".png"), tex.EncodeToPNG());
            File.WriteAllText(Path.Combine(frames, tag + "_cam.txt"),
                "cx=" + F(centre.x) + "\ncy=" + F(centre.y) +
                "\nsize=" + F(size) + "\naspect=" + F(aspect) +
                "\nw=" + w + "\nh=" + h + "\nppu=" + F(cfg.ppu) + "\n");

            // ---- 同帧逐渲染器数据 ----
            var sb = new StringBuilder();
            sb.Append("{\n");
            sb.Append("  \"character\": ").Append(Str(root.name)).Append(",\n");
            sb.Append("  \"animator\": ").Append(Str(animator.name)).Append(",\n");
            sb.Append("  \"state\": ").Append(Str(st.name)).Append(",\n");
            sb.Append("  \"clip\": ").Append(Str(clip.name)).Append(",\n");
            sb.Append("  \"clipLength\": ").Append(F(clip.length)).Append(",\n");
            sb.Append("  \"t\": ").Append(F(t)).Append(",\n");
            // 真实采样时刻（秒）= Animator 被冻住那一刻的状态时间。切帧对账用它，
            // 别用标称 t —— 以前差 2~3 帧就是"读值时 Animator 还在走"造成的。
            sb.Append("  \"stateTime\": ").Append(F(stateTime)).Append(",\n");
            sb.Append("  \"norm\": ").Append(F(t / Mathf.Max(1e-4f, clip.length))).Append(",\n");
            // 每层的运行时权重 / 当前状态：判"第二层默认 clip 该不该并"就靠它
            // （资产里的 m_DefaultWeight 是编辑期值，实测和运行时不一致）。
            AppendLayers(sb, animator);
            sb.Append("  \"camera\": { \"cx\": ").Append(F(centre.x))
              .Append(", \"cy\": ").Append(F(centre.y))
              .Append(", \"size\": ").Append(F(size))
              .Append(", \"ppu\": ").Append(F(cfg.ppu))
              .Append(", \"w\": ").Append(w).Append(", \"h\": ").Append(h)
              .Append(", \"pos\": [").Append(F(cam.transform.position.x)).Append(",")
              .Append(F(cam.transform.position.y)).Append(",")
              .Append(F(cam.transform.position.z)).Append("], \"forward\": [")
              .Append(F(cam.transform.forward.x)).Append(",")
              .Append(F(cam.transform.forward.y)).Append(",")
              .Append(F(cam.transform.forward.z)).Append("] },\n");
            sb.Append("  \"drawOrderHint\": \"同 sortingOrder 时 Unity 按到相机的深度排序：camDepth 大 = 画得早（在下层）\",\n");
            sb.Append("  \"renderers\": [\n");
            var mesh = new Mesh();
            bool first = true;
            foreach (var r in rends)
            {
                if (!first) sb.Append(",\n");
                first = false;
                sb.Append("    { \"path\": ").Append(Str(RelPath(root, r.transform)))
                  .Append(", \"type\": ").Append(Str(r.GetType().Name))
                  .Append(", \"activeSelf\": ").Append(B(r.gameObject.activeSelf))
                  .Append(", \"activeInHierarchy\": ").Append(B(r.gameObject.activeInHierarchy))
                  .Append(", \"enabled\": ").Append(B(r.enabled))
                  .Append(", \"isVisible\": ").Append(B(r.isVisible))
                  .Append(", \"sortingOrder\": ").Append(r.sortingOrder)
                  .Append(", \"sortingLayerName\": ").Append(Str(r.sortingLayerName))
                  .Append(", \"sortingLayerID\": ").Append(r.sortingLayerID)
                  .Append(", \"boundsCenter\": [").Append(F(r.bounds.center.x)).Append(",")
                  .Append(F(r.bounds.center.y)).Append(",").Append(F(r.bounds.center.z)).Append("]")
                  .Append(", \"boundsSize\": [").Append(F(r.bounds.size.x)).Append(",")
                  .Append(F(r.bounds.size.y)).Append(",").Append(F(r.bounds.size.z)).Append("]")
                  .Append(", \"camDepth\": ")
                  .Append(F(Vector3.Dot(r.bounds.center - cam.transform.position,
                                        cam.transform.forward)))
                  .Append(", \"distToCam\": ")
                  .Append(F(Vector3.Distance(r.bounds.center, cam.transform.position)))
                  .Append(", \"sprite\": ").Append(Str(SpriteName(r)));
                var spr0 = r as SpriteRenderer;
                if (spr0 != null)
                    sb.Append(", \"flipX\": ").Append(B(spr0.flipX))
                      .Append(", \"flipY\": ").Append(B(spr0.flipY));
                // 同口径判据（2026-09-19 加，与 `PlayModeSamplerRunner` 那套对齐）：
                // 判"sprite 件尺寸对不上"时只看这几项 —— `boundsSize` 是**矩形**世界 AABB，
                // 产物画的是**紧贴网格**，两者必然不同；`spriteRect/spritePpu` 才是同口径。
                // `spriteVertsAabb` = 运行时 `Sprite.vertices` 的 AABB（紧贴网格、pivot 在原点），
                // `lossyScale` = 渲染器世界缩放（排查"同一个 sprite 被不同缩放"）。
                if (spr0 != null && spr0.sprite != null)
                {
                    var sp0 = spr0.sprite;
                    Vector2[] sv0 = sp0.vertices;
                    float ax0 = 0f, ay0 = 0f, ax1 = 0f, ay1 = 0f;
                    for (int vk = 0; vk < sv0.Length; vk++)
                    {
                        if (vk == 0) { ax0 = ax1 = sv0[vk].x; ay0 = ay1 = sv0[vk].y; }
                        else
                        {
                            if (sv0[vk].x < ax0) ax0 = sv0[vk].x;
                            if (sv0[vk].x > ax1) ax1 = sv0[vk].x;
                            if (sv0[vk].y < ay0) ay0 = sv0[vk].y;
                            if (sv0[vk].y > ay1) ay1 = sv0[vk].y;
                        }
                    }
                    Vector3 lsc = r.transform.lossyScale;
                    sb.Append(", \"spriteRect\": [").Append(F(sp0.rect.x)).Append(",")
                      .Append(F(sp0.rect.y)).Append(",").Append(F(sp0.rect.width))
                      .Append(",").Append(F(sp0.rect.height)).Append("]")
                      .Append(", \"spritePpu\": ").Append(F(sp0.pixelsPerUnit))
                      .Append(", \"spriteBoundsSize\": [")
                      .Append(F(sp0.bounds.size.x)).Append(",")
                      .Append(F(sp0.bounds.size.y)).Append(",")
                      .Append(F(sp0.bounds.size.z)).Append("]")
                      .Append(", \"spriteVertsAabb\": [").Append(F(ax0)).Append(",")
                      .Append(F(ay0)).Append(",").Append(F(ax1)).Append(",")
                      .Append(F(ay1)).Append("]")
                      .Append(", \"lossyScale\": [").Append(F(lsc.x)).Append(",")
                      .Append(F(lsc.y)).Append(",").Append(F(lsc.z)).Append("]");
                }

                var smr = r as SkinnedMeshRenderer;
                var mf = r.GetComponent<MeshFilter>();
                bool spriteMesh = cfg.mesh && spr0 != null && spr0.sprite != null;
                if (cfg.mesh && (smr != null || (mf != null && mf.sharedMesh != null)
                                 || spriteMesh))
                {
                    try
                    {
                        Mesh src = null;
                        Matrix4x4 m = r.transform.localToWorldMatrix;
                        Vector3[] vs = null;
                        int[] tris = null;
                        if (spriteMesh)
                        {
                            // Sprite：`Sprite.vertices/triangles` 给的是**紧致网格**
                            // （局部、pivot 在原点）；**不含** flipX/flipY —— 那两个是
                            // 绘制期绕 pivot 镜像，单独写在 flipX/flipY 字段里，
                            // 比对时按需镜像即可。
                            // 注意类型：Sprite.vertices 是 Vector2[]、
                            // Sprite.triangles 是 ushort[]（不是 Vector3[]/int[]）。
                            var sv2 = spr0.sprite.vertices;
                            var st2 = spr0.sprite.triangles;
                            vs = new Vector3[sv2.Length];
                            for (int k = 0; k < sv2.Length; k++)
                                vs[k] = new Vector3(sv2[k].x, sv2[k].y, 0f);
                            tris = new int[st2.Length];
                            for (int k = 0; k < st2.Length; k++) tris[k] = st2[k];
                            // ⚠️ `Sprite.vertices` 是**相对 pivot** 的局部坐标、**不含**
                            // flipX/flipY（那俩是绘制期绕 pivot 镜像）。产物画的是
                            // **镜像后**的几何 ⇒ 这里也镜像，两边才同口径。
                            // 旧版没镜像，导致"带翻转的 sprite 件"位置总差 2~6%
                            // （alice_skin2 的伞最极端：差 3.6 世界单位），见 docs 12.8。
                            if (spr0.flipX != spr0.flipY)      // 只翻一个轴 ⇒ 绕序反了
                                for (int k = 0; k + 2 < tris.Length; k += 3)
                                {
                                    int tmp = tris[k + 1]; tris[k + 1] = tris[k + 2]; tris[k + 2] = tmp;
                                }
                            if (spr0.flipX)
                                for (int k = 0; k < vs.Length; k++) vs[k].x = -vs[k].x;
                            if (spr0.flipY)
                                for (int k = 0; k < vs.Length; k++) vs[k].y = -vs[k].y;
                        }
                        else if (smr != null)
                        {
                            // BakeMesh(mesh, true)：true = 把渲染器世界缩放乘进顶点
                            // （不带 useScale 的那个重载会缩放平方，见 docs 3.30）
                            smr.BakeMesh(mesh, true);
                            src = mesh;
                        }
                        else src = mf.sharedMesh;
                        if (vs == null) vs = src.vertices;
                        if (tris == null) tris = src.triangles;
                        // 统一成世界坐标：
                        //  · SMR：BakeMesh(mesh, true) 已带缩放，再乘 localToWorld
                        //    （与 ModelInspect 修过的那条一致，见 docs 3.30）
                        //  · Sprite / MeshFilter：局部顶点乘 localToWorld
                        var worldArr = new Vector3[vs.Length];
                        for (int i = 0; i < vs.Length; i++)
                            worldArr[i] = m.MultiplyPoint3x4(vs[i]);
                        // 自检：算出来的世界顶点应该落在渲染器自己的 `bounds` 附近。
                        // 不吻合 = 顶点的空间口径错了（旧版脚本有整帧 y 恒 0 的脏数据），
                        // 这时在日志里点名、并在 JSON 里留标记，免得对账时白追。
                        bool spaceSuspect = !MatchesBounds(worldArr, r.bounds);
                        if (spaceSuspect)
                            PlaySampleLog.W("   [mesh] " + r.name
                                            + " 的顶点与 r.bounds 不吻合（空间口径可疑）");
                        // 顺手把网格自己的 AABB 尺寸记下来：与 `boundsSize` 一比就知道
                        // "顶点是不是被散开了"（2026-09-19 blackwyrm 那件靠这个才看清）。
                        Vector3 gmn = worldArr[0], gmx = worldArr[0];
                        for (int i = 1; i < worldArr.Length; i++)
                        {
                            gmn = Vector3.Min(gmn, worldArr[i]);
                            gmx = Vector3.Max(gmx, worldArr[i]);
                        }
                        Vector3 gsz = gmx - gmn;
                        sb.Append(", \"mesh\": { \"count\": ").Append(worldArr.Length)
                          .Append(", \"space\": \"world（已应用 flipX/flipY = Unity 画出来的几何）\"")
                          .Append(", \"spaceSuspect\": ").Append(B(spaceSuspect))
                          .Append(", \"aabbSize\": [").Append(F(gsz.x)).Append(",")
                          .Append(F(gsz.y)).Append(",").Append(F(gsz.z)).Append("]")
                          .Append(", \"verts\": [");
                        int cap = Mathf.Min(worldArr.Length, 4000);
                        for (int i = 0; i < cap; i++)
                        {
                            Vector3 p = worldArr[i];
                            if (i > 0) sb.Append(",");
                            sb.Append("[").Append(F(p.x)).Append(",")
                              .Append(F(p.y)).Append(",").Append(F(p.z)).Append("]");
                        }
                        sb.Append("], \"tris\": [");
                        for (int i = 0; i < tris.Length; i++)
                        {
                            if (i > 0) sb.Append(",");
                            sb.Append(tris[i]);
                        }
                        sb.Append("] }");
                    }
                    catch (Exception e)
                    {
                        sb.Append(", \"meshError\": ").Append(Str(e.Message));
                    }
                }
                sb.Append(" }");
            }
            sb.Append("\n  ]\n}\n");
            File.WriteAllText(Path.Combine(dir, tag + ".json"), sb.ToString(),
                              new UTF8Encoding(false));
            UnityEngine.Object.DestroyImmediate(mesh);
            PlaySampleLog.W("[refshot] 出帧 " + tag);
        }
        catch (Exception e)
        {
            PlaySampleLog.E("[refshot] 出帧失败 " + tag, e);
        }
        finally
        {
            RenderTexture.active = old;
            if (camObj != null)
            {
                var c = camObj.GetComponent<Camera>();
                if (c != null) c.targetTexture = null;
                UnityEngine.Object.DestroyImmediate(camObj);
            }
            if (rt != null) { rt.Release(); UnityEngine.Object.DestroyImmediate(rt); }
            if (tex != null) UnityEngine.Object.DestroyImmediate(tex);
        }
    }

    // ------------------------------------------------------------------ 小工具
    private static string SpriteName(Renderer r)
    {
        var sr = r as SpriteRenderer;
        if (sr == null || sr.sprite == null) return "";
        return sr.sprite.name + "|" + (sr.sprite.texture != null ? sr.sprite.texture.name : "");
    }

    private static string RelPath(GameObject root, Transform t)
    {
        if (t == root.transform) return root.name;
        var parts = new List<string>();
        var cur = t;
        while (cur != null)
        {
            parts.Add(cur.name);
            if (cur == root.transform) break;
            cur = cur.parent;
        }
        parts.Reverse();
        return string.Join("/", parts.ToArray());
    }

    private static IEnumerable<GameObject> FindRoots(Cfg cfg)
    {
        var names = Split(cfg.names);
        var all = new List<GameObject>();
        var scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
        foreach (var go in scene.GetRootGameObjects())
        {
            foreach (var t in go.GetComponentsInChildren<Transform>(true))
                all.Add(t.gameObject);
        }
        if (names.Count == 0)
        {
            // 自动：带 Animator 且有 Sprite/网格渲染器的根（排除控制器命名空间）
            return all.Where(g => g.GetComponent<Animator>() != null
                                  && g.GetComponentsInChildren<Renderer>(true).Any())
                      .Where(g => !g.name.StartsWith("_"))
                      .Distinct()
                      .ToArray();
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

    /// <summary>
    /// 世界顶点集是否落在渲染器自己的 bounds 附近（空间口径自检）。
    /// 判两件事：① 中心对不上 = 口径错；② 尺寸对不上 = 顶点被**散开**
    /// （错空间/错骨骼）。2026-09-19 的教训：blackwyrm `Part_Hair_Denggi_UP_36`
    /// 有一份 907 顶点的渲染器，中心恰好对、顶点却铺开 1.54 而自身 bounds 只有 0.25
    /// —— 只查中心会漏掉它。
    /// </summary>
    private static bool MatchesBounds(Vector3[] p, Bounds b)
    {
        if (p == null || p.Length == 0)
            return true;                    // 没有顶点就不判（例如退化网格）
        Vector3 mn = p[0], mx = p[0];
        for (int i = 1; i < p.Length; i++)
        {
            mn = Vector3.Min(mn, p[i]);
            mx = Vector3.Max(mx, p[i]);
        }
        float tol = Mathf.Max(0.02f, b.size.magnitude * 0.35f);
        if (((mn + mx) * 0.5f - b.center).magnitude >= tol)
            return false;
        // 网格 AABB 只可能比 bounds **小**（贴图矩形之内），不可能 2 倍大 ⇒ 只查"过大"，
        // 避免把"sprite 矩形比紧贴网格大"这种正常情况误判。
        return (mx - mn).magnitude < Mathf.Max(0.02f, b.size.magnitude) * 2.0f;
    }

    /// <summary>当前状态的真实采样时刻（秒）：normalizedTime 取圈内比例 × 时长。</summary>
    private static float StateTimeOf(Animator an, int layer, AnimationClip clip)
    {
        try
        {
            float n = an.GetCurrentAnimatorStateInfo(layer).normalizedTime;
            n -= Mathf.Floor(n);
            return n * Mathf.Max(1e-4f, clip.length);
        }
        catch (Exception) { return -1f; }
    }

    /// <summary>
    /// 每层的运行时状态（权重 / 当前状态 hash / 是否在过渡）。
    /// 用途：我们按"某层的默认 clip"合并副层动画时，需要知道**运行时这层到底有没有生效** ——
    /// 资产里的 `m_DefaultWeight` 是编辑期值（实测 bheur 的 Base Layer 写 0、Drone 层写 1，
    /// 而真值里身体在动、drone 静止，说明运行时权重被游戏改过），光看资产判不出来。
    /// </summary>
    private static void AppendLayers(StringBuilder sb, Animator an)
    {
        sb.Append("  \"layers\": [");
        try
        {
            for (int i = 0; i < an.layerCount; i++)
            {
                if (i > 0) sb.Append(", ");
                var si = an.GetCurrentAnimatorStateInfo(i);
                sb.Append("{ \"index\": ").Append(i)
                  .Append(", \"name\": ").Append(Str(an.GetLayerName(i)))
                  .Append(", \"weight\": ").Append(F(an.GetLayerWeight(i)))
                  .Append(", \"stateHash\": ").Append(si.shortNameHash)
                  .Append(", \"normalizedTime\": ").Append(F(si.normalizedTime))
                  .Append(", \"inTransition\": ").Append(B(an.IsInTransition(i)))
                  .Append(" }");
            }
        }
        catch (Exception) { /* 读不到就留空数组（JSON 保持合法） */ }
        sb.Append("],\n");
    }

    private static string B(bool v) { return v ? "true" : "false"; }

    private static string Str(string s)
    {
        if (s == null) return "\"\"";
        return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}

/// <summary>
/// ⭐ **要出的参考帧清单（硬编码在这里——改这里就行，不用在窗口里输入）**
///
/// 每条 = 角色名 / 该角色要看的状态 / 该状态里的时刻（**秒**）。
/// 工具会：先激活角色（edit 模式）→ 进 Play → 按状态+时刻步进 Animator
/// → 出「带相机的 PNG + 同帧逐渲染器 JSON（含世界顶点、flipX/flipY、排序、camDepth）」。
/// </summary>
public static class PlayRefShotPlan
{
    // 2026-09-19 批次（5 个角色，都是"单角色就能判"的，画面里不会被别的角色挡住）：
    //   · bheur_skin1 / blackwyrm_skin1 / circe_skin1 —— **副层（第二层）到底有没有生效**：
    //     我们要拿每层的运行时 weight + 当前状态来定"副层默认 clip 该不该并"；
    //   · constantias2_skin1 / alice_skin2 —— 复验：换图表情、以及伞（翻转件）
    //     在新版导出（顶点已按 flipX/flipY 镜像）下与产物是否同口径。
    public const string Names =
        "bheur_skin1," +
        "blackwyrm_skin1," +
        "circe_skin1," +
        "constantias2_skin1," +
        "alice_skin2";

    // 状态名**大小写敏感**，各角色不一样；多余的项不会匹配到别人。实际命中的是：
    //   bheur_skin1        ← breast / Tep_1 / Lobby
    //   blackwyrm_skin1    ← breast / Tep_1 / lobby
    //   circe_skin1        ← PECS_Circe_NS1_Lobby
    //   constantias2_skin1 ← breast / lobby
    //   alice_skin2        ← breast / Tep_1 / lobby
    // 共 12 个「状态×角色」，乘 3 个时刻 = 36 帧。
    public const string States =
        "breast,Tep_1,Lobby,lobby,PECS_Circe_NS1_Lobby";

    // ⚠️ 这里的时刻是**秒**（不是比例！）。取 0.5/1.5/2.5 三个点就够看"副层动没动"
    // 与"翻转件位置对不对"（更靠后的点若超出 clip 会被钳制，没意义）。
    public const string Times = "0.5,1.5,2.5";

    public const float Ppu = 1024f;      // 1024 够看脸；要更细可调到 2048（体积/时间 ×4）
    public const float Margin = 1.08f;
    public const bool Mesh = true;       // 写网格顶点（几何/镜像对账要用）
    public const bool ExitAfter = true;  // 采完自动退出 Play
    public const bool ActivateEarly = true;  // 先在 edit 模式激活角色再进 Play

    public static PlayRefShot.Cfg ToCfg()
    {
        return new PlayRefShot.Cfg
        {
            names = Names,
            states = States,
            times = Times,
            ppu = Ppu,
            margin = Margin,
            mesh = Mesh,
            exitAfter = ExitAfter,
            activateEarly = ActivateEarly,
            outRoot = "",
        };
    }
}
