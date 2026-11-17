string[] names = new string[] { "2DModel_3P_Alice_NS1_DL_N" };
var sb = new System.Text.StringBuilder();
sb.Append("{\"parts\":[");
bool first = true;
foreach (var name in names) {
    var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
    if (prefab == null) continue;
    var go = UnityEngine.Object.Instantiate(prefab);
    go.SetActive(true);
    foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
        var sr = r as UnityEngine.SpriteRenderer;
        string spriteName = (sr != null && sr.sprite != null) ? sr.sprite.name : "";
        if (!first) sb.Append(",");
        first = false;
        sb.Append("{\"n\":\"").Append(r.transform.name.Replace("\"", "'"))
          .Append("\",\"sprite\":\"").Append(spriteName.Replace("\"", "'"))
          .Append("\",\"active\":").Append(r.enabled && r.gameObject.activeInHierarchy ? "true" : "false")
          .Append("}");
    }
    UnityEngine.Object.DestroyImmediate(go);
}
sb.Append("]}");
System.IO.File.WriteAllText(@"D:\VB\Convert\Live2d\Products\_sprite_names.json", sb.ToString());
return "ok";
