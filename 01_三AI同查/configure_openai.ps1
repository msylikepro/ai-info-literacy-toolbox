param([string]$StatusFile)
. (Join-Path $PSScriptRoot 'configure_apis.ps1')
if ($MyInvocation.InvocationName -ne '.') {
    Show-ApiConfigWindow -StatusFile $StatusFile -InitialProvider GPT
}