using System;
using UnityEditor;
using UnityEngine;

public class RemoveMissingScripts : EditorWindow
{
    static int m_goCount;
    static int m_missingCount;

    [MenuItem("Çå³ý/Remove Missing Scripts")]
    static void Apply()
    {
        var beginTime = System.DateTime.UtcNow.Ticks;

        m_goCount = 0;
        m_missingCount = 0;
        foreach (var go in Selection.gameObjects)
        {
            search(go);
            var co=go.GetComponent<Collider2D>();
            DestroyImmediate(co);
        }
            

        var endTime = System.DateTime.UtcNow.Ticks;
        var deltaTime = endTime - beginTime;

        Debug.Log($"Searched in {m_goCount} GameObjects, found and removed {m_missingCount} missing scripts. Took {deltaTime / 10000.0} ms.");
    }

    static void search(GameObject go)
    {
        m_goCount++;
        m_missingCount += GameObjectUtility.RemoveMonoBehavioursWithMissingScript(go);
        foreach (Transform child in go.transform)
            search(child.gameObject);
    }
    [MenuItem("Çå³ý/RemoveColl")]
    public static void DelS()
    {
        foreach(var id in Selection.assetGUIDs)
        {
            string path=AssetDatabase.GUIDToAssetPath(id);
            GameObject go=AssetDatabase.LoadAssetAtPath<GameObject>(path);
            del(go);
        }
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log("end");
    }

    static void del(GameObject go)
    {
        foreach (Transform child in go.transform)
        {
            del(child.gameObject);
            if (child.gameObject.name== "specialTouch")
            {
                DestroyImmediate(child.gameObject, true);
                return;
            }
            BoxCollider co=null;
            if (go.TryGetComponent(out co))
            {
                Debug.Log("del");
                DestroyImmediate(co);
            }
            
        }
            
    }
    [MenuItem("Çå³ý/DelEvent")]
    static void events()
    {
        string[] uids = AssetDatabase.FindAssets("t:AnimationClip", new string[] { "Assets/rawLo/alice" });
        string path;
        for (int i = 0; i < uids.Length; i++)
        {
            path = AssetDatabase.GUIDToAssetPath(uids[i]);
            var ac = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            var names = AnimationUtility.GetAnimationEvents(ac);
            AnimationEvent ae = null;
            foreach (var name in names)
            {
                if (name.functionName != "EventDynamicBone")
                {
                    ae = name;
                }

            }
            if (ae != null)
            {
                AnimationUtility.SetAnimationEvents(ac, new AnimationEvent[1] { ae });
                AssetDatabase.SaveAssets();
            }
            else
            {
                AnimationUtility.SetAnimationEvents(ac, new AnimationEvent[0]);
                AssetDatabase.SaveAssets();
            }
        }
    }
}
