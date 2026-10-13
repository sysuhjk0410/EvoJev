#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from guard_process import available_gib
from settings import load
from grounded import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    from jev import location, stop_advisor
    run = location(args.run)
    config = load(run / 'config.json')
    start = time.monotonic()
    while True:
        if available_gib() < 50:
            raise RuntimeError('MemAvailable below 50 GiB safety floor')
        ready = (run / 'worker_health.json').exists() and json.loads((run / 'worker_health.json').read_text()).get('ready')
        advisor_ready = False
        try:
            with urlopen(config['advisor_url'].rstrip('/') + '/v1/models', timeout=5) as response:
                advisor_ready = any(row['id'] == config['advisor_name'] for row in json.load(response)['data'])
        except (URLError, TimeoutError):
            pass
        if ready and advisor_ready:
            break
        if time.monotonic() - start > 1800:
            raise TimeoutError('Owned worker/advisor startup did not complete')
        time.sleep(5)
    subprocess.run([sys.executable, str(run / 'online_controller.py'), '--run', str(run)], cwd=run,
                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), check=True)
    if json.loads((run / 'status.json').read_text()).get('status') != 'complete':
        raise ValueError('Single-pass run did not reach audited completion')
    stop_advisor(run)
    write(run / 'STOP_WORKER', {'reason': 'Audited online experiment complete'})
    subprocess.run([sys.executable, str(ROOT / 'scripts/publish_online.py'), '--run', str(run)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
