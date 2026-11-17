// ExportSelected.cs
// 单独导出"当前选中的对象/组件"：不用整角色，选中谁就导谁。
// 典型用法：在 Hierarchy 里选中某个部件（例如 eternity 的 Part_BallonBed__10），
// 点菜单 → 只渲染它自己，出四张参考图，用来确认它在 Unity 里到底怎么显示。
//
// 输出：D:\VB\Unity2Spine\info\Data\Frames\  （见 Assets\Script\ExportRoots.cs）
//       _selected/<对象名>/{00_full,01_dynamic,02_sprites_white,03_sprites_dark}.png
//       （+ 各自的 _cam.txt）
//
// 说明：
//   · 会自动激活选中对象及其父链（场景里通常是 disabled），导完恢复原状；
//   · 渲染期间自动关掉"不属于该对象"的渲染器，所以画面里只有它；
//   · 支持多选，逐个导出。

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class ExportSelected
{
    private const string OutRoot = "_selected";

    [MenuItem("Tools/2DModel/校准数据/导出选中对象（参考图）")]
    public static void ExportFrames()
    {
        GameObject[] targets = Selection.gameObjects;
        if (targets == null || targets.Length == 0)
        {
            Debug.LogError("[ExportSelected] 请先在 Hierarchy 里选中一个对象");
            return;
        }

        AnimationMode.StartAnimationMode();
        try
        {
            foreach (GameObject go in targets)
            {
                if (go == null)
                    continue;
                string dir = ExportRoots.Of("Data", "Frames",
                                            OutRoot, Sanitize(go.name));
                Directory.CreateDirectory(dir);

                // 激活该对象及其父链，导完恢复
                List<GameObject> reactivated = CalibTargets.Activate(go);
                // 渲染时只保留该对象子树的渲染器
                List<Renderer> otherOff = CalibTargets.IsolateRenderers(go);
                try
                {
                    Debug.Log("[ExportSelected] 导出 " + go.name + " -> " + dir);
                    TwoDModelCalibExport.CaptureAllSets(go, dir);
                }
                finally
                {
                    CalibTargets.RestoreRenderers(otherOff);
                    CalibTargets.Restore(reactivated);
                }
            }
        }
        finally
        {
            AnimationMode.StopAnimationMode();
        }
        AssetDatabase.Refresh();
        Debug.Log("[ExportSelected] 完成，输出在 " +
                  ExportRoots.Of("Data", "Frames", OutRoot) + "/");
    }

    private const string ConfigOutRoot = "_parts";

    /// <summary>
    /// 按 export_config.json 里的 `parts` 列表导出：脚本自己去场景里找这些部件
    /// （**包含 disabled 的**），临时激活后只渲染它们，导完恢复原状。
    /// 用来盯某个具体部件（例如 eternity 的 Part_BallonBed__10）的真实渲染。
    /// </summary>
    [MenuItem("Tools/2DModel/校准数据/导出配置里的部件（export_config.json）")]
    public static void ExportConfiguredParts()
    {
        TwoDModelCalibExport.ExportConfig cfg =
            TwoDModelCalibExport.LoadConfig();
        if (cfg == null || cfg.parts == null || cfg.parts.Length == 0)
        {
            Debug.LogError("[ExportSelected] 配置里没有 parts，或者找不到 " +
                           ExportRoots.Of("Data") + "\\export_config.json");
            return;
        }
        if (!string.IsNullOrEmpty(cfg.scene))
            TwoDModelCalibExport.ScenePath = cfg.scene;
        Scene scene = EditorSceneManager.OpenScene(
            TwoDModelCalibExport.ScenePath, OpenSceneMode.Single);

        AnimationMode.StartAnimationMode();
        try
        {
            int found = 0;
            foreach (string partName in cfg.parts)
            {
                if (string.IsNullOrEmpty(partName))
                    continue;
                GameObject go = FindByName(scene, partName);
                if (go == null)
                {
                    Debug.LogWarning("[ExportSelected] 场景里找不到部件: " +
                                     partName);
                    continue;
                }
                found++;
                string dir = ExportRoots.Of("Data", "Frames",
                                            ConfigOutRoot, Sanitize(go.name));
                Directory.CreateDirectory(dir);
                List<GameObject> reactivated = CalibTargets.Activate(go);
                List<Renderer> otherOff = CalibTargets.IsolateRenderers(go);
                try
                {
                    Debug.Log("[ExportSelected] 部件 " + go.name + " -> " + dir);
                    TwoDModelCalibExport.CaptureAllSets(go, dir);
                }
                finally
                {
                    CalibTargets.RestoreRenderers(otherOff);
                    CalibTargets.Restore(reactivated);
                }
            }
            Debug.Log("[ExportSelected] 配置部件导出完成：" + found + "/" +
                      cfg.parts.Length + " 个命中，输出在 " +
                      ExportRoots.Of("Data", "Frames", ConfigOutRoot) + "/");
        }
        finally
        {
            AnimationMode.StopAnimationMode();
        }
        AssetDatabase.Refresh();
    }

    /// <summary>按名字递归找对象（包含 disabled）。</summary>
    private static GameObject FindByName(Scene scene, string name)
    {
        foreach (GameObject root in scene.GetRootGameObjects())
        {
            GameObject r = FindByName(root.transform, name);
            if (r != null)
                return r;
        }
        return null;
    }

    private static GameObject FindByName(Transform t, string name)
    {
        if (t.name == name)
            return t.gameObject;
        for (int i = 0; i < t.childCount; i++)
        {
            GameObject r = FindByName(t.GetChild(i), name);
            if (r != null)
                return r;
        }
        return null;
    }

    /// <summary>去掉路径里不能做文件名的字符。</summary>
    private static string Sanitize(string name)
    {
        char[] bad = Path.GetInvalidFileNameChars();
        foreach (char c in bad)
            name = name.Replace(c, '_');
        return name.Replace('/', '_').Replace('\\', '_').Trim();
    }
}
