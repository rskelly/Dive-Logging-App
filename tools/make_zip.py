"""Build the zip that users extract and run: dist/DiveLogging-<version>.zip

    python tools/make_zip.py            # libraries are installed from PyPI on first start
    python tools/make_zip.py --wheels   # include the Windows libraries, for machines
                                        # that can't reach PyPI

Runs on any OS: nothing is compiled.
"""

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from divelog import __version__  # noqa: E402

FILES = ['DiveLogging.bat', 'run.py', 'requirements.txt', 'config-variables.csv', 'README-desktop.txt']


def download_wheels(target):
    """The Windows wheels pinned in requirements.txt, checked against its hashes."""
    subprocess.run([sys.executable, '-m', 'pip', 'download', '--disable-pip-version-check', '--quiet',
                    '--require-hashes', '--no-deps', '--only-binary=:all:',
                    '--platform', 'win_amd64', '--python-version', '3.10', '--implementation', 'cp',
                    '--abi', 'abi3', '--abi', 'none',
                    '-r', str(ROOT / 'requirements.txt'), '-d', str(target)], check=True)
    return sorted(target.glob('*.whl'))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--wheels', action='store_true', help='include the Windows libraries')
    parser.add_argument('--out', type=Path, help='output zip (default: dist/DiveLogging-<version>[-offline].zip)')
    args = parser.parse_args()
    out = args.out or ROOT / 'dist' / f'DiveLogging-{__version__}{"-offline" if args.wheels else ""}.zip'
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        files = [(ROOT / f, f) for f in FILES]
        files += [(p, p.relative_to(ROOT).as_posix()) for p in sorted((ROOT / 'divelog').rglob('*.py'))]
        if args.wheels:
            files += [(w, f'wheels/{w.name}') for w in download_wheels(Path(tmp))]
        for path, name in files:
            # Everything in one folder, so extracting doesn't scatter files
            z.write(path, f'DiveLogging/{name}')
    print(f'{out} ({out.stat().st_size / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
