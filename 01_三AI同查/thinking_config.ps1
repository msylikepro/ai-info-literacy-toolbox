param([string]$SettingsPath)

$ErrorActionPreference = 'Stop'
$script:ThinkingSettingsPath = Join-Path $PSScriptRoot 'data\thinking.json'
$script:ThinkingChoices = @{
    GPT = @{ Codes=@('low','medium','high','xhigh','max'); Labels=@('低','中','高','更高','最高'); Default='medium'; Model='GPT · gpt-6.1-sol' }
    Qwen = @{ Codes=@('off','low','medium','xhigh'); Labels=@('关闭思考','低','中','更高'); Default='off'; Model='千问 · qwen3.8-max' }
    DeepSeek = @{ Codes=@('off','low','high','max'); Labels=@('关闭思考','低','高','最高'); Default='off'; Model='DeepSeek · V4.1 Flash' }
}

function Get-ThinkingSettings([string]$SettingsPath = $script:ThinkingSettingsPath) {
    $saved = $null
    if (Test-Path -LiteralPath $SettingsPath -PathType Leaf) {
        $saved = Get-Content -LiteralPath $SettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $saved -or $saved -is [Array] -or $saved -is [string]) { throw '思考设置文件格式无效。' }
    }
    $result = @{}
    foreach ($provider in @('GPT','Qwen','DeepSeek')) {
        $value = $script:ThinkingChoices[$provider].Default
        if ($saved -and $saved.PSObject.Properties[$provider]) { $value = [string]$saved.$provider }
        if ($value -notin $script:ThinkingChoices[$provider].Codes) { throw ($provider + ' 思考档位无效。') }
        $result[$provider] = $value
    }
    return $result
}

function Save-ThinkingConfig($state) {
    $values = @{}
    foreach ($provider in @('GPT','Qwen','DeepSeek')) {
        $entry = $state.Entries[$provider]
        $index = $entry.Box.SelectedIndex
        if ($index -lt 0 -or $index -ge $script:ThinkingChoices[$provider].Codes.Count) { throw '请选择有效思考档位。' }
        $values[$provider] = $script:ThinkingChoices[$provider].Codes[$index]
    }
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $state.SettingsPath))
    $temporary = $state.SettingsPath + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary,($values | ConvertTo-Json),(New-Object Text.UTF8Encoding($false)))
        # Windows PowerShell converts $null to an empty string for this .NET argument.
        if ([IO.File]::Exists($state.SettingsPath)) { [IO.File]::Replace($temporary,$state.SettingsPath,[NullString]::Value) }
        else { [IO.File]::Move($temporary,$state.SettingsPath) }
    } finally { if ([IO.File]::Exists($temporary)) {[IO.File]::Delete($temporary)} }
}

function Get-ThinkingLabel([string]$Provider,[string]$Code) {
    $choice = $script:ThinkingChoices[$Provider]
    $index = [Array]::IndexOf($choice.Codes,$Code)
    if ($index -lt 0) { return '档位无效' }
    return $choice.Labels[$index]
}

function New-ThinkingConfigWindow([string]$SettingsPath = $script:ThinkingSettingsPath) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $values = Get-ThinkingSettings -SettingsPath $SettingsPath
    $form = New-Object Windows.Forms.Form
    $form.Text = '思考档位'; $form.ClientSize = New-Object Drawing.Size(650,365)
    $form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false; $form.MinimizeBox = $false
    $form.Font = New-Object Drawing.Font('Microsoft YaHei UI',10)
    $intro = New-Object Windows.Forms.Label
    $intro.Text = '分别设置三个模型的思考深度，保存后下一次答题生效。'
    $intro.SetBounds(20,18,610,30); $form.Controls.Add($intro)
    $entries = @{}; $row = 0
    foreach ($provider in @('GPT','Qwen','DeepSeek')) {
        $choice = $script:ThinkingChoices[$provider]
        $label = New-Object Windows.Forms.Label
        $label.Text = $choice.Model; $label.SetBounds(20,(65+$row*55),365,35)
        $box = New-Object Windows.Forms.ComboBox
        $box.DropDownStyle = 'DropDownList'; $box.SetBounds(415,(62+$row*55),210,35)
        foreach ($text in $choice.Labels) { [void]$box.Items.Add($text) }
        $box.SelectedIndex = [Array]::IndexOf($choice.Codes,$values[$provider])
        $entries[$provider] = @{ Box=$box }
        $form.Controls.AddRange(@($label,$box)); $row++
    }
    $hint = New-Object Windows.Forms.Label
    $hint.Text = "思考档位越高，通常等待越久、用量越多。`r`nGPT 最低为低档；千问和 DeepSeek 可以关闭思考。"
    $hint.SetBounds(20,232,610,55); $form.Controls.Add($hint)
    $status = New-Object Windows.Forms.Label; $status.SetBounds(20,300,325,45)
    $save = New-Object Windows.Forms.Button; $save.Text='保存设置'; $save.SetBounds(365,305,125,36)
    $close = New-Object Windows.Forms.Button; $close.Text='取消'; $close.SetBounds(505,305,120,36)
    $close.DialogResult='Cancel'; $form.CancelButton=$close; $form.AcceptButton=$save
    $state = @{Form=$form;Entries=$entries;SettingsPath=$SettingsPath;Status=$status;SaveButton=$save}
    $save.Tag=$state
    $save.Add_Click({param($sender,$eventArgs)
        try { Save-ThinkingConfig $sender.Tag; $sender.Tag.Form.DialogResult='OK'; $sender.Tag.Form.Close() }
        catch {$sender.Tag.Status.Text='保存失败，请检查文件写入权限。'}
    })
    $form.Controls.AddRange(@($status,$save,$close))
    return $state
}

if ($MyInvocation.InvocationName -ne '.') {
    if (-not $SettingsPath) { $SettingsPath=$script:ThinkingSettingsPath }
    $window=$null
    try { $window=New-ThinkingConfigWindow -SettingsPath $SettingsPath; [void]$window.Form.ShowDialog() }
    catch { [void][Windows.Forms.MessageBox]::Show('无法读取思考设置，请检查 data\thinking.json。','思考档位') }
    finally { if ($window) {$window.Form.Dispose()} }
}
