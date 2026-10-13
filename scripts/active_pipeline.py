import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from guard_process import available_gib
from grounded import write


def require_memory():
    if available_gib() < 50:
        raise RuntimeError('MemAvailable below 50 GiB')


def stop_worker(run):
    record = run / 'worker_resources.json'
    if not record.exists():
        return
    pid = json.loads(record.read_text())['pid']
    proc = Path('/proc') / str(pid)
    if proc.exists():
        command = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
        if str(run / 'worker.py') not in command:
            raise RuntimeError('Worker ownership mismatch')
        (run / 'STOP_WORKER').touch()
        for _ in range(120):
            if not proc.exists():
                break
            time.sleep(1)
        else:
            raise RuntimeError('Owned worker did not stop')


def start_role(run, role, name):
    require_memory()
    for _ in range(30):
        if subprocess.run(['tmux', 'has-session', '-t', '=' + name], capture_output=True).returncode != 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Refusing to replace an existing tmux session')
    command = shlex.join([sys.executable, '-B', '-u', str(ROOT / 'scripts/jev.py'), role, '--run', run.name])
    command += ' >> ' + shlex.quote(str(run / (role + '.log'))) + ' 2>&1'
    subprocess.run(['tmux', 'new-session', '-d', '-s', name, '-c', str(ROOT), command], check=True)


def wait_worker(run):
    for _ in range(120):
        require_memory()
        file = run / 'worker_health.json'
        if file.exists() and json.loads(file.read_text()).get('ready'):
            return
        time.sleep(2)
    raise TimeoutError('Worker did not become ready')


def phase(run, script, name):
    require_memory()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(run),
                       TMPDIR=str(run / 'tmp'), OMP_NUM_THREADS='4', HF_HOME=str(run / 'cache/hf'))
    subprocess.run([sys.executable, '-B', '-u', str(run / script), '--run', str(run), '--phase', name],
                   env=environment, cwd=run, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--worker-session', default='jev_main_active_worker')
    parser.add_argument('--collector-session', default='jev_main_active_collect')
    args = parser.parse_args()
    if not args.run.replace('_', '').replace('-', '').isalnum():
        raise ValueError('Invalid run name')
    run = ROOT / 'runs' / args.run
    lock = (run / 'active_pipeline.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    advisor_started = False
    try:
        if not (run / 'search_test_predictions.json').exists():
            while True:
                require_memory()
                memory = run / 'historical_memory.json'
                plan = json.loads((run / 'protocol.json').read_text())
                if memory.exists() and set(json.loads(memory.read_text())) == set(plan['historical_pool']):
                    break
                if subprocess.run(['tmux', 'has-session', '-t', '=' + args.collector_session], capture_output=True).returncode != 0:
                    raise RuntimeError('Historical collection stopped before completion')
                time.sleep(10)
            resource = run / 'controller_resources.json'
            if resource.exists():
                pid = json.loads(resource.read_text())['pid']
                for _ in range(30):
                    if not (Path('/proc') / str(pid)).exists():
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError('Historical controller still active')
            stop_worker(run)
            archive = run / 'code_revisions' / str(time.time_ns())
            archive.mkdir(parents=True)
            for source in (ROOT / 'src').glob('*.py'):
                target = run / source.name
                if target.exists():
                    shutil.copyfile(target, archive / source.name)
                shutil.copyfile(source, target)
            (run / 'STOP_WORKER').unlink(missing_ok=True)
            (run / 'worker_health.json').unlink(missing_ok=True)
            start_role(run, 'worker', args.worker_session)
            wait_worker(run)
            phase(run, 'search_experiment.py', 'learn')
            config = json.loads((run / 'config.json').read_text())
            address = urlparse(config['advisor_url'])
            if address.hostname != '127.0.0.1':
                raise ValueError('Advisor must use loopback')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', address.port))
            start_role(run, 'advisor', 'jev_main_active_advisor')
            advisor_started = True
            for _ in range(600):
                require_memory()
                try:
                    with urlopen(config['advisor_url'] + '/v1/models', timeout=2) as response:
                        models = json.load(response)['data']
                    if any(m['id'] == config['advisor_name'] for m in models):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise TimeoutError('Task-owned advisor did not become ready')
            phase(run, 'search_experiment.py', 'evolve')
            subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/jev.py'), 'stop-advisor', '--run', run.name], check=True)
            advisor_started = False
            phase(run, 'search_experiment.py', 'gate')
            outcome = json.loads((run / 'development_summary.json').read_text())
            if not outcome['passed']:
                stop_worker(run)
                return
        else:
            record = run / 'worker_resources.json'
            alive = record.exists() and (Path('/proc') / str(json.loads(record.read_text())['pid'])).exists()
            if not alive:
                (run / 'STOP_WORKER').unlink(missing_ok=True)
                (run / 'worker_health.json').unlink(missing_ok=True)
                start_role(run, 'worker', args.worker_session)
                wait_worker(run)
        phase(run, 'active_full.py', 'predict')
        phase(run, 'active_full.py', 'score')
        stop_worker(run)
    except Exception as error:
        write(run / 'pipeline_failure.json', {'error': str(error), 'completed_traces_preserved': True})
        raise
    finally:
        if advisor_started and (run / 'advisor_resources.json').exists():
            subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/jev.py'), 'stop-advisor', '--run', run.name], check=False)


if __name__ == '__main__':
    main()
