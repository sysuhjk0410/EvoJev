#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from settings import load


def location(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Use a simple run name')
    return ROOT / 'runs' / name


def check_gpus(gpus):
    used = subprocess.run(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid', '--format=csv,noheader'], capture_output=True, text=True, check=True).stdout
    inventory = subprocess.run(['nvidia-smi', '--query-gpu=index,uuid', '--format=csv,noheader'], capture_output=True, text=True, check=True).stdout
    mapping = {line.split(',')[0].strip(): line.split(',')[1].strip() for line in inventory.splitlines()}
    for gpu in gpus.split(','):
        if mapping[gpu] in used:
            raise RuntimeError(f'GPU {gpu} is occupied; configure a free GPU, never kill its processes')


def stop_advisor(run):
    config = load(run / 'config.json')
    record = json.loads((run / 'advisor_resources.json').read_text())
    pid = record['pid']
    proc = Path('/proc') / str(pid)
    if proc.exists():
        command = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
        environment = (proc / 'environ').read_bytes().split(b'\0')
        if not ('vllm.entrypoints.openai.api_server' in command and
                ('--served-model-name ' + config['advisor_name']) in command and
                ('HF_HOME=' + str(run / 'cache/hf')).encode() in environment and os.getpgid(pid) == pid):
            raise RuntimeError('PID ownership mismatch: refusing to stop this process')
        os.killpg(pid, signal.SIGTERM)
        import time
        for _ in range(120):
            if not proc.exists():
                break
            time.sleep(1)
        else:
            raise RuntimeError('Advisor did not exit; final evaluation is blocked')
    from grounded import write
    online = (run / 'online_plan.json').exists()
    write(run / 'advisor_stopped.json', {'pid': pid, 'stopped_before_frozen_test': not online,
                                        'stopped_after_online_completion': online})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'doctor', 'worker', 'advisor', 'prime', 'train', 'test', 'score', 'report', 'stop-advisor', 'diagnose', 'active-collect', 'active-learn', 'active-evolve', 'active-gate'])
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/local.example.json')
    parser.add_argument('--run', default='full754')
    parser.add_argument('--case', default='case_0069')
    parser.add_argument('--single-case', action='store_true')
    parser.add_argument('--harness', type=Path)
    parser.add_argument('--advisor-max-model-len', type=int, default=16384)
    parser.add_argument('--advisor-gpu-memory-utilization', type=float, default=0.80)
    parser.add_argument('--advisor-max-num-seqs', type=int, default=2)
    args = parser.parse_args()
    run = location(args.run)
    if args.command == 'prepare':
        from prepare import prepare
        print(json.dumps(prepare(args.config, run, args.case if args.single_case else None)))
        return
    config = load(run / 'config.json' if (run / 'config.json').exists() else args.config)
    if args.command == 'doctor':
        import importlib.metadata
        result = {'config': config, 'exists': {k: Path(config[k]).exists() for k in ('benchmark_root', 'jev_checkpoint', 'jev_backbone', 'advisor_model')}}
        result['versions'] = {k: importlib.metadata.version(k) for k in ('torch', 'transformers', 'PyYAML', 'safetensors')}
        print(json.dumps(result, indent=2))
        return
    if args.command in ('worker', 'advisor'):
        config = load(run / 'config.json')
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='4',
            PYTHONPATH=str(run), HF_HOME=str(run / 'cache/hf'), TORCH_HOME=str(run / 'cache/torch'),
            TMPDIR=str(run / 'tmp'), VLLM_CACHE_ROOT=str(run / 'cache/vllm'),
            TRITON_CACHE_DIR=str(run / 'cache/triton'), CUDA_CACHE_PATH=str(run / 'cache/cuda'))
        python = config.get('python', sys.executable)
        if args.command == 'worker':
            env['CUDA_VISIBLE_DEVICES'] = config['jev_gpus']
            command = [python, str(run / 'worker.py'), '--run', str(run)]
        else:
            env['CUDA_VISIBLE_DEVICES'] = config['advisor_gpus']
            address = urlparse(config['advisor_url'])
            if address.hostname != '127.0.0.1':
                raise ValueError('Advisor must use loopback')
            if args.advisor_max_model_len <= 0 or args.advisor_max_num_seqs <= 0:
                raise ValueError('Advisor context and concurrency must be positive')
            if not 0 < args.advisor_gpu_memory_utilization < 1:
                raise ValueError('Advisor GPU memory utilization must be between zero and one')
            command = [python, '-m', 'vllm.entrypoints.openai.api_server', '--model', config['advisor_model'],
                '--served-model-name', config['advisor_name'], '--host', '127.0.0.1', '--port', str(address.port),
                '--tensor-parallel-size', str(config['advisor_tensor_parallel']), '--max-model-len', str(args.advisor_max_model_len),
                '--gpu-memory-utilization', str(args.advisor_gpu_memory_utilization), '--max-num-seqs', str(args.advisor_max_num_seqs),
                '--enforce-eager', '--safetensors-load-strategy', 'eager']
        from guard_process import available_gib
        if available_gib() < config['mem_available_min_gib']:
            raise RuntimeError('MemAvailable below configured safety floor')
        check_gpus(env['CUDA_VISIBLE_DEVICES'])
        guarded = [python, str(run / 'guard_process.py'), '--record', str(run / (args.command + '_resources.json')), '--'] + command
        os.chdir(run)
        os.execve(python, guarded, env)
    elif args.command == 'stop-advisor':
        stop_advisor(run)
    elif args.command == 'report':
        subprocess.run([config.get('python', sys.executable), str(run / 'report_full.py')], cwd=run, check=True)
    elif args.command == 'diagnose':
        os.environ.update(CUDA_VISIBLE_DEVICES=config['jev_gpus'], OMP_NUM_THREADS='4',
            PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', HF_HOME=str(run / 'cache/hf'),
            TORCH_HOME=str(run / 'cache/torch'), TMPDIR=str(run / 'tmp'),
            TRITON_CACHE_DIR=str(run / 'cache/triton'), CUDA_CACHE_PATH=str(run / 'cache/cuda'))
        check_gpus(config['jev_gpus'])
        from guard_process import available_gib
        if available_gib() < config['mem_available_min_gib']:
            raise RuntimeError('MemAvailable below safety floor')
        from isolation import install
        from grounded import GroundedSearch, write
        install(run, run / 'worker_access.jsonl')
        from cloudops_evolution import JevRanker
        ranker = JevRanker(config, run / 'scores')
        harness = json.loads(args.harness.read_text()) if args.harness else {'version': 0, 'rules': []}
        task = json.loads((run / 'public/cases' / args.case / 'task.json').read_text())
        trace = GroundedSearch(run / 'public/repo', ranker, budget=24).run(run / 'public/cases' / args.case, task, harness)
        write(run / 'diagnosis.json', trace)
        print(json.dumps({'prediction': trace['prediction'], 'healthy': trace['healthy'], 'tool_calls': trace['tool_calls']}))
    else:
        script = 'search_experiment.py' if args.command.startswith('active-') else 'controller.py'
        phase = args.command.removeprefix('active-')
        subprocess.run([config.get('python', sys.executable), str(run / script), '--run', str(run), '--phase', phase], cwd=run, check=True)


if __name__ == '__main__':
    main()
