# API Reference

FastAPI service for Teensy console bridging. All endpoints are unauthenticated and intended for local network access. The default port is `8001`; use `scripts/port-proxy-8000.sh apply` if you want requests to `:8000` forwarded to `:8001` via iptables.

## General Notes
- Content type: JSON for all REST calls (`Content-Type: application/json`).
- Axis tokens must be 1-8 alphanumeric characters (`setname` uses the same rules). They are normalized to lowercase by the server.
- Driver/TMC endpoints only accept physical axes (`r`, `z`, `x1`, `x2`) or their renamed labels (no virtual `x`/`p`).
- Soft limits enforced on `moveabs` before sending to the Teensy: `x` 0..2100, `z` -11500..-50, `p` -255..255. `r` is unrestricted. Homing is still required for X/Z/P on the firmware side.
- The UART mirror runs on `/dev/serial0` at 1,000,000 baud with `\n` newlines. The server forwards exactly the same ASCII commands the Teensy USB console accepts.
- CORS is open to typical local network origins (localhost, 10.x/192.168.x/172.16-31 ranges).

## Endpoints

### GET /api/settings
Returns the current settings (see `app/settings.py` for fields). Useful to pre-fill the web UI.

### POST /api/settings
Partial update of settings. Unknown keys are rejected. `console_history` and `metrics_history` resize in-memory buffers; UART settings are handed to the UART manager immediately. Example:
```bash
curl -X POST http://<host>:8001/api/settings \
  -H 'Content-Type: application/json' \
  -d '{"console_history":800,"metrics_history":600,"axis_map":{"vertical":"z"}}'
```

### POST /api/command
Send a raw console command string. `setname` commands update the persistent `axis_map` automatically. Example: `{"command":"moveto z 180"}`.

### POST /api/moveabs
Coordinated absolute move helper. Body accepts any subset of `x`, `z`, `p`, `r` targets (integers). At least one axis is required; values outside the soft limits above are rejected. Response echoes the command string sent to UART.

### POST /api/coordstatus
Sends `coordstatus` to the Teensy.

### GET /api/coordstatus?refresh=1
Returns the latest `coordstatus` console line from the buffer. `refresh=1` also issues a new `coordstatus` command before reading.

### POST /api/pos
Sends `pos` to the Teensy.

### GET /api/pos?refresh=1
Returns the latest `pos` console line from the buffer. `refresh=1` also issues a new `pos` command before reading.

### POST /api/maxvelocity
Query or set maximum velocity. Payload: `{ "axis": "<optional>", "sps": <optional int 0-1000> }`. Omitting `sps` performs a query. Axis tokens are normalized and validated.

### POST /api/maxaccel
Query or set maximum acceleration. Payload: `{ "axis": "<optional>", "sps2": <optional int>=1 }`. Omitting `sps2` performs a query. Axis tokens are normalized and validated.

### POST /api/stop
Stop helper. Optional payload `{ "axis": "<label>" }` sends `stop <axis>`; empty body performs a global stop. Axis tokens must be 1–8 alphanumeric characters.

### POST /api/home
Trigger Z homing. Sends `home z` to the console. Requires the Z limit switch to be pressed.

### POST /api/reboot
Reboot a specific axis controller. Payload: `{ "axis": "<r|z|x1|x2|label>" }`.

### GET /api/driverstatus?axis=<axis>&refresh=1
Runs `driverstatus <axis>` when `refresh=1` and returns the latest driver status block (same structure as `tmcstatus`, between `*************************` markers) for the requested physical axis. `axis` must resolve to `r`, `z`, `x1`, or `x2`.

### GET /api/driversettings?axis=<axis>&refresh=1
Runs `driversettings <axis>` when `refresh=1` and returns the latest driver settings block (same structure as `tmcsettings`, between `*************************` markers) for the requested physical axis.

### POST /api/driversettings
Toggle a driver via `driversettings <axis> enable|disable`. Payload: `{ "axis": "<r|z|x1|x2|label>", "state": "enable|disable" }`. Uses the same physical-axis validation as `driverstatus`.

### WebSockets
- `WS /ws/console` – combined stream. Initial payload includes `console`, `settings`, `metrics`, and `uartReady`. Subsequent messages carry console lines and parsed metrics. Sending text writes raw commands to UART (same as `/api/command`).
- `WS /ws/axis/{axis_id}` – per-axis stream for `r|z|x1|x2`. Initial payload mirrors the combined socket but scoped to that axis. Sending text writes commands scoped to that axis.

## cURL Examples
```bash
# Send a coordinated move (with soft-limit validation)
curl -X POST http://<host>:8001/api/moveabs \
  -H 'Content-Type: application/json' \
  -d '{"x":100,"z":-120,"p":0}'

# Query current positions (fresh read)
curl 'http://<host>:8001/api/pos?refresh=1'

# Set per-axis velocity cap
curl -X POST http://<host>:8001/api/maxvelocity \
  -H 'Content-Type: application/json' \
  -d '{"axis":"z","sps":80}'

# Global emergency stop
curl -X POST http://<host>:8001/api/stop -H 'Content-Type: application/json' -d '{}'

# Fetch the latest driver status block (force refresh)
curl 'http://<host>:8001/api/driverstatus?axis=z&refresh=1'

# Disable a driver
curl -X POST http://<host>:8001/api/driversettings \
  -H 'Content-Type: application/json' \
  -d '{"axis":"z","state":"disable"}'

# Home the Z axis
curl -X POST http://<host>:8001/api/home

# Reboot a single axis controller
curl -X POST http://<host>:8001/api/reboot \
  -H 'Content-Type: application/json' \
  -d '{"axis":"z"}'
```
