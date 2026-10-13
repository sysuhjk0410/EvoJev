#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${JEV_PYTHON:-python}"
RUN="${1:-full754}"
"$PY" - "$ROOT/runs/$RUN" <<'PY'
import json, sys, time
from pathlib import Path
from urllib.request import urlopen
run = Path(sys.argv[1]); config = json.loads((run / 'config.json').read_text())
deadline = time.monotonic() + 1200
while True:
    try:
        ready = json.loads((run / 'worker_health.json').read_text())['ready']
        with urlopen(config['advisor_url'] + '/health', timeout=3) as response:
            healthy = response.status == 200
        if ready and healthy:
            break
    except (OSError, ValueError, KeyError):
        pass
    if time.monotonic() > deadline:
        raise TimeoutError('Start the worker and advisor in separate tmux sessions first')
    time.sleep(3)
PY
if ! [ -f "$ROOT/runs/$RUN/state.json" ]; then
  "$PY" "$ROOT/scripts/jev.py" prime --run "$RUN"
else
  "$PY" - "$ROOT/runs/$RUN/state.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['status'] == 'actual_gate_passed', 'Resume train explicitly; do not restart prime'
PY
fi
"$PY" "$ROOT/scripts/jev.py" stop-advisor --run "$RUN"
"$PY" "$ROOT/scripts/jev.py" test --run "$RUN"
"$PY" "$ROOT/scripts/jev.py" score --run "$RUN"
"$PY" "$ROOT/scripts/jev.py" report --run "$RUN"
touch "$ROOT/runs/$RUN/STOP_WORKER"
