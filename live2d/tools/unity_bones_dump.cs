string name = "2DModel_BR_Khan_N";
string part = "kh_parts_body";
string outPath = @"D:\VB\Convert\Live2d\Products\_unity_ref\" + name + ".bones.json";
var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
var go = UnityEngine.Object.Instantiate(prefab);
go.SetActive(true);
var sb = new System.Text.StringBuilder();
sb.Append("{\"parts\":[");
bool first = true;
foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
    if (!r.enabled) continue;
    var smr = r as UnityEngine.SkinnedMeshRenderer;
    if (smr == null) continue;
    if (smr.bones == null || smr.bones.Length == 0) continue;
    if (part != "" && r.transform.name != part) continue;
    if (!first) sb.Append(",");
    first = false;
    sb.Append("{\"name\":\"").Append(r.transform.name).Append("\",\"bones\":[");
    for (int i = 0; i < smr.bones.Length; i++) {
        var bn = smr.bones[i];
        if (i > 0) sb.Append(",");
        var m = bn.localToWorldMatrix;
        sb.Append("{\"n\":\"").Append(bn.name).Append("\",\"m\":[");
        for (int rr = 0; rr < 4; rr++) {
            for (int cc = 0; cc < 4; cc++) {
                if (rr > 0 || cc > 0) sb.Append(",");
                sb.Append(m[rr, cc].ToString("F6"));
            }
        }
        sb.Append("]}");
    }
    sb.Append("]}");
}
sb.Append("]}");
System.IO.File.WriteAllText(outPath, sb.ToString());
UnityEngine.Object.DestroyImmediate(go);
return "OK " + outPath;
