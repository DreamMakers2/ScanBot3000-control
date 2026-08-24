from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class ConsoleBuffer:
    def __init__(self, max_lines: int) -> None:
        self._lines: Deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    def snapshot(self) -> List[str]:
        with self._lock:
            return list(self._lines)


class MetricsBuffer:
    def __init__(self, max_samples: int) -> None:
        self._samples: Deque[Dict[str, Any]] = deque(maxlen=max_samples)
        self._lock = threading.Lock()
        self._latest: Optional[Dict[str, Any]] = None

    def append(self, metrics: Dict[str, Any]) -> None:
        metrics_with_ts = {**metrics, "time": time.time()}
        with self._lock:
            self._latest = metrics_with_ts
            self._samples.append(metrics_with_ts)

    def latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._latest) if self._latest else None

    def history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._samples)


__all__ = ["ConsoleBuffer", "MetricsBuffer"]
