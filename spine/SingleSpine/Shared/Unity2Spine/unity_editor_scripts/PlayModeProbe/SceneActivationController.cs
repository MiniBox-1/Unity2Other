// SceneActivationController.cs —— 挂在 Camera（或任意常驻物体）上的"逐个导出"调度器
//
// 解决的问题：19 个角色全部放在场景里、都在 (0,0,0)、里面还有一堆 disable 的部件。
// 如果让所有 PlayModeProbe 在 Start() 里一起跑：19 个动画同时乱跳、帧率崩、
// 全量 BakeMesh 慢到没法用，日志也会糊在一起。
//
// 本脚本把流程改成**串行**：
//   【角色 1】激活 → 唤醒它的 probe → 等采样完成 → 关回 inactive
//   【角色 2】激活 → 唤醒它的 probe → 等采样完成 → 关回 inactive
//   ……
//   全部跑完 → 把所有场景根的激活状态恢复成"进 Play 之前的样子"
//
// 依赖 PlayModeProbe.waitForExternalStart：本脚本在 Awake 里把场景里**所有** probe
// 设成"等外部唤醒"，所以 probe 不会自己跑，只会被这里一个一个放行。
// Awake() 一定早于所有 Start()，所以这个设置一定生效。
//
// 日志：和 probe 共用一个文件（D:\VB\Unity2Spine\info\_logs\play_probe.log，Console 打 [PlayProbe]）。
//
// 注意：`activateDescendants=true`（默认）会把角色下面**原本 disable 的部件也强行打开**，
//       这对"导出要能读到/渲染到所有部件"是必要的，但会让这些部件的 activeSelf 真值
//       和 Unity 实际渲染不一致（有 m_IsActive 曲线的部件仍会被曲线覆盖回去）。
//       只想要干净真值就把这个开关关掉——probe 采样并不需要部件是打开的。

using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

[DisallowMultipleComponent]
public class SceneActivationController : MonoBehaviour
{
    [Header("目标范围")]
    [Tooltip("只处理名字包含该子串的场景根（区分大小写不敏感）；留空 = 全部根")]
    public string nameFilter = "";
    [Tooltip("跳过自己所在的根（挂在 Camera 上时就是跳过 Main Camera）")]
    public bool skipOwnRoot = true;
    [Tooltip("按名字把某些根排除掉（逗号分隔的子串，命中任一即跳过）")]
    public string excludeNames = "";
    [Tooltip("只处理这些根（逗号分隔的子串，命中任一即处理）；留空 = 全部。补跑用，例如：babariana,constantias2_normal")]
    public string onlyNames = "";

    [Header("逐个导出")]
    [Tooltip("把场景里所有 probe 改成『等外部唤醒』，由本脚本逐个放行。强烈建议保持开启")]
    public bool gateAllProbes = true;
    [Tooltip("同时只让一个角色处于激活状态（其余的先关掉，全部跑完再恢复原状）")]
    public bool oneAtATime = true;
    [Tooltip("激活根时，把它下面原本 disable 的部件也一起打开（导出需要；会改写 activeSelf 真值）")]
    public bool activateDescendants = true;
    [Tooltip("进 Play 后自动开始；关掉则等手动 Begin()（Inspector 按钮 / 按键）")]
    public bool autoStart = true;

    [Header("节奏与超时")]
    [Tooltip("单个角色等采样完成的最长时间（秒），超时就跳过它继续下一个")]
    public float perTargetTimeoutSeconds = 600f;
    [Tooltip("目标里没有 probe 时，保持打开多久再关回去（秒）")]
    public float noProbeHoldSeconds = 0.5f;
    [Tooltip("每个角色之间的间隔（秒）")]
    public float gapSeconds = 0f;

    [Header("手动控制（None = 不绑定）")]
    public KeyCode startKey = KeyCode.None;
    public KeyCode skipKey = KeyCode.None;
    public KeyCode abortKey = KeyCode.None;

    // ------------------------------------------------------------ 运行状态
    public bool IsFinished { get; private set; }
    public int CurrentIndex { get; private set; }
    public int TotalTargets { get; private set; }

    private List<GameObject> _targets = new List<GameObject>();
    private Dictionary<GameObject, bool> _origActive = new Dictionary<GameObject, bool>();
    private Coroutine _routine;
    private bool _skipCurrent;
    private bool _abort;

    // ------------------------------------------------------------ 生命周期
    private void Awake()
    {
        PlayModeProbe.Log("[激活控制] Awake：挂在 " + name + "（场景 " + gameObject.scene.name + "）");

        if (gateAllProbes)
        {
            int n = 0;
            foreach (PlayModeProbe p in FindObjectsOfType<PlayModeProbe>(true))
            {
                if (p == null || p.waitForExternalStart) continue;
                p.waitForExternalStart = true;
                n++;
            }
            PlayModeProbe.Log("[激活控制] 已把 " + n + " 个 probe 设为『等外部唤醒』");
        }
        CollectTargets();
    }

    private void Start()
    {
        if (autoStart) Begin();
    }

    private void Update()
    {
        if (startKey != KeyCode.None && Input.GetKeyDown(startKey)) Begin();
        if (skipKey != KeyCode.None && Input.GetKeyDown(skipKey)) { _skipCurrent = true; PlayModeProbe.Log("[激活控制] 收到跳过当前角色的指令"); }
        if (abortKey != KeyCode.None && Input.GetKeyDown(abortKey)) { _abort = true; PlayModeProbe.Log("[激活控制] 收到中止指令"); }
    }

    private void OnDestroy()
    {
        RestoreAllRoots("OnDestroy");
    }

    // ------------------------------------------------------------ 对外接口
    /// <summary>开始逐个导出。</summary>
    public void Begin()
    {
        if (_routine != null) { PlayModeProbe.Log("[激活控制] 已经在跑了，忽略 Begin()"); return; }
        _routine = StartCoroutine(RunSequential());
    }

    /// <summary>跳过当前角色（跑到一半也能用）。</summary>
    public void SkipCurrent() { _skipCurrent = true; }

    /// <summary>中止整个流程并恢复现场。</summary>
    public void Abort() { _abort = true; }

    // ------------------------------------------------------------ 主流程
    private IEnumerator RunSequential()
    {
        PlayModeProbe.Log(string.Format("[激活控制] 开始逐个导出：{0} 个目标，单角色超时 {1}s，"
                                        + "同步独占={2}，打开子部件={3}",
                                        _targets.Count, perTargetTimeoutSeconds, oneAtATime, activateDescendants));

        // 1) 记下每个目标根进 Play 时的激活状态；独占模式下先把它们全关掉
        _origActive.Clear();
        foreach (GameObject r in _targets)
            if (r != null) _origActive[r] = r.activeSelf;

        if (oneAtATime)
        {
            int closed = 0;
            foreach (GameObject r in _targets)
                if (r != null && r.activeSelf) { r.SetActive(false); closed++; }
            if (closed > 0)
            {
                PlayModeProbe.Log("[激活控制] 独占模式：已先把 " + closed + " 个角色关掉");
                yield return null;   // 让关闭生效、probe 的协程先挂起
            }
        }

        // 2) 逐个角色
        TotalTargets = _targets.Count;
        for (int i = 0; i < _targets.Count; i++)
        {
            if (_abort) { PlayModeProbe.Log("[激活控制] 已中止，停止在 " + (i + 1) + "/" + _targets.Count); break; }

            GameObject root = _targets[i];
            CurrentIndex = i + 1;
            if (root == null) continue;

            _skipCurrent = false;
            PlayModeProbe.Log(string.Format("[激活控制] ({0}/{1}) ==== {2} ====",
                                            i + 1, _targets.Count, root.name));

            bool rootWasInactive = !root.activeSelf;
            List<GameObject> opened = OpenTarget(root);
            int extraParts = opened.Count - (rootWasInactive ? 1 : 0);
            if (extraParts > 0)
                PlayModeProbe.Log(string.Format("    {0}：额外打开了 {1} 个原本 inactive 的部件"
                                                + "（会改写它们的 activeSelf 真值）", root.name, extraParts));

            PlayModeProbe[] probes = root.GetComponentsInChildren<PlayModeProbe>(true);
            WarnUncoveredAnimators(root, probes);
            if (probes.Length == 0)
            {
                PlayModeProbe.Log("    " + root.name + "：没有 probe，保持 " + noProbeHoldSeconds + "s");
                yield return WaitSeconds(noProbeHoldSeconds);
            }
            else
            {
                PlayModeProbe.Log("    " + root.name + "：唤醒 " + probes.Length + " 个 probe");
                for (int k = 0; k < probes.Length; k++)
                    if (probes[k] != null) probes[k].BeginSampling();

                float t0 = Time.time;
                while (true)
                {
                    bool all = true;
                    for (int k = 0; k < probes.Length; k++)
                    {
                        PlayModeProbe p = probes[k];
                        if (p != null && !p.IsDone) { all = false; break; }
                    }
                    if (all) break;
                    if (_skipCurrent)
                    {
                        PlayModeProbe.Log("    " + root.name + "：用户跳过，不等了");
                        break;
                    }
                    if (Time.time - t0 > perTargetTimeoutSeconds)
                    {
                        PlayModeProbe.Log("    " + root.name + "：等待超时 " + perTargetTimeoutSeconds + "s，继续下一个");
                        break;
                    }
                    yield return null;
                }

                for (int k = 0; k < probes.Length; k++)
                    if (probes[k] != null)
                        PlayModeProbe.Log("    " + probes[k].name + " → " + (probes[k].DoneReason ?? "(没结束)"));
            }

            CloseTarget(opened, root);
            if (gapSeconds > 0f) yield return WaitSeconds(gapSeconds);
            else yield return null;
        }

        // 3) 恢复现场
        RestoreAllRoots("逐个导出结束");
        IsFinished = true;
        PlayModeProbe.Log("[激活控制] 全部完成。日志 " + PlayModeProbe.LogPath);
        PlayModeProbe.Log("[激活控制] 输出目录：" + OutputDirs());
        _routine = null;
    }

    // ------------------------------------------------------------ 激活 / 恢复
    /// <summary>打开一个目标根（以及它下面原本 inactive 的部件），返回"被我们打开过的物体"。</summary>
    private List<GameObject> OpenTarget(GameObject root)
    {
        var opened = new List<GameObject>();
        if (!root.activeSelf)
        {
            root.SetActive(true);
            opened.Add(root);
        }
        if (!activateDescendants) return opened;

        // 先取快照再逐个打开（开父级不会增删 Transform，数组是稳定的）
        Transform[] all = root.GetComponentsInChildren<Transform>(true);
        for (int i = 0; i < all.Length; i++)
        {
            GameObject go = all[i].gameObject;
            if (go == gameObject) continue;
            if (go.activeSelf) continue;
            go.SetActive(true);
            opened.Add(go);
        }
        return opened;
    }

    /// <summary>把这一轮打开过的物体关回去（倒序：先子后父）。</summary>
    private void CloseTarget(List<GameObject> opened, GameObject root)
    {
        int n = 0;
        for (int i = opened.Count - 1; i >= 0; i--)
        {
            GameObject go = opened[i];
            if (go == null) continue;
            go.SetActive(false);
            n++;
        }
        PlayModeProbe.Log("    " + root.name + "：已把 " + n + " 个物体关回 inactive");
    }

    private void RestoreAllRoots(string why)
    {
        if (_origActive.Count == 0) return;
        int n = 0;
        foreach (KeyValuePair<GameObject, bool> kv in _origActive)
        {
            if (kv.Key == null) continue;
            if (kv.Key.activeSelf == kv.Value) continue;
            kv.Key.SetActive(kv.Value);
            n++;
        }
        PlayModeProbe.Log("[激活控制] 恢复场景根激活状态：" + n + " 个（" + why + "）");
    }

    private static IEnumerator WaitSeconds(float s)
    {
        float t0 = Time.time;
        while (Time.time - t0 < s) yield return null;
    }

    /// <summary>
    /// 一个角色可能有多个 Animator（例如 babariana 的 Char_PECS_Babariana_NS1 与 *_Bg_Only），
    /// 而一个 probe 默认只负责其中一个。这里点名"没被任何 probe 覆盖"的 Animator，
    /// 免得跑完才发现少采了一半状态。
    /// </summary>
    private static void WarnUncoveredAnimators(GameObject root, PlayModeProbe[] probes)
    {
        Animator[] all = root.GetComponentsInChildren<Animator>(true);
        if (all.Length <= 1) return;

        var covered = new HashSet<Animator>();
        for (int i = 0; i < probes.Length; i++)
        {
            if (probes[i] == null) continue;
            Animator a = probes[i].ResolveAnimator();
            if (a != null) covered.Add(a);
        }

        var missing = new List<string>();
        for (int i = 0; i < all.Length; i++)
            if (!covered.Contains(all[i]))
                missing.Add(PlayModeProbe.RelPath(root.transform, all[i].transform));

        if (missing.Count > 0)
            PlayModeProbe.Log(string.Format(
                "    警告：{0} 有 {1} 个 Animator，其中 {2} 个没被任何 probe 覆盖，这些状态不会被采样：{3}。"
                + "补法：在被漏掉的 Animator 所在节点下面挂一个 probe，把它的 animatorPath 填成上面的路径。",
                root.name, all.Length, missing.Count, string.Join(", ", missing.ToArray())));
    }

    // ------------------------------------------------------------ 目标收集
    private void CollectTargets()
    {
        _targets.Clear();
        Scene scene = gameObject.scene.IsValid() ? gameObject.scene : SceneManager.GetActiveScene();
        Transform ownRoot = transform.root;

        string[] excludes = string.IsNullOrEmpty(excludeNames)
            ? new string[0]
            : excludeNames.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);
        string[] only = string.IsNullOrEmpty(onlyNames)
            ? new string[0]
            : onlyNames.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);

        foreach (GameObject root in scene.GetRootGameObjects())
        {
            if (root == null) continue;
            if (skipOwnRoot && root.transform == ownRoot) continue;
            if (!string.IsNullOrEmpty(nameFilter)
                && root.name.IndexOf(nameFilter, StringComparison.OrdinalIgnoreCase) < 0) continue;

            if (only.Length > 0)
            {
                bool hit = false;
                for (int i = 0; i < only.Length; i++)
                {
                    string o = only[i].Trim();
                    if (o.Length > 0 && root.name.IndexOf(o, StringComparison.OrdinalIgnoreCase) >= 0)
                    { hit = true; break; }
                }
                if (!hit) continue;
            }

            bool excluded = false;
            for (int i = 0; i < excludes.Length; i++)
            {
                string e = excludes[i].Trim();
                if (e.Length > 0 && root.name.IndexOf(e, StringComparison.OrdinalIgnoreCase) >= 0)
                { excluded = true; break; }
            }
            if (excluded) continue;

            // 只挑"像角色"的根：子树里得有 SkinnedMeshRenderer（或 MeshRenderer / SpriteRenderer）
            if (root.GetComponentInChildren<Renderer>(true) == null) continue;
            _targets.Add(root);
        }

        _targets.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
        PlayModeProbe.Log("[激活控制] 目标 " + _targets.Count + " 个："
            + string.Join(", ", ToNameArray(_targets.GetRange(0, Math.Min(8, _targets.Count))))
            + (_targets.Count > 8 ? ", …" : ""));
    }

    private static string[] ToNameArray(List<GameObject> gos)
    {
        var a = new string[gos.Count];
        for (int i = 0; i < gos.Count; i++) a[i] = gos[i] == null ? "?" : gos[i].name;
        return a;
    }

    /// <summary>列出场景里 probe 实际用的输出目录（各自可能配了不同的 outSubDir）。</summary>
    private static string OutputDirs()
    {
        var dirs = new List<string>();
        foreach (PlayModeProbe p in FindObjectsOfType<PlayModeProbe>(true))
        {
            if (p == null) continue;
            string d = p.OutDir;
            if (!dirs.Contains(d)) dirs.Add(d);
        }
        if (dirs.Count == 0) return "(场景里没有 probe)";
        return string.Join(" | ", dirs.ToArray());
    }
}
