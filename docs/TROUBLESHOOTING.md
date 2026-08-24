# Control Troubleshooting

Only issues supported by code, existing documentation, or project history are included.

## `/dev/serial0` cannot be opened

Verify that the serial login shell is disabled, the hardware UART is enabled, the service user has serial permissions, and no other process owns the device. Check the actual device name on your Linux image rather than committing a host-specific path.

## Console data is corrupt or intermittent

The established link runs at 1,000,000 baud. Verify both endpoints, common ground, short/reliable wiring, and 8N1 settings. Firmware project history includes serial/link-timeout tuning, so fix physical/configuration errors before increasing timeouts.

## Service starts but no telemetry appears

The UART manager is designed to reconnect. Confirm the Teensy is powered, firmware is running, and the configured serial device matches the Pi's UART. Use the Teensy USB console to separate firmware/link problems from FastAPI issues.

## `moveabs` returns a validation error

The server enforces X/Z/P ranges that mirror the firmware's documented soft limits. The firmware additionally requires homing for X/Z/P. Use `coordstatus` and `pos` to determine current state.

## Browser requests are rejected by CORS

The code allows localhost and common private-address origins. A custom hostname/domain is not automatically allowed by the current regex. Prefer a controlled reverse proxy/origin policy rather than broadening CORS without considering the unauthenticated motion-control surface.

## systemd unit fails after copying

The provided unit is intentionally a template. Edit its path and user/group values for the deployment host before installation. The repository does not commit a real developer home directory.
