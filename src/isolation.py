
import json
import os
from pathlib import Path
import sys


def install(run, report):
    run = run.resolve()
    config = json.loads((run / 'config.json').read_text())
    root = Path(config['project_root'])
    forbidden = [run / 'sealed_evaluation', run / 'feedback_store', run / 'advisor', Path(config['benchmark_root']),
                 root / 'web', root / 'docs', root / 'README.html', root / 'index.html',
                 run / 'online/feedback', run / 'online/proposals']
    forbidden.extend(Path(p).resolve() for p in config.get('deny_paths', []))
    experiments = root / 'runs'
    report.parent.mkdir(parents=True, exist_ok=True)
    log = report.open('a')
    reads, denied = set(), []

    def emit(value):
        log.write(json.dumps(value) + '\n')
        log.flush()

    def hook(event, args):
        if event not in {'open', 'os.listdir', 'os.scandir', 'socket.connect'}:
            return
        if event == 'socket.connect':
            address = args[1]
            if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1', 'localhost'}:
                emit({'event': event, 'denied': str(address)})
                raise PermissionError('Diagnosis network access must be loopback only')
            return
        value = args[0]
        if not isinstance(value, (str, bytes, os.PathLike)):
            return
        path = Path(os.path.realpath(os.fsdecode(value)))
        public = (run / 'public').resolve()
        if event == 'open' and (path == public or public in path.parents):
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in ('w', 'a', '+', 'x'))) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                denied.append(str(path))
                emit({'event': event, 'denied': str(path), 'reason': 'Public observations are read-only'})
                raise PermissionError('Public observations are read-only')
        blocked = any(path == target or target in path.parents for target in forbidden)
        blocked |= (path == experiments or experiments in path.parents) and not (path == run or run in path.parents)
        if blocked:
            denied.append(str(path))
            emit({'event': event, 'denied': str(path)})
            raise PermissionError('Historical feedback, final labels and other experiments are inaccessible')
        if event == 'open' and str(path) not in reads:
            reads.add(str(path))
            emit({'event': event, 'path': str(path), 'mode': str(args[1])})

    sys.addaudithook(hook)
    return {'reads': reads, 'denied': denied, 'log': log}
