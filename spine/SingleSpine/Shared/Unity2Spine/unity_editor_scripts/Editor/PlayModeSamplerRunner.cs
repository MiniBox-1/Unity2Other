// PlayModeSampler.cs
// （编辑器窗口在 PlayModeSamplerWindow.cs —— Unity 要求文件名与类名一致）
// 在 **Play 模式** 下采样角色的运行时行为，供 D:\VB\Unity2Spine 离线比对。
//
// 为什么用 Play 模式：TwoDModelCalibExport 用 AnimationMode.SampleAnimationClip
// （编辑器采样）不跑 Animator 状态机，采样后那句 animator.Update(0) 还会覆盖
// m_IsActive；这里让 Animator 真的按状态机播，逐帧记录"Unity 到底显示了什么"。
//
// 采样范围：每个 **角色 × Animator（主+副）× 状态（含子状态机、所有层）**
// 输出：D:\VB\Unity2Spine\info\Data\PlayFrames\<角色>@<Animator>@<状态>.json + _summary.json
// 日志：D:\VB\Unity2Spine\info\_logs\play_sample.log（同时打 Console）
//
// 菜单：Tools/2DModel/运行时采样/
//   · 采样窗口                 —— 配置 + 开始 + 只打印诊断 + 打开日志
//   · 开始采样（不用窗口）
//   · 打开日志
//
// 注意（C# 限制）：协程里**不能**在带 catch 的 try 中 yield。
// 所以所有有风险的步骤（Play/Update、建 JSON、写文件、遍历 controller）
// 都放在**不带 yield 的 helper** 里各自 try/catch；协程体里只有 try/finally。

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

// ------------------------------------------------------------------ 日志
public static class PlaySampleLog
{
    private static string _path;

    public static string LogPath
    {
        get
        {
            if (_path != null) return _path;
            // 统一日志目录：D:\VB\Unity2Spine\info\_logs（见 Assets\Script\ExportRoots.cs）
            string dir = ExportRoots.Logs();
            try
            {
                Directory.CreateDirectory(dir);
                _path = Path.Combine(dir, "play_sample.log");
            }
            catch
            {
                // 兜底：万一 info 写不进去，退回工程根（**不要写进 Assets**，会触发导入）
                _path = Path.Combine(Application.dataPath, "..", "play_sample.log");
            }
            return _path;
        }
    }

    public static void W(string msg)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + "  " + msg;
        try { File.AppendAllText(LogPath, line + Environment.NewLine); } catch { }
        Debug.Log("[PlaySample] " + msg);
    }

    public static void E(string msg, Exception ex = null)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + "  [ERROR] " + msg
                      + (ex == null ? "" : ("\n" + ex));
        try { File.AppendAllText(LogPath, line + Environment.NewLine); } catch { }
        Debug.LogError("[PlaySample] " + msg + (ex == null ? "" : ("\n" + ex)));
    }
}

// ------------------------------------------------------------------ 窗口
[InitializeOnLoad]
public static class PlayModeSamplerBootstrap
{
    private static bool _installed;

    static PlayModeSamplerBootstrap()
    {
        EditorApplication.playModeStateChanged += OnStateChanged;
        EditorApplication.update += Watch;
    }

    private static void OnStateChanged(PlayModeStateChange s)
    {
        PlaySampleLog.W("playModeStateChanged: " + s);
        if (s == PlayModeStateChange.EnteredPlayMode) Install("EnteredPlayMode");
    }

    private static void Watch()
    {
        if (!EditorApplication.isPlaying) { _installed = false; return; }
        if (!_installed) Install("update-watch");
    }

    private static void Install(string why)
    {
        if (_installed) return;
        _installed = true;
        var cfg = PlayModeSamplerRunner.LoadConfigFromEditorPrefs();
        if (cfg == null)
        {
            PlaySampleLog.W("进入 Play 模式但没有待采样配置（" + why + "）——忽略");
            return;
        }
        PlayModeSamplerRunner.PendingConfig = cfg;
        PlayModeSamplerRunner.EnsureRunning(cfg);
        PlaySampleLog.W("已启动采样子程序（" + why + "）");
    }
}

// ------------------------------------------------------------------ 运行器
/// <summary>
/// Play 模式采样驱动（**不是 MonoBehaviour**：Assets/Editor 下的脚本
/// 不能 AddComponent 到 GameObject，用 EditorApplication.update 推进协程）。
/// </summary>
public static class PlayModeSamplerRunner
{
    [Serializable]
    public class Config
    {
        public string names = "";
        public float step = 0.05f;
        public bool includeInactive = true;
        public bool bake = false;          // 额外写全量 BakeMesh（PoseFrames 兼容）
        public string bakeChars = "";      // 只给这些角色写 BakeMesh（子串匹配，空=全部）
    }

    /// <summary>采样结果（协程不能返回值，用这个盒子带出来）。</summary>
    public class Result
    {
        public bool ok = true;
        public string error = "";
    }

    public class StateEntry
    {
        public string name = "";
        public int layer;
        public AnimatorState state;
    }

    private const string PrefKey = "PlayModeSampler.PendingConfig";
    private const string LastNamesKey = "PlayModeSampler.LastNames";
    public static Config PendingConfig;
    public static bool StopRequested;

    // ---------------------------------------------------------- 入口
    public static void SaveConfigToEditorPrefs(Config c)
    {
        try { EditorPrefs.SetString(PrefKey, JsonUtility.ToJson(c)); }
        catch (Exception ex) { PlaySampleLog.E("保存配置失败", ex); }
    }

    public static Config LoadConfigFromEditorPrefs()
    {
        string s = EditorPrefs.GetString(PrefKey, "");
        if (string.IsNullOrEmpty(s)) return null;
        EditorPrefs.DeleteKey(PrefKey);
        try { return JsonUtility.FromJson<Config>(s); }
        catch { return null; }
    }

    // 采样协程由 **EditorApplication.update** 驱动，不使用 MonoBehaviour：
    // Assets/Editor 下的脚本不能 AddComponent（Unity:
    // "Can't add script behaviour ... because it is an editor script"）。
    private static IEnumerator _routine;
    // 手动驱动迭代器时，`yield return <IEnumerator>` 不会自动展开（那是
    // MonoBehaviour 协程调度器干的事），所以自己用栈维护嵌套。
    private static readonly Stack<IEnumerator> _stack = new Stack<IEnumerator>();

    public static void EnsureRunning(Config cfg)
    {
        if (_routine != null)
        {
            PlaySampleLog.W("采样已在运行，忽略本次请求");
            return;
        }
        _routine = Run(cfg ?? new Config());
        _stack.Clear();
        _stack.Push(_routine);
        EditorApplication.update += Pump;
        PlaySampleLog.W("开始采样（EditorApplication.update 驱动）");
    }

    /// <summary>
    /// 每个编辑器帧推进迭代器；支持 `yield return 内层 IEnumerator` 的嵌套。
    /// `Current == null` 表示"等下一帧"，直接返回；异常在 MoveNext 抛出，这里兜住。
    /// </summary>
    private static void Pump()
    {
        if (_routine == null) { EditorApplication.update -= Pump; return; }
        try
        {
            while (_stack.Count > 0)
            {
                IEnumerator top = _stack.Peek();
                if (!top.MoveNext()) { _stack.Pop(); continue; }
                if (top.Current is IEnumerator inner)
                {
                    _stack.Push(inner);
                    continue;                 // 立刻进入内层
                }
                return;                       // Current == null：等下一帧
            }
            Finish();
        }
        catch (Exception ex)
        {
            PlaySampleLog.E("采样协程异常", ex);
            Finish();
        }
    }

    private static void Finish()
    {
        _routine = null;
        _stack.Clear();
        EditorApplication.update -= Pump;
    }

    public static void StartSampling(Config cfg)
    {
        PlaySampleLog.W("=== 开始采样 === 角色名=[" + (cfg.names ?? "") + "] 步长="
                        + cfg.step + "s 含 disabled=" + cfg.includeInactive);
        int n = CountCharacters(cfg);
        PlaySampleLog.W("场景里扫到 " + n + " 个角色"
            + (n == 0 ? "（0 个 = prefab 没拖进当前场景，或角色名写错）" : ""));
        EditorPrefs.SetString(LastNamesKey, cfg.names ?? "");
        PendingConfig = cfg;
        if (EditorApplication.isPlayingOrWillChangePlaymode)
        {
            PlaySampleLog.W("已经在 Play 模式里，直接开始采样");
            EnsureRunning(cfg);
            return;
        }
        SaveConfigToEditorPrefs(cfg);
        EditorApplication.EnterPlaymode();
        PlaySampleLog.W("已调用 EditorApplication.EnterPlaymode()");
    }

    /// <summary>只做诊断：扫角色、列 Animator 与状态、写日志，不进 Play 模式。</summary>
    public static void Diagnose(Config cfg)
    {
        PlaySampleLog.W("=== 诊断（不进 Play 模式）===");
        var roots = FindCharacters(cfg);
        PlaySampleLog.W("扫到角色 " + roots.Count + " 个"
                        + (roots.Count == 0 ? "：请把 prefabs/main 里的 prefab 拖进当前场景" : ""));
        foreach (var root in roots)
        {
            var animators = CollectAnimators(root);
            PlaySampleLog.W("角色 " + root.name + "：Animator " + animators.Count + " 个");
            for (int i = 0; i < animators.Count; i++)
            {
                var an = animators[i];
                var ctrl = an.runtimeAnimatorController as AnimatorController;
                if (ctrl == null)
                {
                    PlaySampleLog.W("   " + an.name + "：controller 为空（"
                        + (an.runtimeAnimatorController == null ? "null"
                           : an.runtimeAnimatorController.GetType().Name) + "）");
                    continue;
                }
                var states = CollectStates(ctrl);
                PlaySampleLog.W("   " + an.name + (i == 0 ? "（主）" : "（副）")
                                + "：controller=" + ctrl.name + " 状态 " + states.Count + " 个："
                                + string.Join(",", states.Take(24).Select(s => s.name).ToArray()));
            }
        }
    }

    [MenuItem("Tools/2DModel/运行时采样/开始采样（不用窗口）")]
    public static void MenuStart()
    {
        StartSampling(new Config
        {
            names = EditorPrefs.GetString(LastNamesKey, ""),
            step = 0.05f, includeInactive = true, bake = false,
        });
    }

    [MenuItem("Tools/2DModel/运行时采样/打开日志")]
    public static void OpenLog() { EditorUtility.RevealInFinder(PlaySampleLog.LogPath); }

    [MenuItem("Tools/2DModel/运行时采样/停止采样并退出 Play 模式")]
    public static void MenuStop()
    {
        StopRequested = true;
        PlaySampleLog.W("菜单：停止采样");
        if (EditorApplication.isPlaying) EditorApplication.ExitPlaymode();
    }

    // ---------------------------------------------------------- 主流程
    // 注意：协程里只有 try/finally（合法）；所有可能抛异常的步骤都在 helper 里。
    private static IEnumerator Run(Config cfg)
    {
        StopRequested = false;
        // 统一导出根：D:\VB\Unity2Spine\info\Data\PlayFrames
        string outDir = ExportRoots.Data("PlayFrames");
        try { Directory.CreateDirectory(outDir); }
        catch (Exception ex) { PlaySampleLog.E("建输出目录失败: " + outDir, ex); }

        var summary = new List<string>();
        int okFiles = 0, failStates = 0;
        var targets = FindCharacters(cfg);
        PlaySampleLog.W("角色 " + targets.Count + " 个，输出目录 " + outDir);
        if (targets.Count == 0)
            PlaySampleLog.W("没扫到角色：请先把 prefabs/main 里的 prefab 拖进当前场景再点开始");

        foreach (GameObject root in targets)
        {
            if (StopRequested) break;
            var prevActive = new List<KeyValuePair<GameObject, bool>>();
            ActivateChain(root, prevActive);
            try
            {
                yield return null;
                var animators = CollectAnimators(root);
                PlaySampleLog.W("角色 " + root.name + "：Animator " + animators.Count + " 个");
                for (int ai = 0; ai < animators.Count; ai++)
                {
                    var animator = animators[ai];
                    var ctrl = animator.runtimeAnimatorController as AnimatorController;
                    if (ctrl == null)
                    {
                        PlaySampleLog.W("   跳过 " + animator.name + "：没有 AnimatorController");
                        continue;
                    }
                    var states = CollectStates(ctrl);
                    PlaySampleLog.W("   " + animator.name + (ai == 0 ? "（主）" : "（副）")
                                    + "：状态 " + states.Count + " 个");
                    foreach (var st in states)
                    {
                        if (StopRequested) break;
                        var clip = st.state.motion as AnimationClip;
                        if (clip == null)
                        {
                            PlaySampleLog.W("      跳过 " + st.name + "：motion 不是 AnimationClip");
                            continue;
                        }
                        if (clip.length <= 0f)
                        {
                            PlaySampleLog.W("      跳过 " + st.name + "：时长 0");
                            continue;
                        }
                        string file = Sanitize(root.name) + "@" + Sanitize(animator.name)
                                      + "@" + Sanitize(st.name) + ".json";
                        string path = Path.Combine(outDir, file);
                        var res = new Result();
                        yield return SampleState(root, animator, st, clip, cfg, path, ai == 0, res);
                        if (res.ok)
                        {
                            okFiles++;
                            summary.Add("{\"char\": " + Str(root.name)
                                        + ", \"animator\": " + Str(animator.name)
                                        + ", \"state\": " + Str(st.name)
                                        + ", \"clip\": " + Str(clip.name)
                                        + ", \"duration\": " + F(clip.length)
                                        + ", \"isMain\": " + Bool(ai == 0)
                                        + ", \"file\": " + Str(file) + "}");
                        }
                        else
                        {
                            failStates++;
                            PlaySampleLog.E("采样失败 " + file + "：" + res.error);
                        }
                    }
                }
            }
            finally
            {
                RestoreChain(prevActive);
            }
        }

        WriteTextSafe(Path.Combine(outDir, "_summary.json"),
                      "[\n  " + string.Join(",\n  ", summary.ToArray()) + "\n]\n",
                      new Result());
        PlaySampleLog.W("=== 完成：成功 " + okFiles + " 个状态，失败 " + failStates
                        + "，输出 " + outDir + " ===");
        try { AssetDatabase.Refresh(); } catch { }
        if (EditorApplication.isPlaying) EditorApplication.ExitPlaymode();
    }

    // 逐状态采样：Animator.Play 定位 + Update(0) 让状态机求值（真运行时求值）。
    // 这里**没有** try/catch，风险步骤全在 helper 里。
    private static IEnumerator SampleState(GameObject root, Animator animator, StateEntry st,
                                           AnimationClip clip, Config cfg, string outPath,
                                           bool isMain, Result res)
    {
        int hash = GetStateHash(st);
        int frameCount = Mathf.Min(4000, Mathf.CeilToInt(clip.length / cfg.step) + 1);
        bool bake = cfg.bake && WantsBake(cfg, root.name);
        // 每个状态开始前先把 Animator 复位：否则"上一个状态打开过的部件"会留着，
        // 让本状态看起来是可见的（babariana 的 Start 就被 breed 污染过）。
        Rebind(animator);
        var sb = new StringBuilder();
        var sbPose = bake ? new StringBuilder() : null;
        sb.Append("{\n");
        sb.Append("  \"prefab\": ").Append(Str(root.name)).Append(",\n");
        sb.Append("  \"animator\": ").Append(Str(animator.name)).Append(",\n");
        sb.Append("  \"isMain\": ").Append(Bool(isMain)).Append(",\n");
        sb.Append("  \"state\": ").Append(Str(st.name)).Append(",\n");
        sb.Append("  \"clip\": ").Append(Str(clip.name)).Append(",\n");
        sb.Append("  \"layer\": ").Append(st.layer).Append(",\n");
        sb.Append("  \"duration\": ").Append(F(clip.length)).Append(",\n");
        sb.Append("  \"step\": ").Append(F(cfg.step)).Append(",\n");
        sb.Append("  \"mode\": \"playmode\",\n");
        sb.Append("  \"frames\": [\n");
        if (sbPose != null)
        {
            sbPose.Append("{\n");
            sbPose.Append("  \"prefab\": ").Append(Str(root.name)).Append(",\n");
            sbPose.Append("  \"clip\": ").Append(Str(clip.name)).Append(",\n");
            sbPose.Append("  \"duration\": ").Append(F(clip.length)).Append(",\n");
            sbPose.Append("  \"mode\": \"playmode\",\n");
            sbPose.Append("  \"frames\": [\n");
        }
        for (int i = 0; i < frameCount; i++)
        {
            float t = Mathf.Min(clip.length, i * cfg.step);
            float norm = clip.length <= 0f ? 0f : t / clip.length;
            if (!StepAnimator(animator, hash, st.layer, norm, res))
                yield break;
            sb.Append(i == 0 ? "    " : "    ,");
            sb.Append(BuildFrameJson(root, animator, t, norm, cfg, res));
            sb.Append("\n");
            if (sbPose != null)
            {
                sbPose.Append(i == 0 ? "    " : "    ,");
                sbPose.Append(BuildPoseFrameJson(root, animator, t, norm, res));
                sbPose.Append("\n");
            }
            if (!res.ok) yield break;
            // 每帧只在必要时让出：Animator.Play + Update(0) 是同步求值，
            // 一帧里连续采 25 个点没问题——比"每采一帧等一帧"快 20 倍左右。
            if (i % 25 == 24) yield return null;
            if (StopRequested) break;
        }
        yield return null;
        sb.Append("\n  ]\n}\n");
        WriteTextSafe(outPath, sb.ToString(), res);
        if (res.ok) PlaySampleLog.W("    " + Path.GetFileName(outPath));
        if (sbPose != null && res.ok)
        {
            sbPose.Append("\n  ]\n}\n");
            string posePath = Path.ChangeExtension(outPath, ".playpose.json");
            WriteTextSafe(posePath, sbPose.ToString(), res);
            if (res.ok) PlaySampleLog.W("        + " + Path.GetFileName(posePath) + "（全量 BakeMesh）");
        }
    }

    private static bool WantsBake(Config cfg, string charName)
    {
        if (!cfg.bake) return false;
        string want = cfg.bakeChars ?? "";
        if (want.Trim().Length == 0) return true;
        foreach (string s in want.Split(new[] { ',', ';', '，' }, StringSplitOptions.RemoveEmptyEntries))
        {
            string t = s.Trim();
            if (t.Length > 0 && charName.IndexOf(t, StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
        }
        return false;
    }

    private static void Rebind(Animator animator)
    {
        try { animator.Rebind(); }
        catch (Exception ex) { PlaySampleLog.E("Animator.Rebind 失败", ex); }
    }

    // ---------------------------------------------------------- 不带 yield 的 helper
    private static int GetStateHash(StateEntry st)
    {
        try { return st.state.nameHash != 0 ? st.state.nameHash : Animator.StringToHash(st.name); }
        catch { return Animator.StringToHash(st.name); }
    }

    private static bool StepAnimator(Animator animator, int hash, int layer,
                                     float norm, Result res)
    {
        try
        {
            animator.Play(hash, layer, Mathf.Clamp01(norm));
            animator.Update(0f);
            return true;
        }
        catch (Exception ex)
        {
            res.ok = false;
            res.error = "Animator.Play/Update 异常: " + ex.Message;
            return false;
        }
    }

    private static string BuildFrameJson(GameObject root, Animator animator,
                                         float t, float norm, Config cfg, Result res)
    {
        try
        {
            var b = new StringBuilder();
            var st = animator.GetCurrentAnimatorStateInfo(0);
            b.Append("{\"t\": ").Append(F(t))
             .Append(", \"normalized\": ").Append(F(norm))
             .Append(", \"stateHash\": ").Append(st.shortNameHash)
             .Append(", \"stateNorm\": ").Append(F(st.normalizedTime))
            .Append(",\n  \"transforms\": [");
            // GetComponentsInChildren(true) 已经包含自己，别再手动加一次（否则根节点会出现两条）
            var ts = new List<Transform>(root.GetComponentsInChildren<Transform>(true));
            for (int i = 0; i < ts.Count; i++)
            {
                if (i > 0) b.Append(", ");
                Transform x = ts[i];
                b.Append("{\"path\": ").Append(Str(PathOf(x)))
                 .Append(", \"localPos\": ").Append(V3(x.localPosition))
                 .Append(", \"localEuler\": ").Append(V3(x.localEulerAngles))
                 .Append(", \"localScale\": ").Append(V3(x.localScale))
                 .Append("}");
            }
            b.Append("],\n  \"renderers\": [");
            bool first = true;
            foreach (SkinnedMeshRenderer r in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                if (!first) b.Append(", ");
                first = false;
                b.Append("{\"path\": ").Append(Str(PathOf(r.transform)))
                 .Append(", \"kind\": \"skinned\"").Append(Flags(r))
                 .Append(", \"mesh\": ").Append(Str(r.sharedMesh == null ? "" : r.sharedMesh.name))
                 .Append(", \"bones\": ").Append(r.bones == null ? 0 : r.bones.Length)
                 .Append(", \"localToWorld\": ").Append(Mat4(r.transform.localToWorldMatrix));
                if (cfg.bake)
                {
                    var m = new Mesh();
                    r.BakeMesh(m, true);
                    Vector3[] vs = m.vertices;
                    b.Append(", \"bakedFirst\": [");
                    for (int i = 0; i < Mathf.Min(8, vs.Length); i++)
                    {
                        if (i > 0) b.Append(", ");
                        b.Append(V3(vs[i]));
                    }
                    b.Append("]");
                    UnityEngine.Object.DestroyImmediate(m);
                }
                b.Append("}");
            }
            foreach (MeshRenderer r in root.GetComponentsInChildren<MeshRenderer>(true))
            {
                if (!first) b.Append(", ");
                first = false;
                b.Append("{\"path\": ").Append(Str(PathOf(r.transform)))
                 .Append(", \"kind\": \"static\"").Append(Flags(r))
                 .Append(", \"localToWorld\": ").Append(Mat4(r.transform.localToWorldMatrix))
                 .Append("}");
            }
            foreach (SpriteRenderer r in root.GetComponentsInChildren<SpriteRenderer>(true))
            {
                if (!first) b.Append(", ");
                first = false;
                b.Append("{\"path\": ").Append(Str(PathOf(r.transform)))
                 .Append(", \"kind\": \"sprite\"").Append(Flags(r))
                 .Append(", \"sprite\": ").Append(Str(r.sprite == null ? "" : r.sprite.name))
                 .Append(", \"worldCorners\": ").Append(Corners(r))
                 .Append("}");
            }
            b.Append("]}");
            return b.ToString();
        }
        catch (Exception ex)
        {
            res.ok = false;
            res.error = "建帧 JSON 异常: " + ex.Message;
            return "{}";
        }
    }

    /// <summary>
    /// PoseFrames 兼容的一帧（含**全量 BakeMesh** 顶点/uv/三角形 + localToWorld +
    /// 显隐三件套）。写成 .playpose.json 后可以直接喂给
    /// `tools/calib_geo.py --pose <file>` 做逐顶点比对。
    /// 结构对齐 TwoDModelCalibExport：`skinned` 数组里同时放蒙皮与静态 mesh（用 kind 区分）。
    /// </summary>
    private static string BuildPoseFrameJson(GameObject root, Animator animator,
                                             float t, float norm, Result res)
    {
        try
        {
            var b = new StringBuilder();
            b.Append("{\"time\": ").Append(F(t))
             .Append(", \"normalized\": ").Append(F(norm))
            .Append(",\n  \"transforms\": [");
            // GetComponentsInChildren(true) 已经包含自己，别再手动加一次（否则根节点会出现两条）
            var ts = new List<Transform>(root.GetComponentsInChildren<Transform>(true));
            for (int i = 0; i < ts.Count; i++)
            {
                if (i > 0) b.Append(", ");
                Transform x = ts[i];
                b.Append("{\"path\": ").Append(Str(PathOf(x)))
                 .Append(", \"localPos\": ").Append(V3(x.localPosition))
                 .Append(", \"localEuler\": ").Append(V3(x.localEulerAngles))
                 .Append(", \"localScale\": ").Append(V3(x.localScale))
                 .Append("}");
            }
            b.Append("],\n  \"skinned\": [");
            bool first = true;
            foreach (SkinnedMeshRenderer r in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                if (!first) b.Append(", ");
                first = false;
                var m = new Mesh();
                bool ok = true;
                try { r.BakeMesh(m, true); }
                catch (Exception ex) { ok = false; WarnMeshOnce("skinned:" + (r.sharedMesh == null ? r.name : r.sharedMesh.name), ex); }
                b.Append("{\"path\": ").Append(Str(PathOf(r.transform)))
                 .Append(", \"kind\": \"skinned\", \"readable\": ").Append(Bool(ok))
                 .Append(", \"vertexCount\": ").Append(ok ? m.vertexCount : 0);
                if (ok)
                {
                    Vector3[] vs = m.vertices;
                    Vector2[] uv = m.uv;
                    int[] tris = m.triangles;
                    b.Append(", \"positions\": ").Append(V3List(vs))
                     .Append(", \"uvs\": ").Append(UVList(uv))
                     .Append(", \"triangles\": ").Append(IntList(tris));
                }
                b
                 .Append(", \"localToWorld\": ").Append(Mat4(r.transform.localToWorldMatrix))
                 .Append(", \"sortingOrder\": ").Append(r.sortingOrder)
                 .Append(", \"activeInHierarchy\": ").Append(Bool(r.gameObject.activeInHierarchy))
                 .Append(", \"activeSelf\": ").Append(Bool(r.gameObject.activeSelf))
                 .Append(", \"enabled\": ").Append(Bool(r.enabled))
                 .Append("}");
                UnityEngine.Object.DestroyImmediate(m);
            }
            foreach (MeshRenderer r in root.GetComponentsInChildren<MeshRenderer>(true))
            {
                var mf = r.GetComponent<MeshFilter>();
                if (mf == null || mf.sharedMesh == null) continue;
                if (!first) b.Append(", ");
                first = false;
                Mesh m = mf.sharedMesh;
                // Read/Write 关闭的 Mesh 读 .vertices/.uv/.triangles 会抛
                // "Not allowed to access vertices ... isReadable is false"。
                bool readable = m.isReadable;
                if (!readable) WarnMeshOnce("static:" + m.name, null);
                b.Append("{\"path\": ").Append(Str(PathOf(r.transform)))
                 .Append(", \"kind\": \"static\", \"readable\": ").Append(Bool(readable))
                 .Append(", \"vertexCount\": ").Append(readable ? m.vertexCount : 0);
                if (readable)
                    b.Append(", \"positions\": ").Append(V3List(m.vertices))
                     .Append(", \"uvs\": ").Append(UVList(m.uv))
                     .Append(", \"triangles\": ").Append(IntList(m.triangles));
                b
                 .Append(", \"localToWorld\": ").Append(Mat4(r.transform.localToWorldMatrix))
                 .Append(", \"sortingOrder\": ").Append(r.sortingOrder)
                 .Append(", \"activeInHierarchy\": ").Append(Bool(r.gameObject.activeInHierarchy))
                 .Append(", \"activeSelf\": ").Append(Bool(r.gameObject.activeSelf))
                 .Append(", \"enabled\": ").Append(Bool(r.enabled))
                 .Append("}");
            }
            b.Append("],\n  \"sprites\": [");
            first = true;
            foreach (SpriteRenderer r in root.GetComponentsInChildren<SpriteRenderer>(true))
            {
                if (!first) b.Append(", ");
                first = false;
                b.Append("{\"path\": ").Append(Str(PathOf(r.transform)))
                 .Append(", \"kind\": \"sprite\", \"worldCorners\": ").Append(Corners(r))
                 // 同口径判据（2026-09-19 加）：`worldCorners` 是 `SpriteRenderer.bounds`
                 // （**矩形**世界 AABB），而产物画的是**紧贴网格**（tight mesh），两者必然
                 // 不同大小 —— 之前拿它比出"头/脸小 15~20%"就是口径错。
                 // 下面这几项才能和产物同口径对：
                 //   spriteRect/ppu → 我们自己拼 quad 的口径
                 //   spriteBounds   → 精灵资产自己的 bounds（含 rect 尺寸/ppu）
                 .Append(", \"spriteRect\": ")
                 .Append(r.sprite == null ? "[0,0,0,0]" :
                         ("[" + F(r.sprite.rect.x) + ", " + F(r.sprite.rect.y) + ", "
                              + F(r.sprite.rect.width) + ", " + F(r.sprite.rect.height) + "]"))
                 .Append(", \"spritePpu\": ")
                 .Append(r.sprite == null ? "100" : F(r.sprite.pixelsPerUnit))
                 .Append(", \"spriteBoundsSize\": ")
                 .Append(r.sprite == null ? "[0,0,0]" :
                         ("[" + F(r.sprite.bounds.size.x) + ", "
                              + F(r.sprite.bounds.size.y) + ", "
                              + F(r.sprite.bounds.size.z) + "]"))
                 .Append(", \"spritePivot\": ")
                 .Append(r.sprite == null ? "[0.5,0.5]" :
                         ("[" + F(r.sprite.pivot.x / Mathf.Max(1f, r.sprite.rect.width))
                              + ", " + F(r.sprite.pivot.y / Mathf.Max(1f, r.sprite.rect.height)) + "]"))
                 .Append(", \"sortingOrder\": ").Append(r.sortingOrder)
                 .Append(", \"activeInHierarchy\": ").Append(Bool(r.gameObject.activeInHierarchy))
                 .Append(", \"activeSelf\": ").Append(Bool(r.gameObject.activeSelf))
                 .Append(", \"enabled\": ").Append(Bool(r.enabled))
                 .Append("}");
            }
            b.Append("]}");
            return b.ToString();
        }
        catch (Exception ex)
        {
            res.ok = false;
            res.error = "建 PoseFrames 兼容帧异常: " + ex.Message;
            return "{}";
        }
    }

    private static string V3List(Vector3[] vs)
    {
        var b = new StringBuilder("[");
        for (int i = 0; i < vs.Length; i++)
        {
            if (i > 0) b.Append(", ");
            b.Append(V3(vs[i]));
        }
        return b.Append("]").ToString();
    }

    private static string UVList(Vector2[] uvs)
    {
        var b = new StringBuilder("[");
        for (int i = 0; i < uvs.Length; i++)
        {
            if (i > 0) b.Append(", ");
            b.Append("[").Append(F(uvs[i].x)).Append(", ").Append(F(uvs[i].y)).Append("]");
        }
        return b.Append("]").ToString();
    }

    private static string IntList(int[] xs)
    {
        var b = new StringBuilder("[");
        for (int i = 0; i < xs.Length; i++)
        {
            if (i > 0) b.Append(", ");
            b.Append(xs[i]);
        }
        return b.Append("]").ToString();
    }

    private static void WriteTextSafe(string path, string text, Result res)
    {
        try
        {
            File.WriteAllText(path, text, new UTF8Encoding(false));
        }
        catch (Exception ex)
        {
            res.ok = false;
            res.error = "写文件失败: " + ex.Message;
            PlaySampleLog.E("写文件失败 " + path, ex);
        }
    }

    private static List<StateEntry> CollectStates(AnimatorController ctrl)
    {
        var outList = new List<StateEntry>();
        try
        {
            for (int li = 0; li < ctrl.layers.Length; li++)
                Collect(ctrl.layers[li].stateMachine, li, outList);
        }
        catch (Exception ex) { PlaySampleLog.E("遍历状态失败（controller=" + ctrl.name + "）", ex); }
        return outList;
    }

    private static void Collect(AnimatorStateMachine sm, int layer, List<StateEntry> outList)
    {
        if (sm == null) return;
        foreach (var cs in sm.states)
        {
            if (cs.state == null) continue;
            outList.Add(new StateEntry { name = cs.state.name, layer = layer, state = cs.state });
        }
        foreach (var sub in sm.stateMachines)
            Collect(sub.stateMachine, layer, outList);
    }

    /// <summary>主 Animator 排最前（与离线侧“层级 DFS 第一个”一致），其余照原顺序。</summary>
    public static List<Animator> CollectAnimators(GameObject root)
    {
        var list = new List<Animator>();
        try
        {
            var all = root.GetComponentsInChildren<Animator>(true);
            var main = root.GetComponentInChildren<Animator>(true);
            if (main != null) list.Add(main);
            foreach (var an in all) if (an != main) list.Add(an);
        }
        catch (Exception ex) { PlaySampleLog.E("收集 Animator 失败（" + root.name + "）", ex); }
        return list;
    }

    public static int CountCharacters(Config cfg)
    {
        try { return FindCharacters(cfg).Count; }
        catch { return 0; }
    }

    private static List<GameObject> FindCharacters(Config cfg)
    {
        var result = new List<GameObject>();
        try
        {
            var wanted = (cfg.names ?? "")
                .Split(new[] { ',', ';', '，' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(s => s.Trim()).Where(s => s.Length > 0).ToList();
            foreach (var go in SceneObjects())
            {
                if (go == null || go.transform.parent != null) continue;
                if (wanted.Count > 0)
                {
                    if (!wanted.Contains(go.name)) continue;
                }
                else
                {
                    if (go.GetComponentInChildren<Animator>(true) == null) continue;
                    if (go.GetComponentInChildren<SkinnedMeshRenderer>(true) == null) continue;
                }
                if (!cfg.includeInactive && !go.activeInHierarchy) continue;
                result.Add(go);
            }
        }
        catch (Exception ex) { PlaySampleLog.E("扫描场景角色失败", ex); }
        return result;
    }

    private static IEnumerable<GameObject> SceneObjects()
    {
        foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
            if (go != null && go.scene.IsValid() && go.scene.isLoaded) yield return go;
    }

    private static void ActivateChain(GameObject root, List<KeyValuePair<GameObject, bool>> prev)
    {
        try
        {
            var chain = new List<GameObject>();
            Transform t = root.transform;
            while (t != null) { chain.Add(t.gameObject); t = t.parent; }
            foreach (var g in chain)
            {
                prev.Add(new KeyValuePair<GameObject, bool>(g, g.activeSelf));
                g.SetActive(true);
            }
        }
        catch (Exception ex) { PlaySampleLog.E("激活角色失败（" + root.name + "）", ex); }
    }

    private static void RestoreChain(List<KeyValuePair<GameObject, bool>> prev)
    {
        for (int i = prev.Count - 1; i >= 0; i--)
        {
            try { if (prev[i].Key != null) prev[i].Key.SetActive(prev[i].Value); }
            catch { }
        }
    }

    private static string Flags(Renderer r)
    {
        return ", \"enabled\": " + Bool(r.enabled)
             + ", \"activeSelf\": " + Bool(r.gameObject.activeSelf)
             + ", \"activeInHierarchy\": " + Bool(r.gameObject.activeInHierarchy);
    }

    private static string Corners(SpriteRenderer r)
    {
        Bounds b = r.bounds;
        Vector3 c = b.center, e = b.extents;
        return "[" + V3(new Vector3(c.x - e.x, c.y - e.y, c.z)) + ", "
                   + V3(new Vector3(c.x + e.x, c.y - e.y, c.z)) + ", "
                   + V3(new Vector3(c.x + e.x, c.y + e.y, c.z)) + ", "
                   + V3(new Vector3(c.x - e.x, c.y + e.y, c.z)) + "]";
    }

    private static string V3(Vector3 v)
    {
        return "[" + F(v.x) + ", " + F(v.y) + ", " + F(v.z) + "]";
    }

    private static string Mat4(Matrix4x4 m)
    {
        var s = new StringBuilder("[");
        for (int i = 0; i < 4; i++)
        {
            if (i > 0) s.Append(", ");
            s.Append("[").Append(F(m[i, 0])).Append(", ").Append(F(m[i, 1])).Append(", ")
             .Append(F(m[i, 2])).Append(", ").Append(F(m[i, 3])).Append("]");
        }
        return s.Append("]").ToString();
    }

    private static string F(float v)
    {
        return v.ToString("0.######", System.Globalization.CultureInfo.InvariantCulture);
    }

    private static string Bool(bool v) { return v ? "true" : "false"; }

    private static string Str(string s)
    {
        if (s == null) return "\"\"";
        return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }

    private static string PathOf(Transform t)
    {
        var parts = new List<string>();
        Transform cur = t;
        while (cur != null) { parts.Insert(0, cur.name); cur = cur.parent; }
        return string.Join("/", parts.ToArray());
    }

    private static string Sanitize(string name)
    {
        if (string.IsNullOrEmpty(name)) return "_";
        foreach (char c in Path.GetInvalidFileNameChars()) name = name.Replace(c, '_');
        return name.Replace('/', '_').Replace('\\', '_').Replace(' ', '_');
    }

    private static readonly HashSet<string> _warnedMeshes = new HashSet<string>();

    /// <summary>同一个 Mesh 只报一次，避免日志被刷爆。</summary>
    private static void WarnMeshOnce(string key, Exception ex)
    {
        bool first;
        lock (_warnedMeshes) first = _warnedMeshes.Add(key);
        if (!first) return;
        PlaySampleLog.W("注意：" + key + " 读不到网格数据（Mesh 的 Read/Write 没开）。"
                        + "这一条只记 变换/显隐；要拿顶点就在该 Mesh 的导入设置里勾 Read/Write Enabled。"
                        + (ex == null ? "" : "（" + ex.Message + "）"));
    }
}
