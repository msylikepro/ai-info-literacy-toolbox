param(
    [Parameter(Mandatory=$true)][string]$CredentialFile,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][string]$PasswordFile
)

$ErrorActionPreference = 'Stop'
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
$taskPassword = [IO.Path]::GetFullPath($PasswordFile)
$taskCredential = [IO.Path]::GetFullPath($CredentialFile)
$taskCompiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (Test-Path -LiteralPath $taskOutput) { throw 'Use a new output directory.' }
if (Test-Path -LiteralPath $taskPassword) { throw 'Use a new password file path.' }
if ($taskPassword.StartsWith($taskOutput.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Save the password separately, outside the output directory.'
}
if (-not (Test-Path -LiteralPath $taskCredential -PathType Leaf)) { throw 'DPAPI credential file not found.' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $taskPassword) -PathType Container)) { throw 'Password parent directory not found.' }
[void][IO.Directory]::CreateDirectory($taskOutput)
$taskExecutable = Join-Path $taskOutput '导入共享API配置.exe'
& $taskCompiler /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    /reference:System.Web.Extensions.dll /reference:System.Security.dll `
    ('/out:' + $taskExecutable) (Join-Path $PSScriptRoot 'SharedApiConfig.cs')
if ($LASTEXITCODE -ne 0) { throw 'Shared API helper compilation failed.' }
try {
    # Load the helper as a library: DPAPI decryption/export stays inside this process.
    $taskAssembly = [Reflection.Assembly]::LoadFile($taskExecutable)
    $taskExport = $taskAssembly.GetType('SharedApiConfig').GetMethod('Export')
    [void]$taskExport.Invoke($null, @($taskCredential, $taskOutput, $taskPassword))
} catch {
    # Never echo source JSON, passwords, nested exception details, or plaintext keys.
    throw 'Shared API export failed. Check all three DPAPI keys, HTTPS addresses, account and file permissions.'
}
Write-Output ('Encrypted package created: ' + $taskOutput)
Write-Output ('Password saved separately: ' + $taskPassword)
