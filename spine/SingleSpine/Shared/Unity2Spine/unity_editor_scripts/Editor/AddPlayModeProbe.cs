// AddPlayModeProbe.cs
// 批量把运行时采样组件 PlayModeProbe 挂到场景里的角色上（可批量移除、刷新状态表）。
//
// 菜单（Tools/2DModel/运行时采样/）：
//   · 给场景里的角色批量挂采样脚本（自动扫 root：子树里有 Animator + SkinnedMeshRenderer）
//   · 给选中的物体挂采样脚本
//   · 给 prefabs/main 名单里的角色挂采样脚本（按名字匹配场景 root）
//   · 从场景里移除采样脚本
//   · 刷新所有采样脚本的状态表（把 AnimatorController 的状态名/hash/层/时长写进组件）
//
// 说明：PlayModeProbe 是**普通（非 Editor）脚本**，所以能挂到 GameObject 上；
// 状态表由本工具在编辑器里填好，运行时不需要任何 Editor API。

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class AddPlayModeProbe
{
    // ------------------------------------------------------------ 菜单
    [MenuItem("Tools/2DModel/运行时采样/给场景里的角色批量挂采样脚本")]
    public static void AddToSceneCharacters() { Add(FindSceneCharacters(null), "场景里的角色"); }

    [MenuItem("Tools/2DModel/运行时采样/给选中的物体挂采样脚本")]
    public static void AddToSelection()
    {
        var list = new List<GameObject>();
        foreach (var go in Selection.gameObjects)
        {
            if (go == null) continue;
            if (go.GetComponentInChildren<Animator>(true) == null)
            {
                PlaySampleLog.W("跳过 " + go.name + "：子树里没有 Animator");
                continue;
            }
            list.Add(go);
        }
        Add(list, "选中的物体");
    }

    [MenuItem("Tools/2DModel/运行时采样/给 prefabs-main 名单里的角色挂采样脚本")]
    public static void AddToPrefabsMain()
    {
        var names = new List<string>();
        foreach (string guid in AssetDatabase.FindAssets("t:Prefab", new[] { "Assets/prefabs/main" }))
            names.Add(Path.GetFileNameWithoutExtension(AssetDatabase.GUIDToAssetPath(guid)));
        Add(FindSceneCharacters(names), "prefabs/main 名单（" + names.Count + " 个名字）");
    }

    [MenuItem("Tools/2DModel/运行时采样/从场景里移除采样脚本")]
    public static void RemoveFromScene()
    {
        int n = 0;
        foreach (var probe in FindProbes())
        {
            PlaySampleLog.W("移除 " + PathOf(probe.transform) + " 上的 PlayModeProbe");
            UnityEngine.Object.DestroyImmediate(probe);
            n++;
        }
        MarkDirty();
        PlaySampleLog.W("已移除 " + n + " 个 PlayModeProbe");
    }

    [MenuItem("Tools/2DModel/运行时采样/刷新所有采样脚本的状态表")]
    public static void RefreshAllStateTables()
    {
        int n = 0;
        foreach (var probe in FindProbes())
            if (FillStateTable(probe)) n++;
        MarkDirty();
        PlaySampleLog.W("已刷新 " + n + " 个采样脚本的状态表");
    }

    [MenuItem("Tools/2DModel/运行时采样/给摄像机挂逐个导出控制器")]
    public static void AttachActivationController()
    {
        Camera cam = Camera.main;
        if (cam == null)
        {
            foreach (var c in Resources.FindObjectsOfTypeAll<Camera>())
                if (c != null && !EditorUtility.IsPersistent(c) && c.scene.IsValid()) { cam = c; break; }
        }
        if (cam == null)
        {
            PlaySampleLog.W("场景里找不到 Camera，取消");
            return;
        }
        var go = cam.gameObject;
        var ctrl = go.GetComponent<SceneActivationController>();
        if (ctrl == null)
        {
            ctrl = Undo.AddComponent<SceneActivationController>(go);
            PlaySampleLog.W("已给 " + go.name + " 挂上 SceneActivationController（逐个导出：激活→采样→关回去）");
        }
        else
        {
            PlaySampleLog.W(go.name + " 上已经 SceneActivationController，没重复挂");
        }
        EditorUtility.SetDirty(ctrl);
        Selection.activeGameObject = go;
        MarkDirty();
    }

    [MenuItem("Tools/2DModel/运行时采样/把所有采样脚本设为：等外部唤醒")]
    public static void GateAllProbes()
    {
        int n = 0;
        foreach (var probe in FindProbes())
        {
            probe.waitForExternalStart = true;
            EditorUtility.SetDirty(probe);
            n++;
        }
        MarkDirty();
        PlaySampleLog.W("已把 " + n + " 个采样脚本设为『等外部唤醒』"
                        + "（它们不会自己跑，由摄像机上的 SceneActivationController 逐个放行）");
    }

    [MenuItem("Tools/2DModel/运行时采样/把所有采样脚本设为：自己跑")]
    public static void UngateAllProbes()
    {
        int n = 0;
        foreach (var probe in FindProbes())
        {
            probe.waitForExternalStart = false;
            EditorUtility.SetDirty(probe);
            n++;
        }
        MarkDirty();
        PlaySampleLog.W("已把 " + n + " 个采样脚本恢复成『自己跑』（Start 里就会开始采样）");
    }

    /// <summary>
    /// 一个角色可能有多个 Animator（babariana 有 Char_PECS_Babariana_NS1 和 *_Bg_Only），
    /// 而一个 probe 只负责一个。这个菜单自动给"没被任何 probe 覆盖"的 Animator 补挂 probe，
    /// 并把 animatorPath 精确指过去（否则会重复采同一个）。
    /// </summary>
    [MenuItem("Tools/2DModel/运行时采样/给多 Animator 的角色自动补挂 probe")]
    public static void AddProbesForUncoveredAnimators()
    {
        int added = 0, skipped = 0, touchedChars = 0;
        foreach (var root in FindSceneCharacters(null))
        {
            var anims = root.GetComponentsInChildren<Animator>(true);
            if (anims.Length <= 1) continue;

            var probes = root.GetComponentsInChildren<PlayModeProbe>(true);
            var covered = new HashSet<Animator>();
            foreach (var p in probes)
            {
                var a = p.ResolveAnimator();
                if (a != null) covered.Add(a);
            }

            bool any = false;
            foreach (var a in anims)
            {
                if (covered.Contains(a)) continue;

                GameObject host = FindFreeHost(a.transform);
                if (host == null)
                {
                    skipped++;
                    PlaySampleLog.W("  跳过 " + PathOf(a.transform) + "：找不到能挂 probe 的物体");
                    continue;
                }

                var probe = Undo.AddComponent<PlayModeProbe>(host);
                CopySettings(probes.Length > 0 ? probes[0] : null, probe);
                // 相对宿主写路径（宿主就是 Animator 所在节点时是 "."，非空，不会被当成"没填"）
                probe.animatorPath = PlayModeProbe.RelPath(host.transform, a.transform);
                bool ok = FillStateTable(probe);
                PlaySampleLog.W(string.Format("  补挂 {0} → 宿主 {1}，animatorPath='{2}'，状态表 {3}",
                                              PathOf(a.transform), PathOf(host.transform),
                                              probe.animatorPath, ok ? "已填" : "为空"));
                added++;
                any = true;
            }
            if (any) touchedChars++;
        }
        MarkDirty();
        PlaySampleLog.W(string.Format("自动补挂完成：涉及 {0} 个角色，新增 {1} 个 probe，跳过 {2}",
                                      touchedChars, added, skipped));
    }

    /// <summary>找一个没挂 PlayModeProbe 的宿主（优先自己，其次子物体，再往上找兄弟）。</summary>
    private static GameObject FindFreeHost(Transform t)
    {
        if (t.GetComponent<PlayModeProbe>() == null) return t.gameObject;
        for (int i = 0; i < t.childCount; i++)
            if (t.GetChild(i).GetComponent<PlayModeProbe>() == null) return t.GetChild(i).gameObject;
        Transform p = t.parent;
        while (p != null)
        {
            for (int i = 0; i < p.childCount; i++)
                if (p.GetChild(i).GetComponent<PlayModeProbe>() == null) return p.GetChild(i).gameObject;
            p = p.parent;
        }
        return null;
    }

    /// <summary>把已有 probe 的采样设置抄给新 probe，免得新的一直是默认值。</summary>
    private static void CopySettings(PlayModeProbe from, PlayModeProbe to)
    {
        if (from == null || to == null) return;
        to.mode = from.mode;
        to.step = from.step;
        to.bakeMeshes = from.bakeMeshes;
        to.followSeconds = from.followSeconds;
        to.outSubDir = from.outSubDir;
        to.waitForExternalStart = from.waitForExternalStart;
    }

    // ------------------------------------------------------------ 核心
    private static void Add(List<GameObject> targets, string what)
    {
        int added = 0, refreshed = 0, skipped = 0;
        foreach (var go in targets)
        {
            if (go == null) continue;
            var probe = go.GetComponent<PlayModeProbe>();
            if (probe == null)
            {
                probe = Undo.AddComponent<PlayModeProbe>(go);   // 可撤销
                added++;
            }
            else refreshed++;
            if (!FillStateTable(probe)) skipped++;
        }
        MarkDirty();
        PlaySampleLog.W(string.Format("批量挂采样脚本（{0}）：新增 {1}，刷新 {2}，状态表为空 {3}，共 {4} 个目标",
                                      what, added, refreshed, skipped, targets.Count));
        int inactive = 0;
        foreach (var go in targets)
            if (go != null && !go.activeInHierarchy) inactive++;
        if (inactive > 0)
            PlaySampleLog.W("注意：有 " + inactive + " 个目标是 inactive 的。"
                            + "MonoBehaviour 的 Start() 不会执行 → 采样不会跑，进 Play 前请先激活这些根物体。");
        if (added + refreshed > 0)
            PlaySampleLog.W("提示：Play 模式里采样组件会自己跑；跑完看 " + PlayModeProbe.LogPath);
    }

    /// <summary>把 AnimatorController 的状态写进组件字段（名字/hash/层/时长/clip 名）。</summary>
    public static bool FillStateTable(PlayModeProbe probe)
    {
        var anims = probe.GetComponentsInChildren<Animator>(true);
        if (anims.Length == 0) return false;

        // 一个角色可能有多个 Animator（例如 babariana 的 Char_PECS_Babariana_NS1 与
        // *_Bg_Only）。取"状态最多"的那个当主，并把它的**相对路径**写进 animatorPath，
        // 保证运行时 ResolveAnimator() 解析到的是同一个，不会采错对象。
        var animator = probe.ResolveAnimator();
        if (string.IsNullOrEmpty(probe.animatorPath) && anims.Length > 1)
        {
            int best = -1;
            Animator pick = animator;
            foreach (var a in anims)
            {
                int c = CountStates(a.runtimeAnimatorController as AnimatorController);
                PlaySampleLog.W(string.Format("  {0}：发现 Animator {1}（{2} 个状态）",
                    probe.name, PlayModeProbe.RelPath(probe.transform, a.transform), c));
                if (c > best) { best = c; pick = a; }
            }
            if (pick != null)
            {
                animator = pick;
                probe.animatorPath = PlayModeProbe.RelPath(probe.transform, pick.transform);
                PlaySampleLog.W(string.Format("  {0}：主 Animator 取 {1}（{2} 个状态）",
                                              probe.name, probe.animatorPath, best));
            }
        }
        if (animator == null) return false;
        var ctrl = animator.runtimeAnimatorController as AnimatorController;
        if (ctrl == null)
        {
            PlaySampleLog.W("  " + probe.name + "：没有 AnimatorController，状态表留空");
            return false;
        }
        var names = new List<string>();
        var hashes = new List<int>();
        var layers = new List<int>();
        var lengths = new List<float>();
        var clips = new List<string>();
        for (int li = 0; li < ctrl.layers.Length; li++)
            Collect(ctrl.layers[li].stateMachine, li, names, hashes, layers, lengths, clips);
        probe.stateNames = names.ToArray();
        probe.stateHashes = hashes.ToArray();
        probe.stateLayers = layers.ToArray();
        probe.stateLengths = lengths.ToArray();
        probe.clipNames = clips.ToArray();
        EditorUtility.SetDirty(probe);
        PlaySampleLog.W("  " + PathOf(probe.transform) + "：" + names.Count + " 个状态（"
                        + string.Join(",", names.Take(8).ToArray()) + (names.Count > 8 ? ",…" : "") + "）");
        return names.Count > 0;
    }

    private static int CountStates(AnimatorController ctrl)
    {
        if (ctrl == null) return 0;
        int n = 0;
        for (int li = 0; li < ctrl.layers.Length; li++)
        {
            var names = new List<string>();
            var hashes = new List<int>();
            var layers = new List<int>();
            var lengths = new List<float>();
            var clips = new List<string>();
            Collect(ctrl.layers[li].stateMachine, li, names, hashes, layers, lengths, clips);
            n += names.Count;
        }
        return n;
    }

    private static void Collect(AnimatorStateMachine sm, int layer,
                                List<string> names, List<int> hashes, List<int> layers,
                                List<float> lengths, List<string> clips)
    {
        if (sm == null) return;
        foreach (var cs in sm.states)
        {
            if (cs.state == null) continue;
            var clip = cs.state.motion as AnimationClip;
            names.Add(cs.state.name);
            hashes.Add(cs.state.nameHash != 0 ? cs.state.nameHash : Animator.StringToHash(cs.state.name));
            layers.Add(layer);
            lengths.Add(clip == null ? 0f : clip.length);
            clips.Add(clip == null ? "" : clip.name);
        }
        foreach (var sub in sm.stateMachines) Collect(sub.stateMachine, layer, names, hashes, layers, lengths, clips);
    }

    // ------------------------------------------------------------ 查找
    private static List<GameObject> FindSceneCharacters(List<string> wanted)
    {
        var result = new List<GameObject>();
        foreach (var go in SceneObjects())
        {
            if (go.transform.parent != null) continue;
            if (wanted != null && wanted.Count > 0 && !wanted.Contains(go.name)) continue;
            if (go.GetComponentInChildren<Animator>(true) == null) continue;
            if (go.GetComponentInChildren<SkinnedMeshRenderer>(true) == null) continue;
            result.Add(go);
        }
        result.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
        return result;
    }

    private static IEnumerable<PlayModeProbe> FindProbes()
    {
        foreach (var go in SceneObjects())
        {
            var p = go.GetComponent<PlayModeProbe>();
            if (p != null) yield return p;
        }
    }

    private static IEnumerable<GameObject> SceneObjects()
    {
        foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
            if (go != null && go.scene.IsValid() && go.scene.isLoaded) yield return go;
    }

    public static void MarkDirty()
    {
        try
        {
            var scene = SceneManager.GetActiveScene();
            if (scene.IsValid()) UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(scene);
        }
        catch (Exception ex) { PlaySampleLog.E("标记场景脏失败", ex); }
    }

    private static string PathOf(Transform t)
    {
        var parts = new List<string>();
        Transform cur = t;
        while (cur != null) { parts.Insert(0, cur.name); cur = cur.parent; }
        return string.Join("/", parts.ToArray());
    }
}

/// <summary>PlayModeProbe 的 Inspector：直接在这里刷新状态表 / 移除。</summary>
[CustomEditor(typeof(PlayModeProbe))]
public class PlayModeProbeEditor : Editor
{
    public override void OnInspectorGUI()
    {
        DrawDefaultInspector();
        var probe = (PlayModeProbe)target;
        EditorGUILayout.Space();
        EditorGUILayout.LabelField("状态表", probe.stateNames == null
            ? "（空）" : (probe.stateNames.Length + " 个"));
        if (GUILayout.Button("刷新状态列表（读当前 Animator 的 controller）"))
        {
            AddPlayModeProbe.FillStateTable(probe);
            EditorUtility.SetDirty(probe);
        }
        if (GUILayout.Button("从本物体移除采样脚本"))
            UnityEngine.Object.DestroyImmediate(probe);
    }
}

/// <summary>
/// 批量把采样选项写进场景里**所有** PlayModeProbe（模式 / 步长 / 全量 BakeMesh / 记录时长）。
/// 为什么需要：组件是批量挂上去的，逐个体检勾 bakeMeshes 不现实。
/// </summary>
public class PlayProbeOptionsWindow : EditorWindow
{
    private PlayModeProbe.ProbeMode _mode = PlayModeProbe.ProbeMode.AllStates;
    private float _step = 0.05f;
    private bool _bake;
    private float _follow = 20f;
    private string _outSubDir = "probe_step";
    private PlayModeProbe.SampleAdvance _advance = PlayModeProbe.SampleAdvance.NaturalStep;
    private int _yieldEvery = 0;
    private string _info = "";

    [MenuItem("Tools/2DModel/运行时采样/批量设置采样选项窗口")]
    public static void Open()
    {
        var w = GetWindow<PlayProbeOptionsWindow>("采样选项");
        w.minSize = new Vector2(460, 220);
    }

    private void OnGUI()
    {
        EditorGUILayout.HelpBox(
            "下面这些值会**批量写进场景里所有 PlayModeProbe**（不需要一个个在 Inspector 里勾）。\n" +
            "「写全量 BakeMesh」会额外产出 <角色>@<Animator>@<状态>.playpose.json（体积大，按需限制角色）。",
            MessageType.Info);

        _mode = (PlayModeProbe.ProbeMode)EditorGUILayout.EnumPopup(
            new GUIContent("模式", "AllStates=逐个状态采样（会切动画）；FollowRuntime=不干扰播放，只记录"),
            _mode);
        _step = Mathf.Max(0.01f, EditorGUILayout.FloatField("采样步长（秒）", _step));
        _advance = (PlayModeProbe.SampleAdvance)EditorGUILayout.EnumPopup(
            new GUIContent("推进方式", "NaturalStep=连续推进（显隐正确，推荐）；Seek=逐个时间点跳帧（旧行为，m_IsActive 会粘住）"),
            _advance);
        _yieldEvery = Mathf.Max(0, EditorGUILayout.IntField(
            new GUIContent("每采 N 点让出一帧（0=不让出）", "NaturalStep 下让出会让 Unity 自己 Update，时间轴可能错位；只在 BakeMesh 太慢时用"),
            _yieldEvery));
        _bake = EditorGUILayout.Toggle(
            new GUIContent("写全量 BakeMesh（体积大）", "勾上才有 .playpose.json，可做逐顶点比对"), _bake);
        _follow = Mathf.Max(0.1f, EditorGUILayout.FloatField("FollowRuntime 记录时长（秒）", _follow));
        _outSubDir = EditorGUILayout.TextField(
            new GUIContent("输出子目录", "相对 D:\\VB\\Unity2Spine\\info\\Data\\PlayFrames。默认 probe_step，和旧的 seek 采样结果分开；留空=写 PlayFrames 本身"),
            _outSubDir);

        EditorGUILayout.Space();
        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("应用到场景里所有采样脚本", GUILayout.Height(32))) ApplyAll();
        if (GUILayout.Button("从场景里读取（取第一个）", GUILayout.Height(32))) ReadOne();
        EditorGUILayout.EndHorizontal();
        EditorGUILayout.Space();
        EditorGUILayout.LabelField(_info, EditorStyles.wordWrappedLabel);
    }

    private void ApplyAll()
    {
        int n = 0;
        foreach (var probe in Probes())
        {
            probe.mode = _mode;
            probe.step = _step;
            probe.advance = _advance;
            probe.yieldEvery = _yieldEvery;
            probe.bakeMeshes = _bake;
            probe.followSeconds = _follow;
            probe.outSubDir = _outSubDir;
            EditorUtility.SetDirty(probe);
            n++;
        }
        AddPlayModeProbe.MarkDirty();
        _info = string.Format("已把 模式={0} 步长={1}s 推进={2} 让出={3} BakeMesh={4} 时长={5}s 子目录='{6}' 写进 {7} 个 PlayModeProbe",
                              _mode, _step, _advance, _yieldEvery, _bake, _follow, _outSubDir, n);
        PlaySampleLog.W(_info);
    }

    private void ReadOne()
    {
        foreach (var probe in Probes())
        {
            _mode = probe.mode;
            _step = Mathf.Max(0.01f, probe.step);
            _advance = probe.advance;
            _yieldEvery = Mathf.Max(0, probe.yieldEvery);
            _bake = probe.bakeMeshes;
            _follow = Mathf.Max(0.1f, probe.followSeconds);
            _outSubDir = probe.outSubDir ?? "";
            _info = "已读取 " + probe.name + " 的选项";
            PlaySampleLog.W(_info);
            return;
        }
        _info = "场景里没有 PlayModeProbe";
    }

    private IEnumerable<PlayModeProbe> Probes()
    {
        foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
        {
            if (go == null) continue;
            if (EditorUtility.IsPersistent(go)) continue;
            if (!go.scene.IsValid() || !go.scene.isLoaded) continue;
            var p = go.GetComponent<PlayModeProbe>();
            if (p != null) yield return p;
        }
    }
}
