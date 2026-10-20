using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

// This test-only console entry point is never included in the distributed helper.
internal static class SharedApiTestHost
{
    static readonly string[] Providers = { "deepseek", "qwen", "openai" };
    static int Main(string[] args)
    {
        try
        {
            if (args[0] == "fixture")
            {
                var value = new Dictionary<string, object>();
                foreach (string prefix in Providers)
                {
                    byte[] plain = Encoding.UTF8.GetBytes("FAKE-ONLY-TEST-" + prefix);
                    try { value[prefix + "_key"] = Convert.ToBase64String(ProtectedData.Protect(plain, null, DataProtectionScope.CurrentUser)); }
                    finally { Array.Clear(plain, 0, plain.Length); }
                    value[prefix + "_base_url"] = args.Length > 2 ? args[2] : "https://example.invalid/" + prefix;
                }
                value["future_thinking"] = new Dictionary<string, object> { { "mode", "high" }, { "enabled", false } };
                value["future_array"] = new object[] { 1, "keep" };
                File.WriteAllText(args[1], new JavaScriptSerializer().Serialize(value), new UTF8Encoding(false));
            }
            else if (args[0] == "export") SharedApiConfig.Export(args[1], args[2], args[3]);
            else if (args[0] == "import") SharedApiConfig.Import(args[1], args[2], args[3]);
            else if (args[0] == "hold-gate")
            {
                string normalized = Path.GetFullPath(args[1]).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                string name;
                using (SHA256 hash = SHA256.Create())
                    name = "Local\\InfoLiteracyToolbox-" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(normalized.ToLowerInvariant()))).Replace("-", "").ToUpperInvariant();
                using (var gate = new Mutex(false, name))
                {
                    if (!gate.WaitOne(0)) throw new Exception();
                    try { Console.WriteLine("HELD"); Console.Out.Flush(); Console.ReadLine(); }
                    finally { gate.ReleaseMutex(); }
                }
            }
            else if (args[0] == "prefill")
            {
                using (var window = new SharedApiWindow(args[1]))
                {
                    if (window.Visible) throw new Exception();
                    bool found = false;
                    foreach (System.Windows.Forms.Control control in window.Controls)
                    {
                        var box = control as System.Windows.Forms.TextBox;
                        if (box != null && box.ReadOnly && box.Text == args[1]) found = true;
                        if (box != null && box.UseSystemPasswordChar && box.Text.Length != 0) throw new Exception();
                    }
                    if (!found) throw new Exception();
                }
            }
            else if (args[0] == "verify")
            {
                var value = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(args[1]));
                foreach (string prefix in Providers)
                {
                    byte[] plain = ProtectedData.Unprotect(Convert.FromBase64String((string)value[prefix + "_key"]), null, DataProtectionScope.CurrentUser);
                    try { if (Encoding.UTF8.GetString(plain) != "FAKE-ONLY-TEST-" + prefix) throw new Exception(); }
                    finally { Array.Clear(plain, 0, plain.Length); }
                    if ((string)value[prefix + "_base_url"] != "https://example.invalid/" + prefix) throw new Exception();
                }
            }
            else throw new Exception();
            Console.WriteLine("OK"); return 0;
        }
        catch (Exception) { Console.Error.WriteLine("FAILED (details suppressed to protect credentials)"); return 1; }
    }
}
