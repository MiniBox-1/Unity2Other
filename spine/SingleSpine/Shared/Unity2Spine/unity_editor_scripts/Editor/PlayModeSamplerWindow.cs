// PlayModeSamplerWindow.cs
// Play 模式运行时采样的编辑器窗口（配置 + 开始 + 只打印诊断 + 打开日志）。
// 采样实现见 PlayModeSamplerRunner.cs；日志 D:\VB\Unity2Spine\info\_logs\play_sample.log。
// 为什么用 Play 模式：TwoDModelCalibExport 用 AnimationMode.SampleAnimationClip
// （编辑器采样）不跑 Animator 状态机，采样后那句 animator.Update(0) 还会覆盖
// m_IsActive；这里让 Animator 真的按状态机播，逐帧记录"Unity 到底显示了什么"。
//
// 采样范围：每个 **角色 × Animator（主+副）× 状态（含子状态机、所有层）**
// 输出：D:\VB\Unity2Spine\info\Data\PlayFrames\<角色>@<Animator>@<状态>.json + _summary.json
// 日志：D:\VB\Unity2Spine\info\_logs\play_sample.log（同时打 Console）
//
// 菜单：Tools/2DModel/运行时采样/
//   · 采样窗口                 —— 配置 + 开始 + 只打印诊断 + 打开日志
//   · 开始采样（不用窗口）
//   · 打开日志
//
// 注意（C# 限制）：协程里**不能**在带 catch 的 try 中 yield。
// 所以所有有风险的步骤（Play/Update、建 JSON、写文件、遍历 controller）
// 都放在**不带 yield 的 helper** 里各自 try/catch；协程体里只有 try/finally。

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

// ------------------------------------------------------------------ 日志
public class PlayModeSamplerWindow : EditorWindow
{
    private string characterNames = "";
    private float sampleStep = 0.05f;
    private bool includeInactiveCharacters = true;
    private bool bakeMeshes = false;
    private string bakeChars = "";
    private string info = "";
    private int cachedCount = -1;
    private double cachedAt = -10.0;

    [MenuItem("Tools/2DModel/运行时采样/采样窗口")]
    public static void Open()
    {
        var w = GetWindow<PlayModeSamplerWindow>("运行时采样");
        w.minSize = new Vector2(540, 340);
    }

    private void OnGUI()
    {
        EditorGUILayout.HelpBox(
            "Play 模式下按 Animator 状态机采样：每个 角色 × Animator × 状态 一份 JSON。\n" +
            "角色名留空 = 自动扫描场景里所有 2DModel 角色（含 disabled）。\n" +
            "先点「只打印诊断」确认能扫到角色，再点「开始采样」。",
            MessageType.Info);

        characterNames = EditorGUILayout.TextField("角色名（逗号分隔）", characterNames);
        if (GUILayout.Button("从 Assets/prefabs/main 读取角色名"))
        {
            var names = new List<string>();
            foreach (string guid in AssetDatabase.FindAssets(
                         "t:Prefab", new[] { "Assets/prefabs/main" }))
                names.Add(Path.GetFileNameWithoutExtension(AssetDatabase.GUIDToAssetPath(guid)));
            names.Sort();
            characterNames = string.Join(",", names);
            info = "已读取 " + names.Count + " 个角色名（prefabs/main）";
            PlaySampleLog.W(info);
        }
        sampleStep = EditorGUILayout.FloatField("采样步长（秒）", sampleStep);
        includeInactiveCharacters = EditorGUILayout.Toggle("包含 disabled 的角色", includeInactiveCharacters);
        bakeMeshes = EditorGUILayout.Toggle("同时写 BakeMesh 前 8 点（慢）", bakeMeshes);
        bakeChars = EditorGUILayout.TextField("只给这些角色写全量 BakeMesh（子串，空=全部）", bakeChars);

        var cfg = new PlayModeSamplerRunner.Config
        {
            names = characterNames,
            step = Mathf.Max(0.01f, sampleStep),
            includeInactive = includeInactiveCharacters,
            bake = bakeMeshes,
            bakeChars = bakeChars,
        };

        if (EditorApplication.timeSinceStartup - cachedAt > 0.5 || cachedCount < 0)
        {
            cachedAt = EditorApplication.timeSinceStartup;
            cachedCount = PlayModeSamplerRunner.CountCharacters(cfg);
        }
        EditorGUILayout.LabelField("场景里能扫到的角色数", cachedCount.ToString());
        EditorGUILayout.LabelField("日志文件", PlaySampleLog.LogPath);

        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("开始采样（进入 Play 模式）", GUILayout.Height(34)))
            PlayModeSamplerRunner.StartSampling(cfg);
        if (GUILayout.Button("只打印诊断（不进 Play）", GUILayout.Height(34)))
            PlayModeSamplerRunner.Diagnose(cfg);
        EditorGUILayout.EndHorizontal();

        if (GUILayout.Button("打开日志文件"))
            EditorUtility.RevealInFinder(PlaySampleLog.LogPath);
        if (GUILayout.Button("停止采样并退出 Play 模式"))
        {
            PlayModeSamplerRunner.StopRequested = true;
            PlaySampleLog.W("用户点了停止");
            if (EditorApplication.isPlaying) EditorApplication.ExitPlaymode();
        }
        EditorGUILayout.Space();
        EditorGUILayout.LabelField(info, EditorStyles.wordWrappedLabel);
    }

    private void OnInspectorUpdate() { Repaint(); }
}

// ------------------------------------------------------------------ 触发引导
// 两条通道保证一定触发：playModeStateChanged + EditorApplication.update 轮询
// （后者覆盖 "Project Settings 里关了 Domain Reload、静态构造不重跑" 的情况）。
