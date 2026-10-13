import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tokenize

root = Path(__file__).resolve().parents[1]

def archive_text(rel, text):
    expected = 'progress' if str(rel) == 'web/archive/progress.js' else rel.stem
    prefix = 'window.EvoJevArchive.deliver('
    if not text.startswith(prefix) or not text.endswith(');\n'):
        raise ValueError('Invalid static archive wrapper')
    args = json.loads('[' + text[len(prefix):-3] + ']')
    if len(args) != 2 or args[0] != expected or not isinstance(args[1], str):
        raise ValueError('Invalid static archive key')
    decoded = gzip.decompress(base64.b64decode(args[1], validate=True)).decode('utf-8')
    if not isinstance(json.loads(decoded), dict):
        raise ValueError('Invalid static archive payload')
    return decoded

def audit():
    records = []
    violations = []
    paths = []
    documented_case_samples = 0
    for directory, children, files in os.walk(root, followlinks=False):
        children[:] = [p for p in children if p not in ('runs', 'logs', '.staging', '__pycache__', '.git', '.cache') and not p.startswith('.venv')]
        paths.extend(Path(directory) / file for file in files)
    for path in sorted(paths):
        rel = path.relative_to(root)
        if not path.is_file() or any(p in ('runs', 'logs', '.staging', '__pycache__', '.git', '.cache') or p.startswith('.venv') for p in rel.parts) or path.name == 'PACKAGE_MANIFEST.json' or path.name.endswith('.local.json'):
            continue
        body = path.read_bytes()
        if path.suffix in ('.pt', '.pth', '.safetensors', '.parquet', '.bin', '.ckpt', '.gguf', '.onnx'):
            violations.append({'file': str(rel), 'reason': 'Model or benchmark payload'})
        compressed = path.name.endswith('.json.gz')
        if compressed or path.suffix in ('.py', '.md', '.json', '.js', '.sh', '.cjs', '.html', '.css', '.bib', '.txt'):
            text = (gzip.decompress(body) if compressed else body).decode('utf-8')
            if re.fullmatch(r'web/archive/(?:progress|cases/case_\d{4})\.js', str(rel)):
                text = archive_text(rel, text)
            scan_text = text
            if str(rel) == 'docs/case_walkthroughs.json':
                document = json.loads(text)
                cases = document.get('cases', [])
                if (document.get('schema') != 'evojev_module_io_walkthrough_v1' or len(cases) != 3 or
                        len({case['case'] for case in cases}) != 3 or
                        any(set(case['original_public_task']) != {'query', 'namespace'} or
                            any(case['integrity'][key] != 0 for key in ('new_tool_calls', 'new_JEV_calls', 'new_advisor_calls'))
                            for case in cases)):
                    violations.append({'file': str(rel), 'reason': 'Invalid requested three-case documentation'})
                else:
                    documented_case_samples = 3
                    benchmark_host_path = '/' + 'mnt/data'
                    scan_text = re.sub(re.escape(benchmark_host_path) + r'(?![\w/.-])', 'BENCHMARK_HOST_PATH', scan_text)
                    scan_text = re.sub(r'(?<=://)(?:10\.|172\.(?:1[6-9]|2\d|3[01])\.|192\.168\.)\d[\d.]*',
                                       'BENCHMARK_CLUSTER_ADDRESS', scan_text)
            if re.search(r'sk-[A-Za-z0-9_-]{18,}|BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY', text):
                violations.append({'file': str(rel), 'reason': 'Credential-like content'})
            if re.search(r'/(?:data/dds-data|home/(?!\{)[\w.-]+|Users/(?!\{)[\w.-]+|root|mnt)(?:/|\b)', scan_text):
                violations.append({'file': str(rel), 'reason': 'Machine-specific absolute path'})
            if re.search(r'(?:@|://)(?:10\.|172\.(?:1[6-9]|2\d|3[01])\.|192\.168\.)\d[\d.]*|33\.33\.33\.12[13]|222\.200\.180\.22', scan_text):
                violations.append({'file': str(rel), 'reason': 'Machine-specific address'})
            if path.suffix == '.py':
                if any(t.type == tokenize.COMMENT and not t.string.startswith('#!') for t in tokenize.generate_tokens(io.StringIO(text).readline)):
                    violations.append({'file': str(rel), 'reason': 'Python comment'})
        records.append({'file': str(rel), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
    if violations:
        raise ValueError(json.dumps(violations))
    result = {'schema': 1, 'files': records, 'total_bytes': sum(r['bytes'] for r in records),
        'models_bundled': False, 'full_benchmark_bundled': False,
        'benchmark_payload_bundled': bool(documented_case_samples), 'documented_case_samples': documented_case_samples,
        'machine_specific_absolute_paths': 0, 'credential_matches': 0}
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    result = audit()
    if args.write:
        (root / 'PACKAGE_MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'files': len(result['files']), 'bytes': result['total_bytes'], 'audit': 'passed'}))
