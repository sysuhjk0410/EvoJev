import argparse
import fcntl
from pathlib import Path
import traceback

from grounded import write
from search_experiment import collect, learn, gate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    lock = (run / 'search_controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        collect(run)
        learn(run)
        gate(run)
    except Exception as error:
        write(run / 'pipeline_failure.json', {'error': str(error), 'traceback': traceback.format_exc(),
                                             'completed_traces_preserved': True})
        raise


if __name__ == '__main__':
    main()
