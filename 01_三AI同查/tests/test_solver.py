import io
from dataclasses import replace
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

try:
    import solver
except ModuleNotFoundError:
    solver = None


class SolverTest(unittest.TestCase):
    def test_thinking_levels_are_sent_and_have_sufficient_output_budget(self):
        for provider, field, levels in (
            ('GPT','openai_reasoning_effort',('low','medium','high','xhigh','max')),
            ('Qwen','qwen_reasoning_effort',('off','low','medium','xhigh')),
            ('DeepSeek','deepseek_reasoning_effort',('off','low','high','max'))):
            for level in levels:
                with self.subTest(provider=provider,level=level):
                    settings=replace(self.settings,**{field:level})
                    data=({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"answer":"A","reason":"依据"}'}]}]}
                          if provider=='GPT' else {'choices':[{'message':{'content':'{"answer":"A","reason":"依据"}','reasoning_content':'private reasoning'},'finish_reason':'stop'}]})
                    with patch.object(solver.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(data).encode())) as api:
                        answer=solver.call_api(provider,'测试题',settings)
                    body=json.loads(api.call_args.args[0].data)
                    self.assertEqual(answer,{'answer':'A','reason':'依据'})
                    if provider=='GPT':self.assertEqual(body['reasoning']['effort'],level)
                    elif provider=='Qwen':self.assertEqual(body['enable_thinking'],level!='off')
                    else:self.assertEqual(body['thinking']['type'],'disabled' if level=='off' else 'enabled')
                    if provider!='GPT' and level!='off':
                        self.assertEqual(body['reasoning_effort'],level)
                        self.assertGreaterEqual(body['max_tokens'],8192)
                    elif provider!='GPT':self.assertNotIn('reasoning_effort',body)

    def test_invalid_thinking_levels_are_rejected_before_sending(self):
        for field,value,provider in [('openai_reasoning_effort','off','GPT'),('qwen_reasoning_effort','high','Qwen'),('deepseek_reasoning_effort','medium','DeepSeek')]:
            with self.subTest(field=field),patch.object(solver.urllib.request,'urlopen') as api:
                with self.assertRaisesRegex(ValueError,'思考'):
                    solver.call_api(provider,'测试题',replace(self.settings,**{field:value}))
                api.assert_not_called()

    def test_blank_model_and_thinking_environment_falls_back_to_defaults(self):
        with patch.dict(solver.os.environ,{'QWEN_MODEL':'','DEEPSEEK_MODEL':'','QWEN_REASONING_EFFORT':'','DEEPSEEK_REASONING_EFFORT':''}):
            settings=solver.Settings.from_env()
        self.assertEqual(settings.qwen_model,'qwen3.8-max')
        self.assertEqual(settings.deepseek_model,'deepseek-flash')
        self.assertEqual(settings.qwen_reasoning_effort,'off')
        self.assertEqual(settings.deepseek_reasoning_effort,'off')

    def setUp(self):
        self.assertIsNotNone(solver, '缺少三模型核心调用模块 solver.py')
        self.settings = solver.Settings(openai_key='gpt-test', qwen_key='qwen-test', deepseek_key='ds-test')

    def test_three_providers_overlap_even_when_api_answers_agree(self):
        barrier = threading.Barrier(3)
        seen = []
        lock = threading.Lock()

        def respond(provider, question, settings):
            with lock:
                seen.append((provider, question))
            barrier.wait(timeout=2)
            return {'answer': 'B', 'reason': '由通用知识判断。'}

        with patch.object(solver, 'call_api', side_effect=respond):
            results = solver.answer_question('示例题', self.settings)
        self.assertEqual(sorted(seen), [('DeepSeek', '示例题'), ('GPT', '示例题'), ('Qwen', '示例题')])
        self.assertEqual([r.provider for r in results], ['GPT', 'Qwen', 'DeepSeek'])
        self.assertEqual([r.answer for r in results], ['B', 'B', 'B'])
        self.assertTrue(all(r.error is None for r in results))

    def test_provider_failure_preserves_other_answers_and_is_not_consistent(self):
        def respond(provider, question, settings):
            if provider == 'GPT':
                raise TimeoutError('请求超时 gpt-test')
            return {'answer': 'A', 'reason': '理由'}

        with patch.object(solver, 'call_api', side_effect=respond):
            results = solver.answer_question('测试题', self.settings)
        self.assertIsNotNone(results[0].error)
        self.assertNotIn('gpt-test', results[0].error)
        self.assertEqual([r.answer for r in results[1:]], ['A', 'A'])
        self.assertIn('无法完整比较', solver.compare_answers(results))

    def test_fast_model_is_reported_before_slow_models_finish(self):
        release = threading.Event()
        events = []

        def respond(provider, question, settings):
            if provider != 'Qwen' and not release.wait(3):
                raise TimeoutError('等待增量结果回调')
            return {'answer': 'B', 'reason': '依据'}

        def completed(result):
            events.append(result.provider)
            if result.provider == 'Qwen':
                self.assertEqual(events, ['Qwen'])
                release.set()

        with patch.object(solver, 'call_api', side_effect=respond):
            results = solver.answer_question('测试题', self.settings, on_result=completed)
        self.assertEqual(events[0], 'Qwen')
        self.assertEqual(set(events), {'GPT', 'Qwen', 'DeepSeek'})
        self.assertEqual([r.provider for r in results], ['GPT', 'Qwen', 'DeepSeek'])
        self.assertTrue(all(r.error is None for r in results))

    def test_json_lines_emit_three_results_then_final_analysis(self):
        output = io.StringIO()
        with patch.object(solver, 'call_api', return_value={'answer': 'B', 'reason': '依据'}), \
                patch.object(solver.sys, 'stdout', output):
            code = solver.main(['--json-lines', '测试题'])
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual([event['type'] for event in events], ['model_result'] * 3 + ['complete'])
        self.assertEqual({event['result']['provider'] for event in events[:3]}, set(solver.PROVIDERS))
        self.assertTrue(all('analysis' not in event for event in events[:3]))
        self.assertIn('一致', events[-1]['analysis'])

    def test_consistency_normalizes_choices_and_judgements(self):
        for answers in [('Ａ、Ｃ', 'CA', 'A, C'), ('正确', '对', 'true')]:
            with self.subTest(answers=answers):
                results = [solver.Result(p, a, '理由') for p, a in zip(solver.PROVIDERS, answers)]
                question = '多选题：A. 第一项 C. 第三项' if answers[0] == 'Ａ、Ｃ' else '判断题'
                self.assertIn('一致', solver.compare_answers(results, question))
                self.assertNotIn('不一致', solver.compare_answers(results, question))
        results = [solver.Result(p, a, '理由') for p, a in zip(solver.PROVIDERS, ('A', 'B', 'A'))]
        self.assertIn('不一致', solver.compare_answers(results))
        self.assertIn('GPT：A', solver.compare_answers(results))

    def test_free_text_is_not_treated_as_a_set_of_option_letters(self):
        for answers in [('AI', 'IA', 'AI'), ('CAD', 'DAC', 'CAD')]:
            with self.subTest(answers=answers):
                results = [solver.Result(p, a, '理由') for p, a in zip(solver.PROVIDERS, answers)]
                self.assertIn('不一致', solver.compare_answers(results))

    def test_api_arrearage_is_reported_as_account_issue(self):
        failure = urllib.error.HTTPError('https://example.com', 400, 'Bad Request', {},
            io.BytesIO(b'{"error":{"code":"Arrearage","message":"qwen-test"}}'))
        with patch.object(solver.urllib.request, 'urlopen', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, '欠费|余额不足') as error:
                solver.call_api('Qwen', '题目', self.settings)
        self.assertNotIn('qwen-test', str(error.exception))

    def test_parse_structured_answer_rejects_empty_or_invalid_fields(self):
        good = '```json\n{"answer":" A ","reason":" 简要依据 "}\n```'
        self.assertEqual(solver.parse_answer(good), {'answer': 'A', 'reason': '简要依据'})
        for bad in ['不是JSON', '{}', '[]', '{"answer":"", "reason":"x"}',
                    '{"answer":true, "reason":"x"}', '{"answer":"A", "reason":" "}']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                solver.parse_answer(bad)

    def test_output_has_question_three_answers_and_analysis_in_order(self):
        results = [solver.Result(p, 'A', '简要依据') for p in solver.PROVIDERS]
        output = solver.format_output('题干\nA. 选项', results)
        self.assertTrue(output.startswith('题目：\n题干\nA. 选项'))
        self.assertEqual(output.count('答案：A'), 3)
        self.assertEqual(output.count('理由：简要依据'), 3)
        headings = ['======== GPT ========', '======== Qwen ========',
                    '======== DeepSeek ========', '======== 综合分析 ========']
        offsets = [output.index(h) for h in headings]
        self.assertEqual(offsets, sorted(offsets))

    def test_api_request_uses_each_provider_credentials_and_only_question(self):
        response_data = {'choices': [{'message': {'role': 'assistant',
                         'content': '{"answer":"B","reason":"依据"}'}, 'finish_reason': 'stop'}]}
        observed = []

        def urlopen(request, timeout):
            observed.append((request.full_url, request.get_header('Authorization'),
                             json.loads(request.data), timeout))
            data = response_data
            if request.full_url.endswith('/responses'):
                data = {'status': 'completed', 'output': [
                    {'type': 'reasoning', 'summary': []},
                    {'type': 'message', 'content': [{'type': 'output_text',
                        'text': '{"answer":"B","reason":"依据"}'}]}]}
            return io.BytesIO(json.dumps(data).encode('utf-8'))

        with patch.object(solver.urllib.request, 'urlopen', side_effect=urlopen):
            for provider in solver.PROVIDERS:
                self.assertEqual(solver.call_api(provider, '仅这道题', self.settings)['answer'], 'B')
        self.assertEqual([r[1] for r in observed], ['Bearer gpt-test', 'Bearer qwen-test', 'Bearer ds-test'])
        self.assertEqual([r[2]['model'] for r in observed], ['gpt-6.1-sol', 'qwen3.8-max', 'deepseek-flash'])
        self.assertEqual(observed[0][0], 'https://api.openai.com/v1/responses')
        self.assertEqual(observed[0][2]['reasoning']['effort'], 'medium')
        self.assertGreaterEqual(observed[0][2]['max_output_tokens'], 4096)
        self.assertNotIn('max_tokens', observed[0][2])
        self.assertEqual(observed[0][2]['text']['format']['type'], 'json_schema')
        self.assertTrue(observed[0][2]['text']['format']['strict'])
        self.assertFalse(observed[0][2]['store'])
        self.assertNotIn('reasoning_effort', observed[1][2])
        self.assertNotIn('reasoning_effort', observed[2][2])
        self.assertTrue(all(r[0].endswith('/chat/completions') for r in observed[1:]))
        self.assertEqual(observed[0][2]['input'], [{'role': 'user', 'content': '仅这道题'}])
        self.assertTrue(all(r[2]['messages'][1] == {'role': 'user', 'content': '仅这道题'} for r in observed[1:]))
        self.assertTrue(all('tools' not in r[2] for r in observed))

    def test_api_missing_key_and_http_error_do_not_expose_secret(self):
        with self.assertRaisesRegex(ValueError, 'QWEN_API_KEY'):
            solver.call_api('Qwen', '题目', solver.Settings())
        with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
            solver.call_api('GPT', '题目', solver.Settings())
        failure = urllib.error.HTTPError('https://example.com', 401, 'qwen-test', {},
                                         io.BytesIO(b'qwen-test'))
        with patch.object(solver.urllib.request, 'urlopen', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 401') as error:
                solver.call_api('Qwen', '题目', self.settings)
        self.assertNotIn('qwen-test', str(error.exception))

    def test_gpt_proxy_is_scoped_to_its_request(self):
        response = {'choices': [{'message': {'content': '{"answer":"B","reason":"依据"}'}}]}
        settings = solver.Settings(openai_key='gpt-test', qwen_key='qwen-test',
                                   openai_proxy='http://127.0.0.1:7897')
        with patch.object(solver.urllib.request, 'build_opener') as builder, \
                patch.object(solver.urllib.request, 'urlopen') as direct:
            gpt_response = {'status': 'completed', 'output': [{'type': 'message',
                'content': [{'type': 'output_text', 'text': '{"answer":"B","reason":"依据"}'}]}]}
            builder.return_value.open.return_value = io.BytesIO(json.dumps(gpt_response).encode())
            direct.return_value = io.BytesIO(json.dumps(response).encode())
            before = dict(solver.os.environ)
            self.assertEqual(solver.call_api('GPT', '题目', settings)['answer'], 'B')
            self.assertEqual(solver.call_api('Qwen', '题目', settings)['answer'], 'B')
            self.assertEqual(dict(solver.os.environ), before)
        builder.assert_called_once()
        self.assertEqual(builder.call_args.args[0].proxies, {
            'http': settings.openai_proxy, 'https': settings.openai_proxy})
        self.assertEqual(builder.return_value.open.call_args.args[0].get_header('Authorization'), 'Bearer gpt-test')
        self.assertEqual(direct.call_args.args[0].get_header('Authorization'), 'Bearer qwen-test')

    def test_gpt_environment_settings_and_medium_default(self):
        with patch.dict(solver.os.environ, {'OPENAI_API_KEY': 'local-test',
                'OPENAI_BASE_URL': 'https://api.openai.com/v1', 'OPENAI_MODEL': '',
                'OPENAI_REASONING_EFFORT': '', 'OPENAI_PROXY_URL': 'http://127.0.0.1:7897'}):
            settings = solver.Settings.from_env()
        self.assertEqual(settings.openai_key, 'local-test')
        self.assertEqual(settings.openai_model, 'gpt-6.1-sol')
        self.assertEqual(settings.openai_reasoning_effort, 'medium')
        self.assertEqual(settings.openai_proxy, 'http://127.0.0.1:7897')

    def test_gpt_network_errors_quota_and_truncated_response(self):
        failures = [
            (urllib.error.URLError('gpt-test'), '超时|网络'),
            (urllib.error.HTTPError('https://api.openai.com', 429, 'private', {},
                io.BytesIO(b'{"error":{"code":"insufficient_quota","message":"gpt-test"}}')), '额度不足'),
            (urllib.error.HTTPError('https://api.openai.com', 401, 'private', {},
                io.BytesIO(b'gpt-test')), 'HTTP 401'),
        ]
        for failure, expected in failures:
            with self.subTest(expected=expected), \
                    patch.object(solver.urllib.request, 'urlopen', side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, expected) as error:
                    solver.call_api('GPT', '题目', self.settings)
                self.assertNotIn('gpt-test', str(error.exception))
        response = {'status': 'incomplete', 'output': []}
        with patch.object(solver.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaisesRegex(ValueError, '未完整返回'):
                solver.call_api('GPT', '题目', self.settings)

    def test_blank_question_does_not_launch_requests(self):
        with self.assertRaises(ValueError):
            solver.answer_question(' \n ', self.settings)

    def test_json_output_preserves_special_question_text(self):
        question = '题目：======== GPT ======== and ======== Qwen ========'
        results = [solver.Result(p, 'B', '依据') for p in solver.PROVIDERS]
        output = io.StringIO()
        with patch.object(solver, 'answer_question', return_value=results), patch.object(solver.sys, 'stdout', output):
            code = solver.main(['--json', question])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload['question'], question)
        self.assertEqual([m['answer'] for m in payload['models']], ['B', 'B', 'B'])
        self.assertIn('一致', payload['analysis'])

    @unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell not available')
    def test_windows_launcher_handles_utf8_source_and_propagates_input_error(self):
        # Exercise the real launcher without touching personal DPAPI data or a source .venv.
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / 'app'
            stage.mkdir()
            for name in ('run_solver.ps1', 'solver.py', 'thinking_config.ps1'):
                shutil.copy2(Path(__file__).resolve().parents[1] / name, stage / name)
            for credential_args in ([], ['-CredentialFile', 'nonexistent-credentials.json']):
                with self.subTest(credential_args=credential_args):
                    process = subprocess.run(
                        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                         str(stage / 'run_solver.ps1'), '-Question', '测试题', '-Timeout', '0', *credential_args],
                        capture_output=True, encoding='utf-8', errors='replace', timeout=10,
                        env={**os.environ, 'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']},
                    )
                    self.assertEqual(process.returncode, 2, process.stderr)
                    self.assertIn('输入错误', process.stderr)


if __name__ == '__main__':
    unittest.main()
