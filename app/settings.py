from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, validator


class AppSettings(BaseModel):
    serial_device: str = "/dev/serial0"
    baud_rate: int = 1_000_000
    data_bits: int = 8
    parity: str = "N"
    stop_bits: int = 1
    newline: str = "\n"
    console_history: int = 500
    metrics_history: int = 300  # seconds worth of samples kept on the frontend
    # Map of console axis label (lowercased) -> logical axis id ("r","z","x1","x2")
    axis_map: Dict[str, str] = {
        "r": "r",
        "z": "z",
        "x1": "x1",
        "x2": "x2",
        # Friendly labels for new axis naming
        "x": "x1",
        "p": "x2",
    }

    @validator("data_bits")
    def _validate_data_bits(cls, value: int) -> int:
        if value not in (5, 6, 7, 8):
            raise ValueError("data_bits must be 5, 6, 7, or 8")
        return value

    @validator("parity")
    def _validate_parity(cls, value: str) -> str:
        value = value.upper()
        if value not in ("N", "E", "O"):
            raise ValueError("parity must be one of N, E, O")
        return value

    @validator("stop_bits")
    def _validate_stop_bits(cls, value: int) -> int:
        if value not in (1, 2):
            raise ValueError("stop_bits must be 1 or 2")
        return value

    @validator("newline")
    def _validate_newline(cls, value: str) -> str:
        if value not in ("\n", "\r\n"):
            raise ValueError("newline must be either '\\n' or '\\r\\n'")
        return value

    @validator("console_history")
    def _validate_console_history(cls, value: int) -> int:
        if value < 50:
            raise ValueError("console_history must be at least 50 lines")
        return value

    @validator("metrics_history")
    def _validate_metrics_history(cls, value: int) -> int:
        if value < 60:
            raise ValueError("metrics_history must be at least 60 seconds")
        return value


class SettingsManager:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._settings = self._load()

    def _load(self) -> AppSettings:
        # Load from file if present, otherwise create defaults on disk
        if self._path.exists():
            with self._path.open("r", encoding="utf-8") as handle:
                data: Dict[str, Any] = json.load(handle)
            loaded = AppSettings(**data)
        else:
            loaded = AppSettings()
            self._persist(loaded)

        # Apply environment overrides (useful when running under systemd with EnvironmentFile or .env)
        overrides: Dict[str, Any] = {}
        env_map = {
            "SERIAL_DEVICE": ("serial_device", str),
            "BAUD_RATE": ("baud_rate", int),
            "DATA_BITS": ("data_bits", int),
            "PARITY": ("parity", str),
            "STOP_BITS": ("stop_bits", int),
            "NEWLINE": ("newline", str),
            "CONSOLE_HISTORY": ("console_history", int),
            "METRICS_HISTORY": ("metrics_history", int),
        }
        for env_key, (field, caster) in env_map.items():
            raw = os.getenv(env_key)
            if raw is None:
                continue
            # Allow NEWLINE to be provided as \n or \r\n in a .env file
            if field == "newline":
                if raw == "\\n":
                    raw = "\n"
                elif raw == "\\r\\n":
                    raw = "\r\n"
            try:
                overrides[field] = caster(raw)
            except Exception:
                # Ignore invalid overrides; pydantic will validate on merge
                continue

        if overrides:
            return loaded.copy(update=overrides)
        return loaded

    def get(self) -> AppSettings:
        with self._lock:
            return AppSettings(**self._settings.dict())

    def update(self, new_data: Dict[str, Any]) -> AppSettings:
        with self._lock:
            merged = self._settings.copy(update=new_data)
            self._persist(merged)
            self._settings = merged
            return AppSettings(**merged.dict())

    def _persist(self, settings: AppSettings) -> None:
        tmp_path = self._path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(settings.dict(), handle, indent=2)
            handle.flush()
        tmp_path.replace(self._path)


__all__ = ["AppSettings", "SettingsManager"]
