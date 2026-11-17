// ExportSelectedInfo.cs
// 把"选中对象"的渲染器信息导成 JSON，用于和离线解析（prefab/mesh 文本）对照。
//
// 重点输出 Unity 侧的**实际值**，这些从磁盘文本里推不出来：
//   · SkinnedMeshRenderer.bounds / localBounds —— Unity 自己算的包围盒
//   · BakeMesh 后的顶点数与范围 —— Unity 真正拿去渲染的顶点
//   · bones / rootBone / bindposes / boneWeights 的实际数量与前几个值
//   · transform 的位置、缩放、局部到世界矩阵
//
// 用法：Hierarchy 里选中目标，点菜单
//   Tools/2DModel/校准数据/导出选中对象的渲染器信息
// 输出：D:\VB\Unity2Spine\info\Data\SelectedInfo\<对象名>.json

using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

public static class ExportSelectedInfo
{
    private const string OutDir = "SelectedInfo";

    [MenuItem("Tools/2DModel/校准数据/导出选中对象的渲染器信息")]
    public static void Export()
    {
        GameObject go = Selection.activeGameObject;
        if (go == null)
        {
            Debug.LogError("[Info] 请先在 Hierarchy 里选中一个对象");
            return;
        }
        // 统一导出根：D:\VB\Unity2Spine\info\Data\SelectedInfo
        string dir = ExportRoots.Of("Data", OutDir);
        Directory.CreateDirectory(dir);
        string path = Path.Combine(dir, Sanitize(go.name) + ".json");
        File.WriteAllText(path, Build(go), new UTF8Encoding(false));
        AssetDatabase.Refresh();
        Debug.Log("[Info] 已写出 " + path);
    }

    private static string Build(GameObject root)
    {
        List<string> L = new List<string>();
        L.Add("{");
        L.Add("  \"root\": " + Str(root.name) + ",");
        L.Add("  \"activeInHierarchy\": " + Bool(root.activeInHierarchy) + ",");
        L.Add("  \"transform\": " + TransformJson(root.transform) + ",");

        List<SkinnedMeshRenderer> skinned = new List<SkinnedMeshRenderer>(
            root.GetComponentsInChildren<SkinnedMeshRenderer>(true));
        L.Add("  \"skinnedCount\": " + skinned.Count + ",");
        L.Add("  \"skinned\": [");
        for (int i = 0; i < skinned.Count; i++)
        {
            string tail = (i == skinned.Count - 1) ? "" : ",";
            L.Add(SkinnedJson(skinned[i]) + tail);
        }
        L.Add("  ],");

        List<SpriteRenderer> sprites = new List<SpriteRenderer>(
            root.GetComponentsInChildren<SpriteRenderer>(true));
        L.Add("  \"spriteCount\": " + sprites.Count + ",");
        L.Add("  \"sprites\": [");
        for (int i = 0; i < sprites.Count; i++)
        {
            SpriteRenderer sr = sprites[i];
            string tail = (i == sprites.Count - 1) ? "" : ",";
            L.Add("    " + SpriteJson(sr) + tail);
        }
        L.Add("  ]");
        L.Add("}");
        return string.Join("\n", L) + "\n";
    }

    private static string SkinnedJson(SkinnedMeshRenderer smr)
    {
        List<string> L = new List<string>();
        L.Add("    {");
        L.Add("      \"path\": " + Str(PathOf(smr.transform)) + ",");
        L.Add("      \"enabled\": " + Bool(smr.enabled) + ",");
        L.Add("      \"activeInHierarchy\": "
              + Bool(smr.gameObject.activeInHierarchy) + ",");
        L.Add("      \"transform\": " + TransformJson(smr.transform) + ",");
        L.Add("      \"bounds\": " + BoundsJson(smr.bounds) + ",");
        L.Add("      \"localBounds\": " + BoundsJson(smr.localBounds) + ",");
        L.Add("      \"localToWorld\": "
              + Mat4(smr.transform.localToWorldMatrix) + ",");
        L.Add("      \"updateWhenOffscreen\": "
              + Bool(smr.updateWhenOffscreen) + ",");
        L.Add("      \"rootBone\": "
              + (smr.rootBone == null
                 ? "null" : Str(PathOf(smr.rootBone))) + ",");
        L.Add("      \"boneCount\": "
              + (smr.bones == null ? 0 : smr.bones.Length) + ",");
        L.Add("      \"bones\": " + BoneListJson(smr.bones) + ",");
        // 全量 bindposes（网格自带的绑定姿态）——离线侧要判断
        // “bindpose 数与 m_Bones 数不一致”时到底谁对，必须看全量。
        L.Add("      \"bindposes\": "
              + BindposesJson(smr.sharedMesh) + ",");
        // 全量 boneWeights（每顶点 4 组 索引+权重），最多写 512 个顶点。
        L.Add("      \"boneWeights\": "
              + AllWeightsJson(smr.sharedMesh) + ",");
        L.Add("      \"mesh\": " + MeshJson(smr.sharedMesh) + ",");
        L.Add("      \"baked\": " + BakedJson(smr));
        L.Add("    }");
        return string.Join("\n", L);
    }

    private static string SpriteJson(SpriteRenderer sr)
    {
        List<string> L = new List<string>();
        L.Add("{");
        L.Add("      \"path\": " + Str(PathOf(sr.transform)) + ",");
        L.Add("      \"enabled\": " + Bool(sr.enabled) + ",");
        L.Add("      \"bounds\": " + BoundsJson(sr.bounds) + ",");
        L.Add("      \"sprite\": "
              + (sr.sprite == null ? "null" : Str(sr.sprite.name))
              + ",");
        L.Add("      \"pixelsPerUnit\": "
              + (sr.sprite == null ? "0" : F(sr.sprite.pixelsPerUnit)));
        L.Add("    }");
        return string.Join("\n", L);
    }

    private static string MeshJson(Mesh mesh)
    {
        if (mesh == null)
            return "null";
        List<string> L = new List<string>();
        L.Add("{");
        L.Add("        \"name\": " + Str(mesh.name) + ",");
        L.Add("        \"vertexCount\": " + mesh.vertexCount + ",");
        L.Add("        \"bounds\": " + BoundsJson(mesh.bounds) + ",");
        L.Add("        \"bindposeCount\": "
              + (mesh.bindposes == null ? 0 : mesh.bindposes.Length) + ",");
        L.Add("        \"boneWeightCount\": "
              + (mesh.boneWeights == null ? 0 : mesh.boneWeights.Length) + ",");
        L.Add("        \"firstBoneWeights\": "
              + FirstWeightsJson(mesh.boneWeights) + ",");
        L.Add("        \"isReadable\": " + Bool(mesh.isReadable));
        L.Add("      }");
        return string.Join("\n", L);
    }

    private static string FirstWeightsJson(BoneWeight[] ws)
    {
        if (ws == null || ws.Length == 0)
            return "[]";
        int n = Mathf.Min(4, ws.Length);
        List<string> L = new List<string>();
        for (int i = 0; i < n; i++)
        {
            BoneWeight w = ws[i];
            L.Add(WeightJson(w));
        }
        return "[" + string.Join(", ", L) + "]";
    }

    /// <summary>一条 BoneWeight 的合法 JSON：{"i":[4 个索引],"w":[4 个权重]}。
    /// 旧写法用 "0,1,0,0|1,0,0,0" 那种带竖线的字符串，整个文件不是合法 JSON。</summary>
    private static string WeightJson(BoneWeight w)
    {
        return "{\"i\": [" + w.boneIndex0 + ", " + w.boneIndex1 + ", "
             + w.boneIndex2 + ", " + w.boneIndex3 + "], \"w\": ["
             + F(w.weight0) + ", " + F(w.weight1) + ", "
             + F(w.weight2) + ", " + F(w.weight3) + "]}";
    }

    private static string BoneListJson(Transform[] bones)
    {
        if (bones == null || bones.Length == 0)
            return "[]";
        List<string> L = new List<string>();
        for (int i = 0; i < bones.Length; i++)
            L.Add(bones[i] == null ? "null" : Str(PathOf(bones[i])));
        return "[" + string.Join(", ", L) + "]";
    }

    /// <summary>网格自带的全部 bindposes（每根骨 4x4，16 个数一列）。</summary>
    private static string BindposesJson(Mesh mesh)
    {
        if (mesh == null || mesh.bindposes == null || mesh.bindposes.Length == 0)
            return "[]";
        List<string> L = new List<string>();
        foreach (Matrix4x4 m in mesh.bindposes) L.Add(Mat4(m));
        return "[" + string.Join(", ", L) + "]";
    }

    /// <summary>全量 per-vertex BoneWeight（最多 512 个顶点，避免 JSON 过大）。</summary>
    private static string AllWeightsJson(Mesh mesh)
    {
        if (mesh == null)
            return "[]";
        BoneWeight[] ws = mesh.boneWeights;
        if (ws == null || ws.Length == 0)
            return "[]";
        int n = Mathf.Min(512, ws.Length);
        List<string> L = new List<string>();
        for (int i = 0; i < n; i++)
        {
            BoneWeight w = ws[i];
            L.Add(WeightJson(w));
        }
        return "[" + string.Join(", ", L) + "]";
    }

    /// <summary>BakeMesh：Unity 真正渲染用的顶点（当前姿态、局部空间）。</summary>
    private static string BakedJson(SkinnedMeshRenderer smr)
    {
        try
        {
            Mesh baked = new Mesh();
            smr.BakeMesh(baked, true);
            Vector3[] vs = baked.vertices;
            string json;
            if (vs.Length == 0)
            {
                json = "{\"vertexCount\": 0}";
            }
            else
            {
                Vector3 mn = vs[0];
                Vector3 mx = vs[0];
                for (int i = 1; i < vs.Length; i++)
                {
                    mn = Vector3.Min(mn, vs[i]);
                    mx = Vector3.Max(mx, vs[i]);
                }
                List<string> first = new List<string>();
                int n = Mathf.Min(4, vs.Length);
                for (int i = 0; i < n; i++)
                    first.Add(V3(vs[i]));
                json = "{\"vertexCount\": " + vs.Length
                    + ", \"min\": " + V3(mn)
                    + ", \"max\": " + V3(mx)
                    + ", \"first\": [" + string.Join(", ", first) + "]}";
            }
            Object.DestroyImmediate(baked);
            return json;
        }
        catch (System.Exception ex)
        {
            return "{\"error\": " + Str(ex.Message) + "}";
        }
    }

    private static string TransformJson(Transform t)
    {
        return "{\"name\": " + Str(t.name)
            + ", \"localPosition\": " + V3(t.localPosition)
            + ", \"localScale\": " + V3(t.localScale)
            + ", \"lossyScale\": " + V3(t.lossyScale)
            + ", \"worldPosition\": " + V3(t.position) + "}";
    }

    private static string BoundsJson(Bounds b)
    {
        return "{\"center\": " + V3(b.center)
            + ", \"size\": " + V3(b.size)
            + ", \"extents\": " + V3(b.extents) + "}";
    }

    private static string PathOf(Transform t)
    {
        string p = t.name;
        Transform cur = t.parent;
        int guard = 0;
        while (cur != null && guard++ < 64)
        {
            p = cur.name + "/" + p;
            cur = cur.parent;
        }
        return p;
    }

    private static string V3(Vector3 v)
    {
        return "[" + F(v.x) + ", " + F(v.y) + ", " + F(v.z) + "]";
    }

    private static string Mat4(Matrix4x4 m)
    {
        List<string> rows = new List<string>();
        for (int r = 0; r < 4; r++)
        {
            rows.Add("[" + F(m[r, 0]) + ", " + F(m[r, 1]) + ", "
                     + F(m[r, 2]) + ", " + F(m[r, 3]) + "]");
        }
        return "[" + string.Join(", ", rows) + "]";
    }

    private static string Bool(bool v)
    {
        return v ? "true" : "false";
    }

    private static string Str(string s)
    {
        return "\"" + (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"")
            + "\"";
    }

    private static string F(float v)
    {
        return v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
    }

    private static string Sanitize(string name)
    {
        foreach (char c in Path.GetInvalidFileNameChars())
            name = name.Replace(c, '_');
        return name.Replace('/', '_').Replace('\\', '_').Trim();
    }
}
