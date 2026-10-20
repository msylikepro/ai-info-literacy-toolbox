"""Windows-only end-to-end checks; every credential is an obviously fake fixture."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HERE = Path(__file__).resolve().parent
COMPILER = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI is required')
class SharedApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='shared-api-fake-tests-')
        cls.host = Path(cls.work.name) / 'test.exe'
        subprocess.run([str(COMPILER), '/nologo', '/target:exe', '/main:SharedApiTestHost',
                        '/codepage:65001', '/reference:System.Windows.Forms.dll',
                        '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll',
                        '/reference:System.Security.dll', '/out:' + str(cls.host),
                        str(HERE.parent / 'SharedApiConfig.cs'), str(HERE / 'SharedApiTestHost.cs')], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.work.name)
        self.root = Path(self.temp.name)
        self.target = self.root / 'toolbox'
        data = self.target / '01_三AI同查/data'
        data.mkdir(parents=True)
        (self.target / 'AI信息素养工具箱.exe').write_bytes(b'fake launcher')
        (self.target / 'build-manifest.json').write_text(json.dumps({
            'product': 'AI信息素养工具箱_Windows免安装版', 'version': '1.3.0',
            'files': [{'path': 'AI信息素养工具箱.exe', 'bytes': 13,
                       'sha256': hashlib.sha256(b'fake launcher').hexdigest()}]}), encoding='utf-8')
        self.config = data / 'api-keys.dpapi.json'
        self.source = self.root / 'source.json'
        self.output = self.root / 'package'
        self.output.mkdir()
        self.password = self.root / 'separate-password.txt'
        self.call('fixture', self.source)
        self.call('export', self.source, self.output, self.password)
        self.encrypted = self.output / 'shared-api.enc.json'

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args, succeeds=True):
        result = subprocess.run([str(self.host), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if succeeds else 1, result.stdout + result.stderr)
        self.assertNotIn('FAKE-', result.stdout + result.stderr)
        return result

    def import_config(self, password=None, succeeds=True):
        self.call('import', self.target, self.encrypted,
                  password or self.password.read_text(encoding='utf-8').strip(), succeeds=succeeds)

    def snapshot(self):
        return {str(p.relative_to(self.target)): p.read_bytes()
                for p in self.target.rglob('*') if p.is_file()}

    def test_roundtrip_dpapi_and_preserve_unknown_fields_and_backup(self):
        self.call('fixture', self.config)
        old = self.config.read_bytes()
        self.import_config()
        self.call('verify', self.config)
        current = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(current['future_thinking'], {'mode': 'high', 'enabled': False})
        self.assertEqual(current['future_array'], [1, 'keep'])
        backups = list(self.config.parent.glob('api-*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old)
        self.assertNotIn(b'FAKE-', self.config.read_bytes())

    def test_new_config_and_password_kept_outside_package(self):
        self.import_config()
        self.call('verify', self.config)
        self.assertEqual({p.name for p in self.output.iterdir()}, {'shared-api.enc.json'})
        envelope = json.loads(self.encrypted.read_text(encoding='utf-8'))
        self.assertGreaterEqual(envelope['iterations'], 200000)
        self.assertGreaterEqual(len(self.password.read_text(encoding='utf-8').strip()), 40)
        self.assertNotIn(b'FAKE-', self.encrypted.read_bytes())

    def test_wrong_password_and_tampered_fields_never_mutate_target(self):
        self.call('fixture', self.config)
        before = self.snapshot()
        self.import_config('incorrect-password', succeeds=False)
        original = self.encrypted.read_text(encoding='utf-8')
        for field in ('salt', 'iv', 'ciphertext', 'mac'):
            envelope = json.loads(original)
            blob = bytearray(base64.b64decode(envelope[field]))
            blob[0] ^= 1
            envelope[field] = base64.b64encode(blob).decode()
            self.encrypted.write_text(json.dumps(envelope), encoding='utf-8')
            self.import_config(succeeds=False)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.snapshot(), before)

    def test_iteration_bounds_and_wrong_version_never_mutate_target(self):
        before = self.snapshot()
        original = self.encrypted.read_text(encoding='utf-8')
        for iterations in (0, 199999, 1000001):
            envelope = json.loads(original)
            envelope['iterations'] = iterations
            self.encrypted.write_text(json.dumps(envelope), encoding='utf-8')
            self.import_config(succeeds=False)
            self.assertEqual(self.snapshot(), before)
        self.encrypted.write_text(original, encoding='utf-8')
        manifest = self.target / 'build-manifest.json'
        manifest.write_text(manifest.read_text(encoding='utf-8').replace('1.3.0', '1.2.0'), encoding='utf-8')
        before = self.snapshot()
        self.import_config(succeeds=False)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_endpoint_export_rejected_without_secret_outputs(self):
        for endpoint in ('http://example.com', 'https://user:pass@example.com',
                         'https://example.com?v=secret', 'https://example.com#token',
                         'https://example.com/v1/responses'):
            self.call('fixture', self.source, endpoint)
            output = self.root / ('bad-' + hashlib.sha256(endpoint.encode()).hexdigest()[:8])
            output.mkdir()
            password = output.parent / (output.name + '.password')
            self.call('export', self.source, output, password, succeeds=False)
            self.assertEqual(list(output.iterdir()), [])
            self.assertFalse(password.exists())

    def test_password_inside_package_refused(self):
        self.call('export', self.source, self.output, self.output / 'password.txt', succeeds=False)
        self.assertFalse((self.output / 'password.txt').exists())

    def independent_decrypt(self):
        envelope = json.loads(self.encrypted.read_text(encoding='utf-8'))
        key = hashlib.pbkdf2_hmac('sha256', self.password.read_text(encoding='utf-8').strip().encode(),
                                 base64.b64decode(envelope['salt']), envelope['iterations'], 64)
        self.assertTrue(hmac.compare_digest(base64.b64decode(envelope['mac']),
                                          hmac.digest(key[32:], self.authentication_bytes(envelope), 'sha256')))
        decryptor = Cipher(algorithms.AES(key[:32]), modes.CBC(base64.b64decode(envelope['iv']))).decryptor()
        padded = decryptor.update(base64.b64decode(envelope['ciphertext'])) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return envelope, key, json.loads(unpadder.update(padded) + unpadder.finalize())

    @staticmethod
    def authentication_bytes(envelope):
        return '\n'.join(str(envelope[field]) for field in (
            'format', 'productId', 'targetVersion', 'kdf', 'cipher', 'iterations', 'salt', 'iv', 'ciphertext')).encode()

    def test_independent_pbkdf2_aes_hmac_roundtrip(self):
        envelope, key, payload = self.independent_decrypt()
        for prefix in ('deepseek', 'qwen', 'openai'):
            self.assertEqual(payload[prefix + '_key'], 'FAKE-ONLY-TEST-' + prefix)

    def test_authenticated_invalid_endpoint_rejected_without_mutation(self):
        envelope, key, payload = self.independent_decrypt()
        payload['openai_base_url'] = 'https://example.invalid?secret=123'
        padder = padding.PKCS7(128).padder()
        plain = json.dumps(payload).encode()
        padded = padder.update(plain) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key[:32]), modes.CBC(base64.b64decode(envelope['iv']))).encryptor()
        envelope['ciphertext'] = base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()
        envelope['mac'] = base64.b64encode(hmac.digest(key[32:], self.authentication_bytes(envelope), 'sha256')).decode()
        self.encrypted.write_text(json.dumps(envelope), encoding='utf-8')
        before = self.snapshot()
        self.import_config(succeeds=False)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_current_json_never_mutates_target(self):
        self.config.write_bytes(b'broken json')
        before = self.snapshot()
        self.import_config(succeeds=False)
        self.assertEqual(self.snapshot(), before)

    def test_junction_in_target_rejected(self):
        data = self.config.parent
        moved = self.root / 'real-data'
        data.rename(moved)
        command = "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path '{}' -Target '{}' | Out-Null".format(
            str(data).replace("'", "''"), str(moved).replace("'", "''"))
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], check=True, capture_output=True)
        try:
            self.import_config(succeeds=False)
            self.assertEqual(list(moved.iterdir()), [])
        finally:
            data.rmdir()  # Remove the junction itself, never recurse into its target.

    def test_real_builder_with_fake_credentials_compiles_gui_and_separate_password(self):
        output = self.root / 'real-builder'
        password = self.root / 'real-builder-password.txt'
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                 str(HERE.parent / 'build_shared_api.ps1'), '-CredentialFile', str(self.source),
                                 '-OutputDirectory', str(output), '-PasswordFile', str(password)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({p.name for p in output.iterdir()}, {'导入共享API配置.exe', 'shared-api.enc.json'})
        self.assertTrue(password.exists())
        self.call('import', self.target, output / 'shared-api.enc.json', password.read_text(encoding='utf-8').strip())
        self.call('verify', self.config)

    def test_target_prefill_preserves_blank_masked_password_and_no_automatic_import(self):
        before = self.snapshot()
        self.call('prefill', self.target)
        self.assertEqual(self.snapshot(), before)

    def test_toolbox_gate_held_by_separate_process_rejects_without_mutation(self):
        self.call('fixture', self.config)
        before = self.snapshot()
        holder = subprocess.Popen([str(self.host), 'hold-gate', str(self.target)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'HELD')
            self.import_config(succeeds=False)
            self.assertEqual(self.snapshot(), before)
        finally:
            holder.communicate('release\n', timeout=5)
        self.assertEqual(holder.returncode, 0)
        self.import_config()
        self.call('verify', self.config)

    def test_gate_released_after_decryption_rejection(self):
        self.import_config('incorrect-password', succeeds=False)
        self.import_config()
        self.call('verify', self.config)

    def test_pending_upgrade_journal_rejects_until_committed(self):
        journal = self.target / 'update-backups/fake-transaction/journal.json'
        journal.parent.mkdir(parents=True)
        for status in ('applying', 'validating', 'restoring-data', 'rollback-failed'):
            journal.write_text(json.dumps({'status': status, 'fromVersion': '1.2.0'}), encoding='utf-8')
            before = self.snapshot()
            self.import_config(succeeds=False)
            self.assertEqual(self.snapshot(), before)
        journal.write_text(json.dumps({'status': 'committed', 'fromVersion': '1.2.0'}), encoding='utf-8')
        committed = journal.read_bytes()
        self.import_config()
        self.call('verify', self.config)
        self.assertEqual(journal.read_bytes(), committed)

    def test_long_config_path_204_characters_imports_and_preserves_backup(self):
        suffix = '/01_三AI同查/data/api-keys.dpapi.json'
        name_length = 204 - len(str(self.root)) - 1 - len(suffix)
        long_target = self.root / ('long-' + 'x' * (name_length - 5))
        self.target.rename(long_target)
        self.target = long_target
        self.config = long_target / suffix.lstrip('/')
        self.assertEqual(len(str(self.config)), 204)
        self.call('fixture', self.config)
        old = self.config.read_bytes()
        self.import_config()
        self.call('verify', self.config)
        backups = list(self.config.parent.glob('api-*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertLess(len(str(backups[0])), 260)
        self.assertEqual(backups[0].read_bytes(), old)


if __name__ == '__main__':
    unittest.main()
