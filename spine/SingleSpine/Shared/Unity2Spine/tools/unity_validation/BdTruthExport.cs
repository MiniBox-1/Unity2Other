// ============================================================================
// BdTruthExport —— BdOne（NGUI 动态立绘）真值导出（Editor / batchmode 均可用）
//
// 对 Assets/prefab/chr 下每个角色 prefab：把它实例化，逐个 Animation 组件
// 的默认 clip 用 AnimationClip.SampleAnimation 按固定步长采样，逐帧记录
//
//   · 每个 Transform 的 localPosition / rotationZ / localScale / activeSelf
//   · UISprite 的颜色、widget 宽高、depth、mType、mFlip、enabled
//   · UISprite.drawingDimensions —— NGUI 实际用来画这张图的局部矩形
//     （x0,y0,x1,y1；这是"部件放在哪儿、多大"的真值）
//   · 该 UISprite 解析到的 atlas region 元数据（x/y/w/h/padding）
//
// 输出：<out>/<角色>__<clip>.json
// 用法（batchmode）：
//   Unity.exe -batchmode -quit -projectPath D:\VB\Search\BdOne `
//     -executeMethod BdTruthExport.ExportAll -bdOut <dir> [-bdStep 0.05] `
//     [-bdChars 阿波罗,安洁利卡] -logFile <log>
// ============================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

public static class BdTruthExport
{
    const string CHR_DIR = "Assets/prefab/chr";

    class NodeInfo
    {
        public Transform tr;
        public string path;
        public string name;
        public UISprite sprite;
        public string spriteName;
        public float w, h, depth;
        public int type, flip;
        public bool enabled;
    }

    public static void ExportAll()
    {
        string outDir = Arg("-bdOut", null);
        if (string.IsNullOrEmpty(outDir))
            outDir = Path.Combine(Directory.GetCurrentDirectory(), "_bd_truth");
        float step = 0.05f;
        string stepArg = Arg("-bdStep", null);
        if (!string.IsNullOrEmpty(stepArg))
            float.TryParse(stepArg, NumberStyles.Float, CultureInfo.InvariantCulture, out step);
        string charFilter = Arg("-bdChars", null);
        var wanted = new HashSet<string>();
        if (!string.IsNullOrEmpty(charFilter))
            foreach (var s in charFilter.Split(','))
                if (s.Trim().Length > 0) wanted.Add(s.Trim());

        Directory.CreateDirectory(outDir);
        int okPrefabs = 0, okClips = 0, failClips = 0;
        var files = Directory.GetFiles(CHR_DIR, "*.prefab");
        Array.Sort(files, StringComparer.Ordinal);
        foreach (var f in files)
        {
            string fp = f.Replace('\\', '/');
            string charName = Path.GetFileNameWithoutExtension(fp);
            if (wanted.Count > 0 && !wanted.Contains(charName)) continue;

            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(fp);
            if (prefab == null)
            {
                Debug.LogError("[BdTruthExport] prefab 载入失败: " + fp);
                continue;
            }
            GameObject inst = UnityEngine.Object.Instantiate(prefab);
            inst.name = charName;
            prefab = null;
            try
            {
                var anims = inst.GetComponentsInChildren<Animation>(true);
                okPrefabs++;
                foreach (var anim in anims)
                {
                    if (anim == null || anim.clip == null) continue;
                    try
                    {
                        ExportClip(charName, anim, anim.clip, step, outDir);
                        okClips++;
                    }
                    catch (Exception ex)
                    {
                        failClips++;
                        Debug.LogError("[BdTruthExport] clip 导出失败 " + anim.clip.name
                                       + ": " + ex);
                    }
                }
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(inst);
            }
        }
        Debug.Log(string.Format("[BdTruthExport] 完成：prefab={0} clip={1} 失败={2} -> {3}",
                                okPrefabs, okClips, failClips, outDir));
        if (Application.isBatchMode) EditorApplication.Exit(failClips == 0 ? 0 : 1);
    }

    static void ExportClip(string charName, Animation anim, AnimationClip clip,
                           float step, string outDir)
    {
        Transform root = anim.transform;
        var nodes = new List<NodeInfo>();
        var all = root.GetComponentsInChildren<Transform>(true);
        foreach (var t in all)
        {
            var ni = new NodeInfo();
            ni.tr = t;
            ni.path = RelPath(root, t);
            ni.name = t.name;
            var sp = t.GetComponent<UISprite>();
            if (sp != null)
            {
                ni.sprite = sp;
                ni.spriteName = sp.spriteName;
                ni.w = sp.width;
                ni.h = sp.height;
                ni.depth = sp.depth;
                ni.type = (int)sp.type;
                ni.flip = (int)sp.flip;
                ni.enabled = sp.enabled;
            }
            nodes.Add(ni);
        }

        var sb = new StringBuilder();
        sb.Append("{\"format\":\"bd-ngui-truth-v1\",\"char\":").Append(J(charName));
        sb.Append(",\"assembly\":").Append(J(root.name));
        sb.Append(",\"clip\":").Append(J(clip.name));
        sb.Append(",\"duration\":").Append(N(clip.length));
        sb.Append(",\"step\":").Append(N(step));
        sb.Append(",\"nodeCount\":").Append(nodes.Count);
        sb.Append(",\"nodes\":[");
        for (int i = 0; i < nodes.Count; i++)
        {
            var ni = nodes[i];
            if (i > 0) sb.Append(',');
            sb.Append("{\"path\":").Append(J(ni.path));
            sb.Append(",\"name\":").Append(J(ni.name));
            if (ni.sprite != null)
            {
                sb.Append(",\"sprite\":{");
                sb.Append("\"spriteName\":").Append(J(ni.spriteName));
                sb.Append(",\"widgetW\":").Append(N(ni.w));
                sb.Append(",\"widgetH\":").Append(N(ni.h));
                sb.Append(",\"depth\":").Append(N(ni.depth));
                sb.Append(",\"type\":").Append(ni.type);
                sb.Append(",\"flip\":").Append(ni.flip);
                sb.Append(",\"enabled\":").Append(ni.enabled ? "true" : "false");
                var atlas = ni.sprite.atlas;
                var atlasObj = atlas as UnityEngine.Object;
                sb.Append(",\"atlas\":")
                  .Append(atlasObj != null ? J(atlasObj.name) : "null");
                var data = ni.sprite.GetAtlasSprite();
                if (data != null)
                {
                    sb.Append(",\"hasRegion\":true");
                    sb.Append(",\"region\":{");
                    sb.Append("\"name\":").Append(J(data.name));
                    sb.Append(",\"x\":").Append(data.x).Append(",\"y\":").Append(data.y);
                    sb.Append(",\"width\":").Append(data.width);
                    sb.Append(",\"height\":").Append(data.height);
                    sb.Append(",\"pl\":").Append(data.paddingLeft);
                    sb.Append(",\"pb\":").Append(data.paddingBottom);
                    sb.Append(",\"pr\":").Append(data.paddingRight);
                    sb.Append(",\"pt\":").Append(data.paddingTop);
                    sb.Append("}");
                }
                else sb.Append(",\"hasRegion\":false");
                sb.Append("}");
            }
            sb.Append("}");
        }
        sb.Append("],\"frames\":[");

        int steps = Mathf.Max(1, Mathf.CeilToInt(clip.length / step));
        for (int s = 0; s <= steps; s++)
        {
            float time = Mathf.Min(s * step, clip.length);
            clip.SampleAnimation(root.gameObject, time);
            if (s > 0) sb.Append(',');
            sb.Append("{\"t\":").Append(N(time)).Append(",\"a\":[");
            for (int i = 0; i < nodes.Count; i++)
            {
                var ni = nodes[i];
                var t = ni.tr;
                var q = t.localRotation;
                float rz = Mathf.Atan2(2f * (q.w * q.z + q.x * q.y),
                                       1f - 2f * (q.y * q.y + q.z * q.z)) * Mathf.Rad2Deg;
                if (i > 0) sb.Append(',');
                sb.Append('[');
                sb.Append(N(t.localPosition.x)).Append(',').Append(N(t.localPosition.y));
                sb.Append(',').Append(N(rz));
                sb.Append(',').Append(N(t.localScale.x)).Append(',').Append(N(t.localScale.y));
                sb.Append(',').Append(t.gameObject.activeSelf ? "1" : "0");
                if (ni.sprite != null)
                {
                    var c = ni.sprite.color;
                    var dd = ni.sprite.drawingDimensions;
                    sb.Append(',').Append(N(c.r)).Append(',').Append(N(c.g))
                      .Append(',').Append(N(c.b)).Append(',').Append(N(c.a));
                    sb.Append(',').Append(N(dd.x)).Append(',').Append(N(dd.y))
                      .Append(',').Append(N(dd.z)).Append(',').Append(N(dd.w));
                }
                else
                {
                    sb.Append(",0,0,0,0,0,0,0,0");
                }
                sb.Append(']');
            }
            sb.Append("]}");
        }
        sb.Append("]}");

        string outPath = Path.Combine(outDir, charName + "__" + clip.name + ".json");
        File.WriteAllText(outPath, sb.ToString(), new UTF8Encoding(false));
        Debug.Log("[BdTruthExport] " + charName + "/" + root.name + " clip="
                  + clip.name + " 节点=" + nodes.Count + " 帧=" + (steps + 1)
                  + " -> " + outPath);
    }

    static string RelPath(Transform root, Transform t)
    {
        if (t == root) return "<root>";
        var parts = new List<string>();
        var cur = t;
        while (cur != null && cur != root)
        {
            parts.Add(cur.name);
            cur = cur.parent;
        }
        parts.Reverse();
        return string.Join("/", parts.ToArray());
    }

    static string Arg(string name, string def)
    {
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == name) return args[i + 1];
        return def;
    }

    static string N(float v)
    {
        return v.ToString("0.######", CultureInfo.InvariantCulture);
    }

    static string J(string s)
    {
        if (s == null) return "null";
        var sb = new StringBuilder("\"");
        foreach (var ch in s)
        {
            switch (ch)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (ch < 32) sb.Append("\\u").Append(((int)ch).ToString("x4"));
                    else sb.Append(ch);
                    break;
            }
        }
        return sb.Append('"').ToString();
    }
}
