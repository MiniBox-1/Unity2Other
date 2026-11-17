// TwoDModelDebugExporter.cs
// 用法：
//   1) 把本脚本挂到 NormalLocal 2DModel prefab 的根节点（带 Animator 的
//      ch_root 或 prefab 根，取决于你要导出的层级）。
//   2) 在 Inspector 填 animState（如 lobby）与 normalizedTime（0~1）。
//   3) 进入 Play Mode，脚本会播到该状态/时刻，烘焙所有 SkinnedMeshRenderer，
//      并把 JSON 写到 D:\VB\Unity2Spine\info\RigDebug\ 下（Console 也会打印路径）。
//
// 用途：和 D:\VB\Unity2Spine 的 2DModel -> Spine 离线转换结果做逐点/逐层比对。
//
// 无需第三方 JSON 库，输出兼容 UTF-8 的 JSON 文本。

using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

public class TwoDModelDebugExporter : MonoBehaviour
{
    [Tooltip("启动后自动导出一次（推荐 true）")]
    public bool exportOnStart = true;

    [Tooltip("Animator 状态名；留空则导出现有姿势，不主动播放")]
    public string animState = "lobby";

    [Tooltip("0=状态首帧，1=状态末帧")]
    [Range(0f, 1f)]
    public float normalizedTime = 0f;

    [Tooltip("烘焙 SkinnedMeshRenderer 前的等待帧数（让动画真正求值）")]
    public int settleFrames = 5;

    [Tooltip("输出目录；留空 = D:\\VB\\Unity2Spine\\info\\RigDebug")]
    public string outputDirectory = "";

    [Tooltip("每次输出是否打印到 Unity Console")]
    public bool logToConsole = true;

    [Tooltip("启用按 Animator 逐帧密集导出（供帧烘焙转换器使用）")]
    public bool exportPoseFrames = true;

    [Tooltip("逐帧采样步长（秒）")]
    public float frameStep = 0.05f;

    [Tooltip("单角色最大帧数保护")]
    public int frameLimit = 600;

    [Tooltip("输出文件用场景根 GameObject 命名（避免 ch_root 互相覆盖）")]
    public bool useRootObjectName = true;

    private void OnEnable()
    {
        // 探针（AedaProbeRuntime）会话中自动让路，避免两套协程抢动画
        if (GameObject.Find("AedaProbeRuntime") != null)
            return;
        if (exportOnStart && exportPoseFrames)
            StartCoroutine(ExportPoseFramesWhenReady());
        else if (exportOnStart)
            StartCoroutine(ExportWhenReady());
    }

    private IEnumerator ExportPoseFramesWhenReady()
    {
        yield return null;
        Animator animator = GetComponentInChildren<Animator>();
        string clipName = animState;
        float duration = 1f;
        if (animator != null && animator.runtimeAnimatorController != null)
        {
            var clips = animator.runtimeAnimatorController.animationClips;
            if (clips != null && clips.Length > 0)
            {
                if (string.IsNullOrEmpty(clipName))
                    clipName = clips[0].name;
                foreach (var c in clips)
                    if (c.name == clipName)
                        duration = c.length;
                if (duration == 1f)
                {
                    foreach (var c in clips)
                    {
                        if (c.name.Contains(animState) || animState.Contains(c.name))
                        {
                            clipName = c.name;
                            duration = c.length;
                            break;
                        }
                    }
                }
            }
        }
        if (string.IsNullOrEmpty(clipName))
            clipName = "";

        int count = Mathf.CeilToInt(duration / Mathf.Max(0.001f, frameStep)) + 1;
        if (count > frameLimit)
            count = frameLimit;

        StringBuilder sb = new StringBuilder();
        sb.Append("{\n  \"prefab\": \"").Append(Escape(gameObject.name)).Append("\",\n");
        sb.Append("  \"clip\": \"").Append(Escape(clipName)).Append("\",\n");
        sb.Append("  \"duration\": ").Append(F(duration)).Append(",\n");
        sb.Append("  \"frames\": [\n");

        for (int i = 0; i < count; i++)
        {
            float t = Mathf.Min(duration, i * frameStep);
            if (animator != null)
            {
                string playState = string.IsNullOrEmpty(animState) ? clipName : animState;
                if (!string.IsNullOrEmpty(playState))
                    animator.Play(playState, 0, duration > 0f ? t / duration : 0f);
            }
            yield return null;
            yield return null;
            sb.Append(i == 0 ? "    " : "    ,")
              .Append(FrameJson(animator, t)).Append("\n");
        }
        sb.Append("  ]\n}\n");

        string dir = string.IsNullOrEmpty(outputDirectory)
            ? ExportRoots.Data("PoseFrames")
            : Path.Combine(outputDirectory, "PoseFrames");
        Directory.CreateDirectory(dir);
        string fileName = useRootObjectName && transform.root != null
            ? transform.root.name : name;
        string path = Path.Combine(dir, fileName + ".json");
        File.WriteAllText(path, sb.ToString(), Encoding.UTF8);
        if (logToConsole)
            Debug.Log("[TwoDModelDebugExporter] 密集帧已写出 " + path);
    }

    private string FrameJson(Animator animator, float time)
    {
        StringBuilder b = new StringBuilder();
        b.Append("{\"time\": ").Append(F(time)).Append(",\n");
        List<Transform> all = new List<Transform> { transform };
        all.AddRange(GetComponentsInChildren<Transform>(true));
        b.Append("  \"transforms\": [");
        for (int i = 0; i < all.Count; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append(TransformJson(all[i]));
        }
        b.Append("],\n  \"renderers\": [");
        bool first = true;
        foreach (var smr in GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (!smr.gameObject.activeInHierarchy || !smr.enabled)
                continue;
            if (!first)
                b.Append(",\n");
            first = false;
            b.Append("    ").Append(SkinnedMeshJson(smr));
        }
        foreach (var sr in GetComponentsInChildren<SpriteRenderer>(true))
        {
            if (!sr.gameObject.activeInHierarchy || !sr.enabled)
                continue;
            if (!first)
                b.Append(",\n");
            first = false;
            b.Append("    ").Append(SpriteJson(sr));
        }
        foreach (var mf in GetComponentsInChildren<MeshFilter>(true))
        {
            MeshRenderer mr0 = mf.GetComponent<MeshRenderer>();
            if (mr0 == null || !mf.gameObject.activeInHierarchy || !mr0.enabled)
                continue;
            if (!first)
                b.Append(",\n");
            first = false;
            b.Append("    {\"kind\": \"static\", \"path\": \"")
                .Append(Escape(PathOf(mf.transform))).Append("\", \"gameObject\": \"")
                .Append(Escape(mf.name)).Append("\", \"vertexCount\": ")
                .Append(mf.sharedMesh == null ? 0 : mf.sharedMesh.vertexCount)
                .Append(", \"localToWorld\": ")
                .Append(Mat4(mf.transform.localToWorldMatrix)).Append("}");
        }
        b.Append("\n  ]}");
        return b.ToString();
    }

    public IEnumerator ExportWhenReady()
    {
        yield return null;

        // 先尝试播放指定动画状态到指定时间
        var animator = GetComponentInChildren<Animator>();
        if (animator != null && !string.IsNullOrEmpty(animState))
        {
            try
            {
                animator.Play(animState, 0, normalizedTime);
            }
            catch
            {
                // 状态名不存在时保持现状
                Debug.LogWarning("[TwoDModelDebugExporter] 找不到动画状态: " + animState);
            }
        }

        for (int i = 0; i < settleFrames; i++)
            yield return null;

        ExportNow();
    }

    [ContextMenu("Export JSON Now")]
    public void ExportNow()
    {
        StringBuilder sb = new StringBuilder();
        sb.Append("{\n");
        sb.Append("  \"prefab\": \"").Append(Escape(gameObject.name)).Append("\",\n");
        sb.Append("  \"exportTime\": \"").Append(System.DateTime.Now.ToString("s")).Append("\",\n");

        var animator = GetComponentInChildren<Animator>();
        sb.Append("  \"animatorState\": ").Append(AnimatorStateJson(animator)).Append(",\n");
        sb.Append("  \"transforms\": [\n");

        var allTransforms = new List<Transform>();
        allTransforms.Add(transform);
        allTransforms.AddRange(GetComponentsInChildren<Transform>(true));

        // 层级里完整导出每个 Transform
        for (int i = 0; i < allTransforms.Count; i++)
        {
            Transform t = allTransforms[i];
            sb.Append(i == 0 ? "    " : "    ,").Append(TransformJson(t)).Append("\n");
        }
        sb.Append("  ],\n");

        sb.Append("  \"renderers\": [\n");
        bool first = true;
        foreach (var smr in GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (!smr.gameObject.activeInHierarchy || !smr.enabled)
                continue;
            sb.Append(first ? "    " : "    ,").Append(SkinnedMeshJson(smr)).Append("\n");
            first = false;
        }
        foreach (var mf in GetComponentsInChildren<MeshFilter>(true))
        {
            MeshRenderer mr1 = mf.GetComponent<MeshRenderer>();
            if (mr1 == null || !mf.gameObject.activeInHierarchy || !mr1.enabled)
                continue;
            sb.Append(first ? "    " : "    ,").Append(MeshFilterJson(mf)).Append("\n");
            first = false;
        }
        foreach (var sr in GetComponentsInChildren<SpriteRenderer>(true))
        {
            if (!sr.gameObject.activeInHierarchy || !sr.enabled)
                continue;
            sb.Append(first ? "    " : "    ,").Append(SpriteJson(sr)).Append("\n");
            first = false;
        }
        sb.Append("  ]\n");
        sb.Append("}\n");

        string dir = string.IsNullOrEmpty(outputDirectory)
            ? ExportRoots.Of("RigDebug")
            : outputDirectory;
        Directory.CreateDirectory(dir);
        string path = Path.Combine(dir, name + "_" + System.DateTime.Now.ToString("HHmmss") + ".json");
        File.WriteAllText(path, sb.ToString(), Encoding.UTF8);
        if (logToConsole)
            Debug.Log("[TwoDModelDebugExporter] 已写出 " + path);
    }

    private static string AnimatorStateJson(Animator animator)
    {
        if (animator == null)
            return "{}";
        string state = "";
        float time = -1f;
        try
        {
            if (animator.IsInTransition(0))
                animator.Update(0f);
            AnimatorStateInfo info = animator.GetCurrentAnimatorStateInfo(0);
            state = animator.GetCurrentAnimatorClipInfo(0).Length > 0
                ? animator.GetCurrentAnimatorClipInfo(0)[0].clip.name
                : "";
            time = info.normalizedTime;
        }
        catch
        {
            // 忽略：没有 Animator 数据时输出空
        }
        return "{\"clip\": \"" + Escape(state) + "\", \"normalizedTime\": "
               + time.ToString("F4", System.Globalization.CultureInfo.InvariantCulture) + "}";
    }

    private static string TransformJson(Transform t)
    {
        StringBuilder b = new StringBuilder();
        b.Append("{\"path\": \"").Append(Escape(PathOf(t))).Append("\",\n");
        b.Append("      \"name\": \"").Append(Escape(t.name)).Append("\",\n");
        b.Append("      \"localPos\": ").Append(V3(t.localPosition)).Append(",\n");
        b.Append("      \"localRot\": ").Append(Q(t.localRotation)).Append(",\n");
        b.Append("      \"localEuler\": ").Append(V3(t.localEulerAngles)).Append(",\n");
        b.Append("      \"localScale\": ").Append(V3(t.localScale)).Append(",\n");
        b.Append("      \"worldPos\": ").Append(V3(t.position)).Append(",\n");
        b.Append("      \"worldRot\": ").Append(Q(t.rotation)).Append(",\n");
        b.Append("      \"worldScale\": ").Append(V3(t.lossyScale)).Append(",\n");
        b.Append("      \"worldMatrix\": ").Append(Mat4(t.localToWorldMatrix)).Append("}");
        return b.ToString();
    }

    private static string SkinnedMeshJson(SkinnedMeshRenderer smr)
    {
        StringBuilder b = new StringBuilder();
        Mesh mesh = smr.sharedMesh;
        b.Append("{\"kind\": \"skinned\",\n");
        b.Append("      \"path\": \"").Append(Escape(PathOf(smr.transform))).Append("\",\n");
        b.Append("      \"gameObject\": \"").Append(Escape(smr.name)).Append("\",\n");
        b.Append("      \"enabled\": ").Append(smr.enabled ? "true" : "false").Append(",\n");
        b.Append("      \"meshName\": \"").Append(Escape(mesh == null ? "" : mesh.name)).Append("\",\n");
        b.Append("      \"vertexCount\": ").Append(mesh == null ? 0 : mesh.vertexCount).Append(",\n");
        b.Append("      \"isReadable\": ").Append(mesh == null ? "false" :
            (mesh.isReadable ? "true" : "false")).Append(",\n");
        b.Append("      \"rootBone\": \"").Append(Escape(smr.rootBone ? PathOf(smr.rootBone) : "")).Append("\",\n");

        if (smr.bones != null && smr.bones.Length > 0)
        {
            b.Append("      \"bones\": [");
            for (int i = 0; i < smr.bones.Length; i++)
            {
                if (i > 0)
                    b.Append(", ");
                b.Append("\"").Append(Escape(smr.bones[i] ? PathOf(smr.bones[i]) : "null")).Append("\"");
            }
            b.Append("],\n");
        }
        else
        {
            b.Append("      \"bones\": [],\n");
        }

        b.Append("      \"bindposes\": [");
        if (mesh != null && mesh.isReadable)
        {
            try
            {
                Matrix4x4[] binds = mesh.bindposes;
                for (int i = 0; i < binds.Length; i++)
                {
                    if (i > 0)
                        b.Append(", ");
                    b.Append(Mat4(binds[i]));
                }
            }
            catch
            {
                b.Append("/* mesh not readable */");
            }
        }
        b.Append("],\n");

        // 可选：如果 Mesh 可读，直接导出骨权重；不可读则走 BakeMesh
        b.Append("      \"boneWeights\": ");
        b.Append(MeshWeightsJson(mesh));
        b.Append(",\n");

        b.Append("      \"baked\": ").Append(BakedMeshJson(smr)).Append(",\n");
        Material sm = smr.sharedMaterial;
        b.Append("      \"sortingOrder\": ").Append(smr.sortingOrder.ToString())
            .Append(",\n");
        b.Append("      \"renderQueue\": ")
            .Append(sm == null ? -1 : sm.renderQueue).Append(",\n");
        b.Append("      \"localToWorld\": ").Append(Mat4(smr.transform.localToWorldMatrix)).Append("}");
        return b.ToString();
    }

    private static string MeshWeightsJson(Mesh mesh)
    {
        if (mesh == null || !mesh.isReadable)
            return "[]";
        BoneWeight[] weights = mesh.boneWeights;
        StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < weights.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            BoneWeight w = weights[i];
            b.Append("{\"i\": [").Append(w.boneIndex0).Append(",").Append(w.boneIndex1)
                .Append(",").Append(w.boneIndex2).Append(",").Append(w.boneIndex3)
                .Append("], \"w\": [").Append(F(w.weight0)).Append(",").Append(F(w.weight1))
                .Append(",").Append(F(w.weight2)).Append(",").Append(F(w.weight3)).Append("]}");
        }
        b.Append("]");
        return b.ToString();
    }

    private static string BakedMeshJson(SkinnedMeshRenderer smr)
    {
        if (smr.sharedMesh == null)
            return "{}";
        try
        {
            Mesh baked = new Mesh();
            smr.BakeMesh(baked, true);
            return MeshDataJson(baked, smr.transform);
        }
        catch
        {
            return "{}";
        }
    }

    private static string MeshFilterJson(MeshFilter mf)
    {
        Mesh mesh = mf.sharedMesh;
        StringBuilder b = new StringBuilder();
        b.Append("{\"kind\": \"static\",\n");
        b.Append("      \"path\": \"").Append(Escape(PathOf(mf.transform))).Append("\",\n");
        b.Append("      \"gameObject\": \"").Append(Escape(mf.name)).Append("\",\n");
        b.Append("      \"meshName\": \"").Append(Escape(mesh == null ? "" : mesh.name)).Append("\",\n");
        b.Append("      \"vertexCount\": ").Append(mesh == null ? 0 : mesh.vertexCount).Append(",\n");
        MeshRenderer mr = mf.GetComponent<MeshRenderer>();
        Material sm2 = mr == null ? null : mr.sharedMaterial;
        b.Append("      \"sortingOrder\": ")
            .Append(mr == null ? 0 : mr.sortingOrder).Append(",\n");
        b.Append("      \"renderQueue\": ")
            .Append(sm2 == null ? -1 : sm2.renderQueue).Append(",\n");
        b.Append("      \"data\": ").Append(MeshDataJson(mesh, mf.transform)).Append(",\n");
        b.Append("      \"localToWorld\": ").Append(Mat4(mf.transform.localToWorldMatrix)).Append("}");
        return b.ToString();
    }

    private static string SpriteJson(SpriteRenderer sr)
    {
        Sprite sprite = sr.sprite;
        Texture2D tex = sprite != null ? sprite.texture : null;
        Vector3[] localC = SpriteLocalCorners(sr);
        Vector3[] worldC = new Vector3[localC.Length];
        for (int i = 0; i < localC.Length; i++)
            worldC[i] = sr.transform.TransformPoint(localC[i]);
        StringBuilder b = new StringBuilder();
        b.Append("{\"kind\": \"sprite\",\n");
        b.Append("      \"path\": \"").Append(Escape(PathOf(sr.transform))).Append("\",\n");
        b.Append("      \"gameObject\": \"").Append(Escape(sr.name)).Append("\",\n");
        b.Append("      \"enabled\": ").Append(sr.enabled ? "true" : "false").Append(",\n");
        b.Append("      \"spriteName\": \"").Append(Escape(sprite == null ? "" : sprite.name)).Append("\",\n");
        if (sprite != null)
        {
            b.Append("      \"rect\": [").Append(F(sprite.rect.x)).Append(", ")
                .Append(F(sprite.rect.y)).Append(", ").Append(F(sprite.rect.width))
                .Append(", ").Append(F(sprite.rect.height)).Append("],\n");
            b.Append("      \"pivot\": [").Append(F(sprite.pivot.x)).Append(", ")
                .Append(F(sprite.pivot.y)).Append("],\n");
            b.Append("      \"pixelsPerUnit\": ").Append(F(sprite.pixelsPerUnit)).Append(",\n");
            b.Append("      \"textureSize\": [").Append(tex == null ? 0 : tex.width)
                .Append(", ").Append(tex == null ? 0 : tex.height).Append("],\n");
        }
        else
        {
            b.Append("      \"rect\": [],\n      \"textureSize\": [0, 0],\n");
        }
        b.Append("      \"localCorners\": [");
        for (int i = 0; i < localC.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append("[").Append(F(localC[i].x)).Append(", ")
                .Append(F(localC[i].y)).Append(", ").Append(F(localC[i].z)).Append("]");
        }
        b.Append("],\n");
        b.Append("      \"worldCorners\": [");
        for (int i = 0; i < worldC.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append("[").Append(F(worldC[i].x)).Append(", ")
                .Append(F(worldC[i].y)).Append(", ").Append(F(worldC[i].z)).Append("]");
        }
        b.Append("],\n");
        Material sm3 = sr.sharedMaterial;
        b.Append("      \"sortingOrder\": ").Append(sr.sortingOrder.ToString())
            .Append(",\n");
        b.Append("      \"renderQueue\": ")
            .Append(sm3 == null ? -1 : sm3.renderQueue).Append(",\n");
        b.Append("      \"localToWorld\": ").Append(Mat4(sr.transform.localToWorldMatrix)).Append("}");
        return b.ToString();
    }

    private static Vector3[] SpriteLocalCorners(SpriteRenderer sr)
    {
        Sprite s = sr.sprite;
        if (s == null)
            return new Vector3[0];
        float w = s.rect.width / s.pixelsPerUnit;
        float h = s.rect.height / s.pixelsPerUnit;
        float l = -s.pivot.x / s.pixelsPerUnit;
        float b = -s.pivot.y / s.pixelsPerUnit;
        return new[]
        {
            new Vector3(l, b, 0f), new Vector3(l + w, b, 0f),
            new Vector3(l + w, b + h, 0f), new Vector3(l, b + h, 0f),
        };
    }

    private static string MeshDataJson(Mesh mesh, Transform space)
    {
        if (mesh == null)
            return "{}";
        if (!mesh.isReadable)
        {
            return "{\"vertexCount\": " + (mesh == null ? 0 : mesh.vertexCount)
                   + ", \"note\": \"mesh not readable, enable Read/Write or use baked data\"}";
        }
        Vector3[] verts = mesh.vertices;
        Vector2[] uv = mesh.uv;
        int[] tris = mesh.triangles;
        StringBuilder b = new StringBuilder();
        b.Append("{\"vertexCount\": ").Append(verts.Length).Append(",\n");
        b.Append("        \"positions\": [");
        for (int i = 0; i < verts.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append(V3(verts[i]));
        }
        b.Append("],\n");
        b.Append("        \"uvs\": [");
        for (int i = 0; i < uv.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append("[").Append(F(uv[i].x)).Append(", ").Append(F(uv[i].y)).Append("]");
        }
        b.Append("],\n");
        b.Append("        \"triangles\": [");
        for (int i = 0; i < tris.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append(tris[i].ToString());
        }
        b.Append("],\n");
        b.Append("        \"space\": \"").Append(Escape(space ? PathOf(space) : "")).Append("\"}");
        return b.ToString();
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

    private static string V3(Vector3 v)
    {
        return "[" + F(v.x) + ", " + F(v.y) + ", " + F(v.z) + "]";
    }

    private static string Q(Quaternion q)
    {
        return "[" + F(q.x) + ", " + F(q.y) + ", " + F(q.z) + ", " + F(q.w) + "]";
    }

    private static string Mat4(Matrix4x4 m)
    {
        StringBuilder b = new StringBuilder("[");
        for (int r = 0; r < 4; r++)
        {
            if (r > 0)
                b.Append(", ");
            b.Append("[");
            for (int c = 0; c < 4; c++)
            {
                if (c > 0)
                    b.Append(", ");
                b.Append(F(m[r, c]));
            }
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
        if (string.IsNullOrEmpty(s))
            return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"")
                .Replace("\n", "\\n").Replace("\r", "\\r");
    }
}
