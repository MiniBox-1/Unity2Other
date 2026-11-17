var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/2DModel_3P_Alice_NS1_DL_N.uAnim.prefab");
var go = UnityEngine.Object.Instantiate(prefab);
go.SetActive(true);
var sb = new System.Text.StringBuilder();
sb.Append("{\"parts\":[");
bool first = true;
foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
    if (!r.transform.name.Contains("FullBodyIMG")) continue;
    if (!first) sb.Append(",");
    first = false;
    var chain = new System.Text.StringBuilder();
    var t = r.transform;
    int depth = 0;
    while (t != null && depth < 12) {
        chain.Append(t.name).Append(t.gameObject.activeSelf ? "[1]" : "[0]").Append(" < ");
        t = t.parent; depth++;
    }
    sb.Append("{\"n\":\"").Append(r.transform.name.Replace("\"", "'"))
      .Append("\",\"enabled\":").Append(r.enabled ? "1" : "0")
      .Append(",\"self\":").Append(r.gameObject.activeSelf ? "1" : "0")
      .Append(",\"chain\":\"").Append(chain.ToString().Replace("\"", "'")).Append("\"}");
}
sb.Append("]}");
System.IO.File.WriteAllText(@"D:\VB\Convert\Live2d\Products\_why_inactive.json", sb.ToString());
UnityEngine.Object.DestroyImmediate(go);
return "ok";
