#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def available_gib():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) / 1024**2
    raise RuntimeError('MemAvailable unavailable')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[0] == '--' else args.command
    if available_gib() < 50:
        raise RuntimeError('Refusing launch below 50 GiB MemAvailable')
    child = subprocess.Popen(command, start_new_session=True)
    stop = [False]
    def stopping(*_):
        stop[0] = True
    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    while child.poll() is None:
        available = available_gib()
        args.record.write_text(json.dumps({'pid': child.pid, 'available_gib': available,
                                          'updated_at': time.time(), 'threshold_gib': 50}))
        if available < 50 or stop[0]:
            print(f'Guard stopping owned group {child.pid}: MemAvailable={available:.2f} GiB', flush=True)
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            raise SystemExit(75 if available < 50 else 143)
        time.sleep(2)
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    raise SystemExit(child.returncode)


if __name__ == '__main__':
    main()
