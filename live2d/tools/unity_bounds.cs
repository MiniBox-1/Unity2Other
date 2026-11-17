string name = "2DModel_BR_Khan_N";
string outPath = @"D:\VB\Convert\Live2d\Products\_unity_ref\" + name + ".bounds.json";
var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
if (prefab == null) return "ERR prefab not found";
var go = UnityEngine.Object.Instantiate(prefab);
go.SetActive(true);
foreach (var t in go.GetComponentsInChildren<UnityEngine.Transform>(true)) t.gameObject.SetActive(true);
foreach (var r0 in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) r0.enabled = true;
var sb = new System.Text.StringBuilder();
sb.Append("{\"parts\":[");
var rs = go.GetComponentsInChildren<UnityEngine.Renderer>(true);
bool first = true;
foreach (var r in rs) {
    var b = r.bounds;
    if (!first) sb.Append(",");
    first = false;
    string p = r.transform.name.Replace("\\", "/").Replace("\"", "'");
    sb.Append("{\"name\":\"" + p + "\",\"c\":[" + b.center.x.ToString("F4") + "," + b.center.y.ToString("F4") + "],\"s\":[" + b.size.x.ToString("F4") + "," + b.size.y.ToString("F4") + "],\"k\":\"" + r.GetType().Name + "\"}");
}
sb.Append("]}");
System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(outPath));
System.IO.File.WriteAllText(outPath, sb.ToString());
UnityEngine.Object.DestroyImmediate(go);
return "OK parts=" + rs.Length + " -> " + outPath;
