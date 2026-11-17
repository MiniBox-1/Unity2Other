// ============================================================================
// 一个脚本 / 一个命令，把"查看一个角色"要做的事全做掉。
//
// 为什么要统一：以前要分别跑 PoseFrames 导出、Play 采样、参考图渲染、
// 运行时探针、单部件隔离渲染……口径各不相同（尤其"编辑器采样"和"运行时
// 状态机"会给出不一样的答案，见 alice_skin2 的伞）。这里一次跑完，
// 全部写进同一个目录 + 一份 manifest.json，便于离线比对。
//
// 产物：D:\VB\Unity2Spine\info\_inspect_<角色>\
//   renderers.json          静态清单：每个 renderer 的 path/kind/显隐/层序/
//                           材质贴图/网格统计/bounds
//   dynamic.json            逐状态逐帧运行时数据（真推进 Animator）
//   frames/<状态>_t<毫秒>.png + _cam.txt   正交相机渲染（1:1）
//   part_<部件名>.json/.png  可选（-probePart）：单部件隔离渲染 + 顶点/骨骼/贴图区
//   manifest.json           本次参数 + 产物清单
//
// 用法（菜单）：Tools/2DModel/查看/一键导出（全部）
// 用法（批处理）：
//   Unity.exe -batchmode -projectPath D:\VB\Search\NormalLocal\lastOrign -quit ^
//     -executeMethod ModelInspect.All ^
//     -probePrefab Assets/prefabs/lo/banshee/banshee_skin1.prefab ^
//     -probeName banshee_skin1 ^
//     -probeStates Start,breast ^        (可选，默认全部状态)
//     -probeTimes 0,0.5,1.0 ^            (可选，默认 0；状态内相对时间，秒)
//     -probePart parts_Hand_R ^          (可选：额外隔离导出某个部件)
//     -probePpu 320 ^                    (可选，渲染的像素/世界单位)
//     -logFile D:\VB\Unity2Spine\info\_logs\inspect.log
// ============================================================================
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class ModelInspect
{
    const string DefaultPrefab = "Assets/prefabs/lo/banshee/banshee_skin1.prefab";
    const string DefaultName = "banshee_skin1";
    const float Dt = 0.05f;
    const int MaxFramesPerState = 4000;

    class Args
    {
        public string prefab = DefaultPrefab;
        public string name = DefaultName;
        public List<string> states = null;                 // null = 全部状态
        public List<float> times = new List<float> { 0f }; // 默认只渲 t=0
        public string part = null;
        public string chain = null;   // 逐帧 dump 该节点 + 祖先的 local TRS 与世界位置
        public float ppu = 320f;
        public float margin = 1.08f;
        public string outRoot = null;
    }

    static Args ParseArgs()
    {
        var a = new Args();
        string[] argv = Environment.GetCommandLineArgs();
        for (int i = 0; i < argv.Length - 1; i++)
        {
            switch (argv[i])
            {
                case "-probePrefab": a.prefab = argv[i + 1]; break;
                case "-probeName": a.name = argv[i + 1]; break;
                case "-probePart": a.part = argv[i + 1]; break;
                case "-probeChain": a.chain = argv[i + 1]; break;
                case "-probeStates": a.states = Split(argv[i + 1]); break;
                case "-probeTimes": a.times = SplitF(argv[i + 1]); break;
                case "-probePpu":
                    float.TryParse(argv[i + 1], NumberStyles.Float,
                                   CultureInfo.InvariantCulture, out a.ppu);
                    break;
                case "-probeOut": a.outRoot = argv[i + 1]; break;
            }
        }
        return a;
    }

    static List<string> Split(string s)
    {
        var l = new List<string>();
        foreach (var x in (s ?? "").Split(','))
        {
            var t = x.Trim();
            if (t.Length > 0) l.Add(t);
        }
        return l;
    }

    static List<float> SplitF(string s)
    {
        var l = new List<float>();
        foreach (var x in Split(s))
        {
            float v;
            if (float.TryParse(x, NumberStyles.Float,
                               CultureInfo.InvariantCulture, out v)) l.Add(v);
        }
        if (l.Count == 0) l.Add(0f);
        return l;
    }

    [MenuItem("Tools/2DModel/查看/一键导出（全部）")]
    public static void All()
    {
        var a = ParseArgs();
        if (Environment.GetCommandLineArgs().Length <= 2)
        {
            // 编辑器里从菜单点：优先用当前选中的（场景实例或 prefab 资源）
            var sel = Selection.activeGameObject;
            if (sel != null)
            {
                var p = PrefabUtility.GetCorrespondingObjectFromSource(sel);
                string path = p != null ? AssetDatabase.GetAssetPath(p) : null;
                if (!string.IsNullOrEmpty(path) && path.EndsWith(".prefab"))
                {
                    a.prefab = path;
                    a.name = Path.GetFileNameWithoutExtension(path);
                }
                else
                {
                    a.name = sel.name;
                }
            }
        }
        try
        {
            Run(a);
        }
        catch (Exception e)
        {
            Debug.LogError("[Inspect] FAILED: " + e);
            if (Application.isBatchMode) EditorApplication.Exit(2);
            return;
        }
        if (Application.isBatchMode) EditorApplication.Exit(0);
    }

    static void Run(Args a)
    {
        GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(a.prefab);
        // 统一导出根（D:\VB\Unity2Spine\info），见 ExportRoots.cs
        string root = string.IsNullOrEmpty(a.outRoot)
            ? ExportRoots.Root
            : a.outRoot;
        string dir = Path.Combine(root, "_inspect_" + a.name);
        Directory.CreateDirectory(dir);
        Directory.CreateDirectory(Path.Combine(dir, "frames"));

        var log = new StringBuilder();
        Action<string> L = m =>
        {
            log.AppendLine(m);
            Debug.Log("[Inspect] " + m);
        };

        L("角色 = " + a.name);
        L("prefab = " + a.prefab);

        GameObject go = FindInScene(a.name);
        bool temp = false;
        if (go == null)
        {
            if (prefab == null)
            {
                L("[ERROR] 场景里没有 " + a.name + "，且 prefab 加载失败：" + a.prefab);
                File.WriteAllText(Path.Combine(dir, "run.log"), log.ToString());
                return;
            }
            go = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            temp = true;
            L("场景里没有该角色，已临时实例化 prefab");
        }
        else
        {
            L("使用场景里的实例");
        }

        var activateChain = CalibTargets.Activate(go);
        var isolateOff = CalibTargets.IsolateRenderers(go);
        try
        {
            WriteRenderers(dir, go, L);
            var states = CollectStates(go, a.states);
            WriteDynamic(dir, go, states, L);
            RenderFrames(dir, go, states, a, L);
            if (!string.IsNullOrEmpty(a.part)) WritePart(dir, go, states, a, L);
            if (!string.IsNullOrEmpty(a.chain)) WriteChain(dir, go, states, a, L);
            WriteManifest(dir, a, states, L);
        }
        finally
        {
            CalibTargets.RestoreRenderers(isolateOff);
            CalibTargets.Restore(activateChain);
            if (temp) UnityEngine.Object.DestroyImmediate(go);
        }
        File.WriteAllText(Path.Combine(dir, "run.log"), log.ToString());
        L("完成 -> " + dir);
    }

    static GameObject FindInScene(string name)
    {
        foreach (var t in UnityEngine.Object.FindObjectsOfType<Transform>(true))
            if (t.name == name && t.parent == null) return t.gameObject;
        foreach (var t in UnityEngine.Object.FindObjectsOfType<Transform>(true))
            if (t.name == name) return t.root.gameObject;
        return null;
    }

    // ------------------------------------------------- 1) 静态清单
    static void WriteRenderers(string dir, GameObject go, Action<string> L)
    {
        var sb = new StringBuilder();
        sb.Append("{\n  \"unity\": \"").Append(Application.unityVersion).Append("\",\n");
        sb.Append("  \"renderers\": [\n");
        bool first = true;
        int n = 0;
        foreach (var r in go.GetComponentsInChildren<Renderer>(true))
        {
            var smr = r as SkinnedMeshRenderer;
            var spr = r as SpriteRenderer;
            if (smr == null && spr == null) continue;
            if (!first) sb.Append(",\n");
            first = false;
            n++;
            sb.Append("    {\"path\": \"").Append(Esc(PathOf(go.transform, r.transform))).Append("\"");
            sb.Append(", \"kind\": \"").Append(smr != null ? "skinned" : "sprite").Append("\"");
            sb.Append(", \"activeSelf\": ").Append(r.gameObject.activeSelf ? "true" : "false");
            sb.Append(", \"activeInHierarchy\": ").Append(r.gameObject.activeInHierarchy ? "true" : "false");
            sb.Append(", \"enabled\": ").Append(r.enabled ? "true" : "false");
            sb.Append(", \"sortingLayer\": \"").Append(Esc(r.sortingLayerName)).Append("\"");
            sb.Append(", \"sortingOrder\": ").Append(r.sortingOrder);
            AppendVec(sb, "boundsCenter", r.bounds.center);
            AppendVec(sb, "boundsSize", r.bounds.size);
            var mats = r.sharedMaterials;
            sb.Append(", \"materials\": [");
            for (int i = 0; i < mats.Length; i++)
            {
                if (i > 0) sb.Append(", ");
                sb.Append("\"").Append(Esc(mats[i] != null ? mats[i].name : "")).Append("\"");
            }
            sb.Append("]");
            if (smr != null && smr.sharedMesh != null)
            {
                sb.Append(", \"vertexCount\": ").Append(smr.sharedMesh.vertexCount);
                sb.Append(", \"triangles\": ").Append(smr.sharedMesh.triangles.Length / 3);
                sb.Append(", \"bones\": ").Append(smr.bones != null ? smr.bones.Length : 0);
                sb.Append(", \"bindposes\": ").Append(smr.sharedMesh.bindposes.Length);
                sb.Append(", \"rootBone\": \"")
                  .Append(Esc(smr.rootBone != null ? smr.rootBone.name : "")).Append("\"");
            }
            if (spr != null)
            {
                sb.Append(", \"sprite\": \"")
                  .Append(Esc(spr.sprite != null ? spr.sprite.name : "")).Append("\"");
                sb.Append(", \"flipX\": ").Append(spr.flipX ? "true" : "false");
                sb.Append(", \"flipY\": ").Append(spr.flipY ? "true" : "false");
                if (spr.sprite != null)
                {
                    // Sprite 自己生成的网格：2 个三角形=整块四边形（FullRect），
                    // 更多=按 alpha 轮廓的紧致网格（Tight）。用来判断
                    // "矩形里混进来的邻居图素会不会被画出来"。
                    var sv = spr.sprite.vertices;
                    var st = spr.sprite.triangles;
                    sb.Append(", \"spriteMeshVerts\": ").Append(sv != null ? sv.Length : 0);
                    sb.Append(", \"spriteMeshTris\": ").Append(st != null ? st.Length / 3 : 0);
                    // 完整顶点/UV/索引也一起给：这是"逆向 Unity 的
                    // alpha→轮廓→简化 算法"的拟合目标（只用于对拍，不进成品）。
                    sb.Append(", \"spriteVerts\": [");
                    for (int k = 0; sv != null && k < sv.Length; k++)
                    {
                        if (k > 0) sb.Append(", ");
                        sb.Append("[").Append(F(sv[k].x)).Append(", ")
                          .Append(F(sv[k].y)).Append("]");
                    }
                    sb.Append("]");
                    var su2 = spr.sprite.uv;
                    sb.Append(", \"spriteUvs\": [");
                    for (int k = 0; su2 != null && k < su2.Length; k++)
                    {
                        if (k > 0) sb.Append(", ");
                        sb.Append("[").Append(F(su2[k].x)).Append(", ")
                          .Append(F(su2[k].y)).Append("]");
                    }
                    sb.Append("]");
                    sb.Append(", \"spriteTris\": [");
                    for (int k = 0; st != null && k < st.Length; k++)
                    {
                        if (k > 0) sb.Append(", ");
                        sb.Append(st[k]);
                    }
                    sb.Append("]");
                    sb.Append(", \"spriteBounds\": [")
                      .Append(F(spr.sprite.bounds.min.x)).Append(", ")
                      .Append(F(spr.sprite.bounds.min.y)).Append(", ")
                      .Append(F(spr.sprite.bounds.max.x)).Append(", ")
                      .Append(F(spr.sprite.bounds.max.y)).Append("]");
                }
                if (spr.sprite != null && spr.sprite.texture != null)
                {
                    var rc = spr.sprite.textureRect;
                    sb.Append(", \"texture\": \"")
                      .Append(Esc(spr.sprite.texture.name)).Append("\"");
                    sb.Append(", \"textureRect\": [").Append(F(rc.x)).Append(", ")
                      .Append(F(rc.y)).Append(", ").Append(F(rc.width)).Append(", ")
                      .Append(F(rc.height)).Append("]");
                }
            }
            sb.Append("}");
        }
        sb.Append("\n  ]\n}\n");
        File.WriteAllText(Path.Combine(dir, "renderers.json"), sb.ToString());
        L("renderers.json 写出（" + n + " 个 renderer）");
    }

    // ------------------------------------------------- 2) 运行时逐帧
    class StateInfo
    {
        public Animator animator;
        public string name;
        public AnimationClip clip;
    }

    static List<StateInfo> CollectStates(GameObject go, List<string> only)
    {
        var outp = new List<StateInfo>();
        foreach (var an in go.GetComponentsInChildren<Animator>(true))
        {
            var ctrl = an.runtimeAnimatorController as AnimatorController;
            if (ctrl == null) continue;
            var states = new List<AnimatorState>();
            CollectSm(ctrl.layers[0].stateMachine, states);
            foreach (var st in states)
            {
                var clip = st.motion as AnimationClip;
                if (clip == null) continue;
                if (only != null && !only.Contains(st.name)) continue;
                outp.Add(new StateInfo { animator = an, name = st.name, clip = clip });
            }
        }
        return outp;
    }

    static void CollectSm(AnimatorStateMachine sm, List<AnimatorState> outp)
    {
        foreach (var s in sm.states)
            if (s.state != null) outp.Add(s.state);
        foreach (var sub in sm.stateMachines)
            if (sub.stateMachine != null) CollectSm(sub.stateMachine, outp);
    }

    static void WriteDynamic(string dir, GameObject go, List<StateInfo> states,
                             Action<string> L)
    {
        var sb = new StringBuilder();
        sb.Append("{\n  \"unity\": \"").Append(Application.unityVersion).Append("\",\n");
        sb.Append("  \"dt\": ").Append(F(Dt)).Append(",\n  \"states\": [\n");
        var mesh = new Mesh();
        bool firstState = true;
        foreach (var si in states)
        {
            if (!firstState) sb.Append(",\n");
            firstState = false;
            Play(si, 0f);
            sb.Append("    {\"state\": \"").Append(Esc(si.name)).Append("\"");
            sb.Append(", \"clip\": \"").Append(Esc(si.clip.name)).Append("\"");
            sb.Append(", \"clipLength\": ").Append(F(si.clip.length));
            sb.Append(", \"frames\": [\n");
            float t = 0f;
            int n = 0;
            while (t <= si.clip.length + 1e-4f && n < MaxFramesPerState)
            {
                si.animator.Update(Dt);
                if (n > 0) sb.Append(",\n");
                sb.Append("      {\"t\": ").Append(F(t));
                sb.Append(", \"renderers\": [");
                bool firstR = true;
                foreach (var r in go.GetComponentsInChildren<Renderer>(true))
                {
                    var smr = r as SkinnedMeshRenderer;
                    var spr = r as SpriteRenderer;
                    if (smr == null && spr == null) continue;
                    if (!firstR) sb.Append(", ");
                    firstR = false;
                    sb.Append("{\"path\": \"").Append(Esc(PathOf(go.transform, r.transform))).Append("\"");
                    sb.Append(", \"activeSelf\": ").Append(r.gameObject.activeSelf ? "true" : "false");
                    sb.Append(", \"activeInHierarchy\": ").Append(r.gameObject.activeInHierarchy ? "true" : "false");
                    sb.Append(", \"enabled\": ").Append(r.enabled ? "true" : "false");
                    sb.Append(", \"sortingOrder\": ").Append(r.sortingOrder);
                    sb.Append(", \"isVisible\": ").Append(r.isVisible ? "true" : "false");
                    AppendVec(sb, "boundsCenter", r.bounds.center);
                    AppendVec(sb, "boundsSize", r.bounds.size);
                    if (smr != null && smr.sharedMesh != null)
                    {
                        try
                        {
                            // 必须带 useScale: true —— 和 PoseFrames/SceneT0 那两个
                            // 导出脚本同一个口径（TwoDModelCalibExport 也是
                            // BakeMesh(baked, true) + localToWorldMatrix）。
                            // 参数少的那个重载会把 transform 的世界缩放**预先乘进
                            // 顶点**，再乘一次 localToWorldMatrix 就等于把缩放平方，
                            // 框会小 |lossyScale| 倍（babariana 的
                            // parts_001_back_hiar：错值 0.186 宽 vs 真值 1.138）。
                            smr.BakeMesh(mesh, true);
                            var vs = mesh.vertices;
                            Vector3 lo = new Vector3(float.MaxValue, float.MaxValue, float.MaxValue);
                            Vector3 hi = new Vector3(float.MinValue, float.MinValue, float.MinValue);
                            var m = r.transform.localToWorldMatrix;
                            for (int k = 0; k < vs.Length; k++)
                            {
                                var wv = m.MultiplyPoint3x4(vs[k]);
                                lo = Vector3.Min(lo, wv);
                                hi = Vector3.Max(hi, wv);
                            }
                            AppendVec(sb, "meshMin", lo);
                            AppendVec(sb, "meshMax", hi);
                        }
                        catch (Exception e)
                        {
                            sb.Append(", \"meshError\": \"").Append(Esc(e.Message)).Append("\"");
                        }
                    }
                    else if (spr != null)
                    {
                        sb.Append(", \"sprite\": \"")
                          .Append(Esc(spr.sprite != null ? spr.sprite.name : "")).Append("\"");
                    }
                    sb.Append("}");
                }
                sb.Append("]}");
                n++;
                t += Dt;
            }
            sb.Append("\n    ]}");
            L("dynamic: " + si.name + " " + n + " 帧");
        }
        UnityEngine.Object.DestroyImmediate(mesh);
        sb.Append("\n  ]\n}\n");
        File.WriteAllText(Path.Combine(dir, "dynamic.json"), sb.ToString());
        L("dynamic.json 写出");
    }

    static void Play(StateInfo si, float t)
    {
        si.animator.Rebind();
        si.animator.Play(si.name, 0, 0f);
        si.animator.Update(0f);
        float acc = 0f;
        while (acc < t - 1e-6f) { si.animator.Update(Dt); acc += Dt; }
    }

    // ------------------------------------------------- 3) 参考图渲染
    static void RenderFrames(string dir, GameObject go, List<StateInfo> states,
                             Args a, Action<string> L)
    {
        var outDir = Path.Combine(dir, "frames");
        if (a.times == null || a.times.Count == 0) a.times = new List<float> { 0f };
        foreach (var si in states)
        {
            foreach (var t in a.times)
            {
                if (t > si.clip.length + 1e-4f) continue;
                Play(si, t);
                string tag = si.name + "_t" + Mathf.RoundToInt(t * 1000f);
                Render(go, outDir, tag, a.ppu, a.margin, null);
                L("frames/" + tag + ".png");
            }
        }
    }

    static void Render(GameObject go, string outDir, string tag, float ppu,
                       float margin, HashSet<string> onlyParts)
    {
        var rends = new List<Renderer>();
        foreach (var r in go.GetComponentsInChildren<Renderer>(true))
        {
            if (r is SkinnedMeshRenderer || r is SpriteRenderer) rends.Add(r);
        }
        var off = new List<Renderer>();
        if (onlyParts != null)
        {
            foreach (var r in rends)
                if (!onlyParts.Contains(Leaf(r.transform.name)))
                {
                    if (r.enabled) { r.enabled = false; off.Add(r); }
                }
        }
        try
        {
            bool has = false;
            Bounds b = new Bounds();
            foreach (var r in rends)
            {
                if (!r.enabled || !r.gameObject.activeInHierarchy) continue;
                b.Encapsulate(r.bounds);
                has = true;
            }
            if (!has || b.size.sqrMagnitude < 1e-8f)
            {
                Debug.LogWarning("[Inspect] " + tag + " 没有可见渲染器，跳过截图");
                return;
            }
            float halfH = Mathf.Max(1e-3f, b.extents.y) * margin;
            float halfW = Mathf.Max(1e-3f, b.extents.x) * margin;
            int w = Mathf.Clamp(Mathf.RoundToInt(halfW * 2f * ppu), 64, 4096);
            int h = Mathf.Clamp(Mathf.RoundToInt(halfH * 2f * ppu), 64, 4096);
            float aspect = (float)w / h;
            float size = Mathf.Max(halfH, halfW / aspect);
            Vector3 centre = b.center;

            var rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32);
            var camObj = new GameObject("inspect_cam");
            var cam = camObj.AddComponent<Camera>();
            cam.orthographic = true;
            cam.orthographicSize = size;
            cam.transform.position = new Vector3(centre.x, centre.y, -10f);
            cam.transform.LookAt(new Vector3(centre.x, centre.y, 0f));
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(1f, 1f, 1f, 1f);
            cam.targetTexture = rt;

            var old = RenderTexture.active;
            Texture2D tex = null;
            try
            {
                cam.Render();
                RenderTexture.active = rt;
                tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
                tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
                tex.Apply();
                RenderTexture.active = old;
                File.WriteAllBytes(Path.Combine(outDir, tag + ".png"), tex.EncodeToPNG());
                File.WriteAllText(
                    Path.Combine(outDir, tag + "_cam.txt"),
                    "cx=" + F(centre.x) + "\ncy=" + F(centre.y) +
                    "\nsize=" + F(size) + "\naspect=" + F(aspect) +
                    "\nw=" + w + "\nh=" + h + "\nppu=" + F(ppu) + "\n");
            }
            finally
            {
                RenderTexture.active = old;
                cam.targetTexture = null;
                UnityEngine.Object.DestroyImmediate(camObj);
                rt.Release();
                UnityEngine.Object.DestroyImmediate(rt);
                if (tex != null) UnityEngine.Object.DestroyImmediate(tex);
            }
        }
        finally
        {
            foreach (var r in off) if (r != null) r.enabled = true;
        }
    }

    // ------------------------------------------------- 4) 单部件
    static void WritePart(string dir, GameObject go, List<StateInfo> states,
                          Args a, Action<string> L)
    {
        string want = a.part;
        var si = states.Count > 0 ? states[0] : null;
        if (si != null) Play(si, a.times.Count > 0 ? a.times[0] : 0f);

        var keep = new HashSet<string> { want };
        Render(go, Path.Combine(dir, "frames"), "part_" + Sanitize(want),
               a.ppu, 1.15f, keep);

        var sb = new StringBuilder();
        sb.Append("{\n  \"part\": \"").Append(Esc(want)).Append("\",\n");
        sb.Append("  \"state\": \"").Append(Esc(si != null ? si.name : "")).Append("\",\n");
        sb.Append("  \"items\": [\n");
        var mesh = new Mesh();
        bool first = true;
        foreach (var r in go.GetComponentsInChildren<Renderer>(true))
        {
            if (Leaf(r.transform.name) != want) continue;
            var smr = r as SkinnedMeshRenderer;
            var spr = r as SpriteRenderer;
            if (smr == null && spr == null) continue;
            if (!first) sb.Append(",\n");
            first = false;
            sb.Append("    {\"path\": \"").Append(Esc(PathOf(go.transform, r.transform))).Append("\"");
            sb.Append(", \"kind\": \"").Append(smr != null ? "skinned" : "sprite").Append("\"");
            sb.Append(", \"activeInHierarchy\": ").Append(r.gameObject.activeInHierarchy ? "true" : "false");
            sb.Append(", \"enabled\": ").Append(r.enabled ? "true" : "false");
            sb.Append(", \"sortingOrder\": ").Append(r.sortingOrder);
            AppendVec(sb, "boundsCenter", r.bounds.center);
            AppendVec(sb, "boundsSize", r.bounds.size);
            if (smr != null && smr.sharedMesh != null)
            {
                try
                {
                    smr.BakeMesh(mesh, true);   // 同 WriteDynamic：见那里的注释
                    var vs = mesh.vertices;
                    var m = r.transform.localToWorldMatrix;
                    sb.Append(", \"worldVertices\": [");
                    for (int k = 0; k < vs.Length; k++)
                    {
                        if (k > 0) sb.Append(", ");
                        var wv = m.MultiplyPoint3x4(vs[k]);
                        sb.Append("[").Append(F(wv.x)).Append(", ").Append(F(wv.y)).Append("]");
                    }
                    sb.Append("]");
                    sb.Append(", \"bones\": [");
                    if (smr.bones != null)
                    {
                        for (int k = 0; k < smr.bones.Length; k++)
                        {
                            if (k > 0) sb.Append(", ");
                            sb.Append("\"")
                              .Append(Esc(smr.bones[k] != null ? smr.bones[k].name : ""))
                              .Append("\"");
                        }
                    }
                    sb.Append("]");
                }
                catch (Exception e)
                {
                    sb.Append(", \"meshError\": \"").Append(Esc(e.Message)).Append("\"");
                }
            }
            if (spr != null && spr.sprite != null)
            {
                sb.Append(", \"sprite\": \"").Append(Esc(spr.sprite.name)).Append("\"");
                // Unity 自己生成的紧致网格：用它作为"我们该发什么网格"的真值
                // （只用于验收/对拍，不进成品）。
                var sv = spr.sprite.vertices;
                var su = spr.sprite.uv;
                var st = spr.sprite.triangles;
                sb.Append(", \"spriteVerts\": [");
                for (int k = 0; sv != null && k < sv.Length; k++)
                {
                    if (k > 0) sb.Append(", ");
                    sb.Append("[").Append(F(sv[k].x)).Append(", ").Append(F(sv[k].y)).Append("]");
                }
                sb.Append("]");
                sb.Append(", \"spriteUvs\": [");
                for (int k = 0; su != null && k < su.Length; k++)
                {
                    if (k > 0) sb.Append(", ");
                    sb.Append("[").Append(F(su[k].x)).Append(", ").Append(F(su[k].y)).Append("]");
                }
                sb.Append("]");
                sb.Append(", \"spriteTris\": [");
                for (int k = 0; st != null && k < st.Length; k++)
                {
                    if (k > 0) sb.Append(", ");
                    sb.Append(st[k]);
                }
                sb.Append("]");
                sb.Append(", \"spriteBounds\": [")
                  .Append(F(spr.sprite.bounds.min.x)).Append(", ")
                  .Append(F(spr.sprite.bounds.min.y)).Append(", ")
                  .Append(F(spr.sprite.bounds.max.x)).Append(", ")
                  .Append(F(spr.sprite.bounds.max.y)).Append("]");
                if (spr.sprite.texture != null)
                {
                    var rc = spr.sprite.textureRect;
                    sb.Append(", \"texture\": \"").Append(Esc(spr.sprite.texture.name)).Append("\"");
                    sb.Append(", \"textureRect\": [").Append(F(rc.x)).Append(", ")
                      .Append(F(rc.y)).Append(", ").Append(F(rc.width)).Append(", ")
                      .Append(F(rc.height)).Append("]");
                }
            }
            sb.Append("}");
        }
        UnityEngine.Object.DestroyImmediate(mesh);
        sb.Append("\n  ]\n}\n");
        File.WriteAllText(Path.Combine(dir, "part_" + Sanitize(want) + ".json"),
                          sb.ToString());
        L("part_" + Sanitize(want) + " 写出");
    }

    // ------------------------------------------------- 5) manifest
    /// <summary>
    /// 逐帧 dump 某个节点（按叶子名匹配）及其**整条祖先链**的 local TRS +
    /// 世界位置。用来定位"某个部件在运行时和离线算的差一个平移，是哪一级
    /// 节点的差异"。
    /// </summary>
    static void WriteChain(string dir, GameObject go, List<StateInfo> states,
                           Args a, Action<string> L)
    {
        string want = a.chain;
        Transform target = null;
        foreach (var t in go.GetComponentsInChildren<Transform>(true))
        {
            if (Leaf(t.name) == want) { target = t; break; }
        }
        if (target == null)
        {
            L("[warn] chain: 找不到节点 " + want);
            return;
        }
        var chain = new List<Transform>();
        for (var t = target; t != null; t = t.parent)
        {
            chain.Add(t);
            if (t == go.transform) break;
        }
        chain.Reverse();

        var sb = new StringBuilder();
        sb.Append("{\n  \"target\": \"").Append(Esc(want)).Append("\",\n");
        sb.Append("  \"chain\": [");
        for (int i = 0; i < chain.Count; i++)
        {
            if (i > 0) sb.Append(", ");
            sb.Append("\"").Append(Esc(PathOf(go.transform, chain[i]))).Append("\"");
        }
        sb.Append("],\n  \"states\": [\n");
        bool firstState = true;
        foreach (var si in states)
        {
            if (!firstState) sb.Append(",\n");
            firstState = false;
            Play(si, 0f);
            sb.Append("    {\"state\": \"").Append(Esc(si.name)).Append("\", \"frames\": [\n");
            float t = 0f;
            int n = 0;
            while (t <= si.clip.length + 1e-4f && n < MaxFramesPerState)
            {
                si.animator.Update(Dt);
                if (n > 0) sb.Append(",\n");
                sb.Append("      {\"t\": ").Append(F(t)).Append(", \"nodes\": [");
                for (int i = 0; i < chain.Count; i++)
                {
                    var tr = chain[i];
                    if (i > 0) sb.Append(", ");
                    sb.Append("{\"name\": \"").Append(Esc(tr.name)).Append("\"");
                    sb.Append(", \"localPos\": [").Append(F(tr.localPosition.x)).Append(", ")
                      .Append(F(tr.localPosition.y)).Append(", ")
                      .Append(F(tr.localPosition.z)).Append("]");
                    sb.Append(", \"localEuler\": [").Append(F(tr.localEulerAngles.x)).Append(", ")
                      .Append(F(tr.localEulerAngles.y)).Append(", ")
                      .Append(F(tr.localEulerAngles.z)).Append("]");
                    sb.Append(", \"localScale\": [").Append(F(tr.localScale.x)).Append(", ")
                      .Append(F(tr.localScale.y)).Append(", ")
                      .Append(F(tr.localScale.z)).Append("]");
                    AppendVec(sb, "worldPos", tr.position);
                    sb.Append("}");
                }
                sb.Append("]}");
                n++;
                t += Dt;
            }
            sb.Append("\n    ]}");
            L("chain: " + si.name + " " + n + " 帧（链长 " + chain.Count + "）");
        }
        sb.Append("\n  ]\n}\n");
        File.WriteAllText(Path.Combine(dir, "chain_" + Sanitize(want) + ".json"),
                          sb.ToString());
    }

    static void WriteManifest(string dir, Args a, List<StateInfo> states,
                              Action<string> L)
    {
        var sb = new StringBuilder();
        sb.Append("{\n");
        sb.Append("  \"unity\": \"").Append(Application.unityVersion).Append("\",\n");
        sb.Append("  \"prefab\": \"").Append(Esc(a.prefab)).Append("\",\n");
        sb.Append("  \"char\": \"").Append(Esc(a.name)).Append("\",\n");
        sb.Append("  \"dt\": ").Append(F(Dt)).Append(",\n");
        sb.Append("  \"ppu\": ").Append(F(a.ppu)).Append(",\n");
        sb.Append("  \"part\": \"").Append(Esc(a.part ?? "")).Append("\",\n");
        sb.Append("  \"states\": [");
        for (int i = 0; i < states.Count; i++)
        {
            if (i > 0) sb.Append(", ");
            sb.Append("\"").Append(Esc(states[i].name)).Append("\"");
        }
        sb.Append("],\n  \"files\": [");
        bool first = true;
        foreach (var f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories))
        {
            string rel = f.Substring(dir.Length + 1).Replace('\\', '/');
            if (rel == "manifest.json" || rel == "run.log") continue;
            if (!first) sb.Append(", ");
            first = false;
            sb.Append("\"").Append(Esc(rel)).Append("\"");
        }
        sb.Append("]\n}\n");
        File.WriteAllText(Path.Combine(dir, "manifest.json"), sb.ToString());
        L("manifest.json 写出");
    }

    // ------------------------------------------------- 工具
    static string Leaf(string name)
    {
        if (string.IsNullOrEmpty(name)) return "";
        int i = name.LastIndexOf(' ');
        return (i > 0 && name.EndsWith(")")) ? name.Substring(0, i) : name;
    }

    static string Sanitize(string s)
    {
        var sb = new StringBuilder();
        foreach (var c in (s ?? ""))
        {
            sb.Append((char.IsLetterOrDigit(c) || c == '_' || c == '-') ? c : '_');
        }
        return sb.ToString();
    }

    static string PathOf(Transform root, Transform tf)
    {
        var parts = new List<string>();
        var cur = tf;
        while (cur != null)
        {
            parts.Add(cur.name);
            if (cur == root) break;
            cur = cur.parent;
        }
        parts.Reverse();
        return string.Join("/", parts.ToArray());
    }

    static void AppendVec(StringBuilder sb, string key, Vector3 v)
    {
        sb.Append(", \"").Append(key).Append("\": [")
          .Append(F(v.x)).Append(", ").Append(F(v.y)).Append(", ").Append(F(v.z))
          .Append("]");
    }

    static string F(float v)
    {
        return v.ToString("0.#####", CultureInfo.InvariantCulture);
    }

    static string Esc(string s)
    {
        return (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");
    }
}
