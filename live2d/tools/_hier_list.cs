string[] allNames = new string[] { "2DModel_3P_Alice_NS1_DL_N","2DModel_BR_Emily_NS1_DL_N" };
string dir = @"D:\VB\Convert\Live2d\Products\_unity_ref\";
foreach (var name in allNames) {
    var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
    if (prefab == null) continue;
    var go = UnityEngine.Object.Instantiate(prefab);
    go.SetActive(true);
    var sb = new System.Text.StringBuilder();
    sb.Append("{\"parts\":[");
    bool first = true;
    foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
        if (!first) sb.Append(",");
        first = false;
        string path = r.transform.name;
        var t = r.transform.parent;
        int depth = 0;
        while (t != null && depth < 6) { path = t.name + "/" + path; t = t.parent; depth++; }
        var mats = r.sharedMaterials;
        string shader = (mats != null && mats.Length > 0 && mats[0] != null && mats[0].shader != null)
            ? mats[0].shader.name : "";
        sb.Append("{\"name\":\"").Append(r.transform.name.Replace("\"", "'")).Append("\"")
          .Append(",\"layer\":").Append(r.gameObject.layer)
          .Append(",\"layerName\":\"").Append(UnityEngine.LayerMask.LayerToName(r.gameObject.layer)).Append("\"")
          .Append(",\"tag\":\"").Append(r.gameObject.tag).Append("\"")
          .Append(",\"active\":").Append(r.enabled && r.gameObject.activeInHierarchy ? "true" : "false")
          .Append(",\"type\":\"").Append(r.GetType().Name).Append("\"")
          .Append(",\"shader\":\"").Append(shader).Append("\"")
          .Append(",\"path\":\"").Append(path.Replace("\"", "'")).Append("\"}");
    }
    sb.Append("]}");
    System.IO.File.WriteAllText(dir + name + ".hier.json", sb.ToString());
    UnityEngine.Object.DestroyImmediate(go);
}
return "hier dumped";
