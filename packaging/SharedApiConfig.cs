using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// .NET Framework 4.8 / C# 5. No network calls or plaintext credential files.
public static class SharedApiConfig
{
    const string Product = "ai-info-literacy-toolbox";
    const string Version = "1.3.0";
    const string Cipher = "AES-256-CBC+HMAC-SHA256";
    const string Kdf = "PBKDF2-HMAC-SHA256";
    const int Iterations = 250000;
    const int MaxFile = 1048576;
    static readonly string[] Providers = { "deepseek", "qwen", "openai" };
    static JavaScriptSerializer Json() { return new JavaScriptSerializer { MaxJsonLength = MaxFile, RecursionLimit = 40 }; }
    static void Clear(byte[] bytes) { if (bytes != null) Array.Clear(bytes, 0, bytes.Length); }
    static byte[] Random(int length) { byte[] value = new byte[length]; using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(value); return value; }
    static string Required(Dictionary<string, object> data, string key, int max)
    {
        object value;
        if (!data.TryGetValue(key, out value) || !(value is string) || String.IsNullOrWhiteSpace((string)value) || ((string)value).Length > max)
            throw new InvalidDataException("配置字段不完整或超出长度限制。");
        return (string)value;
    }
    static Dictionary<string, object> ReadJson(string path)
    {
        CheckPath(path);
        if (!File.Exists(path) || new FileInfo(path).Length > MaxFile) throw new InvalidDataException("配置文件不存在或过大。");
        return Parse(File.ReadAllText(path, Encoding.UTF8));
    }
    static Dictionary<string, object> Parse(string text)
    {
        var value = Json().DeserializeObject(text) as Dictionary<string, object>;
        if (value == null) throw new InvalidDataException("配置格式无效。");
        return value;
    }
    // Check every existing ancestor, including ancestors outside the selected root.
    static void CheckPath(string path)
    {
        string current = Path.GetFullPath(path);
        while (!String.IsNullOrEmpty(current))
        {
            try
            {
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("不能使用链接或联接点路径。");
            }
            catch (FileNotFoundException) { }
            catch (DirectoryNotFoundException) { }
            current = Path.GetDirectoryName(current);
        }
    }
    static void ValidateEndpoint(string value)
    {
        Uri uri;
        if (!Uri.TryCreate(value, UriKind.Absolute, out uri) || uri.Scheme != "https" || String.IsNullOrEmpty(uri.Host)
            || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0
            || uri.AbsolutePath.TrimEnd('/').EndsWith("/responses", StringComparison.OrdinalIgnoreCase)
            || uri.AbsolutePath.TrimEnd('/').EndsWith("/chat/completions", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("API 基础地址必须是无账号、查询参数及片段的 HTTPS 地址。");
    }
    static void ValidatePayload(Dictionary<string, object> payload)
    {
        if (payload.Count != 6) throw new InvalidDataException("共享配置字段无效。");
        foreach (string prefix in Providers)
        {
            string key = Required(payload, prefix + "_key", 16384);
            foreach (char c in key) if (Char.IsControl(c)) throw new InvalidDataException("密钥格式无效。");
            ValidateEndpoint(Required(payload, prefix + "_base_url", 2048));
        }
    }
    static byte[] Decode(Dictionary<string, object> value, string field, int min, int max)
    {
        string encoded = Required(value, field, (max + 2) / 3 * 4);
        byte[] decoded = Convert.FromBase64String(encoded);
        if (decoded.Length < min || decoded.Length > max || Convert.ToBase64String(decoded) != encoded)
            throw new InvalidDataException("加密配置格式无效。");
        return decoded;
    }
    static byte[] AuthenticationBytes(int iterations, byte[] salt, byte[] iv, byte[] ciphertext)
    {
        // Fixed metadata and canonical encodings are authenticated as well as the ciphertext.
        return Encoding.UTF8.GetBytes("1\n" + Product + "\n" + Version + "\n" + Kdf + "\n" + Cipher + "\n"
            + iterations.ToString(CultureInfo.InvariantCulture) + "\n" + Convert.ToBase64String(salt) + "\n"
            + Convert.ToBase64String(iv) + "\n" + Convert.ToBase64String(ciphertext));
    }
    static byte[] Derive(string password, byte[] salt, int iterations)
    {
        if (String.IsNullOrEmpty(password) || password.Length > 1024) throw new InvalidDataException("请输入有效的导入口令。");
        using (var pbkdf = new Rfc2898DeriveBytes(password, salt, iterations, HashAlgorithmName.SHA256)) return pbkdf.GetBytes(64);
    }
    static string Encrypt(Dictionary<string, object> payload, string password)
    {
        ValidatePayload(payload);
        byte[] salt = Random(32), iv = Random(16), keys = null, plain = null, encryptionKey = new byte[32], macKey = new byte[32];
        try
        {
            keys = Derive(password, salt, Iterations);
            Buffer.BlockCopy(keys, 0, encryptionKey, 0, 32); Buffer.BlockCopy(keys, 32, macKey, 0, 32);
            plain = Encoding.UTF8.GetBytes(Json().Serialize(payload));
            byte[] encrypted;
            using (Aes aes = Aes.Create())
            {
                aes.Key = encryptionKey; aes.IV = iv; aes.Mode = CipherMode.CBC; aes.Padding = PaddingMode.PKCS7;
                using (var transform = aes.CreateEncryptor()) encrypted = transform.TransformFinalBlock(plain, 0, plain.Length);
            }
            byte[] mac;
            using (var hmac = new HMACSHA256(macKey)) mac = hmac.ComputeHash(AuthenticationBytes(Iterations, salt, iv, encrypted));
            return Json().Serialize(new Dictionary<string, object> {
                {"format", 1}, {"productId", Product}, {"targetVersion", Version}, {"kdf", Kdf}, {"cipher", Cipher},
                {"iterations", Iterations}, {"salt", Convert.ToBase64String(salt)}, {"iv", Convert.ToBase64String(iv)},
                {"ciphertext", Convert.ToBase64String(encrypted)}, {"mac", Convert.ToBase64String(mac)} });
        }
        finally { Clear(keys); Clear(plain); Clear(encryptionKey); Clear(macKey); }
    }
    static Dictionary<string, object> Decrypt(string file, string password)
    {
        var value = ReadJson(file);
        if (value.Count != 10 || !value.ContainsKey("format") || !(value["format"] is int) || (int)value["format"] != 1
            || Required(value, "productId", 100) != Product || Required(value, "targetVersion", 20) != Version
            || Required(value, "kdf", 100) != Kdf || Required(value, "cipher", 100) != Cipher
            || !value.ContainsKey("iterations") || !(value["iterations"] is int))
            throw new InvalidDataException("共享配置版本或格式无效。");
        int iterations = (int)value["iterations"];
        if (iterations < 200000 || iterations > 1000000) throw new InvalidDataException("加密参数超出安全范围。");
        byte[] salt = Decode(value, "salt", 32, 32), iv = Decode(value, "iv", 16, 16),
            encrypted = Decode(value, "ciphertext", 16, 131072), mac = Decode(value, "mac", 32, 32);
        if (encrypted.Length % 16 != 0) throw new InvalidDataException("密文长度无效。");
        byte[] keys = null, encryptionKey = new byte[32], macKey = new byte[32], plain = null;
        try
        {
            keys = Derive(password, salt, iterations);
            Buffer.BlockCopy(keys, 0, encryptionKey, 0, 32); Buffer.BlockCopy(keys, 32, macKey, 0, 32);
            byte[] expected;
            using (var hmac = new HMACSHA256(macKey)) expected = hmac.ComputeHash(AuthenticationBytes(iterations, salt, iv, encrypted));
            int different = 0;
            for (int i = 0; i < mac.Length; i++) different |= mac[i] ^ expected[i];
            if (different != 0) throw new CryptographicException("导入口令错误或共享文件已损坏。未修改配置。");
            using (Aes aes = Aes.Create())
            {
                aes.Key = encryptionKey; aes.IV = iv; aes.Mode = CipherMode.CBC; aes.Padding = PaddingMode.PKCS7;
                using (var transform = aes.CreateDecryptor()) plain = transform.TransformFinalBlock(encrypted, 0, encrypted.Length);
            }
            var payload = Parse(new UTF8Encoding(false, true).GetString(plain));
            ValidatePayload(payload);
            return payload;
        }
        finally { Clear(keys); Clear(encryptionKey); Clear(macKey); Clear(plain); }
    }
    public static void Export(string credentialFile, string outputDirectory, string passwordFile)
    {
        string output = Path.GetFullPath(outputDirectory).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string passwordPath = Path.GetFullPath(passwordFile);
        string destination = Path.Combine(output, "shared-api.enc.json");
        CheckPath(output); CheckPath(passwordPath); CheckPath(credentialFile);
        if (!Directory.Exists(output) || File.Exists(destination) || File.Exists(passwordPath)
            || passwordPath.StartsWith(output, StringComparison.OrdinalIgnoreCase)
            || !Directory.Exists(Path.GetDirectoryName(passwordPath)))
            throw new InvalidDataException("请使用新的输出文件夹；口令文件须单独保存在共享包文件夹以外。");
        var source = ReadJson(credentialFile);
        var payload = new Dictionary<string, object>();
        try
        {
            foreach (string prefix in Providers)
            {
                byte[] protectedBytes = Convert.FromBase64String(Required(source, prefix + "_key", 65536));
                byte[] plain = null;
                try
                {
                    plain = ProtectedData.Unprotect(protectedBytes, null, DataProtectionScope.CurrentUser);
                    payload[prefix + "_key"] = new UTF8Encoding(false, true).GetString(plain);
                }
                finally { Clear(protectedBytes); Clear(plain); }
                payload[prefix + "_base_url"] = Required(source, prefix + "_base_url", 2048);
            }
            byte[] random = Random(32);
            string password;
            try { password = Convert.ToBase64String(random).TrimEnd('=').Replace('+', '-').Replace('/', '_'); }
            finally { Clear(random); }
            string envelope = Encrypt(payload, password);
            bool passwordCreated = false;
            try
            {
                WriteNew(passwordPath, password + Environment.NewLine); passwordCreated = true;
                WriteNew(destination, envelope);
            }
            catch { if (passwordCreated) File.Delete(passwordPath); throw; }
        }
        finally { payload.Clear(); source.Clear(); }
    }
    static void WriteNew(string path, string text)
    {
        using (var file = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        using (var writer = new StreamWriter(file, new UTF8Encoding(false))) { writer.Write(text); writer.Flush(); file.Flush(true); }
    }
    static string ValidateTarget(string root)
    {
        root = Path.GetFullPath(root);
        CheckPath(root);
        if (!Directory.Exists(root)) throw new InvalidDataException("请选择工具箱文件夹。");
        string backups = Path.Combine(root, "update-backups");
        CheckPath(backups);
        if (Directory.Exists(backups))
        {
            foreach (string directory in Directory.GetDirectories(backups))
            {
                CheckPath(directory);
                string journalFile = Path.Combine(directory, "journal.json");
                CheckPath(journalFile);
                if (!File.Exists(journalFile)) continue;
                var journal = ReadJson(journalFile);
                object status;
                string state = journal.TryGetValue("status", out status) ? Convert.ToString(status, CultureInfo.InvariantCulture) : "";
                if (state == "applying" || state == "validating" || state == "restoring-data" || state == "rollback-failed")
                    throw new InvalidDataException("发现未完成的离线升级，请先运行同一个升级程序完成恢复，再导入共享 API。");
            }
        }
        string manifest = Path.Combine(root, "build-manifest.json");
        var release = ReadJson(manifest);
        if (Required(release, "product", 100) != "AI信息素养工具箱_Windows免安装版" || Required(release, "version", 20) != Version)
            throw new InvalidDataException("请先将工具箱升级到 1.3.0，再导入共享 API。");
        object records;
        if (!release.TryGetValue("files", out records) || !(records is object[])) throw new InvalidDataException("工具箱版本清单不完整。");
        bool launcherDeclared = false;
        foreach (object record in (object[])records)
        {
            var item = record as Dictionary<string, object>;
            object path;
            if (item != null && item.TryGetValue("path", out path) && (path as string) == "AI信息素养工具箱.exe") launcherDeclared = true;
        }
        string launcher = Path.Combine(root, "AI信息素养工具箱.exe");
        string module = Path.Combine(root, "01_三AI同查");
        string data = Path.Combine(module, "data");
        string config = Path.Combine(data, "api-keys.dpapi.json");
        CheckPath(launcher); CheckPath(config);
        if (!launcherDeclared || !File.Exists(launcher) || !Directory.Exists(module) || !Directory.Exists(data))
            throw new InvalidDataException("请选择完整的 1.3.0 工具箱文件夹。");
        return config;
    }
    public static void Import(string root, string encryptedFile, string password)
    {
        string normalized = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string name;
        using (SHA256 hash = SHA256.Create())
            name = "Local\\InfoLiteracyToolbox-" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(normalized.ToLowerInvariant()))).Replace("-", "").ToUpperInvariant();
        using (var gate = new Mutex(false, name))
        {
            bool acquired = false;
            try
            {
                try { acquired = gate.WaitOne(0); }
                catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) throw new IOException("工具箱正在使用或升级，请关闭后再导入。");
                ImportExclusive(normalized, encryptedFile, password);
            }
            finally { if (acquired) gate.ReleaseMutex(); }
        }
    }
    static void ImportExclusive(string root, string encryptedFile, string password)
    {
        // All authentication, schema and path validation happens before the first write.
        string config = ValidateTarget(root);
        var payload = Decrypt(encryptedFile, password);
        var current = File.Exists(config) ? ReadJson(config) : new Dictionary<string, object>();
        string temporary = config + ".import-" + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            foreach (string prefix in Providers)
            {
                byte[] plain = Encoding.UTF8.GetBytes((string)payload[prefix + "_key"]);
                try { current[prefix + "_key"] = Convert.ToBase64String(ProtectedData.Protect(plain, null, DataProtectionScope.CurrentUser)); }
                finally { Clear(plain); }
                current[prefix + "_base_url"] = payload[prefix + "_base_url"];
            }
            CheckPath(config);
            WriteNew(temporary, Json().Serialize(current));
            CheckPath(config);
            if (File.Exists(config))
            {
                string backup = Path.Combine(Path.GetDirectoryName(config), "api-" + Guid.NewGuid().ToString("N") + ".bak");
                if (File.Exists(backup) || Directory.Exists(backup)) throw new IOException("备份文件已存在，请重新导入。");
                File.Replace(temporary, config, backup);
            }
            else File.Move(temporary, config);
        }
        finally { payload.Clear(); current.Clear(); if (File.Exists(temporary)) File.Delete(temporary); }
    }
}

internal sealed class SharedApiWindow : Form
{
    readonly TextBox folder = new TextBox(), password = new TextBox();
    readonly Label status = new Label();
    readonly Button import = new Button();
    public SharedApiWindow(string target)
    {
        Text = "导入共享 API 配置 · 1.3.0"; ClientSize = new Size(670, 360);
        StartPosition = FormStartPosition.CenterScreen; FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; Font = new Font("Microsoft YaHei UI", 10);
        var intro = new Label { Text = "将共享的 DeepSeek、千问、GPT 密钥保存到当前 Windows 账号。\r\n共享密钥的用量由提供者承担，请仅在获授权的团队内使用。", AutoSize = false };
        intro.SetBounds(20, 16, 630, 56);
        var label = new Label { Text = "选择已升级到 1.3.0 的工具箱文件夹：" }; label.SetBounds(20, 82, 600, 25);
        folder.ReadOnly = true; folder.Text = target ?? ""; folder.SetBounds(20, 111, 520, 30);
        var browse = new Button { Text = "选择…" }; browse.SetBounds(550, 109, 100, 32);
        browse.Click += delegate { using (var dialog = new FolderBrowserDialog { Description = "选择 AI信息素养工具箱.exe 所在文件夹" }) if (dialog.ShowDialog(this) == DialogResult.OK) folder.Text = dialog.SelectedPath; };
        var pwlabel = new Label { Text = "导入口令（由提供者单独发送）：" }; pwlabel.SetBounds(20, 155, 600, 25);
        password.UseSystemPasswordChar = true; password.MaxLength = 1024; password.SetBounds(20, 184, 630, 30);
        status.Text = "导入将覆盖这三个模型的密钥和地址，原本机加密配置会自动备份。\r\n请先关闭工具箱；共享文件须与本程序放在同一文件夹。";
        status.SetBounds(20, 232, 630, 65);
        import.Text = "导入并覆盖配置"; import.SetBounds(430, 305, 220, 36);
        import.Click += delegate {
            import.Enabled = false;
            try
            {
                SharedApiConfig.Import(folder.Text, Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "shared-api.enc.json"), password.Text);
                password.Clear(); status.Text = "导入成功。密钥已在当前 Windows 账号下加密保存，可打开工具箱使用。";
            }
            catch (Exception) { status.Text = "导入失败：请先关闭工具箱并完成升级，再核对口令、共享文件、1.3.0 工具箱路径及写入权限。"; }
            finally { import.Enabled = true; }
        };
        Controls.AddRange(new Control[] { intro, label, folder, browse, pwlabel, password, status, import });
        FormClosed += delegate { password.Clear(); };
    }
}

internal static class SharedApiProgram
{
    [STAThread]
    static void Main(string[] args)
    {
        try
        {
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += delegate { MessageBox.Show("操作失败，请关闭后重试。", "导入共享 API 配置"); };
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            string target = "";
            if (args.Length != 0)
            {
                if (args.Length != 2 || args[0] != "--target") throw new ArgumentException();
                target = Path.GetFullPath(args[1]);
            }
            using (var form = new SharedApiWindow(target)) Application.Run(form);
        }
        catch (Exception) { try { MessageBox.Show("导入程序无法启动，请检查 .NET Framework 4.8 及文件权限。", "导入共享 API 配置"); } catch { } }
    }
}
