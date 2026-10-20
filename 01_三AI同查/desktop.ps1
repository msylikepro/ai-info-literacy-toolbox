param([Alias('CodexProxy')][string]$GptProxy = 'http://127.0.0.1:7897')

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class AnswerDesktopWindow {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr handle);
}
'@
[Windows.Forms.Application]::EnableVisualStyles()
$script:DesktopRoot = $PSScriptRoot
. (Join-Path $PSScriptRoot 'thinking_config.ps1')
if (-not $PSBoundParameters.ContainsKey('GptProxy')) {
    if ($env:OPENAI_PROXY_URL) { $GptProxy = $env:OPENAI_PROXY_URL }
    elseif ($env:CODEX_PROXY_URL) { $GptProxy = $env:CODEX_PROXY_URL }
}
$script:DesktopProxy = $GptProxy

function Clear-AnswerImage($state) {
    $old = $state.ImagePreview.Image
    $state.ImagePreview.Image = $null
    if ($old) { $old.Dispose() }
    $state.ImageBytes = $null
    $state.ImageLabel.Text = '可上传或粘贴一张题目截图（PNG/JPEG，最多 10 MiB）'
}

function Set-AnswerImage($state, [Drawing.Image]$image, [string]$label = '题目截图') {
    if ($state.Process) { return }
    if ($image.Width -gt 8192 -or $image.Height -gt 8192) {
        $state.StatusLabel.Text = '图片边长不能超过 8192 像素。'; return
    }
    $stream = New-Object IO.MemoryStream
    $copy = $null
    try {
        # Draw into a fresh bitmap to detach from files/clipboard and strip metadata.
        $copy = New-Object Drawing.Bitmap($image.Width, $image.Height)
        $graphics = [Drawing.Graphics]::FromImage($copy)
        try { $graphics.DrawImage($image, 0, 0, $image.Width, $image.Height) } finally { $graphics.Dispose() }
        $copy.Save($stream, [Drawing.Imaging.ImageFormat]::Png)
        if ($stream.Length -gt 10MB) { $state.StatusLabel.Text = '图片转为 PNG 后超过 10 MiB，请裁剪后重试。'; return }
        $bytes = $stream.ToArray()
        Clear-AnswerImage $state
        $state.ImageBytes = $bytes
        $state.ImagePreview.Image = $copy
        $copy = $null
        $state.ImageLabel.Text = '已附题目截图 · {0} × {1} · {2:N0} KB' -f $image.Width, $image.Height, ($bytes.Length / 1KB)
        $state.StatusLabel.Text = '图片已就绪，可直接答题，也可补充文字。'
    } finally { if ($copy) { $copy.Dispose() }; $stream.Dispose() }
}

function Set-AnswerImageFromFile($state, [string]$path) {
    if ($state.Process) { return }
    $image = $null; $stream = $null
    try {
        $file = Get-Item -LiteralPath $path
        if ($file.PSIsContainer -or $file.Length -gt 10MB) { throw '图片不能超过 10 MiB。' }
        $stream = [IO.File]::OpenRead($file.FullName)
        $image = [Drawing.Image]::FromStream($stream, $false, $true)
        if ($image.RawFormat.Guid -notin @([Drawing.Imaging.ImageFormat]::Png.Guid, [Drawing.Imaging.ImageFormat]::Jpeg.Guid)) {
            throw '请选择 PNG 或 JPEG 图片。'
        }
        Set-AnswerImage $state $image
    } catch { $state.StatusLabel.Text = '图片无法读取：请选择有效 PNG/JPEG，最多 10 MiB，边长不超过 8192 像素。' }
    finally { if ($image) { $image.Dispose() }; if ($stream) { $stream.Dispose() } }
}

function Paste-AnswerImage($state) {
    if ($state.Process) { return }
    $image = $null
    try {
        if (-not [Windows.Forms.Clipboard]::ContainsImage()) { $state.StatusLabel.Text = '剪贴板中没有图片，请先复制题目截图。'; return }
        $image = [Windows.Forms.Clipboard]::GetImage()
        Set-AnswerImage $state $image
    } catch { $state.StatusLabel.Text = '无法读取剪贴板图片，请重新复制截图后重试。' }
    finally { if ($image) { $image.Dispose() } }
}

function Set-AnswerBusy($state, [bool]$busy) {
    foreach ($control in @($state.StartButton, $state.ClearButton, $state.ExampleButton,
        $state.QuestionBox, $state.ProxyBox, $state.TimeoutInput, $state.ConfigButton, $state.ThinkingButton,
        $state.UploadImageButton, $state.PasteImageButton, $state.RemoveImageButton)) { $control.Enabled = -not $busy }
}

function Stop-AnswerRequest($state) {
    $state.Timer.Stop()
    if ($state.Process) {
        if (-not $state.Process.HasExited) {
            $stopInfo = New-Object Diagnostics.ProcessStartInfo
            $stopInfo.FileName = Join-Path $env:SystemRoot 'System32\taskkill.exe'
            $stopInfo.Arguments = '/PID ' + $state.Process.Id + ' /T /F'
            $stopInfo.UseShellExecute = $false
            $stopInfo.CreateNoWindow = $true
            $stopInfo.RedirectStandardOutput = $true
            $stopInfo.RedirectStandardError = $true
            $stopper = [Diagnostics.Process]::Start($stopInfo)
            [void]$stopper.WaitForExit(3000)
            $stopper.Dispose()
        }
        $state.Process.Dispose()
        $state.Process = $null
    }
    if ($state.QuestionFile -and (Test-Path -LiteralPath $state.QuestionFile)) {
        Remove-Item -LiteralPath $state.QuestionFile -ErrorAction SilentlyContinue
    }
    if ($state.ImageFile -and (Test-Path -LiteralPath $state.ImageFile)) {
        Remove-Item -LiteralPath $state.ImageFile -ErrorAction SilentlyContinue
    }
    if ($state.TempDirectory -and (Test-Path -LiteralPath $state.TempDirectory)) {
        Remove-Item -LiteralPath $state.TempDirectory -ErrorAction SilentlyContinue
    }
    $state.QuestionFile = $null
    $state.ImageFile = $null
    $state.TempDirectory = $null
    Set-AnswerBusy $state $false
}

function Show-AnswerOutput($state, [string]$output, [string]$errorText, [int]$exitCode) {
    try {
        $payload = $output | ConvertFrom-Json
        if ($payload.question -isnot [string] -or @($payload.models).Count -ne 3 -or
            $payload.analysis -isnot [string]) { throw 'Invalid result format' }
        $parts = @("题目：`r`n" + $payload.question)
        foreach ($provider in @('GPT', 'Qwen', 'DeepSeek')) {
            $matches = @($payload.models | Where-Object { $_.provider -eq $provider })
            if ($matches.Count -ne 1) { throw 'Missing model result' }
            $model = $matches[0]
            $answer = if ($model.error) { '调用失败' } else { $model.answer }
            $reason = if ($model.error) { $model.error } else { $model.reason }
            $text = "答案：$answer`r`n理由：$reason"
            $state.ResultBoxes[$provider].Text = $text
            $parts += "======== $provider ========`r`n$text"
        }
        $state.AnalysisLabel.Text = $payload.analysis
        $parts += "======== 综合分析 ========`r`n" + $payload.analysis
        $state.Output = $parts -join "`r`n`r`n"
    } catch {
        $detail = if ($errorText.Trim()) { $errorText.Trim() } else { $state.StreamError }
        if (-not $detail) { $detail = '后台请求异常结束，未收到完整结果。' }
        $parts = @("题目：`r`n" + $state.QuestionSnapshot)
        foreach ($provider in @('GPT', 'Qwen', 'DeepSeek')) {
            if (-not $state.CompletedModels.ContainsKey($provider)) {
                $state.ResultBoxes[$provider].Text = '未获取到该模型结果。'
            }
            $parts += "======== $provider ========`r`n" + $state.ResultBoxes[$provider].Text
        }
        $state.AnalysisLabel.Text = '无法完整比较：' + $detail
        $parts += "======== 综合分析 ========`r`n" + $state.AnalysisLabel.Text
        $state.Output = $parts -join "`r`n`r`n"
        $exitCode = 2
    }
    $state.CopyButton.Enabled = $true
    $elapsed = ([DateTime]::UtcNow - $state.StartedAt).TotalSeconds
    $status = if ($exitCode -eq 0) { '完成，三个模型均已返回' }
              elseif ($exitCode -eq 1) { '完成，部分模型调用失败，请查看结果' }
              else { '请求失败，请查看错误信息或复制完整结果' }
    $state.StatusLabel.Text = $status + (' · 用时 {0:N1} 秒' -f $elapsed)
}

function Update-AnswerRequest($state) {
    if (-not $state.Process) { return }
    $elapsed = ([DateTime]::UtcNow - $state.StartedAt).TotalSeconds
    if (-not $state.FinalReceived) {
        $state.StatusLabel.Text = ('已完成 {0}/3 个模型 · 已用时 {1:N0} 秒' -f $state.CompletedModels.Count, $elapsed)
    }
    while ($state.StdoutTask -and $state.StdoutTask.IsCompleted) {
        try { $line = $state.StdoutTask.Result }
        catch { $state.StreamError = '读取模型结果失败。'; $line = $null }
        if ($null -eq $line) {
            $state.StdoutEnded = $true; $state.StdoutTask = $null; break
        }
        [void]$state.OutputLines.Add($line)
        if ($line.Trim()) {
            try {
                $event = $line | ConvertFrom-Json
                if ($event.type -eq 'model_result') {
                    $model = $event.result
                    if ($model.provider -notin @('GPT', 'Qwen', 'DeepSeek')) { throw 'Unknown provider' }
                    $state.CompletedModels[$model.provider] = $model
                    $answer = if ($model.error) { '调用失败' } else { $model.answer }
                    $reason = if ($model.error) { $model.error } else { $model.reason }
                    $state.ResultBoxes[$model.provider].Text = "答案：$answer`r`n理由：$reason"
                } elseif ($event.type -eq 'complete') {
                    $code = if (@($event.models | Where-Object { $_.error }).Count) { 1 } else { 0 }
                    Show-AnswerOutput $state $line '' $code
                    $state.FinalReceived = $true
                } else { throw 'Unknown event' }
            } catch { $state.StreamError = '模型结果格式错误，未获取完整综合分析。' }
        }
        $state.StdoutTask = $state.Process.StandardOutput.ReadLineAsync()
    }
    if (-not $state.Process.HasExited -or -not $state.StdoutEnded -or
        -not $state.StderrTask.IsCompleted) { return }
    if (-not $state.FinalReceived) {
        Show-AnswerOutput $state ($state.OutputLines -join "`n") $state.StderrTask.Result $state.Process.ExitCode
    }
    Stop-AnswerRequest $state
}

function Start-AnswerRequest($state) {
    if ($state.Process) { return }
    $question = $state.QuestionBox.Text.Trim()
    if (-not $question -and -not $state.ImageBytes) { $state.StatusLabel.Text = '请先输入题目和完整选项，或上传/粘贴题目截图。'; return }
    if (-not $question) { $question = '请识别图片中的题目及完整选项，并独立作答。图片不清晰或信息不足时请在理由中说明。' }
    $proxy = $state.ProxyBox.Text.Trim()
    if ($proxy) {
        $uri = $null
        if (-not [Uri]::TryCreate($proxy, [UriKind]::Absolute, [ref]$uri) -or
            $uri.Scheme -notin @('http', 'https') -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
            $state.StatusLabel.Text = 'GPT 代理请填写 http/https 地址，或留空使用系统网络。'; return
        }
        $proxy = $uri.AbsoluteUri
    }
    try {
        $state.TempDirectory = Join-Path $env:TEMP ('ai-answer-ui-' + [Guid]::NewGuid().ToString('N'))
        [void][IO.Directory]::CreateDirectory($state.TempDirectory)
        $state.QuestionFile = Join-Path $state.TempDirectory 'question.txt'
        [IO.File]::WriteAllText($state.QuestionFile, $question, (New-Object Text.UTF8Encoding($false)))
        if ($state.ImageBytes) {
            $state.ImageFile = Join-Path $state.TempDirectory 'question.png'
            [IO.File]::WriteAllBytes($state.ImageFile, $state.ImageBytes)
        }
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $info.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $state.RunnerPath +
            '" -File "' + $state.QuestionFile + '" -Timeout ' +
            $state.TimeoutInput.Value.ToString([Globalization.CultureInfo]::InvariantCulture) + ' -JsonLines'
        if ($proxy) { $info.Arguments += ' -GptProxy "' + $proxy + '"' }
        if ($state.ImageFile) { $info.Arguments += ' -Image "' + $state.ImageFile + '"' }
        $info.Arguments += ' -ThinkingFile "' + $state.ThinkingFile + '"'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = New-Object Text.UTF8Encoding($false)
        $info.StandardErrorEncoding = New-Object Text.UTF8Encoding($false)
        $info.WorkingDirectory = $script:DesktopRoot
        $info.EnvironmentVariables.Remove('CODEX_PROXY_URL')
        $info.EnvironmentVariables.Remove('OPENAI_PROXY_URL')
        foreach ($name in @('OPENAI_REASONING_EFFORT','QWEN_REASONING_EFFORT','DEEPSEEK_REASONING_EFFORT')) { $info.EnvironmentVariables.Remove($name) }
        $process = New-Object Diagnostics.Process
        $process.StartInfo = $info
        [void]$process.Start()
        $state.Process = $process
        $state.StdoutTask = $process.StandardOutput.ReadLineAsync()
        $state.StderrTask = $process.StandardError.ReadToEndAsync()
        $state.StartedAt = [DateTime]::UtcNow
        $state.Output = ''
        $state.OutputLines = New-Object 'Collections.Generic.List[string]'
        $state.CompletedModels = @{}
        $state.QuestionSnapshot = $question
        $state.StdoutEnded = $false
        $state.FinalReceived = $false
        $state.StreamError = ''
        $state.CopyButton.Enabled = $false
        Set-AnswerBusy $state $true
        foreach ($box in $state.ResultBoxes.Values) { $box.Text = '正在独立回答，请稍候…' }
        $state.AnalysisLabel.Text = '等待三个模型返回后比较答案。'
        $state.StatusLabel.Text = '三个模型正在独立回答…'
        $state.Timer.Start()
    } catch {
        Stop-AnswerRequest $state
        $state.StatusLabel.Text = '请求启动失败，请确认启动脚本和本机环境可用。'
    }
}

function Update-ModelLabels($state) {
    $values=Get-ThinkingSettings -SettingsPath $state.ThinkingFile
    foreach ($provider in @('GPT','Qwen','DeepSeek')) {
        $choice=$script:ThinkingChoices[$provider]
        $state.ModelGroups[$provider].Text=$choice.Model + ' / ' + (Get-ThinkingLabel $provider $values[$provider])
    }
}

function New-AnswerWindow([string]$RunnerPath = (Join-Path $script:DesktopRoot 'run_solver.ps1'),
                         [string]$ThinkingFile = (Join-Path $script:DesktopRoot 'data\thinking.json')) {
    $form = New-Object Windows.Forms.Form
    $form.Text = 'AI+信息素养 · 三模型答题测试'
    $form.ClientSize = New-Object Drawing.Size(1140, 800)
    $form.MinimumSize = New-Object Drawing.Size(960, 700)
    $form.StartPosition = 'CenterScreen'
    $form.Font = New-Object Drawing.Font('Microsoft YaHei UI', 10)
    $form.BackColor = [Drawing.ColorTranslator]::FromHtml('#F5F7FB')
    $root = New-Object Windows.Forms.TableLayoutPanel
    $root.Dock = 'Fill'; $root.Padding = New-Object Windows.Forms.Padding(20)
    $root.ColumnCount = 1; $root.RowCount = 5
    foreach ($height in @(64, 318)) { [void]$root.RowStyles.Add((New-Object Windows.Forms.RowStyle('Absolute', $height))) }
    [void]$root.RowStyles.Add((New-Object Windows.Forms.RowStyle('Percent', 100)))
    foreach ($height in @(86, 32)) { [void]$root.RowStyles.Add((New-Object Windows.Forms.RowStyle('Absolute', $height))) }
    $form.Controls.Add($root)
    $title = New-Object Windows.Forms.Label
    $title.Text = 'AI+信息素养  /  三模型答题测试'
    $title.Font = New-Object Drawing.Font('Microsoft YaHei UI', 19, [Drawing.FontStyle]::Bold)
    $title.ForeColor = [Drawing.ColorTranslator]::FromHtml('#18243C')
    $title.Dock = 'Fill'; $title.TextAlign = 'MiddleLeft'
    $root.Controls.Add($title, 0, 0)

    $inputGroup = New-Object Windows.Forms.GroupBox
    $inputGroup.Text = '输入题目或截图（回车发送，Shift+回车换行，Ctrl+V 粘贴截图）'; $inputGroup.Dock = 'Fill'
    $inputLayout = New-Object Windows.Forms.TableLayoutPanel
    $inputLayout.Dock = 'Fill'; $inputLayout.Padding = New-Object Windows.Forms.Padding(10)
    $inputLayout.ColumnCount = 1; $inputLayout.RowCount = 4
    [void]$inputLayout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Percent', 100)))
    [void]$inputLayout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Absolute', 62)))
    [void]$inputLayout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Absolute', 48)))
    [void]$inputLayout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Absolute', 36)))
    $inputGroup.Controls.Add($inputLayout); $root.Controls.Add($inputGroup, 0, 1)
    $questionBox = New-Object Windows.Forms.RichTextBox
    $questionBox.Dock = 'Fill'; $questionBox.Font = New-Object Drawing.Font('Microsoft YaHei UI', 12)
    $questionBox.BorderStyle = 'FixedSingle'; $questionBox.DetectUrls = $false
    $inputLayout.Controls.Add($questionBox, 0, 0)
    $attachment = New-Object Windows.Forms.FlowLayoutPanel
    $attachment.Dock = 'Fill'; $attachment.WrapContents = $false
    $attachment.Margin = New-Object Windows.Forms.Padding(0)
    $imageButtons = @{}
    foreach ($entry in @(@('Upload', '上传图片'), @('Paste', '粘贴图片'), @('Remove', '移除图片'))) {
        $button = New-Object Windows.Forms.Button
        $button.Text = $entry[1]; $button.Size = New-Object Drawing.Size(95, 36)
        $button.Margin = New-Object Windows.Forms.Padding(0, 10, 8, 0)
        $imageButtons[$entry[0]] = $button; $attachment.Controls.Add($button)
    }
    $imagePreview = New-Object Windows.Forms.PictureBox
    $imagePreview.Size = New-Object Drawing.Size(74, 56); $imagePreview.SizeMode = 'Zoom'
    $imagePreview.BorderStyle = 'FixedSingle'; $attachment.Controls.Add($imagePreview)
    $imageLabel = New-Object Windows.Forms.Label
    $imageLabel.Size = New-Object Drawing.Size(440, 54); $imageLabel.TextAlign = 'MiddleLeft'
    $imageLabel.Text = '可上传或粘贴一张题目截图（PNG/JPEG，最多 10 MiB）'
    $attachment.Controls.Add($imageLabel)
    $inputLayout.Controls.Add($attachment, 0, 1)
    $toolbar = New-Object Windows.Forms.FlowLayoutPanel
    $toolbar.Dock = 'Fill'; $toolbar.WrapContents = $false
    $buttons = @{}
    foreach ($entry in @(@('Start', '开始三模型答题', 150), @('Example', '载入示例', 95),
                        @('Clear', '清空题目', 95), @('Copy', '复制完整结果', 125),
                        @('Config', '配置三模型 API', 140), @('Thinking', '思考档位', 105))) {
        $button = New-Object Windows.Forms.Button
        $button.Text = $entry[1]; $button.Size = New-Object Drawing.Size($entry[2], 36)
        $button.FlatStyle = 'Flat'; $button.FlatAppearance.BorderSize = 0
        $button.BackColor = [Drawing.ColorTranslator]::FromHtml('#E5EAF2')
        $button.Margin = New-Object Windows.Forms.Padding(0, 6, 10, 0)
        $buttons[$entry[0]] = $button; $toolbar.Controls.Add($button)
    }
    $buttons.Start.BackColor = [Drawing.ColorTranslator]::FromHtml('#2563EB')
    $buttons.Start.ForeColor = [Drawing.Color]::White; $buttons.Copy.Enabled = $false
    $inputLayout.Controls.Add($toolbar, 0, 2)
    $settingsPanel = New-Object Windows.Forms.FlowLayoutPanel
    $settingsPanel.Dock = 'Fill'; $settingsPanel.WrapContents = $false
    $proxyLabel = New-Object Windows.Forms.Label
    $proxyLabel.Text = 'GPT 代理'; $proxyLabel.AutoSize = $true
    $proxyLabel.Margin = New-Object Windows.Forms.Padding(0, 7, 8, 0)
    $proxyBox = New-Object Windows.Forms.TextBox
    $proxyBox.Text = $script:DesktopProxy; $proxyBox.Width = 260
    $timeoutLabel = New-Object Windows.Forms.Label
    $timeoutLabel.Text = '每路超时（秒）'; $timeoutLabel.AutoSize = $true
    $timeoutLabel.Margin = New-Object Windows.Forms.Padding(20, 7, 8, 0)
    $timeoutInput = New-Object Windows.Forms.NumericUpDown
    $timeoutInput.Minimum = 10; $timeoutInput.Maximum = 600; $timeoutInput.Value = 120
    $timeoutInput.Width = 80
    $settingsPanel.Controls.AddRange(@($proxyLabel, $proxyBox, $timeoutLabel, $timeoutInput))
    $inputLayout.Controls.Add($settingsPanel, 0, 3)

    $cards = New-Object Windows.Forms.TableLayoutPanel
    $cards.Dock = 'Fill'; $cards.ColumnCount = 3; $cards.RowCount = 1
    $resultBoxes = @{}
    $modelGroups = @{}
    $modelNames = @('GPT API · gpt-6.1-sol / medium', 'Qwen · qwen3.8-max', 'DeepSeek · deepseek-flash')
    $providers = @('GPT', 'Qwen', 'DeepSeek')
    for ($i = 0; $i -lt 3; $i++) {
        [void]$cards.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Percent', 33.333)))
        $group = New-Object Windows.Forms.GroupBox
        $group.Text = $modelNames[$i]; $group.Dock = 'Fill'
        $group.Padding = New-Object Windows.Forms.Padding(10, 24, 10, 10)
        $box = New-Object Windows.Forms.RichTextBox
        $box.Dock = 'Fill'; $box.ReadOnly = $true; $box.DetectUrls = $false
        $box.Font = New-Object Drawing.Font('Microsoft YaHei UI', 11)
        $box.BorderStyle = 'None'; $box.BackColor = [Drawing.Color]::White
        $box.Text = '等待输入题目。'; $group.Controls.Add($box)
        $cards.Controls.Add($group, $i, 0); $resultBoxes[$providers[$i]] = $box
        $modelGroups[$providers[$i]] = $group
    }
    $root.Controls.Add($cards, 0, 2)
    $analysisGroup = New-Object Windows.Forms.GroupBox
    $analysisGroup.Text = '综合分析'; $analysisGroup.Dock = 'Fill'
    $analysisLabel = New-Object Windows.Forms.RichTextBox
    $analysisLabel.Dock = 'Fill'; $analysisLabel.ReadOnly = $true; $analysisLabel.BorderStyle = 'None'
    $analysisLabel.BackColor = $form.BackColor; $analysisLabel.Text = '提交题目后，在这里查看三个模型的答案是否一致。'
    $analysisGroup.Controls.Add($analysisLabel); $root.Controls.Add($analysisGroup, 0, 3)
    $statusLabel = New-Object Windows.Forms.Label
    $statusLabel.Text = '就绪 · 回车发送，Shift+回车换行；三个模型同时回答'
    $statusLabel.Dock = 'Fill'; $statusLabel.TextAlign = 'MiddleLeft'
    $statusLabel.ForeColor = [Drawing.ColorTranslator]::FromHtml('#52627A')
    $root.Controls.Add($statusLabel, 0, 4)
    $timer = New-Object Windows.Forms.Timer; $timer.Interval = 150
    $state = @{
        Form = $form; QuestionBox = $questionBox; ProxyBox = $proxyBox; TimeoutInput = $timeoutInput;
        StartButton = $buttons.Start; ExampleButton = $buttons.Example; ClearButton = $buttons.Clear;
        CopyButton = $buttons.Copy; ConfigButton = $buttons.Config; ThinkingButton=$buttons.Thinking;
        UploadImageButton = $imageButtons.Upload; PasteImageButton = $imageButtons.Paste;
        RemoveImageButton = $imageButtons.Remove; ImagePreview = $imagePreview; ImageLabel = $imageLabel;
        ImageBytes = $null; ImageFile = $null;
        ThinkingFile=$ThinkingFile; ModelGroups=$modelGroups;
        ResultBoxes = $resultBoxes; AnalysisLabel = $analysisLabel;
        StatusLabel = $statusLabel; Timer = $timer; RunnerPath = $RunnerPath; Process = $null;
        Output = ''; QuestionFile = $null; TempDirectory = $null; StartedAt = [DateTime]::UtcNow;
        CompletedModels = @{}; QuestionSnapshot = ''; StdoutEnded = $false; FinalReceived = $false;
        StreamError = ''; OutputLines = (New-Object 'Collections.Generic.List[string]')
    }
    Update-ModelLabels $state
    $script:AnswerWindow = $state
    foreach ($button in $buttons.Values) { $button.Tag = $state }
    foreach ($button in $imageButtons.Values) { $button.Tag = $state }
    $imageButtons.Upload.Add_Click({ param($sender, $eventArgs)
        $dialog = New-Object Windows.Forms.OpenFileDialog
        $dialog.Filter = '题目图片 (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg'
        $dialog.Title = '选择题目截图'; $dialog.Multiselect = $false
        try { if ($dialog.ShowDialog($sender.Tag.Form) -eq 'OK') { Set-AnswerImageFromFile $sender.Tag $dialog.FileName } }
        finally { $dialog.Dispose() }
    })
    $imageButtons.Paste.Add_Click({ param($sender, $eventArgs) Paste-AnswerImage $sender.Tag })
    $imageButtons.Remove.Add_Click({ param($sender, $eventArgs) Clear-AnswerImage $sender.Tag })
    $form.Tag = $state
    $questionBox.Tag = $state
    $questionBox.Add_KeyDown({ param($sender, $eventArgs)
        if ($eventArgs.Control -and $eventArgs.KeyCode -eq [Windows.Forms.Keys]::V) {
            try {
                if ([Windows.Forms.Clipboard]::ContainsImage()) {
                    $eventArgs.Handled = $true; $eventArgs.SuppressKeyPress = $true
                    Paste-AnswerImage $sender.Tag; return
                }
            } catch { $sender.Tag.StatusLabel.Text = '剪贴板暂时不可用，请稍后重试。' }
        }
        if ($eventArgs.KeyCode -eq [Windows.Forms.Keys]::Enter -and -not $eventArgs.Shift) {
            $eventArgs.Handled = $true
            $eventArgs.SuppressKeyPress = $true
            Start-AnswerRequest $sender.Tag
        }
    })
    $buttons.Start.Add_Click({ param($sender, $eventArgs) Start-AnswerRequest $sender.Tag })
    $buttons.Config.Add_Click({ param($sender, $eventArgs)
        & (Join-Path $script:DesktopRoot 'configure_apis.ps1')
    })
    $buttons.Thinking.Add_Click({param($sender,$eventArgs)
        & (Join-Path $script:DesktopRoot 'thinking_config.ps1') -SettingsPath $sender.Tag.ThinkingFile
        Update-ModelLabels $sender.Tag
    })
    $buttons.Example.Add_Click({ param($sender, $eventArgs)
        $sender.Tag.QuestionBox.Text = "AIGC 指的是哪一种内容生产方式？`r`nA. 完全由人工手工创作内容`r`nB. 利用人工智能生成内容`r`nC. 仅从数据库检索原文`r`nD. 仅对现有内容进行人工分类"
    })
    $buttons.Clear.Add_Click({ param($sender, $eventArgs)
        Clear-AnswerImage $sender.Tag
        $sender.Tag.QuestionBox.Clear(); $sender.Tag.QuestionBox.Focus()
    })
    $buttons.Copy.Add_Click({ param($sender, $eventArgs)
        try {
            [Windows.Forms.Clipboard]::SetText($sender.Tag.Output)
            $sender.Tag.StatusLabel.Text = '完整题目、三家答案和综合分析已复制。'
        } catch { $sender.Tag.StatusLabel.Text = '剪贴板暂时不可用，请稍后重试。' }
    })
    $timer.Add_Tick({ Update-AnswerRequest $script:AnswerWindow })
    $form.Add_FormClosing({ param($sender, $eventArgs)
        Stop-AnswerRequest $sender.Tag; Clear-AnswerImage $sender.Tag; $sender.Tag.Timer.Dispose()
    })
    $form.Add_Shown({ param($sender, $eventArgs)
        [void][AnswerDesktopWindow]::ShowWindow($sender.Handle, 5)
        [void][AnswerDesktopWindow]::SetForegroundWindow($sender.Handle)
        $sender.Tag.QuestionBox.Focus()
    })
    return $state
}

if ($MyInvocation.InvocationName -ne '.') {
    $window = New-AnswerWindow
    try { [void]$window.Form.ShowDialog() }
    finally { Stop-AnswerRequest $window; Clear-AnswerImage $window; $window.Timer.Dispose(); $window.Form.Dispose() }
}
