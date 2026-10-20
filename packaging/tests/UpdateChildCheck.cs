using System;
using System.Reflection;
using System.IO;
using System.Runtime.InteropServices;

static class UpdateChildCheck
{
    [DllImport("kernel32.dll")] static extern uint SetErrorMode(uint mode);
    static string Quote(string path){return "\""+path+"\"";}
    static int Main(string[] args)
    {
        SetErrorMode(0x0001|0x0002);
        try
        {
            Assembly assembly=Assembly.LoadFrom(args[0]);
            Type type=assembly.GetType("UpdateEngine",true);
            using(IDisposable engine=(IDisposable)Activator.CreateInstance(type,true))
            {
                MethodInfo run=type.GetMethod("Run",BindingFlags.Instance|BindingFlags.NonPublic);
                run.Invoke(engine,new object[]{args[1],"-B "+Quote(args[2])+" "+Quote(args[3]),args[4],args[5],120000});
            }
            return 0;
        }
        catch(Exception error)
        {
            File.WriteAllText(Path.Combine(args[4],"host-error.log"),error.ToString());
            return 1;
        }
    }
}
