// CalibTargets.cs
// 校准导出的公共逻辑：在 save 场景里按名字找角色，**逐个**处理——
//   1) 角色在场景里通常是 disabled（多个角色一起放着时），导出前把整条父链
//      临时激活，导出后恢复原状；
//   2) 截图/采样时可以把其它角色的渲染器临时关掉，避免互相遮挡；
//   3) 角色不要求是场景根对象，递归查找即可。
//
// 用法（各导出脚本）：
//   CalibTargets.ForEach(CalibTargets.DefaultNames, root => { ...导出... });

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class CalibTargets
{
    /// <summary>递归找名字匹配的角色（含 disabled），命中后不再进它的子树。</summary>
    public static List<GameObject> Collect(string[] names)
    {
        List<GameObject> outList = new List<GameObject>();
        Scene scene = SceneManager.GetActiveScene();
        if (!scene.IsValid())
            return outList;
        foreach (GameObject root in scene.GetRootGameObjects())
            Collect(root.transform, names, outList);
        return outList;
    }

    private static void Collect(Transform t, string[] names,
                                List<GameObject> outList)
    {
        if (Match(t.name, names))
        {
            outList.Add(t.gameObject);
            return;
        }
        for (int i = 0; i < t.childCount; i++)
            Collect(t.GetChild(i), names, outList);
    }

    public static bool Match(string name, string[] names)
    {
        foreach (string n in names)
            if (name == n || name.StartsWith(n + "(") ||
                name.StartsWith(n + " "))
                return true;
        return false;
    }

    /// <summary>激活角色及其父链，返回被改过的对象（用于恢复）。</summary>
    public static List<GameObject> Activate(GameObject root)
    {
        List<GameObject> chain = new List<GameObject>();
        for (Transform t = root.transform; t != null; t = t.parent)
            if (!t.gameObject.activeSelf)
                chain.Add(t.gameObject);
        foreach (GameObject go in chain)
            go.SetActive(true);
        return chain;
    }

    public static void Restore(List<GameObject> chain)
    {
        for (int i = chain.Count - 1; i >= 0; i--)
            if (chain[i] != null)
                chain[i].SetActive(false);
    }

    /// <summary>逐个角色跑一遍：激活 -> 回调 -> 恢复。互不影响。</summary>
    public static void ForEach(string[] names, System.Action<GameObject> action)
    {
        List<GameObject> targets = Collect(names);
        for (int i = 0; i < targets.Count; i++)
        {
            GameObject root = targets[i];
            Debug.Log(string.Format("[Calib] ({0}/{1}) 导出 {2}",
                                    i + 1, targets.Count, root.name));
            List<GameObject> chain = Activate(root);
            try
            {
                action(root);
            }
            catch (System.Exception ex)
            {
                Debug.LogError("[Calib] " + root.name + " 失败: " +
                               ex.Message + "\n" + ex.StackTrace);
            }
            finally
            {
                Restore(chain);
            }
        }
    }

    /// <summary>截图前只保留该角色的渲染器，返回被关掉的那些（用于恢复）。</summary>
    public static List<Renderer> IsolateRenderers(GameObject root)
    {
        List<Renderer> off = new List<Renderer>();
        HashSet<Renderer> mine = new HashSet<Renderer>(
            root.GetComponentsInChildren<Renderer>(true));
        foreach (Renderer r in Object.FindObjectsByType<Renderer>(
                     FindObjectsInactive.Include, FindObjectsSortMode.None))
            if (!mine.Contains(r) && r.enabled)
            {
                r.enabled = false;
                off.Add(r);
            }
        return off;
    }

    public static void RestoreRenderers(List<Renderer> off)
    {
        foreach (Renderer r in off)
            if (r != null)
                r.enabled = true;
    }
}
