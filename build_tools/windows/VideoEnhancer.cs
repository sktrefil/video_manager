using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Video Enhancer")]
[assembly: AssemblyDescription("Portable video watermark crop, stabilization and interpolation")]
[assembly: AssemblyVersion("0.1.0.0")]

internal static class Program
{
    private static readonly object LogLock = new object();

    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); }
            else { result.Append('\\', slashes); result.Append(c); }
            slashes = 0;
        }
        result.Append('\\', slashes * 2); result.Append('"');
        return result.ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string logs = Path.Combine(root, "logs");
        try
        {
            Directory.CreateDirectory(logs);
            string python = Path.Combine(root, "runtime", "python.exe");
            string entry = Path.Combine(root, "app", "launch.py");
            if (!File.Exists(python) || !File.Exists(entry))
                throw new FileNotFoundException("Keep VideoEnhancer.exe together with the runtime, app and bin folders.");
            var arguments = new StringBuilder("-s " + Quote(entry));
            foreach (string argument in args) arguments.Append(" ").Append(Quote(argument));
            var info = new ProcessStartInfo(python, arguments.ToString());
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            info.StandardErrorEncoding = Encoding.UTF8;
            info.EnvironmentVariables.Remove("PYTHONHOME");
            info.EnvironmentVariables.Remove("PYTHONPATH");
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            info.EnvironmentVariables["PATH"] = Path.Combine(root, "bin") + Path.PathSeparator + (info.EnvironmentVariables["PATH"] ?? "");
            using (var log = new StreamWriter(Path.Combine(logs, "launcher.log"), true, Encoding.UTF8))
            using (var process = new Process())
            {
                log.AutoFlush = true;
                log.WriteLine("--- " + DateTime.Now.ToString("s") + " ---");
                process.StartInfo = info;
                DataReceivedEventHandler handler = delegate(object sender, DataReceivedEventArgs e)
                { if (e.Data != null) lock (LogLock) log.WriteLine(e.Data); };
                process.OutputDataReceived += handler;
                process.ErrorDataReceived += handler;
                process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
                process.WaitForExit();
                if (process.ExitCode != 0)
                    MessageBox.Show("Video Enhancer could not finish.\nSee " + Path.Combine(logs, "launcher.log"),
                                    "Video Enhancer", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Video Enhancer", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
