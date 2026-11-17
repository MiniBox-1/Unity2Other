string[] allNames = new string[] { "2DModel_AGS_RheinRitter_NS1" };
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
        bool active = r.enabled && r.gameObject.activeInHierarchy;
        var sr = r as UnityEngine.SpriteRenderer;
        var smr = r as UnityEngine.SkinnedMeshRenderer;
        var mf = r.GetComponent<UnityEngine.MeshFilter>();
        string sprite = sr != null && sr.sprite != null ? sr.sprite.name : "";
        string mesh = smr != null && smr.sharedMesh != null ? smr.sharedMesh.name
                    : (mf != null && mf.sharedMesh != null ? mf.sharedMesh.name : "");
        var mats = r.sharedMaterials;
        string shader = (mats != null && mats.Length > 0 && mats[0] != null && mats[0].shader != null)
            ? mats[0].shader.name : "";
        if (!first) sb.Append(",");
        first = false;
        string pn = r.transform.name.Replace("\\", "/").Replace("\"", "'");
        var tex = sr != null && sr.sprite != null && sr.sprite.texture != null ? sr.sprite.texture.name
                : ((mats != null && mats.Length > 0 && mats[0] != null && mats[0].mainTexture != null)
                   ? mats[0].mainTexture.name : "");
        sb.Append("{\"name\":\"").Append(pn).Append("\",\"tex\":\"").Append(tex).Append("\"")
          .Append(",\"active\":").Append(active ? "true" : "false")
          .Append(",\"type\":\"").Append(r.GetType().Name).Append("\"")
          .Append(",\"sprite\":\"").Append(sprite).Append("\"")
          .Append(",\"mesh\":\"").Append(mesh).Append("\"")
          .Append(",\"shader\":\"").Append(shader).Append("\"}");
    }
    sb.Append("]}");
    System.IO.File.WriteAllText(dir + name + ".detail.json", sb.ToString());
    UnityEngine.Object.DestroyImmediate(go);
}
return "detail dumped";
