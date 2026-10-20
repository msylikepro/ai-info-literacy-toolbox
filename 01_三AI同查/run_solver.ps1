param(
    [Parameter(Position = 0)][string]$Question,
    [string]$File,
    [string]$Image,
    [double]$Timeout = 120,
    [Alias('CodexProxy')][string]$GptProxy,
    [string]$CredentialFile,
    [string]$ThinkingFile,
    [switch]$Json,
    [switch]$JsonLines
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
if (-not $CredentialFile) { $CredentialFile = Join-Path $PSScriptRoot 'data\api-keys.dpapi.json' }
$taskEnvironmentNames = @('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'QWEN_API_KEY', 'DEEPSEEK_API_KEY', 'QWEN_BASE_URL', 'DEEPSEEK_BASE_URL', 'OPENAI_PROXY_URL', 'OPENAI_REASONING_EFFORT', 'QWEN_REASONING_EFFORT', 'DEEPSEEK_REASONING_EFFORT')
$taskOriginalEnvironment = @{}
foreach ($taskName in $taskEnvironmentNames) {
    $taskOriginalEnvironment[$taskName] = [Environment]::GetEnvironmentVariable($taskName, 'Process')
}

try {
    . (Join-Path $PSScriptRoot 'thinking_config.ps1')
    if (-not $ThinkingFile) { $ThinkingFile = Join-Path $PSScriptRoot 'data\thinking.json' }
    $taskPreferences = Get-ThinkingSettings -SettingsPath $ThinkingFile
    foreach ($taskThinkingMapping in @(@('GPT','OPENAI_REASONING_EFFORT'),@('Qwen','QWEN_REASONING_EFFORT'),@('DeepSeek','DEEPSEEK_REASONING_EFFORT'))) {
        if (-not [Environment]::GetEnvironmentVariable($taskThinkingMapping[1],'Process')) {
            [Environment]::SetEnvironmentVariable($taskThinkingMapping[1],$taskPreferences[$taskThinkingMapping[0]],'Process')
        }
    }
    if ($GptProxy) { $env:OPENAI_PROXY_URL = $GptProxy }
    # Reuse locally encrypted credentials; existing environment variables take priority.
    if (Test-Path -LiteralPath $CredentialFile -PathType Leaf) {
        Add-Type -AssemblyName System.Security
        $taskCredentials = Get-Content -LiteralPath $CredentialFile -Raw | ConvertFrom-Json
        $taskLoadedQwenKey = $false
        $taskLoadedOpenAIKey = $false
        $taskLoadedDeepSeekKey = $false
        foreach ($taskMapping in @(@('openai_key', 'OPENAI_API_KEY'), @('qwen_key', 'QWEN_API_KEY'), @('deepseek_key', 'DEEPSEEK_API_KEY'))) {
            if ([Environment]::GetEnvironmentVariable($taskMapping[1], 'Process')) { continue }
            if ($taskMapping[1] -eq 'QWEN_API_KEY' -and $env:DASHSCOPE_API_KEY) { continue }
            if (-not $taskCredentials.($taskMapping[0])) { continue }
            $taskEncryptedBytes = [Convert]::FromBase64String($taskCredentials.($taskMapping[0]))
            $taskKeyBytes = [Security.Cryptography.ProtectedData]::Unprotect(
                $taskEncryptedBytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
            try {
                [Environment]::SetEnvironmentVariable(
                    $taskMapping[1], [Text.Encoding]::UTF8.GetString($taskKeyBytes), 'Process')
            } finally {
                [Array]::Clear($taskKeyBytes, 0, $taskKeyBytes.Length)
            }
            if ($taskMapping[1] -eq 'QWEN_API_KEY') { $taskLoadedQwenKey = $true }
            if ($taskMapping[1] -eq 'OPENAI_API_KEY') { $taskLoadedOpenAIKey = $true }
            if ($taskMapping[1] -eq 'DEEPSEEK_API_KEY') { $taskLoadedDeepSeekKey = $true }
        }
        if ($taskLoadedQwenKey -and -not $env:QWEN_BASE_URL -and $taskCredentials.qwen_base_url) {
            $env:QWEN_BASE_URL = $taskCredentials.qwen_base_url
        }
        if ($taskLoadedOpenAIKey -and -not $env:OPENAI_BASE_URL -and $taskCredentials.openai_base_url) {
            $env:OPENAI_BASE_URL = $taskCredentials.openai_base_url
        }
        if ($taskLoadedDeepSeekKey -and -not $env:DEEPSEEK_BASE_URL -and $taskCredentials.deepseek_base_url) {
            $env:DEEPSEEK_BASE_URL = $taskCredentials.deepseek_base_url
        }
        Remove-Variable taskCredentials
    }

    $taskPython = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
        $taskPython = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    }
    $taskArguments = @('-u', (Join-Path $PSScriptRoot 'solver.py'), '--timeout',
        $Timeout.ToString([Globalization.CultureInfo]::InvariantCulture))
    if ($Json) { $taskArguments += '--json' }
    if ($JsonLines) { $taskArguments += '--json-lines' }
    if ($Image) { $taskArguments += @('--image', $Image) }
    if ($PSBoundParameters.ContainsKey('Question')) { $taskArguments += @('--', $Question) }
    if ($File) {
        if ($PSBoundParameters.ContainsKey('Question')) { throw 'Use either a question or -File.' }
        $taskArguments += @('--file', $File)
    }
    & $taskPython @taskArguments
    $taskExitCode = $LASTEXITCODE
} finally {
    foreach ($taskName in $taskEnvironmentNames) {
        [Environment]::SetEnvironmentVariable($taskName, $taskOriginalEnvironment[$taskName], 'Process')
    }
}
exit $taskExitCode
