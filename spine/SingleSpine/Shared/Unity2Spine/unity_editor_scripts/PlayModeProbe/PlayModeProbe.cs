// PlayModeProbe.cs  —— 运行时采样组件（放在 Assets/Editor 之外，可挂到 GameObject）
//
// 和 Assets/Editor/PlayModeSamplerRunner.cs 的区别：
//   · 这个是**普通 MonoBehaviour**，可以用编辑器菜单批量挂到场景里的角色上；
//   · 它在 **游戏循环里**运行（真运行时：状态机切换、writeDefaultValues、物理都生效），
//     而不是编辑器脚本用 EditorApplication.update 手动驱动；
//   · 状态表（名字/hash/层/时长）由编辑器工具预先写进组件字段，运行时不需要
//     任何 Editor API，因此可以直接用在打包后的游戏里。
//
// 两种模式：
//   AllStates      —— 逐个状态 Rebind + Play + Update(0) 逐帧采样（用于离线校准）。
//                     注意：会真的切换动画，只适合单独跑，别和"正常游戏"混。
//   FollowRuntime  —— 完全不干扰播放，只按帧记录"当前在播什么 + 各渲染器显隐"，
//                     持续 followSeconds 秒（用于记录玩家实际操作时的动态表现）。
//
// 输出：D:\VB\Unity2Spine\info\Data\PlayFrames\<角色>@<Animator>@<状态>.json
//       打开 bakeMeshes 时额外写 <...>.playpose.json（PoseFrames 兼容，含全量顶点）
// 日志：<工程>/play_probe.log

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

[DisallowMultipleComponent]
public class PlayModeProbe : MonoBehaviour
{
    public enum ProbeMode { AllStates, FollowRuntime }

    [Header("采样设置")]
    public ProbeMode mode = ProbeMode.AllStates;

    /// <summary>时间轴推进方式。0=自然步进（新，默认）—— 让状态机连续走完，离散的
    /// m_IsActive 才会被正确应用；1=跳帧（旧行为）—— 逐点 Play(hash,layer,t/dur)，
    /// 快，但实测会把"动画里打开过的物体"一直粘在 ON，显隐真值不可信。</summary>
    public enum SampleAdvance { NaturalStep, Seek }
    [Tooltip("时间轴推进方式：NaturalStep=连续推进（能正确还原 SetActive 离散曲线）；Seek=逐个时间点跳帧（旧行为，快但 m_IsActive 会粘住）")]
    public SampleAdvance advance = SampleAdvance.NaturalStep;
    [Tooltip("NaturalStep 下每采多少点让出一帧；0=不让出（最准确）。让出会让 Unity 自己也 Update 这个 Animator，时间轴会错位，仅当 BakeMesh 太慢时才用")]
    public int yieldEvery = 0;

    [Tooltip("采样步长（秒）")] public float step = 0.05f;
    [Tooltip("额外写全量 BakeMesh（PoseFrames 兼容的 .playpose.json，体积大）")]
    public bool bakeMeshes = false;
    [Tooltip("FollowRuntime 模式的记录时长（秒）")] public float followSeconds = 20f;
    [Tooltip("输出子目录（相对 D:\\VB\\Unity2Spine\\info\\Data\\PlayFrames）。默认 probe_step：和旧的 seek 采样结果分开，避免互相覆盖；留空=直接写 PlayFrames")]
    public string outSubDir = "probe_step";
    [Tooltip("等外部唤醒再采样（相机上的 SceneActivationController 逐个角色放行）；勾上后 Start 不会自己跑")]
    public bool waitForExternalStart = false;

    private bool _beginRequested;

    /// <summary>外部控制器（SceneActivationController）用它逐个放行本 probe。</summary>
    public void BeginSampling()
    {
        _beginRequested = true;
    }

    [Header("状态表（由编辑器工具填；也可手动点“刷新状态列表”）")]
    [Tooltip("相对角色根的 Animator 路径；留空 = 子树里第一个。一个角色有多个 Animator 时用它区分")]
    public string animatorPath = "";
    public string[] stateNames = new string[0];
    public int[] stateHashes = new int[0];
    public int[] stateLayers = new int[0];
    public float[] stateLengths = new float[0];
    public string[] clipNames = new string[0];

    public string OutDir
    {
        get
        {
            // 统一导出根：D:\VB\Unity2Spine\info\Data\PlayFrames（见 Assets\Script\ExportRoots.cs）
            string d = ExportRoots.Data("PlayFrames");
            if (!string.IsNullOrEmpty(outSubDir)) d = Path.Combine(d, outSubDir);
            return d;
        }
    }

    public static string LogPath
    {
        get { return Path.Combine(ExportRoots.Logs(), "play_probe.log"); }
    }

    public static void Log(string msg)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + "  [" + "PlayProbe" + "] " + msg;
        try { File.AppendAllText(LogPath, line + Environment.NewLine); } catch { }
        Debug.Log("[PlayProbe] " + msg);
    }

    private static readonly HashSet<string> _warned = new HashSet<string>();

    private static readonly HashSet<string> _noted = new HashSet<string>();

    /// <summary>同一类提示只写一次。</summary>
    private static void NoteOnce(string key, string msg)
    {
        bool first;
        lock (_noted) first = _noted.Add(key);
        if (first) Log(msg);
    }

    /// <summary>同一类问题只报一次（否则每帧几百条会把日志刷爆）。</summary>
    private static void WarnOnce(string key, Exception ex)
    {
        bool first;
        lock (_warned) first = _warned.Add(key);
        if (!first) return;
        Log("注意：" + key + " 读不到网格数据（Mesh 的 Read/Write 没开）。"
            + "这一条只记 变换/显隐，顶点为空；要拿顶点就在该 Mesh 的导入设置里勾上 Read/Write Enabled。"
            + (ex == null ? "" : "（" + ex.Message + "）"));
    }

    /// <summary>本 probe 是否已经结束（正常跑完 / 跳过）。摄像机控制器靠它决定何时恢复激活状态。</summary>
    public bool IsDone { get; private set; }
    public string DoneReason { get; private set; }

    private void Finish(string reason)
    {
        IsDone = true;
        DoneReason = reason;
        Log(name + "：采样结束（" + reason + "）");
    }

    private void Start()
    {
        try { Directory.CreateDirectory(OutDir); } catch { }
        StartCoroutine(Run());
    }

    /// <summary>
    /// 统一切入点：需要外部唤醒时先在这里等。
    /// （MonoBehaviour 的协程里 `yield return <IEnumerator>` 会自动展开，
    ///   和编辑器版的 EditorApplication.update 手推不一样。）
    /// </summary>
    private IEnumerator Run()
    {
        if (waitForExternalStart)
        {
            Log(name + "：已挂起，等待 SceneActivationController 逐个唤醒");
            float t0 = Time.time;
            while (!_beginRequested)
            {
                if (Time.time - t0 > 600f) { Finish("等待外部唤醒超时 600s"); yield break; }
                yield return null;
            }
            Log(name + "：收到唤醒，开始采样");
        }
        if (mode == ProbeMode.AllStates) yield return SampleAllStates();
        else yield return Follow();
    }

    // ------------------------------------------------------------ AllStates
    private IEnumerator SampleAllStates()
    {
        Animator animator = FindAnimator();
        if (animator == null)
        {
            Finish("子树里没有 Animator，跳过");
            yield break;
        }
        if (stateHashes == null || stateHashes.Length == 0)
        {
            Finish("状态表为空——请在编辑器里点“刷新状态列表”后再跑");
            yield break;
        }
        Animator[] allAnims = GetComponentsInChildren<Animator>(true);
        if (allAnims.Length > 1)
            Log(string.Format("{0}：子树里有 {1} 个 Animator，本 probe 负责 {2}（animatorPath={3}）；其余请另挂 probe 用 animatorPath 指定",
                              name, allAnims.Length, animator.name,
                              string.IsNullOrEmpty(animatorPath) ? "(空=第一个)" : animatorPath));
        if (!OwnsAnimator(animator))
        {
            Finish("同一个 Animator 已由更浅层的 probe 负责，跳过（避免互抢状态）");
            yield break;
        }
        string charName = TopName();
        Log(string.Format("{0}：开始 AllStates，状态 {1} 个，步长 {2}s，BakeMesh={3}",
                          charName, stateHashes.Length, step, bakeMeshes));
        for (int si = 0; si < stateHashes.Length; si++)
        {
            float dur = (stateLengths != null && si < stateLengths.Length) ? stateLengths[si] : 0f;
            if (dur <= 0f) { Log("   跳过 " + stateNames[si] + "：时长 0"); continue; }
            string file = Sanitize(charName) + "@" + Sanitize(animator.name) + "@"
                          + Sanitize(stateNames[si]) + ".json";
            string path = Path.Combine(OutDir, file);
            yield return SampleOneState(animator, si, dur, path);
        }
        Finish("完成 AllStates，输出目录 " + OutDir);
    }

    private IEnumerator SampleOneState(Animator animator, int si, float dur, string outPath)
    {
        int hash = stateHashes[si];
        int layer = (stateLayers != null && si < stateLayers.Length) ? stateLayers[si] : 0;
        int frames = Mathf.Min(4000, Mathf.CeilToInt(dur / step) + 1);
        // 复位：否则上一个状态打开过的部件会留着（见 docs 静态prefab路线 8.1 的坑）
        animator.Rebind();
        var sb = new StringBuilder();
        var sbPose = bakeMeshes ? new StringBuilder() : null;
        sb.Append("{\n  \"prefab\": ").Append(Str(TopName())).Append(",\n");
        sb.Append("  \"animator\": ").Append(Str(animator.name)).Append(",\n");
        sb.Append("  \"state\": ").Append(Str(stateNames[si])).Append(",\n");
        sb.Append("  \"clip\": ").Append(Str(si < clipNames.Length ? clipNames[si] : "")).Append(",\n");
        sb.Append("  \"duration\": ").Append(F(dur)).Append(",\n");
        sb.Append("  \"step\": ").Append(F(step)).Append(",\n");
        sb.Append("  \"advance\": ").Append(Str(advance == SampleAdvance.Seek ? "seek" : "natural-step")).Append(",\n");
        sb.Append("  \"mode\": \"playmode-runtime\",\n  \"frames\": [\n");
        if (sbPose != null)
        {
            sbPose.Append("{\n  \"prefab\": ").Append(Str(TopName())).Append(",\n");
            sbPose.Append("  \"animator\": ").Append(Str(animator.name)).Append(",\n");
            sbPose.Append("  \"state\": ").Append(Str(stateNames[si])).Append(",\n");
            sbPose.Append("  \"clip\": ").Append(Str(si < clipNames.Length ? clipNames[si] : "")).Append(",\n");
            sbPose.Append("  \"duration\": ").Append(F(dur))
                  .Append(",\n  \"advance\": ").Append(Str(advance == SampleAdvance.Seek ? "seek" : "natural-step"))
                  .Append(",\n  \"mode\": \"playmode-runtime\",\n  \"frames\": [\n");
        }
        if (advance == SampleAdvance.Seek)
        {
            // 旧行为：逐点跳帧。快，但 m_IsActive 会被粘住（见 docs 8.1.8）。
            NoteOnce("advance:Seek",
                "注意：advance=Seek（旧跳帧采样）。实测这条路径会把 m_IsActive 粘在 ON，"
                + "显隐真值不可信；要正确还原请把 advance 改成 NaturalStep。");
            for (int i = 0; i < frames; i++)
            {
                float t = Mathf.Min(dur, i * step);
                animator.Play(hash, layer, dur <= 0f ? 0f : t / dur);
                animator.Update(0f);
                sb.Append(i == 0 ? "    " : "    ,").Append(LiteFrame(t, animator)).Append("\n");
                if (sbPose != null)
                    sbPose.Append(i == 0 ? "    " : "    ,").Append(PoseFrame(t, animator)).Append("\n");
                if (i % 25 == 24) yield return null;
            }
        }
        else
        {
            // 自然步进：Play 一次，然后连续 Update(step) 推进整条时间轴。
            // 关键点是**不要在推进过程中让出帧**：让出的那一帧 Unity 自己也会 Update
            // 这个 Animator，状态机的连续时间就被打断了，离散显隐又会错。
            animator.Play(hash, layer, 0f);
            animator.Update(0f);
            if (bakeMeshes && yieldEvery == 0 && frames > 200)
                NoteOnce("advance:slow",
                    "注意：NaturalStep + BakeMesh + 不让出帧，本状态 " + frames
                    + " 个采样点会一次性跑完，编辑器会卡住一段时间"
                    + "（这是为了不让 Unity 自行 Update 打断时间轴；确实太慢可临时把 yieldEvery 设成 25）。");
            for (int i = 0; i < frames; i++)
            {
                float t = Mathf.Min(dur, i * step);
                if (i > 0) animator.Update(step);
                sb.Append(i == 0 ? "    " : "    ,").Append(LiteFrame(t, animator)).Append("\n");
                if (sbPose != null)
                    sbPose.Append(i == 0 ? "    " : "    ,").Append(PoseFrame(t, animator)).Append("\n");
                if (yieldEvery > 0 && i % yieldEvery == yieldEvery - 1)
                {
                    if (i == yieldEvery - 1)
                        NoteOnce("advance:yield",
                            "注意：NaturalStep 下设了 yieldEvery=" + yieldEvery
                            + "，让出的帧里 Unity 会自行 Update 该 Animator，"
                            + "时间轴可能错位。要最准确请设 yieldEvery=0。");
                    yield return null;
                }
            }
        }
        sb.Append("\n  ]\n}\n");
        try { File.WriteAllText(outPath, sb.ToString(), new UTF8Encoding(false)); }
        catch (Exception ex) { Log("写文件失败 " + outPath + "：" + ex.Message); yield break; }
        Log("    " + Path.GetFileName(outPath));
        if (sbPose != null)
        {
            sbPose.Append("\n  ]\n}\n");
            string posePath = Path.ChangeExtension(outPath, ".playpose.json");
            try
            {
                File.WriteAllText(posePath, sbPose.ToString(), new UTF8Encoding(false));
                Log("        + " + Path.GetFileName(posePath) + "（全量 BakeMesh）");
            }
            catch (Exception ex) { Log("写文件失败 " + posePath + "：" + ex.Message); }
        }
        yield return null;
    }

    // ------------------------------------------------------------ FollowRuntime
    private IEnumerator Follow()
    {
        Animator animator = FindAnimator();
        if (animator == null) { Finish("子树里没有 Animator，跳过"); yield break; }
        if (!OwnsAnimator(animator))
        {
            Finish("同一个 Animator 已由更浅层的 probe 负责，跳过（避免互抢状态）");
            yield break;
        }
        string charName = TopName();
        string path = Path.Combine(OutDir, Sanitize(charName) + "@follow.json");
        Log(string.Format("{0}：开始 FollowRuntime，记录 {1}s（不干扰播放）", charName, followSeconds));
        var sb = new StringBuilder();
        sb.Append("{\n  \"prefab\": ").Append(Str(charName))
          .Append(",\n  \"mode\": \"follow-runtime\",\n  \"frames\": [\n");
        float t0 = Time.time;
        int n = 0;
        while (Time.time - t0 < followSeconds)
        {
            var st = animator.GetCurrentAnimatorStateInfo(0);
            sb.Append(n == 0 ? "    " : "    ,")
              .Append(FollowFrame(Time.time - t0, st.shortNameHash, st.normalizedTime, true))
              .Append("\n");
            n++;
            yield return null;
        }
        sb.Append("\n  ]\n}\n");
        try { File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false)); Log("    " + Path.GetFileName(path)); }
        catch (Exception ex) { Log("写文件失败 " + path + "：" + ex.Message); }
        Finish("完成 FollowRuntime：" + n + " 帧");
    }

    // ------------------------------------------------------------ 帧数据
    private string LiteFrame(float t, Animator animator)
    {
        var b = new StringBuilder();
        b.Append("{\"t\": ").Append(F(t)).Append(",\n  \"transforms\": [");
        var ts = AllTransforms();
        for (int i = 0; i < ts.Count; i++)
        {
            if (i > 0) b.Append(", ");
            Transform x = ts[i];
            b.Append("{\"path\": ").Append(Str(PathOf(x)))
             .Append(", \"localPos\": ").Append(V3(x.localPosition))
             .Append(", \"localEuler\": ").Append(V3(x.localEulerAngles))
             .Append(", \"localScale\": ").Append(V3(x.localScale)).Append("}");
        }
        b.Append("],\n  \"renderers\": [");
        b.Append(RendererFlags());
        b.Append("]}");
        return b.ToString();
    }

    private string FollowFrame(float t, int stateHash, float stateNorm, bool live)
    {
        var b = new StringBuilder();
        b.Append("{\"t\": ").Append(F(t))
         .Append(", \"stateHash\": ").Append(stateHash)
         .Append(", \"stateNorm\": ").Append(F(stateNorm))
         .Append(",\n  \"renderers\": [").Append(RendererFlags()).Append("]}");
        return b.ToString();
    }

    /// <summary>PoseFrames 兼容（供 tools/calib_geo.py --pose 直接用）。</summary>
    private string PoseFrame(float t, Animator animator)
    {
        var b = new StringBuilder();
        b.Append("{\"time\": ").Append(F(t)).Append(",\n  \"transforms\": [");
        var ts = AllTransforms();
        for (int i = 0; i < ts.Count; i++)
        {
            if (i > 0) b.Append(", ");
            Transform x = ts[i];
            b.Append("{\"path\": ").Append(Str(PathOf(x)))
             .Append(", \"localPos\": ").Append(V3(x.localPosition))
             .Append(", \"localEuler\": ").Append(V3(x.localEulerAngles))
             .Append(", \"localScale\": ").Append(V3(x.localScale)).Append("}");
        }
        b.Append("],\n  \"skinned\": [");
        bool first = true;
        foreach (SkinnedMeshRenderer r in GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (!first) b.Append(", ");
            first = false;
            var m = new Mesh();
            bool ok = true;
            try { r.BakeMesh(m, true); }
            catch (Exception ex) { ok = false; WarnOnce("skinned:" + (r.sharedMesh == null ? r.name : r.sharedMesh.name), ex); }
            b.Append("{\"path\": ").Append(Str(PathOf(r.transform)))
             .Append(", \"kind\": \"skinned\", \"readable\": ").Append(Bool(ok))
             .Append(", \"vertexCount\": ").Append(ok ? m.vertexCount : 0);
            if (ok)
                b.Append(", \"positions\": ").Append(V3List(m.vertices))
                 .Append(", \"uvs\": ").Append(UVList(m.uv))
                 .Append(", \"triangles\": ").Append(IntList(m.triangles));
            b
             .Append(", \"localToWorld\": ").Append(Mat4(r.transform.localToWorldMatrix))
             .Append(", \"sortingOrder\": ").Append(r.sortingOrder)
              .Append(", \"activeInHierarchy\": ").Append(Bool(r.gameObject.activeInHierarchy))
             .Append(", \"activeSelf\": ").Append(Bool(r.gameObject.activeSelf))
             .Append(", \"enabled\": ").Append(Bool(r.enabled)).Append("}");
            UnityEngine.Object.Destroy(m);
        }
        foreach (MeshRenderer r in GetComponentsInChildren<MeshRenderer>(true))
        {
            var mf = r.GetComponent<MeshFilter>();
            if (mf == null || mf.sharedMesh == null) continue;
            if (!first) b.Append(", ");
            first = false;
            Mesh m = mf.sharedMesh;
            // Mesh 的 Read/Write 关闭时读 .vertices/.uv/.triangles 会抛
            // "Not allowed to access vertices ... isReadable is false"（CS_parts_gun 就是这种）。
            // 这里降级成只记存在性 + 变换 + 显隐，位置信息留空，并在日志里点名。
            bool readable = m.isReadable;
            if (!readable) WarnOnce("static:" + m.name, null);
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
             .Append(", \"enabled\": ").Append(Bool(r.enabled)).Append("}");
        }
        b.Append("],\n  \"sprites\": [");
        first = true;
        foreach (SpriteRenderer r in GetComponentsInChildren<SpriteRenderer>(true))
        {
            if (!first) b.Append(", ");
            first = false;
            b.Append("{\"path\": ").Append(Str(PathOf(r.transform)))
             .Append(", \"kind\": \"sprite\", \"worldCorners\": ").Append(Corners(r))
             .Append(", \"sortingOrder\": ").Append(r.sortingOrder)
             .Append(", \"activeInHierarchy\": ").Append(Bool(r.gameObject.activeInHierarchy))
             .Append(", \"activeSelf\": ").Append(Bool(r.gameObject.activeSelf))
             .Append(", \"enabled\": ").Append(Bool(r.enabled)).Append("}");
        }
        b.Append("]}");
        return b.ToString();
    }

    private string RendererFlags()
    {
        bool first = true;
        var b = new StringBuilder();
        foreach (SkinnedMeshRenderer r in GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (!first) b.Append(", ");
            first = false;
            b.Append("{\"path\": ").Append(Str(PathOf(r.transform))).Append(", \"kind\": \"skinned\"")
             .Append(", \"enabled\": ").Append(Bool(r.enabled))
             .Append(", \"activeSelf\": ").Append(Bool(r.gameObject.activeSelf))
             .Append(", \"activeInHierarchy\": ").Append(Bool(r.gameObject.activeInHierarchy))
             .Append(", \"bones\": ").Append(r.bones == null ? 0 : r.bones.Length)
             .Append(", \"localToWorld\": ").Append(Mat4(r.transform.localToWorldMatrix)).Append("}");
        }
        foreach (MeshRenderer r in GetComponentsInChildren<MeshRenderer>(true))
        {
            if (!first) b.Append(", ");
            first = false;
            b.Append("{\"path\": ").Append(Str(PathOf(r.transform))).Append(", \"kind\": \"static\"")
             .Append(", \"enabled\": ").Append(Bool(r.enabled))
             .Append(", \"activeSelf\": ").Append(Bool(r.gameObject.activeSelf))
             .Append(", \"activeInHierarchy\": ").Append(Bool(r.gameObject.activeInHierarchy))
             .Append(", \"localToWorld\": ").Append(Mat4(r.transform.localToWorldMatrix)).Append("}");
        }
        foreach (SpriteRenderer r in GetComponentsInChildren<SpriteRenderer>(true))
        {
            if (!first) b.Append(", ");
            first = false;
            b.Append("{\"path\": ").Append(Str(PathOf(r.transform))).Append(", \"kind\": \"sprite\"")
             .Append(", \"enabled\": ").Append(Bool(r.enabled))
             .Append(", \"activeSelf\": ").Append(Bool(r.gameObject.activeSelf))
             .Append(", \"activeInHierarchy\": ").Append(Bool(r.gameObject.activeInHierarchy))
             .Append(", \"sprite\": ").Append(Str(r.sprite == null ? "" : r.sprite.name))
             .Append(", \"worldCorners\": ").Append(Corners(r)).Append("}");
        }
        return b.ToString();
    }

    private List<Transform> AllTransforms()
    {
        // GetComponentsInChildren(includeInactive:true) 已经包含自己，别再手动加一次
        return new List<Transform>(GetComponentsInChildren<Transform>(true));
    }

    /// <summary>
    /// 解析本 probe 负责的 Animator：
    ///   1. 指定了 animatorPath 就按相对路径精确找（一个角色多 Animator 时用）；
    ///   2. 否则取子树里第一个。
    /// </summary>
    public Animator ResolveAnimator()
    {
        if (!string.IsNullOrEmpty(animatorPath))
        {
            foreach (Animator a in GetComponentsInChildren<Animator>(true))
                if (RelPath(transform, a.transform) == animatorPath) return a;
        }
        return GetComponentInChildren<Animator>(true);
    }

    /// <summary>自己或最近的、带 Animator 的祖先（组件挂错层级也能用）。</summary>
    private Animator FindAnimator()
    {
        var an = ResolveAnimator();
        if (an != null) return an;
        Transform t = transform.parent;
        while (t != null)
        {
            an = t.GetComponentInChildren<Animator>(true);
            if (an != null) return an;
            t = t.parent;
        }
        return null;
    }

    /// <summary>
    /// 同一个 Animator 只让**层级最浅**的那个 probe 驱动。
    /// 否则几十个 probe 会一起 Play/Rebind 同一个 Animator，互相抢状态、重复写同一批文件。
    /// </summary>
    private bool OwnsAnimator(Animator an)
    {
        if (an == null) return false;
        int myDepth = Depth(transform);
        PlayModeProbe[] all = FindObjectsOfType<PlayModeProbe>(true);
        for (int i = 0; i < all.Length; i++)
        {
            PlayModeProbe p = all[i];
            if (p == null || p == this) continue;
            if (p.FindAnimator() != an) continue;     // 管的是别的 Animator，互不影响
            int d = Depth(p.transform);
            if (d < myDepth) return false;            // 有更浅的负责
            if (d == myDepth && p.GetInstanceID() < GetInstanceID()) return false;  // 平手按 ID 决出
        }
        return true;
    }

    private static int Depth(Transform t)
    {
        int d = 0;
        while (t.parent != null) { t = t.parent; d++; }
        return d;
    }

    /// <summary>角色根名字：向上找到最顶层祖先。</summary>
    private string TopName()
    {
        Transform t = transform;
        while (t.parent != null) t = t.parent;
        return t.name;
    }

    // ------------------------------------------------------------ 小工具
    private static string V3(Vector3 v)
    {
        return "[" + F(v.x) + ", " + F(v.y) + ", " + F(v.z) + "]";
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

    private static string Corners(SpriteRenderer r)
    {
        Bounds b = r.bounds;
        Vector3 c = b.center, e = b.extents;
        return "[" + V3(new Vector3(c.x - e.x, c.y - e.y, c.z)) + ", "
                   + V3(new Vector3(c.x + e.x, c.y - e.y, c.z)) + ", "
                   + V3(new Vector3(c.x + e.x, c.y + e.y, c.z)) + ", "
                   + V3(new Vector3(c.x - e.x, c.y + e.y, c.z)) + "]";
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

    /// <summary>target 相对 from 的层级路径；target 不在 from 之下时回退成完整路径。</summary>
    public static string RelPath(Transform from, Transform target)
    {
        if (from == target) return ".";      // 自己：用一个非空标记，避免和"没填 animatorPath"混淆
        var parts = new List<string>();
        Transform cur = target;
        while (cur != null && cur != from) { parts.Insert(0, cur.name); cur = cur.parent; }
        if (cur != from) return PathOf(target);
        return string.Join("/", parts.ToArray());
    }

    private static string Sanitize(string name)
    {
        if (string.IsNullOrEmpty(name)) return "_";
        foreach (char c in Path.GetInvalidFileNameChars()) name = name.Replace(c, '_');
        return name.Replace('/', '_').Replace('\\', '_').Replace(' ', '_');
    }
}
