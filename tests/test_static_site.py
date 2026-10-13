import base64
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_site', ROOT / 'scripts/build_site.py')
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
audit_spec = importlib.util.spec_from_file_location('package_audit', ROOT / 'scripts/package_audit.py')
package_audit = importlib.util.module_from_spec(audit_spec)
audit_spec.loader.exec_module(package_audit)


def decode(path):
    args = json.loads('[' + path.read_text().split('(', 1)[1].rsplit(')', 1)[0] + ']')
    return args[0], json.loads(gzip.decompress(base64.b64decode(args[1])))


class StaticSiteTests(unittest.TestCase):
    def test_archive_audit_scans_decoded_content_and_rejects_invalid_wrappers(self):
        path = Path('web/archive/cases/case_0340.js')
        text = (ROOT / path).read_text()
        decoded = package_audit.archive_text(path, text)
        self.assertEqual(json.loads(decoded), decode(ROOT / path)[1])
        with self.assertRaises(ValueError):
            package_audit.archive_text(path, text + 'alert(1);')
        with self.assertRaises(ValueError):
            package_audit.archive_text(Path('web/archive/cases/case_0341.js'), text)

    def test_all_static_predictions_and_traces_equal_archive(self):
        original = json.loads(gzip.decompress((ROOT / 'web/presentation.json.gz').read_bytes()))
        extra = json.loads(gzip.decompress((ROOT / 'web/diagnostics.json.gz').read_bytes()))
        key, progress = decode(ROOT / 'web/archive/progress.js')
        self.assertEqual(key, 'progress')
        self.assertEqual(progress, original['progress'])
        files = list((ROOT / 'web/archive/cases').glob('*.js'))
        self.assertEqual(len(files), 754)
        self.assertEqual({path.stem for path in files}, set(original['cases']))
        for path in files:
            key, traces = decode(path)
            self.assertEqual(key, path.stem)
            expected = {arm: dict(trace, diagnostic=extra['cases'][key]) for arm, trace in original['cases'][key].items()}
            self.assertEqual(traces, expected)

    def test_generated_site_has_relative_links_and_no_server_requirement(self):
        text = (ROOT / 'index.html').read_text()
        self.assertIn('data-archive="static"', text)
        self.assertNotIn('src="/', text)
        self.assertNotIn('href="/', text)
        self.assertIn('web/archive.js', text)
        self.assertIn('web/integrated.js', text)
        self.assertTrue((ROOT / '.nojekyll').is_file())
        manifest = json.loads((ROOT / 'web/archive/manifest.json').read_text())
        self.assertEqual(manifest['new_inference_calls'], 0)

    def test_runbook_keeps_commands_and_cautions_inline(self):
        text = (ROOT / 'web/integrated.js').read_text()
        self.assertIn('scripts/prepare_online.py', text)
        self.assertIn('scripts/export_diagnostics.py', text)
        self.assertIn('run-notes', text)
        self.assertIn('MemAvailable', text)
        self.assertNotIn('runbook-links', text)
        self.assertNotIn('docs/reproduce.md', text)
        self.assertNotIn('<details>', text)
        self.assertNotIn('download=', text)

    def test_solver_cannot_read_static_case_or_documented_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / 'config.json').write_text(json.dumps({'project_root': str(ROOT), 'benchmark_root': str(run / 'benchmark')}))
            code = 'from pathlib import Path; from isolation import install; import sys; run=Path(sys.argv[1]); install(run,run/"access.jsonl"); Path(sys.argv[2]).read_bytes()'
            for name in ('web/archive/cases/case_0158.js', 'docs/case_walkthroughs.json', 'README.html'):
                result = subprocess.run([sys.executable, '-B', '-c', code, str(run), str(ROOT / name)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('PermissionError', result.stderr)


if __name__ == '__main__':
    unittest.main()
