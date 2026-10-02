"""Create an isolated environment using only the dependency wheels in runtime/."""
from pathlib import Path
import os
import subprocess
import sys
import venv

root = Path(__file__).resolve().parent.parent
if sys.version_info < (3, 10):
    raise SystemExit('Please run this script with Python 3.10 or newer.')
environment = root / '.venv'
python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
if not python.exists():
    venv.EnvBuilder(with_pip=True).create(environment)
subprocess.run([str(python), '-m', 'pip', 'install', '--no-index', '--find-links',
                str(root / 'runtime'), '-r', str(root / 'requirements.txt')], check=True)
print('\nReady. Use this Python interpreter for the commands in README.md:')
print(python)
