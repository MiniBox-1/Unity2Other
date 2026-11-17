string[] allNames = new string[] { "2DModel_BR_WarWolf_NS1", "2DModel_BR_Scathy_N", "2DModel_3P_Eternity_NS2" };
var sb = new System.Text.StringBuilder();
foreach (var name in allNames) {
    var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
    var go = UnityEngine.Object.Instantiate(prefab);
    go.SetActive(true);
    int total = 0, active0 = 0;
    foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) { total++; if (r.enabled && r.gameObject.activeInHierarchy) active0++; }
    var anim = go.GetComponentInChildren<UnityEngine.Animator>(true);
    if (anim != null) { anim.Rebind(); anim.Update(0.0f); }
    int active1 = 0;
    foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) { if (r.enabled && r.gameObject.activeInHierarchy) active1++; }
    UnityEngine.Object.DestroyImmediate(go);
    sb.Append(name).Append(": total=").Append(total).Append(" active=").Append(active0).Append(" afterAnim=").Append(active1).Append("\n");
}
return sb.ToString();
