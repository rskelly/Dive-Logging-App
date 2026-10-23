"""Value formats stored in the log: times, configuration strings and ID lists."""

import re
from datetime import datetime, timezone

# ISO 8601 UTC, e.g. 2026-10-23T19:46:23Z
TIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def now_utc():
    """The current time, formatted for the log."""
    return datetime.now(timezone.utc).strftime(TIME_FORMAT)


def parse_time(text):
    """Parse a logged time. Returns an aware datetime, or None."""
    try:
        return datetime.strptime((text or '').strip(), TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def duration(start, end, unit_seconds=60):
    """The time from start to end (log strings) in minutes (or another unit), or None."""
    start, end = parse_time(start), parse_time(end)
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / unit_seconds


def format_number(value):
    """Format a configuration value: integers without a decimal point."""
    value = float(value)
    return str(int(value)) if value.is_integer() else repr(value)


# A configuration string is {'variable':value, ...}, e.g. {'pan':10, 'tilt':-5.5}
_PAIR = re.compile(r"'([^']*)'\s*:\s*([^,}]*)")


def parse_config(text):
    """Split a configuration string into (variable, value) pairs. Values stay strings."""
    return [(name, value.strip()) for name, value in _PAIR.findall(text or '')]


def build_config(pairs):
    """Join (variable, value) pairs into a configuration string."""
    return '{' + ', '.join(f"'{name}':{value}" for name, value in pairs) + '}'


def join_ids(ids):
    """Join IDs (pilots, instrument configs) with ';' as the log stores them."""
    return ';'.join(str(i) for i in ids)


def split_ids(text):
    """Split a ';'-separated list, dropping empty items."""
    return [i for i in (text or '').split(';') if i]
