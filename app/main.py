from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, model_validator, validator

from .parser import parse_metrics
from .settings import AppSettings, SettingsManager
from .state import ConsoleBuffer, MetricsBuffer
from .uart import UARTManager, UARTNotReadyError
from .ws import WebSocketManager

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.json"
LOCAL_ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$"

app = FastAPI(title="Teensy Console")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=LOCAL_ORIGIN_REGEX,  # allow browsers on typical local networks
    allow_methods=["*"],
    allow_headers=["*"],
)


class CommandRequest(BaseModel):
    command: str


class SettingsUpdate(BaseModel):
    serial_device: str | None = None
    baud_rate: int | None = None
    data_bits: int | None = None
    parity: str | None = None
    stop_bits: int | None = None
    newline: str | None = None
    console_history: int | None = None
    metrics_history: int | None = None

    class Config:
        extra = "forbid"


MOVEABS_LIMITS: Dict[str, Tuple[int, int]] = {
    # Soft limits enforced by the Teensy after a successful homing sequence
    "x": (0, 2100),
    "z": (-11500, -50),
    "p": (-255, 255),
}
AXIS_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


class MoveAbsRequest(BaseModel):
    x: int | None = None
    z: int | None = None
    p: int | None = None
    r: int | None = None

    @model_validator(mode="after")
    def _validate_targets(self) -> "MoveAbsRequest":
        if not any(getattr(self, axis) is not None for axis in ("x", "z", "p", "r")):
            raise ValueError("At least one axis target is required")
        for axis, (lo, hi) in MOVEABS_LIMITS.items():
            val = getattr(self, axis)
            if val is None:
                continue
            if not (lo <= int(val) <= hi):
                raise ValueError(f"{axis} target must be between {lo} and {hi}")
        return self


class StopRequest(BaseModel):
    axis: Optional[str] = None

    @validator("axis")
    def _validate_axis(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        token = value.strip()
        if not token:
            return None
        if not AXIS_TOKEN_RE.match(token):
            raise ValueError("axis must be 1-8 alphanumeric characters with no spaces")
        return token


class RebootRequest(BaseModel):
    axis: str


def _validate_axis_token(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    token = value.strip()
    if not token:
        return None
    if not AXIS_TOKEN_RE.match(token):
        raise ValueError("axis must be 1-8 alphanumeric characters with no spaces")
    return token.lower()


class MaxVelocityRequest(BaseModel):
    axis: Optional[str] = None
    sps: Optional[int] = None

    @validator("axis")
    def _axis(cls, value: Optional[str]) -> Optional[str]:
        return _validate_axis_token(value)

    @validator("sps")
    def _sps(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if not (0 <= int(value) <= 1000):
            raise ValueError("sps must be between 0 and 1000")
        return int(value)


class MaxAccelRequest(BaseModel):
    axis: Optional[str] = None
    sps2: Optional[int] = None

    @validator("axis")
    def _axis(cls, value: Optional[str]) -> Optional[str]:
        return _validate_axis_token(value)

    @validator("sps2")
    def _sps2(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if int(value) < 1:
            raise ValueError("sps2 must be at least 1")
        return int(value)


def _parse_axis_token(line: str) -> Optional[str]:
    # Extract first token (before whitespace or colon), normalize lowercase and strip trailing ':'
    line = line.lstrip()
    if not line:
        return None
    token = ""
    for ch in line:
        if ch.isspace() or ch == ":":
            break
        token += ch
    token = token.strip().rstrip(":").lower()
    return token or None


def _resolve_axis(token: Optional[str], axis_map: Dict[str, str]) -> Optional[str]:
    if not token:
        return None
    target = axis_map.get(token)
    if target in {"r", "z", "x1", "x2"}:
        return target
    return None


def _latest_console_line(prefixes: tuple[str, ...]) -> Optional[str]:
    console_buffer: ConsoleBuffer = app.state.console_buffer
    snapshot = console_buffer.snapshot()
    lowered = tuple(p.lower() for p in prefixes)
    for line in reversed(snapshot):
        text = line.lstrip().lower()
        if any(text.startswith(pref) for pref in lowered):
            return line
    return None


def _resolve_real_axis_id(raw: Optional[str]) -> str:
    if raw is None:
        raise HTTPException(status_code=422, detail="axis is required")
    token = raw.strip().lower()
    if not token:
        raise HTTPException(status_code=422, detail="axis is required")
    if not AXIS_TOKEN_RE.match(token):
        raise HTTPException(status_code=422, detail="axis must be 1-8 alphanumeric characters")
    if token in {"x", "p"}:
        raise HTTPException(status_code=422, detail="axis must be a physical axis (r, z, x1, x2)")
    settings_manager: SettingsManager = app.state.settings_manager
    axis_map = settings_manager.get().axis_map
    if token in {"r", "z", "x1", "x2"}:
        return token
    axis = axis_map.get(token)
    if axis in {"r", "z", "x1", "x2"}:
        return axis
    raise HTTPException(status_code=422, detail="Unknown axis label")


def _latest_driver_block(axis_id: str, keywords: tuple[str, ...]) -> Optional[list[str]]:
    console_buffer: ConsoleBuffer = app.state.console_buffer
    settings_manager: SettingsManager = app.state.settings_manager
    axis_map = settings_manager.get().axis_map
    snapshot = console_buffer.snapshot()
    marker = "*************************"

    block: list[str] = []
    collecting = False

    for line in reversed(snapshot):
        axis_token = _parse_axis_token(line)
        resolved = _resolve_axis(axis_token, axis_map)
        if resolved != axis_id:
            continue

        if marker in line:
            if collecting:
                block.append(line)
                block.reverse()
                lowered_block = [ln.lower() for ln in block]
                if any(kw in ln for ln in lowered_block for kw in keywords):
                    return block
                block = []
                collecting = False
            else:
                collecting = True
                block = [line]
            continue

        if collecting:
            block.append(line)

    return None


async def _wait_for_driver_block(
    axis_id: str,
    keywords: tuple[str, ...],
    baseline: Optional[list[str]] = None,
    timeout: float = 0.75,
    poll_interval: float = 0.05,
) -> Optional[list[str]]:
    """
    Wait briefly for a new driver block to arrive, preferring fresh data after a refresh request.
    Falls back to the baseline block if nothing newer shows up before the timeout.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    block = _latest_driver_block(axis_id, keywords)

    while True:
        if block and (baseline is None or block != baseline):
            return block
        if asyncio.get_running_loop().time() >= deadline:
            return block if block else baseline
        await asyncio.sleep(poll_interval)
        block = _latest_driver_block(axis_id, keywords)


async def _consume_uart_lines() -> None:
    queue: "asyncio.Queue[str]" = app.state.line_queue
    console_buffer: ConsoleBuffer = app.state.console_buffer
    metrics_buffer: MetricsBuffer = app.state.metrics_buffer
    ws_manager: WebSocketManager = app.state.ws_manager
    axis_ws: Dict[str, WebSocketManager] = app.state.axis_ws
    axis_buffers: Dict[str, Tuple[ConsoleBuffer, MetricsBuffer]] = app.state.axis_buffers
    settings_manager: SettingsManager = app.state.settings_manager

    while True:
        line = await queue.get()
        console_buffer.append(line)

        # Determine axis (if any) by first token using current axis_map
        axis_token = _parse_axis_token(line)
        axis_id = _resolve_axis(axis_token, settings_manager.get().axis_map)

        # Parse metrics for global + per-axis
        metrics = parse_metrics(line)
        metrics_payload: Dict[str, Any] | None = None
        if metrics:
            metrics_buffer.append(metrics)
            metrics_payload = metrics_buffer.latest()

        # Always broadcast to legacy global stream
        message: Dict[str, Any] = {"type": "console", "line": line}
        if metrics_payload:
            message["metrics"] = metrics_payload
        await ws_manager.broadcast(message)

        # Deliver to axis-specific streams
        if axis_id and axis_id in axis_buffers:
            axis_console, axis_metrics = axis_buffers[axis_id]
            axis_console.append(line)
            axis_payload = None
            if metrics:
                axis_metrics.append(metrics)
                axis_payload = axis_metrics.latest()
            axis_msg: Dict[str, Any] = {"type": "console", "line": line}
            if axis_payload:
                axis_msg["metrics"] = axis_payload
            await axis_ws[axis_id].broadcast(axis_msg)
        else:
            # Unknown or unlabeled: send to all axis panels
            for ax in ("r", "z", "x1", "x2"):
                if ax in axis_buffers:
                    await axis_ws[ax].broadcast({"type": "console", "line": line})


@app.on_event("startup")
async def on_startup() -> None:
    loop = asyncio.get_running_loop()
    settings_manager = SettingsManager(CONFIG_PATH)
    settings = settings_manager.get()
    console_buffer = ConsoleBuffer(settings.console_history)
    metrics_buffer = MetricsBuffer(max_samples=settings.metrics_history * 10)
    ws_manager = WebSocketManager()
    line_queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=4096)

    uart_manager = UARTManager(loop=loop, line_queue=line_queue, settings=settings)

    app.state.loop = loop
    app.state.settings_manager = settings_manager
    app.state.console_buffer = console_buffer
    app.state.metrics_buffer = metrics_buffer
    app.state.ws_manager = ws_manager
    app.state.line_queue = line_queue
    app.state.uart_manager = uart_manager

    # Per-axis buffers and websocket managers
    axes = ("r", "z", "x1", "x2")
    app.state.axis_buffers = {ax: (ConsoleBuffer(settings.console_history), MetricsBuffer(max_samples=settings.metrics_history * 10)) for ax in axes}
    app.state.axis_ws = {ax: WebSocketManager() for ax in axes}

    consumer_task = asyncio.create_task(_consume_uart_lines())
    app.state.consumer_task = consumer_task

    uart_manager.start()

    LOGGER.info("Startup complete")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    LOGGER.info("Shutting down")
    consumer_task: asyncio.Task[Any] = app.state.consumer_task
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    uart_manager: UARTManager = app.state.uart_manager
    uart_manager.stop()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/settings")
async def get_settings() -> AppSettings:
    settings_manager: SettingsManager = app.state.settings_manager
    return settings_manager.get()


@app.post("/api/settings")
async def update_settings(payload: SettingsUpdate) -> AppSettings:
    settings_manager: SettingsManager = app.state.settings_manager
    console_buffer: ConsoleBuffer = app.state.console_buffer
    metrics_buffer: MetricsBuffer = app.state.metrics_buffer
    uart_manager: UARTManager = app.state.uart_manager
    axis_buffers: Dict[str, Tuple[ConsoleBuffer, MetricsBuffer]] = app.state.axis_buffers

    updates = payload.dict(exclude_unset=True)
    new_settings = settings_manager.update(updates)

    if "console_history" in updates:
        snapshot = console_buffer.snapshot()
        new_buffer = ConsoleBuffer(new_settings.console_history)
        for line in snapshot[-new_settings.console_history :]:
            new_buffer.append(line)
        app.state.console_buffer = new_buffer
        console_buffer = new_buffer

        # Recreate per-axis console buffers with new size
        for ax, (ax_console, ax_metrics) in list(axis_buffers.items()):
            ax_snap = ax_console.snapshot()
            ax_new_console = ConsoleBuffer(new_settings.console_history)
            for line in ax_snap[-new_settings.console_history :]:
                ax_new_console.append(line)
            axis_buffers[ax] = (ax_new_console, ax_metrics)
        app.state.axis_buffers = axis_buffers

    if "metrics_history" in updates:
        history = metrics_buffer.history()
        max_samples = max(new_settings.metrics_history * 10, 1)
        new_metrics_buffer = MetricsBuffer(max_samples=max_samples)
        for sample in history[-max_samples:]:
            payload_sample = {k: v for k, v in sample.items() if k != "time"}
            new_metrics_buffer.append(payload_sample)
        app.state.metrics_buffer = new_metrics_buffer
        metrics_buffer = new_metrics_buffer

        # Recreate per-axis metric buffers
        for ax, (ax_console, ax_metrics) in list(axis_buffers.items()):
            ax_hist = ax_metrics.history()
            ax_new_metrics = MetricsBuffer(max_samples=max_samples)
            for sample in ax_hist[-max_samples:]:
                payload_sample = {k: v for k, v in sample.items() if k != "time"}
                ax_new_metrics.append(payload_sample)
            axis_buffers[ax] = (ax_console, ax_new_metrics)
        app.state.axis_buffers = axis_buffers

    uart_manager.update_settings(new_settings)

    return new_settings


@app.post("/api/command")
async def send_command(request: CommandRequest) -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    settings_manager: SettingsManager = app.state.settings_manager
    try:
        # Intercept setname commands to update axis label map
        _maybe_update_axis_map(settings_manager, request.command)
        await uart_manager.send_command(request.command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok"}


def _format_moveabs_command(payload: MoveAbsRequest) -> str:
    parts = ["moveabs"]
    for axis in ("x", "z", "p", "r"):
        value = getattr(payload, axis)
        if value is None:
            continue
        parts.extend([axis, str(int(value))])
    return " ".join(parts)


def _format_axis_value_command(base: str, axis: Optional[str], value: Optional[int]) -> str:
    parts = [base]
    if axis:
        parts.append(axis.lower())
    if value is not None:
        parts.append(str(int(value)))
    return " ".join(parts)


@app.post("/api/moveabs")
async def moveabs(payload: MoveAbsRequest) -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    command = _format_moveabs_command(payload)
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


@app.post("/api/coordstatus")
async def coordstatus() -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    command = "coordstatus"
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


@app.get("/api/coordstatus")
async def coordstatus_get(refresh: bool = False) -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    if refresh:
        try:
            await uart_manager.send_command("coordstatus")
        except UARTNotReadyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    line = _latest_console_line(("coord",))
    return {"status": "ok", "line": line}


@app.post("/api/pos")
async def pos() -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    command = "pos"
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


@app.get("/api/pos")
async def pos_get(refresh: bool = False) -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    if refresh:
        try:
            await uart_manager.send_command("pos")
        except UARTNotReadyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    line = _latest_console_line(("pos",))
    return {"status": "ok", "line": line}


@app.post("/api/maxvelocity")
async def maxvelocity(payload: MaxVelocityRequest) -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    command = _format_axis_value_command("maxvelocity", payload.axis, payload.sps)
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


@app.post("/api/maxaccel")
async def maxaccel(payload: MaxAccelRequest) -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    command = _format_axis_value_command("maxaccel", payload.axis, payload.sps2)
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


@app.post("/api/stop")
async def stop(payload: StopRequest) -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    axis = payload.axis
    command = "stop" if not axis else f"stop {axis}"
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


@app.post("/api/home")
async def home() -> Dict[str, Any]:
    uart_manager: UARTManager = app.state.uart_manager
    command = "home z"
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


@app.post("/api/reboot")
async def reboot(payload: RebootRequest) -> Dict[str, Any]:
    axis_id = _resolve_real_axis_id(payload.axis)
    uart_manager: UARTManager = app.state.uart_manager
    command = f"reboot {axis_id}"
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


@app.websocket("/ws/console")
async def websocket_console(websocket: WebSocket) -> None:
    ws_manager: WebSocketManager = app.state.ws_manager
    console_buffer: ConsoleBuffer = app.state.console_buffer
    metrics_buffer: MetricsBuffer = app.state.metrics_buffer
    uart_manager: UARTManager = app.state.uart_manager

    connection = await ws_manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "type": "init",
                "console": console_buffer.snapshot(),
                "settings": app.state.settings_manager.get().dict(),
                "metrics": metrics_buffer.history(),
                "uartReady": uart_manager.is_ready(),
            }
        )
        while True:
            message = await websocket.receive_text()
            # Treat any incoming text as a console command.
            _maybe_update_axis_map(app.state.settings_manager, message)
            await uart_manager.send_command(message)
    except WebSocketDisconnect:
        LOGGER.info("WebSocket client disconnected")
    except UARTNotReadyError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
    finally:
        await ws_manager.disconnect(connection)


def _normalize_axis_id(raw: str) -> Optional[str]:
    v = raw.strip().lower()
    if v in {"r", "z", "x1", "x2"}:
        return v
    return None


def _maybe_update_axis_map(settings_manager: SettingsManager, command: str) -> None:
    try:
        text = (command or "").strip()
        if not text:
            return
        tokens = text.split()
        if not tokens:
            return
        # Patterns supported:
        # 1) setname <axis> <label>
        # 2) <axis> setname <label>
        if tokens[0].lower() == "setname" and len(tokens) >= 3:
            axis = _normalize_axis_id(tokens[1])
            label = tokens[2]
        elif len(tokens) >= 3 and _normalize_axis_id(tokens[0]) and tokens[1].lower() == "setname":
            axis = _normalize_axis_id(tokens[0])
            label = tokens[2]
        else:
            return
        if not axis or not label:
            return
        raw_map = settings_manager.get().axis_map
        new_map = dict(raw_map)
        new_map[label.strip().rstrip(":").lower()] = axis
        # Persist update
        settings_manager.update({"axis_map": new_map})
        LOGGER.info("Updated axis label map: %s -> %s", label, axis)
    except Exception as exc:
        LOGGER.warning("Failed to update axis map from command: %s", exc)


@app.websocket("/ws/axis/{axis_id}")
async def websocket_axis(websocket: WebSocket, axis_id: str) -> None:
    axis = _normalize_axis_id(axis_id)
    if not axis:
        await websocket.close(code=1008)
        return
    axis_ws: Dict[str, WebSocketManager] = app.state.axis_ws
    axis_buffers: Dict[str, Tuple[ConsoleBuffer, MetricsBuffer]] = app.state.axis_buffers
    uart_manager: UARTManager = app.state.uart_manager
    console_buffer, metrics_buffer = axis_buffers[axis]
    manager = axis_ws[axis]

    connection = await manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "type": "init",
                "axis": axis,
                "console": console_buffer.snapshot(),
                "settings": app.state.settings_manager.get().dict(),
                "metrics": metrics_buffer.history(),
                "uartReady": uart_manager.is_ready(),
            }
        )
        while True:
            message = await websocket.receive_text()
            _maybe_update_axis_map(app.state.settings_manager, message)
            await uart_manager.send_command(message)
    except WebSocketDisconnect:
        LOGGER.info("Axis WebSocket client disconnected [%s]", axis)
    except UARTNotReadyError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
    finally:
        await manager.disconnect(connection)


@app.get("/api/driverstatus")
async def driverstatus(axis: str, refresh: bool = False) -> Dict[str, Any]:
    axis_id = _resolve_real_axis_id(axis)
    uart_manager: UARTManager = app.state.uart_manager
    keywords = ("hardware_disabled", "status.")
    baseline_block = _latest_driver_block(axis_id, keywords)
    command = f"driverstatus {axis_id}"
    if refresh:
        try:
            await uart_manager.send_command(command)
        except UARTNotReadyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        block = await _wait_for_driver_block(axis_id, keywords, baseline_block)
    else:
        block = baseline_block
    return {"status": "ok", "axis": axis_id, "lines": block}


class DriverSettingsToggleRequest(BaseModel):
    axis: str
    state: str

    @validator("state")
    def _state(cls, value: str) -> str:
        if value.lower() not in {"enable", "disable"}:
            raise ValueError("state must be 'enable' or 'disable'")
        return value.lower()


@app.get("/api/driversettings")
async def driversettings(axis: str, refresh: bool = False) -> Dict[str, Any]:
    axis_id = _resolve_real_axis_id(axis)
    uart_manager: UARTManager = app.state.uart_manager
    keywords = ("settings.",)
    baseline_block = _latest_driver_block(axis_id, keywords)
    command = f"driversettings {axis_id}"
    if refresh:
        try:
            await uart_manager.send_command(command)
        except UARTNotReadyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        block = await _wait_for_driver_block(axis_id, keywords, baseline_block)
    else:
        block = baseline_block
    return {"status": "ok", "axis": axis_id, "lines": block}


@app.post("/api/driversettings")
async def driversettings_toggle(payload: DriverSettingsToggleRequest) -> Dict[str, Any]:
    axis_id = _resolve_real_axis_id(payload.axis)
    uart_manager: UARTManager = app.state.uart_manager
    command = f"driversettings {axis_id} {payload.state}"
    try:
        await uart_manager.send_command(command)
    except UARTNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "command": command}


__all__ = ["app"]
