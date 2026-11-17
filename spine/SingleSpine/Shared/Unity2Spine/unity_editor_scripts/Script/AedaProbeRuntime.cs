// AedaProbeRuntime.cs
// Play Mode 运行态探针：进入 Play 后把角色动画冻结在默认状态首帧附近，
// 然后逐组开关 Renderer（sprite/skinned/mesh/particle/other），每次用
// 同一正交相机渲染到 RenderTexture 并输出 PNG，最后写 done.txt 通知编辑器。
//
// 由 ProbeAedaRenderers.Export（Assets/Editor）自动挂载并进入 Play Mode；
// 也可手动挂到任意 GameObject 上运行（rootName 填目标角色场景根名）。

using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

public class AedaProbeRuntime : MonoBehaviour
{
    [Tooltip("要探测的场景根 GameObject 名（如 aeda_normal）")]
    public string rootName = "aeda_normal";

    private class Entry
    {
        public Renderer renderer;
        public string group;
        public string path;
        public bool originalEnabled;
    }

    private string _outDir;
    private GameObject _root;
    private List<Entry> _entries = new List<Entry>();
    private List<string> _groups = new List<string>();

    private static readonly string[] GroupRank =
    {
        "sprite", "skinned", "mesh", "particle", "other",
    };

    private IEnumerator Start()
    {
        // 等 Play Mode 真正开始、场景对象就绪
        yield return null;

        // 统一导出根：D:\VB\Unity2Spine\info\Data\Frames\probe（见 Assets\Script\ExportRoots.cs）
        _outDir = ExportRoots.Of("Data", "Frames", "probe");
        Directory.CreateDirectory(_outDir);

        _root = FindRoot();
        if (_root == null)
        {
            Fail("找不到场景根对象: " + rootName);
            yield break;
        }

        // ---- 冻结在接近 t=0 的默认状态 ----
        Time.timeScale = 1f;
        yield return null;
        yield return null;

        Animator[] anims = _root.GetComponentsInChildren<Animator>(true);
        foreach (Animator a in anims)
        {
            if (a == null)
                continue;
            try
            {
                AnimatorStateInfo info = a.GetCurrentAnimatorStateInfo(0);
                if (info.shortNameHash != 0)
                    a.Play(info.shortNameHash, 0, 0f);
            }
            catch
            {
                // 个别 Animator 状态异常时保持现状即可
            }
            a.speed = 0f;
        }

        Time.timeScale = 0f; // 冻结动画/粒子推进
        yield return null;
        yield return null;

        // 求值后禁用 Animator，避免状态机行为每帧改写 Renderer.enabled
        foreach (Animator a in anims)
        {
            if (a != null)
                a.enabled = false;
        }

        EnumerateRenderers();
        if (_entries.Count == 0)
        {
            Fail("角色下没有任何 Renderer");
            yield break;
        }

        WriteReport();
        DumpStateJson();

        // ---- 相机（优先复用 CaptureFrames 的 *_cam.txt，保证与 t00 参考同框）----
        float cx, cy, orthoSize;
        int w, h;
        if (!ReadCam(out cx, out cy, out orthoSize, out w, out h))
            ComputeCam(out cx, out cy, out orthoSize, out w, out h);

        Camera cam = new GameObject("aeda_probe_cam").AddComponent<Camera>();
        cam.enabled = false;
        cam.orthographic = true;
        cam.orthographicSize = orthoSize;
        cam.transform.position = new Vector3(cx, cy, -10f);
        cam.transform.LookAt(new Vector3(cx, cy, 0f));
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = Color.white;
        cam.allowHDR = false;
        cam.allowMSAA = false;

        RenderTexture rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32);
        rt.Create();
        cam.targetTexture = rt;

        // ---- 逐组开关并截帧（每组开关后等一帧，确保可见性刷新）----
        yield return RunVariant("00_full", cam, true, true, true, true, true);
        yield return RunVariant("01_no_sprite", cam, false, true, true, true, true);
        yield return RunVariant("02_no_skinned", cam, true, false, true, true, true);
        yield return RunVariant("03_no_mesh", cam, true, true, false, true, true);
        yield return RunVariant("04_no_particle", cam, true, true, true, false, true);
        yield return RunVariant("05_no_other", cam, true, true, true, true, false);
        yield return RunVariant("06_only_sprite", cam, true, false, false, false, false);
        yield return RunVariant("07_only_skinned", cam, false, true, false, false, false);
        yield return RunVariant("08_only_mesh", cam, false, false, true, false, false);
        yield return RunVariant("09_sprite_skinned", cam, true, true, false, false, false);
        yield return RunVariant("10_sprite_mesh", cam, true, false, true, false, false);
        yield return RunVariant("11_skinned_mesh", cam, false, true, true, false, false);
        yield return RunVariant("12_sprite_skinned_mesh", cam, true, true, true, false, false);
        yield return RunVariant("13_none", cam, false, false, false, false, false);

        // ---- 恢复现场 ----
        RestoreOriginal();
        cam.targetTexture = null;
        rt.Release();
        Object.Destroy(cam.gameObject);
        Time.timeScale = 1f;

        File.WriteAllText(Path.Combine(_outDir, "done.txt"),
            "OK " + System.DateTime.Now.ToString("s", CultureInfo.InvariantCulture),
            Encoding.UTF8);
        Debug.Log("[AedaProbeRuntime] 探针完成，输出: " + _outDir);
    }

    private GameObject FindRoot()
    {
        if (transform.root != null && transform.root.name == rootName)
            return transform.root.gameObject;
        GameObject[] roots = UnityEngine.SceneManagement.SceneManager
            .GetActiveScene().GetRootGameObjects();
        foreach (GameObject g in roots)
        {
            if (g.name == rootName)
                return g;
        }
        return null;
    }

    private void EnumerateRenderers()
    {
        _entries.Clear();
        _groups.Clear();
        foreach (Renderer r in _root.GetComponentsInChildren<Renderer>(true))
        {
            if (r == null)
                continue;
            string group = GroupOf(r);
            if (!_groups.Contains(group))
                _groups.Add(group);
            _entries.Add(new Entry
            {
                renderer = r,
                group = group,
                path = PathOf(r.transform),
                originalEnabled = r.enabled,
            });
        }
        _groups.Sort((a, b) =>
        {
            int ia = System.Array.IndexOf(GroupRank, a);
            int ib = System.Array.IndexOf(GroupRank, b);
            if (ia < 0) ia = 99;
            if (ib < 0) ib = 99;
            return ia.CompareTo(ib);
        });
    }

    private static string GroupOf(Renderer r)
    {
        if (r is SpriteRenderer)
            return "sprite";
        if (r is SkinnedMeshRenderer)
            return "skinned";
        if (r is MeshRenderer)
            return "mesh";
        if (r is ParticleSystemRenderer)
            return "particle";
        return "other";
    }

    private void SetGroup(string group, bool enabled)
    {
        foreach (Entry e in _entries)
        {
            if (e.group == group)
                e.renderer.enabled = enabled;
        }
    }

    private void RestoreOriginal()
    {
        foreach (Entry e in _entries)
            e.renderer.enabled = e.originalEnabled;
    }

    private IEnumerator RunVariant(string tag, Camera cam,
                                   bool sprite, bool skinned, bool mesh,
                                   bool particle, bool other)
    {
        SetGroup("sprite", sprite);
        SetGroup("skinned", skinned);
        SetGroup("mesh", mesh);
        SetGroup("particle", particle);
        SetGroup("other", other);
        yield return null;
        Capture(tag, cam);
    }

    private void Capture(string tag, Camera cam)
    {
        RenderTexture rt = cam.targetTexture;
        if (rt == null)
            return;
        cam.Render();
        RenderTexture old = RenderTexture.active;
        RenderTexture.active = rt;
        Texture2D tex = new Texture2D(rt.width, rt.height, TextureFormat.RGBA32, false);
        tex.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0);
        tex.Apply();
        RenderTexture.active = old;
        byte[] png = tex.EncodeToPNG();
        File.WriteAllBytes(Path.Combine(_outDir, tag + ".png"), png);
        Debug.Log("[AedaProbeRuntime] " + tag + ".png");
        Object.Destroy(tex);
    }

    private bool ReadCam(out float cx, out float cy, out float size,
                         out int w, out int h)
    {
        cx = cy = size = 0f;
        w = 1024;
        h = 1215;
        string p = Path.Combine(Path.GetDirectoryName(_outDir), rootName + "_cam.txt");
        if (!File.Exists(p))
            return false;
        try
        {
            foreach (string line in File.ReadAllLines(p))
            {
                int i = line.IndexOf('=');
                if (i < 0)
                    continue;
                string k = line.Substring(0, i).Trim();
                string v = line.Substring(i + 1).Trim();
                if (k == "cx") cx = ParseF(v);
                else if (k == "cy") cy = ParseF(v);
                else if (k == "size") size = ParseF(v);
                else if (k == "w") w = (int)ParseF(v);
                else if (k == "h") h = (int)ParseF(v);
            }
            return size > 0f && w > 0 && h > 0;
        }
        catch
        {
            return false;
        }
    }

    private void ComputeCam(out float cx, out float cy, out float size,
                            out int w, out int h)
    {
        Bounds b = new Bounds(_root.transform.position, Vector3.zero);
        bool has = false;
        foreach (Entry e in _entries)
        {
            if (!e.renderer.enabled || e.renderer.bounds.size.sqrMagnitude < 1e-6f)
                continue;
            if (!has)
            {
                b = e.renderer.bounds;
                has = true;
            }
            else
            {
                b.Encapsulate(e.renderer.bounds);
            }
        }
        cx = b.center.x;
        cy = b.center.y;
        float aspect = Mathf.Clamp(b.size.x / Mathf.Max(1e-3f, b.size.y), 0.35f, 2.2f);
        w = 1024;
        h = Mathf.Max(256, Mathf.RoundToInt(1024f / aspect));
        size = Mathf.Max(b.extents.y, b.extents.x / aspect) * 1.15f;
    }

    private void WriteReport()
    {
        StringBuilder sb = new StringBuilder();
        sb.Append("root=").Append(rootName).Append('\n');
        sb.Append("totalRenderers=").Append(_entries.Count).Append('\n');
        foreach (string g in _groups)
        {
            int n = 0;
            foreach (Entry e in _entries)
                if (e.group == g)
                    n++;
            sb.Append("group_").Append(g).Append('=').Append(n).Append('\n');
        }
        sb.Append("--- entries ---\n");
        foreach (Entry e in _entries)
        {
            sb.Append(e.group).Append('\t')
              .Append(e.renderer.GetType().Name).Append('\t')
              .Append(e.renderer.enabled ? "on" : "off").Append('\t')
              .Append(e.path).Append('\n');
        }
        File.WriteAllText(Path.Combine(_outDir, "report.txt"), sb.ToString(), Encoding.UTF8);
    }

    // ---- 冻结默认姿态后，把当前可见 Renderer 几何按 SceneT0 兼容 schema 导出 ----
    private void DumpStateJson()
    {
        string dir = ExportRoots.Data("PoseFrames");
        Directory.CreateDirectory(dir);
        string outPath = Path.Combine(dir, rootName + "_default.json");
        StringBuilder b = new StringBuilder();
        b.Append("{\n  \"prefab\": \"").Append(Escape(rootName)).Append("\",\n");
        b.Append("  \"source\": \"probe-default-freeze\",\n");
        b.Append("  \"renderers\": [");
        bool first = true;
        foreach (Renderer r in _root.GetComponentsInChildren<Renderer>(true))
        {
            if (r == null || !r.gameObject.activeInHierarchy || !r.enabled)
                continue;
            if (r is SkinnedMeshRenderer)
                AppendSkinnedJson(b, (SkinnedMeshRenderer)r, ref first);
            else if (r is SpriteRenderer)
                AppendSpriteJson(b, (SpriteRenderer)r, ref first);
            else if (r is MeshRenderer)
            {
                MeshFilter mf = r.GetComponent<MeshFilter>();
                if (mf != null)
                    AppendStaticJson(b, mf, ref first);
            }
        }
        b.Append("\n  ]\n}\n");
        File.WriteAllText(outPath, b.ToString(), Encoding.UTF8);
        Debug.Log("[AedaProbeRuntime] 默认姿态数据: " + outPath);
    }

    private void AppendSkinnedJson(StringBuilder b, SkinnedMeshRenderer smr,
                                   ref bool first)
    {
        Mesh baked = new Mesh();
        try
        {
            smr.BakeMesh(baked, true);
        }
        catch
        {
            return;
        }
        if (!first) b.Append(",\n");
        first = false;
        Material m = smr.sharedMaterial;
        Bounds wb = smr.bounds;
        b.Append("    {\"kind\": \"skinned\",\n");
        b.Append("      \"path\": \"").Append(Escape(PathOf(smr.transform))).Append("\",\n");
        b.Append("      \"baked\": ").Append(MeshData(baked)).Append(",\n");
        b.Append("      \"worldBounds\": [").Append(F(wb.min.x)).Append(", ")
            .Append(F(wb.min.y)).Append(", ").Append(F(wb.max.x)).Append(", ")
            .Append(F(wb.max.y)).Append("],\n");
        b.Append("      \"sortingOrder\": ").Append(smr.sortingOrder).Append(",\n");
        b.Append("      \"renderQueue\": ").Append(m == null ? -1 : m.renderQueue).Append(",\n");
        b.Append("      \"localToWorld\": ").Append(Mat4(smr.transform.localToWorldMatrix))
            .Append("}");
    }

    private void AppendSpriteJson(StringBuilder b, SpriteRenderer sr, ref bool first)
    {
        Sprite s = sr.sprite;
        Texture2D tex = s == null ? null : s.texture;
        if (s == null)
            return;
        Vector3[] local = SpriteLocalCorners(sr);
        Vector3[] world = new Vector3[local.Length];
        for (int i = 0; i < local.Length; i++)
            world[i] = sr.transform.TransformPoint(local[i]);
        if (!first) b.Append(",\n");
        first = false;
        Material m = sr.sharedMaterial;
        b.Append("    {\"kind\": \"sprite\",\n");
        b.Append("      \"path\": \"").Append(Escape(PathOf(sr.transform))).Append("\",\n");
        b.Append("      \"rect\": [").Append(F(s.rect.x)).Append(", ").Append(F(s.rect.y))
            .Append(", ").Append(F(s.rect.width)).Append(", ").Append(F(s.rect.height)).Append("],\n");
        b.Append("      \"pivot\": [").Append(F(s.pivot.x)).Append(", ").Append(F(s.pivot.y)).Append("],\n");
        b.Append("      \"textureSize\": [").Append(tex == null ? 0 : tex.width).Append(", ")
            .Append(tex == null ? 0 : tex.height).Append("],\n");
        b.Append("      \"worldCorners\": [");
        for (int i = 0; i < world.Length; i++)
        {
            if (i > 0) b.Append(", ");
            b.Append(Vec3(world[i]));
        }
        b.Append("],\n");
        b.Append("      \"sortingOrder\": ").Append(sr.sortingOrder).Append(",\n");
        b.Append("      \"renderQueue\": ").Append(m == null ? -1 : m.renderQueue).Append(",\n");
        b.Append("      \"localToWorld\": ").Append(Mat4(sr.transform.localToWorldMatrix))
            .Append("}");
    }

    private void AppendStaticJson(StringBuilder b, MeshFilter mf, ref bool first)
    {
        Mesh mesh = mf.sharedMesh;
        MeshRenderer mr = mf.GetComponent<MeshRenderer>();
        if (mesh == null || mr == null)
            return;
        if (!first) b.Append(",\n");
        first = false;
        Material m = mr.sharedMaterial;
        b.Append("    {\"kind\": \"static\",\n");
        b.Append("      \"path\": \"").Append(Escape(PathOf(mf.transform))).Append("\",\n");
        b.Append("      \"data\": ").Append(MeshData(mesh)).Append(",\n");
        b.Append("      \"sortingOrder\": ").Append(mr.sortingOrder).Append(",\n");
        b.Append("      \"renderQueue\": ").Append(m == null ? -1 : m.renderQueue).Append(",\n");
        b.Append("      \"localToWorld\": ").Append(Mat4(mf.transform.localToWorldMatrix))
            .Append("}");
    }

    private string MeshData(Mesh mesh)
    {
        if (mesh == null)
            return "{}";
        Vector3[] verts = mesh.vertices;
        Vector2[] uv = mesh.uv;
        int[] tris = mesh.triangles;
        StringBuilder b = new StringBuilder();
        b.Append("{\"vertexCount\": ").Append(verts.Length).Append(", \"positions\": [");
        for (int i = 0; i < verts.Length; i++)
        {
            if (i > 0) b.Append(", ");
            b.Append(Vec3(verts[i]));
        }
        b.Append("], \"uvs\": [");
        for (int i = 0; i < uv.Length; i++)
        {
            if (i > 0) b.Append(", ");
            b.Append("[").Append(F(uv[i].x)).Append(", ").Append(F(uv[i].y)).Append("]");
        }
        b.Append("], \"triangles\": [");
        for (int i = 0; i < tris.Length; i++)
        {
            if (i > 0) b.Append(", ");
            b.Append(tris[i].ToString());
        }
        b.Append("]}");
        return b.ToString();
    }

    private static Vector3[] SpriteLocalCorners(SpriteRenderer sr)
    {
        Sprite s = sr.sprite;
        float w = s.rect.width / s.pixelsPerUnit;
        float h = s.rect.height / s.pixelsPerUnit;
        float l = -s.rect.width * s.pivot.x / s.pixelsPerUnit;
        float bot = -s.rect.height * s.pivot.y / s.pixelsPerUnit;
        return new[]
        {
            new Vector3(l, bot, 0f), new Vector3(l + w, bot, 0f),
            new Vector3(l + w, bot + h, 0f), new Vector3(l, bot + h, 0f),
        };
    }

    private static string Vec3(Vector3 v)
    {
        return "[" + F(v.x) + ", " + F(v.y) + ", " + F(v.z) + "]";
    }

    private static string Mat4(Matrix4x4 m)
    {
        StringBuilder b = new StringBuilder("[");
        for (int r = 0; r < 4; r++)
        {
            if (r > 0) b.Append(", ");
            b.Append("[");
            for (int c = 0; c < 4; c++)
            {
                if (c > 0) b.Append(", ");
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

    private void Fail(string msg)
    {
        Debug.LogError("[AedaProbeRuntime] " + msg);
        Directory.CreateDirectory(_outDir);
        File.WriteAllText(Path.Combine(_outDir, "done.txt"), "ERROR " + msg, Encoding.UTF8);
        Time.timeScale = 1f;
    }

    private static float ParseF(string s)
    {
        float v;
        float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v);
        return v;
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
}
