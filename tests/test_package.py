import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from settings import load
from prepare import enumerate_cases

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dashboard', ROOT / 'scripts/dashboard.py')
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


class PackageTests(unittest.TestCase):
    def test_config_rejects_lower_memory_floor(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'config.json'
            file.write_text(json.dumps({k: '/fake' for k in ('benchmark_root', 'jev_checkpoint', 'jev_backbone', 'advisor_model')} | {'mem_available_min_gib': 49}))
            with self.assertRaises(ValueError):
                load(file)

    def test_numeric_case_order_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for number in (10, 2, 1):
                file = root / 'benchmark/system/fault' / str(number) / 'metadata.json'
                file.parent.mkdir(parents=True)
                file.write_text('{"DO_NOT_READ":true}')
            values = list(enumerate_cases(root).values())
            self.assertEqual([p.parent.name for p in values], ['1', '2', '10'])

    def test_dashboard_bundle_complete_without_labels(self):
        store = dashboard.Store()
        progress = store.progress()
        self.assertEqual(len(progress['cases']), 754)
        self.assertEqual(progress['phase'], 'complete')
        self.assertEqual(progress['completed_arms'], 754 * len(store.arms()))
        if progress.get('method_family') == 'online_single_pass':
            self.assertEqual(progress['summary']['worker_forbidden_attempts'], 0)
            self.assertEqual(len(progress['timeline']), 754)
            self.assertEqual(progress['summary']['retrospective_predictions'], 0)
        elif progress.get('method_family') == 'active_search':
            self.assertEqual(progress['summary']['worker_forbidden_attempts'], 0)
            self.assertEqual(len(progress['timeline']), progress['summary']['evolution']['proposals'])
        else:
            self.assertEqual(len(progress['timeline']), 96)
            self.assertEqual(sum(e['accepted'] for e in progress['timeline']), 10)
        for case in progress['cases']:
            self.assertNotIn('gold', case)
            self.assertNotIn('query', case)

    def test_case_trace_has_no_benchmark_payload(self):
        trace = dashboard.Store().case('case_0000')
        self.assertEqual(set(trace), set(dashboard.Store().arms()))
        self.assertTrue(all('output' not in s for t in trace.values() for s in t['steps']))

    def test_case_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            dashboard.Store().case('../sealed_evaluation/labels')

    def test_missing_case_rejected(self):
        with self.assertRaises(FileNotFoundError):
            dashboard.Store().case('case_9999')

    def test_only_requested_case_documentation_is_bundled(self):
        for name in ('examples', 'results', 'reports'):
            self.assertFalse((ROOT / name).exists())
        files = sorted(p.name for p in (ROOT / 'docs').iterdir()) if (ROOT / 'docs').exists() else []
        self.assertEqual(files, ['case_walkthroughs.json', 'methodology.md', 'reproduce.md'])

    def test_method_document_is_modular_and_has_no_semicolons(self):
        text = (ROOT / 'docs/methodology.md').read_text()
        self.assertNotIn(';', text)
        self.assertNotIn('\uff1b', text)
        self.assertIn('一句话概括', text)
        self.assertEqual(len(re.findall(r'^## \d+\.', text, re.M)), 8)
        self.assertEqual(text.count('**输入。**'), 8)
        self.assertEqual(text.count('**输出。**'), 8)
        self.assertIn('../README.html', text)

    def test_method_page_and_assets_are_served_read_only(self):
        for route, path, mime in (
            ('/README.html', 'README.html', 'text/html'),
            ('/docs/methodology.md', 'docs/methodology.md', 'text/plain'),
            ('/web/methodology.js', 'web/methodology.js', 'text/javascript'),
            ('/web/methodology.css', 'web/methodology.css', 'text/css'),
            ('/web/cursor.css', 'web/cursor.css', 'text/css'),
            ('/cursor.css', 'web/cursor.css', 'text/css'),
            ('/web/lucide.min.js', 'web/lucide.min.js', 'text/javascript'),
        ):
            with self.subTest(route=route):
                response = {}
                request = object.__new__(dashboard.handler(dashboard.Store()))
                request.path = route
                request.reply = lambda body, content_type: response.update(body=body, mime=content_type)
                request.do_GET()
                self.assertEqual(response['mime'], mime)
                self.assertEqual(response['body'], (ROOT / path).read_bytes())

    def test_readme_is_compact_and_local_documentation_links_resolve(self):
        text = (ROOT / 'README.md').read_text()
        self.assertLessEqual(len(text.splitlines()), 80)
        self.assertIn('docs/methodology.md', text)
        self.assertIn('scripts/prepare_online.py', text)
        self.assertIn('configs/local.json', text)
        self.assertNotIn('[完整运行指南]', text)
        for path in (ROOT / 'README.md', ROOT / 'docs/methodology.md', ROOT / 'docs/reproduce.md'):
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' not in target and not target.startswith('#'):
                    self.assertTrue((path.parent / target.split('#', 1)[0]).is_file(), target)

    def test_readme_media_files_exist(self):
        media = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', (ROOT / 'README.md').read_text())
        self.assertEqual(set(media), {'workflow.png'})
        self.assertTrue(all((ROOT / file).is_file() for file in media))

    def test_workflow_endpoint_uses_project_root(self):
        response = {}
        handler = object.__new__(dashboard.handler(dashboard.Store()))
        handler.path = '/workflow.png'
        handler.reply = lambda body, mime: response.update(body=body, mime=mime)
        handler.do_GET()
        self.assertEqual(response['mime'], 'image/png')
        self.assertEqual(response['body'], (ROOT / 'workflow.png').read_bytes())

    def test_admitted_rule_origins_preserved(self):
        progress = dashboard.Store().progress()
        if progress.get('method_family') == 'online_single_pass':
            learned = {rule for e in progress['timeline'] for rule in e.get('accepted_rule_ids', [])}
            self.assertTrue(learned.issubset({r['id'] for r in progress['rules']}))
            return
        learned = {e['rule']['id'] for e in progress['timeline'] if e['accepted']}
        self.assertEqual(len(learned), sum(e['accepted'] for e in progress['timeline']))
        self.assertTrue(learned.issubset({r['id'] for r in progress['rules']}))

    def test_presentation_has_all_frozen_traces(self):
        store = dashboard.Store()
        for case in store.progress()['cases']:
            self.assertEqual(set(store.case(case['case'])), set(store.arms()))

    def test_source_code_not_bundled_in_presentation(self):
        store = dashboard.Store()
        for case in store.progress()['cases']:
            for trace in store.case(case['case']).values():
                self.assertNotIn('gold', trace)
                self.assertNotIn('query', trace)
                for step in trace['steps']:
                    self.assertEqual(set(step), {'tool', 'arguments', 'elapsed_sec', 'error'})

    def test_accuracy_counts_unchanged(self):
        progress = dashboard.Store().progress()
        for arm in dashboard.Store().arms():
            count = sum(row['arms'][arm]['correct'] for row in progress['cases'])
            self.assertEqual(count, progress['summary']['metrics'][arm]['correct'])

    def test_solver_cannot_read_frontend_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / 'config.json').write_text(json.dumps({'project_root': str(ROOT), 'benchmark_root': str(run / 'benchmark')}))
            code = ('from pathlib import Path; from isolation import install; '
                    'import sys; run=Path(sys.argv[1]); install(run,run/"access.jsonl"); '
                    'Path(sys.argv[2]).read_bytes()')
            result = subprocess.run([sys.executable, '-B', '-c', code, str(run),
                                     str(ROOT / 'web/presentation.json.gz')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('PermissionError', result.stderr)


if __name__ == '__main__':
    unittest.main()
