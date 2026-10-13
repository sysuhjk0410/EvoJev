import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def script_payload(key, value):
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    encoded = base64.b64encode(gzip.compress(body, mtime=0)).decode()
    return 'window.EvoJevArchive.deliver(' + json.dumps(key) + ',' + json.dumps(encoded) + ');\n'


def build(root=ROOT):
    root = Path(root)
    presentation = json.loads(gzip.decompress((root / 'web/presentation.json.gz').read_bytes()))
    diagnostics = json.loads(gzip.decompress((root / 'web/diagnostics.json.gz').read_bytes()))
    progress = presentation['progress']
    ids = [row['case'] for row in progress['cases']]
    if len(ids) != len(set(ids)) or set(ids) != set(presentation['cases']) or set(ids) != set(diagnostics['cases']):
        raise ValueError('Static archive must preserve every published unique case')
    archive = root / 'web/archive'
    (archive / 'cases').mkdir(parents=True, exist_ok=True)
    (archive / 'progress.js').write_text(script_payload('progress', progress))
    for case in ids:
        if not re.fullmatch(r'case_\d{4}', case):
            raise ValueError('Invalid case')
        traces = {arm: dict(trace, diagnostic=diagnostics['cases'][case]) for arm, trace in presentation['cases'][case].items()}
        (archive / 'cases' / (case + '.js')).write_text(script_payload(case, traces))
    stale = [path for path in (archive / 'cases').glob('*.js') if path.stem not in ids]
    if stale:
        raise ValueError('Stale static cases must be inspected before publication')
    source = (root / 'web/index.html').read_text()
    source = source.replace('<html lang="en">', '<html lang="en" data-archive="static">')
    assets = {path.name for path in (root / 'web').iterdir() if path.suffix in ('.css', '.js')}
    source = re.sub(r'(src|href)="/([^"?]+)"', lambda match: match[1] + '="' + ('web/' if match[2] in assets else '') + match[2] + '"', source)
    source = source.replace('href="/"', 'href="index.html"')
    (root / 'index.html').write_text(source)
    (root / '.nojekyll').write_text('')
    result = {'schema': 1, 'cases': len(ids), 'source_sha256': {
        name: hashlib.sha256((root / 'web' / name).read_bytes()).hexdigest()
        for name in ('presentation.json.gz', 'diagnostics.json.gz')
    }, 'new_inference_calls': 0}
    (archive / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    argparse.ArgumentParser().parse_args()
    print(json.dumps(build()))
