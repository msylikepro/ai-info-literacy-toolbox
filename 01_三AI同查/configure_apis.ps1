param([string]$StatusFile)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Security
if (-not ('ApiKeyWindow' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ApiKeyWindow {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr handle);
}
'@
}
$script:ApiCredentialPath = Join-Path $PSScriptRoot 'data\api-keys.dpapi.json'

function Save-ApiProviderConfig($entry) {
    $taskUri = $null
    if (-not [Uri]::TryCreate($entry.BaseBox.Text.Trim(), [UriKind]::Absolute, [ref]$taskUri) -or
        $taskUri.Scheme -ne 'https' -or $taskUri.UserInfo -or $taskUri.Query -or $taskUri.Fragment -or
        $taskUri.AbsolutePath.TrimEnd('/') -match '/(responses|chat/completions)$') {
        throw 'Enter an HTTPS Base URL, not a complete request URL.'
    }
    # Reload on each save, so changing one provider preserves the other providers.
    $taskCredentials = [pscustomobject]@{}
    if (Test-Path -LiteralPath $entry.CredentialPath -PathType Leaf) {
        $taskCredentials = Get-Content -LiteralPath $entry.CredentialPath -Raw | ConvertFrom-Json
    }
    if (-not [string]::IsNullOrWhiteSpace($entry.KeyBox.Text)) {
        $taskKeyBytes = [Text.Encoding]::UTF8.GetBytes($entry.KeyBox.Text.Trim())
        try {
            $taskProtected = [Security.Cryptography.ProtectedData]::Protect(
                $taskKeyBytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
            $taskCredentials | Add-Member -NotePropertyName $entry.KeyField -NotePropertyValue ([Convert]::ToBase64String($taskProtected)) -Force
        } finally { [Array]::Clear($taskKeyBytes, 0, $taskKeyBytes.Length) }
    } elseif (-not $taskCredentials.($entry.KeyField)) { throw 'API key is required.' }
    $taskBaseUrl = $taskUri.AbsoluteUri.TrimEnd('/')
    if ($entry.Provider -eq 'GPT' -and $taskUri.Host -in @('www.micuapi.ai', 'api-slb.micuapi.ai') -and
        $taskUri.AbsolutePath -eq '/') { $taskBaseUrl += '/v1' }
    $taskCredentials | Add-Member -NotePropertyName $entry.BaseField -NotePropertyValue $taskBaseUrl -Force
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $entry.CredentialPath))
    $taskTemporaryPath = $entry.CredentialPath + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($taskTemporaryPath, ($taskCredentials | ConvertTo-Json),
            (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $taskTemporaryPath -Destination $entry.CredentialPath -Force
    } finally {
        if (Test-Path -LiteralPath $taskTemporaryPath) { Remove-Item -LiteralPath $taskTemporaryPath }
    }
    $entry.KeyBox.Clear()
    $entry.BaseBox.Text = $taskBaseUrl
}

function New-ApiConfigWindow([string]$CredentialPath = $script:ApiCredentialPath,
                             [string]$InitialProvider = 'DeepSeek') {
    $form = New-Object Windows.Forms.Form
    $form.Text = '配置 DeepSeek、千问、GPT API'
    $form.ClientSize = New-Object Drawing.Size(700, 420)
    $form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'
    $form.Font = New-Object Drawing.Font('Microsoft YaHei UI', 10)
    $form.MaximizeBox = $false; $form.MinimizeBox = $false; $form.TopMost = $true
    $tabs = New-Object Windows.Forms.TabControl
    $tabs.SetBounds(18, 14, 664, 290)
    $saved = [pscustomobject]@{}
    if (Test-Path -LiteralPath $CredentialPath -PathType Leaf) {
        $saved = Get-Content -LiteralPath $CredentialPath -Raw | ConvertFrom-Json
    }
    $entries = @{}
    foreach ($definition in @(
        @('DeepSeek', 'DeepSeek', 'deepseek', 'https://api.deepseek.com', 'V4.1 Flash（deepseek-flash）· Chat Completions'),
        @('Qwen', '千问 Qwen', 'qwen', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen3.8-max · Chat Completions'),
        @('GPT', 'GPT', 'openai', 'https://api.openai.com/v1', 'gpt-6.1-sol · Responses')
    )) {
        $provider, $label, $prefix, $defaultBase, $model = $definition
        $page = New-Object Windows.Forms.TabPage
        $page.Text = $label
        $keyLabel = New-Object Windows.Forms.Label
        $keyLabel.Text = 'API 密钥（隐藏输入；留空保留已有密钥）'
        $keyLabel.SetBounds(14, 15, 620, 28)
        $keyBox = New-Object Windows.Forms.TextBox
        $keyBox.UseSystemPasswordChar = $true; $keyBox.SetBounds(14, 48, 620, 30)
        $baseLabel = New-Object Windows.Forms.Label
        $baseLabel.Text = 'Base URL（填写该密钥所属平台提供的 API 基础地址）'
        $baseLabel.SetBounds(14, 93, 620, 28)
        $baseBox = New-Object Windows.Forms.TextBox
        $baseField = $prefix + '_base_url'
        $baseBox.Text = if ($saved.$baseField) { $saved.$baseField } else { $defaultBase }
        $baseBox.SetBounds(14, 126, 620, 30)
        $info = New-Object Windows.Forms.Label
        $info.Text = "当前模型：$model`r`n切换标签可配置其他模型，改动后点击保存此模型。`r`n地址需使用 HTTPS；不要填写完整 /responses 或 /chat/completions。"
        $info.SetBounds(14, 171, 620, 75)
        $entry = @{ Provider=$provider; CredentialPath=$CredentialPath; KeyField=($prefix + '_key');
                    BaseField=$baseField; KeyBox=$keyBox; BaseBox=$baseBox }
        $page.Tag = $entry; $entries[$provider] = $entry
        $page.Controls.AddRange(@($keyLabel, $keyBox, $baseLabel, $baseBox, $info))
        [void]$tabs.TabPages.Add($page)
        if ($provider -eq $InitialProvider) { $tabs.SelectedTab = $page }
    }
    $status = New-Object Windows.Forms.Label
    $status.Text = '密钥在本机加密保存。已设置的 API 环境变量仍优先。'
    $status.SetBounds(18, 315, 664, 45)
    $save = New-Object Windows.Forms.Button
    $save.Text = '保存此模型'; $save.SetBounds(412, 370, 130, 34)
    $close = New-Object Windows.Forms.Button
    $close.Text = '关闭'; $close.SetBounds(556, 370, 126, 34)
    $close.DialogResult = [Windows.Forms.DialogResult]::Cancel
    $form.AcceptButton = $save; $form.CancelButton = $close
    $state = @{ Form=$form; Tabs=$tabs; Entries=$entries; StatusLabel=$status; SaveButton=$save; Saved=$false;
                KeyBox=$entries.GPT.KeyBox; BaseBox=$entries.GPT.BaseBox; CredentialPath=$CredentialPath }
    $save.Tag = $state; $form.Tag = $state
    $save.Add_Click({ param($sender, $eventArgs)
        $entry = $sender.Tag.Tabs.SelectedTab.Tag
        try { Save-ApiProviderConfig $entry }
        catch {
            $sender.Tag.StatusLabel.Text = '保存失败：请检查密钥、HTTPS Base URL 及文件写入权限。'; return
        }
        $sender.Tag.Saved = $true
        $sender.Tag.StatusLabel.Text = $entry.Provider + ' 配置已保存，下一次答题生效；可继续配置其他模型。'
    })
    $form.Controls.AddRange(@($tabs, $status, $save, $close))
    $form.Add_Shown({ param($sender, $eventArgs)
        [void][ApiKeyWindow]::ShowWindow($sender.Handle, 5)
        [void][ApiKeyWindow]::SetForegroundWindow($sender.Handle)
        $sender.Tag.Tabs.SelectedTab.Tag.KeyBox.Focus()
    })
    return $state
}

# Preserve the existing GPT-only scripting entry points.
function New-OpenAIConfigWindow([string]$CredentialPath = $script:ApiCredentialPath) {
    return New-ApiConfigWindow -CredentialPath $CredentialPath -InitialProvider GPT
}
function Save-OpenAIConfig($state) { Save-ApiProviderConfig $state.Entries.GPT }

function Show-ApiConfigWindow([string]$StatusFile, [string]$InitialProvider = 'DeepSeek') {
    $state = New-ApiConfigWindow -InitialProvider $InitialProvider
    try {
        [void]$state.Form.ShowDialog()
        if ($StatusFile) {
            [IO.File]::WriteAllText($StatusFile, (@{saved=$state.Saved} | ConvertTo-Json))
        }
    } finally {
        foreach ($entry in $state.Entries.Values) { $entry.KeyBox.Clear() }
        $state.Form.Dispose()
    }
}
if ($MyInvocation.InvocationName -ne '.') { Show-ApiConfigWindow -StatusFile $StatusFile }
