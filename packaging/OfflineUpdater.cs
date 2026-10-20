using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// Populated by JavaScriptSerializer rather than direct assignments.
#pragma warning disable 0649
sealed class ReleaseFile { public string path; public string sha256; public long bytes; }
sealed class Release { public string product; public string version; public ReleaseFile[] files; }
sealed class UpdateDescription
{
    public int format; public string productId, fromVersion, toVersion, baseManifestHash, targetManifestHash;
    public ReleaseFile[] files; public string[] delete, seedFiles;
}
#pragma warning restore 0649
sealed class SavedFile { public string path; public bool existed; }
sealed class SavedDirectory { public string path; public bool existed; }
sealed class Journal
{
    public string status, target, fromVersion, toVersion, error;
    public string recoveryData;
    public bool restoringSnapshot;
    public List<SavedFile> files = new List<SavedFile>();
    public List<SavedDirectory> directories = new List<SavedDirectory>();
}

sealed class UpdateEngine : IDisposable
{
    public const string Launcher = "AI信息素养工具箱.exe";
    static readonly string[] Mutable = { "01_三AI同查/data", "02_淘汰赛模考/data", "03_50知识点检验/02_网站检测工具/reports" };
    public readonly string Work;
    public readonly UpdateDescription Description;
    readonly Release before, after;
    readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
    public UpdateEngine()
    {
        Work = Path.Combine(Path.GetTempPath(),"literacy-update-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Work);
        try
        {
            using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            {
                if (resource == null) throw new InvalidOperationException("升级文件缺失，请重新获取完整升级包。");
                using (SHA256 hash = SHA256.Create())
                    if (Hex(hash.ComputeHash(resource)) != Bundle.Hash) throw new InvalidOperationException("升级包校验失败，未修改原程序。");
                resource.Position = 0;
                using (ZipArchive zip = new ZipArchive(resource,ZipArchiveMode.Read))
                {
                    var entries = new Dictionary<string,ZipArchiveEntry>(StringComparer.OrdinalIgnoreCase);
                    foreach (ZipArchiveEntry entry in zip.Entries)
                    {
                        if (entries.ContainsKey(entry.FullName)) throw new InvalidOperationException("升级包包含重复文件。");
                        entries.Add(entry.FullName,entry);
                    }
                    foreach (string name in new [] {"update.json","base-manifest.json","target-manifest.json"})
                        Extract(entries,name,Path.Combine(Work,name));
                    Description = json.Deserialize<UpdateDescription>(File.ReadAllText(Path.Combine(Work,"update.json"),Encoding.UTF8));
                    if (Description.format != 1 || Description.productId != "ai-info-literacy-toolbox") throw new InvalidOperationException("升级包格式不兼容。");
                    if (Hash(Path.Combine(Work,"base-manifest.json")) != Description.baseManifestHash || Hash(Path.Combine(Work,"target-manifest.json")) != Description.targetManifestHash)
                        throw new InvalidOperationException("版本清单校验失败。");
                    before = json.Deserialize<Release>(File.ReadAllText(Path.Combine(Work,"base-manifest.json"),Encoding.UTF8));
                    after = json.Deserialize<Release>(File.ReadAllText(Path.Combine(Work,"target-manifest.json"),Encoding.UTF8));
                    ValidateDescription();
                    foreach (ReleaseFile file in Description.files)
                    {
                        string destination = Within(Work,"payload/"+file.path);
                        Extract(entries,"files/"+file.path,destination);
                        if (new FileInfo(destination).Length != file.bytes || Hash(destination) != file.sha256) throw new InvalidOperationException("升级文件校验失败："+file.path);
                    }
                    if (entries.Count != 3 + Description.files.Length) throw new InvalidOperationException("升级包含有未声明的文件。");
                }
            }
        }
        catch { Dispose(); throw; }
    }
    static void Extract(Dictionary<string,ZipArchiveEntry> entries,string name,string destination)
    {
        ZipArchiveEntry entry;
        if (!entries.TryGetValue(name,out entry)) throw new InvalidOperationException("升级包缺少文件："+name);
        Directory.CreateDirectory(Path.GetDirectoryName(destination));
        using (Stream input = entry.Open()) using (FileStream output = File.Create(destination)) input.CopyTo(output);
    }
    static string Hex(byte[] value) { return BitConverter.ToString(value).Replace("-","").ToLowerInvariant(); }
    public static string Hash(string file) { using (SHA256 hash = SHA256.Create()) using (Stream stream = File.OpenRead(file)) return Hex(hash.ComputeHash(stream)); }
    static void SafePath(string path,bool allowManifest)
    {
        if (String.IsNullOrEmpty(path) || path.Contains('\\') || path.Contains(':') || path.StartsWith("/")) throw new InvalidOperationException("非法升级路径。");
        foreach (string part in path.Split('/'))
        {
            if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(" ") || part.EndsWith(".") || part.Any(c=>c<32)) throw new InvalidOperationException("非法升级路径。");
            string device = part.Split('.')[0].ToLowerInvariant();
            if (new [] {"con","prn","aux","nul","com1","com2","com3","com4","com5","com6","com7","com8","com9","lpt1","lpt2","lpt3","lpt4","lpt5","lpt6","lpt7","lpt8","lpt9"}.Contains(device)) throw new InvalidOperationException("非法升级路径。");
        }
        string lower = path.ToLowerInvariant();
        bool seed = path == "02_淘汰赛模考/data/source_questions.json" || path == "02_淘汰赛模考/data/source_bank.json"
            || path == "02_淘汰赛模考/data/reviewed_duplicate_groups.json";
        if ((lower.StartsWith("01_三ai同查/data/") || lower.StartsWith("02_淘汰赛模考/data/")) && !seed
            || lower.StartsWith("03_50知识点检验/02_网站检测工具/reports/") || lower.StartsWith("logs/") || lower.StartsWith("update-backups/")
            || (!allowManifest && lower == "build-manifest.json")) throw new InvalidOperationException("升级包不能覆盖个人数据："+path);
    }
    static Dictionary<string,ReleaseFile> Map(Release release)
    {
        if (release.product != "AI信息素养工具箱_Windows免安装版" || release.files == null) throw new InvalidOperationException("版本清单不属于本工具箱。");
        var result = new Dictionary<string,ReleaseFile>(StringComparer.OrdinalIgnoreCase);
        foreach (ReleaseFile file in release.files)
        {
            SafePath(file.path,false);
            if (result.ContainsKey(file.path) || file.sha256 == null || file.sha256.Length != 64 || file.bytes < 0) throw new InvalidOperationException("版本清单文件异常。");
            result.Add(file.path,file);
        }
        if (!result.ContainsKey(Launcher)) throw new InvalidOperationException("版本清单缺少工具箱入口。");
        return result;
    }
    void ValidateDescription()
    {
        var old = Map(before); var next = Map(after);
        string oldVersion = before.version ?? "1.0.0";
        if (oldVersion != Description.fromVersion || after.version != Description.toVersion || new Version(Description.toVersion) <= new Version(oldVersion)) throw new InvalidOperationException("升级版本号异常。");
        var changes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ReleaseFile file in Description.files)
        {
            ReleaseFile target,prior;
            SafePath(file.path,false);
            if (!changes.Add(file.path) || !next.TryGetValue(file.path,out target) || target.sha256 != file.sha256 || target.bytes != file.bytes || (old.TryGetValue(file.path,out prior) && prior.sha256 == file.sha256)) throw new InvalidOperationException("升级清单与目标版本不一致。");
        }
        if (next.Values.Count(file=>!old.ContainsKey(file.path) || old[file.path].sha256 != file.sha256) != changes.Count) throw new InvalidOperationException("升级清单不完整。");
        var deletes = new HashSet<string>(Description.delete,StringComparer.OrdinalIgnoreCase);
        if (deletes.Count != Description.delete.Length || !deletes.SetEquals(old.Keys.Where(path=>!next.ContainsKey(path)))) throw new InvalidOperationException("升级删除清单异常。");
        foreach (string path in deletes) SafePath(path,false);
        var expectedSeeds = changes.Where(path=>path == "02_淘汰赛模考/data/source_questions.json" || path == "02_淘汰赛模考/data/source_bank.json");
        if (!new HashSet<string>(Description.seedFiles).SetEquals(expectedSeeds)) throw new InvalidOperationException("题库更新清单异常。");
    }
    public static string Normalize(string root) { return Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar; }
    static string Within(string root,string relative)
    {
        string full = Path.GetFullPath(Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)));
        if (!full.StartsWith(Normalize(root),StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("升级路径超出所选文件夹。");
        string current = full;
        while (current != null && current.Length >= Normalize(root).TrimEnd('\\').Length)
        {
            if ((File.Exists(current)||Directory.Exists(current)) && (File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0) throw new InvalidOperationException("不支持通过链接或联接点更新："+current);
            current = Path.GetDirectoryName(current);
        }
        return full;
    }
    public static string MutexName(string root)
    {
        using (SHA256 hash=SHA256.Create()) return "Local\\InfoLiteracyToolbox-"+Hex(hash.ComputeHash(Encoding.UTF8.GetBytes(Normalize(root).ToLowerInvariant()))).ToUpperInvariant();
    }
    static void CopyTree(string source,string destination)
    {
        if ((File.GetAttributes(source)&FileAttributes.ReparsePoint)!=0) throw new InvalidOperationException("个人数据中存在链接，已停止升级。");
        Directory.CreateDirectory(destination);
        foreach (string file in Directory.GetFiles(source))
        {
            if ((File.GetAttributes(file)&FileAttributes.ReparsePoint)!=0) throw new InvalidOperationException("个人数据中存在链接，已停止升级。");
            File.Copy(file,Path.Combine(destination,Path.GetFileName(file)),true);
        }
        foreach (string directory in Directory.GetDirectories(source)) CopyTree(directory,Path.Combine(destination,Path.GetFileName(directory)));
    }
    static void Replace(string source,string destination)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destination));
        string temp=destination+".update-"+Guid.NewGuid().ToString("N")+".tmp";
        try
        {
            File.Copy(source,temp);
            if (File.Exists(destination)) File.Replace(temp,destination,null);
            else File.Move(temp,destination);
        }
        finally { if(File.Exists(temp))File.Delete(temp); }
    }
    void Save(string file,object value)
    {
        string temporary=file+".tmp";
        File.WriteAllText(temporary,json.Serialize(value),new UTF8Encoding(false));
        if(File.Exists(file))File.Replace(temporary,file,null); else File.Move(temporary,file);
    }
    void SetStatus(string backup,Journal journal,string status)
    {
        journal.status=status; Save(Path.Combine(backup,"journal.json"),journal);
    }
    void Restore(string root,string backup,Journal journal,bool restoreData=true)
    {
        if (!String.Equals(Normalize(root),Normalize(journal.target),StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("备份不属于所选工具箱。");
        if(restoreData)
        {
            journal.restoringSnapshot=true;
            SetStatus(backup,journal,"restoring-data");
        }
        var missingDirectories=new HashSet<string>(journal.directories.Where(item=>!Directory.Exists(Within(root,item.path))).Select(item=>item.path));
        foreach(SavedFile file in journal.files)
        {
            SafePath(file.path,true);
            string target=Within(root,file.path);
            if(file.existed)Replace(Within(backup,"program/"+file.path),target);
            else if(File.Exists(target))File.Delete(target);
        }
        foreach(SavedDirectory directory in journal.directories)
        {
            if(!Mutable.Contains(directory.path))throw new InvalidOperationException("备份数据目录异常。");
            string target=Within(root,directory.path);
            if(!restoreData)
            {
                if(directory.existed&&missingDirectories.Contains(directory.path))CopyTree(Within(backup,"userdata/"+directory.path),target);
                continue;
            }
            if(Directory.Exists(target))
            {
                // Validate every entry before recursive deletion, including links.
                CheckTree(target); Directory.Delete(target,true);
            }
            if(directory.existed)CopyTree(Within(backup,"userdata/"+directory.path),target);
        }
        journal.restoringSnapshot=false;
        SetStatus(backup,journal,"rolled-back");
    }
    static void CheckTree(string directory)
    {
        if((File.GetAttributes(directory)&FileAttributes.ReparsePoint)!=0)throw new InvalidOperationException("数据目录存在链接，不能自动恢复。");
        foreach(string entry in Directory.GetFileSystemEntries(directory))
        {
            if((File.GetAttributes(entry)&FileAttributes.ReparsePoint)!=0)throw new InvalidOperationException("数据目录存在链接，不能自动恢复。");
            if(Directory.Exists(entry))CheckTree(entry);
        }
    }
    List<string> Recover(string root)
    {
        var preserved=new List<string>();
        string backups=Within(root,"update-backups");
        if(!Directory.Exists(backups))return preserved;
        foreach(string backup in Directory.GetDirectories(backups).OrderBy(value=>value))
        {
            if((File.GetAttributes(backup)&FileAttributes.ReparsePoint)!=0)throw new InvalidOperationException("升级备份目录存在链接。");
            string file=Path.Combine(backup,"journal.json");
            if(!File.Exists(file))continue;
            Journal journal=json.Deserialize<Journal>(File.ReadAllText(file,Encoding.UTF8));
            if(new []{"applying","validating","restoring-data","rollback-failed"}.Contains(journal.status))
            {
                // An original v1 EXE may still have been present when interrupted.
                // Preserve any work saved afterwards, both in place and separately.
                // Keep rescue data beside transaction backups. Nesting another
                // GUID below a backup can exceed .NET Framework's MAX_PATH.
                string current=Within(root,"update-backups/recovery-"+Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(current);
                foreach(string path in Mutable)
                    if(Directory.Exists(Within(root,path)))CopyTree(Within(root,path),Within(current,path));
                journal.recoveryData=current;Save(file,journal);
                // A partial snapshot restoration must be completed, rather than
                // mistaking a half-restored directory for newer complete data.
                bool finishSnapshot=journal.restoringSnapshot||journal.status=="restoring-data";
                Restore(root,backup,journal,finishSnapshot);preserved.Add(current);
            }
        }
        return preserved;
    }
    string Run(string executable,string arguments,string root,string log,int timeout)
    {
        var start=new ProcessStartInfo(executable,arguments);
        start.UseShellExecute=false;start.CreateNoWindow=true;start.WorkingDirectory=root;
        start.RedirectStandardOutput=true;start.RedirectStandardError=true;
        start.StandardOutputEncoding=Encoding.UTF8;start.StandardErrorEncoding=Encoding.UTF8;
        foreach(string name in new []{"PYTHONHOME","PYTHONPATH","NODE_OPTIONS","NODE_PATH","ADMIN_PASSWORD"})start.EnvironmentVariables.Remove(name);
        start.EnvironmentVariables["PYTHONUTF8"]="1";start.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"]="1";
        using(ProcessGroup children=new ProcessGroup())
        using(Process process=Process.Start(start))
        {
            children.Add(process,true);
            Task<string> output=process.StandardOutput.ReadToEndAsync(),error=process.StandardError.ReadToEndAsync();
            if(!process.WaitForExit(timeout))
            {
                var kill=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"taskkill.exe"),"/PID "+process.Id+" /T /F");
                kill.UseShellExecute=false;kill.CreateNoWindow=true;
                using(Process stopper=Process.Start(kill))stopper.WaitForExit(5000);
                process.WaitForExit(5000);throw new TimeoutException("升级后验证超时，正在恢复旧版本。");
            }
            Task.WaitAll(output,error);
            File.AppendAllText(log,output.Result+error.Result,Encoding.UTF8);
            if(process.ExitCode!=0)throw new InvalidOperationException("升级后验证未通过，已停止更新。详情见备份文件夹的 validation.log。");
            return output.Result;
        }
    }
    static string Quote(string text)
    {
        if(text.Contains('"'))throw new InvalidOperationException("路径不能包含双引号。");
        return "\""+text.TrimEnd('\\')+"\"";
    }
    public Dictionary<string,object> Apply(string selected,Action<string> progress)
    {
        string root=Normalize(selected);
        Within(root,"build-manifest.json");
        if(!File.Exists(Within(root,Launcher))||!File.Exists(Within(root,"build-manifest.json")))throw new InvalidOperationException("请选择原工具箱 EXE 所在的完整文件夹。");
        if(Assembly.GetExecutingAssembly().Location.StartsWith(root,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("请先将升级包解压到原工具箱文件夹以外的位置，再运行升级。");
        using(Mutex gate=new Mutex(false,MutexName(root)))
        {
            bool acquired;
            try { acquired=gate.WaitOne(0); } catch(AbandonedMutexException){ acquired=true; }
            if(!acquired)throw new InvalidOperationException("工具箱仍在运行，请先关闭原工具箱和答题窗口，再点击开始升级。");
            try
            {
                progress("检查并恢复上次未完成的升级…");List<string> recovered=Recover(root);
                string manifest=Within(root,"build-manifest.json");
                if(Hash(manifest)==Description.targetManifestHash)throw new InvalidOperationException("当前文件夹已经是 v"+Description.toVersion+"，无需重复升级。");
                if(Hash(manifest)!=Description.baseManifestHash)throw new InvalidOperationException("原版本与此升级包不匹配。此包适用于 v"+Description.fromVersion+" → v"+Description.toVersion+"。");
                progress("检查原版本与文件完整性…");
                var old=Map(before);
                foreach(ReleaseFile file in before.files)
                {
                    string original=Within(root,file.path);
                    if(!File.Exists(original)||Hash(original)!=file.sha256)throw new InvalidOperationException("原程序文件已修改或缺失，未执行升级："+file.path);
                }
                foreach(ReleaseFile file in Description.files)
                    if(!old.ContainsKey(file.path)&&(File.Exists(Within(root,file.path))||Directory.Exists(Within(root,file.path))))throw new InvalidOperationException("新增文件位置已被占用，未覆盖："+file.path);
                foreach(string directory in Mutable)if(Directory.Exists(Within(root,directory)))CheckTree(Within(root,directory));
                string database=Within(root,"02_淘汰赛模考/data/platform.db");
                if(File.Exists(database))using(FileStream check=new FileStream(database,FileMode.Open,FileAccess.ReadWrite,FileShare.None)){}
                string backup=Within(root,"update-backups/"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(backup);
                Journal journal=new Journal{target=root,fromVersion=Description.fromVersion,toVersion=Description.toVersion};
                progress("备份程序与个人数据…");
                foreach(string path in Description.files.Select(file=>file.path).Concat(Description.delete).Concat(new []{"build-manifest.json"}).Distinct(StringComparer.OrdinalIgnoreCase))
                {
                    string original=Within(root,path);
                    journal.files.Add(new SavedFile{path=path,existed=File.Exists(original)});
                    if(File.Exists(original))
                    {
                        string saved=Within(backup,"program/"+path);Directory.CreateDirectory(Path.GetDirectoryName(saved));File.Copy(original,saved);
                    }
                }
                foreach(string path in Mutable)
                {
                    string original=Within(root,path);bool existed=Directory.Exists(original);
                    journal.directories.Add(new SavedDirectory{path=path,existed=existed});
                    if(existed)CopyTree(original,Within(backup,"userdata/"+path));
                }
                SetStatus(backup,journal,"prepared");
                try
                {
                    SetStatus(backup,journal,"applying");progress("替换本次更新的程序文件…");
                    foreach(ReleaseFile file in Description.files)Replace(Within(Work,"payload/"+file.path),Within(root,file.path));
                    foreach(string path in Description.delete)if(File.Exists(Within(root,path)))File.Delete(Within(root,path));
                    SetStatus(backup,journal,"validating");progress("验证新版本，保留题库与成绩…");
                    string log=Path.Combine(backup,"validation.log");
                    string arguments="-B "+Quote(Within(root,"02_淘汰赛模考/upgrade_data.py"))+" --verify";
                    foreach(string seed in Description.seedFiles)arguments+=" --seed "+Quote(Path.GetFileName(seed));
                    Run(Within(root,"runtime/python/python.exe"),arguments,root,log,120000);
                    Run(Within(root,"runtime/node/node.exe"),"--check "+Quote(Within(root,"03_50知识点检验/02_网站检测工具/server.cjs")),root,log,30000);
                    foreach(ReleaseFile file in after.files)if(Hash(Within(root,file.path))!=file.sha256)throw new InvalidOperationException("升级后文件复核失败："+file.path);
                    Replace(Path.Combine(Work,"target-manifest.json"),manifest);
                    SetStatus(backup,journal,"committed");progress("升级完成，个人数据已保留。");
                    return new Dictionary<string,object>{{"passed",true},{"version",Description.toVersion},{"backup",backup},{"changedFiles",Description.files.Length},{"recoveredDataCopies",recovered}};
                }
                catch(Exception error)
                {
                    journal.error=error.Message;progress("升级未完成，正在恢复升级前状态…");
                    try
                    {
                        if(!acquired)throw new InvalidOperationException("请关闭新打开的工具箱，再重新运行升级程序恢复。");
                        Restore(root,backup,journal);
                    }
                    catch(Exception recovery)
                    {
                        journal.error+="；恢复提示："+recovery.Message;SetStatus(backup,journal,"rollback-failed");
                        throw new InvalidOperationException("升级未完成，请关闭工具箱后再次运行本升级程序恢复。备份："+backup,recovery);
                    }
                    throw new InvalidOperationException("升级未完成，已恢复升级前的程序与个人数据。\n"+error.Message+"\n备份："+backup,error);
                }
            }
            finally{if(acquired)gate.ReleaseMutex();}
        }
    }
    public static void Report(string file,object value)
    {
        if(String.IsNullOrEmpty(file))return;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(file)));
        File.WriteAllText(file,new JavaScriptSerializer().Serialize(value),new UTF8Encoding(false));
    }
    public void Dispose()
    {
        if(Work!=null&&Directory.Exists(Work)&&Path.GetFileName(Work).StartsWith("literacy-update-"))
            try{CheckTree(Work);Directory.Delete(Work,true);}catch(IOException){}catch(UnauthorizedAccessException){}
    }
}

sealed class UpgradeWindow : Form
{
    readonly UpdateEngine engine;
    readonly TextBox target=new TextBox();
    readonly Label status=new Label();
    readonly Button start=new Button(),browse=new Button();
    bool running;
    public UpgradeWindow(UpdateEngine value,string initial)
    {
        engine=value;Text="AI＋信息素养工具箱 · 离线升级";StartPosition=FormStartPosition.CenterScreen;
        Font=new Font("Microsoft YaHei UI",10F);AutoScaleMode=AutoScaleMode.Dpi;ClientSize=new Size(730,355);FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;
        Label title=new Label{Text="离线升级  v"+engine.Description.fromVersion+" → v"+engine.Description.toVersion,Font=new Font(Font.FontFamily,18F,FontStyle.Bold)};
        title.SetBounds(24,22,680,42);Controls.Add(title);
        Label note=new Label{Text="请先关闭原工具箱。选择原程序所在文件夹，升级时会备份并保留个人数据。\n升级完成后，继续打开原文件夹中的工具箱即可。"};note.SetBounds(26,78,680,55);Controls.Add(note);
        Label label=new Label{Text="原工具箱文件夹"};label.SetBounds(26,149,620,25);Controls.Add(label);
        target.SetBounds(26,180,545,28);target.Text=initial??"";Controls.Add(target);
        browse.Text="选择文件夹";browse.SetBounds(584,177,120,35);Controls.Add(browse);
        browse.Click+=delegate{using(FolderBrowserDialog dialog=new FolderBrowserDialog()){dialog.Description="选择原 AI信息素养工具箱.exe 所在的文件夹";dialog.SelectedPath=target.Text;if(dialog.ShowDialog(this)==DialogResult.OK)target.Text=dialog.SelectedPath;}};
        status.Text="就绪。此次只更新变化文件，不需要联网。";status.SetBounds(26,230,678,48);Controls.Add(status);
        start.Text="开始升级";start.SetBounds(534,292,170,40);Controls.Add(start);
        start.Click+=async delegate
        {
            if(running)return;
            string selected=target.Text.Trim();if(!Directory.Exists(selected)){MessageBox.Show(this,"请选择原工具箱文件夹。");return;}
            running=true;start.Enabled=browse.Enabled=target.Enabled=false;
            try
            {
                var result=await Task.Run(()=>engine.Apply(selected,text=>BeginInvoke(new Action(()=>status.Text=text))));
                MessageBox.Show(this,"升级完成，API 配置、账号、题库、成绩和审核记录已保留。\n\n现在可以打开原文件夹中的工具箱。\n备份："+result["backup"],"升级完成");
                start.Text="升级完成";
            }
            catch(Exception error){status.Text="升级未完成，请查看提示。";MessageBox.Show(this,error.Message,"升级提示",MessageBoxButtons.OK,MessageBoxIcon.Warning);start.Enabled=browse.Enabled=target.Enabled=true;}
            finally{running=false;}
        };
        FormClosing+=delegate(object sender,FormClosingEventArgs args){if(running){args.Cancel=true;status.Text="正在升级或恢复，请等待完成后再关闭。";}};
    }
}

static class UpdaterProgram
{
    [STAThread]
    static int Main(string[] args)
    {
        bool apply=false;string target=null,report=null;
        for(int i=0;i<args.Length;i++)
        {
            if(args[i]=="--apply")apply=true;
            else if(args[i]=="--target"&&i+1<args.Length)target=args[++i];
            else if(args[i]=="--report"&&i+1<args.Length)report=args[++i];
        }
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        try
        {
            using(UpdateEngine engine=new UpdateEngine())
            {
                if(apply){if(target==null)throw new InvalidOperationException("缺少原工具箱目录。");UpdateEngine.Report(report,engine.Apply(target,delegate(string text){}));}
                else Application.Run(new UpgradeWindow(engine,target));
            }
            return 0;
        }
        catch(Exception error)
        {
            if(apply){try{UpdateEngine.Report(report,new{passed=false,error=error.Message});}catch{}}
            else MessageBox.Show(error.Message,"离线升级提示",MessageBoxButtons.OK,MessageBoxIcon.Warning);
            return 1;
        }
    }
}
