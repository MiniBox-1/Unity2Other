// 把“尾巴条的 spline/IK 解算”逐帧烘进 AnimationClip（.anim）。
//
// 背景：这类 2DModel 的尾巴是「可见 spline 控制链（spline_Ctrl_1..7，被动画驱动）+
// 静止的变形骨链（Controllers/CTRL_Spline/bone_N/Bone_Tail_XX，网格权重用的就是它）」
// 两套骨骼。原工程里应由一个运行时脚本把控制点解算到变形骨上，ripoff 出来的 prefab
// 里该脚本已丢失 ⇒ 播放动画时尾巴尖（Bone_Tail_End 的子物体）跟着 spline 飞走、
// 尾巴条不动，末端被拉成细丝。
//
// 本脚本不依赖那个脚本，直接把解算结果烘进 clip：
//   · 每根变形骨 Bone_Tail_02..32 按静止时沿尾巴弧长取参数 u∈[0,6]；
//   · 每帧用 7 个锚点的**刚体运动** R_j = W_j(t)·W_j(rest)⁻¹ 做混合
//     （锚点 = spline_Ctrl_1..6 + Bone_Tail_End：末端锚点用尖的骨头，条末端与尖
//       永远共享同一个刚体运动，接缝不会裂）；
//   · 可选 IK（FABRIK）：两端钉住（基座跟随 guide、末端=尖的绑定姿态），中间顺 guide
//     但**骨长严格不变**，过渡更顺、不拉丝；
//   · 写曲线时切线用中心差分（否则默认 0 切线 ⇒ 每帧减速到 0，肉眼看“一抽一抽”）；
//   · 局部四元数强制符号连续，避免 4 条分量曲线跳变。
// 静止姿态（所有 R_j = 单位阵）解算结果=原样 ⇒ 不动画时外观不变；
// 尾巴尖、尖下面的阴影都不受影响。
//
// 用法（菜单）：Tools/2DModel/尾巴/把 spline 解算烘进各 clip
// 用法（批处理，一行一个任务）：
//   TAIL_BAKE_JOBS=<txt>，每行  <prefabPath>|<clip1>;<clip2>|ik=0/1
//   （clip 列表留空 = 用该 prefab 的 AnimatorController 里的所有 clip）
//   Unity.exe -batchmode -projectPath <proj> -quit -executeMethod BakeTailSpline.BakeJobsFromFile

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

public static class BakeTailSpline
{
    const int LeafFrom = 2;
    const int LeafTo = 32;
    const float Step = 0.05f;          // 烘焙步长（秒）；与转换器默认 --dt 一致
    const int IkIterations = 12;       // IK（FABRIK）迭代次数
    const float IkGuidePull = 0.2f;    // 每轮向 guide 拉回的比例

    // 默认任务：test 下两个角色（含它们各自目录里的 clip 副本）
    static readonly string[] DefaultPrefabs =
    {
        "Assets/prefabs/test/alice_skin1_dl_origin/assetbundleresource/character_2d/2DModel_3P_Alice_NS1_DL_N.prefab",
        "Assets/prefabs/test/alice_skin1_origin/2DModel_3P_Alice_NS1.prefab",
    };

    static string[] CtrlNames()
    {
        var a = new string[7];
        for (int i = 0; i < 7; i++) a[i] = "spline_Ctrl_" + (i + 1);
        return a;
    }

    // ---------------------------------------------------------------- 工具

    /// <summary>把一串关键帧做成平滑曲线：切线用中心差分，写成 Unity 自己的
    /// tangentMode=1（默认 0 切线会让每帧速度掉到 0，看起来一抽一抽）。</summary>
    static AnimationCurve SmoothCurve(List<Keyframe> keys)
    {
        var c = new AnimationCurve(keys.ToArray());
        int n = c.length;
        for (int i = 0; i < n; i++)
        {
            var k = c[i];
            float slope;
            if (n == 1)
                slope = 0f;
            else if (i == 0)
                slope = (c[1].value - c[0].value) / Mathf.Max(1e-6f, c[1].time - c[0].time);
            else if (i == n - 1)
                slope = (c[n - 1].value - c[n - 2].value) / Mathf.Max(1e-6f, c[n - 1].time - c[n - 2].time);
            else
                slope = (c[i + 1].value - c[i - 1].value) / Mathf.Max(1e-6f, c[i + 1].time - c[i - 1].time);
            k.inTangent = slope;
            k.outTangent = slope;
            k.tangentMode = 1;
            k.weightedMode = 0;
            k.inWeight = 0.33333334f;
            k.outWeight = 0.33333334f;
            c.MoveKey(i, k);
        }
        return c;
    }

    static Transform FindDeep(Transform root, string name)
    {
        if (root.name == name) return root;
        for (int i = 0; i < root.childCount; i++)
        {
            var r = FindDeep(root.GetChild(i), name);
            if (r != null) return r;
        }
        return null;
    }

    static string RelPath(Transform root, Transform t)
    {
        var parts = new List<string>();
        var cur = t;
        while (cur != null && cur != root)
        {
            parts.Add(cur.name);
            cur = cur.parent;
        }
        parts.Reverse();
        return string.Join("/", parts);
    }

    static bool EnvFlag(string name, bool dflt)
    {
        var v = Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrEmpty(v)) return dflt;
        return v != "0" && v.ToLower() != "false";
    }

    static void WriteReport(StringBuilder report)
    {
        AssetDatabase.SaveAssets();
        string outPath = Environment.GetEnvironmentVariable("TAIL_BAKE_REPORT");
        if (string.IsNullOrEmpty(outPath))
            outPath = Path.Combine(Path.GetTempPath(), "tail_bake_report.txt");
        File.WriteAllText(outPath, report.ToString(), Encoding.UTF8);
        Debug.Log("[BakeTailSpline] 报告 -> " + outPath);
        Debug.Log(report.ToString());
    }

    // ---------------------------------------------------------------- 入口

    [MenuItem("Tools/2DModel/尾巴/把 spline 解算烘进各 clip")]
    public static void BakeMenu()
    {
        var rep = new StringBuilder();
        // 默认：不做 IK，且只烘 parts_Tail_F 用到的骨（B 保持静止，避免缝顶点被拉开）
        foreach (var p in DefaultPrefabs) BakeJob(p, null, false, true, rep);
        WriteReport(rep);
    }

    /// <summary>TAIL_BAKE_PREFABS = prefab 路径，';' 分隔（烘各自的 controller clip）。</summary>
    public static void BakeFromEnv()
    {
        var env = Environment.GetEnvironmentVariable("TAIL_BAKE_PREFABS");
        var list = string.IsNullOrEmpty(env)
            ? new string[0]
            : env.Split(';').Where(s => !string.IsNullOrWhiteSpace(s)).ToArray();
        var rep = new StringBuilder();
        bool ik = EnvFlag("TAIL_BAKE_IK", true);
        foreach (var p in list) BakeJob(p, null, ik, EnvFlag("TAIL_BAKE_FONLY", true), rep);
        WriteReport(rep);
    }

    /// <summary>TAIL_BAKE_RIG_PREFAB + TAIL_BAKE_CLIPS（只烘指定 clip）。</summary>
    public static void BakeClipsFromEnv()
    {
        string rig = Environment.GetEnvironmentVariable("TAIL_BAKE_RIG_PREFAB");
        string env = Environment.GetEnvironmentVariable("TAIL_BAKE_CLIPS");
        var clips = string.IsNullOrEmpty(env)
            ? new string[0]
            : env.Split(';').Where(s => !string.IsNullOrWhiteSpace(s)).ToArray();
        var rep = new StringBuilder();
        BakeJob(rig, clips, EnvFlag("TAIL_BAKE_IK", true),
                EnvFlag("TAIL_BAKE_FONLY", true), rep);
        WriteReport(rep);
    }

    /// <summary>TAIL_BAKE_JOBS = 任务文件，每行 &lt;prefab&gt;|&lt;clip1;clip2&gt;|ik=0/1。</summary>
    public static void BakeJobsFromFile()
    {
        var rep = new StringBuilder();
        string jobsPath = Environment.GetEnvironmentVariable("TAIL_BAKE_JOBS");
        if (string.IsNullOrEmpty(jobsPath) || !File.Exists(jobsPath))
        {
            Debug.LogError("[BakeTailSpline] 需要 TAIL_BAKE_JOBS 指向任务文件");
            WriteReport(rep);
            return;
        }
        foreach (var raw in File.ReadAllLines(jobsPath))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line.StartsWith("#")) continue;
            var parts = line.Split('|');
            string prefab = parts[0].Trim();
            string[] clips = (parts.Length > 1 && parts[1].Trim().Length > 0)
                ? parts[1].Split(';').Where(s => !string.IsNullOrWhiteSpace(s))
                       .Select(s => s.Trim()).ToArray()
                : null;
            bool ik = true;
            bool fOnly = false;
            for (int k = 2; k < parts.Length; k++)
            {
                var opt = parts[k].Trim();
                if (opt.StartsWith("ik=")) ik = opt.Substring(3).Trim() != "0";
                if (opt.StartsWith("fonly=")) fOnly = opt.Substring(6).Trim() != "0";
            }
            BakeJob(prefab, clips, ik, fOnly, rep);
        }
        WriteReport(rep);
    }

    // ---------------------------------------------------------------- 主流程

    static void BakeJob(string prefabPath, string[] clipPaths, bool useIk,
                        bool fOnly, StringBuilder report)
    {
        if (string.IsNullOrEmpty(prefabPath))
        {
            Debug.LogError("[BakeTailSpline] 空 prefab 路径");
            return;
        }
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null)
        {
            Debug.LogError("[BakeTailSpline] 找不到 prefab：" + prefabPath);
            return;
        }
        var inst = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        inst.transform.position = Vector3.zero;
        inst.transform.rotation = Quaternion.identity;
        inst.transform.localScale = Vector3.one;
        try
        {
            var animator = inst.GetComponentInChildren<Animator>(true);
            if (animator == null)
            {
                Debug.LogError("[BakeTailSpline] " + prefabPath + " 没有 Animator");
                return;
            }
            var root = animator.gameObject;
            var ctrl = CtrlNames().Select(n => FindDeep(inst.transform, n)).ToArray();
            var leaves = new List<Transform>();
            for (int i = LeafFrom; i <= LeafTo; i++)
                leaves.Add(FindDeep(inst.transform, string.Format("Bone_Tail_{0:00}", i)));
            var endBone = FindDeep(inst.transform, "Bone_Tail_End");
            if (ctrl.Any(t => t == null) || leaves.Any(t => t == null) || endBone == null)
            {
                Debug.LogError("[BakeTailSpline] " + prefabPath
                               + " 缺 spline_Ctrl/Bone_Tail_XX/Bone_Tail_End");
                return;
            }

            var leafRest = leaves.Select(t => t.localToWorldMatrix).ToArray();
            var ctrlRestInv = ctrl.Select(t => t.localToWorldMatrix.inverse).ToArray();
            var endRestInv = endBone.localToWorldMatrix.inverse;

            // 解算参考姿态：用**网格的 bind 姿态**（锚在 Bone_Tail_End 上），
            //   参考[i] = W_End(rest) · bind_End · bind_i⁻¹
            // 因为 prefab 里的静止姿态和网格 bind 姿态并不一致（缝处顶点会被拉开成细线），
            // 用 bind 做参考，整条尾巴就等于美术绑定的形状：没有细线、不拉伸。
            var leafRef = (Matrix4x4[])leafRest.Clone();
            {
                // 两个网格各有自己的 bind 空间，必须分开取、并用**都在两边的骨**做锚
                var bindF = new Dictionary<string, Matrix4x4>();
                var bindB = new Dictionary<string, Matrix4x4>();
                foreach (var pair in new[]
                {
                    new KeyValuePair<string, Dictionary<string, Matrix4x4>>(
                        "parts_Tail_F", bindF),
                    new KeyValuePair<string, Dictionary<string, Matrix4x4>>(
                        "parts_Tail_B", bindB),
                })
                {
                    var go = FindDeep(inst.transform, pair.Key);
                    var smr = go != null ? go.GetComponent<SkinnedMeshRenderer>() : null;
                    if (smr == null || smr.sharedMesh == null || smr.bones == null) continue;
                    var bps = smr.sharedMesh.bindposes;
                    int cnt = Mathf.Min(smr.bones.Length, bps != null ? bps.Length : 0);
                    for (int i = 0; i < cnt; i++)
                        if (smr.bones[i] != null)
                            pair.Value[smr.bones[i].name] = bps[i];
                }
                Matrix4x4 bindEnd;
                string anchorName = "Bone_Tail_21";     // F/B 都有的骨，用作 B 的锚
                if (bindF.TryGetValue(endBone.name, out bindEnd))
                {
                    var wEndRest = endBone.localToWorldMatrix;
                    var bindEndInv = bindEnd.inverse;
                    int used = 0;
                    for (int i = 0; i < leaves.Count; i++)
                    {
                        Matrix4x4 b;
                        if (bindF.TryGetValue(leaves[i].name, out b))
                        {
                            // 参考[i] 的世界矩阵 = W_End · (bind_i · bind_End⁻¹)⁻¹
                            leafRef[i] = wEndRest * (b * bindEndInv).inverse;
                            used++;
                        }
                    }
                    // B 的骨用 B 自己的 bind，锚在共享骨上（只有相对关系，不跨空间）
                    Matrix4x4 anchorBindB;
                    if (bindB.TryGetValue(anchorName, out anchorBindB))
                    {
                        int idx = leaves.FindIndex(t => t.name == anchorName);
                        if (idx >= 0)
                        {
                            var wAnchor = leafRef[idx];
                            var anchorInv = anchorBindB.inverse;
                            for (int i = 0; i < leaves.Count; i++)
                            {
                                Matrix4x4 b;
                                if (bindF.ContainsKey(leaves[i].name)) continue;
                                if (bindB.TryGetValue(leaves[i].name, out b))
                                {
                                    leafRef[i] = wAnchor * (b * anchorInv).inverse;
                                    used++;
                                }
                            }
                        }
                    }
                    report.AppendLine("   bind 参考生效 " + used + " / " + leaves.Count
                                      + " 根骨（F 锚 Bone_Tail_End，B 锚 " + anchorName + "）");
                }
                else
                {
                    report.AppendLine("   [warn] 没读到 bind 数据，仍用 prefab 静止姿态");
                }
            }

            // 只烘 parts_Tail_F 用到的那些骨（B 的部分保持静止，避免它的缝顶点被拉开成细线）
            var target = new bool[leaves.Count];
            if (fOnly)
            {
                var fGo = FindDeep(inst.transform, "parts_Tail_F");
                var smr = fGo != null ? fGo.GetComponent<SkinnedMeshRenderer>() : null;
                if (smr == null)
                {
                    Debug.LogWarning("[BakeTailSpline] 没找到 parts_Tail_F，退化为全部烘");
                    for (int i = 0; i < target.Length; i++) target[i] = true;
                }
                else
                {
                    var names = new HashSet<string>(
                        smr.bones.Where(b => b != null).Select(b => b.name));
                    for (int i = 0; i < leaves.Count; i++)
                        target[i] = names.Contains(leaves[i].name);
                    report.AppendLine("   parts_Tail_F 用到 "
                        + target.Count(x => x) + " / " + leaves.Count + " 根骨");
                }
            }
            else
            {
                for (int i = 0; i < target.Length; i++) target[i] = true;
            }

            // 沿尾巴弧长的参数 u∈[0,6]
            var u = new float[leaves.Count];
            float total = 0f;
            var cum = new float[leaves.Count];
            for (int i = 1; i < leaves.Count; i++)
            {
                // 用参考姿态（bind）算弧长，和控制链的对应关系更准
                total += Vector3.Distance(leafRef[i - 1].GetColumn(3),
                                          leafRef[i].GetColumn(3));
                cum[i] = total;
            }
            for (int i = 0; i < leaves.Count; i++)
                u[i] = total > 1e-9f ? 6f * cum[i] / total : 0f;

            List<AnimationClip> clips = new List<AnimationClip>();
            if (clipPaths == null)
            {
                if (animator.runtimeAnimatorController == null)
                {
                    Debug.LogError("[BakeTailSpline] " + prefabPath + " 没有 controller");
                    return;
                }
                clips = animator.runtimeAnimatorController.animationClips
                    .Where(c => c != null).Distinct().ToList();
            }
            else
            {
                foreach (var cp in clipPaths)
                {
                    var c = AssetDatabase.LoadAssetAtPath<AnimationClip>(cp);
                    if (c == null) Debug.LogError("[BakeTailSpline] 找不到 clip：" + cp);
                    else if (!clips.Contains(c)) clips.Add(c);
                }
            }
            report.AppendLine(string.Format("== {0}  ({1} 个 clip, IK={2})",
                                            prefabPath, clips.Count, useIk));
            foreach (var clip in clips)
                BakeClip(root, clip, ctrl, ctrlRestInv, endBone, endRestInv,
                         leaves, leafRef, u, report, useIk, target);
            report.AppendLine();
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(inst);
        }
    }

    static void BakeClip(GameObject root, AnimationClip clip, Transform[] ctrl,
                         Matrix4x4[] ctrlRestInv, Transform endBone,
                         Matrix4x4 endRestInv, List<Transform> leaves,
                         Matrix4x4[] leafRest, float[] u, StringBuilder report,
                         bool useIk, bool[] target)
    {
        int n = leaves.Count;
        var paths = leaves.Select(t => RelPath(root.transform, t)).ToArray();
        var posKeys = new List<Keyframe>[n * 3];
        var rotKeys = new List<Keyframe>[n * 4];
        for (int i = 0; i < n * 3; i++) posKeys[i] = new List<Keyframe>();
        for (int i = 0; i < n * 4; i++) rotKeys[i] = new List<Keyframe>();

        var restPos = leafRest.Select(m => m.GetColumn(3)).ToArray();
        var restLen = new float[n - 1];
        for (int i = 1; i < n; i++)
            restLen[i - 1] = Vector3.Distance(restPos[i - 1], restPos[i]);

        var prevQ = new Quaternion[n];        // guide 姿态的符号连续
        var prevLQ = new Quaternion[n];       // 局部四元数的符号连续
        var guidePos = new Vector3[n];
        var guideRot = new Quaternion[n];
        var pos = new Vector3[n];

        float devMax = 0f, devMaxT = 0f;
        float length = Mathf.Max(clip.length, 0.0001f);
        int steps = Mathf.Max(1, Mathf.CeilToInt(length / Step));

        AnimationMode.StartAnimationMode();
        try
        {
            for (int f = 0; f <= steps; f++)
            {
                float t = Mathf.Min(length, f * Step);
                AnimationMode.SampleAnimationClip(root, clip, t);
                var R = new Matrix4x4[7];
                for (int j = 0; j < 6; j++)
                    R[j] = ctrl[j].localToWorldMatrix * ctrlRestInv[j];
                R[6] = endBone.localToWorldMatrix * endRestInv;   // 末端锚点 = 尾巴尖

                for (int i = 0; i < n; i++)
                {
                    float ui = u[i];
                    int j = Mathf.Clamp((int)Mathf.Floor(ui), 0, 5);
                    float w = ui - j;
                    if (ui >= 6f) { j = 5; w = 1f; }
                    w = w * w * (3f - 2f * w);
                    var A = R[j] * leafRest[i];
                    var B = R[j + 1] * leafRest[i];
                    Quaternion qa = A.rotation, qb = B.rotation;
                    if (Quaternion.Dot(qa, qb) < 0f)
                        qb = new Quaternion(-qb.x, -qb.y, -qb.z, -qb.w);
                    Quaternion q = Quaternion.Slerp(qa, qb, w);
                    if (f > 0 && Quaternion.Dot(q, prevQ[i]) < 0f)
                        q = new Quaternion(-q.x, -q.y, -q.z, -q.w);
                    prevQ[i] = q;
                    guidePos[i] = Vector3.Lerp(A.GetColumn(3), B.GetColumn(3), w);
                    guideRot[i] = q;
                }

                // IK：两端钉住（基座=guide[0]、末端=guide[n-1] 即尾巴尖的绑定姿态），
                // 中间顺 guide，但骨长严格不变。
                if (useIk)
                {
                    for (int i = 0; i < n; i++) pos[i] = guidePos[i];
                    pos[0] = guidePos[0];
                    for (int it = 0; it < IkIterations; it++)
                    {
                        for (int i = 1; i < n; i++)          // 正向：从基座推
                        {
                            Vector3 d = pos[i] - pos[i - 1];
                            if (d.sqrMagnitude < 1e-12f) d = Vector3.right;
                            Vector3 fixedP = pos[i - 1] + d.normalized * restLen[i - 1];
                            pos[i] = Vector3.Lerp(fixedP, guidePos[i], IkGuidePull);
                            d = pos[i] - pos[i - 1];
                            if (d.sqrMagnitude < 1e-12f) d = Vector3.right;
                            pos[i] = pos[i - 1] + d.normalized * restLen[i - 1];
                        }
                        pos[n - 1] = guidePos[n - 1];        // 末端钉死
                        for (int i = n - 2; i >= 1; i--)     // 反向：从末端推
                        {
                            Vector3 d = pos[i] - pos[i + 1];
                            if (d.sqrMagnitude < 1e-12f) d = Vector3.right;
                            pos[i] = pos[i + 1] + d.normalized * restLen[i];
                        }
                        pos[0] = guidePos[0];
                    }
                }

                for (int i = 0; i < n; i++)
                {
                    Vector3 p = useIk ? pos[i] : guidePos[i];
                    Quaternion q = guideRot[i];
                    if (useIk && i < n - 1)
                    {
                        // 保持原扭向，只把“朝向”转到 IK 后的方向
                        Vector3 dGuide = guidePos[i + 1] - guidePos[i];
                        Vector3 dIk = pos[i + 1] - pos[i];
                        if (dGuide.sqrMagnitude > 1e-12f && dIk.sqrMagnitude > 1e-12f)
                            q = Quaternion.FromToRotation(dGuide.normalized, dIk.normalized) * q;
                    }
                    var targetM = Matrix4x4.TRS(p, q, leafRest[i].lossyScale);
                    var local = leaves[i].parent.localToWorldMatrix.inverse * targetM;
                    Vector3 lp = local.GetColumn(3);
                    Quaternion lq = local.rotation;
                    if (f > 0 && Quaternion.Dot(lq, prevLQ[i]) < 0f)
                        lq = new Quaternion(-lq.x, -lq.y, -lq.z, -lq.w);
                    prevLQ[i] = lq;
                    posKeys[i * 3 + 0].Add(new Keyframe(t, lp.x));
                    posKeys[i * 3 + 1].Add(new Keyframe(t, lp.y));
                    posKeys[i * 3 + 2].Add(new Keyframe(t, lp.z));
                    rotKeys[i * 4 + 0].Add(new Keyframe(t, lq.x));
                    rotKeys[i * 4 + 1].Add(new Keyframe(t, lq.y));
                    rotKeys[i * 4 + 2].Add(new Keyframe(t, lq.z));
                    rotKeys[i * 4 + 3].Add(new Keyframe(t, lq.w));
                    if (i == n - 1)     // 末端骨与“尖的绑定姿态”的偏差（≈0）
                    {
                        float d = Vector3.Distance(p, guidePos[n - 1]);
                        if (d > devMax) { devMax = d; devMaxT = t; }
                    }
                }
            }
        }
        finally
        {
            AnimationMode.StopAnimationMode();
        }

        for (int i = 0; i < n; i++)
        {
            string p = paths[i];
            if (!target[i])
            {
                // 目标之外（parts_Tail_B 的那些骨）：把之前烘进去的曲线清掉，
                // 让它们回到静止（= 原样），B 的缝顶点就不会被拉开。
                foreach (var prop in new[]
                {
                    "localPosition.x", "localPosition.y", "localPosition.z",
                    "localRotation.x", "localRotation.y", "localRotation.z",
                    "localRotation.w",
                })
                    clip.SetCurve(p, typeof(Transform), prop, null);
                continue;
            }
            clip.SetCurve(p, typeof(Transform), "localPosition.x", SmoothCurve(posKeys[i * 3 + 0]));
            clip.SetCurve(p, typeof(Transform), "localPosition.y", SmoothCurve(posKeys[i * 3 + 1]));
            clip.SetCurve(p, typeof(Transform), "localPosition.z", SmoothCurve(posKeys[i * 3 + 2]));
            clip.SetCurve(p, typeof(Transform), "localRotation.x", SmoothCurve(rotKeys[i * 4 + 0]));
            clip.SetCurve(p, typeof(Transform), "localRotation.y", SmoothCurve(rotKeys[i * 4 + 1]));
            clip.SetCurve(p, typeof(Transform), "localRotation.z", SmoothCurve(rotKeys[i * 4 + 2]));
            clip.SetCurve(p, typeof(Transform), "localRotation.w", SmoothCurve(rotKeys[i * 4 + 3]));
        }
        EditorUtility.SetDirty(clip);
        report.AppendLine(string.Format(
            "   clip {0,-24} 时长{1,5:0.00}s 烘 {2}/{7} 骨 × {3} 帧 IK={4}；末端偏离 {5:0.0000} (t={6:0.00})",
            clip.name, length, n, steps + 1, useIk, devMax, devMaxT,
            target.Count(x => x)));
    }
}
