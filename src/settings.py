
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def load(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text())
    root = Path(data.get('project_root', PROJECT)).resolve()
    for name in ('benchmark_root', 'jev_checkpoint', 'jev_backbone', 'advisor_model'):
        value = Path(data[name]).expanduser()
        data[name] = str(value.resolve() if value.is_absolute() else (root / value).resolve())
    data['project_root'] = str(root)
    data['deny_paths'] = [str((root / p).resolve()) for p in data.get('deny_paths', [])]
    if data.get('mem_available_min_gib', 50) < 50:
        raise ValueError('Safety floor must be at least 50 GiB')
    return data
