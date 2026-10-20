using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

static class UpdateUiPreview
{
    [DllImport("kernel32.dll")]static extern uint SetErrorMode(uint value);
    [STAThread]
    static int Main(string[] args)
    {
        SetErrorMode(3);
        try
        {
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
            Assembly assembly=Assembly.LoadFrom(args[0]);
            Type engineType=assembly.GetType("UpdateEngine",true),windowType=assembly.GetType("UpgradeWindow",true);
            using(IDisposable engine=(IDisposable)Activator.CreateInstance(engineType,true))
            using(Form form=(Form)Activator.CreateInstance(windowType,new object[]{engine,args[1]}))
            {
                form.StartPosition=FormStartPosition.Manual;form.Location=new Point(-15000,-15000);
                form.Show();Application.DoEvents();
                using(Bitmap bitmap=new Bitmap(form.Width,form.Height))
                {
                    form.DrawToBitmap(bitmap,new Rectangle(0,0,form.Width,form.Height));bitmap.Save(args[2]);
                }
            }
            return 0;
        }
        catch(Exception error){File.WriteAllText(args[2]+".error.txt",error.ToString());return 1;}
    }
}
