// BatchAttachComponent.cs
// 批量给场景里的 GameObject 挂 / 卸**任意 MonoBehaviour**（不用一个个手拖）。
//
// 和 AddPlayModeProbe.cs 的区别：
//   · AddPlayModeProbe 只处理 PlayModeProbe 一个组件（但会自动填状态表）；
//   · 本工具是通用的——任何 MonoBehaviour 都能批量挂/卸，还能按"筛选组件"定位目标。
// 两者互补：常用的 PlayModeProbe 直接走 AddPlayModeProbe 的快捷菜单，其它脚本走这里。
//
// 只作用于**场景里的实例**，不改 prefab 资源文件；全部走 Undo，可用 Ctrl+Z 撤销。
//
// 菜单：Tools/2DModel/批量组件/
//   · 批量挂/卸组件窗口        —— 选类型 + 选范围，批量添加 / 移除 / 只统计
//   · 给选中物体挂 <类型>（无快捷键，用窗口）
//
// 目标范围（Scope）：
//   Selection        选中的 GameObject（可勾选"含子物体"）
//   CharacterRoots   场景所有根物体里，子树中有 Animator + SkinnedMeshRenderer 的"角色根"
//   SceneAllRoots    场景所有根物体
//   AllSceneObjects  场景所有物体（含层级里的子物体、disabled 的）
//   WithComponent    场景里所有挂了 <筛选组件> 的物体（例如"所有带 Animator 的物体"）
//
// 日志：和运行时采样同一个日志（D:\VB\Unity2Spine\info\_logs\play_sample.log）。

using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

public class BatchAttachComponentWindow : EditorWindow
{
    public enum Scope
    {
        Selection,
        CharacterRoots,
        SceneAllRoots,
        AllSceneObjects,
        WithComponent,
    }

    private static readonly string[] ScopeLabels =
    {
        "选中的 GameObject",
        "场景里的角色根（有 Animator + SkinnedMeshRenderer）",
        "场景所有根物体",
        "场景所有物体（含子物体 / disabled）",
        "场景里挂了【筛选组件】的物体",
    };

    // ---- 类型目录 ----
    private static List<Type> _projectTypes;
    private static List<Type> _allTypesWithUnity;
    private string _typeFilter = "";
    private Vector2 _scroll;
    private Type _attachType;
    private Type _filterType;
    private bool _includeUnityTypes;

    // ---- 范围 ----
    private Scope _scope = Scope.CharacterRoots;
    private bool _includeInactive = true;
    private bool _includeChildren = false;
    private bool _skipExisting = true;
    private bool _onePerBranch = true;

    private string _info = "";
    private List<GameObject> _targets;
    private string _targetsKey;
    private double _targetsAt = -10.0;

    [MenuItem("Tools/2DModel/批量组件/批量挂卸组件窗口")]
    public static void Open()
    {
        var w = GetWindow<BatchAttachComponentWindow>("批量挂组件");
        w.minSize = new Vector2(560, 480);
    }

    // ------------------------------------------------------------ GUI
    private void OnGUI()
    {
        EditorGUILayout.HelpBox(
            "给场景里的 GameObject 批量挂 / 卸任意 MonoBehaviour。\n" +
            "先在下面搜索框里筛类型，点某行的「要挂」把它设为动作组件，点「筛选」设为目标筛选。\n" +
            "只改场景实例，不动 prefab 资源；支持 Ctrl+Z 撤销。",
            MessageType.Info);

        // -------- 动作组件 --------
        EditorGUILayout.LabelField("动作组件（要挂 / 卸的）", EditorStyles.boldLabel);
        EditorGUILayout.LabelField(_attachType == null ? "（未选）" : FullName(_attachType),
                                   EditorStyles.wordWrappedLabel);
        EditorGUILayout.LabelField("目标筛选组件", _filterType == null ? "（无）" : FullName(_filterType));
        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("清空动作组件")) _attachType = null;
        if (GUILayout.Button("清空筛选组件")) _filterType = null;
        EditorGUILayout.EndHorizontal();

        // -------- 类型搜索 --------
        EditorGUILayout.Space();
        EditorGUILayout.LabelField("MonoBehaviour 类型（输入关键字过滤）", EditorStyles.boldLabel);
        _includeUnityTypes = EditorGUILayout.Toggle("包含 Unity 自带组件（Rigidbody 等）", _includeUnityTypes);
        _typeFilter = EditorGUILayout.TextField("搜索", _typeFilter);
        var list = Filtered(_typeFilter, _includeUnityTypes);
        EditorGUILayout.LabelField("匹配 " + list.Count + " 个类型"
                                   + (list.Count > 200 ? "（只显示前 200 个，再输关键字缩小）" : ""));
        _scroll = EditorGUILayout.BeginScrollView(_scroll, GUILayout.Height(160));
        int shown = 0;
        foreach (var t in list)
        {
            if (shown++ >= 200) break;
            EditorGUILayout.BeginHorizontal();
            bool isAttach = t == _attachType;
            bool isFilter = t == _filterType;
            var style = (isAttach || isFilter) ? EditorStyles.boldLabel : EditorStyles.label;
            EditorGUILayout.LabelField((isAttach ? "▶ " : "") + (isFilter ? "◇ " : "") + FullName(t),
                                       style, GUILayout.MinWidth(200));
            if (GUILayout.Button("要挂", GUILayout.Width(48))) _attachType = t;
            if (GUILayout.Button("筛选", GUILayout.Width(48))) _filterType = t;
            EditorGUILayout.EndHorizontal();
        }
        EditorGUILayout.EndScrollView();

        // -------- 范围 --------
        EditorGUILayout.Space();
        EditorGUILayout.LabelField("目标范围", EditorStyles.boldLabel);
        _scope = (Scope)EditorGUILayout.Popup("范围", (int)_scope, ScopeLabels);
        _includeInactive = EditorGUILayout.Toggle("包含 disabled 的物体", _includeInactive);
        if (_scope == Scope.CharacterRoots)
        {
            _includeChildren = false;
            EditorGUILayout.LabelField("（角色根范围固定只挂根节点——挂到子物体会让同一个 Animator 被几十个 probe 抢）");
        }
        else
        {
            _includeChildren = EditorGUILayout.Toggle("把子物体也一起挂（否则只挂命中的物体本身）", _includeChildren);
        }
        _skipExisting = EditorGUILayout.Toggle("跳过已经挂过的（关掉=可能重复挂/刷新）", _skipExisting);
        _onePerBranch = EditorGUILayout.Toggle(
            new GUIContent("同一分支只挂一个", "父级已经挂了同组件时，子物体跳过——避免一个 Animator 被多个组件驱动"),
            _onePerBranch);

        var targets = Targets();
        EditorGUILayout.LabelField("当前会命中 " + targets.Count + " 个 GameObject");
        if (GUILayout.Button("重新扫描场景")) { Targets(true); Repaint(); }
        if (targets.Count > 500)
            EditorGUILayout.HelpBox("目标超过 500 个，确认一下范围/是否误开了子物体——批量挂组件会真的写进场景。",
                                    MessageType.Warning);
        if (targets.Count > 0)
        {
            var head = string.Join(", ", targets.Take(5).Select(g => g.name).ToArray());
            EditorGUILayout.LabelField("例如：" + head + (targets.Count > 5 ? " …" : ""),
                                       EditorStyles.wordWrappedLabel);
        }

        // -------- 动作 --------
        EditorGUILayout.Space();
        EditorGUILayout.BeginHorizontal();
        using (new EditorGUI.DisabledScope(_attachType == null || targets.Count == 0))
        {
            if (GUILayout.Button("批量挂载", GUILayout.Height(34)))
                Apply(targets, _attachType, true, _skipExisting, _onePerBranch);
            if (GUILayout.Button("批量卸载", GUILayout.Height(34)))
                Apply(targets, _attachType, false, false, _onePerBranch);
        }
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.Space();
        EditorGUILayout.LabelField(_info, EditorStyles.wordWrappedLabel);
    }

    // ------------------------------------------------------------ 执行
    private static void Apply(List<GameObject> targets, Type type, bool add, bool skipExisting, bool onePerBranch)
    {
        int changed = 0, skipped = 0, failed = 0;
        // 目标按层级路径排序 = 父级在前；"同一分支只挂一个"才能正确地把组件留在父级
        foreach (var go in targets)
        {
            if (go == null) continue;
            try
            {
                var existing = go.GetComponent(type);
                if (add)
                {
                    if (existing != null && skipExisting) { skipped++; continue; }
                    if (onePerBranch && existing == null && HasAncestorWith(go, type))
                    {
                        skipped++;   // 父级已经挂了同组件，子物体不再挂（避免一个 Animator 被多个组件驱动）
                        continue;
                    }
                    var comp = Undo.AddComponent(go, type);
                    if (comp == null) { failed++; continue; }
                    // PlayModeProbe 特例：顺手把 AnimatorController 的状态表填进去
                    var probe = comp as PlayModeProbe;
                    if (probe != null)
                    {
                        try { AddPlayModeProbe.FillStateTable(probe); } catch (Exception ex)
                        { PlaySampleLog.E("填状态表失败 " + go.name, ex); }
                    }
                    changed++;
                }
                else
                {
                    if (existing == null) { skipped++; continue; }
                    Undo.DestroyObjectImmediate(existing);
                    changed++;
                }
            }
            catch (Exception ex)
            {
                failed++;
                PlaySampleLog.E((add ? "挂 " : "卸 ") + type.Name + " 到 " + go.name + " 失败", ex);
            }
        }
        MarkSceneDirty();
        string what = (add ? "挂载 " : "卸载 ") + type.Name;
        string msg = string.Format("批量{0}：改动 {1}，跳过 {2}，失败 {3}，目标 {4}",
                                   what, changed, skipped, failed, targets.Count);
        if (add)
        {
            int inactive = 0;
            foreach (var go in targets)
                if (go != null && !go.activeInHierarchy) inactive++;
            if (inactive > 0)
                msg += "；其中 " + inactive + " 个是 inactive 的（MonoBehaviour 的 Start/Update 不会执行）";
        }
        PlaySampleLog.W(msg);
        var w = GetWindow<BatchAttachComponentWindow>("批量挂组件");
        w._info = msg;
        w._targets = null;      // 目标变了，下次重扫
        w.Repaint();
    }

    private static bool HasAncestorWith(GameObject go, Type type)
    {
        Transform p = go.transform.parent;
        while (p != null)
        {
            if (p.GetComponent(type) != null) return true;
            p = p.parent;
        }
        return false;
    }

    // ------------------------------------------------------------ 收集目标
    /// <summary>
    /// 带缓存的目标收集：OnGUI 每帧都会读，直接重扫 4000+ 物体的场景会卡。
    /// 1 秒 TTL + 显式"重新扫描"按钮。
    /// </summary>
    private List<GameObject> Targets(bool force = false)
    {
        string key = string.Format("{0}|{1}|{2}|{3}|{4}|{5}",
            (int)_scope, FullName(_filterType), FullName(_attachType),
            _includeInactive, _includeChildren, _onePerBranch);
        if (!force && _targets != null && key == _targetsKey
            && EditorApplication.timeSinceStartup - _targetsAt < 1.0)
            return _targets;
        _targetsKey = key;
        _targetsAt = EditorApplication.timeSinceStartup;
        _targets = Collect(_scope, _filterType, _includeInactive, _includeChildren);
        return _targets;
    }

    private static List<GameObject> Collect(Scope scope, Type filterType, bool includeInactive, bool includeChildren)
    {
        var bases = new List<GameObject>();
        switch (scope)
        {
            case Scope.Selection:
                bases.AddRange(Selection.gameObjects.Where(g => g != null));
                break;
            case Scope.CharacterRoots:
                bases.AddRange(CharacterRoots(includeInactive));
                break;
            case Scope.SceneAllRoots:
                bases.AddRange(RootObjects(includeInactive));
                break;
            case Scope.AllSceneObjects:
                bases.AddRange(SceneObjects(includeInactive));
                break;
            case Scope.WithComponent:
                if (filterType != null)
                    bases.AddRange(SceneObjects(includeInactive).Where(g => g.GetComponent(filterType) != null));
                break;
        }

        var result = new List<GameObject>();
        foreach (var g in bases)
        {
            if (g == null) continue;
            if (includeChildren)
                result.AddRange(g.GetComponentsInChildren<Transform>(includeInactive).Select(t => t.gameObject));
            else
                result.Add(g);
        }

        // 去重 + 再按筛选组件过滤
        var uniq = new HashSet<GameObject>();
        var final = new List<GameObject>();
        foreach (var g in result)
        {
            if (g == null || !uniq.Add(g)) continue;
            if (filterType != null && g.GetComponent(filterType) == null) continue;
            final.Add(g);
        }
        final.Sort((a, b) => string.CompareOrdinal(PathOf(a.transform), PathOf(b.transform)));
        return final;
    }

    private static IEnumerable<GameObject> RootObjects(bool includeInactive)
    {
        var scene = SceneManager.GetActiveScene();
        foreach (var g in scene.GetRootGameObjects())
            if (includeInactive || g.activeInHierarchy) yield return g;
    }

    /// <summary>
    /// "角色根" = 子树里有 Animator + SkinnedMeshRenderer，且**父级子树里没有新角色**的最高节点。
    /// 这样既覆盖"每个角色是一个场景根"，也覆盖"角色都被塞进一个容器"的情况——
    /// 后者如果用场景根当角色根，会把整个容器当成一个角色。
    /// </summary>
    private static IEnumerable<GameObject> CharacterRoots(bool includeInactive)
    {
        foreach (var g in SceneObjects(includeInactive))
        {
            if (g.GetComponentInChildren<Animator>(true) == null) continue;
            if (g.GetComponentInChildren<SkinnedMeshRenderer>(true) == null) continue;
            Transform p = g.transform.parent;
            if (p != null && ParentHasForeignAnimator(p, g)) continue;
            yield return g;
        }
    }

    /// <summary>父级子树里是否有"不属于本节点子树"的 Animator（= 父级还装着别的角色）。</summary>
    private static bool ParentHasForeignAnimator(Transform parent, GameObject child)
    {
        var mine = new HashSet<Animator>(child.GetComponentsInChildren<Animator>(true));
        foreach (var a in parent.GetComponentsInChildren<Animator>(true))
            if (!mine.Contains(a)) return true;
        return false;
    }

    private static IEnumerable<GameObject> SceneObjects(bool includeInactive)
    {
        foreach (var g in Resources.FindObjectsOfTypeAll<GameObject>())
        {
            if (g == null) continue;
            if (EditorUtility.IsPersistent(g)) continue;              // prefab 资源，不动
            if (!g.scene.IsValid() || !g.scene.isLoaded) continue;    // 不在当前场景
            if (!includeInactive && !g.activeInHierarchy) continue;
            yield return g;
        }
    }

    private static void MarkSceneDirty()
    {
        var scene = SceneManager.GetActiveScene();
        if (scene.IsValid()) UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(scene);
    }

    private static string PathOf(Transform t)
    {
        var parts = new List<string>();
        Transform cur = t;
        while (cur != null) { parts.Insert(0, cur.name); cur = cur.parent; }
        return string.Join("/", parts.ToArray());
    }

    // ------------------------------------------------------------ 类型目录
    private static List<Type> Filtered(string keyword, bool includeUnity)
    {
        var all = AllTypes(includeUnity);
        if (string.IsNullOrEmpty(keyword)) return all;
        string k = keyword.ToLowerInvariant();
        return all.Where(t => FullName(t).ToLowerInvariant().Contains(k)).ToList();
    }

    private static List<Type> AllTypes(bool includeUnity)
    {
        if (includeUnity && _allTypesWithUnity != null) return _allTypesWithUnity;
        if (!includeUnity && _projectTypes != null) return _projectTypes;
        var result = new List<Type>();
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            if (asm.IsDynamic) continue;
            string an = asm.GetName().Name;
            if (!includeUnity && an.StartsWith("Unity")) continue;   // Unity 自带组件默认不列
            if (an.StartsWith("System") || an.StartsWith("mscorlib")) continue;
            if (an.StartsWith("Microsoft")) continue;
            if (an.StartsWith("nunit") || an.StartsWith("NUnit")) continue;
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }
            catch { continue; }
            foreach (var t in types)
            {
                if (!IsAttachable(t, includeUnity)) continue;
                result.Add(t);
            }
        }
        result = result
            .GroupBy(t => FullName(t))
            .Select(g => g.First())
            .OrderBy(FullName, StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (includeUnity) _allTypesWithUnity = result; else _projectTypes = result;
        return result;
    }

    private static bool IsAttachable(Type t, bool includeUnity)
    {
        if (t == null) return false;
        if (t.IsAbstract || t.IsInterface || t.IsGenericTypeDefinition) return false;
        if (t.Name.Contains("<") || t.Name.Contains(">")) return false;   // 编译器生成
        if (!typeof(MonoBehaviour).IsAssignableFrom(t)) return false;
        if (typeof(Editor).IsAssignableFrom(t)) return false;
        if (typeof(EditorWindow).IsAssignableFrom(t)) return false;
        if (!includeUnity && t.Namespace != null && t.Namespace.StartsWith("Unity")) return false;
        return true;
    }

    private static string FullName(Type t)
    {
        if (t == null) return "";
        return string.IsNullOrEmpty(t.Namespace) ? t.Name : (t.Namespace + "." + t.Name);
    }
}
