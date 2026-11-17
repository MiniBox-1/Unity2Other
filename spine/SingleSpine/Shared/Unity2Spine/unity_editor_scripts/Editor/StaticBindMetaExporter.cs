// StaticBindMetaExporter.cs
// 静态绑定元数据导出（不进 Play、不采样动画、不读动态帧）：
// 从 prefab 实例的 SkinnedMeshRenderer/sharedMesh 导出姿态无关的
// 局部顶点/uv/三角形、bindposes、boneWeights、骨骼路径与排序。
// 静态 prefab -> Spine 路线用它替代不稳定的 mesh 二进制流解析。
//
// 运行：Tools/2DModel/Export Static Bind Meta（编辑器）
// 输出：D:\VB\Unity2Spine\info\Data\StaticMeta\<角色>.json
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class StaticBindMetaExporter
{
    [MenuItem("Tools/2DModel/Export Static Bind Meta")]
    public static void Export()
    {
        // 统一导出根：D:\VB\Unity2Spine\info\Data\StaticMeta
        string outDir = ExportRoots.Data("StaticMeta");
        Directory.CreateDirectory(outDir);
        EditorSceneManager.OpenScene("Assets/Scenes/save.unity",
                                     OpenSceneMode.Single);
        // 逐个角色：激活（场景里通常是 disabled）-> 取绑定元数据 -> 恢复
        CalibTargets.ForEach(TwoDModelCalibExport.Names, root =>
        {
            string json = Build(root);
            File.WriteAllText(Path.Combine(outDir, root.name + ".json"),
                              json, new UTF8Encoding(false));
            Debug.Log("[StaticBindMeta] " + root.name);
        });
        AssetDatabase.Refresh();
        if (Application.isBatchMode)
            EditorApplication.Exit(0);
    }

    private static string Build(GameObject root)
    {
        StringBuilder b = new StringBuilder();
        b.Append("{\n  \"root\": \"").Append(Escape(root.name)).Append("\",\n");
        b.Append("  \"renderers\": [");
        bool first = true;
        foreach (SkinnedMeshRenderer smr in
                 root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            Mesh mesh = smr.sharedMesh;
            if (mesh == null)
                continue;
            if (!first)
                b.Append(",\n");
            first = false;
            b.Append("    {\"kind\": \"skinned\",\n");
            b.Append("      \"path\": \"").Append(Escape(PathOf(smr.transform))).Append("\",\n");
            b.Append("      \"sortingOrder\": ").Append(smr.sortingOrder).Append(",\n");
            b.Append("      \"bones\": [");
            if (smr.bones != null)
            {
                for (int i = 0; i < smr.bones.Length; i++)
                {
                    if (i > 0)
                        b.Append(", ");
                    b.Append("\"").Append(Escape(
                        smr.bones[i] ? PathOf(smr.bones[i]) : "null")).Append("\"");
                }
            }
            b.Append("],\n");
            b.Append("      \"bindposes\": [");
            Matrix4x4[] binds = mesh.bindposes;
            for (int i = 0; i < binds.Length; i++)
            {
                if (i > 0)
                    b.Append(", ");
                b.Append(Mat4(binds[i]));
            }
            b.Append("],\n");
            b.Append("      \"boneWeights\": ");
            b.Append(WeightsJson(mesh));
            b.Append(",\n");
            b.Append("      \"mesh\": ").Append(MeshJson(mesh)).Append("}");
        }
        b.Append("\n  ]\n}\n");
        return b.ToString();
    }

    private static string WeightsJson(Mesh mesh)
    {
        BoneWeight[] ws = mesh.boneWeights;
        StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < ws.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            BoneWeight w = ws[i];
            b.Append("{\"i\": [").Append(w.boneIndex0).Append(",")
                .Append(w.boneIndex1).Append(",").Append(w.boneIndex2)
                .Append(",").Append(w.boneIndex3).Append("], \"w\": [")
                .Append(F(w.weight0)).Append(",").Append(F(w.weight1)).Append(",")
                .Append(F(w.weight2)).Append(",").Append(F(w.weight3)).Append("]}");
        }
        b.Append("]");
        return b.ToString();
    }

    private static string MeshJson(Mesh mesh)
    {
        if (!mesh.isReadable)
            return "{\"vertexCount\": " + mesh.vertexCount +
                   ", \"note\": \"mesh not readable\"}";
        Vector3[] verts = mesh.vertices;
        Vector2[] uv = mesh.uv;
        int[] tris = mesh.triangles;
        StringBuilder b = new StringBuilder();
        b.Append("{\"vertexCount\": ").Append(verts.Length)
            .Append(", \"positions\": [");
        for (int i = 0; i < verts.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append(V3(verts[i]));
        }
        b.Append("], \"uvs\": [");
        for (int i = 0; i < uv.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append("[").Append(F(uv[i].x)).Append(", ")
                .Append(F(uv[i].y)).Append("]");
        }
        b.Append("], \"triangles\": [");
        for (int i = 0; i < tris.Length; i++)
        {
            if (i > 0)
                b.Append(", ");
            b.Append(tris[i].ToString());
        }
        b.Append("]}");
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
