# ScanBot3000 Control Setup

This guide uses only environment and hardware assumptions evidenced by the repository. The exact Raspberry Pi OS release used during development is not recorded.

## 1. Hardware

The established host is a **Raspberry Pi 4B (2 GB)** connected to the Teensy 4.1 Serial8 mirror.

Documented UART wiring:

- Pi GPIO14 / TXD → Teensy pin 34 / RX8.
- Pi GPIO15 / RXD ← Teensy pin 35 / TX8.
- Common ground between Pi and Teensy.
- UART configuration: 1,000,000 baud, 8 data bits, no parity, 1 stop bit, LF newline.

## 2. Enable the Raspberry Pi UART

On a Raspberry Pi Linux image that provides `raspi-config`:

```bash
sudo raspi-config
```

Disable the serial login shell and enable the hardware serial port, then reboot. Distribution-specific UART naming/configuration can vary; the application default is `/dev/serial0`.

## 3. Install software

The existing deployment instructions use Debian-family package commands:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
```

The README historically required Python 3.10+; the repository does not record a narrower tested interpreter release.

## 4. Clone and create a virtual environment

```bash
git clone https://github.com/DreamMakers2/ScanBot3000-control.git
cd ScanBot3000-control
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 5. Configure

```bash
cp .env.example .env
```

Edit `.env` locally if your serial device or server port differs. `.env` and the runtime `config/settings.json` are intentionally ignored and must not be committed.

## 6. Run directly

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Open `http://<host>:8001/` from a browser on the same trusted network.

Confirm the dashboard loads before enabling motor drivers. With firmware connected, verify telemetry and use `coordstatus`/`pos` before motion commands.

## 7. Optional startup helper

`scripts/start-teensy-console.sh` creates/updates the virtual environment and starts Uvicorn using `.env` overrides.

```bash
./scripts/start-teensy-console.sh
```

## 8. Optional systemd deployment

`scripts/scanbot3000-control.service` is a **template**, not a machine-specific unit. Before installing it, edit `WorkingDirectory`, `EnvironmentFile`, `ExecStart`, `User`, and `Group` for your host. Do not commit those local edits back to the public repository.

Then install and enable the edited copy using normal systemd commands.

The `scanbot` user/path shown in the template are examples, not a verified default account.

## 9. Optional port redirect

`scripts/port-proxy-8000.sh` can redirect TCP port 8000 to 8001 using `iptables`. This requires root privileges and is Linux-specific. It does not add authentication.

## 10. Connect the kinematics client

Serve `ScanBot3000-kinematics` separately and configure it to use this host's `/api` endpoint. Keep both browser and API on a trusted network.
