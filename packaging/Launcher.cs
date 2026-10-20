using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

sealed class Service
{
    public Process Process;
    public int Port;
    public string Url { get { return "http://127.0.0.1:" + Port; } }
}

sealed class Toolbox : IDisposable
{
    public static string VersionText()
    {
        try
        {
            var release = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"build-manifest.json"),Encoding.UTF8));
            return release.ContainsKey("version") ? Convert.ToString(release["version"]) : "1.0.0";
        }
        catch { return "未知版本"; }
    }
    public static void CheckPendingUpdate()
    {
        string backups=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"update-backups");
        if(!Directory.Exists(backups))return;
        foreach(string directory in Directory.GetDirectories(backups))
        {
            string file=Path.Combine(directory,"journal.json");
            if(!File.Exists(file))continue;
            var journal=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(file,Encoding.UTF8));
            string state=journal.ContainsKey("status") ? Convert.ToString(journal["status"]) : "";
            if(state=="applying"||state=="validating"||state=="restoring-data"||state=="rollback-failed")
                throw new InvalidOperationException("发现未完成的离线升级，请先重新运行同一个「双击升级.exe」完成恢复，再打开工具箱。个人数据与备份仍保留在原文件夹中。");
        }
    }
    public readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    public readonly string Logs;
    readonly ProcessGroup group = new ProcessGroup();
    readonly Dictionary<string, Service> services = new Dictionary<string, Service>();
    readonly Dictionary<string, Process> windows = new Dictionary<string, Process>();
    public string Python { get { return Path.Combine(Root, "runtime", "python", "python.exe"); } }
    public string Node { get { return Path.Combine(Root, "runtime", "node", "node.exe"); } }
    public Toolbox()
    {
        Logs = Path.Combine(Root, "logs");
        Directory.CreateDirectory(Logs);
        string probe = Path.Combine(Logs, ".write-test");
        File.WriteAllText(probe, "ok"); File.Delete(probe);
    }
    public static string Quote(string text)
    {
        // All arguments here are file paths or controlled literals, never commands.
        if (text.IndexOf('"') >= 0) throw new ArgumentException("路径不能包含双引号。");
        return "\"" + text.TrimEnd('\\') + "\"";
    }
    ProcessStartInfo StartInfo(string file, string arguments)
    {
        if (!File.Exists(file)) throw new FileNotFoundException("程序文件缺失，请重新完整解压压缩包。", file);
        ProcessStartInfo info = new ProcessStartInfo(file, arguments);
        info.WorkingDirectory = Root;
        info.UseShellExecute = false; info.CreateNoWindow = true;
        info.EnvironmentVariables.Remove("PYTHONHOME");
        info.EnvironmentVariables.Remove("PYTHONPATH");
        info.EnvironmentVariables.Remove("NODE_OPTIONS");
        info.EnvironmentVariables.Remove("NODE_PATH");
        info.EnvironmentVariables["PYTHONUTF8"] = "1";
        info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
        info.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        return info;
    }
    Process StartLogged(ProcessStartInfo info, string name)
    {
        info.RedirectStandardOutput = true; info.RedirectStandardError = true;
        info.StandardOutputEncoding = Encoding.UTF8; info.StandardErrorEncoding = Encoding.UTF8;
        string file = Path.Combine(Logs, name + ".log");
        object gate = new object();
        Action<string> append = delegate(string line)
        {
            if (line == null) return;
            lock (gate)
            {
                try { File.AppendAllText(file, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + line + Environment.NewLine, Encoding.UTF8); }
                catch (IOException) { }
            }
        };
        Process child = new Process(); child.StartInfo = info;
        child.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { append(e.Data); };
        child.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { append(e.Data); };
        child.Start(); group.Add(child);
        child.BeginOutputReadLine(); child.BeginErrorReadLine();
        return child;
    }
    public static bool Alive(Process child)
    {
        try { return child != null && !child.HasExited; } catch (InvalidOperationException) { return false; }
    }
    public void Desktop(string mode)
    {
        Process previous;
        if (windows.TryGetValue(mode, out previous) && Alive(previous)) return;
        string script = Path.Combine(Root, "01_三AI同查", mode == "ai" ? "desktop.ps1" : "configure_apis.ps1");
        string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        ProcessStartInfo info = StartInfo(powershell, "-NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File " + Quote(script));
        windows[mode] = StartLogged(info, mode);
    }
    static int FreePort()
    {
        TcpListener listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start(); int port = ((IPEndPoint)listener.LocalEndpoint).Port; listener.Stop(); return port;
    }
    public static string Get(string url)
    {
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
        request.Proxy = null; request.Timeout = 2000; request.ReadWriteTimeout = 2000;
        using (WebResponse response = request.GetResponse())
        using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8)) return reader.ReadToEnd();
    }
    public Service StartService(string name)
    {
        Service previous;
        if (services.TryGetValue(name, out previous) && Alive(previous.Process))
        {
            Get(previous.Url + (name == "exam" ? "/_portable/health" : "/api/health"));
            return previous;
        }
        for (int attempt = 0; attempt < 3; attempt++)
        {
            int port = FreePort();
            ProcessStartInfo info;
            if (name == "exam") info = StartInfo(Python, "-u " + Quote(Path.Combine(Root, "02_淘汰赛模考", "portable_server.py")) + " --port " + port);
            else
            {
                info = StartInfo(Node, Quote(Path.Combine(Root, "03_50知识点检验", "02_网站检测工具", "server.cjs")));
                info.EnvironmentVariables["CHECKER_PORT"] = port.ToString();
                info.EnvironmentVariables.Remove("CHECKER_REPORTS_DIR");
            }
            Service service = new Service(); service.Port = port; service.Process = StartLogged(info, name);
            string health = service.Url + (name == "exam" ? "/_portable/health" : "/api/health");
            DateTime deadline = DateTime.UtcNow.AddSeconds(25);
            while (Alive(service.Process) && DateTime.UtcNow < deadline)
            {
                try
                {
                    string response = Get(health);
                    if (response.Contains(name == "exam" ? "info-literacy-exam" : "info-literacy-checker"))
                    { services[name] = service; return service; }
                }
                catch (WebException) { }
                Thread.Sleep(150);
            }
            group.Stop(service.Process);
        }
        throw new InvalidOperationException("启动失败，请查看 logs\\" + name + ".log。确认已完整解压，且程序文件夹可以写入。");
    }
    public void StopServices()
    {
        foreach (Service service in services.Values) group.Stop(service.Process);
        services.Clear();
    }
    public string ExamAddress()
    {
        Service service;
        if (!services.TryGetValue("exam", out service) || !Alive(service.Process)) return "模考尚未启动";
        string text = "本机：" + service.Url;
        try
        {
            foreach (IPAddress ip in Dns.GetHostAddresses(Dns.GetHostName()))
                if (ip.AddressFamily == AddressFamily.InterNetwork && !IPAddress.IsLoopback(ip))
                    text += "    局域网：http://" + ip + ":" + service.Port;
        }
        catch (SocketException) { }
        return text;
    }
    public void Open(string target)
    {
        Process.Start(new ProcessStartInfo(target) { UseShellExecute = true });
    }
    public string PathFor(string relative) { return Path.Combine(Root, relative); }
    string Probe(string executable, string arguments)
    {
        ProcessStartInfo info = StartInfo(executable, arguments);
        info.RedirectStandardOutput = true; info.RedirectStandardError = true;
        info.StandardOutputEncoding = Encoding.UTF8; info.StandardErrorEncoding = Encoding.UTF8;
        using (Process process = Process.Start(info))
        {
            group.Add(process);
            Task<string> output = process.StandardOutput.ReadToEndAsync();
            Task<string> error = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(20000)) { group.Stop(process); throw new TimeoutException("运行组件自检超时。"); }
            Task.WaitAll(output, error);
            if (process.ExitCode != 0) throw new InvalidOperationException(error.Result);
            return output.Result.Trim();
        }
    }
    public Dictionary<string, object> Check()
    {
        Dictionary<string, object> result = new Dictionary<string, object>();
        result["checkedAt"] = DateTimeOffset.Now.ToString("o");
        result["python"] = Probe(Python, "-c " + Quote("import sys,ssl,sqlite3,flask,openpyxl; print(sys.version.split()[0]); print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version)"));
        result["node"] = Probe(Node, "--version");
        foreach (string path in new string[] { "01_三AI同查\\desktop.ps1", "01_三AI同查\\configure_apis.ps1",
            "03_50知识点检验\\01_网址清单\\50个知识点_网址清单.html",
            "03_50知识点检验\\04_网址导航网站\\knowledge-links\\dist\\index.html",
            "03_50知识点检验\\03_PDF参考资料\\_资料索引.html" })
            if (!File.Exists(PathFor(path))) throw new FileNotFoundException("缺少资料文件，请重新完整解压。", path);
        string[] pdfs = Directory.GetFiles(PathFor("03_50知识点检验\\03_PDF参考资料"), "*.pdf");
        if (pdfs.Length == 0) throw new InvalidOperationException("PDF 资料缺失。");
        result["pdfCount"] = pdfs.Length;
        Service exam = StartService("exam");
        result["examUrl"] = exam.Url;
        result["exam"] = Get(exam.Url + "/_portable/health");
        if (!Get(exam.Url + "/login").Contains("登录")) throw new InvalidOperationException("模考登录页面加载失败。");
        Service checker = StartService("checker");
        result["checkerUrl"] = checker.Url;
        result["checker"] = Get(checker.Url + "/api/state");
        // Record only summary data: the state can grow with the user's later scans.
        var state = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>((string)result["checker"]);
        result["checker"] = state["stats"];
        if (!Get(checker.Url + "/").Contains("检测")) throw new InvalidOperationException("网站检测页面加载失败。");
        if (!Get(checker.Url + "/knowledge/").Contains("网址导航")) throw new InvalidOperationException("知识点资料页面加载失败。");
        result["passed"] = true;
        return result;
    }
    public static void SaveJson(string file, object value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(file)));
        File.WriteAllText(file, new JavaScriptSerializer().Serialize(value), new UTF8Encoding(false));
    }
    public void Dispose() { group.Dispose(); }
}

sealed class MainWindow : Form
{
    readonly Toolbox toolbox;
    readonly Label status = new Label();
    readonly TextBox addresses = new TextBox();
    readonly List<Button> actions = new List<Button>();
    bool busy;
    public MainWindow(Toolbox instance)
    {
        toolbox = instance;
        Text = "AI＋信息素养工具箱"; StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 10F);
        AutoScaleMode = AutoScaleMode.Dpi; ClientSize = new Size(900, 710);
        MinimumSize = new Size(916, 749); MaximizeBox = false;
        BackColor = Color.FromArgb(245, 247, 251);
        Label title = new Label(); title.Text = "AI＋信息素养工具箱";
        title.Font = new Font(Font.FontFamily, 23F, FontStyle.Bold); title.SetBounds(32, 24, 830, 48); Controls.Add(title);
        Label subtitle = new Label(); subtitle.Text = "Windows 免安装版  ·  三个模块，一个入口  ·  v" + Toolbox.VersionText();
        subtitle.ForeColor = Color.FromArgb(90, 103, 123); subtitle.SetBounds(34, 79, 820, 27); Controls.Add(subtitle);
        Panel ai = Card(124, "01   三 AI 同查", "同一题目同时交给 GPT、千问和 DeepSeek，独立作答并比较。需要联网。\n首次使用先配置 API；代理按自己电脑的实际情况填写。");
        AddButton(ai, "打开", 635, 28, 132, delegate { toolbox.Desktop("ai"); });
        AddButton(ai, "配置 API", 635, 76, 132, delegate { toolbox.Desktop("config"); });
        Panel exam = Card(276, "02   淘汰赛模考", "全题库刷题、错题复习、个人与团队模考。刷题进度自动保存。\n自动打开浏览器；保持本工具箱窗口打开，即可继续答题。");
        AddButton(exam, "打开", 635, 28, 132, delegate { toolbox.Open(toolbox.StartService("exam").Url); });
        AddButton(exam, "管理员账号", 635, 76, 132, delegate
        {
            toolbox.StartService("exam");
            string file = toolbox.PathFor("02_淘汰赛模考\\data\\admin_credentials.txt");
            if (File.Exists(file)) toolbox.Open(file);
            else ShowMessage("管理员密码由本机 ADMIN_PASSWORD 配置指定。", "管理员账号");
        });
        Panel knowledge = Card(428, "03   50 知识点检验", "网址导航与本地 PDF 可离线查阅，网站实时检测需要联网。\n检测结果与人工审核记录自动保存在本程序文件夹中。");
        AddButton(knowledge, "知识点资料", 20, 91, 153, delegate { toolbox.Open(toolbox.StartService("checker").Url + "/knowledge/"); });
        AddButton(knowledge, "网站检测", 185, 91, 153, delegate { toolbox.Open(toolbox.StartService("checker").Url); });
        AddButton(knowledge, "PDF 资料", 350, 91, 153, delegate { toolbox.Open(toolbox.PathFor("03_50知识点检验\\03_PDF参考资料\\_资料索引.html")); });
        AddButton(knowledge, "原网址清单", 515, 91, 153, delegate { toolbox.Open(toolbox.PathFor("03_50知识点检验\\01_网址清单\\50个知识点_网址清单.html")); });
        addresses.ReadOnly = true; addresses.BorderStyle = BorderStyle.None;
        addresses.BackColor = BackColor; addresses.Font = new Font(Font.FontFamily, 9F);
        addresses.SetBounds(34, 582, 832, 24); addresses.Text = "模考启动后，这里显示可复制的本机和局域网地址。"; Controls.Add(addresses);
        AddButton(this, "环境自检", 32, 615, 130, delegate
        {
            Dictionary<string, object> result = toolbox.Check();
            Toolbox.SaveJson(Path.Combine(toolbox.Logs, "startup-check.json"), result);
            ShowMessage("自检通过：包内运行组件、模考和网站检测均已启动。\nPDF 资料完整；没有调用 AI 接口。\n\n报告保存在 logs\\startup-check.json。", "环境自检");
        });
        AddButton(this, "停止网页服务", 174, 615, 145, delegate { toolbox.StopServices(); });
        AddButton(this, "数据与日志", 331, 615, 130, delegate { toolbox.Open(toolbox.Root); });
        AddButton(this, "使用说明", 473, 615, 130, delegate { toolbox.Open(toolbox.PathFor("先读我_使用说明.txt")); });
        Button upgrade = new Button(); upgrade.Text = "离线升级"; upgrade.SetBounds(615,615,130,37);
        upgrade.FlatStyle = FlatStyle.Flat; upgrade.BackColor = Color.FromArgb(239,244,252);
        upgrade.ForeColor = Color.FromArgb(35,76,145); upgrade.Cursor = Cursors.Hand;
        Controls.Add(upgrade); actions.Add(upgrade);
        upgrade.Click += delegate
        {
            using (OpenFileDialog choose = new OpenFileDialog())
            {
                choose.Title = "选择已解压升级包中的「双击升级.exe」";
                choose.Filter = "离线升级程序 (*.exe)|*.exe";
                if (choose.ShowDialog(this) != DialogResult.OK) return;
                try
                {
                    // The updater stays outside the launcher's process group so
                    // it can replace this EXE after the current launcher exits.
                    ProcessStartInfo update = new ProcessStartInfo(choose.FileName,"--target " + Toolbox.Quote(toolbox.Root));
                    update.UseShellExecute = false; update.WorkingDirectory = Path.GetDirectoryName(choose.FileName);
                    Process.Start(update); Close();
                }
                catch (Exception error) { MessageBox.Show(this,error.Message,"无法打开升级程序"); }
            }
        };
        status.SetBounds(34, 673, 832, 25); status.Font = new Font(Font.FontFamily, 9F);
        status.ForeColor = Color.FromArgb(90, 103, 123); status.Text = "准备就绪。退出工具箱会同时关闭它启动的模块。"; Controls.Add(status);
        FormClosing += delegate(object sender, FormClosingEventArgs args)
        {
            if (busy) { args.Cancel = true; status.Text = "正在完成启动或自检，请稍候再退出。"; }
        };
    }
    Panel Card(int top, string heading, string description)
    {
        Panel panel = new Panel(); panel.SetBounds(32, top, 836, 140);
        panel.BackColor = Color.White; Controls.Add(panel);
        Label title = new Label(); title.Text = heading; title.Font = new Font(Font.FontFamily, 14F, FontStyle.Bold);
        title.SetBounds(20, 13, 590, 30); panel.Controls.Add(title);
        Label text = new Label(); text.Text = description; text.ForeColor = Color.FromArgb(90, 103, 123);
        text.Font = new Font(Font.FontFamily, 9.5F); text.SetBounds(20, 49, 595, 43); panel.Controls.Add(text);
        return panel;
    }
    void AddButton(Control parent, string text, int left, int top, int width, Action action)
    {
        Button button = new Button(); button.Text = text; button.SetBounds(left, top, width, 37);
        button.FlatStyle = FlatStyle.Flat; button.FlatAppearance.BorderColor = Color.FromArgb(206, 216, 232);
        button.BackColor = Color.FromArgb(239, 244, 252); button.ForeColor = Color.FromArgb(35, 76, 145);
        button.Cursor = Cursors.Hand; parent.Controls.Add(button); actions.Add(button);
        button.Click += delegate { Execute(action); };
    }
    void ShowMessage(string text, string title)
    {
        if (InvokeRequired) Invoke(new Action(delegate { MessageBox.Show(this, text, title); }));
        else MessageBox.Show(this, text, title);
    }
    async void Execute(Action action)
    {
        if (busy) return;
        busy = true; foreach (Button button in actions) button.Enabled = false;
        status.Text = "正在处理，请稍候…";
        try
        {
            await Task.Run(action);
            status.Text = "准备就绪。退出工具箱会同时关闭它启动的模块。";
        }
        catch (Exception error)
        {
            Toolbox.SaveJson(Path.Combine(toolbox.Logs, "last-error.json"), new { message = error.Message, at = DateTimeOffset.Now.ToString("o") });
            status.Text = "操作未完成，请查看提示或运行日志。";
            MessageBox.Show(this, error.Message, "未能完成操作", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally
        {
            addresses.Text = toolbox.ExamAddress(); busy = false;
            foreach (Button button in actions) button.Enabled = true;
        }
    }
}

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        bool check = args.Length > 0 && args[0] == "--check";
        string report = args.Length > 1 ? Path.GetFullPath(args[1]) : Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs", "startup-check.json");
        try
        {
            // Scope the single instance to this extracted copy, not every copy.
            string instanceName;
            using (var hash = System.Security.Cryptography.SHA256.Create())
                instanceName = "Local\\InfoLiteracyToolbox-" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(AppDomain.CurrentDomain.BaseDirectory.ToLowerInvariant()))).Replace("-", "");
            bool created;
            using (Mutex single = new Mutex(true, instanceName, out created))
            {
                if (!created)
                {
                    if (check) { Toolbox.SaveJson(report, new { passed = false, error = "请先关闭同目录下正在运行的工具箱，再执行自检。" }); return 2; }
                    MessageBox.Show("这个文件夹中的工具箱已经打开，请使用已有窗口。", "AI＋信息素养工具箱"); return 0;
                }
                Toolbox.CheckPendingUpdate();
                using (Toolbox toolbox = new Toolbox())
                {
                    if (check) { Toolbox.SaveJson(report, toolbox.Check()); return 0; }
                    Application.Run(new MainWindow(toolbox));
                }
            }
            return 0;
        }
        catch (Exception error)
        {
            if (check)
            {
                try { Toolbox.SaveJson(report, new { passed = false, error = error.Message }); } catch { }
            }
            else MessageBox.Show("启动失败：" + error.Message + "\n\n请完整解压到桌面或文档等可写文件夹后再启动。", "AI＋信息素养工具箱", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
