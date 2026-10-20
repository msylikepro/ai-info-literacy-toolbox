param([string]$StatusFile)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Security
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class QwenKeyWindow {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr handle);
}
'@
$taskCredentialPath = Join-Path $PSScriptRoot 'data\api-keys.dpapi.json'
if (-not (Test-Path -LiteralPath $taskCredentialPath -PathType Leaf)) {
    throw 'The encrypted credential file is missing. Configure the existing credentials first.'
}
$taskExisting = Get-Content -LiteralPath $taskCredentialPath -Raw | ConvertFrom-Json
$taskInitialBase = $taskExisting.qwen_base_url
Remove-Variable taskExisting

$taskForm = New-Object System.Windows.Forms.Form
$taskForm.Text = 'Replace Qwen API key - local secure input'
$taskForm.ClientSize = New-Object System.Drawing.Size(660, 255)
$taskForm.StartPosition = 'CenterScreen'
$taskForm.FormBorderStyle = 'FixedDialog'
$taskForm.MaximizeBox = $false
$taskForm.MinimizeBox = $false
$taskForm.TopMost = $true
$taskForm.Add_Shown({
    [void][QwenKeyWindow]::ShowWindow($taskForm.Handle, 5)
    [void][QwenKeyWindow]::SetForegroundWindow($taskForm.Handle)
})

$taskKeyLabel = New-Object System.Windows.Forms.Label
$taskKeyLabel.Text = 'New Qwen / Alibaba Model Studio API key (hidden):'
$taskKeyLabel.SetBounds(18, 18, 620, 24)
$taskKeyBox = New-Object System.Windows.Forms.TextBox
$taskKeyBox.UseSystemPasswordChar = $true
$taskKeyBox.SetBounds(18, 46, 620, 26)
$taskUrlLabel = New-Object System.Windows.Forms.Label
$taskUrlLabel.Text = 'API base URL (must match the region of your key):'
$taskUrlLabel.SetBounds(18, 86, 620, 24)
$taskUrlBox = New-Object System.Windows.Forms.TextBox
$taskUrlBox.Text = $taskInitialBase
$taskUrlBox.SetBounds(18, 114, 620, 26)
$taskNote = New-Object System.Windows.Forms.Label
$taskNote.Text = 'Encrypted for this Windows user. DeepSeek credentials stay unchanged.'
$taskNote.SetBounds(18, 155, 620, 24)
$taskSave = New-Object System.Windows.Forms.Button
$taskSave.Text = 'Save new key'
$taskSave.SetBounds(398, 200, 125, 32)
$taskCancel = New-Object System.Windows.Forms.Button
$taskCancel.Text = 'Cancel'
$taskCancel.SetBounds(533, 200, 105, 32)
$taskCancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$taskForm.AcceptButton = $taskSave
$taskForm.CancelButton = $taskCancel
$taskForm.Controls.AddRange(@($taskKeyLabel, $taskKeyBox, $taskUrlLabel, $taskUrlBox,
    $taskNote, $taskSave, $taskCancel))

$taskSave.Add_Click({
    $taskUri = $null
    if ([string]::IsNullOrWhiteSpace($taskKeyBox.Text) -or
        -not [Uri]::TryCreate($taskUrlBox.Text.Trim(), [UriKind]::Absolute, [ref]$taskUri) -or
        $taskUri.Scheme -ne 'https' -or -not $taskUri.Host.EndsWith('.aliyuncs.com') -or
        $taskUri.UserInfo -or $taskUri.Query -or $taskUri.Fragment) {
        [void][System.Windows.Forms.MessageBox]::Show(
            'Enter a nonempty API key and an official Alibaba HTTPS base URL.', 'Check input')
        return
    }
    $taskTemporaryPath = $taskCredentialPath + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        # Reload before saving and change only the Qwen fields.
        $taskCredentials = Get-Content -LiteralPath $taskCredentialPath -Raw | ConvertFrom-Json
        $taskKeyBytes = [Text.Encoding]::UTF8.GetBytes($taskKeyBox.Text.Trim())
        try {
            $taskProtected = [Security.Cryptography.ProtectedData]::Protect(
                $taskKeyBytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
            $taskCredentials.qwen_key = [Convert]::ToBase64String($taskProtected)
        } finally { [Array]::Clear($taskKeyBytes, 0, $taskKeyBytes.Length) }
        $taskCredentials.qwen_base_url = $taskUri.AbsoluteUri.TrimEnd('/')
        [IO.File]::WriteAllText($taskTemporaryPath, ($taskCredentials | ConvertTo-Json),
            (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $taskTemporaryPath -Destination $taskCredentialPath -Force
        Remove-Variable taskCredentials
    } catch {
        if (Test-Path -LiteralPath $taskTemporaryPath) { Remove-Item -LiteralPath $taskTemporaryPath }
        [void][System.Windows.Forms.MessageBox]::Show('Could not save. Please retry.', 'Save failed')
        return
    }
    $taskKeyBox.Clear()
    $taskForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $taskForm.Close()
})

try {
    $taskDialogResult = $taskForm.ShowDialog()
    if ($StatusFile) {
        [IO.File]::WriteAllText($StatusFile,
            (@{ saved = ($taskDialogResult -eq [System.Windows.Forms.DialogResult]::OK) } | ConvertTo-Json))
    }
} finally {
    $taskKeyBox.Clear()
    $taskForm.Dispose()
}
