import argparse
import itertools
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
SLITTING_SCRIPT = PROJECT_DIR / 'slitting.py'


def run(command):
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


def main():
    parser = argparse.ArgumentParser(
        description='Run both objectives and all 2/4 leftover-weight vectors.'
    )
    parser.add_argument(
        '--instances',
        nargs='+',
        help='Optional subset of instance folders. The default is all instances.'
    )
    args = parser.parse_args()
    instance_args = ['--instances', *args.instances] if args.instances else []

    run([
        sys.executable,
        str(SLITTING_SCRIPT),
        '--objective',
        'new_coils_value',
        *instance_args,
    ])

    for retail_y, retail_v, rolled_leftover in itertools.product([2, 4], repeat=3):
        run([
            sys.executable,
            str(SLITTING_SCRIPT),
            '--objective',
            'weighted_loss',
            '--retail-y-weight',
            str(retail_y),
            '--retail-v-weight',
            str(retail_v),
            '--rolled-leftover-weight',
            str(rolled_leftover),
            *instance_args,
        ])


if __name__ == '__main__':
    main()
