"""Set up and start the Dive Logging App.

Uses only the standard library, because it runs before the app's libraries are
installed. DiveLogging.bat runs it twice:

  python run.py --setup    create or update the virtual environment (in a console,
                           so the user sees pip's progress)
  pythonw run.py [args]    start the app from the virtual environment

The virtual environment is rebuilt only when requirements.txt or the Python
installation changes, so normal starts never need the network. A failed rebuild
leaves the existing environment untouched. See WINDOWS_APP_PLAN.md, section 5.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from divelog.settings import home_dir  # standard library only

APP_ROOT = Path(__file__).resolve().parent
REQUIREMENTS = APP_ROOT / 'requirements.txt'
# Optional: wheels shipped with the app, for machines that can't reach PyPI
WHEELS = APP_ROOT / 'wheels'
MIN_PYTHON = (3, 10)
MARKER = 'divelog-env.json'

# setup() exit codes
OK, KEPT_OLD, FAILED = 0, 1, 2


def venv_python(venv, windowed=False):
    if sys.platform == 'win32':
        return venv / 'Scripts' / ('pythonw.exe' if windowed else 'python.exe')
    return venv / 'bin' / 'python'


def wanted():
    """What the environment must have been built from."""
    return {'requirements': hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest(),
            'python': '%d.%d' % sys.version_info[:2],
            'base': str(Path(sys.executable).resolve())}


def built_from(venv):
    try:
        return json.loads((venv / MARKER).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def works(venv):
    """Whether the environment can run the app."""
    py = venv_python(venv)
    return py.exists() and subprocess.run([str(py), '-c', 'import PySide6.QtWidgets, truststore'],
                                          capture_output=True).returncode == 0


def install(py):
    command = [str(py), '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input',
               '--require-hashes', '-r', str(REQUIREMENTS)]
    if WHEELS.is_dir():
        if subprocess.run(command + ['--no-index', '--find-links', str(WHEELS)]).returncode == 0:
            return
        print('\nThe bundled libraries could not be installed; trying PyPI.\n')
    subprocess.run(command, check=True)


def setup():
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    venv, new, old = home / 'venv', home / 'venv.new', home / 'venv.old'
    if built_from(venv) == wanted() and venv_python(venv).exists():
        return OK

    print('Setting up the Dive Logging App. This happens on first use, after an update and after\n'
          'Python is upgraded, and needs network access. It can take a few minutes.\n', flush=True)
    shutil.rmtree(new, ignore_errors=True)
    try:
        subprocess.run([sys.executable, '-m', 'venv', str(new)], check=True)
        install(venv_python(new))
        if not works(new):
            raise RuntimeError('the installed libraries could not be loaded')
        (new / MARKER).write_text(json.dumps(wanted(), indent=2), encoding='utf-8')
        # Swap in the new environment
        shutil.rmtree(old, ignore_errors=True)
        if venv.exists():
            venv.rename(old)
        try:
            new.rename(venv)
        except OSError:
            if old.exists():
                old.rename(venv)
            raise
        shutil.rmtree(old, ignore_errors=True)
        print('\nSetup finished.')
        return OK
    except (subprocess.CalledProcessError, OSError, RuntimeError) as e:
        shutil.rmtree(new, ignore_errors=True)
        reason = 'the libraries could not be installed (see above)' if isinstance(e, subprocess.CalledProcessError) else e
        print(f'\nSetup failed: {reason}.')
        if works(venv):
            print('The app will start with the libraries already installed. Setup will try again next time.')
            return KEPT_OLD
        print('The first start needs network access to PyPI (pypi.org and files.pythonhosted.org).\n'
              'Connect to a network that allows it, or ask for a copy of the app that includes its\n'
              "libraries (a 'wheels' folder), then start the app again.")
        return FAILED


def message(text):
    """Show an error without any extra libraries: a Windows message box, or stderr."""
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, 'Dive Logging', 0x10)
    else:
        print(text, file=sys.stderr)


def launch(args):
    py = venv_python(home_dir() / 'venv', windowed=True)
    if not py.exists():
        message('The Dive Logging App has not been set up yet. Start it with DiveLogging.bat.')
        return 1
    # -m divelog finds the app because the working directory is on the module path
    subprocess.Popen([str(py), '-m', 'divelog', *args], cwd=APP_ROOT)
    return 0


def main():
    if sys.version_info < MIN_PYTHON:
        message('The Dive Logging App needs Python %d.%d or later.' % MIN_PYTHON)
        return FAILED
    if sys.argv[1:2] == ['--setup']:
        return setup()
    return launch(sys.argv[1:])


if __name__ == '__main__':
    sys.exit(main())
