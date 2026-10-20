param([string]$Target,[switch]$ResolveOnly)
$ErrorActionPreference='Stop'

function Resolve-ToolboxUpdate([string]$Directory) {
    if (-not (Test-Path -LiteralPath (Join-Path $Directory 'AI信息素养工具箱.exe') -PathType Leaf)) {throw '请选择原 AI信息素养工具箱.exe 所在的文件夹。'}
    $manifest=Get-Content -LiteralPath (Join-Path $Directory 'build-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.product -ne 'AI信息素养工具箱_Windows免安装版') {throw '所选文件夹不是此工具箱。'}
    $version=if ($manifest.version) {[string]$manifest.version} else {'1.0.0'}
    $backups=Join-Path $Directory 'update-backups'
    if (Test-Path -LiteralPath $backups -PathType Container) {
        foreach ($backup in (Get-ChildItem -LiteralPath $backups -Directory | Sort-Object Name)) {
            $journalFile=Join-Path $backup.FullName 'journal.json'
            if (Test-Path -LiteralPath $journalFile -PathType Leaf) {
                $journal=Get-Content -LiteralPath $journalFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($journal.status -in @('applying','validating','restoring-data','rollback-failed')) {
                    # Native updater first restores the pending base, then applies
                    # the matching delta. Never skip recovery on a new manifest.
                    $version=[string]$journal.fromVersion
                    break
                }
            }
        }
    }
    if ($version -notin @('1.0.0','1.1.0','1.2.0','1.3.0','1.4.0','1.4.1','1.5.0','1.6.0','1.7.0','1.8.0','1.9.0','1.10.0')) {throw ('此升级包不支持当前版本：'+$version)}
    $updater=if ($version -ne '1.10.0') {'updates\'+$version+'\双击升级.exe'} else {$null}
    return @{SourceVersion=$version;TargetVersion='1.10.0';UpdaterRelative=$updater}
}

if ($ResolveOnly) {
    [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
    Resolve-ToolboxUpdate $Target | ConvertTo-Json -Compress
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
try {
    if (-not $Target) {
        $dialog=New-Object Windows.Forms.FolderBrowserDialog
        $dialog.Description='选择原工具箱文件夹。程序自动识别旧版本并升级到 v1.9.0，保留本机配置与个人数据。'
        try {if ($dialog.ShowDialog() -ne 'OK') {exit};$Target=$dialog.SelectedPath}
        finally {$dialog.Dispose()}
    }
    $choice=Resolve-ToolboxUpdate $Target
    if ($choice.UpdaterRelative) {
        $executable=Join-Path $PSScriptRoot $choice.UpdaterRelative
        if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {throw '升级包不完整，请完整解压后再运行。'}
        # Visible native upgrade window is the user-facing interactive action.
        $process=Start-Process -FilePath $executable -ArgumentList @('--target',('"'+$Target.TrimEnd('\')+'"')) -PassThru -Wait
        if ($process.ExitCode -ne 0) {throw '升级未完成。请处理升级窗口中的提示后重试。'}
        $after=Resolve-ToolboxUpdate $Target
        if ($after.SourceVersion -ne '1.10.0') {throw '升级尚未完成，请再次运行并点击升级窗口的“开始升级”。'}
    }
    if (-not $choice.UpdaterRelative) { [void][Windows.Forms.MessageBox]::Show('此文件夹已经是最新的 v1.9.0。','离线升级') }
} catch {
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'离线升级提示','OK','Warning')
}
