"""NDST Dive Logging App: logs dives and transects during field operations.

See WINDOWS_APP_PLAN.md for the design and the output contract.
"""

from pathlib import Path

__version__ = '1.0.0'

# The folder holding run.py, DiveLogging.bat and config-variables.csv
APP_ROOT = Path(__file__).resolve().parent.parent
