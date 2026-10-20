using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

static class LauncherUiCheck
{
    [DllImport("kernel32.dll")]static extern uint SetErrorMode(uint value);
    [STAThread]
    static int Main(string[] args)
    {
        SetErrorMode(3);
        try{return Run(args);}
        catch(Exception error)
        {
            Directory.CreateDirectory(args[1]);
            File.WriteAllText(Path.Combine(args[1],"launcher-ui-error.log"),error.ToString());return 1;
        }
    }
    static int Run(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Assembly assembly = Assembly.LoadFrom(args[0]);
        Type toolboxType = assembly.GetType("Toolbox", true);
        Type windowType = assembly.GetType("MainWindow", true);
        using (IDisposable toolbox = (IDisposable)Activator.CreateInstance(toolboxType, true))
        using (Form form = (Form)Activator.CreateInstance(windowType, new object[] { toolbox }))
        {
            form.StartPosition = FormStartPosition.Manual;
            form.Location = new Point(-15000, -15000);
            form.Show(); Application.DoEvents();
            Directory.CreateDirectory(args[1]);
            using (Bitmap bitmap = new Bitmap(form.Width, form.Height))
            {
                form.DrawToBitmap(bitmap, new Rectangle(0, 0, form.Width, form.Height));
                bitmap.Save(Path.Combine(args[1], "统一入口.png"));
            }
            MethodInfo execute = windowType.GetMethod("Execute", BindingFlags.Instance | BindingFlags.NonPublic);
            FieldInfo busy = windowType.GetField("busy", BindingFlags.Instance | BindingFlags.NonPublic);
            Action slowAction = delegate { Thread.Sleep(1200); };
            Stopwatch clock = Stopwatch.StartNew();
            execute.Invoke(form, new object[] { slowAction });
            long largestPause = 0;
            do
            {
                long before = clock.ElapsedMilliseconds;
                Application.DoEvents();
                largestPause = Math.Max(largestPause, clock.ElapsedMilliseconds - before);
                Thread.Sleep(15);
            } while ((bool)busy.GetValue(form) && clock.ElapsedMilliseconds < 5000);
            if ((bool)busy.GetValue(form) || largestPause > 400)
            {
                Console.Error.WriteLine("UI blocked for " + largestPause + " ms during background work"); return 1;
            }
            string result = "{\"passed\":true,\"largestPauseMs\":" + largestPause + ",\"elapsedMs\":" + clock.ElapsedMilliseconds + "}";
            File.WriteAllText(Path.Combine(args[1], "界面响应验证.json"), result);
            Console.WriteLine(result); return 0;
        }
    }
}
