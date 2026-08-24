from __future__ import annotations

import re
from typing import Any, Dict, Optional

_TOKEN_RE = re.compile(r"([A-Za-z_]+):\s*([^\s]+)")
_NUMERIC_KEYS = {
    "ts",
    "ang",
    "dist",
    "temp",
    "lim",
    "drv",
    "cal",
    "flt",
    "rem",
    "volt",
    "amps",
    "rpm",
    "vel",
    "spd",
    "sps",
    "dps",
}


def parse_metrics(line: str) -> Optional[Dict[str, Any]]:
    """Extract numeric metrics from a console line.

    The Teensy console emits status lines with key:value pairs. This helper extracts
    the values for a known set of keys and converts them to floats when possible.
    """

    matches = _TOKEN_RE.findall(line)
    if not matches:
        return None

    metrics: Dict[str, Any] = {}
    for key, raw_value in matches:
        key_lower = key.lower()
        if key_lower not in _NUMERIC_KEYS:
            continue

        cleaned = raw_value.rstrip(",;")
        if cleaned.endswith("s") and key_lower in {"rem", "ts"}:
            cleaned = cleaned[:-1]
        if cleaned.startswith("0x"):
            try:
                metrics[key_lower] = int(cleaned, 16)
            except ValueError:
                continue
            continue

        try:
            if cleaned.startswith("-0x"):
                metrics[key_lower] = -int(cleaned[3:], 16)
                continue
            if cleaned.isdigit() or (cleaned.startswith("-") and cleaned[1:].isdigit()):
                metrics[key_lower] = int(cleaned)
            else:
                metrics[key_lower] = float(cleaned)
        except ValueError:
            continue

    return metrics or None


__all__ = ["parse_metrics"]
