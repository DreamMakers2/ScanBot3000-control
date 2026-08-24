from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

import serial

from .settings import AppSettings

LOGGER = logging.getLogger(__name__)

_BYTESIZE_MAP = {
    5: serial.FIVEBITS,
    6: serial.SIXBITS,
    7: serial.SEVENBITS,
    8: serial.EIGHTBITS,
}
_STOPBITS_MAP = {
    1: serial.STOPBITS_ONE,
    2: serial.STOPBITS_TWO,
}
_PARITY_MAP = {
    "N": serial.PARITY_NONE,
    "E": serial.PARITY_EVEN,
    "O": serial.PARITY_ODD,
}


class UARTNotReadyError(RuntimeError):
    pass


class UARTManager:
    def __init__(self, loop: asyncio.AbstractEventLoop, line_queue: "asyncio.Queue[str]", settings: AppSettings) -> None:
        self._loop = loop
        self._line_queue = line_queue
        self._settings = settings
        self._serial: Optional[serial.Serial] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._write_lock = threading.Lock()
        self._buffer = ""
        self._reconfigure = threading.Event()

    def start(self) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="uart-reader", daemon=True)
        self._reader_thread.start()
        LOGGER.info("UART reader thread started")

    def stop(self) -> None:
        self._stop_event.set()
        self._reconfigure.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)
        self._close_serial()
        LOGGER.info("UART reader thread stopped")

    def update_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self._reconfigure.set()
        LOGGER.info("UART configuration update requested")

    def is_ready(self) -> bool:
        serial_obj = self._serial
        return bool(serial_obj and serial_obj.is_open)

    async def send_command(self, command: str) -> None:
        command = command.strip()
        if not command:
            return
        newline = self._settings.newline
        payload = (command + newline).encode("utf-8")

        def _write() -> None:
            with self._write_lock:
                if not self._serial or not self._serial.is_open:
                    raise UARTNotReadyError("UART device is not ready")
                self._serial.write(payload)
                self._serial.flush()

        await asyncio.get_running_loop().run_in_executor(None, _write)

    def _open_serial(self) -> None:
        settings = self._settings
        try:
            LOGGER.info("Opening serial port %s @ %d", settings.serial_device, settings.baud_rate)
            serial_obj = serial.Serial(
                port=settings.serial_device,
                baudrate=settings.baud_rate,
                bytesize=_BYTESIZE_MAP[settings.data_bits],
                parity=_PARITY_MAP[settings.parity],
                stopbits=_STOPBITS_MAP[settings.stop_bits],
                timeout=0,
                write_timeout=0,
            )
            serial_obj.reset_input_buffer()
            serial_obj.reset_output_buffer()
            self._serial = serial_obj
            LOGGER.info("Serial port ready")
        except serial.SerialException as exc:
            LOGGER.error("Failed to open serial port: %s", exc)
            self._serial = None
            raise

    def _close_serial(self) -> None:
        with self._write_lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.close()
                except serial.SerialException:
                    pass
        self._serial = None

    def _reader_loop(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            if self._reconfigure.is_set():
                self._close_serial()
                self._reconfigure.clear()

            if not self._serial or not self._serial.is_open:
                try:
                    self._open_serial()
                except serial.SerialException:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 5.0)
                    continue
                backoff = 1.0

            assert self._serial is not None
            try:
                data = self._serial.read(self._serial.in_waiting or 1024)
            except serial.SerialException as exc:
                LOGGER.error("Serial read failed: %s", exc)
                self._close_serial()
                time.sleep(0.5)
                continue

            if data:
                self._handle_data(data)
                continue

            time.sleep(0.001)

    def _handle_data(self, data: bytes) -> None:
        try:
            text = data.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
        self._buffer += text
        newline = "\n"
        while True:
            index = self._buffer.find(newline)
            if index == -1:
                break
            line = self._buffer[:index]
            self._buffer = self._buffer[index + len(newline) :]
            if line.endswith("\r"):
                line = line[:-1]
            asyncio.run_coroutine_threadsafe(self._line_queue.put(line), self._loop)


__all__ = ["UARTManager", "UARTNotReadyError"]
