string[] allNames = new string[] { "2DModel_BR_WarWolf_NS1", "2DModel_BR_Scathy_N", "2DModel_3P_Eternity_NS2", "2DModel_AGS_RheinRitter_NS1" };
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
        if (!r.enabled || !r.gameObject.activeInHierarchy) continue;
        var mats = r.sharedMaterials;
        var m = (mats != null && mats.Length > 0) ? mats[0] : null;
        string shader = m != null && m.shader != null ? m.shader.name : "";
        string blend = "";
        if (m != null && m.HasProperty("_SrcBlend")) blend += "src=" + m.GetInt("_SrcBlend");
        if (m != null && m.HasProperty("_DstBlend")) blend += " dst=" + m.GetInt("_DstBlend");
        if (m != null && m.HasProperty("_BlendMode")) blend += " mode=" + m.GetInt("_BlendMode");
        if (!first) sb.Append(",");
        first = false;
        string pn = r.transform.name.Replace("\\", "/").Replace("\"", "'");
        sb.Append("{\"name\":\"").Append(pn).Append("\",\"type\":\"").Append(r.GetType().Name)
          .Append("\",\"shader\":\"").Append(shader)
          .Append("\",\"queue\":").Append(m != null ? m.renderQueue : -1)
          .Append(",\"blend\":\"").Append(blend).Append("\"}");
    }
    sb.Append("]}");
    System.IO.File.WriteAllText(dir + name + ".mats.json", sb.ToString());
    UnityEngine.Object.DestroyImmediate(go);
}
return "mats dumped";
