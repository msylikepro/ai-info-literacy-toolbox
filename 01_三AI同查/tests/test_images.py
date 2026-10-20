import base64
import io
import json
import os
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import solver
import test_desktop


def png(width=1, height=1):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0\xff\xff\xff')) + chunk(b'IEND', b''))


class ImageSolverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = Path(self.tmp.name) / '题目.png'
        self.image.write_bytes(png())
        self.settings = solver.Settings(openai_key='fake-gpt', qwen_key='fake-qwen', deepseek_key='fake-ds')

    def test_image_question_uses_native_vision_payload_and_retains_models(self):
        observed = []
        def respond(request, timeout):
            body = json.loads(request.data)
            observed.append(body)
            result = {'status': 'completed', 'output': [{'type': 'message', 'content': [
                {'type': 'output_text', 'text': '{"answer":"B","reason":"图中题目"}'}]}]} if request.full_url.endswith('/responses') else {
                'choices': [{'message': {'content': '{"answer":"B","reason":"图中题目"}'}, 'finish_reason': 'stop'}]}
            return io.BytesIO(json.dumps(result).encode())
        with patch.object(solver.urllib.request, 'urlopen', side_effect=respond):
            results = solver.answer_question('补充要求', self.settings, image=self.image)
        self.assertTrue(all(r.answer == 'B' for r in results))
        self.assertEqual({b['model'] for b in observed}, {'gpt-6.1-sol', 'qwen3.8-max', 'deepseek-flash'})
        uri = 'data:image/png;base64,' + base64.b64encode(self.image.read_bytes()).decode()
        for body in observed:
            if 'input' in body:
                self.assertEqual(body['input'][0]['content'], [
                    {'type': 'input_text', 'text': '补充要求'}, {'type': 'input_image', 'image_url': uri}])
                self.assertFalse(body['store'])
            else:
                self.assertEqual(body['messages'][1]['content'], [
                    {'type': 'text', 'text': '补充要求'}, {'type': 'image_url', 'image_url': {'url': uri}}])

    def test_image_only_cli_defaults_prompt_and_never_prints_image_or_path(self):
        output = io.StringIO()
        with patch.object(solver, 'call_api', return_value={'answer': 'B', 'reason': '依据'}) as api, \
                patch.object(solver.sys, 'stdout', output):
            code = solver.main(['--image', str(self.image), '--json-lines'])
        self.assertEqual(code, 0)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(events), 4)
        self.assertIn('识别', events[-1]['question'])
        self.assertNotIn(str(self.image), output.getvalue())
        self.assertNotIn('base64', output.getvalue())
        self.assertEqual(api.call_count, 3)

    def test_invalid_oversized_and_overdimension_images_fail_before_network(self):
        for content in (b'not image', png()[:-5], png(8193, 1), png(0, 1), b'x' * (10 * 1024 * 1024 + 1)):
            with self.subTest(size=len(content)), patch.object(solver.urllib.request, 'urlopen') as api:
                self.image.write_bytes(content)
                with self.assertRaisesRegex(ValueError, '图片|PNG|JPEG|8192|10'):
                    solver.answer_question('', self.settings, image=self.image)
                api.assert_not_called()


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows desktop required')
class ImageDesktopTest(unittest.TestCase):
    setUp = test_desktop.DesktopTest.setUp

    def run_powershell(self, body, runner_body=None, environment=None):
        # Keep the user's clipboard intact even when a UI assertion or fixture fails.
        body = '''
$imageClipboardBefore = [Windows.Forms.Clipboard]::GetDataObject()
try {
''' + body + '''
} finally {
    if ($null -ne $imageClipboardBefore) {
        [Windows.Forms.Clipboard]::SetDataObject($imageClipboardBefore, $true, 10, 100)
    } else {
        [Windows.Forms.Clipboard]::Clear()
    }
}
'''
        return test_desktop.DesktopTest.run_powershell(self, body, runner_body, environment)

    def test_upload_clipboard_remove_clear_and_busy_controls(self):
        result = self.run_powershell('''
$state = New-AnswerWindow -RunnerPath $RunnerPath
$bmp = New-Object Drawing.Bitmap(30, 20)
$path = Join-Path (Split-Path -Parent $RunnerPath) 'fixture.png'
try {
    $state.Form.Show()
    $bmp.Save($path, [Drawing.Imaging.ImageFormat]::Jpeg)
    Set-AnswerImageFromFile $state $path
    $loaded = $state.ImageBytes.Length -gt 0 -and $state.ImagePreview.Image.Width -eq 30
    [Windows.Forms.Clipboard]::SetDataObject($bmp, $true, 10, 100)
    $state.PasteImageButton.PerformClick()
    $pasted = $state.ImageBytes.Length -gt 0
    $jpegBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
    Set-AnswerBusy $state $true
    $disabled = -not $state.UploadImageButton.Enabled -and -not $state.PasteImageButton.Enabled -and -not $state.RemoveImageButton.Enabled
    Set-AnswerBusy $state $false
    $state.RemoveImageButton.PerformClick()
    $removed = $null -eq $state.ImageBytes -and $null -eq $state.ImagePreview.Image
    Set-AnswerImageFromFile $state $path
    $state.ClearButton.PerformClick()
    $cleared = $null -eq $state.ImageBytes -and $null -eq $state.ImagePreview.Image
    $invalid = Join-Path (Split-Path -Parent $RunnerPath) 'bad.png'
    [IO.File]::WriteAllText($invalid,'bad image')
    Set-AnswerImageFromFile $state $invalid
    $state.Form.Size = $state.Form.MinimumSize
    $state.Form.PerformLayout()
    @{loaded=$loaded;pasted=$pasted;disabled=$disabled;removed=$removed;cleared=$cleared;
      rejected=($null -eq $state.ImageBytes);status=$state.StatusLabel.Text;
      thumbnail_visible=$state.ImagePreview.Parent.ClientRectangle.Contains($state.ImagePreview.Bounds);
      jpeg=$jpegBase64;toolbar_visible=($state.ThinkingButton.Right -le $state.ThinkingButton.Parent.ClientSize.Width)} | ConvertTo-Json
} finally { Clear-AnswerImage $state; $bmp.Dispose(); $state.Timer.Dispose(); $state.Form.Dispose() }
''')
        self.assertTrue(all(result[key] for key in ('loaded', 'pasted', 'disabled', 'removed', 'cleared', 'rejected', 'toolbar_visible', 'thumbnail_visible')), {k: v for k, v in result.items() if k != 'jpeg'})
        self.assertIn('图片', result['status'])
        jpeg = self.directory / 'question.jpg'
        jpeg.write_bytes(base64.b64decode(result['jpeg']))
        self.assertEqual(solver.image_data_url(jpeg), 'data:image/jpeg;base64,' + result['jpeg'])

    def test_image_only_request_copies_to_temporary_directory_and_cleans_on_finish_and_cancel(self):
        result = self.run_powershell('''
$state = New-AnswerWindow -RunnerPath $RunnerPath
$bmp = New-Object Drawing.Bitmap(10,10)
try {
    $state.ProxyBox.Text = ''
    Set-AnswerImage $state $bmp 'fixture'
    Start-AnswerRequest $state
    $dir = $state.TempDirectory
    $copy = $state.ImageFile
    $busy = -not $state.UploadImageButton.Enabled
    $limit = [DateTime]::UtcNow.AddSeconds(8)
    while ($state.Process -and [DateTime]::UtcNow -lt $limit) { Update-AnswerRequest $state; Start-Sleep -Milliseconds 30 }
    $finished = $null -eq $state.Process
    $removed = -not (Test-Path -LiteralPath $dir)
    $output = $state.Output
    Start-AnswerRequest $state
    $cancelDir = $state.TempDirectory
    Stop-AnswerRequest $state
    @{busy=$busy;finished=$finished;removed=$removed;output=$output;
      cancelled_removed=(-not (Test-Path -LiteralPath $cancelDir));selected_retained=($state.ImageBytes.Length -gt 0)} | ConvertTo-Json
} finally { Stop-AnswerRequest $state; Clear-AnswerImage $state; $bmp.Dispose(); $state.Timer.Dispose(); $state.Form.Dispose() }
''', '''
param([string]$File,[string]$Image,[string]$GptProxy,[string]$ThinkingFile,[double]$Timeout,[switch]$JsonLines)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
if (-not (Test-Path -LiteralPath $Image)) { throw 'Image not copied' }
$bitmap = [System.Drawing.Image]::FromFile($Image)
$bitmap.Dispose()
$question = [IO.File]::ReadAllText($File)
@{type='complete';question=$question;models=@(@{provider='GPT';answer='B';reason='图片已收到'},@{provider='Qwen';answer='B';reason='图片已收到'},@{provider='DeepSeek';answer='B';reason='图片已收到'});analysis='一致'} | ConvertTo-Json -Depth 5 -Compress
''')
        self.assertTrue(all(result[k] for k in ('busy', 'finished', 'removed', 'cancelled_removed', 'selected_retained')), result)
        self.assertIn('图片已收到', result['output'])

    def test_ctrl_v_routes_images_but_leaves_text_paste_and_close_cleans_request(self):
        result = self.run_powershell('''
$state = New-AnswerWindow -RunnerPath $RunnerPath
$bmp = New-Object Drawing.Bitmap(20,20)
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @'
using System.Reflection;
using System.Windows.Forms;
public static class ImageKeyboardFixture {
    public static KeyEventArgs Paste(Control control) {
        var args = new KeyEventArgs(Keys.Control | Keys.V);
        typeof(Control).GetMethod("OnKeyDown", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(control, new object[] {args});
        return args;
    }
}
'@
try {
    $state.Form.Show()
    [Windows.Forms.Clipboard]::SetDataObject($bmp,$true,10,100)
    $imageEvent = [ImageKeyboardFixture]::Paste($state.QuestionBox)
    $imageHandled = $imageEvent.SuppressKeyPress -and $state.ImageBytes.Length -gt 0
    [Windows.Forms.Clipboard]::SetDataObject('普通题目文字',$true,10,100)
    $textEvent = [ImageKeyboardFixture]::Paste($state.QuestionBox)
    $state.QuestionBox.Text = '请只回答图中第一题'
    Start-AnswerRequest $state
    $directory = $state.TempDirectory
    $imageExists = Test-Path -LiteralPath $state.ImageFile
    $state.Form.Close()
    @{image_handled=[bool]$imageHandled;text_default=(-not $textEvent.SuppressKeyPress);
      image_copied=$imageExists;closed_cleanup=(-not (Test-Path -LiteralPath $directory));
      released=($null -eq $state.ImageBytes -and $null -eq $state.ImagePreview.Image)} | ConvertTo-Json
} finally { Stop-AnswerRequest $state; Clear-AnswerImage $state; $bmp.Dispose(); $state.Timer.Dispose(); $state.Form.Dispose() }
''', '''
param([string]$File,[string]$Image,[string]$GptProxy,[string]$ThinkingFile,[double]$Timeout,[switch]$JsonLines)
Start-Sleep -Seconds 8
''')
        self.assertTrue(all(result.values()), result)


if __name__ == '__main__':
    unittest.main()
