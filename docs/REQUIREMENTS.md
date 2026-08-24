# Control Requirements

## Verified project hardware

### Control host

- **Raspberry Pi 4B**.
- **RAM used in the documented deployment:** 2 GB.
- **Serial interface:** Raspberry Pi primary UART exposed as `/dev/serial0` in the application defaults.
- **Connected controller:** Teensy 4.1 Serial8 mirror.
- **UART settings:** 1,000,000 baud, 8N1, LF newline.

The repository does not establish a lower CPU model, RAM minimum, storage minimum, or alternate SBC as tested. Raspberry Pi 4B 2 GB is therefore the verified baseline rather than a claimed minimum.

### Networking

A local IP network is required only for browser/API access. Ethernet vs Wi-Fi is not constrained by code, and no specific adapter/router is documented. The service binds to a configurable host/port and is intended for a trusted LAN.

### GPU/accelerator

No GPU or hardware accelerator requirement exists for this FastAPI service. Browser rendering requirements belong to `ScanBot3000-kinematics`.

## Software

### Operating environment

The deployment scripts assume a Linux userspace with:

- Python and `venv`.
- systemd for the optional service template.
- serial-device permissions/groups such as `dialout`/`tty`.
- `iptables` only if the optional 8000→8001 redirect script is used.

Existing setup notes target Raspberry Pi/Debian-family commands, but the exact tested Raspberry Pi OS release is not recorded and is intentionally not invented here.

### Python

README history specifies **Python 3.10+**. Runtime dependencies currently declare:

- `fastapi>=0.110`
- `uvicorn[standard]>=0.25`
- `pyserial>=3.5`
- `pydantic>=2.5`

No lockfile is present, so exact dependency versions are not reproducibly pinned by this repository.

### Browser

The built-in control dashboard uses standard browser JavaScript/CSS plus vendored uPlot assets. No browser/version minimum has been recorded.

## Recommended configuration

No higher-spec Raspberry Pi or alternate deployment host has been verified as a project recommendation. Use the documented Raspberry Pi 4B setup for the closest reproduction of the existing system, or test alternatives explicitly.
