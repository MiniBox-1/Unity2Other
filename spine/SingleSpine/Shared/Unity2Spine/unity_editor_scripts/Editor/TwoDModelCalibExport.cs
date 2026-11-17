// TwoDModelCalibExport.cs
// 一次性导出 Unity 侧"修正/校准数据"到 **D:\VB\Unity2Spine\info\Data**
// （2026-09-18 起统一，见 Assets\Script\ExportRoots.cs；供 D:\VB\Unity2Spine 离线校对）：
//
//   info/Data/PoseFrames/<角色>.json          主 clip 逐帧真值：
//                                             Transform + SkinnedMeshRenderer BakeMesh
//                                             (顶点/uv/三角形/localToWorld) + Sprite
//                                             worldCorners + sortingOrder/renderQueue
//   info/Data/PoseFrames/<角色>@<clip>.json    其它 clip（同样的结构）
//   info/Data/SceneT0/<角色>.json             t=0 真值（额外含 bones/bindposes/
//                                             boneWeights/worldMatrix）
//   info/Data/Frames/<角色>/*.png + *_cam.txt  参考截图（按源像素 1:1 渲染）：
//                                             00_full / 01_dynamic / 02_sprites_white
//                                             / 03_sprites_dark，各自带相机参数
//
// 特点（相对旧脚本）：
//   · 默认**包含未激活的渲染器**（audrey 的子树在场景里是未激活的，旧脚本会导出
//     空 skinned/sprites）；日志里会标出 inactive 数量；
//   · 默认**每条 clip 都导**（我们的导出已经覆盖所有 Animator/所有 clip）；
//   · 参考图按**自动估算的 px/unit**（比较网格 UV 张成与世界张成，与离线侧
//     一致）计算渲染分辨率，做到与源贴图 1:1，不做下采样/插值；
//     三个角色实测约 aeda 103 / blacklilith 728 / audrey 628 px/单位。
//
// 用法：
//   菜单 Tools/2DModel/校准数据/全部导出
//   批处理（渲染需要不带 -nographics）：
//     Unity.exe -batchmode -projectPath <工程> -quit \
//       -executeMethod TwoDModelCalibExport.ExportAll \
//       -logFile D:\VB\Unity2Spine\info\_logs\calib.log

using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class TwoDModelCalibExport
{
    /// <summary>
    /// 导出配置（D:\VB\Unity2Spine\info\Data\export_config.json，可选）。
    /// 有它就按里面的设置来，没有就用代码里的默认值。
    /// </summary>
    [System.Serializable]
    public class ExportConfig
    {
        /// <summary>要导出的角色名；留空 + autoDiscover=true 时自动扫描场景。</summary>
        public string[] names = new string[0];
        /// <summary>要单独导出的**部件**（GameObject 名，可以是 disabled 的）；
        /// 非空时"导出配置里的部件"菜单只处理这些部件。</summary>
        public string[] parts = new string[0];
        /// <summary>名字为空时，是否自动扫描场景里所有 2DModel 角色（含 disabled）。</summary>
        public bool autoDiscover = true;
        public string scene = "Assets/Scenes/save.unity";
        public float sampleStep = 0.05f;
        public int maxFrames = 600;
        public bool exportPoseFrames = true;
        public bool exportSceneT0 = true;
        public bool exportFrames = true;
        public float pixelsPerUnit = 0f;
        public int maxRenderSide = 4096;
        public float renderMargin = 1.06f;
        /// <summary>只处理场景里当前处于激活状态的角色。</summary>
        public bool onlyActive = false;
    }

    private static string ConfigPath
    {
        // 统一导出根：D:\VB\Unity2Spine\info（见 Assets\Script\ExportRoots.cs）
        get { return Path.Combine(ExportRoots.Of("Data"), "export_config.json"); }
    }

    /// <summary>读导出配置；文件不存在或解析失败返回 null（用代码默认值）。</summary>
    public static ExportConfig LoadConfig()
    {
        if (!File.Exists(ConfigPath))
            return null;
        try
        {
            ExportConfig cfg = JsonUtility.FromJson<ExportConfig>(
                File.ReadAllText(ConfigPath, new UTF8Encoding(false)));
            Debug.Log("[Calib] 读取配置 " + ConfigPath);
            return cfg;
        }
        catch (System.Exception ex)
        {
            Debug.LogError("[Calib] 配置解析失败（用默认值）: " + ex.Message);
            return null;
        }
    }

    private static void ApplyConfig(ExportConfig cfg)
    {
        if (cfg.names != null && cfg.names.Length > 0)
            Names = cfg.names;
        if (!string.IsNullOrEmpty(cfg.scene))
            ScenePath = cfg.scene;
        sampleStep = cfg.sampleStep;
        maxFrames = cfg.maxFrames;
        doPoseFrames = cfg.exportPoseFrames;
        doSceneT0 = cfg.exportSceneT0;
        doFrames = cfg.exportFrames;
        pixelsPerUnit = cfg.pixelsPerUnit;
        maxRenderSide = cfg.maxRenderSide;
        renderMargin = cfg.renderMargin;
        autoDiscover = cfg.autoDiscover;
        onlyActive = cfg.onlyActive;
    }

    /// <summary>名字列表为空时，是否自动扫描场景里的角色。</summary>
    public static bool autoDiscover = true;

    /// <summary>扫描场景里所有 2DModel 角色根（子树里有 Animator + SkinnedMeshRenderer），
    /// 包含被 disabled 的对象。</summary>
    public static List<GameObject> DiscoverTargets(Scene scene)
    {
        List<GameObject> outList = new List<GameObject>();
        foreach (GameObject root in scene.GetRootGameObjects())
            Discover(root.transform, outList);
        return outList;
    }

    private static void Discover(Transform t, List<GameObject> outList)
    {
        bool hasAnim = t.GetComponent<Animator>() != null;
        bool hasSkin = t.GetComponentInChildren<SkinnedMeshRenderer>(true)
                       != null;
        if (hasAnim && hasSkin)
        {
            outList.Add(t.gameObject);
            return;                     // 命中即止，不再往下找
        }
        for (int i = 0; i < t.childCount; i++)
            Discover(t.GetChild(i), outList);
    }

    // ---- 可调参数（菜单里也能改）----
    public static string[] Names =
    {
        // 三个主力角色
        "audrey_normal", "blacklilith_normal", "aeda_normal",
        // 泛用性抽样（不含 mod 的 14 个原版角色）
        "warwolf_skin1", "lindwurm_skin1", "alice_skin1_fix",
        "nightangel_skin2_dl", "bloodypanther_normal", "daphne_skin1",
        "saetti_skin1", "miho_skin1", "kunoichikaen_skin1", "ran_skin1",
        "eternity_skin2", "cocowhiteshell_normal", "tomoe_skin1",
        "fortune_skin9",
        // 50 个批量转换的角色（prefabs/Change50）
        "alexandra_normal", "alexandra_skin1", "alice_skin1_dl_idle",
        "alice_skin2", "alvis_skin1", "alvis_skin1_dl", "amy_normal",
        "amy_skin1", "andvari_skin2", "arman_skin1", "atalanta_normal",
        "atalanta_skin1", "audrey_skin1", "azaz_skin1", "babariana_skin1",
        "baekto_skin1", "banshee_skin1", "beasthunter_skin1", "bheur_skin1",
        "blacklilith_skin1", "blacklilith_skin2", "blackwyrm_skin1",
        "bloodypanther_skin1", "brownie_skin1", "carolina_normal",
        "cerberus_skin1", "cerberus_skin2", "cerberus_skin3",
        "charlotte_skin1", "charlotte_skin2", "cheona_skin1", "circe_skin1",
        "constantias2_normal", "constantias2_skin0", "constantias2_skin1",
        "constantias2_skin1S", "constantias2_skin2", "csperrault_skin1",
        "csperrault_skin2", "daika_skin1", "daika_skin1_dl",
        "daphne_skin2", "darkelf_skin1", "darkelf_skin1_dl",
        "draculina_skin1", "draculina_skin1_fix",
    };
    public static float sampleStep = 0.05f;      // 逐帧步长（秒）
    public static int maxFrames = 600;           // 单 clip 帧数保护
    public static bool includeInactiveRenderers = true;
    public static bool exportAllClips = true;
    // 采样完 clip 之后是否再调 animator.Update(0)。
    // 开着会让 Animator 状态机把刚采样到的 m_IsActive / m_Enabled 覆盖掉，
    // 真值里的 activeInHierarchy 就与 clip 曲线矛盾（无法判断是谁的问题）。
    // 默认关；真值只用于校准，关掉更忠实于 clip 本身。
    public static bool animatorUpdateAfterSample = false;
    public static bool doPoseFrames = true;
    public static bool doSceneT0 = true;
    public static bool doFrames = true;
    public static float pixelsPerUnit = 0f;      // 0 = 自动估算（推荐）
    public static int maxRenderSide = 4096;
    public static float renderMargin = 1.06f;

    public static string ScenePath = "Assets/Scenes/save.unity";

    // ------------------------------------------------------------- 菜单入口
    [MenuItem("Tools/2DModel/校准数据/全部导出（PoseFrames + SceneT0 + 参考图）")]
    public static void ExportAll()
    {
        doPoseFrames = doSceneT0 = doFrames = true;
        Run();
    }

    [MenuItem("Tools/2DModel/校准数据/只导出 PoseFrames")]
    public static void ExportPoseOnly()
    {
        doPoseFrames = true; doSceneT0 = false; doFrames = false;
        Run();
    }

    [MenuItem("Tools/2DModel/校准数据/只导出 SceneT0")]
    public static void ExportT0Only()
    {
        doPoseFrames = false; doSceneT0 = true; doFrames = false;
        Run();
    }

    [MenuItem("Tools/2DModel/校准数据/只导出参考图（1:1）")]
    public static void ExportFramesOnly()
    {
        doPoseFrames = false; doSceneT0 = false; doFrames = true;
        onlyActive = false;
        Run();
    }

    /// <summary>只处理场景里当前处于激活状态的角色（其余跳过）。
    /// 用法：在 Unity 里手动启用某个角色，再点这两个菜单。</summary>
    public static bool onlyActive = false;

    [MenuItem("Tools/2DModel/校准数据/只导出当前启用的角色（全部）")]
    public static void ExportActiveAll()
    {
        doPoseFrames = doSceneT0 = doFrames = true;
        onlyActive = true;
        Run();
    }

    [MenuItem("Tools/2DModel/校准数据/只导出当前启用角色的参考图")]
    public static void ExportActiveFramesOnly()
    {
        doPoseFrames = false; doSceneT0 = false; doFrames = true;
        onlyActive = true;
        Run();
    }

    // ------------------------------------------------------------- 主流程
    private static void Run()
    {
        ExportConfig cfg = LoadConfig();
        if (cfg != null)
            ApplyConfig(cfg);

        // 统一导出根：D:\VB\Unity2Spine\info\Data（见 Assets\Script\ExportRoots.cs）
        string dataDir = ExportRoots.Of("Data");
        Directory.CreateDirectory(Path.Combine(dataDir, "PoseFrames"));
        Directory.CreateDirectory(Path.Combine(dataDir, "SceneT0"));
        Directory.CreateDirectory(Path.Combine(dataDir, "Frames"));

        Scene scene = EditorSceneManager.OpenScene(ScenePath,
                                                   OpenSceneMode.Single);
        List<GameObject> targets;
        if ((Names == null || Names.Length == 0) && autoDiscover)
        {
            // 没有名单：自己扫描场景里所有 2DModel 角色（含 disabled）
            targets = DiscoverTargets(scene);
            Debug.Log("[Calib] 自动扫描到 " + targets.Count + " 个角色");
        }
        else
        {
            targets = CalibTargets.Collect(Names);
        }
        if (onlyActive)
        {
            targets = targets.FindAll(t => t.activeInHierarchy);
            Debug.Log("[Calib] 只导「启用中」的角色，命中 " + targets.Count + " 个");
        }
        onlyActive = false;

        if (targets.Count == 0)
        {
            Debug.LogError("[Calib] 场景里没找到角色根（" +
                           string.Join(", ", Names) + "）");
            Finish(1);
            return;
        }

        // 逐个角色处理：每次只激活当前这一个（其它保持 disabled），
        // 导出完立刻恢复，避免多个角色互相干扰。
        for (int i = 0; i < targets.Count; i++)
        {
            GameObject root = targets[i];
            Debug.Log(string.Format("[Calib] ({0}/{1}) 导出 {2}",
                                    i + 1, targets.Count, root.name));
            try
            {
                Process(root, dataDir);
            }
            catch (System.Exception ex)
            {
                Debug.LogError("[Calib] " + root.name + " 导出失败: " +
                               ex.Message + "\n" + ex.StackTrace);
            }
        }
        AssetDatabase.Refresh();
        Finish(0);
    }

    private static void Finish(int code)
    {
        Debug.Log("[Calib] 完成（输出在 " + ExportRoots.Of("Data") + "）");
        if (Application.isBatchMode)
            EditorApplication.Exit(code);
    }

    private static bool Match(string name)
    {
        foreach (string n in Names)
            if (name == n || name.StartsWith(n + "("))
                return true;
        return false;
    }

    private static void Process(GameObject root, string dataDir)
    {
        // 单个角色的完整流程：父链激活（其它角色不动）-> 独立采样 -> 导出 -> 恢复。
        // 角色在场景里通常是 disabled，不激活的话 Camera.Render 画不出东西、
        // AnimationMode 也采不到姿势。
        List<GameObject> reactivated = CalibTargets.Activate(root);
        AnimationMode.StartAnimationMode();
        try
        {
            ProcessActive(root, dataDir);
        }
        finally
        {
            AnimationMode.StopAnimationMode();
            CalibTargets.Restore(reactivated);
        }
    }

    private static void ProcessActive(GameObject root, string dataDir)
    {
        List<SkinnedMeshRenderer> skinned =
            new List<SkinnedMeshRenderer>(root.GetComponentsInChildren<
                                          SkinnedMeshRenderer>(
                includeInactiveRenderers));
        List<MeshRenderer> meshes =
            new List<MeshRenderer>(root.GetComponentsInChildren<MeshRenderer>(
                includeInactiveRenderers));
        List<SpriteRenderer> sprites =
            new List<SpriteRenderer>(root.GetComponentsInChildren<
                                     SpriteRenderer>(includeInactiveRenderers));
        int inactive = 0;
        foreach (SkinnedMeshRenderer r in skinned) if (!r.gameObject.activeInHierarchy) inactive++;
        foreach (MeshRenderer r in meshes) if (!r.gameObject.activeInHierarchy) inactive++;
        foreach (SpriteRenderer r in sprites) if (!r.gameObject.activeInHierarchy) inactive++;

        Animator animator = root.GetComponentInChildren<Animator>(true);
        AnimationClip mainClip = MainClip(animator);
        Debug.Log(string.Format(
            "[Calib] {0}: skinned={1} mesh={2} sprites={3}（未激活 {4}）mainClip={5}",
            root.name, skinned.Count, meshes.Count, sprites.Count, inactive,
            mainClip == null ? "<无>" : mainClip.name));

        List<AnimationClip> clips = new List<AnimationClip>();
        if (mainClip != null)
            clips.Add(mainClip);
        if (exportAllClips && animator != null &&
            animator.runtimeAnimatorController != null)
        {
            foreach (AnimationClip c in
                     animator.runtimeAnimatorController.animationClips)
            {
                if (c == null || clips.Contains(c))
                    continue;
                clips.Add(c);
            }
        }

        if (doPoseFrames && clips.Count > 0)
        {
            foreach (AnimationClip c in clips)
            {
                string file = c == mainClip
                    ? root.name + ".json"
                    : root.name + "@" + c.name + ".json";
                string json = BuildPoseFrames(root, animator, c, skinned,
                                              meshes, sprites);
                string outPath = Path.Combine(
                    Path.Combine(dataDir, "PoseFrames"), file);
                File.WriteAllText(outPath, json, new UTF8Encoding(false));
                Debug.Log("[Calib] PoseFrames -> " + outPath);
            }
        }

        if (doSceneT0)
        {
            if (mainClip != null && animator != null)
            {
                AnimationMode.SampleAnimationClip(animator.gameObject, mainClip, 0f);
                try { animator.Update(0f); } catch { }
            }
            string json = BuildSceneT0(root, skinned, meshes, sprites);
            string outPath = Path.Combine(Path.Combine(dataDir, "SceneT0"),
                                          root.name + ".json");
            File.WriteAllText(outPath, json, new UTF8Encoding(false));
            Debug.Log("[Calib] SceneT0 -> " + outPath);
        }

        if (doFrames)
        {
            if (mainClip != null && animator != null)
            {
                AnimationMode.SampleAnimationClip(animator.gameObject, mainClip, 0f);
                try { animator.Update(0f); } catch { }
            }
            string dir = Path.Combine(Path.Combine(dataDir, "Frames"), root.name);
            Directory.CreateDirectory(dir);
            float ppu = pixelsPerUnit > 0f
                ? pixelsPerUnit
                : EstimatePixelsPerUnit(skinned, meshes, sprites);
            Debug.Log("[Calib] " + root.name + " 参考图比例 px/unit = " +
                      F(ppu) + "（源图尺寸 " + SourceTextureSize(sprites) + "）");
            CaptureSet(root, dir, "00_full", RenderSet.All,
                       new Color(1f, 1f, 1f, 1f), ppu, skinned, meshes, sprites);
            CaptureSet(root, dir, "01_dynamic", RenderSet.Dynamic,
                       new Color(1f, 1f, 1f, 1f), ppu, skinned, meshes, sprites);
            CaptureSet(root, dir, "02_sprites_white", RenderSet.Sprites,
                       new Color(1f, 1f, 1f, 1f), ppu, skinned, meshes, sprites);
            CaptureSet(root, dir, "03_sprites_dark", RenderSet.Sprites,
                       new Color(10f / 255f, 10f / 255f, 10f / 255f, 1f),
                       ppu, skinned, meshes, sprites);
        }
    }

    // ----------------------------------------------------------- PoseFrames
    private static string BuildPoseFrames(GameObject root, Animator animator,
                                          AnimationClip clip,
                                          List<SkinnedMeshRenderer> skinned,
                                          List<MeshRenderer> meshes,
                                          List<SpriteRenderer> sprites)
    {
        float dur = clip == null ? 1f : clip.length;
        int frameCount = Mathf.Min(maxFrames,
            Mathf.CeilToInt(dur / Mathf.Max(0.001f, sampleStep)) + 1);
        StringBuilder b = new StringBuilder();
        b.Append("{\n  \"prefab\": \"").Append(Escape(root.name)).Append("\",\n");
        b.Append("  \"clip\": \"").Append(Escape(clip == null ? "" : clip.name))
            .Append("\",\n");
        b.Append("  \"duration\": ").Append(F(dur)).Append(",\n");
        b.Append("  \"frames\": [\n");
        for (int i = 0; i < frameCount; i++)
        {
            float t = Mathf.Min(dur, i * sampleStep);
            if (clip != null)
                AnimationMode.SampleAnimationClip(
                    animator != null ? animator.gameObject : root, clip, t);
            if (animatorUpdateAfterSample && animator != null &&
                animator.isActiveAndEnabled)
            {
                try { animator.Update(0f); } catch { }
            }
            b.Append(i == 0 ? "    " : "    ,");
            b.Append(FrameJson(root, dur <= 0f ? 0f : t / dur, t, skinned,
                               meshes, sprites));
            b.Append("\n");
        }
        b.Append("\n  ]\n}\n");
        return b.ToString();
    }

    private static string FrameJson(GameObject root, float norm, float time,
                                    List<SkinnedMeshRenderer> skinned,
                                    List<MeshRenderer> meshes,
                                    List<SpriteRenderer> sprites)
    {
        StringBuilder b = new StringBuilder();
        b.Append("{\"normalized\": ").Append(F(norm))
            .Append(", \"time\": ").Append(F(time)).Append(",\n");

        List<Transform> ts = new List<Transform> { root.transform };
        ts.AddRange(root.GetComponentsInChildren<Transform>(true));
        b.Append("  \"transforms\": [");
        for (int i = 0; i < ts.Count; i++)
        {
            if (i > 0) b.Append(", ");
            Transform t = ts[i];
            b.Append("{\"path\": \"").Append(Escape(PathOf(t)))
                .Append("\", \"pos\": ").Append(V3(t.position))
                .Append(", \"rot\": ").Append(Q(t.rotation))
                .Append(", \"localPos\": ").Append(V3(t.localPosition))
                .Append(", \"localEuler\": ").Append(V3(t.localEulerAngles))
                .Append(", \"localScale\": ").Append(V3(t.localScale))
                .Append("}");
        }
        b.Append("],\n");

        b.Append("  \"skinned\": [");
        bool first = true;
        foreach (SkinnedMeshRenderer smr in skinned)
        {
            if (!includeInactiveRenderers &&
                (!smr.gameObject.activeInHierarchy || !smr.enabled))
                continue;
            Mesh baked = new Mesh();
            smr.BakeMesh(baked, true);
            b.Append(first ? "" : ", ");
            first = false;
            b.Append("{\"path\": \"").Append(Escape(PathOf(smr.transform)))
                .Append("\", \"kind\": \"skinned\", ")
                .Append(MeshFieldsJson(baked))
                .Append(", \"localToWorld\": ")
                .Append(Mat4(smr.transform.localToWorldMatrix))
                .Append(", \"sortingOrder\": ").Append(smr.sortingOrder)
                .Append(", \"renderQueue\": ").Append(RenderQueue(smr))
                .Append(", \"activeInHierarchy\": ")
                .Append(smr.gameObject.activeInHierarchy ? "true" : "false")
                // activeSelf = 只看自己的 SetActive（不受父链影响）；
                // enabled = 渲染器自己的 m_Enabled。两者分开写，离线侧才能判定
                // “这个部件到底为什么没显示”（父链 vs 自身 vs 渲染器）。
                .Append(", \"activeSelf\": ")
                .Append(smr.gameObject.activeSelf ? "true" : "false")
                .Append(", \"enabled\": ")
                .Append(smr.enabled ? "true" : "false")
                .Append("}");
            Object.DestroyImmediate(baked);
        }
        // 静态 MeshRenderer 也用同一结构（positions/uvs/triangles +
        // localToWorld），转换侧按顶点一一对应比较
        foreach (MeshRenderer mr in meshes)
        {
            MeshFilter mf = mr.GetComponent<MeshFilter>();
            if (mf == null || mf.sharedMesh == null)
                continue;
            if (!includeInactiveRenderers &&
                (!mr.gameObject.activeInHierarchy || !mr.enabled))
                continue;
            b.Append(first ? "" : ", ");
            first = false;
            b.Append("{\"path\": \"").Append(Escape(PathOf(mr.transform)))
                .Append("\", \"kind\": \"static\", ")
                .Append(MeshFieldsJson(mf.sharedMesh))
                .Append(", \"localToWorld\": ")
                .Append(Mat4(mr.transform.localToWorldMatrix))
                .Append(", \"sortingOrder\": ").Append(mr.sortingOrder)
                .Append(", \"renderQueue\": ").Append(RenderQueue(mr))
                .Append(", \"activeInHierarchy\": ")
                .Append(mr.gameObject.activeInHierarchy ? "true" : "false")
                .Append(", \"activeSelf\": ")
                .Append(mr.gameObject.activeSelf ? "true" : "false")
                .Append(", \"enabled\": ")
                .Append(mr.enabled ? "true" : "false")
                .Append("}");
        }
        b.Append("],\n");

        // SpriteRenderer：世界四角 + rect + 贴图尺寸
        b.Append("  \"sprites\": [");
        first = true;
        foreach (SpriteRenderer sr in sprites)
        {
            if (!includeInactiveRenderers &&
                (!sr.gameObject.activeInHierarchy || !sr.enabled))
                continue;
            b.Append(first ? "" : ", ");
            first = false;
            b.Append("{\"path\": \"").Append(Escape(PathOf(sr.transform)))
                .Append("\", \"kind\": \"sprite\", \"worldCorners\": ")
                .Append(V3List(SpriteCorners(sr)))
                .Append(", \"rect\": ")
                .Append(sr.sprite == null ? "[]" : V4(RectOf(sr.sprite)))
                .Append(", \"textureSize\": ")
                .Append(sr.sprite == null || sr.sprite.texture == null
                            ? "[1, 1]"
                            : "[" + sr.sprite.texture.width + ", " +
                              sr.sprite.texture.height + "]")
                .Append(", \"sortingOrder\": ").Append(sr.sortingOrder)
                .Append(", \"renderQueue\": ").Append(RenderQueue(sr))
                .Append(", \"activeInHierarchy\": ")
                .Append(sr.gameObject.activeInHierarchy ? "true" : "false")
                .Append(", \"activeSelf\": ")
                .Append(sr.gameObject.activeSelf ? "true" : "false")
                .Append(", \"enabled\": ")
                .Append(sr.enabled ? "true" : "false")
                .Append("}");
        }
        b.Append("]\n}");
        return b.ToString();
    }

    // ----------------------------------------------------------- SceneT0
    private static string BuildSceneT0(GameObject root,
                                       List<SkinnedMeshRenderer> skinned,
                                       List<MeshRenderer> meshes,
                                       List<SpriteRenderer> sprites)
    {
        StringBuilder b = new StringBuilder();
        b.Append("{\n  \"prefab\": \"").Append(Escape(root.name)).Append("\",\n");
        b.Append("  \"exportTime\": \"").Append(System.DateTime.Now.ToString("s"))
            .Append("\",\n  \"animatorState\": {\"normalizedTime\": 0.0},\n");
        List<Transform> ts = new List<Transform> { root.transform };
        ts.AddRange(root.GetComponentsInChildren<Transform>(true));
        b.Append("  \"transforms\": [\n");
        for (int i = 0; i < ts.Count; i++)
        {
            Transform t = ts[i];
            b.Append(i == 0 ? "    " : "    ,");
            b.Append("{\"path\": \"").Append(Escape(PathOf(t)))
                .Append("\", \"name\": \"").Append(Escape(t.name))
                .Append("\", \"localPos\": ").Append(V3(t.localPosition))
                .Append(", \"localRot\": ").Append(Q(t.localRotation))
                .Append(", \"localEuler\": ").Append(V3(t.localEulerAngles))
                .Append(", \"localScale\": ").Append(V3(t.localScale))
                .Append(", \"worldPos\": ").Append(V3(t.position))
                .Append(", \"worldRot\": ").Append(Q(t.rotation))
                .Append(", \"worldScale\": ").Append(V3(t.lossyScale))
                .Append(", \"worldMatrix\": ")
                .Append(Mat4(t.localToWorldMatrix)).Append("}\n");
        }
        b.Append("  ],\n  \"renderers\": [\n");
        bool first = true;
        foreach (SkinnedMeshRenderer smr in skinned)
        {
            Mesh mesh = smr.sharedMesh;
            Mesh baked = new Mesh();
            smr.BakeMesh(baked, true);
            b.Append(first ? "    " : "    ,");
            first = false;
            b.Append("{\"kind\": \"skinned\", \"path\": \"")
                .Append(Escape(PathOf(smr.transform)))
                .Append("\", \"gameObject\": \"").Append(Escape(smr.name))
                .Append("\", \"enabled\": ").Append(smr.enabled ? "true" : "false")
                .Append(", \"activeInHierarchy\": ")
                .Append(smr.gameObject.activeInHierarchy ? "true" : "false")
                .Append(", \"vertexCount\": ")
                .Append(mesh ? mesh.vertexCount : 0)
                .Append(", \"bones\": [");
            if (smr.bones != null)
                for (int i = 0; i < smr.bones.Length; i++)
                    b.Append(i > 0 ? ", " : "").Append("\"")
                        .Append(Escape(smr.bones[i] ? PathOf(smr.bones[i])
                                                    : "null"))
                        .Append("\"");
            b.Append("], \"bindposes\": [");
            if (mesh != null && mesh.bindposes != null)
                for (int i = 0; i < mesh.bindposes.Length; i++)
                    b.Append(i > 0 ? ", " : "").Append(Mat4(mesh.bindposes[i]));
            b.Append("], \"boneWeights\": ").Append(WeightsJson(mesh))
                .Append(", \"baked\": ").Append(MeshJson(baked))
                .Append(", \"localToWorld\": ")
                .Append(Mat4(smr.transform.localToWorldMatrix))
                .Append(", \"sortingOrder\": ").Append(smr.sortingOrder)
                .Append(", \"renderQueue\": ").Append(RenderQueue(smr))
                .Append("}\n");
            Object.DestroyImmediate(baked);
        }
        foreach (MeshRenderer mr in meshes)
        {
            MeshFilter mf = mr.GetComponent<MeshFilter>();
            if (mf == null || mf.sharedMesh == null)
                continue;
            b.Append(first ? "    " : "    ,");
            first = false;
            b.Append("{\"kind\": \"static\", \"path\": \"")
                .Append(Escape(PathOf(mr.transform)))
                .Append("\", \"localToWorld\": ")
                .Append(Mat4(mr.transform.localToWorldMatrix))
                .Append(", \"positions\": ")
                .Append(V3List(new List<Vector3>(mf.sharedMesh.vertices)))
                .Append(", \"sortingOrder\": ").Append(mr.sortingOrder)
                .Append(", \"renderQueue\": ").Append(RenderQueue(mr))
                .Append("}\n");
        }
        foreach (SpriteRenderer sr in sprites)
        {
            b.Append(first ? "    " : "    ,");
            first = false;
            b.Append("{\"kind\": \"sprite\", \"path\": \"")
                .Append(Escape(PathOf(sr.transform)))
                .Append("\", \"gameObject\": \"").Append(Escape(sr.name))
                .Append("\", \"enabled\": ").Append(sr.enabled ? "true" : "false")
                .Append(", \"rect\": ")
                .Append(sr.sprite == null ? "[]" : V4(RectOf(sr.sprite)))
                .Append(", \"pivot\": ")
                .Append(sr.sprite == null
                            ? "[]"
                            : "[" + F(sr.sprite.pivot.x) + ", " +
                              F(sr.sprite.pivot.y) + "]")
                .Append(", \"pixelsPerUnit\": ")
                .Append(sr.sprite == null ? "100" : F(sr.sprite.pixelsPerUnit))
                .Append(", \"worldCorners\": ").Append(V3List(SpriteCorners(sr)))
                .Append(", \"localToWorld\": ")
                .Append(Mat4(sr.transform.localToWorldMatrix))
                .Append(", \"sortingOrder\": ").Append(sr.sortingOrder)
                .Append(", \"renderQueue\": ").Append(RenderQueue(sr))
                .Append("}\n");
        }
        b.Append("  ]\n}\n");
        return b.ToString();
    }

    // ----------------------------------------------------------- 参考截图
    public enum RenderSet { All, Dynamic, Sprites }

    /// <summary>
    /// 给"单对象导出"用：对任意对象（不必是角色根）出四张参考图。
    /// 调用方负责先激活对象及其父链；渲染期间会自动隔离其它对象的渲染器。
    /// </summary>
    public static void CaptureAllSets(GameObject root, string dir)
    {
        List<SkinnedMeshRenderer> skinned = new List<SkinnedMeshRenderer>(
            root.GetComponentsInChildren<SkinnedMeshRenderer>(true));
        List<MeshRenderer> meshes = new List<MeshRenderer>(
            root.GetComponentsInChildren<MeshRenderer>(true));
        List<SpriteRenderer> sprites = new List<SpriteRenderer>(
            root.GetComponentsInChildren<SpriteRenderer>(true));
        float ppu = pixelsPerUnit > 0f
            ? pixelsPerUnit
            : EstimatePixelsPerUnit(skinned, meshes, sprites);
        Debug.Log(string.Format(
            "[Calib] {0}: skinned={1} mesh={2} sprites={3} px/unit={4}",
            root.name, skinned.Count, meshes.Count, sprites.Count, F(ppu)));
        CaptureSet(root, dir, "00_full", RenderSet.All, Color.white,
                   ppu, skinned, meshes, sprites);
        CaptureSet(root, dir, "01_dynamic", RenderSet.Dynamic, Color.white,
                   ppu, skinned, meshes, sprites);
        CaptureSet(root, dir, "02_sprites_white", RenderSet.Sprites,
                   Color.white, ppu, skinned, meshes, sprites);
        CaptureSet(root, dir, "03_sprites_dark", RenderSet.Sprites,
                   new Color(10f / 255f, 10f / 255f, 10f / 255f, 1f),
                   ppu, skinned, meshes, sprites);
    }

    /// <summary>
    /// 估算"1 世界单位 = 多少源图像素"。做法与离线侧一致：比较蒙皮网格的
    /// UV 张成（× 贴图尺寸 = 像素）与世界张成（单位）；精灵自带局部缩放，
    /// 会污染比值，所以只用网格部件，取两轴的中位数。
    /// </summary>
    private static float EstimatePixelsPerUnit(List<SkinnedMeshRenderer> skinned,
                                               List<MeshRenderer> meshes,
                                               List<SpriteRenderer> sprites)
    {
        int texW = 0, texH = 0;
        foreach (SpriteRenderer sr in sprites)
            if (sr.sprite != null && sr.sprite.texture != null)
            {
                texW = sr.sprite.texture.width;
                texH = sr.sprite.texture.height;
                break;
            }
        if (texW == 0)
            return 100f;

        List<float> vals = new List<float>();
        foreach (SkinnedMeshRenderer smr in skinned)
        {
            Mesh m = smr.sharedMesh;
            if (m == null)
                continue;
            Mesh baked = new Mesh();
            smr.BakeMesh(baked, true);
            Vector3[] vs = baked.vertices;
            Vector2[] uvs = baked.uv;          // 烘焙网格可读，UV 与源网格一致
            Object.DestroyImmediate(baked);
            if (vs.Length == 0 || uvs.Length == 0)
                continue;
            float uMin = float.MaxValue, uMax = float.MinValue;
            float vMin = float.MaxValue, vMax = float.MinValue;
            foreach (Vector2 uv in uvs)
            {
                uMin = Mathf.Min(uMin, uv.x); uMax = Mathf.Max(uMax, uv.x);
                vMin = Mathf.Min(vMin, uv.y); vMax = Mathf.Max(vMax, uv.y);
            }
            float xMin = float.MaxValue, xMax = float.MinValue;
            float yMin = float.MaxValue, yMax = float.MinValue;
            // BakeMesh 给的是**局部空间**顶点，要先变换到世界再比 UV
            Matrix4x4 l2w = smr.transform.localToWorldMatrix;
            foreach (Vector3 v in vs)
            {
                Vector3 w = l2w.MultiplyPoint3x4(v);
                xMin = Mathf.Min(xMin, w.x); xMax = Mathf.Max(xMax, w.x);
                yMin = Mathf.Min(yMin, w.y); yMax = Mathf.Max(yMax, w.y);
            }
            float rx = (uMax - uMin) * texW / Mathf.Max(1e-6f, xMax - xMin);
            float ry = (vMax - vMin) * texH / Mathf.Max(1e-6f, yMax - yMin);
            if (rx > 1f && ry > 1f && rx < 1e5f && ry < 1e5f &&
                Mathf.Abs(rx - ry) / Mathf.Max(rx, ry) < 0.25f)
                vals.Add((rx + ry) * 0.5f);
        }
        if (vals.Count == 0)
            return 100f;
        vals.Sort();
        return vals[vals.Count / 2];
    }

    private static void CaptureSet(GameObject root, string dir, string tag,
                                   RenderSet set, Color bg, float ppu,
                                   List<SkinnedMeshRenderer> skinned,
                                   List<MeshRenderer> meshes,
                                   List<SpriteRenderer> sprites)
    {
        Bounds b = new Bounds();
        bool has = false;
        if (set == RenderSet.All || set == RenderSet.Dynamic)
        {
            foreach (SkinnedMeshRenderer r in skinned)
                Encapsulate(ref b, ref has, r.bounds);
            foreach (MeshRenderer r in meshes)
                Encapsulate(ref b, ref has, r.bounds);
        }
        if (set == RenderSet.All || set == RenderSet.Sprites)
        {
            foreach (SpriteRenderer r in sprites)
                Encapsulate(ref b, ref has, r.bounds);
        }
        if (!has || b.size.sqrMagnitude < 1e-8f)
        {
            Debug.LogWarning("[Calib] " + root.name + " / " + tag +
                             " 没有可见渲染器，跳过截图");
            return;
        }

        float halfH = Mathf.Max(1e-3f, b.extents.y) * renderMargin;
        float halfW = Mathf.Max(1e-3f, b.extents.x) * renderMargin;
        int w = Mathf.Clamp(Mathf.RoundToInt(halfW * 2f * ppu), 64,
                            maxRenderSide);
        int h = Mathf.Clamp(Mathf.RoundToInt(halfH * 2f * ppu), 64,
                            maxRenderSide);
        float aspect = (float)w / h;
        // 高度/宽度取较大者作为正交半高，保证整幅内容都在画面里
        float size = Mathf.Max(halfH, halfW / aspect);

        RenderTexture rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32);
        GameObject camObj = new GameObject("calib_cam");
        Camera cam = camObj.AddComponent<Camera>();
        cam.orthographic = true;
        cam.orthographicSize = size;
        cam.transform.position = new Vector3(b.center.x, b.center.y, -10f);
        cam.transform.LookAt(new Vector3(b.center.x, b.center.y, 0f));
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = bg;
        cam.targetTexture = rt;

        RenderTexture old = RenderTexture.active;
        Texture2D tex = null;
        // 场景里同时放着多个角色时，别的角色会挡在画面里：截图期间先关掉
        // 不属于本角色子树的渲染器，结束后恢复。
        List<Renderer> otherOff = CalibTargets.IsolateRenderers(root);
        // 分层截图必须只渲染本集合：否则 sprite 层会把整个角色也渲进去，
        // 分层比对（calib_sprites / calib_full）就失去意义
        List<Renderer> turnedOff = new List<Renderer>();
        if (set == RenderSet.Sprites)
        {
            foreach (SkinnedMeshRenderer r in skinned)
                if (r.enabled) { r.enabled = false; turnedOff.Add(r); }
            foreach (MeshRenderer r in meshes)
                if (r.enabled) { r.enabled = false; turnedOff.Add(r); }
        }
        else if (set == RenderSet.Dynamic)
        {
            foreach (SpriteRenderer r in sprites)
                if (r.enabled) { r.enabled = false; turnedOff.Add(r); }
        }
        try
        {
            cam.Render();
            RenderTexture.active = rt;
            tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
            tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
            tex.Apply();
            RenderTexture.active = old;
            File.WriteAllBytes(Path.Combine(dir, tag + ".png"),
                               tex.EncodeToPNG());
            File.WriteAllText(
                Path.Combine(dir, tag + "_cam.txt"),
                "cx=" + F(b.center.x) + "\ncy=" + F(b.center.y) +
                "\nsize=" + F(size) + "\naspect=" + F(aspect) +
                "\nw=" + w + "\nh=" + h + "\n");
            Debug.Log("[Calib] 截图 -> " + Path.Combine(dir, tag + ".png") +
                      "  (" + w + "x" + h + ", px/unit=" + F(ppu) + ")");
        }
        finally
        {
            foreach (Renderer r in turnedOff)
                if (r != null) r.enabled = true;
            CalibTargets.RestoreRenderers(otherOff);
            RenderTexture.active = old;
            cam.targetTexture = null;
            Object.DestroyImmediate(camObj);
            rt.Release();
            Object.DestroyImmediate(rt);
            if (tex != null) Object.DestroyImmediate(tex);
        }
    }

    private static void Encapsulate(ref Bounds b, ref bool has, Bounds add)
    {
        if (add.size.sqrMagnitude < 1e-10f)
            return;
        if (!has) { b = add; has = true; }
        else b.Encapsulate(add);
    }

    private static string SourceTextureSize(List<SpriteRenderer> sprites)
    {
        foreach (SpriteRenderer sr in sprites)
            if (sr.sprite != null && sr.sprite.texture != null)
                return sr.sprite.texture.width + "x" + sr.sprite.texture.height;
        return "?";
    }

    // ----------------------------------------------------------- 小工具
    private static AnimationClip MainClip(Animator animator)
    {
        if (animator == null || animator.runtimeAnimatorController == null)
            return null;
        AnimationClip[] clips = animator.runtimeAnimatorController.animationClips;
        if (clips == null || clips.Length == 0)
            return null;
        // 1) 名字里含 lobby 且不含 start/tep/breast（黑莉莉丝的
        //    "3P_BlackLilith_N__2DModel_lobby_Tep_breast" 也含 lobby，要排除）
        foreach (AnimationClip c in clips)
            if ((c.name.Contains("lobby") || c.name.Contains("Lobby")) &&
                !c.name.Contains("start") && !c.name.Contains("Start"))
            {
                string low = c.name.ToLower();
                if (low.Contains("tep") || low.Contains("breast"))
                    continue;
                return c;
            }
        // 2) 退一步：任何含 lobby 的非 start
        foreach (AnimationClip c in clips)
            if ((c.name.Contains("lobby") || c.name.Contains("Lobby")) &&
                !c.name.Contains("start") && !c.name.Contains("Start"))
                return c;
        return clips[0];
    }

    private static string PathOf(Transform t)
    {
        List<string> parts = new List<string>();
        Transform cur = t;
        while (cur != null)
        {
            parts.Insert(0, cur.name);
            cur = cur.parent;
        }
        return string.Join("/", parts.ToArray());
    }

    private static List<Vector3> SpriteCorners(SpriteRenderer sr)
    {
        List<Vector3> outp = new List<Vector3>();
        if (sr.sprite == null)
            return outp;
        Sprite s = sr.sprite;
        float w = s.rect.width / s.pixelsPerUnit;
        float h = s.rect.height / s.pixelsPerUnit;
        float l = -s.pivot.x / s.pixelsPerUnit;
        float b = -s.pivot.y / s.pixelsPerUnit;
        Vector3[] local =
        {
            new Vector3(l, b, 0), new Vector3(l + w, b, 0),
            new Vector3(l + w, b + h, 0), new Vector3(l, b + h, 0),
        };
        for (int i = 0; i < local.Length; i++)
            outp.Add(sr.transform.TransformPoint(local[i]));
        return outp;
    }

    private static List<Vector3> MeshCorners(Mesh mesh, Matrix4x4 m)
    {
        List<Vector3> outp = new List<Vector3>();
        Bounds b = mesh.bounds;
        Vector3[] local =
        {
            new Vector3(b.min.x, b.min.y, b.center.z),
            new Vector3(b.max.x, b.min.y, b.center.z),
            new Vector3(b.max.x, b.max.y, b.center.z),
            new Vector3(b.min.x, b.max.y, b.center.z),
        };
        for (int i = 0; i < local.Length; i++)
            outp.Add(m.MultiplyPoint3x4(local[i]));
        return outp;
    }

    private static int RenderQueue(Renderer r)
    {
        return r.sharedMaterial == null ? -1 : r.sharedMaterial.renderQueue;
    }

    /// <summary>mesh 的字段片段（不含外层大括号），便于嵌进别的对象里。</summary>
    private static string MeshFieldsJson(Mesh mesh)
    {
        StringBuilder b = new StringBuilder();
        Vector3[] vs = mesh.vertices;
        Vector2[] uvs = mesh.uv;
        int[] tris = mesh.triangles;
        b.Append("\"vertexCount\": ").Append(vs.Length).Append(", \"positions\": [");
        for (int i = 0; i < vs.Length; i++)
            b.Append(i > 0 ? ", " : "").Append(V3(vs[i]));
        b.Append("], \"uvs\": [");
        for (int i = 0; i < uvs.Length; i++)
            b.Append(i > 0 ? ", " : "").Append("[")
                .Append(F(uvs[i].x)).Append(", ").Append(F(uvs[i].y)).Append("]");
        b.Append("], \"triangles\": [");
        for (int i = 0; i < tris.Length; i++)
            b.Append(i > 0 ? ", " : "").Append(tris[i]);
        b.Append("]");
        return b.ToString();
    }

    private static string MeshJson(Mesh mesh)
    {
        StringBuilder b = new StringBuilder();
        b.Append("{").Append(MeshFieldsJson(mesh)).Append("}");
        return b.ToString();
    }

    private static string WeightsJson(Mesh mesh)
    {
        if (mesh == null || mesh.boneWeights == null)
            return "[]";
        BoneWeight[] ws = mesh.boneWeights;
        StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < ws.Length; i++)
        {
            if (i > 0) b.Append(", ");
            BoneWeight w = ws[i];
            b.Append("{\"i\": [").Append(w.boneIndex0).Append(",")
                .Append(w.boneIndex1).Append(",").Append(w.boneIndex2)
                .Append(",").Append(w.boneIndex3).Append("], \"w\": [")
                .Append(F(w.weight0)).Append(",").Append(F(w.weight1))
                .Append(",").Append(F(w.weight2)).Append(",")
                .Append(F(w.weight3)).Append("]}");
        }
        b.Append("]");
        return b.ToString();
    }

    private static Vector4 RectOf(Sprite s)
    {
        return new Vector4(s.rect.x, s.rect.y, s.rect.width, s.rect.height);
    }

    private static string V3(Vector3 v)
    {
        return "[" + F(v.x) + ", " + F(v.y) + ", " + F(v.z) + "]";
    }

    private static string V4(Vector4 v)
    {
        return "[" + F(v.x) + ", " + F(v.y) + ", " + F(v.z) + ", " +
               F(v.w) + "]";
    }

    private static string V3List(List<Vector3> vs)
    {
        StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < vs.Count; i++)
            b.Append(i > 0 ? ", " : "").Append(V3(vs[i]));
        b.Append("]");
        return b.ToString();
    }

    private static string Q(Quaternion q)
    {
        return "[" + F(q.x) + ", " + F(q.y) + ", " + F(q.z) + ", " +
               F(q.w) + "]";
    }

    private static string Mat4(Matrix4x4 m)
    {
        StringBuilder b = new StringBuilder("[");
        for (int r = 0; r < 4; r++)
        {
            if (r > 0) b.Append(", ");
            b.Append("[");
            for (int c = 0; c < 4; c++)
                b.Append(c > 0 ? ", " : "").Append(F(m[r, c]));
            b.Append("]");
        }
        b.Append("]");
        return b.ToString();
    }

    private static string F(float v)
    {
        return v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
    }

    private static string Escape(string s)
    {
        return (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");
    }
}
