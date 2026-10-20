import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows desktop required')
class DesktopTest(unittest.TestCase):
    def test_thinking_save_button_overwrites_existing_settings_repeatedly(self):
        result = self.run_powershell('''
. (Join-Path (Split-Path -Parent $DesktopPath) 'thinking_config.ps1')
$settingsPath = Join-Path (Split-Path -Parent $RunnerPath) 'thinking.json'
[IO.File]::WriteAllText($settingsPath,'{"GPT":"low","Qwen":"off","DeepSeek":"off"}')
$checks = @()
foreach ($indices in @(@(1,2,2),@(2,3,3))) {
    $state = New-ThinkingConfigWindow -SettingsPath $settingsPath
    try {
        $state.Form.Show()
        $state.Entries.GPT.Box.SelectedIndex = $indices[0]
        $state.Entries.Qwen.Box.SelectedIndex = $indices[1]
        $state.Entries.DeepSeek.Box.SelectedIndex = $indices[2]
        $state.SaveButton.PerformClick()
        $checks += @{saved=(Get-ThinkingSettings -SettingsPath $settingsPath);
            dialog=$state.Form.DialogResult.ToString();status=$state.Status.Text}
    } finally { $state.Form.Dispose() }
}
$reopened = New-ThinkingConfigWindow -SettingsPath $settingsPath
try {
    @{checks=$checks;indexes=@($reopened.Entries.GPT.Box.SelectedIndex,
        $reopened.Entries.Qwen.Box.SelectedIndex,$reopened.Entries.DeepSeek.Box.SelectedIndex);
        leftover_temps=@(Get-ChildItem -LiteralPath (Split-Path -Parent $settingsPath) -Filter 'thinking.json.*.tmp').Count} | ConvertTo-Json -Depth 5
} finally { $reopened.Form.Dispose() }
''')
        self.assertEqual(result['checks'][0]['saved'], {'GPT': 'medium', 'Qwen': 'medium', 'DeepSeek': 'high'})
        self.assertEqual(result['checks'][1]['saved'], {'GPT': 'high', 'Qwen': 'xhigh', 'DeepSeek': 'max'})
        self.assertTrue(all(check['dialog'] == 'OK' for check in result['checks']), result['checks'])
        self.assertEqual(result['indexes'], [2, 3, 3])
        self.assertEqual(result['leftover_temps'], 0)

    def test_thinking_window_saves_and_restores_provider_choices_without_touching_keys(self):
        result=self.run_powershell('''
. (Join-Path (Split-Path -Parent $DesktopPath) 'thinking_config.ps1')
$settingsPath = Join-Path (Split-Path -Parent $RunnerPath) 'thinking.json'
$credentials = Join-Path (Split-Path -Parent $RunnerPath) 'api-keys.dpapi.json'
[IO.File]::WriteAllText($credentials,'unchanged-private-fixture')
$state=New-ThinkingConfigWindow -SettingsPath $settingsPath
try {
    $defaults=Get-ThinkingSettings -SettingsPath $settingsPath
    $state.Entries.GPT.Box.SelectedIndex=0
    $state.Entries.Qwen.Box.SelectedIndex=3
    $state.Entries.DeepSeek.Box.SelectedIndex=2
    Save-ThinkingConfig $state
    $saved=Get-ThinkingSettings -SettingsPath $settingsPath
    $second=New-ThinkingConfigWindow -SettingsPath $settingsPath
    try {
        @{defaults=$defaults;saved=$saved;indexes=@($second.Entries.GPT.Box.SelectedIndex,$second.Entries.Qwen.Box.SelectedIndex,$second.Entries.DeepSeek.Box.SelectedIndex);
          keys_unchanged=([IO.File]::ReadAllText($credentials) -eq 'unchanged-private-fixture')} | ConvertTo-Json -Depth 5
    } finally {$second.Form.Dispose()}
} finally {$state.Form.Dispose()}
''')
        self.assertEqual(result['defaults'],{'GPT':'medium','Qwen':'off','DeepSeek':'off'})
        self.assertEqual(result['saved'],{'GPT':'low','Qwen':'xhigh','DeepSeek':'high'})
        self.assertEqual(result['indexes'],[0,3,2])
        self.assertTrue(result['keys_unchanged'])

    def test_thinking_button_and_model_headers_reflect_saved_choices(self):
        result=self.run_powershell('''
. (Join-Path (Split-Path -Parent $DesktopPath) 'thinking_config.ps1')
$settingsPath = Join-Path (Split-Path -Parent $RunnerPath) 'thinking.json'
[IO.File]::WriteAllText($settingsPath,'{"GPT":"low","Qwen":"medium","DeepSeek":"high"}')
$state=New-AnswerWindow -RunnerPath $RunnerPath -ThinkingFile $settingsPath
try {
    $headers=@($state.ModelGroups.GPT.Text,$state.ModelGroups.Qwen.Text,$state.ModelGroups.DeepSeek.Text)
    Set-AnswerBusy $state $true
    $disabled=-not $state.ThinkingButton.Enabled
    Set-AnswerBusy $state $false
    @{headers=$headers;disabled_while_busy=$disabled;enabled=$state.ThinkingButton.Enabled;label=$state.ThinkingButton.Text} | ConvertTo-Json
} finally {$state.Timer.Dispose();$state.Form.Dispose()}
''')
        self.assertTrue(result['disabled_while_busy'])
        self.assertTrue(result['enabled'])
        self.assertIn('思考',result['label'])
        self.assertIn('低',result['headers'][0])
        self.assertIn('中',result['headers'][1])
        self.assertIn('V4.1',result['headers'][2])
        self.assertIn('高',result['headers'][2])

    def setUp(self):
        self.assertTrue((ROOT / 'desktop.ps1').exists(), '缺少桌面测试入口')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def run_powershell(self, body, runner_body=None, environment=None):
        runner = self.directory / 'runner.ps1'
        runner.write_text(runner_body or '', encoding='utf-8-sig')
        script = self.directory / 'check.ps1'
        script.write_text(
            "param([string]$DesktopPath,[string]$RunnerPath)\n"
            "$ErrorActionPreference = 'Stop'\n. $DesktopPath\n" + body,
            encoding='utf-8-sig',
        )
        process = subprocess.run(
            ['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
             '-File', str(script), '-DesktopPath', str(ROOT / 'desktop.ps1'),
             '-RunnerPath', str(runner)],
            capture_output=True, encoding='utf-8', errors='replace', timeout=20,
            env={**os.environ, **(environment or {})},
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout.lstrip('\ufeff').strip())

    def test_empty_input_stays_idle_and_shows_validation(self):
        result = self.run_powershell('''
$state = New-AnswerWindow -RunnerPath $RunnerPath
try {
    Start-AnswerRequest $state
    @{ started = ($null -ne $state.Process); button_enabled = $state.StartButton.Enabled;
       status = $state.StatusLabel.Text } | ConvertTo-Json
} finally { $state.Timer.Dispose(); $state.Form.Dispose() }
''')
        self.assertFalse(result['started'])
        self.assertTrue(result['button_enabled'])
        self.assertIn('题目', result['status'])

    def test_openai_config_masks_key_and_preserves_other_credentials(self):
        config_path = ROOT / 'configure_openai.ps1'
        credential_path = self.directory / 'credentials.json'
        result = self.run_powershell('''
$configPath = Join-Path (Split-Path -Parent $DesktopPath) 'configure_openai.ps1'
. $configPath
$credentialPath = Join-Path (Split-Path -Parent $RunnerPath) 'credentials.json'
@{qwen_key='unchanged-qwen';deepseek_key='unchanged-deepseek';qwen_base_url='unchanged-url'} |
    ConvertTo-Json | Set-Content -LiteralPath $credentialPath -Encoding UTF8
$state = New-OpenAIConfigWindow -CredentialPath $credentialPath
try {
    $state.KeyBox.Text = 'dummy-openai-key'
    $masked = $state.KeyBox.UseSystemPasswordChar
    Save-OpenAIConfig $state
    $saved = Get-Content -LiteralPath $credentialPath -Raw | ConvertFrom-Json
    $plainBytes = [Security.Cryptography.ProtectedData]::Unprotect(
        [Convert]::FromBase64String($saved.openai_key), $null,
        [Security.Cryptography.DataProtectionScope]::CurrentUser)
    @{ masked=$masked; cleared=($state.KeyBox.Text -eq '');
       decrypted=([Text.Encoding]::UTF8.GetString($plainBytes) -eq 'dummy-openai-key');
       qwen=$saved.qwen_key; deepseek=$saved.deepseek_key; qwen_url=$saved.qwen_base_url;
       base=$saved.openai_base_url; plaintext_saved=((Get-Content -LiteralPath $credentialPath -Raw).Contains('dummy-openai-key')) } | ConvertTo-Json
    [Array]::Clear($plainBytes, 0, $plainBytes.Length)
} finally { $state.Form.Dispose() }
''')
        self.assertTrue(config_path.exists())
        self.assertTrue(result['masked'])
        self.assertTrue(result['cleared'])
        self.assertTrue(result['decrypted'])
        self.assertFalse(result['plaintext_saved'])
        self.assertEqual(result['qwen'], 'unchanged-qwen')
        self.assertEqual(result['deepseek'], 'unchanged-deepseek')
        self.assertEqual(result['qwen_url'], 'unchanged-url')
        self.assertEqual(result['base'], 'https://api.openai.com/v1')

    def test_openai_config_changes_endpoint_without_reentering_saved_key(self):
        result = self.run_powershell('''
. (Join-Path (Split-Path -Parent $DesktopPath) 'configure_openai.ps1')
$credentialPath = Join-Path (Split-Path -Parent $RunnerPath) 'credentials.json'
$state = New-OpenAIConfigWindow -CredentialPath $credentialPath
try {
    $state.KeyBox.Text = 'dummy-openai-key'
    Save-OpenAIConfig $state
    $before = Get-Content -LiteralPath $credentialPath -Raw | ConvertFrom-Json
    $state.BaseBox.Text = 'https://relay.example/v1/'
    Save-OpenAIConfig $state
    $after = Get-Content -LiteralPath $credentialPath -Raw | ConvertFrom-Json
    $state.BaseBox.Text = 'https://relay.example/v1?key=unsafe'
    $rejected = $false
    try { Save-OpenAIConfig $state } catch { $rejected = $true }
    @{ base=$after.openai_base_url; kept_key=($before.openai_key -eq $after.openai_key);
       rejected=$rejected } | ConvertTo-Json
} finally { $state.Form.Dispose() }
''')
        self.assertEqual(result['base'], 'https://relay.example/v1')
        self.assertTrue(result['kept_key'])
        self.assertTrue(result['rejected'])

    def test_all_api_tabs_save_independently_and_preserve_existing_keys(self):
        result = self.run_powershell('''
. (Join-Path (Split-Path -Parent $DesktopPath) 'configure_apis.ps1')
$credentialPath = Join-Path (Split-Path -Parent $RunnerPath) 'credentials.json'
$state = New-ApiConfigWindow -CredentialPath $credentialPath
try {
    $checks = @()
    foreach ($provider in @('DeepSeek', 'Qwen', 'GPT')) {
        $entry = $state.Entries[$provider]
        $entry.KeyBox.Text = 'dummy-' + $provider
        Save-ApiProviderConfig $entry
        $saved = Get-Content -LiteralPath $credentialPath -Raw | ConvertFrom-Json
        $before = $saved.($entry.KeyField)
        $entry.BaseBox.Text = 'https://relay.example/' + $provider + '/v1'
        Save-ApiProviderConfig $entry
        $saved = Get-Content -LiteralPath $credentialPath -Raw | ConvertFrom-Json
        $bytes = [Security.Cryptography.ProtectedData]::Unprotect(
            [Convert]::FromBase64String($saved.($entry.KeyField)), $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $checks += @{ provider=$provider; masked=$entry.KeyBox.UseSystemPasswordChar;
            cleared=($entry.KeyBox.Text -eq ''); kept=($before -eq $saved.($entry.KeyField));
            correct=([Text.Encoding]::UTF8.GetString($bytes) -eq ('dummy-' + $provider));
            base=$saved.($entry.BaseField) }
        [Array]::Clear($bytes, 0, $bytes.Length)
    }
    $saved = Get-Content -LiteralPath $credentialPath -Raw | ConvertFrom-Json
    $before = Get-Content -LiteralPath $credentialPath -Raw
    $state.Entries.Qwen.BaseBox.Text = 'http://insecure.example/v1'
    $rejected = $false
    try { Save-ApiProviderConfig $state.Entries.Qwen } catch { $rejected = $true }
    @{ checks=$checks; tabs=$state.Tabs.TabCount;
       selected=$state.Tabs.SelectedTab.Text;
       keys=@($saved.PSObject.Properties | Where-Object { $_.Name -match '_key$' }).Count;
       plaintext=$before.Contains('dummy-'); rejected=$rejected;
       unchanged=($before -eq (Get-Content -LiteralPath $credentialPath -Raw)) } | ConvertTo-Json -Depth 5
} finally { $state.Form.Dispose() }
''')
        self.assertEqual(result['tabs'], 3)
        self.assertEqual(result['keys'], 3)
        self.assertFalse(result['plaintext'])
        self.assertTrue(result['rejected'])
        self.assertTrue(result['unchanged'])
        for check in result['checks']:
            self.assertTrue(all(check[key] for key in ('masked', 'cleared', 'kept', 'correct')))
            self.assertEqual(check['base'], 'https://relay.example/' + check['provider'] + '/v1')

    def test_saved_three_api_configs_load_on_next_request_and_env_can_override(self):
        result = self.run_powershell('''
. (Join-Path (Split-Path -Parent $DesktopPath) 'configure_apis.ps1')
$stage = Join-Path (Split-Path -Parent $RunnerPath) 'app'
[void][IO.Directory]::CreateDirectory($stage)
$credentialPath = Join-Path $stage 'credentials.json'
$state = New-ApiConfigWindow -CredentialPath $credentialPath
try {
    $state.Form.Show()
    foreach ($page in $state.Tabs.TabPages) {
        $state.Tabs.SelectedTab = $page
        $page.Tag.KeyBox.Text = 'dummy-' + $page.Tag.Provider
        $page.Tag.BaseBox.Text = 'https://relay.example/' + $page.Tag.Provider + '/v1'
        $state.SaveButton.PerformClick()
    }
    $saved = $state.Saved
    $status = $state.StatusLabel.Text
} finally { $state.Form.Dispose() }
$runnerCopy = Join-Path $stage 'run_solver.ps1'
Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $DesktopPath) 'run_solver.ps1') -Destination $runnerCopy
Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $DesktopPath) 'thinking_config.ps1') -Destination (Join-Path $stage 'thinking_config.ps1')
[void][IO.Directory]::CreateDirectory((Join-Path $stage 'data'))
$thinkingPath = Join-Path $stage 'data/thinking.json'
[IO.File]::WriteAllText($thinkingPath,'{"GPT":"medium","Qwen":"off","DeepSeek":"off"}')
$thinkingState = New-ThinkingConfigWindow -SettingsPath $thinkingPath
try {
    $thinkingState.Entries.GPT.Box.SelectedIndex = 0
    $thinkingState.Entries.Qwen.Box.SelectedIndex = 2
    $thinkingState.Entries.DeepSeek.Box.SelectedIndex = 3
    Save-ThinkingConfig $thinkingState
} finally { $thinkingState.Form.Dispose() }
$probe = @'
import json, os
names = [('OPENAI', 'GPT'), ('QWEN', 'Qwen'), ('DEEPSEEK', 'DeepSeek')]
levels={'GPT':'low','Qwen':'medium','DeepSeek':'max'}
print(json.dumps({name: [os.getenv(name+'_API_KEY') == 'dummy-'+provider, os.getenv(name+'_BASE_URL') == 'https://relay.example/'+provider+'/v1',os.getenv(name+'_REASONING_EFFORT') == levels[provider]] for name, provider in names}))
'@
[IO.File]::WriteAllText((Join-Path $stage 'solver.py'), $probe, (New-Object Text.UTF8Encoding($false)))
$env:PATH = $env:API_TEST_PYTHON_DIR + ';' + $env:PATH
foreach ($name in @('OPENAI_API_KEY','QWEN_API_KEY','DASHSCOPE_API_KEY','DEEPSEEK_API_KEY',
                    'OPENAI_BASE_URL','QWEN_BASE_URL','DEEPSEEK_BASE_URL','OPENAI_REASONING_EFFORT','QWEN_REASONING_EFFORT','DEEPSEEK_REASONING_EFFORT')) {
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
$first = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runnerCopy -CredentialFile $credentialPath -Question probe
if ($LASTEXITCODE -ne 0) { throw 'Saved configuration could not be loaded' }
$env:DEEPSEEK_API_KEY = 'environment-override'
$env:DEEPSEEK_BASE_URL = 'https://override.example/v1'
$env:DEEPSEEK_REASONING_EFFORT = 'low'
$second = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runnerCopy -CredentialFile $credentialPath -Question probe
if ($LASTEXITCODE -ne 0) { throw 'Environment override could not be loaded' }
@{saved=$saved;status=$status;first=($first | ConvertFrom-Json);second=($second | ConvertFrom-Json)} | ConvertTo-Json -Depth 5
''', environment={'API_TEST_PYTHON_DIR': str(Path(sys.executable).parent)})
        self.assertTrue(result['saved'])
        self.assertIn('配置已保存', result['status'])
        self.assertEqual(result['first'], {name: [True, True, True] for name in ('OPENAI', 'QWEN', 'DEEPSEEK')})
        self.assertEqual(result['second']['DEEPSEEK'], [False, False, False])
        self.assertEqual(result['second']['OPENAI'], [True, True, True])
        self.assertEqual(result['second']['QWEN'], [True, True, True])

    def test_request_runs_in_background_renders_results_and_allows_next_question(self):
        result = self.run_powershell('''
$state = New-AnswerWindow -RunnerPath $RunnerPath
try {
    $state.Form.Show()
    $state.ProxyBox.Text = ''
    $state.ExampleButton.PerformClick()
    $exampleLoaded = $state.QuestionBox.Text.Contains('AIGC')
    $state.QuestionBox.Text = "题目含中文 `$() ' 引号`n======== GPT ======== and ======== Qwen ========"
    $state.StartButton.PerformClick()
    $busy = -not $state.StartButton.Enabled
    $questionFile = $state.QuestionFile
    Start-AnswerRequest $state
    $sameRequest = $state.QuestionFile -eq $questionFile
    $limit = [DateTime]::UtcNow.AddSeconds(10)
    while ($state.Process -and [DateTime]::UtcNow -lt $limit) {
        [Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }
    @{ busy = $busy; duplicate_blocked = $sameRequest; example_loaded = $exampleLoaded;
       finished = ($null -eq $state.Process); button_enabled = $state.StartButton.Enabled;
       copy_enabled = $state.CopyButton.Enabled; gpt = $state.ResultBoxes['GPT'].Text;
       qwen = $state.ResultBoxes['Qwen'].Text; analysis = $state.AnalysisLabel.Text;
       copied_text = $state.Output; temp_removed = -not (Test-Path -LiteralPath $questionFile) } | ConvertTo-Json
} finally { Stop-AnswerRequest $state; $state.Timer.Dispose(); $state.Form.Dispose() }
''', '''
param([string]$File,[string]$GptProxy,[double]$Timeout,[switch]$Json,[switch]$JsonLines)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$question = [IO.File]::ReadAllText($File, [Text.Encoding]::UTF8)
Start-Sleep -Milliseconds 300
@{ type='complete'; question = $question; models = @(
    @{provider='GPT'; answer='B'; reason='依据'; error=$null},
    @{provider='Qwen'; answer='B'; reason=('代理变量：' + $env:OPENAI_PROXY_URL); error=$null},
    @{provider='DeepSeek'; answer='B'; reason='依据'; error=$null});
    analysis='三个模型答案是否一致：一致。' } | ConvertTo-Json -Depth 5 -Compress
''', {'OPENAI_PROXY_URL': 'http://127.0.0.1:9999'})
        self.assertTrue(all(result[key] for key in ('busy', 'duplicate_blocked', 'finished',
                        'button_enabled', 'copy_enabled', 'temp_removed', 'example_loaded')))
        self.assertIn('答案：B', result['gpt'])
        self.assertIn('答案：B', result['qwen'])
        self.assertNotIn('9999', result['qwen'])
        self.assertIn('一致', result['analysis'])
        self.assertIn("题目含中文 $() ' 引号", result['copied_text'])

    def test_backend_failure_is_visible_and_restores_controls(self):
        result = self.run_powershell('''
$state = New-AnswerWindow -RunnerPath $RunnerPath
try {
    $state.QuestionBox.Text = '测试题'
    Start-AnswerRequest $state
    $limit = [DateTime]::UtcNow.AddSeconds(10)
    while ($state.Process -and [DateTime]::UtcNow -lt $limit) {
        Update-AnswerRequest $state
        Start-Sleep -Milliseconds 50
    }
    @{ finished = ($null -eq $state.Process); button_enabled = $state.StartButton.Enabled;
       output = $state.Output; status = $state.StatusLabel.Text } | ConvertTo-Json
} finally { Stop-AnswerRequest $state; $state.Timer.Dispose(); $state.Form.Dispose() }
''', '''
param([string]$File,[string]$GptProxy,[double]$Timeout,[switch]$Json,[switch]$JsonLines)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::Error.WriteLine('连接失败，请检查配置')
exit 2
''')
        self.assertTrue(result['finished'])
        self.assertTrue(result['button_enabled'])
        self.assertIn('连接失败', result['output'])
        self.assertIn('失败', result['status'])

    def test_enter_submits_and_shift_enter_does_not_submit(self):
        result = self.run_powershell('''
$state = New-AnswerWindow -RunnerPath $RunnerPath
try {
    $state.QuestionBox.Text = '键盘测试题'
    Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @'
using System.Reflection;
using System.Windows.Forms;
public static class AnswerKeyboardTest {
    public static KeyEventArgs Press(Control control, Keys keys) {
        var args = new KeyEventArgs(keys);
        typeof(Control).GetMethod("OnKeyDown", BindingFlags.Instance | BindingFlags.NonPublic)
            .Invoke(control, new object[] { args });
        return args;
    }
}
'@
    $shiftEvent = [AnswerKeyboardTest]::Press($state.QuestionBox,
        [Windows.Forms.Keys]::Enter -bor [Windows.Forms.Keys]::Shift)
    $shiftIdle = $null -eq $state.Process
    $enterEvent = [AnswerKeyboardTest]::Press($state.QuestionBox, [Windows.Forms.Keys]::Enter)
    @{ shift_idle=$shiftIdle; shift_suppressed=$shiftEvent.SuppressKeyPress;
       enter_started=($null -ne $state.Process); enter_suppressed=$enterEvent.SuppressKeyPress } | ConvertTo-Json
} finally { Stop-AnswerRequest $state; $state.Timer.Dispose(); $state.Form.Dispose() }
''', '''
param([string]$File,[string]$GptProxy,[double]$Timeout,[switch]$JsonLines)
Start-Sleep -Seconds 8
''')
        self.assertTrue(result['shift_idle'])
        self.assertFalse(result['shift_suppressed'])
        self.assertTrue(result['enter_started'])
        self.assertTrue(result['enter_suppressed'])

    def test_early_answer_visible_while_analysis_waits_and_failure_is_preserved(self):
        result = self.run_powershell('''
$state = New-AnswerWindow -RunnerPath $RunnerPath
try {
    $state.Form.Show()
    $state.QuestionBox.Text = '逐条显示测试题'
    $state.StartButton.PerformClick()
    $limit = [DateTime]::UtcNow.AddSeconds(10)
    while (-not $state.ResultBoxes['Qwen'].Text.Contains('答案：B') -and [DateTime]::UtcNow -lt $limit) {
        [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 30
    }
    $early = $state.ResultBoxes['Qwen'].Text.Contains('答案：B') -and $state.Process -and -not $state.Process.HasExited
    $gptWaiting = $state.ResultBoxes['GPT'].Text.Contains('稍候')
    $analysisWaiting = $state.AnalysisLabel.Text.Contains('等待')
    while ($state.Process -and [DateTime]::UtcNow -lt $limit) {
        [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 30
    }
    @{ early_visible=[bool]$early; gpt_waiting=$gptWaiting; analysis_waiting=$analysisWaiting;
       finished=($null -eq $state.Process); qwen=$state.ResultBoxes['Qwen'].Text;
       deepseek=$state.ResultBoxes['DeepSeek'].Text; gpt=$state.ResultBoxes['GPT'].Text;
       analysis=$state.AnalysisLabel.Text; copy_enabled=$state.CopyButton.Enabled } | ConvertTo-Json
} finally { Stop-AnswerRequest $state; $state.Timer.Dispose(); $state.Form.Dispose() }
''', '''
param([string]$File,[string]$GptProxy,[double]$Timeout,[switch]$JsonLines)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$question = [IO.File]::ReadAllText($File, [Text.Encoding]::UTF8)
$qwen = @{provider='Qwen';answer='B';reason='先完成';error=$null}
$deepseek = @{provider='DeepSeek';answer='';reason='';error='模拟连接失败'}
$gpt = @{provider='GPT';answer='B';reason='最后完成';error=$null}
foreach ($model in @($qwen,$deepseek,$gpt)) {
    [Console]::WriteLine((@{type='model_result';result=$model} | ConvertTo-Json -Depth 5 -Compress))
    [Console]::Out.Flush()
    Start-Sleep -Milliseconds 900
}
[Console]::WriteLine((@{type='complete';question=$question;models=@($gpt,$qwen,$deepseek);
    analysis='三个模型答案是否一致：无法完整比较（有模型调用失败）。'} | ConvertTo-Json -Depth 5 -Compress))
exit 1
''')
        self.assertTrue(all(result[key] for key in ('early_visible', 'gpt_waiting', 'analysis_waiting',
                                                  'finished', 'copy_enabled')))
        self.assertIn('答案：B', result['qwen'])
        self.assertIn('答案：B', result['gpt'])
        self.assertIn('模拟连接失败', result['deepseek'])
        self.assertIn('无法完整比较', result['analysis'])


if __name__ == '__main__':
    unittest.main()
