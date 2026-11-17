// ============================================================================
// UnityAnimationExporter
// ----------------------------------------------------------------------------
// 用途：
//   把“原始 Unity 动画”（Legacy AnimationClip）导出成逐帧 JSON。
//   脚本挂在动态立绘 prefab 上，进入 Play Mode 后会自动遍历其下每个
//   Animation 组件，对每个默认 clip 从 t=0 开始用
//   AnimationClip.SampleAnimation 逐帧采样，然后写一个独立 JSON 文件。
//
//   导出的是“Unity 原始动画真值”，不是 Spine 数据；
//   导出文件拿回本地后与 Spine JSON / 离线渲染逐帧对比。
//
// 输出文件名：
//   <outputDirectory>/<prefabName>_<clipName>.json
//
// 依赖：
//   仅 UnityEngine（不需要 Spine / NGUI 程序集）。
//   NGUI UISprite 颜色通过反射读取，缺失也不影响导出。
// ============================================================================

using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

public class UnityAnimationExporter : MonoBehaviour
{
    [Header("采样")]
    [Tooltip("两次采样间隔（秒）。Spine 转换侧默认 0.05，建议保持一致")]
    public float sampleInterval = 0.05f;

    [Tooltip("是否采样每个 clip 的最后时刻（clip.length 帧）")]
    public bool includeEndFrame = true;

    [Header("目标")]
    [Tooltip("空 = 自动收集本节点下所有 Animation；也可手动指定")]
    public Animation[] manualAnimationTargets;

    [Header("输出")]
    [Tooltip("空 = Application.persistentDataPath")]
    public string outputDirectory = "";

    [Tooltip("文件名是否追加时间戳")]
    public bool includeTimestamp = false;

    [Header("行为")]
    public bool autoExportOnStart = true;

    [Tooltip("导出完成后把 transform 恢复成录制前姿态")]
    public bool restoreAfterExport = true;

    // ---------------------------------------------------------- 数据模型
    [Serializable]
    public class NodeState
    {
        public string path;      // 相对当前 clip 根 GameObject（与 Spine path 对齐）
        public string name;
        public float localX;
        public float localY;
        public float localZ;
        public float rotationZ;  // Unity Quaternion 转出的局部 z 角（度）
        public float scaleX;
        public float scaleY;
        public float scaleZ;
        public bool active;
        public bool hasColor;
        public float colorR;
        public float colorG;
        public float colorB;
        public float colorA;
        public float worldX;
        public float worldY;
    }

    [Serializable]
    public class Frame
    {
        public float time;
        public List<NodeState> nodes = new List<NodeState>();
    }

    [Serializable]
    public class ClipExport
    {
        public string format = "unity-legacy-animation-v1";
        public string prefabName;
        public string clipName;
        public string clipRootPath;   // Animation 组件所在 GameObject 相对本组件路径
        public float duration;        // clip.length
        public float sampleInterval;
        public List<Frame> frames = new List<Frame>();
    }

    // ---------------------------------------------------------- 内部状态
    private struct Baseline
    {
        public Transform tr;
        public Vector3 position;
        public Quaternion rotation;
        public Vector3 scale;
        public bool active;
    }

    private readonly List<Baseline> _baseline = new List<Baseline>();

    private void Start()
    {
        if (autoExportOnStart)
            ExportAll();
    }

    // ---------------------------------------------------------- 对外入口
    [ContextMenu("导出全部 Unity 动画")]
    public void ExportAll()
    {
        List<Animation> targets = new List<Animation>();
        if (manualAnimationTargets != null && manualAnimationTargets.Length > 0)
            targets.AddRange(manualAnimationTargets);
        else
            targets.AddRange(GetComponentsInChildren<Animation>(true));

        int okCount = 0;
        for (int i = 0; i < targets.Count; i++)
        {
            Animation anim = targets[i];
            if (anim == null || anim.clip == null)
                continue;

            try
            {
                ExportClip(anim, anim.clip);
                okCount++;
            }
            catch (Exception ex)
            {
                Debug.LogError("[UnityAnimationExporter] 导出失败 " + anim.clip.name + ": " + ex);
            }
        }

        Debug.Log("[UnityAnimationExporter] 完成，导出 clip 数=" + okCount
                  + "，目录=" + GetOutputDirectory());
    }

    [ContextMenu("导出单个（使用当前默认播放的 Animation）")]
    public void ExportFirstClip()
    {
        Animation anim = GetComponentInChildren<Animation>();
        if (anim == null || anim.clip == null)
        {
            Debug.LogWarning("[UnityAnimationExporter] 未找到带默认 clip 的 Animation");
            return;
        }
        ExportClip(anim, anim.clip);
    }

    // ---------------------------------------------------------- 核心导出
    public void ExportClip(Animation anim, AnimationClip clip)
    {
        if (anim == null || clip == null)
            return;

        Transform root = anim.transform;
        Transform[] nodes = root.GetComponentsInChildren<Transform>(true);
        CacheBaseline(nodes);

        ClipExport export = new ClipExport
        {
            prefabName = gameObject.name,
            clipName = clip.name,
            clipRootPath = GetRelativePath(root),
            duration = clip.length,
            sampleInterval = sampleInterval,
        };

        float end = clip.length;
        int stepCount = Mathf.Max(1, Mathf.CeilToInt(end / sampleInterval));

        for (int s = 0; s <= stepCount; s++)
        {
            float time = Mathf.Min(s * sampleInterval, end);
            if (s == stepCount && !includeEndFrame)
                break;

            clip.SampleAnimation(root.gameObject, time);
            export.frames.Add(CaptureFrame(root, nodes, time));
        }

        string path = SaveClip(export);
        Debug.Log("[UnityAnimationExporter] 已导出 " + export.clipName
                  + "，帧数=" + export.frames.Count + " -> " + path);

        if (restoreAfterExport)
            RestoreBaseline();
    }

    private void CacheBaseline(Transform[] nodes)
    {
        _baseline.Clear();
        for (int i = 0; i < nodes.Length; i++)
        {
            Transform t = nodes[i];
            if (t == null)
                continue;
            _baseline.Add(new Baseline
            {
                tr = t,
                position = t.localPosition,
                rotation = t.localRotation,
                scale = t.localScale,
                active = t.gameObject.activeSelf,
            });
        }
    }

    private void RestoreBaseline()
    {
        for (int i = 0; i < _baseline.Count; i++)
        {
            Baseline b = _baseline[i];
            if (b.tr == null)
                continue;
            b.tr.localPosition = b.position;
            b.tr.localRotation = b.rotation;
            b.tr.localScale = b.scale;
            if (b.tr.gameObject.activeSelf != b.active)
                b.tr.gameObject.SetActive(b.active);
        }
        _baseline.Clear();
    }

    private Frame CaptureFrame(Transform root, Transform[] nodes, float time)
    {
        Frame frame = new Frame { time = (float)Math.Round(time, 6) };
        for (int i = 0; i < nodes.Length; i++)
        {
            Transform t = nodes[i];
            if (t == null)
                continue;

            Quaternion q = t.localRotation;
            float zDeg = Mathf.Atan2(
                2f * (q.w * q.z + q.x * q.y),
                1f - 2f * (q.y * q.y + q.z * q.z)) * Mathf.Rad2Deg;

            NodeState st = new NodeState
            {
                path = GetRelativePath(root, t),
                name = t.name,
                localX = t.localPosition.x,
                localY = t.localPosition.y,
                localZ = t.localPosition.z,
                rotationZ = zDeg,
                scaleX = t.localScale.x,
                scaleY = t.localScale.y,
                scaleZ = t.localScale.z,
                active = t.gameObject.activeSelf,
                worldX = t.position.x,
                worldY = t.position.y,
            };

            // NGUI UISprite 颜色（反射，无硬依赖）
            Component[] comps = t.GetComponents<Component>();
            for (int ci = 0; ci < comps.Length; ci++)
            {
                if (comps[ci] == null || comps[ci].GetType().Name != "UISprite")
                    continue;
                try
                {
                    object colorObj = comps[ci].GetType()
                        .GetProperty("color")?.GetValue(comps[ci], null);
                    if (colorObj != null && colorObj is Color)
                    {
                        Color col = (Color)colorObj;
                        st.hasColor = true;
                        st.colorR = col.r;
                        st.colorG = col.g;
                        st.colorB = col.b;
                        st.colorA = col.a;
                    }
                }
                catch (Exception) { }
                break;
            }

            frame.nodes.Add(st);
        }
        return frame;
    }

    private string SaveClip(ClipExport export)
    {
        string dir = GetOutputDirectory();
        Directory.CreateDirectory(dir);

        string name = export.prefabName + "_" + export.clipName;
        if (includeTimestamp)
            name += "_" + DateTime.Now.ToString("yyyyMMdd_HHmmss");
        string path = Path.Combine(dir, name + ".json");

        File.WriteAllText(path, JsonUtility.ToJson(export, true));
        return path;
    }

    private string GetOutputDirectory()
    {
        return string.IsNullOrEmpty(outputDirectory)
            ? Application.persistentDataPath
            : outputDirectory;
    }

    // ---------------------------------------------------------- 工具
    private string GetRelativePath(Transform fromRoot, Transform child)
    {
        if (child == fromRoot)
            return "<root>";

        string path = child.name;
        Transform cur = child.parent;
        while (cur != null && cur != fromRoot)
        {
            path = cur.name + "/" + path;
            cur = cur.parent;
        }
        return path;
    }

    private string GetRelativePath(Transform child)
    {
        return GetRelativePath(transform, child);
    }
}
