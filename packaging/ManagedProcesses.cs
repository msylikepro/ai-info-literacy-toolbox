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

// The launcher owns only the processes it starts. A Windows Job closes their
// descendants as well (including the checker browser) when the launcher exits.
sealed class ProcessGroup : IDisposable
{
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits
    {
        public long ProcessUserTime, JobUserTime;
        public uint Flags;
        public UIntPtr MinWorkingSet, MaxWorkingSet;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters
    {
        public ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits
    {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr attr, string name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int type, IntPtr info, uint size);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    IntPtr handle;
    readonly List<Process> children = new List<Process>();

    public ProcessGroup()
    {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle == IntPtr.Zero) throw new InvalidOperationException("无法创建程序进程组。");
        ExtendedLimits limits = new ExtendedLimits();
        limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        int size = Marshal.SizeOf(typeof(ExtendedLimits));
        IntPtr buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(limits, buffer, false);
            if (!SetInformationJobObject(handle, 9, buffer, (uint)size))
                throw new InvalidOperationException("无法设置程序退出清理。");
        }
        finally { Marshal.FreeHGlobal(buffer); }
    }
    public void Add(Process child, bool requireAssignment = false)
    {
        lock (children) children.Add(child);
        // Nested jobs can be restricted on managed computers; Stop also has a
        // PID-specific fallback and never terminates processes by executable name.
        bool assigned=AssignProcessToJobObject(handle, child.Handle);
        if(!assigned && requireAssignment && !child.HasExited)
        {
            Stop(child);
            throw new InvalidOperationException("当前电脑不允许安全管理升级验证进程，已停止升级。");
        }
    }
    public void Stop(Process child)
    {
        if (child == null) return;
        try
        {
            if (!child.HasExited)
            {
                ProcessStartInfo info = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "taskkill.exe"),
                    "/PID " + child.Id + " /T /F");
                info.UseShellExecute = false; info.CreateNoWindow = true;
                using (Process killer = Process.Start(info)) killer.WaitForExit(5000);
                child.WaitForExit(3000);
            }
        }
        catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception) { }
    }
    public void Dispose()
    {
        lock (children) foreach (Process child in children) Stop(child);
        if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
    }
}

