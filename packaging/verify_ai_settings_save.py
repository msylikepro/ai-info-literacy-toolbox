"""Exercise the real repeated-save UI regression against an arbitrary packaged module."""
import argparse
import io
import json
from pathlib import Path
import types
import unittest

parser = argparse.ArgumentParser()
parser.add_argument('module', type=Path)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--expect-failure', action='store_true')
args = parser.parse_args()
tests = Path(__file__).resolve().parents[1] / '01_三AI同查/tests/test_desktop.py'
code = tests.read_text(encoding='utf-8').replace('$state.Form.Show()',
    '$state.Form.StartPosition = [Windows.Forms.FormStartPosition]::Manual; '
    '$state.Form.Location = New-Object Drawing.Point(-15000,-15000); $state.Form.Show()')
module = types.ModuleType('packaged_ai_save_test')
module.__file__ = str(tests)
exec(compile(code, str(tests), 'exec'), module.__dict__)
module.ROOT = args.module.resolve()
suite = unittest.TestSuite([module.DesktopTest('test_thinking_save_button_overwrites_existing_settings_repeatedly')])
output = io.StringIO()
result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
assert result.testsRun == 1 and not result.skipped
report = {'passed': result.wasSuccessful(), 'expectedFailure': args.expect_failure,
          'module': str(module.ROOT), 'testsRun': result.testsRun, 'output': output.getvalue()}
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: report[k] for k in ('passed','expectedFailure','testsRun')}, ensure_ascii=True))
if result.wasSuccessful() == args.expect_failure:
    print(output.getvalue())
    raise SystemExit('Unexpected repeated-save regression result')
