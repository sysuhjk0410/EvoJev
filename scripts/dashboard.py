#!/usr/bin/env python3

import argparse
import gzip
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
ARMS = ('plain_jev', 'static_tree', 'previous_v3', 'evolved_tree')


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


class Store:
    def __init__(self, path=None):
        self.path = Path(path).resolve() if path is not None else None
        self.cache = None
        self.stamp = None
        self.detail_cache = None
        self.detail_stamp = None

    def arms(self):
        progress = self.progress()
        return tuple(progress.get('arms', ARMS))

    def presentation(self):
        file = ROOT / 'web/presentation.json.gz'
        stamp = file.stat().st_mtime_ns
        if stamp != self.stamp:
            with gzip.open(file, 'rt', encoding='utf-8') as stream:
                self.cache = json.load(stream)
            self.stamp = stamp
        return self.cache

    def progress(self):
        if self.path is None:
            return self.presentation()['progress']
        compact = self.path / 'dashboard.json'
        if compact.exists():
            stamp = compact.stat().st_mtime_ns
            if stamp != self.stamp:
                self.cache, self.stamp = read(compact), stamp
            return self.cache
        status = read(self.path / 'status.json', {})
        events = read(self.path / 'dashboard_events.json', {'timeline': []})
        index = read(self.path / 'test_predictions.json', {'cases': {}})
        
        scored = read(self.path / 'scored_cases.json', [])
        labels = {r['case']: r['gold'] for r in scored}
        cases = []
        protocol = read(self.path / 'protocol.json', {})
        for case, arms in index['cases'].items():
            partition = next((k for k, v in protocol.get('partitions', {}).items() if case in v), 'pending')
            cases.append({'case': case, 'partition': partition, 'arms': {a: {
                **row, 'correct': row['prediction'] == labels[case] if case in labels else None}
                for a, row in arms.items()}})
        return {**status, 'run_id': self.path.name, 'timeline': events['timeline'], 'cases': cases,
                'rules': read(self.path / 'live.json', {'rules': []})['rules'],
                'summary': read(self.path / 'summary.json', {}), 'source': 'Live read-only run; accuracy shown only after scoring'}

    def case(self, name):
        if not re.fullmatch(r'case_\d{4}', name):
            raise ValueError('Invalid case')
        if self.path is None:
            try:
                result = self.presentation()['cases'][name]
                extra = ROOT / 'web/diagnostics.json.gz'
                if extra.exists():
                    stamp = extra.stat().st_mtime_ns
                    if stamp != self.detail_stamp:
                        with gzip.open(extra, 'rt', encoding='utf-8') as stream:
                            self.detail_cache = json.load(stream)
                        self.detail_stamp = stamp
                    detail = self.detail_cache['cases'].get(name)
                    if detail:
                        result = {arm: dict(trace, diagnostic=detail) for arm, trace in result.items()}
                return result
            except KeyError:
                raise FileNotFoundError(name) from None
        bundle = read(self.path / 'cases' / (name + '.json'))
        if bundle is not None:
            return bundle
        rows = {}
        for arm in self.arms():
            trace = read(self.path / ('active_full_traces' if (self.path / 'active_summary.json').exists() else 'full_traces') / name / (arm + '.json'))
            if trace:
                rows[arm] = {k: trace.get(k) for k in ('prediction', 'healthy', 'tool_calls', 'wall_sec')}
                rows[arm]['steps'] = [{k: s.get(k) for k in ('tool', 'arguments', 'elapsed_sec', 'error')} for s in trace['steps']]
                if (self.path / 'active_summary.json').exists():
                    from publish_results import display_tree
                    rows[arm]['search_tree'] = display_tree(trace)
        if not rows:
            raise FileNotFoundError(name)
        return rows


def handler(store):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            target = urlparse(self.path)
            try:
                if target.path == '/api/progress':
                    return self.send_json(store.progress())
                if target.path == '/api/case':
                    return self.send_json(store.case(parse_qs(target.query).get('id', [''])[0]))
                if target.path == '/docs/methodology.html':
                    self.send_response(302)
                    self.send_header('Location', '/README.html')
                    self.end_headers()
                    return
                if target.path in ('/', '/index.html') and store.path is None and (ROOT / 'index.html').exists():
                    return self.reply((ROOT / 'index.html').read_bytes(), 'text/html')
                if target.path.startswith('/web/'):
                    relative = target.path[len('/web/'):]
                    assets = {'styles.css', 'research.css', 'preferences.css', 'integrated.css',
                        'app.js', 'online.js', 'research.js', 'preferences.js', 'integrated.js', 'archive.js',
                        'methodology.css', 'methodology.js', 'cursor.css', 'lucide.min.js', 'archive/progress.js'}
                    if relative not in assets and not re.fullmatch(r'archive/cases/case_\d{4}\.js', relative):
                        return self.send_error(404)
                    file = ROOT / 'web' / relative
                    return self.reply(file.read_bytes(), 'text/css' if file.suffix == '.css' else 'text/javascript')
                allowed = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js',
                    '/online.js': 'online.js', '/research.js': 'research.js', '/research.css': 'research.css',
                    '/preferences.js': 'preferences.js', '/preferences.css': 'preferences.css',
                    '/archive.js': 'archive.js', '/integrated.js': 'integrated.js', '/integrated.css': 'integrated.css',
                    '/cursor.css': 'cursor.css',
                    '/CITATIONS.bib': 'CITATIONS.bib',
                    '/README.html': 'README.html', '/README.md': 'README.md',
                    '/docs/methodology.md': 'methodology.md', '/docs/reproduce.md': 'reproduce.md',
                    '/docs/case_walkthroughs.json': 'case_walkthroughs.json',
                    '/web/methodology.css': 'methodology.css', '/web/methodology.js': 'methodology.js',
                    '/web/lucide.min.js': 'lucide.min.js',
                    '/styles.css': 'styles.css', '/lucide.min.js': 'lucide.min.js', '/workflow.png': 'workflow.png'}
                if target.path not in allowed:
                    return self.send_error(404)
                directory = 'docs' if target.path.startswith('/docs/') else 'web'
                file = ROOT / allowed[target.path] if target.path in ('/workflow.png', '/README.html', '/README.md', '/CITATIONS.bib') else ROOT / directory / allowed[target.path]
                body = file.read_bytes()
                mime = {'html': 'text/html', 'css': 'text/css', 'js': 'text/javascript', 'png': 'image/png',
                        'md': 'text/plain', 'bib': 'text/plain', 'json': 'application/json'}[file.suffix[1:]]
                self.reply(body, mime)
            except (ValueError, FileNotFoundError):
                self.send_error(404)

        def reply(self, body, mime):
            self.send_response(200)
            self.send_header('Content-Type', mime + ('; charset=utf-8' if mime != 'image/png' else ''))
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, data):
            self.reply(json.dumps(data, ensure_ascii=False).encode(), 'application/json')

        def log_message(self, *_):
            pass
    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path)
    parser.add_argument('--host', choices=['127.0.0.1'], default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8777)
    args = parser.parse_args()
    print(f'Read-only research console http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), handler(Store(args.run))).serve_forever()
