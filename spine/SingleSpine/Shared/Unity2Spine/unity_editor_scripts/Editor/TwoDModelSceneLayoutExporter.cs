// TwoDModelSceneLayoutExporter.cs
// 导出 save 场景里三个角色实例的“布局信息”：主相机参数、每棵直接子树的
// 世界包围盒、每个 Renderer 的可见几何与相机屏幕矩形，用来判断哪些子树
// 才是画面里真正显示的“人物动画层/静态图”。
//
// 运行：
//   Unity.exe -batchmode -nographics -projectPath <工程> -quit \
//     -executeMethod TwoDModelSceneLayoutExporter.Export
// 输出：D:\VB\Unity2Spine\info\Data\SceneLayout\<名称>_layout.json

using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class TwoDModelSceneLayoutExporter
{
    [MenuItem("Tools/2DModel/Export Scene Layout")]
    public static void Export()
    {
        // 统一导出根：D:\VB\Unity2Spine\info\Data\SceneLayout
        string outDir = ExportRoots.Data("SceneLayout");
        Directory.CreateDirectory(outDir);
        EditorSceneManager.OpenScene("Assets/Scenes/save.unity",
                                     OpenSceneMode.Single);
        Camera cam = Camera.main;
        // 逐个角色：激活（场景里通常是 disabled）-> 取布局 -> 恢复
        CalibTargets.ForEach(TwoDModelCalibExport.Names, root =>
        {
            string json = Build(root, cam);
            File.WriteAllText(Path.Combine(outDir, root.name + "_layout.json"),
                              json, new UTF8Encoding(false));
            Debug.Log("[TwoDModelSceneLayoutExporter] 写出 " + root.name + "_layout.json");
        });
        AssetDatabase.Refresh();
        if (Application.isBatchMode)
            EditorApplication.Exit(0);
    }

    private static string Build(GameObject root, Camera cam)
    {
        StringBuilder b = new StringBuilder();
        b.Append("{\n  \"root\": \"").Append(Escape(root.name)).Append("\",\n");
        b.Append("  \"camera\": ").Append(cam == null ? "{}" : CameraJson(cam)).Append(",\n");
        b.Append("  \"children\": [\n");
        bool first = true;
        foreach (Transform child in root.transform)
        {
            b.Append(first ? "    " : "    ,").Append(SubtreeJson(child, cam)).Append("\n");
            first = false;
        }
        b.Append("  ]\n}\n");
        return b.ToString();
    }

    private static string CameraJson(Camera cam)
    {
        return "{\"name\": \"" + Escape(cam.name) + "\", \"pos\": " + V3(cam.transform.position)
               + ", \"rot\": " + Q(cam.transform.rotation) + ", \"ortho\": "
               + (cam.orthographic ? "true" : "false") + ", \"orthoSize\": "
               + F(cam.orthographicSize) + ", \"fov\": " + F(cam.fieldOfView)
               + ", \"near\": " + F(cam.nearClipPlane) + ", \"far\": " + F(cam.farClipPlane)
               + ", \"aspect\": " + F(cam.aspect) + "}";
    }

    private static string SubtreeJson(Transform child, Camera cam)
    {
        Renderer[] renderers = child.GetComponentsInChildren<Renderer>(true);
        StringBuilder b = new StringBuilder();
        b.Append("{\"name\": \"").Append(Escape(child.name)).Append("\",\n");
        b.Append("      \"path\": \"").Append(Escape(PathOf(child))).Append("\",\n");
        b.Append("      \"worldPos\": ").Append(V3(child.position)).Append(",\n");
        b.Append("      \"worldMatrix\": ").Append(Mat4(child.localToWorldMatrix)).Append(",\n");
        Bounds u = new Bounds(child.position, Vector3.zero);
        bool has = false;
        foreach (Renderer r in renderers)
        {
            if (has)
                u.Encapsulate(r.bounds);
            else
            {
                u = r.bounds;
                has = true;
            }
        }
        if (has)
        {
            b.Append("      \"worldBounds\": [").Append(F(u.min.x)).Append(", ")
                .Append(F(u.min.y)).Append(", ").Append(F(u.max.x)).Append(", ")
                .Append(F(u.max.y)).Append("],\n");
        }
        b.Append("      \"renderers\": [\n");
        bool f = true;
        foreach (Renderer r in renderers)
        {
            if (!f)
                b.Append(",\n");
            f = false;
            b.Append("        ").Append(RendererJson(r, cam));
        }
        b.Append("\n      ]\n    }");
        return b.ToString();
    }

    private static string RendererJson(Renderer r, Camera cam)
    {
        StringBuilder b = new StringBuilder();
        b.Append("{\"type\": \"").Append(ClassOf(r)).Append("\", \"path\": \"")
            .Append(Escape(PathOf(r.transform))).Append("\", \"bounds\": [")
            .Append(F(r.bounds.min.x)).Append(", ").Append(F(r.bounds.min.y)).Append(", ")
            .Append(F(r.bounds.max.x)).Append(", ").Append(F(r.bounds.max.y)).Append("]");
        if (cam != null)
        {
            Vector3[] c = Corners(r.bounds);
            Vector2 min = new Vector2(1e9f, 1e9f);
            Vector2 max = new Vector2(-1e9f, -1e9f);
            bool any = false;
            foreach (Vector3 p in c)
            {
                Vector3 sp = cam.WorldToScreenPoint(p);
                if (sp.z < 0)
                    continue;
                any = true;
                min = Vector2.Min(min, sp);
                max = Vector2.Max(max, sp);
            }
            if (any)
                b.Append(", \"screenRect\": [").Append(F(min.x)).Append(", ")
                    .Append(F(Screen.height - max.y)).Append(", ").Append(F(max.x - min.x))
                    .Append(", ").Append(F(max.y - min.y)).Append("]");
        }
        b.Append("}");
        return b.ToString();
    }

    private static string ClassOf(Renderer r)
    {
        if (r is SkinnedMeshRenderer)
            return "skinned";
        if (r is SpriteRenderer)
            return "sprite";
        return "mesh";
    }

    private static Vector3[] Corners(Bounds bounds)
    {
        Vector3 c = bounds.center;
        Vector3 e = bounds.extents;
        return new[]
        {
            c + new Vector3(-e.x, -e.y, -e.z), c + new Vector3(e.x, -e.y, -e.z),
            c + new Vector3(e.x, e.y, -e.z), c + new Vector3(-e.x, e.y, -e.z),
            c + new Vector3(-e.x, -e.y, e.z), c + new Vector3(e.x, -e.y, e.z),
            c + new Vector3(e.x, e.y, e.z), c + new Vector3(-e.x, e.y, e.z),
        };
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
